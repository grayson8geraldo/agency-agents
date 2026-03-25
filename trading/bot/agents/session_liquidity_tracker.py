"""Step 2: Session Liquidity Tracker — maps Asian session range and detects sweeps."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

from trading.bot.models import (
    AsiaSession,
    Bias,
    BiasSignal,
    Candle,
    SweepSignal,
    SweepStatus,
)

# Use proper NY timezone (handles EST/EDT automatically)
NY_TZ = ZoneInfo("America/New_York")


class SessionLiquidityTracker:
    """Maps the Asian session range (20:00-00:00 EST) and detects liquidity sweeps.

    For BULLISH bias: waits for price to sweep BELOW the Asian low.
    For BEARISH bias: waits for price to sweep ABOVE the Asian high.
    """

    ASIA_START = time(20, 0)  # 20:00 EST
    ASIA_END = time(0, 0)     # 00:00 EST (next day)
    SWEEP_CUTOFF = time(5, 0)  # Give up if no sweep by 05:00 EST

    def map_session(self, candles: list[Candle]) -> AsiaSession | None:
        """Extract the Asian session range from candle data.

        Args:
            candles: M1 (or any TF) candles covering 20:00-00:00 EST.
        """
        asia_candles = self._filter_asia_candles(candles)

        if not asia_candles:
            logger.warning("No candles found within Asian session window")
            return None

        high = max(c.high for c in asia_candles)
        low = min(c.low for c in asia_candles)

        session = AsiaSession(
            high=high,
            low=low,
            start=asia_candles[0].time,
            end=asia_candles[-1].time,
        )
        logger.info("Asian session mapped: high={}, low={}", high, low)
        return session

    def detect_sweep(
        self,
        candles: list[Candle],
        session: AsiaSession,
        bias: Bias,
    ) -> SweepSignal:
        """Check if price has swept the relevant side of the Asian range.

        Args:
            candles: Candles AFTER the Asian session (00:00-05:00 EST).
            session: The mapped Asian session range.
            bias: Daily bias from Step 1.
        """
        if bias == Bias.NEUTRAL:
            return SweepSignal(status=SweepStatus.EXPIRED, daily_bias=bias, asia_session=session)

        post_session = self._filter_post_session_candles(candles, session.end)

        if not post_session:
            logger.info("No post-session candles yet — still waiting")
            return SweepSignal(
                status=SweepStatus.WAITING, daily_bias=bias, asia_session=session
            )

        # JPY pairs have prices > 10; use 0.01 pip size for them
        pip_size = 0.01 if session.high > 10 else 0.0001

        for candle in post_session:
            if self._is_past_cutoff(candle.time):
                break

            if bias == Bias.BULLISH and candle.low < session.low:
                depth = session.low - candle.low
                depth_pips = round(depth / pip_size, 1)
                logger.info(
                    "SWEEP detected — Asian LOW {} taken at {} (depth: {:.1f} pips)",
                    session.low, candle.time, depth_pips,
                )
                return SweepSignal(
                    status=SweepStatus.SWEPT,
                    daily_bias=bias,
                    asia_session=session,
                    sweep_side="LOW",
                    sweep_price=candle.low,
                    sweep_time=candle.time,
                    depth_pips=depth_pips,
                )

            if bias == Bias.BEARISH and candle.high > session.high:
                depth = candle.high - session.high
                depth_pips = round(depth / pip_size, 1)
                logger.info(
                    "SWEEP detected — Asian HIGH {} taken at {} (depth: {:.1f} pips)",
                    session.high, candle.time, depth_pips,
                )
                return SweepSignal(
                    status=SweepStatus.SWEPT,
                    daily_bias=bias,
                    asia_session=session,
                    sweep_side="HIGH",
                    sweep_price=candle.high,
                    sweep_time=candle.time,
                    depth_pips=depth_pips,
                )

        # Check if we've passed the cutoff
        if post_session and self._is_past_cutoff(post_session[-1].time):
            logger.info("No sweep by 05:00 EST cutoff — no trade today")
            return SweepSignal(
                status=SweepStatus.EXPIRED, daily_bias=bias, asia_session=session
            )

        return SweepSignal(
            status=SweepStatus.MONITORING, daily_bias=bias, asia_session=session
        )

    def analyze(self, candles: list[Candle], bias_signal: BiasSignal) -> SweepSignal:
        """Full Step 2 analysis: map session + detect sweep.

        Args:
            candles: All available M1 candles spanning the Asian session and beyond.
            bias_signal: Output from Step 1.
        """
        if bias_signal.bias == Bias.NEUTRAL:
            logger.info("Bias is NEUTRAL — standing down")
            return SweepSignal(status=SweepStatus.EXPIRED, daily_bias=Bias.NEUTRAL)

        session = self.map_session(candles)
        if session is None:
            return SweepSignal(
                status=SweepStatus.EXPIRED,
                daily_bias=bias_signal.bias,
                notes="Could not map Asian session",
            )

        return self.detect_sweep(candles, session, bias_signal.bias)

    # -- Internal Helpers --

    def _to_ny(self, dt: datetime) -> datetime:
        """Convert a datetime to New York time (handles EST/EDT)."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(NY_TZ)

    def _filter_asia_candles(self, candles: list[Candle]) -> list[Candle]:
        """Return candles from the MOST RECENT 20:00-00:00 NY session only."""
        # Tag each candle with its NY hour
        tagged: list[tuple[datetime, Candle]] = []
        for c in candles:
            ny_time = self._to_ny(c.time)
            if 20 <= ny_time.hour <= 23:
                tagged.append((ny_time, c))

        if not tagged:
            return []

        # Only keep candles from the most recent Asian session date
        # Asian session date = the NY calendar date of the 20:00 candle
        latest_date = tagged[-1][0].date()
        return [c for ny_t, c in tagged if ny_t.date() == latest_date]

    def _filter_post_session_candles(
        self, candles: list[Candle], session_end: datetime
    ) -> list[Candle]:
        """Return candles after the Asian session end."""
        return [c for c in candles if c.time > session_end]

    def _is_past_cutoff(self, dt: datetime) -> bool:
        """Check if a timestamp is past the 05:00 NY sweep monitoring cutoff."""
        ny_time = self._to_ny(dt)
        return ny_time.hour >= 5 and ny_time.hour < 20
