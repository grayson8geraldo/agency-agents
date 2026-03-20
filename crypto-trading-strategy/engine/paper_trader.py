"""
Paper Trader — Live paper trading with real Bybit data and virtual execution.
Uses only public endpoints (no API keys). Event-driven output (no spam).
"""

import time
from datetime import datetime, timezone

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from engine.risk_manager import RiskManager
from engine.signal_generator import SignalGenerator, SignalType
from engine.virtual_exchange import PositionSide, VirtualExchange
from utils.data_fetcher import fetch_ohlcv, fetch_funding_rate, fetch_ticker, get_exchange


console = Console()


class PaperTrader:
    """
    Real-time paper trading engine:
    - Fetches live prices from Bybit (public, no API key)
    - Runs indefinitely until Ctrl+C
    - Only prints when something happens (trade, signal, error)
    - Periodic status every N minutes
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
        self._prev_prices: dict[str, float] = {}
        self._signals_checked = 0
        self._errors = 0
        self._last_status_time = 0.0

    def run(self, interval_seconds: int = 60, status_interval_minutes: int = 5):
        """
        Run paper trading indefinitely.

        Args:
            interval_seconds: How often to check for signals (default 60s)
            status_interval_minutes: How often to print status summary (default 5 min)
        """
        self._print_banner(interval_seconds)
        self._last_status_time = time.time()

        try:
            while True:
                self.iteration += 1
                events = self._tick()

                # Print events (only if something happened)
                for event in events:
                    console.print(event)

                # Periodic status
                now = time.time()
                if now - self._last_status_time >= status_interval_minutes * 60:
                    self._print_status()
                    self._last_status_time = now

                # Check if target reached
                if self.exchange.equity >= self.config.TARGET_BALANCE:
                    console.print(
                        f"  [bold green]TARGET REACHED![/bold green] "
                        f"Equity: ${self.exchange.equity:.2f}"
                    )
                    break

                # Check kill switch
                can_trade, reason = self.risk_mgr.can_trade()
                if not can_trade and "KILL" in reason:
                    console.print(f"  [bold red]{reason}[/bold red]")
                    break

                # Auto-save every 10 iterations
                if self.iteration % 10 == 0:
                    self.exchange.save_trades()

                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            console.print(f"\n  [dim]Stopped by user (Ctrl+C)[/dim]")

        self._print_final_report()

    def _tick(self) -> list[str]:
        """Single iteration. Returns list of event messages to print."""
        events = []

        # Daily/weekly risk reset
        now = datetime.now(timezone.utc)
        if now.date() != self._last_day:
            self.risk_mgr.new_day()
            self._last_day = now.date()
            events.append(f"  [dim]{self._ts()} New day — daily risk reset[/dim]")
        current_week = now.isocalendar()[1]
        if current_week != self._last_week:
            self.risk_mgr.new_week()
            self._last_week = current_week
            events.append(f"  [dim]{self._ts()} New week — weekly risk reset[/dim]")

        # Fetch current prices
        self._prev_prices = dict(self._current_prices)
        self._current_prices = {}
        for symbol in self.config.TRADING_PAIRS:
            try:
                ticker = fetch_ticker(symbol, self.ccxt_exchange)
                if ticker and "last" in ticker:
                    self._current_prices[symbol] = ticker["last"]
            except Exception:
                self._errors += 1

        if not self._current_prices:
            events.append(f"  [yellow]{self._ts()} No prices — network issue?[/yellow]")
            return events

        # Fetch funding rates
        funding_rates = {}
        for symbol in self.config.TRADING_PAIRS:
            try:
                funding_rates[symbol] = fetch_funding_rate(symbol, self.ccxt_exchange)
            except Exception:
                pass

        # Check time stops (real-time based)
        self._check_time_stops()

        # Track trade count before update
        trades_before = len(self.exchange.trade_history)

        # Update positions with current prices
        self.exchange.update_positions(self._current_prices, funding_rates)

        # Sync risk state
        self.risk_mgr.state.equity = self.exchange.equity
        if self.exchange.equity > self.risk_mgr.state.peak_equity:
            self.risk_mgr.state.peak_equity = self.exchange.equity

        # Record closed trades and report them
        while len(self.exchange.trade_history) > self.risk_mgr.state.total_trades:
            idx = self.risk_mgr.state.total_trades
            trade = self.exchange.trade_history[idx]
            self.risk_mgr.record_trade(trade.net_pnl, trade.close_reason)
            pnl_color = "green" if trade.net_pnl > 0 else "red"
            duration_str = f"{trade.duration_minutes:.0f}m" if trade.duration_minutes > 0 else ""
            events.append(
                f"  [{pnl_color}]{self._ts()} CLOSED {trade.symbol} {trade.side} "
                f"@ ${trade.exit_price:,.2f} | "
                f"PnL=${trade.net_pnl:+.2f} | {trade.close_reason} {duration_str}[/{pnl_color}]"
            )

        # Check if can open new positions
        can_trade, reason = self.risk_mgr.can_trade()
        if not can_trade:
            return events

        if len(self.exchange.positions) >= self.config.MAX_CONCURRENT_POSITIONS:
            return events

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
                events.append(
                    f"  [cyan]{self._ts()} OPEN {signal.signal_type.value} {symbol} "
                    f"@ ${signal.entry_price:,.2f} | "
                    f"Size=${position_size:.2f} Lev={leverage}x | "
                    f"SL=${signal.stop_loss:,.2f} TP=${signal.take_profit:,.2f} | "
                    f"Conf={signal.confidence:.0%} Vol={signal.volatility_regime}[/cyan]"
                )
                events.append(
                    f"  [dim]         Reason: {signal.reason}[/dim]"
                )

        return events

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
                    pnl_pct = abs(pos.unrealized_pnl) / pos.margin if pos.margin > 0 else 0
                    if pnl_pct < 0.05:
                        price = self._current_prices.get(pos.symbol, pos.entry_price)
                        to_close.append((pid, price))
            except (ValueError, TypeError):
                pass

        for pid, price in to_close:
            self.exchange.close_position(pid, price, "TIME_STOP")

    def _ts(self) -> str:
        """Current timestamp string."""
        return datetime.now(timezone.utc).strftime("%H:%M:%S")

    def _print_banner(self, interval_seconds: int):
        """Print startup banner."""
        console.print(Panel(
            f"[bold cyan]PAPER TRADER[/bold cyan] — Live Virtual Trading\n\n"
            f"  Balance:  [green]${self.config.STARTING_BALANCE:.2f}[/green]\n"
            f"  Target:   [yellow]${self.config.TARGET_BALANCE:.2f}[/yellow]\n"
            f"  Pairs:    {', '.join(self.config.TRADING_PAIRS)}\n"
            f"  Interval: every {interval_seconds}s\n"
            f"  Source:   Bybit public API (no keys needed)\n\n"
            f"  [dim]Runs indefinitely. Press Ctrl+C to stop.[/dim]\n"
            f"  [dim]Only prints when something happens.[/dim]",
            title="Crypto Futures Paper Trading",
            border_style="cyan",
        ))
        console.print()

    def _print_status(self):
        """Print periodic status summary — compact, no clear screen."""
        elapsed_min = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60
        equity = self.exchange.equity
        pnl = equity - self.config.STARTING_BALANCE
        pnl_pct = (pnl / self.config.STARTING_BALANCE) * 100
        pnl_color = "green" if pnl >= 0 else "red"
        dd = self.risk_mgr.drawdown_pct * 100
        mode = self.risk_mgr.state.mode.value.upper()
        n_pos = len(self.exchange.positions)
        n_trades = len(self.exchange.trade_history)

        # Prices line
        prices_str = "  ".join(
            f"{s.split('/')[0]}=${p:,.2f}" if p else f"{s.split('/')[0]}=N/A"
            for s, p in ((s, self._current_prices.get(s)) for s in self.config.TRADING_PAIRS)
        )

        console.print()
        console.print(
            f"  [bold]{self._ts()}[/bold] "
            f"[{pnl_color}]Equity=${equity:.2f} ({pnl:+.2f})[/{pnl_color}]  "
            f"DD={dd:.1f}%  Mode={mode}  "
            f"Pos={n_pos}  Trades={n_trades}  "
            f"WR={self.risk_mgr.win_rate * 100:.0f}%  "
            f"Iter={self.iteration}"
        )
        console.print(f"  [dim]{prices_str}[/dim]")

        # Show open positions if any
        if self.exchange.positions:
            now = datetime.now(timezone.utc)
            for pid, pos in self.exchange.positions.items():
                side_color = "green" if pos.side == PositionSide.LONG else "red"
                pnl_c = "green" if pos.unrealized_pnl >= 0 else "red"
                current = self._current_prices.get(pos.symbol, 0)
                try:
                    open_dt = datetime.fromisoformat(pos.open_time)
                    held = f"{(now - open_dt).total_seconds() / 60:.0f}m"
                except (ValueError, TypeError):
                    held = "?"
                console.print(
                    f"    [{side_color}]{pos.side.value:5}[/{side_color}] {pos.symbol} "
                    f"entry=${pos.entry_price:,.2f} now=${current:,.2f} "
                    f"[{pnl_c}]uPnL=${pos.unrealized_pnl:+.2f}[/{pnl_c}] "
                    f"SL=${pos.stop_loss:,.2f} TP=${pos.take_profit:,.2f} "
                    f"({held})"
                )

    def _print_final_report(self):
        """Print final session report and save trades."""
        # Close remaining positions at current prices
        if self._current_prices:
            self.exchange.close_all_positions(self._current_prices, "SESSION_END")
        else:
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
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60

        console.print()
        console.print(Panel("[bold]SESSION COMPLETE[/bold]", border_style="cyan"))

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
            report.add_row("Win Rate", f"{stats['win_rate']:.1f}%")
            report.add_row("Profit Factor", f"{stats['profit_factor']:.2f}")
            report.add_row("Total PnL", f"[{pnl_color}]${stats['total_pnl']:+.2f}[/{pnl_color}]")
            report.add_row("Final Equity", f"${stats['final_equity']:.2f}")
            report.add_row("Return", f"[{pnl_color}]{stats['return_pct']:+.1f}%[/{pnl_color}]")
            report.add_row("Max Drawdown", f"{stats['max_drawdown_pct']:.1f}%")
            report.add_row("Fees", f"${stats['total_fees']:.2f}")
            console.print(report)

            reasons = {}
            for t in self.exchange.trade_history:
                reasons[t.close_reason] = reasons.get(t.close_reason, 0) + 1
            if reasons:
                console.print(f"\n  Close reasons: {reasons}")
        else:
            console.print(f"  {stats}")

        console.print(f"  Duration: {elapsed:.1f} min | Iterations: {self.iteration} | Signals: {self._signals_checked}")

        self.exchange.save_trades()
        console.print(f"  Trade log saved to [bold]{self.config.TRADE_LOG_FILE}[/bold]")
