"""
Paper Trader — Live paper trading with real Bybit data and virtual execution.
Uses only public endpoints (no API keys). Rich console dashboard.
"""

import time
from datetime import datetime, timezone

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

from engine.risk_manager import RiskManager
from engine.signal_generator import SignalGenerator, SignalType
from engine.virtual_exchange import PositionSide, VirtualExchange
from utils.data_fetcher import fetch_ohlcv, fetch_funding_rate, fetch_ticker, get_exchange
from utils.indicators import add_all_indicators


console = Console()


class PaperTrader:
    """
    Real-time paper trading engine with rich dashboard:
    - Fetches live prices from Bybit (public, no API key)
    - Generates signals using the same strategy as backtester
    - Executes on virtual exchange with realistic fees/slippage
    - Displays live dashboard with positions, PnL, risk state
    """

    def __init__(self, config):
        self.config = config
        self.exchange = VirtualExchange(config)
        self.risk_mgr = RiskManager(config)
        self.signal_gen = SignalGenerator(config)
        self.ccxt_exchange = get_exchange()
        self.iteration = 0
        self.start_time = datetime.now(timezone.utc)
        self._last_day = self.start_time.date()
        self._last_week = self.start_time.isocalendar()[1]
        self._current_prices: dict[str, float] = {}
        self._event_log: list[str] = []
        self._signals_checked = 0
        self._errors = 0

    def run(self, duration_minutes: int = 60, interval_seconds: int = 60):
        """
        Run paper trading for a specified duration.

        Args:
            duration_minutes: How long to run (default 60 min)
            interval_seconds: How often to check for signals (default 60s)
        """
        self._print_banner(duration_minutes, interval_seconds)
        end_time = time.time() + duration_minutes * 60

        try:
            while time.time() < end_time:
                self.iteration += 1
                self._tick()
                self._render_dashboard(duration_minutes)

                # Check if target reached
                if self.exchange.equity >= self.config.TARGET_BALANCE:
                    self._log("TARGET REACHED!", style="bold green")
                    break

                # Check kill switch
                can_trade, reason = self.risk_mgr.can_trade()
                if not can_trade and "KILL" in reason:
                    self._log(f"HALTED: {reason}", style="bold red")
                    break

                # Auto-save every 10 iterations
                if self.iteration % 10 == 0:
                    self.exchange.save_trades()

                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            self._log("Stopped by user (Ctrl+C)")

        self._print_final_report()

    def _tick(self):
        """Single iteration: fetch data, check signals, manage positions."""
        # Daily/weekly risk reset
        now = datetime.now(timezone.utc)
        if now.date() != self._last_day:
            self.risk_mgr.new_day()
            self._last_day = now.date()
            self._log("New day — daily risk counters reset")
        current_week = now.isocalendar()[1]
        if current_week != self._last_week:
            self.risk_mgr.new_week()
            self._last_week = current_week
            self._log("New week — weekly risk counters reset")

        # Fetch current prices
        self._current_prices = {}
        for symbol in self.config.TRADING_PAIRS:
            try:
                ticker = fetch_ticker(symbol, self.ccxt_exchange)
                if ticker and "last" in ticker:
                    self._current_prices[symbol] = ticker["last"]
            except Exception:
                self._errors += 1

        if not self._current_prices:
            self._log("No prices fetched — network issue?", style="yellow")
            return

        # Fetch funding rates
        funding_rates = {}
        for symbol in self.config.TRADING_PAIRS:
            try:
                funding_rates[symbol] = fetch_funding_rate(symbol, self.ccxt_exchange)
            except Exception:
                pass

        # Check time stops (real-time based)
        self._check_time_stops()

        # Update positions with current prices
        self.exchange.update_positions(self._current_prices, funding_rates)

        # Sync risk state
        self.risk_mgr.state.equity = self.exchange.equity
        if self.exchange.equity > self.risk_mgr.state.peak_equity:
            self.risk_mgr.state.peak_equity = self.exchange.equity

        # Record closed trades
        while len(self.exchange.trade_history) > self.risk_mgr.state.total_trades:
            idx = self.risk_mgr.state.total_trades
            trade = self.exchange.trade_history[idx]
            self.risk_mgr.record_trade(trade.net_pnl, trade.close_reason)
            pnl_color = "green" if trade.net_pnl > 0 else "red"
            self._log(
                f"CLOSED {trade.symbol} {trade.side} "
                f"PnL=${trade.net_pnl:+.2f} ({trade.close_reason})",
                style=pnl_color,
            )

        # Check if can open new positions
        can_trade, reason = self.risk_mgr.can_trade()
        if not can_trade:
            return

        if len(self.exchange.positions) >= self.config.MAX_CONCURRENT_POSITIONS:
            return

        # Check signals for each pair
        for symbol in self.config.TRADING_PAIRS:
            if any(p.symbol == symbol for p in self.exchange.positions.values()):
                continue

            self._signals_checked += 1
            try:
                df = fetch_ohlcv(
                    symbol, self.config.CANDLE_TIMEFRAME, days=7,
                    exchange=self.ccxt_exchange,
                )
            except Exception:
                self._errors += 1
                continue

            if len(df) < 200:
                continue

            signal = self.signal_gen.evaluate_current(df, symbol)
            if signal is None:
                continue

            if signal.confidence < self.config.MIN_CONFIDENCE:
                continue

            # Risk-adjusted sizing
            leverage = min(
                self.risk_mgr.calculate_leverage(signal.volatility_regime),
                signal.leverage,
            )
            position_size = self.risk_mgr.calculate_position_size(
                signal.confidence, signal.entry_price, signal.stop_loss,
            )
            if position_size <= 1:
                continue

            side = PositionSide.LONG if signal.signal_type == SignalType.LONG else PositionSide.SHORT

            pos = self.exchange.open_position(
                symbol=symbol,
                side=side,
                size_usd=position_size,
                entry_price=signal.entry_price,
                leverage=leverage,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            )

            if pos:
                self._log(
                    f"OPEN {signal.signal_type.value} {symbol} "
                    f"@ ${signal.entry_price:.2f} | "
                    f"Size=${position_size:.2f} Lev={leverage}x | "
                    f"SL={signal.stop_loss:.2f} TP={signal.take_profit:.2f} | "
                    f"Conf={signal.confidence:.0%} [{signal.reason}]",
                    style="cyan",
                )

    def _check_time_stops(self):
        """Close positions held longer than TIME_STOP_HOURS (real-time)."""
        time_stop_seconds = self.config.TIME_STOP_HOURS * 3600
        now = datetime.now(timezone.utc)
        to_close = []

        for pid, pos in self.exchange.positions.items():
            try:
                open_dt = datetime.fromisoformat(pos.open_time)
                held_seconds = (now - open_dt).total_seconds()
                if held_seconds >= time_stop_seconds:
                    # Only time-stop if position is near breakeven
                    pnl_pct = abs(pos.unrealized_pnl) / pos.margin if pos.margin > 0 else 0
                    if pnl_pct < 0.05:
                        price = self._current_prices.get(pos.symbol, pos.entry_price)
                        to_close.append((pid, price))
            except (ValueError, TypeError):
                pass

        for pid, price in to_close:
            self.exchange.close_position(pid, price, "TIME_STOP")

    def _log(self, message: str, style: str = "white"):
        """Add an event to the log with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._event_log.append(f"[{style}][{ts}] {message}[/{style}]")
        # Keep last 20 events
        if len(self._event_log) > 20:
            self._event_log = self._event_log[-20:]

    def _print_banner(self, duration_minutes: int, interval_seconds: int):
        """Print startup banner."""
        console.clear()
        console.print(Panel(
            f"[bold cyan]PAPER TRADER[/bold cyan] — Live Virtual Trading\n\n"
            f"  Balance:  [green]${self.config.STARTING_BALANCE:.2f}[/green]\n"
            f"  Target:   [yellow]${self.config.TARGET_BALANCE:.2f}[/yellow]\n"
            f"  Pairs:    {', '.join(self.config.TRADING_PAIRS)}\n"
            f"  Duration: {duration_minutes} min | Check every {interval_seconds}s\n"
            f"  Source:   Bybit public API (no keys needed)\n\n"
            f"  [dim]Press Ctrl+C to stop[/dim]",
            title="Crypto Futures Paper Trading",
            border_style="cyan",
        ))
        console.print()

    def _render_dashboard(self, duration_minutes: int):
        """Render the live trading dashboard."""
        console.clear()
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        elapsed_min = elapsed / 60
        remaining = max(0, duration_minutes - elapsed_min)

        # Header
        equity = self.exchange.equity
        pnl = equity - self.config.STARTING_BALANCE
        pnl_pct = (pnl / self.config.STARTING_BALANCE) * 100
        pnl_color = "green" if pnl >= 0 else "red"
        dd = self.risk_mgr.drawdown_pct * 100
        mode = self.risk_mgr.state.mode.value.upper()
        mode_color = {
            "NORMAL": "green", "AGGRESSIVE": "yellow",
            "DEFENSIVE": "red", "HALTED": "bold red",
        }.get(mode, "white")

        header = (
            f"[bold]PAPER TRADER[/bold]  |  "
            f"Iter: {self.iteration}  |  "
            f"Elapsed: {elapsed_min:.0f}min  |  "
            f"Remaining: {remaining:.0f}min  |  "
            f"Errors: {self._errors}\n"
        )
        console.print(Panel(header, border_style="dim"))

        # Account table
        acct_table = Table(
            title="Account", box=box.ROUNDED, border_style="cyan",
            show_header=False, padding=(0, 1),
        )
        acct_table.add_column("Key", style="dim", width=18)
        acct_table.add_column("Value", width=22)

        acct_table.add_row("Equity", f"[bold]${equity:.2f}[/bold]")
        acct_table.add_row("Balance", f"${self.exchange.balance:.2f}")
        acct_table.add_row("PnL", f"[{pnl_color}]${pnl:+.2f} ({pnl_pct:+.1f}%)[/{pnl_color}]")
        acct_table.add_row("Free Margin", f"${self.exchange.free_margin:.2f}")
        acct_table.add_row("Drawdown", f"{dd:.1f}%")
        acct_table.add_row("Risk Mode", f"[{mode_color}]{mode}[/{mode_color}]")
        acct_table.add_row("Trades", f"{len(self.exchange.trade_history)}")
        acct_table.add_row(
            "Win Rate",
            f"{self.risk_mgr.win_rate * 100:.0f}% "
            f"(PF={self.risk_mgr.profit_factor:.2f})",
        )
        acct_table.add_row(
            "Streaks",
            f"W{self.risk_mgr.state.consecutive_wins} / "
            f"L{self.risk_mgr.state.consecutive_losses}",
        )
        acct_table.add_row("Fees Paid", f"${self.exchange.total_fees_paid:.2f}")
        acct_table.add_row("Signals Checked", f"{self._signals_checked}")

        # Prices table
        price_table = Table(
            title="Live Prices", box=box.ROUNDED, border_style="yellow",
            show_header=True, padding=(0, 1),
        )
        price_table.add_column("Pair", style="bold")
        price_table.add_column("Price", justify="right")
        price_table.add_column("Status")

        for symbol in self.config.TRADING_PAIRS:
            price = self._current_prices.get(symbol)
            price_str = f"${price:,.2f}" if price else "[red]N/A[/red]"
            has_pos = any(p.symbol == symbol for p in self.exchange.positions.values())
            status = "[cyan]IN POSITION[/cyan]" if has_pos else "[dim]watching[/dim]"
            price_table.add_row(symbol, price_str, status)

        console.print(acct_table)
        console.print()
        console.print(price_table)
        console.print()

        # Open Positions table
        if self.exchange.positions:
            pos_table = Table(
                title="Open Positions", box=box.ROUNDED, border_style="magenta",
                show_header=True, padding=(0, 1),
            )
            pos_table.add_column("Symbol", style="bold")
            pos_table.add_column("Side")
            pos_table.add_column("Entry", justify="right")
            pos_table.add_column("Current", justify="right")
            pos_table.add_column("Size", justify="right")
            pos_table.add_column("Lev")
            pos_table.add_column("uPnL", justify="right")
            pos_table.add_column("SL", justify="right")
            pos_table.add_column("TP", justify="right")
            pos_table.add_column("Held")

            now = datetime.now(timezone.utc)
            for pid, pos in self.exchange.positions.items():
                side_color = "green" if pos.side == PositionSide.LONG else "red"
                pnl_color = "green" if pos.unrealized_pnl >= 0 else "red"
                current = self._current_prices.get(pos.symbol, 0)

                try:
                    open_dt = datetime.fromisoformat(pos.open_time)
                    held_min = (now - open_dt).total_seconds() / 60
                    held_str = f"{held_min:.0f}m"
                except (ValueError, TypeError):
                    held_str = "?"

                pos_table.add_row(
                    pos.symbol,
                    f"[{side_color}]{pos.side.value}[/{side_color}]",
                    f"${pos.entry_price:,.2f}",
                    f"${current:,.2f}" if current else "?",
                    f"${pos.size_usd:.2f}",
                    f"{pos.leverage}x",
                    f"[{pnl_color}]${pos.unrealized_pnl:+.2f}[/{pnl_color}]",
                    f"${pos.stop_loss:,.2f}",
                    f"${pos.take_profit:,.2f}",
                    held_str,
                )
            console.print(pos_table)
            console.print()

        # Recent trades table
        recent_trades = self.exchange.trade_history[-5:]
        if recent_trades:
            trade_table = Table(
                title="Recent Trades", box=box.ROUNDED, border_style="blue",
                show_header=True, padding=(0, 1),
            )
            trade_table.add_column("Symbol")
            trade_table.add_column("Side")
            trade_table.add_column("Entry", justify="right")
            trade_table.add_column("Exit", justify="right")
            trade_table.add_column("Net PnL", justify="right")
            trade_table.add_column("Reason")

            for t in recent_trades:
                pnl_color = "green" if t.net_pnl > 0 else "red"
                trade_table.add_row(
                    t.symbol,
                    t.side,
                    f"${t.entry_price:,.2f}",
                    f"${t.exit_price:,.2f}",
                    f"[{pnl_color}]${t.net_pnl:+.2f}[/{pnl_color}]",
                    t.close_reason,
                )
            console.print(trade_table)
            console.print()

        # Event log
        if self._event_log:
            log_text = Text()
            for entry in self._event_log[-10:]:
                console.print(f"  {entry}")
            console.print()

        # Progress bar to target
        progress = min(1.0, max(0.0, (equity - self.config.STARTING_BALANCE) /
                                     (self.config.TARGET_BALANCE - self.config.STARTING_BALANCE)))
        bar_width = 40
        filled = int(bar_width * progress)
        bar_color = "green" if progress > 0 else "red"
        bar = f"[{bar_color}]{'█' * filled}[/{bar_color}][dim]{'░' * (bar_width - filled)}[/dim]"
        console.print(
            f"  Target: ${self.config.STARTING_BALANCE:.0f} {bar} "
            f"${self.config.TARGET_BALANCE:.0f}  "
            f"({progress * 100:.1f}%)"
        )
        console.print(f"\n  [dim]Press Ctrl+C to stop | Auto-saves every 10 iterations[/dim]")

    def _print_final_report(self):
        """Print final session report and save trades."""
        # Close remaining positions at current prices
        if self._current_prices:
            self.exchange.close_all_positions(self._current_prices, "SESSION_END")
        else:
            # Try to fetch one last time
            for symbol in self.config.TRADING_PAIRS:
                try:
                    ticker = fetch_ticker(symbol, self.ccxt_exchange)
                    if ticker and "last" in ticker:
                        self._current_prices[symbol] = ticker["last"]
                except Exception:
                    pass
            if self._current_prices:
                self.exchange.close_all_positions(self._current_prices, "SESSION_END")

        stats = self.exchange.get_performance_stats()

        console.print()
        console.print(Panel(
            "[bold]SESSION COMPLETE[/bold]",
            border_style="cyan",
        ))

        if isinstance(stats, dict) and "total_trades" in stats:
            report = Table(
                title="Final Results",
                box=box.DOUBLE, border_style="green",
                show_header=False, padding=(0, 2),
            )
            report.add_column("Metric", style="bold")
            report.add_column("Value", justify="right")

            pnl_color = "green" if stats['total_pnl'] >= 0 else "red"
            report.add_row("Total Trades", f"{stats['total_trades']}")
            report.add_row("Winning", f"{stats['winning_trades']}")
            report.add_row("Losing", f"{stats['losing_trades']}")
            report.add_row("Win Rate", f"{stats['win_rate']:.1f}%")
            report.add_row("Profit Factor", f"{stats['profit_factor']:.2f}")
            report.add_row("", "")
            report.add_row("Total PnL", f"[{pnl_color}]${stats['total_pnl']:+.2f}[/{pnl_color}]")
            report.add_row("Final Equity", f"${stats['final_equity']:.2f}")
            report.add_row("Return", f"[{pnl_color}]{stats['return_pct']:+.1f}%[/{pnl_color}]")
            report.add_row("Max Drawdown", f"{stats['max_drawdown_pct']:.1f}%")
            report.add_row("Sharpe Ratio", f"{stats['sharpe_ratio']:.2f}")
            report.add_row("", "")
            report.add_row("Avg Win", f"${stats['avg_win']:.2f}")
            report.add_row("Avg Loss", f"${stats['avg_loss']:.2f}")
            report.add_row("Largest Win", f"${stats['largest_win']:.2f}")
            report.add_row("Largest Loss", f"${stats['largest_loss']:.2f}")
            report.add_row("", "")
            report.add_row("Total Fees", f"${stats['total_fees']:.2f}")
            report.add_row("Total Funding", f"${stats['total_funding']:.2f}")

            console.print(report)

            # Close reason breakdown
            reasons = {}
            for t in self.exchange.trade_history:
                reasons[t.close_reason] = reasons.get(t.close_reason, 0) + 1
            if reasons:
                console.print(f"\n  Close reasons: {reasons}")
        else:
            console.print(f"  {stats}")

        # Duration
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60
        console.print(f"  Session duration: {elapsed:.1f} minutes")
        console.print(f"  Iterations: {self.iteration}")
        console.print(f"  Signals checked: {self._signals_checked}")

        self.exchange.save_trades()
        console.print(f"\n  Trade log saved to [bold]{self.config.TRADE_LOG_FILE}[/bold]")
