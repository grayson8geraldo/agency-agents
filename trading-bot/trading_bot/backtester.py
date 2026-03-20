"""Backtesting engine — test forex strategy on real historical data."""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from .config import BotConfig, NY_TZ, UTC_TZ, get_pair_name, get_pip_size
from .exchange import ForexFetcher
from .models import Bias, Candle, TradeStatus
from .risk_manager import RiskManager
from .sessions import analyze_sessions, is_forex_trading_day
from .strategy import generate_signal
from .virtual_account import VirtualAccount

logger = logging.getLogger(__name__)


def _ny_trading_dates(start: date_type, end: date_type) -> list[date_type]:
    """Generate list of NY trading dates (skip Sat/Sun)."""
    dates = []
    current = start
    while current <= end:
        weekday = current.weekday()
        if weekday < 5:  # Mon-Fri
            dates.append(current)
        current += timedelta(days=1)
    return dates


class Backtester:
    """
    Backtests the ORB + Session Analysis strategy on real historical forex data.
    Downloads candles from Yahoo Finance and simulates trading day by day.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.fetcher = ForexFetcher()
        self.risk = RiskManager(config.risk, config.strategy.symbol)

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
        pair_name = get_pair_name(symbol)
        pip_size = get_pip_size(symbol)
        account = VirtualAccount(self.config.risk.initial_balance, symbol)

        # Convert to NY dates for iteration
        start_ny = start_date.astimezone(NY_TZ).date() if start_date.tzinfo else start_date.date()
        end_ny = end_date.astimezone(NY_TZ).date() if end_date.tzinfo else end_date.date()

        print(f"\n{'='*60}")
        print(f"  BACKTESTING: ORB + Session Analysis (Forex)")
        print(f"  Pair:     {pair_name}")
        print(f"  Period:   {start_ny} -> {end_ny}")
        print(f"  Balance:  ${account.state.initial_balance}")
        print(f"  Pip size: {pip_size}")
        print(f"{'='*60}\n")

        # Download all historical data
        # We need data from previous day 19:00 NY for Asia session,
        # so fetch from 2 days before start
        fetch_start = datetime.combine(
            start_ny - timedelta(days=2), time(0, 0), tzinfo=NY_TZ,
        ).astimezone(UTC_TZ)
        fetch_end = datetime.combine(
            end_ny + timedelta(days=1), time(23, 59), tzinfo=NY_TZ,
        ).astimezone(UTC_TZ)

        print("Downloading historical forex data...")
        candles_15m = self.fetcher.fetch_candles_range(
            symbol, "15m", fetch_start, fetch_end,
        )
        candles_5m = self.fetcher.fetch_candles_range(
            symbol, "5m", fetch_start, fetch_end,
        )

        if not candles_15m or not candles_5m:
            print("ERROR: Could not fetch historical data.")
            print("Note: yfinance limits 5m/15m data to ~60 days back from today.")
            return account

        # Show actual data coverage
        first_15m = candles_15m[0].timestamp.astimezone(NY_TZ)
        last_15m = candles_15m[-1].timestamp.astimezone(NY_TZ)
        first_5m = candles_5m[0].timestamp.astimezone(NY_TZ)
        last_5m = candles_5m[-1].timestamp.astimezone(NY_TZ)

        print(f"  15m candles: {len(candles_15m)}  "
              f"({first_15m.date()} {first_15m.strftime('%H:%M')} → "
              f"{last_15m.date()} {last_15m.strftime('%H:%M')} NY)")
        print(f"  5m candles:  {len(candles_5m)}  "
              f"({first_5m.date()} {first_5m.strftime('%H:%M')} → "
              f"{last_5m.date()} {last_5m.strftime('%H:%M')} NY)")
        print()

        # Generate NY trading dates
        trading_dates = _ny_trading_dates(start_ny, end_ny)
        days_processed = 0
        days_with_data = 0
        signals_found = 0

        for ny_date in trading_dates:
            date_str = ny_date.isoformat()
            account.reset_daily(date_str)

            # Kill switch check
            if account.state.kill_switch_active:
                continue

            # Build a NY-based datetime for this trading day (10:00 NY as reference)
            trade_date_ny = datetime.combine(ny_date, time(10, 0), tzinfo=NY_TZ)

            # Get candles for this day's full session
            day_15m = self._get_day_candles(candles_15m, ny_date)
            day_5m = self._get_day_candles(candles_5m, ny_date)

            if not day_15m or not day_5m:
                continue

            days_with_data += 1

            # Run strategy
            result = self._process_day(account, day_15m, day_5m, trade_date_ny)
            if result:
                signals_found += 1

            days_processed += 1

        # Print results
        print(f"\nTrading days in range: {len(trading_dates)}")
        print(f"Days with data: {days_with_data}")
        print(f"Days processed: {days_processed}")
        print(f"Signals/trades: {signals_found}")
        print(account.get_summary())
        self._print_trade_log(account, pip_size)

        return account

    def _get_day_candles(
        self,
        all_candles: list[Candle],
        ny_date: date_type,
    ) -> list[Candle]:
        """
        Get candles relevant for a trading day.

        A forex trading day in NY runs from previous day 19:00 NY
        to current day 17:00 NY (covers Asia, London, NY sessions).
        """
        prev_day = ny_date - timedelta(days=1)

        start_ny = datetime.combine(prev_day, time(19, 0), tzinfo=NY_TZ)
        end_ny = datetime.combine(ny_date, time(17, 0), tzinfo=NY_TZ)

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

        ny_date = trade_date.astimezone(NY_TZ).date()
        orb_end_ny = datetime.combine(ny_date, time(9, 45), tzinfo=NY_TZ)
        orb_end_utc = orb_end_ny.astimezone(UTC_TZ)

        candles_after_orb_5m = [c for c in candles_5m if c.timestamp >= orb_end_utc]

        for i, candle in enumerate(candles_after_orb_5m):
            ny_time = candle.timestamp.astimezone(NY_TZ).time()

            # End of trading session
            if ny_time >= time(16, 55):
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
                    break
                elif close_reason == TradeStatus.CLOSED_TP:
                    account.close_trade(
                        account.state.current_trade.signal.take_profit,
                        candle.timestamp, close_reason,
                    )
                    break
                continue

            # Try to generate signal
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
                logger.debug(f"Signal rejected {trade_date.date()}: {reason}")
                continue

            # Calculate lot size
            lot_size = self.risk.calculate_lot_size(
                account.state.equity, signal.entry_price, signal.stop_loss,
            )
            risk_amount = account.state.equity * self.config.risk.risk_per_trade_pct

            # Open trade
            account.open_trade(signal, lot_size, risk_amount, candle.timestamp)
            return True

        return account.state.current_trade is not None

    def _print_trade_log(self, account: VirtualAccount, pip_size: Decimal):
        """Print detailed trade log."""
        if not account.state.trade_history:
            print("\nNo trades executed during backtest period.")
            return

        print(f"\n{'='*90}")
        print("  TRADE LOG")
        print(f"{'='*90}")
        print(
            f"{'#':>3} {'Date':>12} {'Dir':>5} {'Entry':>9} {'Exit':>9} "
            f"{'SL':>9} {'TP':>9} {'Lots':>5} {'Pips':>7} {'P&L':>8} "
            f"{'Result':>8} {'Bal':>8}"
        )
        print("-" * 90)

        running_balance = account.state.initial_balance
        for t in account.state.trade_history:
            running_balance += t.pnl
            date_str = t.opened_at.strftime("%Y-%m-%d") if t.opened_at else "N/A"
            exit_str = f"{t.exit_price:.5f}" if t.exit_price else "N/A"
            print(
                f"{t.id:>3} {date_str:>12} "
                f"{t.signal.direction.value:>5} "
                f"{t.entry_price:>9.5f} {exit_str:>9} "
                f"{t.signal.stop_loss:>9.5f} {t.signal.take_profit:>9.5f} "
                f"{t.lot_size:>5} {t.pnl_pips:>+7.1f} "
                f"{'${:+.2f}'.format(t.pnl):>8} "
                f"{t.status.value:>8} "
                f"{'${:.2f}'.format(running_balance):>8}"
            )

        print("-" * 90)
