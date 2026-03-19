"""Main trading engine — orchestrates live paper trading on real data."""

from __future__ import annotations

import logging
import time as time_mod
from datetime import datetime, time, timedelta
from decimal import Decimal

from .config import BotConfig, NY_TZ, UTC_TZ
from .exchange import ExchangeFetcher
from .models import Bias, Candle, TradeStatus
from .risk_manager import RiskManager
from .sessions import analyze_sessions
from .strategy import generate_signal
from .virtual_account import VirtualAccount

logger = logging.getLogger(__name__)


class TradingEngine:
    """Live paper-trading engine using real market data."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.exchange = ExchangeFetcher(config.exchange_id)
        self.risk = RiskManager(config.risk)
        self.account = VirtualAccount(config.risk.initial_balance)
        self._last_signal_date: str | None = None

    def run_once(self) -> str | None:
        """
        Run a single iteration of the trading loop.
        Returns a status message or None.
        """
        now = datetime.now(NY_TZ)
        today_str = now.strftime("%Y-%m-%d")

        # Reset daily tracking
        self.account.reset_daily(today_str)

        # Only trade during NY session hours (09:45 - 16:00)
        if now.time() < time(9, 45) or now.time() > time(16, 0):
            return f"Outside NY trading hours ({now.strftime('%H:%M')} NY)"

        # Skip if already traded today
        if self._last_signal_date == today_str:
            # But still check SL/TP on open position
            return self._check_open_position()

        # Check kill switch
        if self.account.state.kill_switch_active:
            return f"Kill switch active: {self.account.state.kill_switch_reason}"

        # Fetch candles for session analysis
        trade_date = now
        candles_15m = self._fetch_session_candles(trade_date, "15m")
        candles_5m = self._fetch_session_candles(trade_date, "5m")

        if not candles_15m or not candles_5m:
            return "Insufficient candle data"

        # Session analysis
        session = analyze_sessions(candles_15m, trade_date)

        if session.bias == Bias.NO_TRADE:
            return f"No trade today: London didn't sweep Asia liquidity"

        # Generate signal
        signal = generate_signal(
            candles_15m, candles_5m, trade_date, session, self.config.strategy,
        )

        if signal is None:
            return None  # No signal yet, keep checking

        # Refine signal with risk management
        signal = self.risk.refine_signal(signal, self.account.state.equity, session)

        # Validate
        valid, reason = self.risk.validate_signal(
            signal,
            self.account.state.equity,
            self.account.state.daily_pnl,
            self.account.state.consecutive_losses,
            self.account.state.peak_equity,
            1 if self.account.state.current_trade else 0,
        )

        if not valid:
            logger.warning(f"Signal rejected: {reason}")
            self._last_signal_date = today_str
            return f"Signal rejected: {reason}"

        # Calculate position size
        position_size = self.risk.calculate_position_size(
            self.account.state.equity, signal.entry_price, signal.stop_loss,
        )

        if position_size <= 0:
            return "Position size too small"

        risk_amount = self.account.state.equity * self.config.risk.risk_per_trade_pct

        # Open trade
        self.account.open_trade(signal, position_size, risk_amount, now)
        self._last_signal_date = today_str

        return (
            f"TRADE OPENED: {signal.direction.value} @ {signal.entry_price}, "
            f"SL={signal.stop_loss}, TP={signal.take_profit}, "
            f"size={position_size}, risk=${risk_amount:.2f}"
        )

    def _check_open_position(self) -> str | None:
        """Check SL/TP for open position using latest candle."""
        trade = self.account.state.current_trade
        if trade is None:
            return None

        try:
            price = self.exchange.get_current_price(self.config.strategy.symbol)
        except Exception as e:
            logger.error(f"Failed to get price: {e}")
            return None

        now = datetime.now(NY_TZ)

        # Create a pseudo-candle from current price for SL/TP check
        candle = Candle(
            timestamp=now,
            open=price, high=price, low=price, close=price,
            volume=Decimal("0"),
        )

        result = self.account.check_sl_tp(candle)
        if result == TradeStatus.CLOSED_TP:
            self.account.close_trade(trade.signal.take_profit, now, result)
            return f"TP HIT! PnL: ${trade.pnl:+.2f}"
        elif result == TradeStatus.CLOSED_SL:
            self.account.close_trade(trade.signal.stop_loss, now, result)
            return f"SL HIT! PnL: ${trade.pnl:+.2f}"

        # Close at end of day (16:00 NY)
        if now.time() >= time(15, 55):
            self.account.close_trade(price, now, TradeStatus.CLOSED_MANUAL)
            return f"End of day close. PnL: ${trade.pnl:+.2f}"

        return None

    def _fetch_session_candles(
        self, trade_date: datetime, timeframe: str,
    ) -> list[Candle]:
        """Fetch candles covering Asia + London + NY sessions."""
        # Need candles from previous day 19:00 NY to now
        ny_now = trade_date.astimezone(NY_TZ)
        start = ny_now.replace(
            hour=19, minute=0, second=0, microsecond=0,
        ) - timedelta(days=1)
        start_utc = start.astimezone(UTC_TZ)

        try:
            return self.exchange.fetch_candles(
                self.config.strategy.symbol, timeframe,
                since=start_utc, limit=500,
            )
        except Exception as e:
            logger.error(f"Failed to fetch {timeframe} candles: {e}")
            return []

    def run_live(self):
        """Run the live trading loop."""
        logger.info(
            f"Starting live paper trading on {self.config.strategy.symbol} "
            f"with ${self.config.risk.initial_balance} virtual balance"
        )
        print(f"\n{'='*50}")
        print(f"  ORB + Session Analysis Bot (Paper Trading)")
        print(f"  Symbol: {self.config.strategy.symbol}")
        print(f"  Balance: ${self.account.state.balance:.2f}")
        print(f"{'='*50}\n")

        try:
            while True:
                try:
                    msg = self.run_once()
                    if msg:
                        now = datetime.now(NY_TZ).strftime("%H:%M:%S")
                        print(f"[{now}] {msg}")
                except Exception as e:
                    logger.error(f"Engine error: {e}", exc_info=True)
                    print(f"[ERROR] {e}")

                time_mod.sleep(self.config.poll_interval_seconds)

        except KeyboardInterrupt:
            print("\n\nShutting down...")
            print(self.account.get_summary())
            self.account.save_state()
