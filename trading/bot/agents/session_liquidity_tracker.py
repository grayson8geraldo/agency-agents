"""Step 2: Session Liquidity Tracker — maps Asian session range and detects sweeps."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from loguru import logger

from trading.bot.models import (
    AsiaSession,
    Bias,
    BiasSignal,
    Candle,
    SweepSignal,
    SweepStatus,
)

# EST = UTC-5
EST = timezone(timedelta(hours=-5))


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

        for candle in post_session:
            if self._is_past_cutoff(candle.time):
                break

            if bias == Bias.BULLISH and candle.low < session.low:
                depth = session.low - candle.low
                logger.info(
                    "SWEEP detected — Asian LOW {} taken at {} (depth: {:.1f} pips)",
                    session.low, candle.time, depth * 10000,
                )
                return SweepSignal(
                    status=SweepStatus.SWEPT,
                    daily_bias=bias,
                    asia_session=session,
                    sweep_side="LOW",
                    sweep_price=candle.low,
                    sweep_time=candle.time,
                    depth_pips=round(depth * 10000, 1),
                )

            if bias == Bias.BEARISH and candle.high > session.high:
                depth = candle.high - session.high
                logger.info(
                    "SWEEP detected — Asian HIGH {} taken at {} (depth: {:.1f} pips)",
                    session.high, candle.time, depth * 10000,
                )
                return SweepSignal(
                    status=SweepStatus.SWEPT,
                    daily_bias=bias,
                    asia_session=session,
                    sweep_side="HIGH",
                    sweep_price=candle.high,
                    sweep_time=candle.time,
                    depth_pips=round(depth * 10000, 1),
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

    def _filter_asia_candles(self, candles: list[Candle]) -> list[Candle]:
        """Return candles that fall within the 20:00-00:00 EST window."""
        result = []
        for c in candles:
            est_time = c.time.astimezone(EST) if c.time.tzinfo else c.time.replace(tzinfo=timezone.utc).astimezone(EST)
            hour = est_time.hour

            # 20:00 - 23:59 EST
            if 20 <= hour <= 23:
                result.append(c)
        return result

    def _filter_post_session_candles(
        self, candles: list[Candle], session_end: datetime
    ) -> list[Candle]:
        """Return candles after the Asian session end."""
        return [c for c in candles if c.time > session_end]

    def _is_past_cutoff(self, dt: datetime) -> bool:
        """Check if a timestamp is past the 05:00 EST sweep monitoring cutoff."""
        est_time = dt.astimezone(EST) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(EST)
        return est_time.hour >= 5 and est_time.hour < 20
