"""Step 5: Liquidity Target Manager — finds M15 liquidity pools and manages position."""

from __future__ import annotations

from loguru import logger

from trading.bot.models import (
    Bias,
    Candle,
    LiquidityTarget,
    OrderSignal,
    SwingPoint,
    TradeOutcome,
    TradeResult,
    TradeSignal,
)


class LiquidityTargetManager:
    """Identifies take-profit levels on M15 from liquidity pools.

    Scans for equal highs/lows, previous session extremes, previous day
    high/low, and trendline clusters. Sets TP at the most obvious target.
    """

    def __init__(
        self,
        min_rr: float = 2.0,
        equal_level_tolerance_pips: float = 3.0,
        swing_lookback: int = 3,
    ) -> None:
        self.min_rr = min_rr
        self.equal_level_tolerance_pips = equal_level_tolerance_pips
        self.swing_lookback = swing_lookback

    @staticmethod
    def _pip_size(price: float) -> float:
        """Return pip size based on price level (0.01 for JPY pairs, 0.0001 otherwise)."""
        return 0.01 if price > 10 else 0.0001

    def find_targets(self, candles_m15: list[Candle], bias: Bias) -> list[LiquidityTarget]:
        """Scan M15 for liquidity targets.

        Args:
            candles_m15: M15 historical candles (look left for targets).
            bias: Daily bias — determines whether we look above or below.
        """
        targets: list[LiquidityTarget] = []
        swings = self._find_swing_points(candles_m15)

        # Determine pip size from price level
        ref_price = candles_m15[-1].close if candles_m15 else 1.0
        pip_size = self._pip_size(ref_price)

        # 1. Equal Highs / Equal Lows
        eq_targets = self._find_equal_levels(swings, bias, pip_size)
        targets.extend(eq_targets)

        # 2. Previous Day High / Low
        pdh_pdl = self._find_previous_day_levels(candles_m15, bias)
        targets.extend(pdh_pdl)

        # 3. Untaken swing extremes
        swing_targets = self._find_untaken_swings(swings, candles_m15, bias)
        targets.extend(swing_targets)

        # Sort by proximity (closest first for BULLISH = lowest first)
        if bias == Bias.BULLISH:
            targets.sort(key=lambda t: t.price)
        else:
            targets.sort(key=lambda t: t.price, reverse=True)

        return targets

    def create_trade_signal(
        self,
        order: OrderSignal,
        candles_m15: list[Candle],
        bias: Bias,
    ) -> TradeSignal | None:
        """Full Step 5: find target, validate R:R, create trade signal.

        Args:
            order: Output from Step 4.
            candles_m15: M15 candles for target scanning.
            bias: Daily bias.
        """
        if order.entry_price is None or order.stop_loss is None:
            return None

        targets = self.find_targets(candles_m15, bias)
        pip_size = self._pip_size(order.entry_price)

        entry = order.entry_price
        sl = order.stop_loss
        risk_pips = abs(entry - sl) / pip_size

        for target in targets:
            reward_pips = abs(target.price - entry) / pip_size
            rr = reward_pips / risk_pips if risk_pips > 0 else 0

            # Target must be on the correct side
            if bias == Bias.BULLISH and target.price <= entry:
                continue
            if bias == Bias.BEARISH and target.price >= entry:
                continue

            if rr >= self.min_rr:
                logger.info(
                    "Target selected: {} at {} (R:R = 1:{:.1f}) — {}",
                    target.target_type, target.price, rr, target.description,
                )
                return TradeSignal(
                    bias=bias,
                    entry=entry,
                    stop_loss=sl,
                    take_profit=target.price,
                    risk_pips=round(risk_pips, 1),
                    reward_pips=round(reward_pips, 1),
                    rr_ratio=round(rr, 2),
                    target=target,
                )

        logger.info("No valid target with R:R >= {:.1f} found", self.min_rr)
        return None

    def evaluate_outcome(
        self,
        trade: TradeSignal,
        candles: list[Candle],
    ) -> TradeOutcome:
        """Simulate or evaluate trade outcome against subsequent candle data.

        Goes through candles after entry to see if TP or SL was hit first.
        """
        pip_size = self._pip_size(trade.entry)

        for candle in candles:
            if trade.bias == Bias.BULLISH:
                # Check SL first (worst case)
                if candle.low <= trade.stop_loss:
                    pips = round(abs(trade.entry - trade.stop_loss) / pip_size, 1)
                    return TradeOutcome(
                        result=TradeResult.LOSS,
                        entry_price=trade.entry,
                        exit_price=trade.stop_loss,
                        pips=-pips,
                        notes="Stop-loss hit",
                    )
                # Check TP
                if candle.high >= trade.take_profit:
                    pips = round(abs(trade.take_profit - trade.entry) / pip_size, 1)
                    return TradeOutcome(
                        result=TradeResult.WIN,
                        entry_price=trade.entry,
                        exit_price=trade.take_profit,
                        pips=pips,
                        rr_achieved=trade.rr_ratio,
                        notes="Take-profit hit",
                    )
            else:  # BEARISH
                if candle.high >= trade.stop_loss:
                    pips = round(abs(trade.stop_loss - trade.entry) / pip_size, 1)
                    return TradeOutcome(
                        result=TradeResult.LOSS,
                        entry_price=trade.entry,
                        exit_price=trade.stop_loss,
                        pips=-pips,
                        notes="Stop-loss hit",
                    )
                if candle.low <= trade.take_profit:
                    pips = round(abs(trade.entry - trade.take_profit) / pip_size, 1)
                    return TradeOutcome(
                        result=TradeResult.WIN,
                        entry_price=trade.entry,
                        exit_price=trade.take_profit,
                        pips=pips,
                        rr_achieved=trade.rr_ratio,
                        notes="Take-profit hit",
                    )

        return TradeOutcome(result=TradeResult.NO_TRADE, notes="Position still open / no data")

    # -- Internal --

    def _find_swing_points(self, candles: list[Candle]) -> list[SwingPoint]:
        swings: list[SwingPoint] = []
        lb = self.swing_lookback

        for i in range(lb, len(candles) - lb):
            c = candles[i]
            is_high = all(
                c.high > candles[i - j].high and c.high > candles[i + j].high
                for j in range(1, lb + 1)
            )
            is_low = all(
                c.low < candles[i - j].low and c.low < candles[i + j].low
                for j in range(1, lb + 1)
            )
            if is_high:
                swings.append(SwingPoint(price=c.high, time=c.time, type="SH"))
            if is_low:
                swings.append(SwingPoint(price=c.low, time=c.time, type="SL"))

        return swings

    def _find_equal_levels(self, swings: list[SwingPoint], bias: Bias, pip_size: float = 0.0001) -> list[LiquidityTarget]:
        """Find equal highs (for bullish) or equal lows (for bearish)."""
        targets: list[LiquidityTarget] = []
        tolerance = self.equal_level_tolerance_pips * pip_size

        if bias == Bias.BULLISH:
            highs = [s for s in swings if s.type == "SH"]
            for i in range(len(highs)):
                for j in range(i + 1, len(highs)):
                    if abs(highs[i].price - highs[j].price) <= tolerance:
                        avg_price = (highs[i].price + highs[j].price) / 2
                        targets.append(LiquidityTarget(
                            price=avg_price,
                            target_type="EQUAL_HIGHS",
                            description=f"Equal highs at {highs[i].price:.5f} and {highs[j].price:.5f}",
                        ))
        else:
            lows = [s for s in swings if s.type == "SL"]
            for i in range(len(lows)):
                for j in range(i + 1, len(lows)):
                    if abs(lows[i].price - lows[j].price) <= tolerance:
                        avg_price = (lows[i].price + lows[j].price) / 2
                        targets.append(LiquidityTarget(
                            price=avg_price,
                            target_type="EQUAL_LOWS",
                            description=f"Equal lows at {lows[i].price:.5f} and {lows[j].price:.5f}",
                        ))

        return targets

    def _find_previous_day_levels(
        self, candles: list[Candle], bias: Bias
    ) -> list[LiquidityTarget]:
        """Find Previous Day High/Low."""
        if len(candles) < 96:  # Need at least 1 day of M15 data
            return []

        targets: list[LiquidityTarget] = []

        # Group candles by date
        by_date: dict[str, list[Candle]] = {}
        for c in candles:
            date_str = c.time.strftime("%Y-%m-%d")
            by_date.setdefault(date_str, []).append(c)

        dates = sorted(by_date.keys())
        if len(dates) < 2:
            return []

        prev_day = by_date[dates[-2]]
        pdh = max(c.high for c in prev_day)
        pdl = min(c.low for c in prev_day)

        if bias == Bias.BULLISH:
            targets.append(LiquidityTarget(
                price=pdh,
                target_type="PDH",
                description=f"Previous day high ({dates[-2]})",
            ))
        else:
            targets.append(LiquidityTarget(
                price=pdl,
                target_type="PDL",
                description=f"Previous day low ({dates[-2]})",
            ))

        return targets

    def _find_untaken_swings(
        self, swings: list[SwingPoint], candles: list[Candle], bias: Bias
    ) -> list[LiquidityTarget]:
        """Find swing highs/lows that haven't been taken (untouched liquidity)."""
        if not candles:
            return []

        targets: list[LiquidityTarget] = []
        current_price = candles[-1].close

        if bias == Bias.BULLISH:
            for sp in swings:
                if sp.type == "SH" and sp.price > current_price:
                    targets.append(LiquidityTarget(
                        price=sp.price,
                        target_type="SWING_HIGH",
                        description=f"Untaken swing high at {sp.time:%Y-%m-%d %H:%M}",
                    ))
        else:
            for sp in swings:
                if sp.type == "SL" and sp.price < current_price:
                    targets.append(LiquidityTarget(
                        price=sp.price,
                        target_type="SWING_LOW",
                        description=f"Untaken swing low at {sp.time:%Y-%m-%d %H:%M}",
                    ))

        return targets
