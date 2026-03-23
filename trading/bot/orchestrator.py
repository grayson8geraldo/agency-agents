"""Trading Bot Orchestrator — coordinates the 5-step ICT pipeline."""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from trading.bot.agents import (
    LiquidityTargetManager,
    MarketStructureAnalyst,
    MicrostructureConfirmer,
    OrderBlockExecutor,
    SessionLiquidityTracker,
)
from trading.bot.models import (
    Bias,
    Candle,
    ConfirmationStatus,
    PipelinePhase,
    PipelineState,
    SweepStatus,
    TradeOutcome,
    TradeResult,
)


class TradingBotOrchestrator:
    """Master pipeline that runs all 5 ICT strategy steps in sequence.

    Pipeline:
        Step 1: M15 Daily Bias (Market Structure Analyst)
        Step 2: Asian Session Sweep (Session Liquidity Tracker)
        Step 3: M1 CHoCH Confirmation (Microstructure Confirmer)
        Step 4: M5 Order Block Entry (Order Block Executor)
        Step 5: M15 Liquidity Target + Position Management
    """

    def __init__(self, instrument: str = "EUR/USD") -> None:
        self.instrument = instrument

        # Initialize all agents
        self.market_analyst = MarketStructureAnalyst(swing_lookback=2)
        self.session_tracker = SessionLiquidityTracker()
        self.micro_confirmer = MicrostructureConfirmer(swing_lookback=2, timeout_minutes=120)
        self.ob_executor = OrderBlockExecutor(
            min_ob_candles=3,
            min_impulse_ratio=1.5,
            sl_buffer_pips=3.0,
            min_rr=2.0,
        )
        self.target_manager = LiquidityTargetManager(min_rr=2.0)

    def run(
        self,
        candles_m15: list[Candle],
        candles_m5: list[Candle],
        candles_m1: list[Candle],
        candles_post_entry: list[Candle] | None = None,
    ) -> PipelineState:
        """Execute the full 5-step pipeline.

        Args:
            candles_m15: M15 candles (48+ hours for bias, also used for targets).
            candles_m5: M5 candles around the expected entry window.
            candles_m1: M1 candles covering Asian session through London open.
            candles_post_entry: Optional candles after entry for backtesting outcome.

        Returns:
            PipelineState with full results.
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        state = PipelineState(date=today, instrument=self.instrument)

        # ──────────────────────────────────────────
        # STEP 1: Daily Bias (M15)
        # ──────────────────────────────────────────
        state.log(f"PIPELINE START — {self.instrument}")
        logger.info("=" * 60)
        logger.info("STEP 1: Determining daily bias on M15")
        logger.info("=" * 60)

        bias_signal = self.market_analyst.analyze(candles_m15)
        state.bias_signal = bias_signal
        state.log(f"Step 1: Bias = {bias_signal.bias.value} (CHoCH: {bias_signal.choch_confirmed})")

        if bias_signal.bias == Bias.NEUTRAL:
            state.phase = PipelinePhase.TERMINATED
            state.termination_reason = "No clear M15 structure — bias NEUTRAL"
            state.log(f"TERMINATED: {state.termination_reason}")
            logger.warning("Pipeline terminated at Step 1: {}", state.termination_reason)
            return state

        state.phase = PipelinePhase.BIAS_DETERMINED
        logger.info("Bias: {} | CHoCH level: {}", bias_signal.bias.value, bias_signal.choch_level)

        # ──────────────────────────────────────────
        # STEP 2: Asian Session Sweep
        # ──────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("STEP 2: Mapping Asian session & detecting sweep")
        logger.info("=" * 60)

        sweep_signal = self.session_tracker.analyze(candles_m1, bias_signal)
        state.sweep_signal = sweep_signal
        state.log(f"Step 2: Sweep status = {sweep_signal.status.value}")

        if sweep_signal.status == SweepStatus.EXPIRED:
            state.phase = PipelinePhase.TERMINATED
            state.termination_reason = "No Asian session sweep detected by cutoff"
            state.log(f"TERMINATED: {state.termination_reason}")
            logger.warning("Pipeline terminated at Step 2: {}", state.termination_reason)
            return state

        if sweep_signal.status in (SweepStatus.WAITING, SweepStatus.MONITORING):
            state.phase = PipelinePhase.SESSION_MAPPED
            state.termination_reason = "Sweep not yet detected — still monitoring"
            state.log(f"PAUSED: {state.termination_reason}")
            logger.info("Pipeline paused at Step 2: waiting for sweep")
            return state

        state.phase = PipelinePhase.SWEEP_DETECTED
        logger.info(
            "Sweep confirmed: {} side at {} (depth: {} pips)",
            sweep_signal.sweep_side, sweep_signal.sweep_price, sweep_signal.depth_pips,
        )

        # ──────────────────────────────────────────
        # STEP 3: M1 CHoCH Confirmation
        # ──────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("STEP 3: Detecting M1 structural shift (CHoCH)")
        logger.info("=" * 60)

        confirmation = self.micro_confirmer.analyze(candles_m1, sweep_signal)
        state.confirmation_signal = confirmation
        state.log(f"Step 3: M1 confirmation = {confirmation.status.value}")

        if confirmation.status == ConfirmationStatus.REJECTED:
            state.phase = PipelinePhase.TERMINATED
            state.termination_reason = "No M1 CHoCH within timeout — setup invalidated"
            state.log(f"TERMINATED: {state.termination_reason}")
            logger.warning("Pipeline terminated at Step 3: {}", state.termination_reason)
            return state

        if confirmation.status == ConfirmationStatus.MONITORING:
            state.phase = PipelinePhase.SWEEP_DETECTED
            state.termination_reason = "M1 CHoCH not yet detected — still monitoring"
            state.log(f"PAUSED: {state.termination_reason}")
            logger.info("Pipeline paused at Step 3: waiting for M1 CHoCH")
            return state

        state.phase = PipelinePhase.M1_CONFIRMED
        logger.info(
            "M1 CHoCH confirmed at {} (close: {}, level: {})",
            confirmation.break_candle_time, confirmation.break_candle_close, confirmation.choch_level,
        )

        # ──────────────────────────────────────────
        # STEP 5 (pre-scan): Find M15 liquidity targets
        # ──────────────────────────────────────────
        targets = self.target_manager.find_targets(candles_m15, bias_signal.bias)
        preliminary_target = targets[0].price if targets else None
        if preliminary_target:
            logger.info("Preliminary target: {} ({})", preliminary_target, targets[0].target_type)

        # ──────────────────────────────────────────
        # STEP 4: M5 Order Block Entry
        # ──────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("STEP 4: Finding M5 order block & placing order")
        logger.info("=" * 60)

        order_signal = self.ob_executor.analyze(candles_m5, confirmation, preliminary_target)
        state.order_signal = order_signal
        state.log(f"Step 4: Order action = {order_signal.action}")

        if order_signal.action != "PLACE_ORDER":
            state.phase = PipelinePhase.TERMINATED
            state.termination_reason = f"Order rejected: {order_signal.action}"
            state.log(f"TERMINATED: {state.termination_reason}")
            logger.warning("Pipeline terminated at Step 4: {}", state.termination_reason)
            return state

        state.phase = PipelinePhase.ORDER_PLACED
        logger.info(
            "Order placed: {} @ {} | SL: {} | Risk: {} pips",
            order_signal.order_type, order_signal.entry_price,
            order_signal.stop_loss, order_signal.risk_pips,
        )

        # ──────────────────────────────────────────
        # STEP 5: Set Take-Profit & Manage Position
        # ──────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("STEP 5: Setting liquidity target & managing position")
        logger.info("=" * 60)

        trade_signal = self.target_manager.create_trade_signal(
            order_signal, candles_m15, bias_signal.bias
        )
        state.trade_signal = trade_signal

        if trade_signal is None:
            state.phase = PipelinePhase.TERMINATED
            state.termination_reason = "No valid liquidity target with acceptable R:R"
            state.log(f"TERMINATED: {state.termination_reason}")
            logger.warning("Pipeline terminated at Step 5: {}", state.termination_reason)
            return state

        state.phase = PipelinePhase.POSITION_ACTIVE
        state.log(
            f"Step 5: TP = {trade_signal.take_profit} "
            f"(R:R = 1:{trade_signal.rr_ratio}) — {trade_signal.target.target_type if trade_signal.target else 'N/A'}"
        )
        logger.info(
            "TRADE ACTIVE: {} @ {} | SL: {} | TP: {} | R:R = 1:{:.1f}",
            order_signal.order_type, trade_signal.entry, trade_signal.stop_loss,
            trade_signal.take_profit, trade_signal.rr_ratio,
        )

        # ──────────────────────────────────────────
        # EVALUATE OUTCOME (backtesting mode)
        # ──────────────────────────────────────────
        if candles_post_entry:
            logger.info("=" * 60)
            logger.info("EVALUATING OUTCOME")
            logger.info("=" * 60)

            outcome = self.target_manager.evaluate_outcome(trade_signal, candles_post_entry)
            state.outcome = outcome
            state.phase = PipelinePhase.COMPLETED
            state.log(f"OUTCOME: {outcome.result.value} | {outcome.pips} pips | {outcome.notes}")

            if outcome.result == TradeResult.WIN:
                logger.info("WIN +{} pips (R:R 1:{:.1f})", outcome.pips, outcome.rr_achieved)
            elif outcome.result == TradeResult.LOSS:
                logger.info("LOSS {} pips", outcome.pips)
            else:
                logger.info("No outcome yet: {}", outcome.notes)
        else:
            state.log("Position active — awaiting outcome (live mode)")

        return state

    def print_summary(self, state: PipelineState) -> None:
        """Print a human-readable daily summary."""
        print("\n" + "=" * 60)
        print(f"  DAILY PIPELINE SUMMARY — {state.instrument} — {state.date}")
        print("=" * 60)
        print(f"  Phase: {state.phase.value}")

        if state.bias_signal:
            print(f"  Bias:  {state.bias_signal.bias.value} (CHoCH: {state.bias_signal.choch_confirmed})")

        if state.sweep_signal and state.sweep_signal.asia_session:
            a = state.sweep_signal.asia_session
            print(f"  Asia:  {a.low} — {a.high}")
            if state.sweep_signal.sweep_price:
                print(f"  Sweep: {state.sweep_signal.sweep_side} at {state.sweep_signal.sweep_price}")

        if state.confirmation_signal and state.confirmation_signal.choch_level:
            print(f"  M1 CHoCH: {state.confirmation_signal.choch_level} at {state.confirmation_signal.break_candle_time}")

        if state.trade_signal:
            ts = state.trade_signal
            print(f"  Entry: {ts.entry}  SL: {ts.stop_loss}  TP: {ts.take_profit}")
            print(f"  R:R:   1:{ts.rr_ratio}")

        if state.outcome:
            o = state.outcome
            print(f"  Result: {o.result.value} ({o.pips:+.1f} pips)")

        if state.termination_reason:
            print(f"  Note:  {state.termination_reason}")

        print("=" * 60)

        if state.logs:
            print("\n  Pipeline Log:")
            for log in state.logs:
                print(f"    {log}")
            print()
