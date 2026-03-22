"""Step 3: LTF Execution Engine.

Monitors the Lower Timeframe for the three required confluences:
1. Liquidity Sweep
2. Market Structure Shift (MSS)
3. Rejection / Displacement pattern

Only produces an EntrySignal when all three fire in sequence.
"""

from __future__ import annotations

import structlog

from models import (
    Bias,
    Candle,
    EntrySignal,
    FairValueGap,
    MSSEvent,
    OrderBlock,
    RejectionEvent,
    RejectionPattern,
    SweepEvent,
    SwingPoint,
    SwingType,
)

logger = structlog.get_logger(__name__)


class LTFExecutionEngine:
    """Confirms entries on the Lower Timeframe with 3 confluences."""

    def __init__(
        self,
        swing_lookback: int = 3,
        max_confluence_window: int = 12,
        pin_bar_wick_ratio: float = 0.6,
        displacement_body_multiplier: float = 2.0,
    ):
        self.swing_lookback = swing_lookback
        self.max_confluence_window = max_confluence_window
        self.pin_bar_wick_ratio = pin_bar_wick_ratio
        self.displacement_body_multiplier = displacement_body_multiplier

        self._sweep: SweepEvent | None = None
        self._mss: MSSEvent | None = None
        self._rejection: RejectionEvent | None = None
        self._candles_since_sweep: int = 0
        self._active = False
        self._direction: Bias | None = None
        self._poi: OrderBlock | None = None

    def activate(self, direction: Bias, poi: OrderBlock) -> None:
        """Start monitoring LTF after POI is touched."""
        self.reset()
        self._active = True
        self._direction = direction
        self._poi = poi
        logger.info("ltf.activated", direction=direction.value, poi_type=poi.type.value)

    def process_candle(self, candles: list[Candle]) -> EntrySignal | None:
        """Process new LTF candles, checking for confluences in order.

        Returns EntrySignal when all 3 confluences are confirmed.
        Returns None if still waiting or if setup is aborted.
        """
        if not self._active or self._direction is None or self._poi is None:
            return None

        if len(candles) < self.swing_lookback * 2 + 3:
            return None

        # Track time since sweep
        if self._sweep is not None:
            self._candles_since_sweep += 1
            if self._candles_since_sweep > self.max_confluence_window:
                logger.info("ltf.confluence_timeout")
                self.reset()
                return None

        # Step through confluences in order
        if self._sweep is None:
            self._check_sweep(candles)
            return None

        if self._mss is None:
            self._check_mss(candles)
            return None

        if self._rejection is None:
            self._check_rejection(candles)

        if self._rejection is not None:
            return self._build_entry_signal()

        return None

    def check_passthrough(self, candles: list[Candle]) -> bool:
        """Check if price passed through the POI without any reaction.

        Returns True if the POI should be invalidated.
        """
        if self._poi is None or not self._active:
            return False

        latest = candles[-1]

        if self._direction == Bias.LONG:
            # For a LONG setup, if price closes well below the demand zone
            if latest.close < self._poi.low:
                logger.info("ltf.poi_passthrough", direction="LONG")
                return True
        elif self._direction == Bias.SHORT:
            # For a SHORT setup, if price closes well above the supply zone
            if latest.close > self._poi.high:
                logger.info("ltf.poi_passthrough", direction="SHORT")
                return True

        return False

    # ── Confluence checks ──────────────────────────────────────

    def _check_sweep(self, candles: list[Candle]) -> None:
        """Confluence 1: Detect liquidity sweep (false breakout)."""
        swing_points = self._detect_ltf_swings(candles)
        latest = candles[-1]

        if self._direction == Bias.LONG:
            local_lows = [sp for sp in swing_points if sp.type == SwingType.LOW]
            if not local_lows:
                return
            last_low = local_lows[-1]
            # Wick below the low, but close above it
            if latest.low < last_low.price and latest.close > last_low.price:
                self._sweep = SweepEvent(
                    direction=Bias.LONG,
                    sweep_extreme=latest.low,
                    level_swept=last_low.price,
                    candle=latest,
                )
                self._candles_since_sweep = 0
                logger.info("ltf.sweep_detected", direction="LONG", swept=last_low.price)

        elif self._direction == Bias.SHORT:
            local_highs = [sp for sp in swing_points if sp.type == SwingType.HIGH]
            if not local_highs:
                return
            last_high = local_highs[-1]
            if latest.high > last_high.price and latest.close < last_high.price:
                self._sweep = SweepEvent(
                    direction=Bias.SHORT,
                    sweep_extreme=latest.high,
                    level_swept=last_high.price,
                    candle=latest,
                )
                self._candles_since_sweep = 0
                logger.info("ltf.sweep_detected", direction="SHORT", swept=last_high.price)

    def _check_mss(self, candles: list[Candle]) -> None:
        """Confluence 2: Detect Market Structure Shift after sweep."""
        swing_points = self._detect_ltf_swings(candles)
        latest = candles[-1]

        if self._direction == Bias.LONG:
            local_highs = [sp for sp in swing_points if sp.type == SwingType.HIGH]
            if not local_highs:
                return
            last_high = local_highs[-1]
            if latest.close > last_high.price:
                self._mss = MSSEvent(
                    direction=Bias.LONG,
                    broken_level=last_high.price,
                    confirmation_close=latest.close,
                    candle=latest,
                )
                logger.info("ltf.mss_detected", direction="LONG", level=last_high.price)

        elif self._direction == Bias.SHORT:
            local_lows = [sp for sp in swing_points if sp.type == SwingType.LOW]
            if not local_lows:
                return
            last_low = local_lows[-1]
            if latest.close < last_low.price:
                self._mss = MSSEvent(
                    direction=Bias.SHORT,
                    broken_level=last_low.price,
                    confirmation_close=latest.close,
                    candle=latest,
                )
                logger.info("ltf.mss_detected", direction="SHORT", level=last_low.price)

    def _check_rejection(self, candles: list[Candle]) -> None:
        """Confluence 3: Detect rejection/displacement pattern."""
        if len(candles) < 3:
            return

        current = candles[-1]
        previous = candles[-2]
        before = candles[-3]

        avg_body = self._average_body_size(candles[-20:])

        # ── Engulfing ──
        if self._direction == Bias.LONG:
            if (
                current.is_bullish
                and current.open <= previous.body_low
                and current.close >= previous.body_high
            ):
                self._rejection = RejectionEvent(
                    pattern=RejectionPattern.BULLISH_ENGULFING, candle=current
                )
                logger.info("ltf.rejection", pattern="BULLISH_ENGULFING")
                return
        elif self._direction == Bias.SHORT:
            if (
                current.is_bearish
                and current.open >= previous.body_high
                and current.close <= previous.body_low
            ):
                self._rejection = RejectionEvent(
                    pattern=RejectionPattern.BEARISH_ENGULFING, candle=current
                )
                logger.info("ltf.rejection", pattern="BEARISH_ENGULFING")
                return

        # ── Pin Bar ──
        if current.total_range > 0:
            wick_ratio = (current.total_range - current.body) / current.total_range
            if wick_ratio >= self.pin_bar_wick_ratio:
                if self._direction == Bias.LONG and current.is_bullish:
                    self._rejection = RejectionEvent(
                        pattern=RejectionPattern.BULLISH_PIN_BAR, candle=current
                    )
                    logger.info("ltf.rejection", pattern="BULLISH_PIN_BAR")
                    return
                if self._direction == Bias.SHORT and current.is_bearish:
                    self._rejection = RejectionEvent(
                        pattern=RejectionPattern.BEARISH_PIN_BAR, candle=current
                    )
                    logger.info("ltf.rejection", pattern="BEARISH_PIN_BAR")
                    return

        # ── Displacement (large body + FVG) ──
        if current.body > avg_body * self.displacement_body_multiplier:
            fvg = None
            if self._direction == Bias.LONG and current.is_bullish:
                if current.low > before.high:
                    fvg = FairValueGap(
                        low=before.high,
                        high=current.low,
                        direction=Bias.LONG,
                        timestamp=current.timestamp,
                    )
                self._rejection = RejectionEvent(
                    pattern=RejectionPattern.BULLISH_DISPLACEMENT,
                    candle=current,
                    fvg=fvg,
                )
                logger.info("ltf.rejection", pattern="BULLISH_DISPLACEMENT", fvg=fvg is not None)
                return
            if self._direction == Bias.SHORT and current.is_bearish:
                if current.high < before.low:
                    fvg = FairValueGap(
                        low=current.high,
                        high=before.low,
                        direction=Bias.SHORT,
                        timestamp=current.timestamp,
                    )
                self._rejection = RejectionEvent(
                    pattern=RejectionPattern.BEARISH_DISPLACEMENT,
                    candle=current,
                    fvg=fvg,
                )
                logger.info("ltf.rejection", pattern="BEARISH_DISPLACEMENT", fvg=fvg is not None)
                return

    # ── Helpers ─────────────────────────────────────────────────

    def _build_entry_signal(self) -> EntrySignal | None:
        """Build the final entry signal from confirmed confluences."""
        if (
            self._sweep is None
            or self._mss is None
            or self._rejection is None
            or self._direction is None
            or self._poi is None
        ):
            return None

        entry_price = self._mss.broken_level

        if self._direction == Bias.LONG:
            stop_loss = self._sweep.sweep_extreme
        else:
            stop_loss = self._sweep.sweep_extreme

        signal = EntrySignal(
            direction=self._direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            sweep=self._sweep,
            mss=self._mss,
            rejection=self._rejection,
            poi=self._poi,
        )

        logger.info(
            "ltf.entry_signal",
            direction=self._direction.value,
            entry=entry_price,
            sl=stop_loss,
            pattern=self._rejection.pattern.value,
        )

        self._active = False
        return signal

    def _detect_ltf_swings(self, candles: list[Candle]) -> list[SwingPoint]:
        """Detect swing points on the LTF."""
        swings: list[SwingPoint] = []
        lb = self.swing_lookback

        for i in range(lb, len(candles) - lb):
            is_high = all(
                candles[i].high > candles[i - j].high and candles[i].high > candles[i + j].high
                for j in range(1, lb + 1)
            )
            if is_high:
                swings.append(
                    SwingPoint(SwingType.HIGH, candles[i].high, candles[i].timestamp, i)
                )

            is_low = all(
                candles[i].low < candles[i - j].low and candles[i].low < candles[i + j].low
                for j in range(1, lb + 1)
            )
            if is_low:
                swings.append(
                    SwingPoint(SwingType.LOW, candles[i].low, candles[i].timestamp, i)
                )

        return swings

    @staticmethod
    def _average_body_size(candles: list[Candle]) -> float:
        """Average candle body size for displacement detection."""
        if not candles:
            return 0.0
        return sum(c.body for c in candles) / len(candles)

    def reset(self) -> None:
        """Clear all confluence state."""
        self._sweep = None
        self._mss = None
        self._rejection = None
        self._candles_since_sweep = 0
        self._active = False
        self._direction = None
        self._poi = None
