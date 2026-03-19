"""
Backtester — Runs the strategy against historical data with virtual execution.
Walk-forward testing with realistic simulation.
"""

import sys
from datetime import datetime, timezone

import pandas as pd

from engine.risk_manager import RiskManager
from engine.signal_generator import SignalGenerator, SignalType
from engine.virtual_exchange import PositionSide, VirtualExchange
from utils.indicators import add_all_indicators


class Backtester:
    """
    Walk-forward backtester that simulates the full trading pipeline:
    1. Signal generation (Quant Strategist)
    2. Risk validation (Risk Manager)
    3. Order execution (Virtual Exchange)
    4. Position management (Trading Bot Developer logic)
    """

    def __init__(self, config):
        self.config = config
        self.exchange = VirtualExchange(config)
        self.risk_mgr = RiskManager(config)
        self.signal_gen = SignalGenerator(config)
        self.equity_curve = []
        self.signals_generated = 0
        self.signals_taken = 0

    def run(self, data: dict[str, pd.DataFrame], verbose: bool = True) -> dict:
        """
        Run backtest on historical data.
        data: {symbol: DataFrame with OHLCV}
        """
        if verbose:
            print("\n" + "=" * 60)
            print("  BACKTESTER — Walk-Forward Simulation")
            print("=" * 60)
            print(f"  Starting balance: ${self.config.STARTING_BALANCE:.2f}")
            print(f"  Target: ${self.config.TARGET_BALANCE:.2f}")
            print(f"  Pairs: {list(data.keys())}")
            print("=" * 60 + "\n")

        # Add indicators to all datasets
        prepared = {}
        for symbol, df in data.items():
            if len(df) < 200:
                print(f"  ⚠ {symbol}: only {len(df)} candles, need 200+. Skipping.")
                continue
            prepared[symbol] = add_all_indicators(df, self.config)

        if not prepared:
            print("  No data with enough candles. Aborting backtest.")
            return {}

        # Find common timestamp range
        min_len = min(len(df) for df in prepared.values())
        start_idx = 200  # Need warm-up for indicators

        day_counter = 0
        bars_per_day = 96  # 15-minute bars in 24 hours
        funding_interval = 32  # Every 8 hours = 32 bars at 15m
        position_open_bars: dict[str, int] = {}  # Track when each position opened
        time_stop_bars = int(self.config.TIME_STOP_HOURS * 4)  # 15m bars per hour

        for i in range(start_idx, min_len):
            # New day logic
            if (i - start_idx) % bars_per_day == 0 and i > start_idx:
                day_counter += 1
                self.risk_mgr.new_day()
                if day_counter % 7 == 0:
                    self.risk_mgr.new_week()

            # Get current prices
            current_prices = {}
            for symbol, df in prepared.items():
                current_prices[symbol] = df.iloc[i]["close"]

            # Apply funding rates periodically
            funding_rates = {}
            if (i - start_idx) % funding_interval == 0:
                for symbol in prepared:
                    funding_rates[symbol] = 0.0001  # Approximate 0.01% per 8h

            # Update existing positions
            self.exchange.update_positions(current_prices, funding_rates)

            # Time stop: close stalled positions
            for pid in list(self.exchange.positions.keys()):
                if pid not in position_open_bars:
                    position_open_bars[pid] = i
                if i - position_open_bars[pid] >= time_stop_bars:
                    pos = self.exchange.positions[pid]
                    price = current_prices.get(pos.symbol, pos.entry_price)
                    self.exchange.close_position(pid, price, "TIME_STOP")
                    del position_open_bars[pid]

            # Sync risk manager equity with exchange
            self.risk_mgr.state.equity = self.exchange.equity
            if self.exchange.equity > self.risk_mgr.state.peak_equity:
                self.risk_mgr.state.peak_equity = self.exchange.equity

            # Record closed trades in risk manager
            while len(self.exchange.trade_history) > self.risk_mgr.state.total_trades:
                idx = self.risk_mgr.state.total_trades
                trade = self.exchange.trade_history[idx]
                self.risk_mgr.record_trade(trade.net_pnl)

            # Record equity
            self.equity_curve.append({
                "bar": i,
                "equity": self.exchange.equity,
                "balance": self.exchange.balance,
                "positions": len(self.exchange.positions),
            })

            # Check if can trade
            can_trade, reason = self.risk_mgr.can_trade()
            if not can_trade:
                continue

            # Skip if max positions reached
            if len(self.exchange.positions) >= self.config.MAX_CONCURRENT_POSITIONS:
                continue

            # Generate signals for each pair
            for symbol, df in prepared.items():
                # Check if already have position in this symbol
                has_position = any(
                    p.symbol == symbol for p in self.exchange.positions.values()
                )
                if has_position:
                    continue

                # Use a lookback window for signal evaluation
                window = df.iloc[max(0, i - 200):i + 1].copy()
                signal = self.signal_gen.evaluate_current(window, symbol, global_idx=i)

                if signal is None:
                    continue

                self.signals_generated += 1

                # Risk manager validates
                can_trade, reason = self.risk_mgr.can_trade()
                if not can_trade:
                    break

                vol_regime = signal.volatility_regime
                leverage = self.risk_mgr.calculate_leverage(vol_regime)
                leverage = min(leverage, signal.leverage)

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

                if pos is not None:
                    self.signals_taken += 1
                    if verbose and self.signals_taken <= 50:  # Limit output
                        print(
                            f"  [{i:>5}] {signal.signal_type.value:5} {symbol:10} "
                            f"@ {signal.entry_price:>10.2f}  "
                            f"SL={signal.stop_loss:>10.2f}  TP={signal.take_profit:>10.2f}  "
                            f"Size=${position_size:>8.2f}  Lev={leverage}x  "
                            f"Conf={signal.confidence:.0%}"
                        )

        # Close any remaining positions at last price
        final_prices = {}
        for symbol, df in prepared.items():
            final_prices[symbol] = df.iloc[-1]["close"]
        self.exchange.close_all_positions(final_prices, "BACKTEST_END")

        # Sync final trades
        while len(self.exchange.trade_history) > self.risk_mgr.state.total_trades:
            idx = self.risk_mgr.state.total_trades
            trade = self.exchange.trade_history[idx]
            self.risk_mgr.record_trade(trade.net_pnl)

        # Results
        stats = self.exchange.get_performance_stats()
        risk_report = self.risk_mgr.get_risk_report()

        if verbose:
            self._print_results(stats, risk_report)

        return {
            "stats": stats,
            "risk_report": risk_report,
            "equity_curve": self.equity_curve,
            "signals_generated": self.signals_generated,
            "signals_taken": self.signals_taken,
        }

    def _print_results(self, stats: dict, risk_report: dict):
        """Pretty-print backtest results."""
        print("\n" + "=" * 60)
        print("  BACKTEST RESULTS")
        print("=" * 60)
        print(f"  Signals generated:  {self.signals_generated}")
        print(f"  Signals traded:     {self.signals_taken}")
        print(f"  Total trades:       {stats.get('total_trades', 0)}")
        print(f"  Win rate:           {stats.get('win_rate', 0):.1f}%")
        print(f"  Profit factor:      {stats.get('profit_factor', 0):.2f}")
        print(f"  Sharpe ratio:       {stats.get('sharpe_ratio', 0):.2f}")
        print("-" * 60)
        print(f"  Starting balance:   ${self.config.STARTING_BALANCE:.2f}")
        print(f"  Final equity:       ${stats.get('final_equity', 0):.2f}")
        print(f"  Total P&L:          ${stats.get('total_pnl', 0):.2f}")
        print(f"  Return:             {stats.get('return_pct', 0):.1f}%")
        print(f"  Max drawdown:       {stats.get('max_drawdown_pct', 0):.1f}%")
        print("-" * 60)
        print(f"  Avg win:            ${stats.get('avg_win', 0):.2f}")
        print(f"  Avg loss:           ${stats.get('avg_loss', 0):.2f}")
        print(f"  Largest win:        ${stats.get('largest_win', 0):.2f}")
        print(f"  Largest loss:       ${stats.get('largest_loss', 0):.2f}")
        print(f"  Total fees:         ${stats.get('total_fees', 0):.2f}")
        print(f"  Total funding:      ${stats.get('total_funding', 0):.2f}")
        print("-" * 60)
        print(f"  Risk mode:          {risk_report.get('mode', 'N/A')}")
        print(f"  Kelly fraction:     {risk_report.get('kelly_fraction', 0):.4f}")
        target_hit = stats.get('final_equity', 0) >= self.config.TARGET_BALANCE
        print(f"  Target reached:     {'YES' if target_hit else 'NO'} "
              f"(${self.config.TARGET_BALANCE:.0f})")
        print("=" * 60)
