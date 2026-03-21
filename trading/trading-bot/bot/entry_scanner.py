"""Entry Signal Scanner — 4-step reversal entry algorithm."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from .models import (
    Candle,
    MarketStructureShift,
    SRZone,
    SetupLog,
    SetupState,
    SwingClassification,
    SwingPoint,
    TradeSignal,
    TrendDirection,
    TrendState,
)

logger = logging.getLogger(__name__)


class EntrySignalScanner:
    """Executes the 4-step reversal entry algorithm."""

    def __init__(
        self,
        confirmation_candle_body_pct: float = 0.60,
        confirmation_candle_min_range: float = 3.0,
        trigger_expiry_bars: int = 5,
        max_trigger_distance: float = 5.0,
        confirmation_timeout_bars: int = 10,
        impulse_min_points: float = 8.0,
        risk_reward_minimum: float = 3.0,
        zone_proximity: float = 3.0,
    ) -> None:
        self.conf_body_pct = confirmation_candle_body_pct
        self.conf_min_range = confirmation_candle_min_range
        self.trigger_expiry_bars = trigger_expiry_bars
        self.max_trigger_distance = max_trigger_distance
        self.conf_timeout_bars = confirmation_timeout_bars
        self.impulse_min_points = impulse_min_points
        self.rr_minimum = risk_reward_minimum
        self.zone_proximity = zone_proximity

        self._state = SetupState.IDLE
        self._setup_number = 0
        self._daily_attempts = 0
        self._max_daily_attempts = 2

        # Step tracking
        self._impulse_direction: str | None = None  # "up" or "down"
        self._impulse_start_price: float | None = None
        self._impulse_end_price: float | None = None
        self._mss_event: MarketStructureShift | None = None
        self._mss_zone: SRZone | None = None
        self._confirmation_candle: Candle | None = None
        self._trigger_bar_count = 0

        # Logs
        self._setup_logs: list[SetupLog] = []
        self._current_steps: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def state(self) -> SetupState:
        return self._state

    @property
    def daily_attempts(self) -> int:
        return self._daily_attempts

    def on_candle(
        self,
        candle: Candle,
        trend: TrendState,
        mss: MarketStructureShift | None,
        nearby_zone: SRZone | None,
        current_price: float,
    ) -> TradeSignal | None:
        """Process a new 1m candle through the state machine. Returns signal if triggered."""

        if self._daily_attempts >= self._max_daily_attempts:
            return None

        if self._state == SetupState.IDLE:
            return self._step1_impulse(candle, trend)

        elif self._state == SetupState.IMPULSE_DETECTED:
            return self._step2_mss_at_zone(candle, mss, nearby_zone)

        elif self._state == SetupState.MSS_AT_ZONE:
            return self._step3_confirmation(candle)

        elif self._state == SetupState.CONFIRMATION:
            return self._step4_trigger(candle, current_price)

        elif self._state == SetupState.TRIGGER_ACTIVE:
            return self._step4_trigger(candle, current_price)

        return None

    def get_setup_logs(self) -> list[SetupLog]:
        return list(self._setup_logs)

    def reset(self) -> None:
        """Reset for new session."""
        self._state = SetupState.IDLE
        self._setup_number = 0
        self._daily_attempts = 0
        self._impulse_direction = None
        self._impulse_start_price = None
        self._impulse_end_price = None
        self._mss_event = None
        self._mss_zone = None
        self._confirmation_candle = None
        self._trigger_bar_count = 0
        self._setup_logs.clear()
        self._current_steps.clear()

    def set_max_attempts(self, max_attempts: int) -> None:
        self._max_daily_attempts = max_attempts

    # ------------------------------------------------------------------
    # Step 1: Detect strong morning impulse
    # ------------------------------------------------------------------
    def _step1_impulse(
        self, candle: Candle, trend: TrendState
    ) -> TradeSignal | None:
        if trend.direction == TrendDirection.UNKNOWN:
            return None
        if trend.direction == TrendDirection.CONSOLIDATION:
            return None

        # Need at least 3 directional swing points
        if trend.swing_count < 3:
            return None

        # Calculate impulse size from session open
        swings = trend.swing_sequence
        if trend.direction == TrendDirection.UP:
            lows = [s.price for s in swings if s.swing_type == "low"]
            highs = [s.price for s in swings if s.swing_type == "high"]
            if lows and highs:
                impulse_size = max(highs) - min(lows)
                if impulse_size >= self.impulse_min_points:
                    self._impulse_direction = "up"
                    self._impulse_start_price = min(lows)
                    self._impulse_end_price = max(highs)
                    self._state = SetupState.IMPULSE_DETECTED
                    self._current_steps = ["step1_impulse"]
                    logger.info(
                        "STEP 1 — Impulse UP detected: +%.1f pts", impulse_size
                    )

        elif trend.direction == TrendDirection.DOWN:
            lows = [s.price for s in swings if s.swing_type == "low"]
            highs = [s.price for s in swings if s.swing_type == "high"]
            if lows and highs:
                impulse_size = max(highs) - min(lows)
                if impulse_size >= self.impulse_min_points:
                    self._impulse_direction = "down"
                    self._impulse_start_price = max(highs)
                    self._impulse_end_price = min(lows)
                    self._state = SetupState.IMPULSE_DETECTED
                    self._current_steps = ["step1_impulse"]
                    logger.info(
                        "STEP 1 — Impulse DOWN detected: -%.1f pts", impulse_size
                    )

        return None

    # ------------------------------------------------------------------
    # Step 2: MSS at key zone
    # ------------------------------------------------------------------
    def _step2_mss_at_zone(
        self,
        candle: Candle,
        mss: MarketStructureShift | None,
        nearby_zone: SRZone | None,
    ) -> TradeSignal | None:
        if mss is None:
            return None

        # For uptrend impulse, we need bearish MSS at resistance
        if self._impulse_direction == "up" and mss.direction != "bearish":
            return None
        if self._impulse_direction == "down" and mss.direction != "bullish":
            return None

        # MSS must be near a key zone
        if nearby_zone is None:
            logger.info("MSS detected but no nearby S/R zone — ignoring")
            return None

        # Validate zone type matches
        if self._impulse_direction == "up" and nearby_zone.zone_type != "resistance":
            return None
        if self._impulse_direction == "down" and nearby_zone.zone_type != "support":
            return None

        self._mss_event = mss
        self._mss_zone = nearby_zone
        self._state = SetupState.MSS_AT_ZONE
        self._current_steps.append("step2_mss_at_zone")
        self._trigger_bar_count = 0
        logger.info(
            "STEP 2 — %s MSS at %s zone (%.2f–%.2f)",
            mss.direction.upper(),
            nearby_zone.zone_type,
            nearby_zone.price_low,
            nearby_zone.price_high,
        )
        return None

    # ------------------------------------------------------------------
    # Step 3: Confirmation candle
    # ------------------------------------------------------------------
    def _step3_confirmation(self, candle: Candle) -> TradeSignal | None:
        self._trigger_bar_count += 1

        # Timeout check
        if self._trigger_bar_count > self.conf_timeout_bars:
            logger.info("STEP 3 EXPIRED — No confirmation candle within %d bars", self.conf_timeout_bars)
            self._expire_setup("No confirmation candle within timeout")
            return None

        # For bearish MSS → need large bearish candle
        if self._mss_event and self._mss_event.direction == "bearish":
            if (
                candle.is_bearish
                and candle.body_pct >= self.conf_body_pct
                and candle.range_size >= self.conf_min_range
            ):
                self._confirmation_candle = candle
                self._state = SetupState.CONFIRMATION
                self._current_steps.append("step3_confirmation")
                self._trigger_bar_count = 0
                logger.info(
                    "STEP 3 — Bearish confirmation candle: range=%.1f, body=%.0f%%",
                    candle.range_size,
                    candle.body_pct * 100,
                )
                # Immediately transition to trigger active
                self._state = SetupState.TRIGGER_ACTIVE
                return None

        # For bullish MSS → need large bullish candle
        if self._mss_event and self._mss_event.direction == "bullish":
            if (
                candle.is_bullish
                and candle.body_pct >= self.conf_body_pct
                and candle.range_size >= self.conf_min_range
            ):
                self._confirmation_candle = candle
                self._state = SetupState.CONFIRMATION
                self._current_steps.append("step3_confirmation")
                self._trigger_bar_count = 0
                logger.info(
                    "STEP 3 — Bullish confirmation candle: range=%.1f, body=%.0f%%",
                    candle.range_size,
                    candle.body_pct * 100,
                )
                self._state = SetupState.TRIGGER_ACTIVE
                return None

        return None

    # ------------------------------------------------------------------
    # Step 4: Trigger entry
    # ------------------------------------------------------------------
    def _step4_trigger(
        self, candle: Candle, current_price: float
    ) -> TradeSignal | None:
        self._trigger_bar_count += 1

        if self._trigger_bar_count > self.trigger_expiry_bars:
            logger.info("STEP 4 EXPIRED — Trigger not hit within %d bars", self.trigger_expiry_bars)
            self._expire_setup("Trigger not hit within expiry window")
            return None

        if self._confirmation_candle is None or self._mss_event is None:
            self._expire_setup("Missing confirmation candle or MSS")
            return None

        # Determine entry direction and trigger level
        if self._mss_event.direction == "bearish":
            # SHORT: trigger = low of confirmation candle
            trigger_price = self._confirmation_candle.low - 0.25  # minus 1 tick
            direction = "short"
            stop_loss = self._mss_event.invalidation_price + 0.50  # buffer
            risk = stop_loss - trigger_price

            if candle.low <= trigger_price:
                entry_price = trigger_price
                target = entry_price - (risk * self.rr_minimum)
                return self._generate_signal(
                    direction, entry_price, stop_loss, target, risk, candle
                )

        elif self._mss_event.direction == "bullish":
            # LONG: trigger = high of confirmation candle
            trigger_price = self._confirmation_candle.high + 0.25  # plus 1 tick
            direction = "long"
            stop_loss = self._mss_event.invalidation_price - 0.50  # buffer
            risk = trigger_price - stop_loss

            if candle.high >= trigger_price:
                entry_price = trigger_price
                target = entry_price + (risk * self.rr_minimum)
                return self._generate_signal(
                    direction, entry_price, stop_loss, target, risk, candle
                )

        # Check if trigger level is too far from current price
        if self._mss_event.direction == "bearish":
            trigger_price = self._confirmation_candle.low - 0.25
        else:
            trigger_price = self._confirmation_candle.high + 0.25
        if abs(current_price - trigger_price) > self.max_trigger_distance:
            logger.info("Trigger too far from price (%.1f pts) — discarding", abs(current_price - trigger_price))
            self._expire_setup("Trigger level too far from current price")
            return None

        return None

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------
    def _generate_signal(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        risk: float,
        candle: Candle,
    ) -> TradeSignal | None:
        reward = abs(target - entry_price)
        rr = reward / risk if risk > 0 else 0

        if rr < self.rr_minimum:
            logger.info("R:R %.1f below minimum %.1f — rejecting", rr, self.rr_minimum)
            self._expire_setup(f"R:R {rr:.1f} below minimum")
            return None

        # Determine quality
        quality: str = "B"
        if self._mss_event and self._mss_event.confidence == "high":
            if self._mss_zone and self._mss_zone.strength.value == "S":
                quality = "A+"
            else:
                quality = "A"

        signal = TradeSignal(
            signal_id=uuid.uuid4().hex[:12],
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target,
            risk_points=risk,
            reward_points=reward,
            risk_reward_ratio=rr,
            confirmation_candle_ts=(
                self._confirmation_candle.timestamp
                if self._confirmation_candle
                else None
            ),
            trigger_expiry=candle.timestamp + timedelta(minutes=self.trigger_expiry_bars),
            sr_zone_id=self._mss_zone.zone_id if self._mss_zone else "",
            mss_direction=self._mss_event.direction if self._mss_event else "",
            setup_quality=quality,
        )

        self._state = SetupState.TRIGGERED
        self._current_steps.append("step4_triggered")
        self._daily_attempts += 1
        self._setup_number += 1

        self._setup_logs.append(
            SetupLog(
                session_date=candle.timestamp.date(),
                setup_number=self._setup_number,
                steps_completed=list(self._current_steps),
                signal=signal,
                notes=f"Triggered {direction} at {entry_price:.2f}",
            )
        )

        logger.info(
            "STEP 4 — TRIGGERED %s at %.2f | SL %.2f | TP %.2f | R:R 1:%.1f | Quality %s",
            direction.upper(),
            entry_price,
            stop_loss,
            target,
            rr,
            quality,
        )

        # Reset state for next potential setup
        self._reset_setup_state()
        return signal

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _expire_setup(self, reason: str) -> None:
        self._setup_number += 1
        self._setup_logs.append(
            SetupLog(
                session_date=datetime.now().date(),
                setup_number=self._setup_number,
                steps_completed=list(self._current_steps),
                failure_reason=reason,
                notes=reason,
            )
        )
        self._reset_setup_state()

    def _reset_setup_state(self) -> None:
        self._state = SetupState.IDLE
        self._impulse_direction = None
        self._impulse_start_price = None
        self._impulse_end_price = None
        self._mss_event = None
        self._mss_zone = None
        self._confirmation_candle = None
        self._trigger_bar_count = 0
        self._current_steps = []
