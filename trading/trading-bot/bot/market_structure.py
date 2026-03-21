"""Market Structure Analyzer — ZigZag swing detection, trend classification, MSS."""

from __future__ import annotations

import logging
from datetime import datetime

from .models import (
    Candle,
    MarketStructureShift,
    SwingClassification,
    SwingPoint,
    TrendDirection,
    TrendState,
)

logger = logging.getLogger(__name__)


class MarketStructureAnalyzer:
    """Detects swing highs/lows via ZigZag, classifies trend, emits MSS events."""

    def __init__(
        self,
        depth_1m: int = 3,
        depth_15m: int = 2,
        min_swing_distance: float = 2.0,
        lookback_swings: int = 6,
    ) -> None:
        self.depth_1m = depth_1m
        self.depth_15m = depth_15m
        self.min_swing_distance = min_swing_distance
        self.lookback_swings = lookback_swings

        # Candle buffers per timeframe
        self._candles: dict[str, list[Candle]] = {"1m": [], "15m": []}
        # Confirmed swing points per timeframe
        self._swings: dict[str, list[SwingPoint]] = {"1m": [], "15m": []}
        # Trend state per timeframe
        self._trend: dict[str, TrendState] = {
            "1m": TrendState(direction=TrendDirection.UNKNOWN),
            "15m": TrendState(direction=TrendDirection.UNKNOWN),
        }
        # Pending (unconfirmed) MSS
        self._pending_mss: MarketStructureShift | None = None
        # Confirmed MSS events
        self.mss_events: list[MarketStructureShift] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def on_candle(self, candle: Candle) -> list[SwingPoint | MarketStructureShift]:
        """Process a new candle. Returns any new confirmed swings or MSS events."""
        tf = candle.timeframe
        self._candles[tf].append(candle)

        events: list[SwingPoint | MarketStructureShift] = []
        depth = self.depth_1m if tf == "1m" else self.depth_15m

        # Need at least 2*depth + 1 candles to confirm a swing
        if len(self._candles[tf]) < 2 * depth + 1:
            return events

        # Check if the candle at position -depth-1 is a swing point
        pivot_idx = len(self._candles[tf]) - depth - 1
        pivot = self._candles[tf][pivot_idx]

        swing = self._detect_swing(pivot, pivot_idx, tf, depth)
        if swing is not None:
            # Classify the swing relative to prior swings
            swing = self._classify_swing(swing, tf)
            self._swings[tf].append(swing)

            # Trim to lookback window
            if len(self._swings[tf]) > self.lookback_swings:
                self._swings[tf] = self._swings[tf][-self.lookback_swings:]

            # Update trend
            self._update_trend(tf)
            events.append(swing)
            logger.info(
                "%s swing %s: %s at %.2f [%s]",
                tf,
                swing.swing_type,
                swing.classification.value,
                swing.price,
                swing.timestamp.strftime("%H:%M:%S"),
            )

            # Check for MSS on 1m only
            if tf == "1m":
                mss = self._check_mss()
                if mss is not None:
                    self.mss_events.append(mss)
                    events.append(mss)
                    logger.info(
                        "MSS CONFIRMED — %s, trigger %.2f, invalidation %.2f",
                        mss.direction,
                        mss.trigger_swing.price,
                        mss.invalidation_price,
                    )

        return events

    def get_trend(self, timeframe: str = "1m") -> TrendState:
        return self._trend[timeframe]

    def get_swings(self, timeframe: str = "1m") -> list[SwingPoint]:
        return list(self._swings[timeframe])

    def get_last_mss(self) -> MarketStructureShift | None:
        if self.mss_events:
            return self.mss_events[-1]
        return None

    def reset(self) -> None:
        """Reset state for a new session."""
        for tf in ("1m", "15m"):
            self._candles[tf].clear()
            self._swings[tf].clear()
            self._trend[tf] = TrendState(direction=TrendDirection.UNKNOWN)
        self._pending_mss = None
        self.mss_events.clear()

    # ------------------------------------------------------------------
    # Swing detection
    # ------------------------------------------------------------------
    def _detect_swing(
        self, pivot: Candle, pivot_idx: int, tf: str, depth: int
    ) -> SwingPoint | None:
        candles = self._candles[tf]

        # Check swing high
        is_high = True
        for i in range(1, depth + 1):
            left = candles[pivot_idx - i]
            right = candles[pivot_idx + i]
            if pivot.high <= left.high or pivot.high <= right.high:
                is_high = False
                break

        # Check swing low
        is_low = True
        for i in range(1, depth + 1):
            left = candles[pivot_idx - i]
            right = candles[pivot_idx + i]
            if pivot.low >= left.low or pivot.low >= right.low:
                is_low = False
                break

        # If both, pick the more pronounced one
        if is_high and is_low:
            high_diff = pivot.high - max(
                candles[pivot_idx - 1].high, candles[pivot_idx + 1].high
            )
            low_diff = min(
                candles[pivot_idx - 1].low, candles[pivot_idx + 1].low
            ) - pivot.low
            if high_diff >= low_diff:
                is_low = False
            else:
                is_high = False

        if not is_high and not is_low:
            return None

        # Min distance filter
        existing = self._swings[tf]
        if existing:
            last = existing[-1]
            price = pivot.high if is_high else pivot.low
            if abs(price - last.price) < self.min_swing_distance:
                # Skip if too close AND same type
                if (is_high and last.swing_type == "high") or (
                    is_low and last.swing_type == "low"
                ):
                    return None

        swing_type = "high" if is_high else "low"
        price = pivot.high if is_high else pivot.low

        return SwingPoint(
            timestamp=pivot.timestamp,
            price=price,
            swing_type=swing_type,
            classification=SwingClassification.INITIAL,
            timeframe=tf,
            confirmed=True,
            bar_index=pivot.bar_index,
        )

    def _classify_swing(self, swing: SwingPoint, tf: str) -> SwingPoint:
        """Classify swing relative to prior swing of same type."""
        same_type = [s for s in self._swings[tf] if s.swing_type == swing.swing_type]
        if not same_type:
            swing.classification = SwingClassification.INITIAL
            return swing

        prev = same_type[-1]
        if swing.swing_type == "high":
            swing.classification = (
                SwingClassification.HH
                if swing.price > prev.price
                else SwingClassification.LH
            )
        else:
            swing.classification = (
                SwingClassification.HL
                if swing.price > prev.price
                else SwingClassification.LL
            )
        return swing

    # ------------------------------------------------------------------
    # Trend classification
    # ------------------------------------------------------------------
    def _update_trend(self, tf: str) -> None:
        swings = self._swings[tf]
        if len(swings) < 4:
            self._trend[tf] = TrendState(
                direction=TrendDirection.UNKNOWN,
                swing_sequence=list(swings),
                last_updated=swings[-1].timestamp if swings else None,
            )
            return

        recent = swings[-4:]
        highs = [s for s in recent if s.swing_type == "high"]
        lows = [s for s in recent if s.swing_type == "low"]

        all_hh = all(s.classification == SwingClassification.HH for s in highs) if highs else False
        all_hl = all(s.classification == SwingClassification.HL for s in lows) if lows else False
        all_lh = all(s.classification == SwingClassification.LH for s in highs) if highs else False
        all_ll = all(s.classification == SwingClassification.LL for s in lows) if lows else False

        if all_hh and all_hl:
            direction = TrendDirection.UP
        elif all_lh and all_ll:
            direction = TrendDirection.DOWN
        else:
            direction = TrendDirection.CONSOLIDATION

        self._trend[tf] = TrendState(
            direction=direction,
            swing_sequence=list(swings),
            last_updated=swings[-1].timestamp,
        )

    # ------------------------------------------------------------------
    # Market Structure Shift detection
    # ------------------------------------------------------------------
    def _check_mss(self) -> MarketStructureShift | None:
        swings = self._swings["1m"]
        if len(swings) < 4:
            return None

        # Look at the last few swings for a structural break
        # Bearish MSS: was uptrend, now see LL followed by LH
        # Bullish MSS: was downtrend, now see HH followed by HL

        recent_lows = [s for s in swings if s.swing_type == "low"]
        recent_highs = [s for s in swings if s.swing_type == "high"]

        if len(recent_lows) < 2 or len(recent_highs) < 2:
            return None

        last_high = recent_highs[-1]
        prev_high = recent_highs[-2]
        last_low = recent_lows[-1]
        prev_low = recent_lows[-2]

        # Bearish MSS: price was making HH/HL, now prints LL then LH
        if (
            last_low.classification == SwingClassification.LL
            and last_high.classification == SwingClassification.LH
            and last_high.timestamp > last_low.timestamp  # LH comes after LL
        ):
            # Check that prior structure was bullish
            if prev_high.classification in (
                SwingClassification.HH,
                SwingClassification.INITIAL,
            ):
                # Invalidation is above the last HH
                invalidation = prev_high.price
                # Check confidence — align with 15m
                confidence = self._mss_confidence("bearish")
                return MarketStructureShift(
                    direction="bearish",
                    trigger_swing=last_low,
                    confirmation_swing=last_high,
                    invalidation_price=invalidation,
                    timestamp=last_high.timestamp,
                    confidence=confidence,
                )

        # Bullish MSS: price was making LL/LH, now prints HH then HL
        if (
            last_high.classification == SwingClassification.HH
            and last_low.classification == SwingClassification.HL
            and last_low.timestamp > last_high.timestamp  # HL comes after HH
        ):
            if prev_low.classification in (
                SwingClassification.LL,
                SwingClassification.INITIAL,
            ):
                invalidation = prev_low.price
                confidence = self._mss_confidence("bullish")
                return MarketStructureShift(
                    direction="bullish",
                    trigger_swing=last_high,
                    confirmation_swing=last_low,
                    invalidation_price=invalidation,
                    timestamp=last_low.timestamp,
                    confidence=confidence,
                )

        return None

    def _mss_confidence(
        self, direction: str
    ) -> str:
        """Check if the MSS aligns with 15m structure for confidence rating."""
        trend_15m = self._trend["15m"]
        # Bearish MSS at 15m resistance area = high confidence
        if direction == "bearish" and trend_15m.direction in (
            TrendDirection.UP,
            TrendDirection.CONSOLIDATION,
        ):
            return "high"
        if direction == "bullish" and trend_15m.direction in (
            TrendDirection.DOWN,
            TrendDirection.CONSOLIDATION,
        ):
            return "high"
        return "medium"
