"""Step 2: MTF Zone Mapper.

Maps Premium/Discount zones, identifies unmitigated Order Blocks (POIs),
detects liquidity pools, and monitors price approach to POIs.
"""

from __future__ import annotations

import structlog

from ..models import (
    Bias,
    Candle,
    LiquidityPool,
    MTFAnalysis,
    OBType,
    OrderBlock,
    PremiumDiscountZones,
    SwingPoint,
    SwingRange,
    SwingType,
    ZoneName,
)

logger = structlog.get_logger(__name__)


class MTFZoneMapper:
    """Identifies trade locations within the HTF swing range."""

    def __init__(
        self,
        min_displacement_pct: float = 1.5,
        equal_level_tolerance_pct: float = 0.1,
        max_ob_age_candles: int = 100,
        chop_zone_low: float = 0.45,
        chop_zone_high: float = 0.55,
    ):
        self.min_displacement_pct = min_displacement_pct
        self.equal_level_tolerance_pct = equal_level_tolerance_pct
        self.max_ob_age_candles = max_ob_age_candles
        self.chop_zone_low = chop_zone_low
        self.chop_zone_high = chop_zone_high
        self._order_blocks: list[OrderBlock] = []

    def analyze(
        self,
        candles: list[Candle],
        swing_range: SwingRange,
        bias: Bias,
        htf_swing_points: list[SwingPoint],
    ) -> MTFAnalysis:
        """Run full MTF zone analysis."""
        zones = self._calculate_zones(swing_range)
        self._detect_order_blocks(candles, swing_range, bias)
        self._prioritize_order_blocks(swing_range)
        self._check_mitigations(candles)
        liquidity = self._find_liquidity_pools(htf_swing_points, candles)

        current_price = candles[-1].close
        price_zone = self._classify_price_zone(current_price, zones)
        permission = self._get_trade_permission(price_zone, bias)

        active = [ob for ob in self._order_blocks if not ob.mitigated]

        analysis = MTFAnalysis(
            zones=zones,
            active_pois=active,
            liquidity_pools=liquidity,
            current_price_zone=price_zone,
            trade_permission=permission,
        )

        logger.info(
            "mtf.analysis_complete",
            active_pois=len(active),
            price_zone=price_zone.value,
            permission=permission.value if permission else "NONE",
        )
        return analysis

    def check_poi_touch(self, price: float, pois: list[OrderBlock]) -> OrderBlock | None:
        """Check if current price has entered any active POI zone."""
        for poi in pois:
            if poi.mitigated:
                continue
            if poi.low <= price <= poi.high:
                logger.info("mtf.poi_touched", type=poi.type.value, low=poi.low, high=poi.high)
                return poi
        return None

    def mark_mitigated(self, poi: OrderBlock) -> None:
        """Mark a POI as mitigated (price passed through without reversal)."""
        poi.mitigated = True
        poi.mitigation_count += 1
        logger.info("mtf.poi_mitigated", type=poi.type.value, low=poi.low, high=poi.high)

    # ── Private ────────────────────────────────────────────────

    def _calculate_zones(self, sr: SwingRange) -> PremiumDiscountZones:
        """Divide the swing range into Premium/Discount zones."""
        s = sr.size
        return PremiumDiscountZones(
            extreme_discount=(sr.low, sr.low + s * 0.236),
            discount=(sr.low + s * 0.236, sr.equilibrium),
            chop_zone=(sr.low + s * self.chop_zone_low, sr.low + s * self.chop_zone_high),
            premium=(sr.equilibrium, sr.low + s * 0.764),
            extreme_premium=(sr.low + s * 0.764, sr.high),
            equilibrium=sr.equilibrium,
        )

    def _detect_order_blocks(
        self, candles: list[Candle], sr: SwingRange, bias: Bias
    ) -> None:
        """Find Order Blocks in the candle data."""
        self._order_blocks = []
        start = max(0, len(candles) - self.max_ob_age_candles)

        for i in range(start, len(candles) - 1):
            cur = candles[i]
            nxt = candles[i + 1]

            displacement = nxt.body / nxt.open * 100 if nxt.open != 0 else 0
            if displacement < self.min_displacement_pct:
                continue

            # Demand OB: bearish candle → bullish displacement
            if cur.is_bearish and nxt.is_bullish:
                ob_low = cur.body_low
                ob_high = cur.body_high
                if ob_high <= sr.equilibrium and bias == Bias.LONG:
                    self._order_blocks.append(
                        OrderBlock(
                            type=OBType.DEMAND,
                            low=ob_low,
                            high=ob_high,
                            timestamp=cur.timestamp,
                            candle_index=i,
                        )
                    )

            # Supply OB: bullish candle → bearish displacement
            if cur.is_bullish and nxt.is_bearish:
                ob_low = cur.body_low
                ob_high = cur.body_high
                if ob_low >= sr.equilibrium and bias == Bias.SHORT:
                    self._order_blocks.append(
                        OrderBlock(
                            type=OBType.SUPPLY,
                            low=ob_low,
                            high=ob_high,
                            timestamp=cur.timestamp,
                            candle_index=i,
                        )
                    )

    def _prioritize_order_blocks(self, sr: SwingRange) -> None:
        """Rank OBs: EXTREME (closest to range boundary) vs PROXIMAL."""
        for ob in self._order_blocks:
            if ob.type == OBType.DEMAND:
                # Closer to range low → more extreme
                pos = sr.price_position(ob.midpoint)
                ob.priority = "EXTREME" if pos < 0.236 else "PROXIMAL"
            elif ob.type == OBType.SUPPLY:
                pos = sr.price_position(ob.midpoint)
                ob.priority = "EXTREME" if pos > 0.764 else "PROXIMAL"

        # Sort: EXTREME first, then by distance from range boundary
        self._order_blocks.sort(
            key=lambda ob: (0 if ob.priority == "EXTREME" else 1, ob.candle_index)
        )

    def _check_mitigations(self, candles: list[Candle]) -> None:
        """Check if any OBs have been traded through (mitigated)."""
        if not candles:
            return
        for ob in self._order_blocks:
            if ob.mitigated:
                continue
            for c in candles[ob.candle_index + 2 :]:
                if ob.type == OBType.DEMAND and c.close < ob.low:
                    ob.mitigated = True
                    ob.mitigation_count += 1
                    break
                if ob.type == OBType.SUPPLY and c.close > ob.high:
                    ob.mitigated = True
                    ob.mitigation_count += 1
                    break

    def _find_liquidity_pools(
        self, swing_points: list[SwingPoint], candles: list[Candle]
    ) -> list[LiquidityPool]:
        """Detect Equal Highs/Lows and Prior Day High/Low."""
        pools: list[LiquidityPool] = []
        tol = self.equal_level_tolerance_pct / 100

        highs = [sp for sp in swing_points if sp.type == SwingType.HIGH]
        lows = [sp for sp in swing_points if sp.type == SwingType.LOW]

        # Equal Highs
        for i, h1 in enumerate(highs):
            for h2 in highs[i + 1 :]:
                if h1.price != 0 and abs(h1.price - h2.price) / h1.price < tol:
                    pools.append(
                        LiquidityPool(
                            type="EQUAL_HIGHS",
                            level=(h1.price + h2.price) / 2,
                            count=2,
                        )
                    )

        # Equal Lows
        for i, l1 in enumerate(lows):
            for l2 in lows[i + 1 :]:
                if l1.price != 0 and abs(l1.price - l2.price) / l1.price < tol:
                    pools.append(
                        LiquidityPool(
                            type="EQUAL_LOWS",
                            level=(l1.price + l2.price) / 2,
                            count=2,
                        )
                    )

        # Prior Day High / Low (from last complete daily candle)
        if len(candles) >= 2:
            pools.append(LiquidityPool(type="PDH", level=candles[-2].high))
            pools.append(LiquidityPool(type="PDL", level=candles[-2].low))

        return pools

    def _classify_price_zone(self, price: float, zones: PremiumDiscountZones) -> ZoneName:
        """Determine which zone the current price is in."""
        if zones.chop_zone[0] <= price <= zones.chop_zone[1]:
            return ZoneName.CHOP
        if price <= zones.extreme_discount[1]:
            return ZoneName.EXTREME_DISCOUNT
        if price <= zones.discount[1]:
            return ZoneName.DISCOUNT
        if price >= zones.extreme_premium[0]:
            return ZoneName.EXTREME_PREMIUM
        if price >= zones.premium[0]:
            return ZoneName.PREMIUM
        return ZoneName.CHOP

    def _get_trade_permission(self, zone: ZoneName, bias: Bias) -> Bias | None:
        """Determine if trading is allowed based on zone and bias alignment."""
        if zone == ZoneName.CHOP:
            return None
        if zone in (ZoneName.DISCOUNT, ZoneName.EXTREME_DISCOUNT) and bias == Bias.LONG:
            return Bias.LONG
        if zone in (ZoneName.PREMIUM, ZoneName.EXTREME_PREMIUM) and bias == Bias.SHORT:
            return Bias.SHORT
        return None

    def reset(self) -> None:
        """Clear all cached data."""
        self._order_blocks = []
