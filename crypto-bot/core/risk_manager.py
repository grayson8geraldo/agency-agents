"""Step 4: Risk & Position Manager.

Calculates Stop Loss at the invalidation extreme, Take Profit (static 3R or
dynamic), position sizing, and manages position lifecycle. Martingale is
strictly forbidden.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from ..models import (
    Bias,
    EntrySignal,
    FairValueGap,
    LiquidityPool,
    OBType,
    OrderBlock,
    Position,
    PositionStatus,
    TradeJournalEntry,
)

logger = structlog.get_logger(__name__)


class RiskManager:
    """Sizes positions and manages SL/TP."""

    def __init__(
        self,
        risk_per_trade_pct: float = 1.0,
        tp_mode: str = "STATIC",
        rr_ratio: float = 3.0,
        sl_buffer_pct: float = 0.05,
        max_daily_loss_pct: float = 3.0,
        max_consecutive_losses: int = 3,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.tp_mode = tp_mode
        self.rr_ratio = rr_ratio
        self.sl_buffer_pct = sl_buffer_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses

        self._daily_pnl: float = 0.0
        self._consecutive_losses: int = 0
        self._trade_count: int = 0
        self._journal: list[TradeJournalEntry] = []

    def build_position(
        self,
        signal: EntrySignal,
        account_balance: float,
        opposite_pois: list[OrderBlock] | None = None,
        fvgs: list[FairValueGap] | None = None,
        liquidity_pools: list[LiquidityPool] | None = None,
    ) -> Position | None:
        """Transform an EntrySignal into a fully sized Position."""
        if self.is_daily_limit_hit(account_balance):
            logger.warning("risk.daily_limit_hit")
            return None

        if self._consecutive_losses >= self.max_consecutive_losses:
            logger.warning("risk.consecutive_loss_limit", losses=self._consecutive_losses)
            return None

        sl = self._calculate_sl(signal)
        risk_per_unit = abs(signal.entry_price - sl)

        if risk_per_unit <= 0:
            logger.error("risk.zero_risk_distance")
            return None

        tp, actual_rr = self._calculate_tp(
            signal.entry_price,
            risk_per_unit,
            signal.direction,
            opposite_pois or [],
            fvgs or [],
            liquidity_pools or [],
        )

        if tp is None:
            logger.warning("risk.no_tp_found")
            return None

        size = self._calculate_size(account_balance, risk_per_unit)
        if size <= 0:
            logger.error("risk.zero_position_size")
            return None

        risk_amount = account_balance * (self.risk_per_trade_pct / 100)

        position = Position(
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=sl,
            take_profit=tp,
            size=size,
            risk_amount=risk_amount,
            rr_ratio=actual_rr,
            tp_mode=self.tp_mode,
        )

        logger.info(
            "risk.position_built",
            direction=signal.direction.value,
            entry=signal.entry_price,
            sl=sl,
            tp=tp,
            size=size,
            rr=actual_rr,
        )
        return position

    def on_position_filled(self, position: Position) -> None:
        """Mark position as open (limit order filled)."""
        position.status = PositionStatus.OPEN
        position.opened_at = datetime.now(timezone.utc)
        self._trade_count += 1
        logger.info("risk.position_opened", entry=position.fill_price or position.entry_price)

    def on_take_profit(self, position: Position, exit_price: float) -> float:
        """Handle TP hit. Returns realized PnL."""
        position.status = PositionStatus.CLOSED_TP
        position.exit_price = exit_price
        position.closed_at = datetime.now(timezone.utc)

        pnl = self._calc_pnl(position, exit_price)
        position.pnl = pnl
        self._daily_pnl += pnl
        self._consecutive_losses = 0

        logger.info("risk.tp_hit", pnl=pnl)
        return pnl

    def on_stop_loss(self, position: Position, exit_price: float) -> float:
        """Handle SL hit. Returns realized PnL (negative)."""
        position.status = PositionStatus.CLOSED_SL
        position.exit_price = exit_price
        position.closed_at = datetime.now(timezone.utc)

        pnl = self._calc_pnl(position, exit_price)
        position.pnl = pnl
        self._daily_pnl += pnl
        self._consecutive_losses += 1

        logger.warning(
            "risk.sl_hit",
            pnl=pnl,
            consecutive_losses=self._consecutive_losses,
        )
        return pnl

    def is_daily_limit_hit(self, account_balance: float) -> bool:
        """Check if daily loss limit has been breached."""
        max_loss = account_balance * (self.max_daily_loss_pct / 100)
        return self._daily_pnl <= -max_loss

    def is_consecutive_limit_hit(self) -> bool:
        return self._consecutive_losses >= self.max_consecutive_losses

    def reset_daily(self) -> None:
        """Reset daily counters (called at UTC midnight)."""
        self._daily_pnl = 0.0
        self._trade_count = 0

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def journal(self) -> list[TradeJournalEntry]:
        return self._journal

    # ── Private ────────────────────────────────────────────────

    def _calculate_sl(self, signal: EntrySignal) -> float:
        """SL at sweep extreme + buffer."""
        extreme = signal.stop_loss
        buffer = extreme * (self.sl_buffer_pct / 100)

        if signal.direction == Bias.LONG:
            return round(extreme - buffer, 2)
        else:
            return round(extreme + buffer, 2)

    def _calculate_tp(
        self,
        entry: float,
        risk: float,
        direction: Bias,
        opposite_pois: list[OrderBlock],
        fvgs: list[FairValueGap],
        pools: list[LiquidityPool],
    ) -> tuple[float | None, float]:
        """Calculate Take Profit. Returns (tp_price, rr_ratio)."""
        if self.tp_mode == "STATIC":
            return self._tp_static(entry, risk, direction)
        return self._tp_dynamic(entry, risk, direction, opposite_pois, fvgs, pools)

    def _tp_static(
        self, entry: float, risk: float, direction: Bias
    ) -> tuple[float, float]:
        """Fixed R:R target."""
        if direction == Bias.LONG:
            tp = round(entry + risk * self.rr_ratio, 2)
        else:
            tp = round(entry - risk * self.rr_ratio, 2)
        return tp, self.rr_ratio

    def _tp_dynamic(
        self,
        entry: float,
        risk: float,
        direction: Bias,
        opposite_pois: list[OrderBlock],
        fvgs: list[FairValueGap],
        pools: list[LiquidityPool],
    ) -> tuple[float | None, float]:
        """Dynamic TP at nearest opposing structure."""
        targets: list[float] = []

        for poi in opposite_pois:
            if direction == Bias.LONG and poi.type == OBType.SUPPLY:
                targets.append(poi.low)
            elif direction == Bias.SHORT and poi.type == OBType.DEMAND:
                targets.append(poi.high)

        for fvg in fvgs:
            mp = fvg.midpoint
            if direction == Bias.LONG and mp > entry:
                targets.append(mp)
            elif direction == Bias.SHORT and mp < entry:
                targets.append(mp)

        for pool in pools:
            if direction == Bias.LONG and pool.type == "PDH" and pool.level > entry:
                targets.append(pool.level)
            elif direction == Bias.SHORT and pool.type == "PDL" and pool.level < entry:
                targets.append(pool.level)

        if not targets:
            # Fallback to static
            return self._tp_static(entry, risk, direction)

        if direction == Bias.LONG:
            tp = min(targets)
        else:
            tp = max(targets)

        rr = abs(tp - entry) / risk if risk > 0 else 0
        # Ensure at least 1R
        if rr < 1.0:
            return self._tp_static(entry, risk, direction)

        return round(tp, 2), round(rr, 2)

    def _calculate_size(self, balance: float, risk_per_unit: float) -> float:
        """Position size = (balance * risk%) / risk_per_unit."""
        risk_amount = balance * (self.risk_per_trade_pct / 100)
        return round(risk_amount / risk_per_unit, 6)

    @staticmethod
    def _calc_pnl(position: Position, exit_price: float) -> float:
        """Calculate realized PnL."""
        if position.direction == Bias.LONG:
            return round((exit_price - position.entry_price) * position.size, 2)
        else:
            return round((position.entry_price - exit_price) * position.size, 2)
