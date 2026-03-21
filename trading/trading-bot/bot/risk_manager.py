"""Risk Manager — position management, SL, break-even, trailing stop."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from .models import (
    Candle,
    ExitReason,
    Position,
    PositionStatus,
    SRZone,
    StopAdjustment,
    SwingPoint,
    TradeResult,
    TradeSignal,
    TrailPhase,
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages open positions with SL, break-even, and trailing stop logic."""

    def __init__(
        self,
        risk_per_trade_dollars: float = 100.0,
        risk_reward_minimum: float = 3.0,
        max_position_size: int = 1,
        breakeven_r_threshold: float = 1.0,
        aggressive_trail_r_threshold: float = 2.0,
        parabolic_candle_count: int = 3,
        zone_stall_timeout_bars: int = 3,
        stop_buffer_ticks: int = 2,
        tick_size: float = 0.25,
        point_value: float = 5.0,  # MES = $5/point (4 ticks × $1.25)
    ) -> None:
        self.risk_per_trade = risk_per_trade_dollars
        self.rr_minimum = risk_reward_minimum
        self.max_position_size = max_position_size
        self.be_r_threshold = breakeven_r_threshold
        self.aggressive_r_threshold = aggressive_trail_r_threshold
        self.parabolic_count = parabolic_candle_count
        self.zone_stall_bars = zone_stall_timeout_bars
        self.stop_buffer = stop_buffer_ticks * tick_size
        self.tick_size = tick_size
        self.point_value = point_value

        self._position: Position | None = None
        self._trade_results: list[TradeResult] = []
        self._daily_loss_count = 0
        self._max_daily_losses = 2
        self._max_favorable: float = 0.0
        self._max_adverse: float = 0.0

        # For parabolic detection
        self._recent_candles: list[Candle] = []
        # For zone stall detection
        self._zone_stall_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def has_position(self) -> bool:
        return self._position is not None

    @property
    def position(self) -> Position | None:
        return self._position

    @property
    def daily_losses(self) -> int:
        return self._daily_loss_count

    @property
    def can_take_trade(self) -> bool:
        return (
            not self.has_position
            and self._daily_loss_count < self._max_daily_losses
        )

    def open_position(self, signal: TradeSignal) -> Position | None:
        """Open a new position from a trade signal."""
        if not self.can_take_trade:
            logger.warning("Cannot open position — daily loss limit or existing position")
            return None

        # Validate R:R
        if signal.risk_reward_ratio < self.rr_minimum:
            logger.warning(
                "Rejecting signal — R:R %.1f below minimum %.1f",
                signal.risk_reward_ratio,
                self.rr_minimum,
            )
            return None

        # Calculate position size
        risk_points = signal.risk_points
        if risk_points <= 0:
            logger.warning("Invalid risk points: %.2f", risk_points)
            return None

        dollar_per_point = self.point_value
        contracts = min(
            int(self.risk_per_trade / (risk_points * dollar_per_point)),
            self.max_position_size,
        )
        contracts = max(contracts, 1)

        self._position = Position(
            position_id=uuid.uuid4().hex[:12],
            direction=signal.direction,
            entry_price=signal.entry_price,
            entry_time=signal.confirmation_candle_ts or datetime.now(),
            contracts=contracts,
            initial_stop=signal.stop_loss,
            current_stop=signal.stop_loss,
            target_price=signal.target_price,
            initial_risk_points=risk_points,
        )
        self._max_favorable = 0.0
        self._max_adverse = 0.0
        self._recent_candles.clear()
        self._zone_stall_count = 0

        logger.info(
            "POSITION OPEN — %s %d at %.2f | SL %.2f | TP %.2f | Risk %.2f pts",
            signal.direction.upper(),
            contracts,
            signal.entry_price,
            signal.stop_loss,
            signal.target_price,
            risk_points,
        )
        return self._position

    def on_candle(
        self,
        candle: Candle,
        swings: list[SwingPoint],
        nearest_target_zone: SRZone | None,
    ) -> TradeResult | None:
        """Process a new 1m candle for position management. Returns TradeResult if closed."""
        if self._position is None:
            return None

        pos = self._position
        current_price = candle.close

        # Track excursions
        pnl = pos.unrealized_pnl(current_price)
        if pnl > self._max_favorable:
            self._max_favorable = pnl
        if pnl < -self._max_adverse:
            self._max_adverse = abs(pnl)

        self._recent_candles.append(candle)
        if len(self._recent_candles) > 10:
            self._recent_candles.pop(0)

        # 1. Check stop-loss hit
        result = self._check_stop_hit(candle)
        if result:
            return result

        # 2. Check target reached
        result = self._check_target(candle)
        if result:
            return result

        # 3. Update trailing logic
        r_multiple = pos.unrealized_r(current_price)

        # Break-even logic
        if pos.status == PositionStatus.ACTIVE and r_multiple >= self.be_r_threshold:
            # Also need a confirming swing
            has_confirming_swing = self._has_confirming_swing(swings)
            if has_confirming_swing:
                self._move_to_breakeven(candle.timestamp)

        # Structural trailing (1R to 2R)
        if pos.status == PositionStatus.BREAK_EVEN or (
            pos.status == PositionStatus.TRAILING
            and pos.trail_phase == TrailPhase.STRUCTURAL
        ):
            if r_multiple >= self.aggressive_r_threshold or self._is_parabolic():
                pos.trail_phase = TrailPhase.AGGRESSIVE
                pos.status = PositionStatus.TRAILING
                logger.info(
                    "TRAIL PHASE 2 — Aggressive trailing active, P&L at +%.1fR",
                    r_multiple,
                )
            else:
                self._trail_structural(swings, candle.timestamp)

        # Aggressive trailing (2R+ or parabolic)
        if (
            pos.status == PositionStatus.TRAILING
            and pos.trail_phase == TrailPhase.AGGRESSIVE
        ):
            self._trail_aggressive(candle)

        # Target zone proximity — tighten trail
        if nearest_target_zone and pos.status in (
            PositionStatus.BREAK_EVEN,
            PositionStatus.TRAILING,
        ):
            result = self._check_zone_stall(candle, nearest_target_zone)
            if result:
                return result

        return None

    def force_close(self, price: float, reason: ExitReason) -> TradeResult | None:
        """Force close the position (session end, emergency, etc.)."""
        if self._position is None:
            return None
        return self._close_position(price, reason, datetime.now())

    def get_trade_results(self) -> list[TradeResult]:
        return list(self._trade_results)

    def reset(self) -> None:
        """Reset for a new session."""
        self._position = None
        self._trade_results.clear()
        self._daily_loss_count = 0
        self._max_favorable = 0.0
        self._max_adverse = 0.0
        self._recent_candles.clear()
        self._zone_stall_count = 0

    # ------------------------------------------------------------------
    # Stop-loss check
    # ------------------------------------------------------------------
    def _check_stop_hit(self, candle: Candle) -> TradeResult | None:
        pos = self._position
        if pos is None:
            return None

        if pos.direction == "long" and candle.low <= pos.current_stop:
            exit_price = pos.current_stop
            reason = self._get_stop_reason()
            return self._close_position(exit_price, reason, candle.timestamp)

        if pos.direction == "short" and candle.high >= pos.current_stop:
            exit_price = pos.current_stop
            reason = self._get_stop_reason()
            return self._close_position(exit_price, reason, candle.timestamp)

        return None

    def _get_stop_reason(self) -> ExitReason:
        pos = self._position
        if pos is None:
            return ExitReason.STOP_LOSS
        if pos.status == PositionStatus.ACTIVE:
            return ExitReason.STOP_LOSS
        if pos.status == PositionStatus.BREAK_EVEN:
            return ExitReason.BREAK_EVEN_STOP
        return ExitReason.TRAILING_STOP

    # ------------------------------------------------------------------
    # Target check
    # ------------------------------------------------------------------
    def _check_target(self, candle: Candle) -> TradeResult | None:
        pos = self._position
        if pos is None:
            return None

        if pos.direction == "long" and candle.high >= pos.target_price:
            return self._close_position(
                pos.target_price, ExitReason.TARGET_REACHED, candle.timestamp
            )
        if pos.direction == "short" and candle.low <= pos.target_price:
            return self._close_position(
                pos.target_price, ExitReason.TARGET_REACHED, candle.timestamp
            )
        return None

    # ------------------------------------------------------------------
    # Break-even
    # ------------------------------------------------------------------
    def _has_confirming_swing(self, swings: list[SwingPoint]) -> bool:
        """Check if there is a new swing confirming the trade direction."""
        pos = self._position
        if pos is None or not swings:
            return False

        recent = [s for s in swings if s.confirmed and s.timestamp >= pos.entry_time]
        if not recent:
            return False

        if pos.direction == "long":
            return any(s.swing_type == "low" and s.price > pos.entry_price for s in recent)
        return any(s.swing_type == "high" and s.price < pos.entry_price for s in recent)

    def _move_to_breakeven(self, ts: datetime) -> None:
        pos = self._position
        if pos is None:
            return

        old_stop = pos.current_stop
        pos.current_stop = pos.entry_price
        pos.status = PositionStatus.BREAK_EVEN
        pos.trail_phase = TrailPhase.STRUCTURAL
        pos.stop_history.append(
            StopAdjustment(
                old_price=old_stop,
                new_price=pos.entry_price,
                reason="break_even",
                timestamp=ts,
            )
        )
        logger.info(
            "BREAK-EVEN SET — Stop %.2f → %.2f, risk eliminated",
            old_stop,
            pos.entry_price,
        )

    # ------------------------------------------------------------------
    # Structural trailing
    # ------------------------------------------------------------------
    def _trail_structural(self, swings: list[SwingPoint], ts: datetime) -> None:
        pos = self._position
        if pos is None:
            return

        if pos.direction == "short":
            # Trail to just above each new LH
            lower_highs = [
                s
                for s in swings
                if s.swing_type == "high"
                and s.confirmed
                and s.timestamp >= pos.entry_time
                and s.price < pos.current_stop
            ]
            if lower_highs:
                best = min(lower_highs, key=lambda s: s.price)
                new_stop = best.price + self.stop_buffer
                if new_stop < pos.current_stop:
                    self._adjust_stop(new_stop, f"structural_trail_LH@{best.price:.2f}", ts)

        elif pos.direction == "long":
            # Trail to just below each new HL
            higher_lows = [
                s
                for s in swings
                if s.swing_type == "low"
                and s.confirmed
                and s.timestamp >= pos.entry_time
                and s.price > pos.current_stop
            ]
            if higher_lows:
                best = max(higher_lows, key=lambda s: s.price)
                new_stop = best.price - self.stop_buffer
                if new_stop > pos.current_stop:
                    self._adjust_stop(new_stop, f"structural_trail_HL@{best.price:.2f}", ts)

    # ------------------------------------------------------------------
    # Aggressive (candle-by-candle) trailing
    # ------------------------------------------------------------------
    def _trail_aggressive(self, candle: Candle) -> None:
        pos = self._position
        if pos is None:
            return

        if pos.direction == "short":
            new_stop = candle.high + self.stop_buffer
            if new_stop < pos.current_stop:
                self._adjust_stop(new_stop, "aggressive_trail", candle.timestamp)

        elif pos.direction == "long":
            new_stop = candle.low - self.stop_buffer
            if new_stop > pos.current_stop:
                self._adjust_stop(new_stop, "aggressive_trail", candle.timestamp)

    # ------------------------------------------------------------------
    # Parabolic detection
    # ------------------------------------------------------------------
    def _is_parabolic(self) -> bool:
        """Detect parabolic move: N consecutive large candles in same direction."""
        if len(self._recent_candles) < self.parabolic_count:
            return False

        recent = self._recent_candles[-self.parabolic_count:]

        # All same direction
        if self._position and self._position.direction == "short":
            if not all(c.is_bearish for c in recent):
                return False
        elif self._position and self._position.direction == "long":
            if not all(c.is_bullish for c in recent):
                return False
        else:
            return False

        # Increasing range
        ranges = [c.range_size for c in recent]
        for i in range(1, len(ranges)):
            if ranges[i] <= ranges[i - 1] * 0.8:  # Allow some tolerance
                return False

        return True

    # ------------------------------------------------------------------
    # Zone stall detection
    # ------------------------------------------------------------------
    def _check_zone_stall(
        self, candle: Candle, zone: SRZone
    ) -> TradeResult | None:
        pos = self._position
        if pos is None:
            return None

        # Check if price is near the target zone
        price = candle.close
        distance = abs(price - zone.midpoint)

        if distance <= 2.0:  # Within 2 points of zone
            # Switch to aggressive trail if not already
            if pos.trail_phase != TrailPhase.TARGET_ZONE:
                pos.trail_phase = TrailPhase.TARGET_ZONE
                logger.info("TARGET ZONE — Price near %s zone, tightening trail", zone.zone_type)

            # Count stall bars
            self._zone_stall_count += 1
            if self._zone_stall_count >= self.zone_stall_bars:
                logger.info("ZONE STALL — Price stalled at zone for %d bars, closing", self._zone_stall_count)
                return self._close_position(price, ExitReason.ZONE_STALL, candle.timestamp)

            # Aggressive candle trail while near zone
            self._trail_aggressive(candle)
        else:
            self._zone_stall_count = 0

        return None

    # ------------------------------------------------------------------
    # Stop adjustment
    # ------------------------------------------------------------------
    def _adjust_stop(self, new_price: float, reason: str, ts: datetime) -> None:
        pos = self._position
        if pos is None:
            return

        old_price = pos.current_stop

        # Never move stop backward
        if pos.direction == "long" and new_price <= pos.current_stop:
            return
        if pos.direction == "short" and new_price >= pos.current_stop:
            return

        pos.current_stop = new_price
        pos.status = PositionStatus.TRAILING
        pos.stop_history.append(
            StopAdjustment(
                old_price=old_price,
                new_price=new_price,
                reason=reason,
                timestamp=ts,
            )
        )
        logger.info("TRAIL — Stop %.2f → %.2f (%s)", old_price, new_price, reason)

    # ------------------------------------------------------------------
    # Close position
    # ------------------------------------------------------------------
    def _close_position(
        self, exit_price: float, reason: ExitReason, ts: datetime
    ) -> TradeResult:
        pos = self._position
        assert pos is not None

        pnl_points = pos.unrealized_pnl(exit_price)
        pnl_dollars = pnl_points * self.point_value * pos.contracts
        r_multiple = pos.unrealized_r(exit_price)

        result = TradeResult(
            position_id=pos.position_id,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=ts,
            contracts=pos.contracts,
            pnl_points=pnl_points,
            pnl_dollars=pnl_dollars,
            r_multiple=r_multiple,
            exit_reason=reason,
            max_favorable_excursion=self._max_favorable,
            max_adverse_excursion=self._max_adverse,
            stop_adjustments=len(pos.stop_history),
        )

        self._trade_results.append(result)

        if pnl_points < 0:
            self._daily_loss_count += 1

        logger.info(
            "POSITION CLOSED — %s | Exit %.2f | P&L %.2f pts (%.1fR, $%.2f) | Reason: %s",
            pos.direction.upper(),
            exit_price,
            pnl_points,
            r_multiple,
            pnl_dollars,
            reason.value,
        )

        self._position = None
        self._max_favorable = 0.0
        self._max_adverse = 0.0
        self._recent_candles.clear()
        self._zone_stall_count = 0

        return result
