"""Backtesting engine — test strategy on real historical data."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from .config import BotConfig, NY_TZ, UTC_TZ
from .exchange import ExchangeFetcher
from .models import Bias, Candle, TradeStatus
from .risk_manager import RiskManager
from .sessions import analyze_sessions
from .strategy import generate_signal
from .virtual_account import VirtualAccount

logger = logging.getLogger(__name__)


class Backtester:
    """
    Backtests the ORB + Session Analysis strategy on real historical data.
    Downloads candles from Binance and simulates trading day by day.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.exchange = ExchangeFetcher(config.exchange_id)
        self.risk = RiskManager(config.risk)

    def run(
        self,
        start_date: datetime,
        end_date: datetime,
        symbol: Optional[str] = None,
    ) -> VirtualAccount:
        """
        Run backtest from start_date to end_date.
        Returns the VirtualAccount with all trade history.
        """
        symbol = symbol or self.config.strategy.symbol
        account = VirtualAccount(self.config.risk.initial_balance)

        print(f"\n{'='*60}")
        print(f"  BACKTESTING: ORB + Session Analysis")
        print(f"  Symbol: {symbol}")
        print(f"  Period: {start_date.date()} → {end_date.date()}")
        print(f"  Initial Balance: ${account.state.initial_balance}")
        print(f"{'='*60}\n")

        # Download all historical data upfront
        print("Downloading historical data...")
        candles_15m = self.exchange.fetch_candles_range(
            symbol, "15m", start_date - timedelta(days=1), end_date + timedelta(days=1),
        )
        candles_5m = self.exchange.fetch_candles_range(
            symbol, "5m", start_date - timedelta(days=1), end_date + timedelta(days=1),
        )

        if not candles_15m or not candles_5m:
            print("ERROR: Could not fetch historical data")
            return account

        print(f"  15m candles: {len(candles_15m)}")
        print(f"  5m candles:  {len(candles_5m)}")
        print()

        # Iterate day by day
        current_date = start_date
        days_processed = 0
        signals_found = 0

        while current_date < end_date:
            ny_date = current_date.astimezone(NY_TZ)

            # Skip weekends (crypto trades 24/7 but ORB strategy is session-based)
            # We still trade crypto on weekends since the strategy watches session times
            date_str = ny_date.strftime("%Y-%m-%d")
            account.reset_daily(date_str)

            # Skip if kill switch
            if account.state.kill_switch_active:
                current_date += timedelta(days=1)
                continue

            # Get candles for this day's sessions
            day_15m = self._get_day_candles(candles_15m, current_date)
            day_5m = self._get_day_candles(candles_5m, current_date)

            if not day_15m or not day_5m:
                current_date += timedelta(days=1)
                continue

            # Run strategy for this day
            result = self._process_day(
                account, day_15m, day_5m, current_date,
            )

            if result:
                signals_found += 1

            days_processed += 1
            current_date += timedelta(days=1)

        # Print results
        print(f"\nDays processed: {days_processed}")
        print(f"Signals found:  {signals_found}")
        print(account.get_summary())
        self._print_trade_log(account)

        return account

    def _get_day_candles(
        self,
        all_candles: list[Candle],
        trade_date: datetime,
    ) -> list[Candle]:
        """
        Get candles relevant for a trading day.
        Need from previous day 19:00 NY to current day 16:00 NY.
        """
        ny_date = trade_date.astimezone(NY_TZ).date()
        prev_day = ny_date - timedelta(days=1)

        # Start: previous day 19:00 NY
        start_ny = datetime.combine(prev_day, time(19, 0), tzinfo=NY_TZ)
        # End: current day 16:00 NY
        end_ny = datetime.combine(ny_date, time(16, 0), tzinfo=NY_TZ)

        start_utc = start_ny.astimezone(UTC_TZ)
        end_utc = end_ny.astimezone(UTC_TZ)

        return [c for c in all_candles if start_utc <= c.timestamp <= end_utc]

    def _process_day(
        self,
        account: VirtualAccount,
        candles_15m: list[Candle],
        candles_5m: list[Candle],
        trade_date: datetime,
    ) -> bool:
        """Process a single trading day. Returns True if a trade was taken."""
        # Session analysis
        session = analyze_sessions(candles_15m, trade_date)

        if session.bias == Bias.NO_TRADE:
            return False

        # Get 5m candles only up to each point in time (no look-ahead)
        ny_date = trade_date.astimezone(NY_TZ).date()

        # Find the ORB candle time range
        orb_end_ny = datetime.combine(ny_date, time(9, 45), tzinfo=NY_TZ)
        orb_end_utc = orb_end_ny.astimezone(UTC_TZ)

        # Process candles sequentially to simulate real-time
        # We check for signals on each new 5m candle after ORB
        candles_after_orb_5m = [c for c in candles_5m if c.timestamp >= orb_end_utc]

        for i, candle in enumerate(candles_after_orb_5m):
            # End of trading session check
            ny_time = candle.timestamp.astimezone(NY_TZ).time()
            if ny_time >= time(15, 55):
                # Close any open position at end of day
                if account.state.current_trade:
                    account.close_trade(
                        candle.close, candle.timestamp, TradeStatus.CLOSED_MANUAL,
                    )
                break

            # Check SL/TP on open position
            if account.state.current_trade:
                close_reason = account.check_sl_tp(candle)
                if close_reason == TradeStatus.CLOSED_SL:
                    account.close_trade(
                        account.state.current_trade.signal.stop_loss,
                        candle.timestamp, close_reason,
                    )
                    break  # One trade per day
                elif close_reason == TradeStatus.CLOSED_TP:
                    account.close_trade(
                        account.state.current_trade.signal.take_profit,
                        candle.timestamp, close_reason,
                    )
                    break  # One trade per day
                continue  # Position open, skip signal generation

            # Try to generate signal with candles available so far
            available_5m = [c for c in candles_5m if c.timestamp <= candle.timestamp]

            signal = generate_signal(
                candles_15m, available_5m, trade_date, session,
                self.config.strategy,
            )

            if signal is None:
                continue

            # Refine with risk management
            signal = self.risk.refine_signal(
                signal, account.state.equity, session,
            )

            # Validate
            valid, reason = self.risk.validate_signal(
                signal,
                account.state.equity,
                account.state.daily_pnl,
                account.state.consecutive_losses,
                account.state.peak_equity,
                0,
            )

            if not valid:
                logger.debug(f"Signal rejected on {trade_date.date()}: {reason}")
                continue

            # Calculate position size
            position_size = self.risk.calculate_position_size(
                account.state.equity, signal.entry_price, signal.stop_loss,
            )

            if position_size <= 0:
                continue

            risk_amount = account.state.equity * self.config.risk.risk_per_trade_pct

            # Open trade
            account.open_trade(signal, position_size, risk_amount, candle.timestamp)
            return True

        return account.state.current_trade is not None

    def _print_trade_log(self, account: VirtualAccount):
        """Print detailed trade log."""
        if not account.state.trade_history:
            print("\nNo trades executed during backtest period.")
            return

        print(f"\n{'='*80}")
        print("  TRADE LOG")
        print(f"{'='*80}")
        print(
            f"{'#':>3} {'Date':>12} {'Dir':>5} {'Entry':>10} {'Exit':>10} "
            f"{'SL':>10} {'TP':>10} {'P&L':>8} {'Result':>8} {'Bal':>10}"
        )
        print("-" * 80)

        running_balance = account.state.initial_balance
        for t in account.state.trade_history:
            running_balance += t.pnl
            date_str = t.opened_at.strftime("%Y-%m-%d") if t.opened_at else "N/A"
            exit_str = f"{t.exit_price:.2f}" if t.exit_price else "N/A"
            print(
                f"{t.id:>3} {date_str:>12} "
                f"{t.signal.direction.value:>5} "
                f"{t.entry_price:>10.2f} {exit_str:>10} "
                f"{t.signal.stop_loss:>10.2f} {t.signal.take_profit:>10.2f} "
                f"{'${:+.2f}'.format(t.pnl):>8} "
                f"{t.status.value:>8} "
                f"{'${:.2f}'.format(running_balance):>10}"
            )

        print("-" * 80)
