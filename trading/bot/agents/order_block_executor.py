"""Step 4: Order Block Executor — finds M5 order blocks and places limit orders."""

from __future__ import annotations

from datetime import timedelta

from loguru import logger

from trading.bot.models import (
    Bias,
    Candle,
    ConfirmationSignal,
    OrderBlock,
    OrderSignal,
)


class OrderBlockExecutor:
    """Identifies order blocks on M5 and generates limit order signals.

    An order block is a consolidation zone (tight range, small candles) that formed
    immediately before an aggressive impulse move. Entry is at the OB boundary,
    stop-loss is beyond the opposite boundary.
    """

    def __init__(
        self,
        min_ob_candles: int = 3,
        min_impulse_ratio: float = 1.5,
        sl_buffer_pips: float = 3.0,
        min_rr: float = 2.0,
        expiry_hours: int = 4,
    ) -> None:
        self.min_ob_candles = min_ob_candles
        self.min_impulse_ratio = min_impulse_ratio
        self.sl_buffer_pips = sl_buffer_pips
        self.min_rr = min_rr
        self.expiry_hours = expiry_hours

    def analyze(
        self,
        candles_m5: list[Candle],
        confirmation: ConfirmationSignal,
        target_price: float | None = None,
    ) -> OrderSignal:
        """Find order block on M5 and generate order signal.

        Args:
            candles_m5: M5 candles around the CHoCH time.
            confirmation: Output from Step 3.
            target_price: Preliminary TP level from Step 5 (for R:R check).
        """
        bias = confirmation.daily_bias
        choch_time = confirmation.break_candle_time

        if choch_time is None:
            return OrderSignal(action="REJECTED_NO_OB")

        # Find candles up to and including the M5 candle that contains the CHoCH.
        # The impulse move that caused CHoCH on M1 may extend a few M5 candles past
        # the exact CHoCH timestamp, so include candles up to 10 min after.
        cutoff = choch_time + timedelta(minutes=10)
        relevant = [c for c in candles_m5 if c.time <= cutoff]
        if len(relevant) < 5:
            logger.warning("Insufficient M5 data around CHoCH time")
            return OrderSignal(action="REJECTED_NO_OB")

        # Detect impulse move and preceding consolidation
        ob = self._find_order_block(relevant, bias)

        if ob is None:
            logger.info("No valid order block found on M5")
            return OrderSignal(action="REJECTED_NO_OB")

        # Calculate entry and stop-loss
        # JPY pairs have prices > 10 (e.g. 150.00) and use 0.01 pip size
        sample_price = ob.upper
        pip_size = 0.01 if sample_price > 10 else 0.0001
        buffer = self.sl_buffer_pips * pip_size

        if bias == Bias.BULLISH:
            # BUY LIMIT at OB upper; SL below OB
            entry = ob.upper
            stop_loss = round(ob.lower - buffer, 5)
        else:
            # SELL LIMIT at OB lower; SL above OB
            entry = ob.lower
            stop_loss = round(ob.upper + buffer, 5)

        risk_pips = abs(entry - stop_loss) / pip_size

        # R:R check
        if target_price is not None:
            reward_pips = abs(target_price - entry) / pip_size
            rr = reward_pips / risk_pips if risk_pips > 0 else 0

            if rr < self.min_rr:
                logger.info(
                    "R:R too low: {:.1f} (min: {:.1f}). Risk: {:.1f} pips, Reward: {:.1f} pips",
                    rr, self.min_rr, risk_pips, reward_pips,
                )
                return OrderSignal(
                    action="REJECTED_LOW_RR",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    risk_pips=risk_pips,
                    order_block=ob,
                )

        order_type = "BUY_LIMIT" if bias == Bias.BULLISH else "SELL_LIMIT"
        expiry = choch_time + timedelta(hours=self.expiry_hours) if choch_time else None

        logger.info(
            "{} at {} | SL: {} | Risk: {:.1f} pips | OB: {}-{} ({} candles)",
            order_type, entry, stop_loss, risk_pips, ob.lower, ob.upper, ob.candle_count,
        )

        return OrderSignal(
            action="PLACE_ORDER",
            order_type=order_type,
            entry_price=entry,
            stop_loss=stop_loss,
            risk_pips=round(risk_pips, 1),
            order_block=ob,
            expiry_time=expiry,
        )

    # -- Internal --

    def _find_order_block(self, candles: list[Candle], bias: Bias) -> OrderBlock | None:
        """Scan M5 candles backwards to find consolidation before impulse.

        Strategy:
        1. Find the strongest impulse candle scanning backwards
        2. Look immediately before it for a consolidation zone
        """
        if len(candles) < 4:
            return None

        # Find the best impulse candle by scanning backwards for the largest
        # directional candle that matches our bias
        impulse_idx = None
        best_body = 0.0

        for i in range(len(candles) - 1, 0, -1):
            c = candles[i]
            if bias == Bias.BULLISH and c.is_bullish and c.body_size > best_body:
                impulse_idx = i
                best_body = c.body_size
            elif bias == Bias.BEARISH and c.is_bearish and c.body_size > best_body:
                impulse_idx = i
                best_body = c.body_size
            # Only search last 10 candles
            if len(candles) - 1 - i >= 10:
                break

        if impulse_idx is None or impulse_idx < 2:
            return None

        # Expand impulse to include adjacent candles in the same direction
        impulse_start = impulse_idx
        impulse_end = impulse_idx
        if bias == Bias.BULLISH:
            while impulse_end + 1 < len(candles) and candles[impulse_end + 1].is_bullish:
                impulse_end += 1
            while impulse_start > 0 and candles[impulse_start - 1].is_bullish:
                impulse_start -= 1
        else:
            while impulse_end + 1 < len(candles) and candles[impulse_end + 1].is_bearish:
                impulse_end += 1
            while impulse_start > 0 and candles[impulse_start - 1].is_bearish:
                impulse_start -= 1

        if impulse_start <= 0:
            return None

        # Calculate impulse size
        impulse_candles = candles[impulse_start : impulse_end + 1]
        impulse_low = min(c.low for c in impulse_candles)
        impulse_high = max(c.high for c in impulse_candles)
        impulse_size = impulse_high - impulse_low

        # Now look for consolidation BEFORE the impulse
        consol_end = impulse_start - 1
        if consol_end < 0:
            return None

        # Walk backwards to find the consolidation range
        consol_start = consol_end
        consol_high = candles[consol_end].high
        consol_low = candles[consol_end].low

        for i in range(consol_end - 1, max(consol_end - 10, -1), -1):
            c = candles[i]
            new_high = max(consol_high, c.high)
            new_low = min(consol_low, c.low)
            new_range = new_high - new_low

            # Consolidation should be tight — if range expands too much, stop
            if new_range > impulse_size * 0.8:
                break

            consol_high = new_high
            consol_low = new_low
            consol_start = i

        candle_count = consol_end - consol_start + 1
        consol_range = consol_high - consol_low

        # Validate
        if candle_count < self.min_ob_candles:
            logger.debug("Consolidation too short: {} candles (min: {})", candle_count, self.min_ob_candles)
            return None

        if consol_range > 0 and impulse_size / consol_range < self.min_impulse_ratio:
            logger.debug(
                "Impulse ratio too low: {:.1f}x (min: {:.1f}x)",
                impulse_size / consol_range, self.min_impulse_ratio,
            )
            return None

        return OrderBlock(
            upper=consol_high,
            lower=consol_low,
            candle_count=candle_count,
            impulse_size=impulse_size,
            timeframe="M5",
        )
