"""
Paper Trader — Live paper trading using real-time data with virtual execution.
Runs continuously, fetching new candles and executing signals.
"""

import time
from datetime import datetime, timezone

import pandas as pd

from engine.risk_manager import RiskManager
from engine.signal_generator import SignalGenerator, SignalType
from engine.virtual_exchange import PositionSide, VirtualExchange
from utils.data_fetcher import fetch_ohlcv, fetch_funding_rate, fetch_ticker, get_exchange
from utils.indicators import add_all_indicators


class PaperTrader:
    """
    Real-time paper trading engine:
    - Fetches live candle data from Binance
    - Generates signals using the same strategy as backtester
    - Executes on virtual exchange
    - Monitors positions and risk in real-time
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

    def run(self, duration_minutes: int = 60, interval_seconds: int = 60):
        """
        Run paper trading for a specified duration.

        Args:
            duration_minutes: How long to run (default 60 min)
            interval_seconds: How often to check for signals (default 60s)
        """
        print("\n" + "=" * 60)
        print("  PAPER TRADER — Live Virtual Trading")
        print("=" * 60)
        print(f"  Balance: ${self.config.STARTING_BALANCE:.2f}")
        print(f"  Target:  ${self.config.TARGET_BALANCE:.2f}")
        print(f"  Pairs:   {self.config.TRADING_PAIRS}")
        print(f"  Running for {duration_minutes} minutes, checking every {interval_seconds}s")
        print("=" * 60 + "\n")

        end_time = time.time() + duration_minutes * 60

        try:
            while time.time() < end_time:
                self.iteration += 1
                self._tick()

                # Print status every 5 iterations
                if self.iteration % 5 == 0:
                    self._print_status()

                # Check if target reached
                if self.exchange.equity >= self.config.TARGET_BALANCE:
                    print(f"\n  TARGET REACHED! Equity: ${self.exchange.equity:.2f}")
                    break

                # Check kill switch
                can_trade, reason = self.risk_mgr.can_trade()
                if not can_trade and "KILL" in reason:
                    print(f"\n  {reason}")
                    break

                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n  Paper trading stopped by user.")

        self._print_final_report()

    def _tick(self):
        """Single iteration: fetch data, check signals, manage positions."""
        # Daily/weekly risk reset
        now = datetime.now(timezone.utc)
        if now.date() != self._last_day:
            self.risk_mgr.new_day()
            self._last_day = now.date()
        current_week = now.isocalendar()[1]
        if current_week != self._last_week:
            self.risk_mgr.new_week()
            self._last_week = current_week

        # Fetch current prices
        current_prices = {}
        for symbol in self.config.TRADING_PAIRS:
            ticker = fetch_ticker(symbol, self.ccxt_exchange)
            if ticker and "last" in ticker:
                current_prices[symbol] = ticker["last"]

        if not current_prices:
            return

        # Fetch funding rates
        funding_rates = {}
        for symbol in self.config.TRADING_PAIRS:
            funding_rates[symbol] = fetch_funding_rate(symbol, self.ccxt_exchange)

        # Update positions
        self.exchange.update_positions(current_prices, funding_rates)

        # Sync risk state
        self.risk_mgr.state.equity = self.exchange.equity
        if self.exchange.equity > self.risk_mgr.state.peak_equity:
            self.risk_mgr.state.peak_equity = self.exchange.equity

        # Record closed trades
        while len(self.exchange.trade_history) > self.risk_mgr.state.total_trades:
            idx = self.risk_mgr.state.total_trades
            trade = self.exchange.trade_history[idx]
            self.risk_mgr.record_trade(trade.net_pnl)
            print(
                f"  CLOSED: {trade.symbol} {trade.side} "
                f"PnL=${trade.net_pnl:+.2f} ({trade.close_reason})"
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

            try:
                df = fetch_ohlcv(symbol, self.config.CANDLE_TIMEFRAME, days=7, exchange=self.ccxt_exchange)
            except Exception:
                continue

            if len(df) < 200:
                continue

            signal = self.signal_gen.evaluate_current(df, symbol)
            if signal is None:
                continue

            # Risk-adjusted sizing
            leverage = self.risk_mgr.calculate_leverage(signal.volatility_regime)
            position_size = self.risk_mgr.calculate_position_size(signal.confidence)
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
                print(
                    f"  OPEN: {signal.signal_type.value} {symbol} "
                    f"@ {signal.entry_price:.2f}  "
                    f"Size=${position_size:.2f}  Lev={leverage}x  "
                    f"SL={signal.stop_loss:.2f}  TP={signal.take_profit:.2f}"
                )

    def _print_status(self):
        """Print current trading status."""
        account = self.exchange.get_account_summary()
        risk = self.risk_mgr.get_risk_report()
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60

        print(f"\n  --- Status (iter {self.iteration}, {elapsed:.0f}min) ---")
        print(f"  Equity: ${account['equity']:.2f}  |  Balance: ${account['balance']:.2f}")
        print(f"  Positions: {account['open_positions']}  |  Trades: {account['total_trades']}")
        print(f"  Drawdown: {risk['drawdown_pct']:.1f}%  |  Mode: {risk['mode']}")
        print(f"  Win rate: {risk['win_rate']:.0f}%  |  Daily PnL: ${risk['daily_pnl']:.2f}")

        for pid, pos in self.exchange.positions.items():
            side = pos.side.value
            pnl = pos.unrealized_pnl
            print(f"    {side:5} {pos.symbol}: entry={pos.entry_price:.2f} uPnL=${pnl:+.2f}")

    def _print_final_report(self):
        """Print final trading report."""
        # Close remaining positions
        current_prices = {}
        for symbol in self.config.TRADING_PAIRS:
            ticker = fetch_ticker(symbol, self.ccxt_exchange)
            if ticker and "last" in ticker:
                current_prices[symbol] = ticker["last"]

        self.exchange.close_all_positions(current_prices, "SESSION_END")

        stats = self.exchange.get_performance_stats()
        print("\n" + "=" * 60)
        print("  PAPER TRADING SESSION RESULTS")
        print("=" * 60)
        if isinstance(stats, dict) and "total_trades" in stats:
            print(f"  Total trades:   {stats['total_trades']}")
            print(f"  Win rate:       {stats['win_rate']:.1f}%")
            print(f"  Total PnL:      ${stats['total_pnl']:.2f}")
            print(f"  Final equity:   ${stats['final_equity']:.2f}")
            print(f"  Return:         {stats['return_pct']:.1f}%")
            print(f"  Max drawdown:   {stats['max_drawdown_pct']:.1f}%")
        else:
            print(f"  {stats}")
        print("=" * 60)

        self.exchange.save_trades()
        print(f"  Trade log saved to {self.config.TRADE_LOG_FILE}")
