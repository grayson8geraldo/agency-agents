"""Risk management — SL/TP calculation, position sizing, kill switches."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .config import RiskConfig
from .models import Bias, SessionAnalysis, TradeSignal, ZoneType

logger = logging.getLogger(__name__)


class RiskManager:
    """Validates and adjusts trade signals for risk compliance."""

    def __init__(self, config: RiskConfig):
        self.config = config

    def calculate_stop_loss(self, signal: TradeSignal) -> Decimal:
        """
        Calculate precise SL based on zone type.
        - Order Block: SL beyond zone extreme + buffer
        - FVG: SL at 50% of FVG
        """
        zone = signal.zone
        buffer = self.config.sl_buffer_pct

        if zone.zone_type == ZoneType.ORDER_BLOCK:
            if signal.direction == Bias.LONG:
                return zone.low * (1 - buffer)
            else:
                return zone.high * (1 + buffer)
        else:  # FVG
            return zone.midpoint

    def calculate_take_profit(
        self,
        entry_price: Decimal,
        stop_loss: Decimal,
        direction: Bias,
        session: Optional[SessionAnalysis] = None,
    ) -> Decimal:
        """
        Calculate TP using R:R ratio (1.5–2.2) with optional structural target.
        """
        risk = abs(entry_price - stop_loss)
        rr = self.config.default_risk_reward
        rr_tp = entry_price + risk * rr if direction == Bias.LONG \
                else entry_price - risk * rr

        # Check structural target (Asia session boundary)
        if session:
            if direction == Bias.LONG and session.asia.high > entry_price:
                structural_tp = session.asia.high
                # Use closer of structural and R:R target
                if structural_tp < rr_tp:
                    # Check if structural TP gives at least min R:R
                    structural_rr = abs(structural_tp - entry_price) / risk if risk else Decimal("0")
                    if structural_rr >= self.config.min_risk_reward:
                        rr_tp = structural_tp
            elif direction == Bias.SHORT and session.asia.low < entry_price:
                structural_tp = session.asia.low
                if structural_tp > rr_tp:
                    structural_rr = abs(entry_price - structural_tp) / risk if risk else Decimal("0")
                    if structural_rr >= self.config.min_risk_reward:
                        rr_tp = structural_tp

        return rr_tp

    def calculate_position_size(
        self,
        equity: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """
        Fixed fractional position sizing.
        Position Size = (Equity * Risk%) / |Entry - SL|
        """
        risk_amount = equity * self.config.risk_per_trade_pct
        sl_distance = abs(entry_price - stop_loss)

        if sl_distance == 0:
            return Decimal("0")

        position_size = risk_amount / sl_distance

        # Cap at max risk
        max_risk = equity * self.config.max_risk_per_trade_pct
        max_size = max_risk / sl_distance
        position_size = min(position_size, max_size)

        # Round down to 8 decimal places (crypto precision)
        return position_size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    def validate_signal(
        self,
        signal: TradeSignal,
        equity: Decimal,
        daily_pnl: Decimal,
        consecutive_losses: int,
        peak_equity: Decimal,
        open_positions: int,
    ) -> tuple[bool, str]:
        """Gate every trade through risk checks. Returns (valid, reason)."""
        cfg = self.config

        # Kill switch: daily loss
        daily_loss_pct = abs(daily_pnl / equity) if equity and daily_pnl < 0 else Decimal("0")
        if daily_loss_pct >= cfg.max_daily_loss_pct:
            return False, f"Kill switch: daily loss {daily_loss_pct:.1%} >= {cfg.max_daily_loss_pct:.1%}"

        # Kill switch: consecutive losses
        if consecutive_losses >= cfg.max_consecutive_losses:
            return False, f"Kill switch: {consecutive_losses} consecutive losses"

        # Kill switch: max drawdown
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity
            if drawdown >= cfg.max_drawdown_pct:
                return False, f"Kill switch: drawdown {drawdown:.1%} >= {cfg.max_drawdown_pct:.1%}"

        # Max open positions
        if open_positions >= cfg.max_open_positions:
            return False, f"Max open positions reached: {open_positions}"

        # Risk:Reward check
        if signal.risk_reward < cfg.min_risk_reward:
            return False, f"R:R {signal.risk_reward:.2f} < minimum {cfg.min_risk_reward}"

        # SL must be set
        if signal.stop_loss == 0:
            return False, "Stop loss is not set"

        return True, "All checks passed"

    def refine_signal(
        self,
        signal: TradeSignal,
        equity: Decimal,
        session: Optional[SessionAnalysis] = None,
    ) -> TradeSignal:
        """Recalculate SL, TP, and position size with proper risk params."""
        sl = self.calculate_stop_loss(signal)
        tp = self.calculate_take_profit(signal.entry_price, sl, signal.direction, session)

        return TradeSignal(
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=sl,
            take_profit=tp,
            zone=signal.zone,
            trigger_type=signal.trigger_type,
            timestamp=signal.timestamp,
        )
