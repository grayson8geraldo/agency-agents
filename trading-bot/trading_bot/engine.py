"""Main trading engine — live forex paper trading on real data."""

from __future__ import annotations

import logging
import time as time_mod
from datetime import datetime, time, timedelta
from decimal import Decimal

from .config import BotConfig, NY_TZ, UTC_TZ, get_pair_name
from .exchange import ForexFetcher
from .models import Bias, Candle, TradeStatus
from .risk_manager import RiskManager
from .sessions import analyze_sessions, is_forex_trading_day
from .strategy import generate_signal
from .virtual_account import VirtualAccount

logger = logging.getLogger(__name__)


class TradingEngine:
    """Live forex paper-trading engine using real market data."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.fetcher = ForexFetcher()
        self.risk = RiskManager(config.risk, config.strategy.symbol)
        self.account = VirtualAccount(
            config.risk.initial_balance, config.strategy.symbol,
        )
        self._last_signal_date: str | None = None

    def run_once(self) -> str | None:
        """Run a single iteration of the trading loop."""
        now = datetime.now(NY_TZ)
        today_str = now.strftime("%Y-%m-%d")
        pair_name = get_pair_name(self.config.strategy.symbol)

        # Check if forex market is open
        if not is_forex_trading_day(now):
            return f"Forex market closed (weekend)"

        # Reset daily tracking
        self.account.reset_daily(today_str)

        # Only trade during NY session hours (09:45 – 17:00)
        if now.time() < time(9, 45) or now.time() > time(17, 0):
            return f"Outside NY trading hours ({now.strftime('%H:%M')} NY)"

        # Already traded today
        if self._last_signal_date == today_str:
            return self._check_open_position()

        # Kill switch
        if self.account.state.kill_switch_active:
            return f"Kill switch: {self.account.state.kill_switch_reason}"

        # Fetch candles for session analysis
        candles_15m = self._fetch_session_candles("15m")
        candles_5m = self._fetch_session_candles("5m")

        if not candles_15m or not candles_5m:
            return "Insufficient candle data"

        # Session analysis
        session = analyze_sessions(candles_15m, now)

        if session.bias == Bias.NO_TRADE:
            return f"No trade: London didn't sweep Asia liquidity"

        # Generate signal
        signal = generate_signal(
            candles_15m, candles_5m, now, session, self.config.strategy,
        )

        if signal is None:
            return None

        # Refine with risk management
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

        # Calculate lot size
        lot_size = self.risk.calculate_lot_size(
            self.account.state.equity, signal.entry_price, signal.stop_loss,
        )
        risk_amount = self.account.state.equity * self.config.risk.risk_per_trade_pct

        # Open trade
        self.account.open_trade(signal, lot_size, risk_amount, now)
        self._last_signal_date = today_str

        sl_pips = self.risk.price_to_pips(signal.entry_price - signal.stop_loss)
        tp_pips = self.risk.price_to_pips(signal.take_profit - signal.entry_price)

        return (
            f"OPEN: {signal.direction.value} {pair_name} "
            f"@ {signal.entry_price:.5f}, "
            f"SL={signal.stop_loss:.5f} ({sl_pips:.1f}p), "
            f"TP={signal.take_profit:.5f} ({tp_pips:.1f}p), "
            f"{lot_size} lot, risk=${risk_amount:.2f}"
        )

    def _check_open_position(self) -> str | None:
        """Check SL/TP for open position."""
        trade = self.account.state.current_trade
        if trade is None:
            return None

        try:
            price = self.fetcher.get_current_price(self.config.strategy.symbol)
        except Exception as e:
            logger.error(f"Failed to get price: {e}")
            return None

        now = datetime.now(NY_TZ)

        candle = Candle(
            timestamp=now, open=price, high=price, low=price,
            close=price, volume=Decimal("0"),
        )

        result = self.account.check_sl_tp(candle)
        if result == TradeStatus.CLOSED_TP:
            self.account.close_trade(trade.signal.take_profit, now, result)
            return f"TP HIT! PnL: ${trade.pnl:+.2f} ({trade.pnl_pips:+.1f} pips)"
        elif result == TradeStatus.CLOSED_SL:
            self.account.close_trade(trade.signal.stop_loss, now, result)
            return f"SL HIT! PnL: ${trade.pnl:+.2f} ({trade.pnl_pips:+.1f} pips)"

        # Close at end of NY session
        if now.time() >= time(16, 55):
            self.account.close_trade(price, now, TradeStatus.CLOSED_MANUAL)
            return f"EOD close. PnL: ${trade.pnl:+.2f} ({trade.pnl_pips:+.1f} pips)"

        return None

    def _fetch_session_candles(self, timeframe: str) -> list[Candle]:
        """Fetch candles covering Asia + London + NY sessions."""
        ny_now = datetime.now(NY_TZ)
        start = ny_now.replace(hour=19, minute=0, second=0, microsecond=0) - timedelta(days=1)

        try:
            return self.fetcher.fetch_candles(
                self.config.strategy.symbol, timeframe,
                start=start.astimezone(UTC_TZ),
                end=ny_now.astimezone(UTC_TZ),
            )
        except Exception as e:
            logger.error(f"Failed to fetch {timeframe} candles: {e}")
            return []

    def run_live(self):
        """Run the live trading loop."""
        pair_name = get_pair_name(self.config.strategy.symbol)
        print(f"\n{'='*55}")
        print(f"  ORB + Session Analysis Forex Bot (Paper Trading)")
        print(f"  Pair:    {pair_name}")
        print(f"  Balance: ${self.account.state.balance:.2f}")
        print(f"{'='*55}\n")

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
