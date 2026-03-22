"""Step 1: HTF Market Structure Analyzer.

Scans Daily/4H candles for Swing Highs/Lows, detects Break of Structure (BOS),
determines directional bias, and fixes the active Swing Range.
"""

from __future__ import annotations

import structlog

from ..models import (
    BOSEvent,
    Bias,
    Candle,
    HTFAnalysis,
    SwingPoint,
    SwingRange,
    SwingType,
)

logger = structlog.get_logger(__name__)


class HTFStructureAnalyzer:
    """Determines market direction on the Higher Timeframe."""

    def __init__(self, swing_lookback: int = 3, min_bos_distance_pct: float = 0.5):
        self.swing_lookback = swing_lookback
        self.min_bos_distance_pct = min_bos_distance_pct
        self._swing_points: list[SwingPoint] = []
        self._last_bos: BOSEvent | None = None
        self._bias: Bias | None = None
        self._swing_range: SwingRange | None = None

    def analyze(self, candles: list[Candle]) -> HTFAnalysis | None:
        """Run full HTF analysis on a list of candles.

        Returns HTFAnalysis if a valid structure exists, None otherwise.
        """
        if len(candles) < self.swing_lookback * 2 + 1:
            logger.warning("htf.insufficient_data", count=len(candles))
            return None

        self._detect_swing_points(candles)

        if len(self._swing_points) < 2:
            logger.info("htf.insufficient_swings", count=len(self._swing_points))
            return None

        self._detect_bos(candles)

        if self._bias is None or self._swing_range is None or self._last_bos is None:
            return None

        valid = self._validate_structure(candles[-1])

        analysis = HTFAnalysis(
            bias=self._bias,
            swing_range=self._swing_range,
            last_bos=self._last_bos,
            swing_points=self._swing_points[-10:],
            structure_valid=valid,
        )
        logger.info(
            "htf.analysis_complete",
            bias=self._bias.value,
            range_low=self._swing_range.low,
            range_high=self._swing_range.high,
            valid=valid,
        )
        return analysis

    def _detect_swing_points(self, candles: list[Candle]) -> None:
        """Identify Swing Highs and Swing Lows."""
        self._swing_points = []
        lb = self.swing_lookback

        for i in range(lb, len(candles) - lb):
            # Check Swing High
            is_high = True
            for j in range(1, lb + 1):
                if candles[i - j].high >= candles[i].high or candles[i + j].high >= candles[i].high:
                    is_high = False
                    break
            if is_high:
                self._swing_points.append(
                    SwingPoint(
                        type=SwingType.HIGH,
                        price=candles[i].high,
                        timestamp=candles[i].timestamp,
                        index=i,
                    )
                )

            # Check Swing Low
            is_low = True
            for j in range(1, lb + 1):
                if candles[i - j].low <= candles[i].low or candles[i + j].low <= candles[i].low:
                    is_low = False
                    break
            if is_low:
                self._swing_points.append(
                    SwingPoint(
                        type=SwingType.LOW,
                        price=candles[i].low,
                        timestamp=candles[i].timestamp,
                        index=i,
                    )
                )

        self._swing_points.sort(key=lambda sp: sp.index)

    def _detect_bos(self, candles: list[Candle]) -> None:
        """Detect the most recent Break of Structure."""
        highs = [sp for sp in self._swing_points if sp.type == SwingType.HIGH]
        lows = [sp for sp in self._swing_points if sp.type == SwingType.LOW]

        if not highs or not lows:
            return

        # Scan from most recent candles backward to find latest BOS
        for i in range(len(candles) - 1, 0, -1):
            candle = candles[i]

            # Find the last swing high/low before this candle
            last_high = None
            last_low = None
            for sp in reversed(highs):
                if sp.index < i:
                    last_high = sp
                    break
            for sp in reversed(lows):
                if sp.index < i:
                    last_low = sp
                    break

            if last_high is None or last_low is None:
                continue

            min_distance_high = last_high.price * (self.min_bos_distance_pct / 100)
            min_distance_low = last_low.price * (self.min_bos_distance_pct / 100)

            # Bullish BOS: close above last swing high
            if candle.close > last_high.price + min_distance_high:
                self._last_bos = BOSEvent(
                    bias=Bias.LONG,
                    broken_level=last_high.price,
                    timestamp=candle.timestamp,
                )
                self._bias = Bias.LONG
                self._swing_range = SwingRange(
                    low=last_low.price,
                    high=candle.high,
                    bias=Bias.LONG,
                )
                return

            # Bearish BOS: close below last swing low
            if candle.close < last_low.price - min_distance_low:
                self._last_bos = BOSEvent(
                    bias=Bias.SHORT,
                    broken_level=last_low.price,
                    timestamp=candle.timestamp,
                )
                self._bias = Bias.SHORT
                self._swing_range = SwingRange(
                    low=candle.low,
                    high=last_high.price,
                    bias=Bias.SHORT,
                )
                return

    def _validate_structure(self, latest_candle: Candle) -> bool:
        """Check if the current structure is still valid.

        Structure is invalidated if price closes beyond the opposite end
        of the swing range.
        """
        if self._swing_range is None or self._bias is None:
            return False

        if self._bias == Bias.LONG and latest_candle.close < self._swing_range.low:
            logger.warning("htf.structure_invalidated", reason="close_below_range_low")
            return False

        if self._bias == Bias.SHORT and latest_candle.close > self._swing_range.high:
            logger.warning("htf.structure_invalidated", reason="close_above_range_high")
            return False

        return True

    def reset(self) -> None:
        """Clear all state for a fresh scan."""
        self._swing_points = []
        self._last_bos = None
        self._bias = None
        self._swing_range = None
