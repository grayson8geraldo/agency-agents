"""Step 5: Trade Orchestrator.

Central coordinator and state machine. Manages the pipeline:
HTF Structure → MTF Zone Mapping → LTF Execution → Risk Management.
Enforces all guardrails (Chop Zone, pass-through, post-SL reset, daily limit).
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from config import BotConfig
from models import (
    Bias,
    Candle,
    Position,
    PositionStatus,
    TradingState,
)
from core.htf_structure import HTFStructureAnalyzer
from core.ltf_execution import LTFExecutionEngine
from core.mtf_zones import MTFZoneMapper
from core.risk_manager import RiskManager

logger = structlog.get_logger(__name__)


class TradeOrchestrator:
    """Master coordinator enforcing the MTFA trading pipeline."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.state = TradingState.SCANNING

        # Initialize agents
        self.htf = HTFStructureAnalyzer(
            swing_lookback=config.structure.swing_lookback,
            min_bos_distance_pct=config.structure.min_bos_distance_pct,
        )
        self.mtf = MTFZoneMapper(
            min_displacement_pct=config.structure.min_displacement_pct,
            equal_level_tolerance_pct=config.structure.equal_level_tolerance_pct,
            max_ob_age_candles=config.structure.max_ob_age_candles,
            chop_zone_low=config.structure.chop_zone_low,
            chop_zone_high=config.structure.chop_zone_high,
        )
        self.ltf = LTFExecutionEngine(
            swing_lookback=config.structure.swing_lookback,
            max_confluence_window=config.execution.max_confluence_window,
            pin_bar_wick_ratio=config.execution.pin_bar_wick_ratio,
            displacement_body_multiplier=config.execution.displacement_body_multiplier,
        )
        self.risk = RiskManager(
            risk_per_trade_pct=config.risk.risk_per_trade_pct,
            tp_mode=config.risk.tp_mode,
            rr_ratio=config.risk.rr_ratio,
            sl_buffer_pct=config.risk.sl_buffer_pct,
            max_daily_loss_pct=config.risk.max_daily_loss_pct,
            max_consecutive_losses=config.risk.max_consecutive_losses,
        )

        # Cached analysis
        self._htf_analysis = None
        self._mtf_analysis = None
        self._active_position: Position | None = None
        self._cooldown_counter: int = 0
        self._last_day: int | None = None

    # ── Public API ─────────────────────────────────────────────

    def tick_htf(self, candles: list[Candle]) -> None:
        """Called when new HTF candle data is available."""
        self._check_daily_reset()

        if self.state == TradingState.HALTED:
            logger.info("orchestrator.halted")
            return

        logger.info("orchestrator.tick_htf", state=self.state.value, candles=len(candles))

        analysis = self.htf.analyze(candles)
        if analysis is None:
            logger.info("orchestrator.htf_no_structure")
            return

        if not analysis.structure_valid:
            logger.warning("orchestrator.htf_structure_invalid")
            self._full_reset()
            return

        self._htf_analysis = analysis
        if self.state == TradingState.SCANNING:
            self._transition(TradingState.MAPPING)

    def tick_mtf(self, candles: list[Candle]) -> None:
        """Called when new MTF candle data is available."""
        if self.state not in (TradingState.MAPPING, TradingState.WAITING):
            return
        if self._htf_analysis is None:
            return

        logger.info("orchestrator.tick_mtf", state=self.state.value)

        analysis = self.mtf.analyze(
            candles,
            self._htf_analysis.swing_range,
            self._htf_analysis.bias,
            self._htf_analysis.swing_points,
        )
        self._mtf_analysis = analysis

        # Guardrail A: Chop Zone
        if analysis.trade_permission is None:
            logger.info("orchestrator.chop_zone_or_no_permission")
            self._transition(TradingState.WAITING)
            return

        if not analysis.active_pois:
            logger.info("orchestrator.no_active_pois")
            self._transition(TradingState.WAITING)
            return

        # Check if price is at a POI
        current_price = candles[-1].close
        touched_poi = self.mtf.check_poi_touch(current_price, analysis.active_pois)

        if touched_poi is not None:
            # Activate LTF execution
            self.ltf.activate(self._htf_analysis.bias, touched_poi)
            self._transition(TradingState.CONFIRMING)
        else:
            self._transition(TradingState.WAITING)

    def tick_ltf(self, candles: list[Candle], account_balance: float) -> Position | None:
        """Called when new LTF candle data is available.

        Returns a Position if an entry was confirmed and sized.
        """
        if self.state == TradingState.COOLDOWN:
            self._cooldown_counter += 1
            if self._cooldown_counter >= self.config.risk.cooldown_candles:
                logger.info("orchestrator.cooldown_expired")
                self._full_reset()
            return None

        if self.state == TradingState.IN_TRADE:
            return self._monitor_position(candles)

        if self.state != TradingState.CONFIRMING:
            return None

        # Guardrail B: Pass-through invalidation
        if self.ltf.check_passthrough(candles):
            logger.info("orchestrator.poi_passthrough")
            self.ltf.reset()
            self._transition(TradingState.WAITING)
            return None

        # Check for entry signal (3 confluences)
        signal = self.ltf.process_candle(candles)
        if signal is None:
            return None

        # Build position through Risk Manager
        opposite_pois = None
        fvgs = None
        pools = None
        if self._mtf_analysis:
            opposite_pois = [
                poi for poi in self._mtf_analysis.active_pois if not poi.mitigated
            ]
            pools = self._mtf_analysis.liquidity_pools

        position = self.risk.build_position(
            signal,
            account_balance,
            opposite_pois=opposite_pois,
            fvgs=[signal.rejection.fvg] if signal.rejection.fvg else None,
            liquidity_pools=pools,
        )

        if position is None:
            # Risk manager rejected (daily limit, consecutive losses, etc.)
            if self.risk.is_daily_limit_hit(account_balance) or self.risk.is_consecutive_limit_hit():
                self._transition(TradingState.HALTED)
            else:
                self._transition(TradingState.WAITING)
            return None

        self._active_position = position
        self._transition(TradingState.IN_TRADE)
        return position

    def on_position_exit(self, exit_price: float, is_tp: bool) -> None:
        """Called when the exchange reports position exit."""
        if self._active_position is None:
            return

        if is_tp:
            self.risk.on_take_profit(self._active_position, exit_price)
            logger.info("orchestrator.tp_hit", pnl=self._active_position.pnl)
            self._active_position = None
            # After TP → return to mapping (reuse HTF structure)
            self._transition(TradingState.MAPPING)
        else:
            # Guardrail C: Post-SL full reset
            self.risk.on_stop_loss(self._active_position, exit_price)
            logger.warning("orchestrator.sl_hit", pnl=self._active_position.pnl)
            self._active_position = None
            self._enter_cooldown()

    @property
    def active_position(self) -> Position | None:
        return self._active_position

    # ── Private ────────────────────────────────────────────────

    def _monitor_position(self, candles: list[Candle]) -> Position | None:
        """Check if current price has hit SL or TP."""
        if self._active_position is None:
            return None

        pos = self._active_position
        latest = candles[-1]

        if pos.direction == Bias.LONG:
            if latest.low <= pos.stop_loss:
                self.on_position_exit(pos.stop_loss, is_tp=False)
                return None
            if latest.high >= pos.take_profit:
                self.on_position_exit(pos.take_profit, is_tp=True)
                return None
        else:
            if latest.high >= pos.stop_loss:
                self.on_position_exit(pos.stop_loss, is_tp=False)
                return None
            if latest.low <= pos.take_profit:
                self.on_position_exit(pos.take_profit, is_tp=True)
                return None

        return pos  # Still open

    def _enter_cooldown(self) -> None:
        """Enter cooldown after stop loss."""
        self._cooldown_counter = 0
        self._transition(TradingState.COOLDOWN)

        # Guardrail D: daily loss circuit breaker
        # (checked on next tick in risk manager)

    def _full_reset(self) -> None:
        """Guardrail C/E: Clear everything and go back to scanning."""
        self.htf.reset()
        self.mtf.reset()
        self.ltf.reset()
        self._htf_analysis = None
        self._mtf_analysis = None
        self._active_position = None
        self._cooldown_counter = 0
        self._transition(TradingState.SCANNING)
        logger.info("orchestrator.full_reset")

    def _transition(self, new_state: TradingState) -> None:
        """Transition the state machine."""
        old = self.state
        self.state = new_state
        if old != new_state:
            logger.info("orchestrator.state_change", old=old.value, new=new_state.value)

    def _check_daily_reset(self) -> None:
        """Reset daily counters at UTC midnight."""
        now = datetime.now(timezone.utc)
        today = now.toordinal()
        if self._last_day is not None and today != self._last_day:
            self.risk.reset_daily()
            if self.state == TradingState.HALTED:
                self._full_reset()
            logger.info("orchestrator.daily_reset")
        self._last_day = today
