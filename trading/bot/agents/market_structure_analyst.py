"""Step 1: Market Structure Analyst — determines daily bias on M15 via CHoCH detection."""

from __future__ import annotations

from loguru import logger

from trading.bot.models import Bias, BiasSignal, Candle, SwingPoint


class MarketStructureAnalyst:
    """Analyzes M15 candles to determine daily directional bias.

    Identifies swing highs/lows, determines trend direction, and detects
    Change of Character (CHoCH) — the moment the prevailing structure breaks.
    """

    def __init__(self, swing_lookback: int = 3) -> None:
        self.swing_lookback = swing_lookback

    def analyze(self, candles: list[Candle]) -> BiasSignal:
        """Run full M15 analysis and return a BiasSignal.

        Args:
            candles: M15 OHLCV candles, minimum ~192 candles (48 hours).
        """
        if len(candles) < 20:
            logger.warning("Insufficient M15 data ({} candles), need at least 20", len(candles))
            return BiasSignal(bias=Bias.NEUTRAL, choch_confirmed=False, notes="Insufficient data")

        swing_points = self._find_swing_points(candles)

        if len(swing_points) < 3:
            logger.info("Only {} swing points found — structure unclear", len(swing_points))
            return BiasSignal(
                bias=Bias.NEUTRAL,
                choch_confirmed=False,
                swing_points=swing_points,
                notes="Not enough swing points to determine structure",
            )

        trend = self._determine_trend(swing_points)
        key_level, key_type = self._find_key_structural_level(swing_points, trend)

        choch_confirmed, choch_candle = self._detect_choch(candles, key_level, key_type, trend)

        if choch_confirmed:
            new_bias = Bias.BULLISH if trend == "bearish" else Bias.BEARISH
            invalidation = self._get_invalidation_level(swing_points, new_bias)
            logger.info(
                "CHoCH detected! {} trend broken at {}. New bias: {}",
                trend, key_level, new_bias.value,
            )
            return BiasSignal(
                bias=new_bias,
                choch_confirmed=True,
                choch_level=key_level,
                choch_candle_time=choch_candle.time if choch_candle else None,
                key_structural_high=self._get_latest_high(swing_points),
                key_structural_low=self._get_latest_low(swing_points),
                invalidation_level=invalidation,
                swing_points=swing_points,
                confidence="HIGH" if len(swing_points) >= 5 else "MEDIUM",
                notes=f"CHoCH above {'LH' if trend == 'bearish' else 'HL'} at {key_level}",
            )

        # No CHoCH — current trend holds
        bias = Bias.BEARISH if trend == "bearish" else Bias.BULLISH
        invalidation = self._get_invalidation_level(swing_points, bias)
        logger.info("No CHoCH — {} trend intact. Bias: {}", trend, bias.value)
        return BiasSignal(
            bias=bias,
            choch_confirmed=False,
            choch_level=key_level,
            key_structural_high=self._get_latest_high(swing_points),
            key_structural_low=self._get_latest_low(swing_points),
            invalidation_level=invalidation,
            swing_points=swing_points,
            confidence="MEDIUM",
            notes=f"Trend {trend}, key level at {key_level} not yet broken",
        )

    # -- Swing Point Detection --

    def _find_swing_points(self, candles: list[Candle]) -> list[SwingPoint]:
        """Identify swing highs and swing lows using lookback comparison."""
        swings: list[SwingPoint] = []
        lb = self.swing_lookback

        for i in range(lb, len(candles) - lb):
            candle = candles[i]

            # Swing High: high is greater than `lb` candles on each side
            is_swing_high = all(
                candle.high > candles[i - j].high and candle.high > candles[i + j].high
                for j in range(1, lb + 1)
            )
            # Swing Low: low is less than `lb` candles on each side
            is_swing_low = all(
                candle.low < candles[i - j].low and candle.low < candles[i + j].low
                for j in range(1, lb + 1)
            )

            if is_swing_high:
                swings.append(SwingPoint(price=candle.high, time=candle.time, type="SH"))
            if is_swing_low:
                swings.append(SwingPoint(price=candle.low, time=candle.time, type="SL"))

        # Label swing points as HH/HL/LH/LL
        self._label_swing_points(swings)
        return swings

    def _label_swing_points(self, swings: list[SwingPoint]) -> None:
        """Label each swing point relative to the previous swing of the same kind."""
        last_high: SwingPoint | None = None
        last_low: SwingPoint | None = None

        for sp in swings:
            if sp.type == "SH":
                if last_high is None:
                    sp.type = "HH"  # First high, assume higher
                elif sp.price > last_high.price:
                    sp.type = "HH"
                else:
                    sp.type = "LH"
                last_high = sp
            elif sp.type == "SL":
                if last_low is None:
                    sp.type = "HL"
                elif sp.price > last_low.price:
                    sp.type = "HL"
                else:
                    sp.type = "LL"
                last_low = sp

    # -- Trend Determination --

    def _determine_trend(self, swings: list[SwingPoint]) -> str:
        """Determine trend from the last few swing points.

        Returns 'bullish', 'bearish', or 'ranging'.
        """
        recent = swings[-6:] if len(swings) >= 6 else swings

        highs = [s for s in recent if s.type in ("HH", "LH")]
        lows = [s for s in recent if s.type in ("HL", "LL")]

        lh_count = sum(1 for s in highs if s.type == "LH")
        ll_count = sum(1 for s in lows if s.type == "LL")
        hh_count = sum(1 for s in highs if s.type == "HH")
        hl_count = sum(1 for s in lows if s.type == "HL")

        bearish_score = lh_count + ll_count
        bullish_score = hh_count + hl_count

        if bearish_score > bullish_score:
            return "bearish"
        if bullish_score > bearish_score:
            return "bullish"
        return "ranging"

    # -- Key Structural Level --

    def _find_key_structural_level(
        self, swings: list[SwingPoint], trend: str
    ) -> tuple[float, str]:
        """Find the key structural level that, if broken, signals a CHoCH.

        In a bearish trend: the last Lower High (LH) is the key level.
        In a bullish trend: the last Higher Low (HL) is the key level.
        """
        if trend == "bearish":
            for sp in reversed(swings):
                if sp.type == "LH":
                    return sp.price, "LH"
            # Fallback: last swing high
            for sp in reversed(swings):
                if sp.type in ("HH", "LH"):
                    return sp.price, sp.type
        else:
            for sp in reversed(swings):
                if sp.type == "HL":
                    return sp.price, "HL"
            for sp in reversed(swings):
                if sp.type in ("HL", "LL"):
                    return sp.price, sp.type

        # Ultimate fallback
        return swings[-1].price, swings[-1].type

    # -- CHoCH Detection --

    def _detect_choch(
        self,
        candles: list[Candle],
        key_level: float,
        key_type: str,
        trend: str,
    ) -> tuple[bool, Candle | None]:
        """Detect if a candle body has closed beyond the key structural level.

        For bearish trend: CHoCH if candle close > key LH level (buyers breaking through).
        For bullish trend: CHoCH if candle close < key HL level (sellers breaking through).
        """
        # Only check recent candles (last 20) for fresh CHoCH
        recent = candles[-20:]

        for candle in recent:
            if trend == "bearish" and key_type in ("LH", "HH"):
                if candle.close > key_level:
                    return True, candle
            elif trend == "bullish" and key_type in ("HL", "LL"):
                if candle.close < key_level:
                    return True, candle

        return False, None

    # -- Helpers --

    def _get_latest_high(self, swings: list[SwingPoint]) -> float | None:
        for sp in reversed(swings):
            if sp.type in ("HH", "LH"):
                return sp.price
        return None

    def _get_latest_low(self, swings: list[SwingPoint]) -> float | None:
        for sp in reversed(swings):
            if sp.type in ("HL", "LL"):
                return sp.price
        return None

    def _get_invalidation_level(self, swings: list[SwingPoint], bias: Bias) -> float | None:
        """The level where the current bias would be invalidated."""
        if bias == Bias.BULLISH:
            # Invalidation = most recent swing low
            return self._get_latest_low(swings)
        elif bias == Bias.BEARISH:
            return self._get_latest_high(swings)
        return None
