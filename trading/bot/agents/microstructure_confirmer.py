"""Step 3: Microstructure Confirmer — detects M1 CHoCH after liquidity sweep."""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger

from trading.bot.models import (
    Bias,
    Candle,
    ConfirmationSignal,
    ConfirmationStatus,
    SweepSignal,
    SwingPoint,
)


class MicrostructureConfirmer:
    """Monitors M1 for a structural shift (CHoCH) after the liquidity sweep.

    After a BULLISH sweep (Asian low taken), M1 will be in a downtrend.
    We wait for M1 to break its last swing high — confirming buyers take control.
    """

    def __init__(self, swing_lookback: int = 2, timeout_minutes: int = 120) -> None:
        self.swing_lookback = swing_lookback
        self.timeout_minutes = timeout_minutes

    def analyze(self, candles_m1: list[Candle], sweep_signal: SweepSignal) -> ConfirmationSignal:
        """Run M1 CHoCH detection after sweep.

        Args:
            candles_m1: M1 candles starting from around the sweep time.
            sweep_signal: Output from Step 2.
        """
        bias = sweep_signal.daily_bias
        sweep_time = sweep_signal.sweep_time

        if sweep_time is None:
            return ConfirmationSignal(
                status=ConfirmationStatus.REJECTED,
                daily_bias=bias,
                notes="No sweep time provided",
            )

        # Filter candles to only those AFTER the sweep
        post_sweep = [c for c in candles_m1 if c.time >= sweep_time]

        if len(post_sweep) < 10:
            logger.info("Only {} M1 candles after sweep — still monitoring", len(post_sweep))
            return ConfirmationSignal(
                status=ConfirmationStatus.MONITORING,
                daily_bias=bias,
            )

        # Check timeout
        elapsed = (post_sweep[-1].time - sweep_time).total_seconds() / 60
        if elapsed > self.timeout_minutes:
            logger.info("{}min elapsed since sweep — no M1 CHoCH, rejecting", int(elapsed))
            return ConfirmationSignal(
                status=ConfirmationStatus.REJECTED,
                daily_bias=bias,
                time_since_sweep_minutes=elapsed,
            )

        # Find swing points on post-sweep M1 data
        swings = self._find_m1_swings(post_sweep)

        if len(swings) < 2:
            return ConfirmationSignal(
                status=ConfirmationStatus.MONITORING,
                daily_bias=bias,
                swing_points_tracked=len(swings),
            )

        # Find the key swing level for CHoCH
        choch_level, choch_type = self._find_choch_level(swings, bias)
        if choch_level is None:
            return ConfirmationSignal(
                status=ConfirmationStatus.MONITORING,
                daily_bias=bias,
                swing_points_tracked=len(swings),
            )

        # Detect CHoCH: candle body close beyond the key level
        post_sweep_extreme = self._get_post_sweep_extreme(post_sweep, bias)

        for candle in post_sweep:
            if bias == Bias.BULLISH and candle.close > choch_level:
                minutes_since = (candle.time - sweep_time).total_seconds() / 60
                logger.info(
                    "M1 CHoCH CONFIRMED at {} — close {} > LH {} ({:.0f}min after sweep)",
                    candle.time, candle.close, choch_level, minutes_since,
                )
                return ConfirmationSignal(
                    status=ConfirmationStatus.CONFIRMED,
                    daily_bias=bias,
                    choch_level=choch_level,
                    break_candle_time=candle.time,
                    break_candle_close=candle.close,
                    post_sweep_extreme=post_sweep_extreme,
                    swing_points_tracked=len(swings),
                    time_since_sweep_minutes=minutes_since,
                )

            if bias == Bias.BEARISH and candle.close < choch_level:
                minutes_since = (candle.time - sweep_time).total_seconds() / 60
                logger.info(
                    "M1 CHoCH CONFIRMED at {} — close {} < HL {} ({:.0f}min after sweep)",
                    candle.time, candle.close, choch_level, minutes_since,
                )
                return ConfirmationSignal(
                    status=ConfirmationStatus.CONFIRMED,
                    daily_bias=bias,
                    choch_level=choch_level,
                    break_candle_time=candle.time,
                    break_candle_close=candle.close,
                    post_sweep_extreme=post_sweep_extreme,
                    swing_points_tracked=len(swings),
                    time_since_sweep_minutes=minutes_since,
                )

        # No CHoCH yet
        return ConfirmationSignal(
            status=ConfirmationStatus.MONITORING,
            daily_bias=bias,
            choch_level=choch_level,
            swing_points_tracked=len(swings),
            time_since_sweep_minutes=elapsed,
        )

    # -- Internal --

    def _find_m1_swings(self, candles: list[Candle]) -> list[SwingPoint]:
        """Find swing highs and lows on M1 data."""
        swings: list[SwingPoint] = []
        lb = self.swing_lookback

        for i in range(lb, len(candles) - lb):
            c = candles[i]

            is_high = all(
                c.high > candles[i - j].high and c.high > candles[i + j].high
                for j in range(1, lb + 1)
            )
            is_low = all(
                c.low < candles[i - j].low and c.low < candles[i + j].low
                for j in range(1, lb + 1)
            )

            if is_high:
                swings.append(SwingPoint(price=c.high, time=c.time, type="SH"))
            if is_low:
                swings.append(SwingPoint(price=c.low, time=c.time, type="SL"))

        return swings

    def _find_choch_level(
        self, swings: list[SwingPoint], bias: Bias
    ) -> tuple[float | None, str | None]:
        """Find the M1 swing level that, if broken, confirms CHoCH.

        For BULLISH bias (M1 in downtrend after sweep): last swing high is the key level.
        For BEARISH bias (M1 in uptrend after sweep): last swing low is the key level.
        """
        if bias == Bias.BULLISH:
            # After sweeping Asian low, M1 is bearish → find last swing high
            for sp in reversed(swings):
                if sp.type == "SH":
                    return sp.price, "SH"
        elif bias == Bias.BEARISH:
            for sp in reversed(swings):
                if sp.type == "SL":
                    return sp.price, "SL"

        return None, None

    def _get_post_sweep_extreme(self, candles: list[Candle], bias: Bias) -> float | None:
        """Get the extreme price reached after the sweep (used for context)."""
        if not candles:
            return None
        if bias == Bias.BULLISH:
            return min(c.low for c in candles)
        return max(c.high for c in candles)
