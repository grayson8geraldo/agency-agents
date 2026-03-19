"""Forex risk management — SL/TP in pips, lot sizing, kill switches."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .config import RiskConfig, get_pip_size, get_pip_value
from .models import Bias, SessionAnalysis, TradeSignal, ZoneType

logger = logging.getLogger(__name__)


class RiskManager:
    """Validates and adjusts trade signals for risk compliance (forex)."""

    def __init__(self, config: RiskConfig, symbol: str = "EURUSD=X"):
        self.config = config
        self.symbol = symbol
        self.pip_size = get_pip_size(symbol)
        self.pip_value_per_lot = get_pip_value(symbol)

    def price_to_pips(self, price_diff: Decimal) -> Decimal:
        """Convert a price difference to pips."""
        return abs(price_diff) / self.pip_size

    def pips_to_price(self, pips: Decimal) -> Decimal:
        """Convert pips to price difference."""
        return pips * self.pip_size

    def calculate_stop_loss(self, signal: TradeSignal) -> Decimal:
        """
        Calculate precise SL based on zone type.
        - Order Block: SL beyond zone extreme + buffer in pips
        - FVG: SL at 50% of FVG
        """
        zone = signal.zone
        buffer = self.pips_to_price(self.config.sl_buffer_pips)

        if zone.zone_type == ZoneType.ORDER_BLOCK:
            if signal.direction == Bias.LONG:
                return zone.low - buffer
            else:
                return zone.high + buffer
        else:  # FVG — SL at 50% of FVG
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
        Structural targets: Asia session high/low boundaries.
        """
        risk = abs(entry_price - stop_loss)
        rr = self.config.default_risk_reward
        rr_tp = entry_price + risk * rr if direction == Bias.LONG \
                else entry_price - risk * rr

        if session and session.asia.candles:
            if direction == Bias.LONG and session.asia.high > entry_price:
                structural_tp = session.asia.high
                if structural_tp < rr_tp:
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

    def calculate_lot_size(
        self,
        equity: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """
        Forex lot sizing based on risk.
        Lot Size = Risk Amount / (SL in pips * pip value per lot)

        For a $200 account with 1% risk = $2 risk per trade.
        If SL = 20 pips, pip value = $0.10/pip (micro lot):
            Lot Size = $2 / (20 * $10) = 0.01 lot (micro lot)
        """
        risk_amount = equity * self.config.risk_per_trade_pct
        sl_pips = self.price_to_pips(entry_price - stop_loss)

        if sl_pips == 0:
            return Decimal("0")

        # Lot size = risk_amount / (sl_pips * pip_value_per_lot)
        lot_size = risk_amount / (sl_pips * self.pip_value_per_lot)

        # Clamp to min/max lot size
        lot_size = max(lot_size, self.config.min_lot_size)
        lot_size = min(lot_size, self.config.max_lot_size)

        # Round down to 2 decimal places (standard forex precision)
        lot_size = lot_size.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        # Final check: ensure risk doesn't exceed max
        actual_risk = sl_pips * self.pip_value_per_lot * lot_size
        max_risk = equity * self.config.max_risk_per_trade_pct
        if actual_risk > max_risk:
            lot_size = (max_risk / (sl_pips * self.pip_value_per_lot)).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN,
            )

        return lot_size

    def validate_signal(
        self,
        signal: TradeSignal,
        equity: Decimal,
        daily_pnl: Decimal,
        consecutive_losses: int,
        peak_equity: Decimal,
        open_positions: int,
    ) -> tuple[bool, str]:
        """Gate every trade through risk checks."""
        cfg = self.config

        # Kill switch: daily loss
        if equity > 0 and daily_pnl < 0:
            daily_loss_pct = abs(daily_pnl / equity)
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
        """Recalculate SL, TP with proper risk params."""
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
