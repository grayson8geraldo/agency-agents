"""Support/Resistance Zone Mapper — identifies and maintains key S/R zones."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Literal

from .models import (
    Candle,
    SRZone,
    SwingPoint,
    ZoneMap,
    ZoneStatus,
    ZoneStrength,
)

logger = logging.getLogger(__name__)


class SRZoneMapper:
    """Builds and maintains dynamic support/resistance zones."""

    def __init__(
        self,
        max_active_zones: int = 10,
        zone_proximity_points: float = 3.0,
        stale_zone_distance: float = 50.0,
        min_zone_width: float = 1.0,
        max_zone_width: float = 6.0,
    ) -> None:
        self.max_active_zones = max_active_zones
        self.zone_proximity = zone_proximity_points
        self.stale_distance = stale_zone_distance
        self.min_zone_width = min_zone_width
        self.max_zone_width = max_zone_width
        self.zone_map = ZoneMap(session_date=date.today())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_pre_session_zones(
        self,
        prior_day_candles: list[Candle],
        overnight_candles: list[Candle],
        swing_points_15m: list[SwingPoint],
    ) -> ZoneMap:
        """Build the initial zone map from prior session, overnight, and 15m swings."""
        self.zone_map = ZoneMap(session_date=date.today())
        now = datetime.now()

        # 1. Prior day high/low
        if prior_day_candles:
            day_high = max(c.high for c in prior_day_candles)
            day_low = min(c.low for c in prior_day_candles)
            self._add_zone("resistance", day_high, ["prior_day_high"], now)
            self._add_zone("support", day_low, ["prior_day_low"], now)

        # 2. Overnight high/low
        if overnight_candles:
            on_high = max(c.high for c in overnight_candles)
            on_low = min(c.low for c in overnight_candles)
            self._add_zone("resistance", on_high, ["overnight_high"], now)
            self._add_zone("support", on_low, ["overnight_low"], now)

        # 3. Swing clusters on 15m
        self._build_swing_cluster_zones(swing_points_15m, now)

        # 4. Merge overlapping zones and rank
        self._merge_overlapping()
        self._rank_zones()
        self._trim_to_max()

        self.zone_map.last_updated = now
        logger.info(
            "Pre-session zone map built: %d zones", len(self.zone_map.zones)
        )
        return self.zone_map

    def on_candle_15m(self, candle: Candle, current_price: float) -> None:
        """Update zone statuses based on new 15m candle."""
        for zone in self.zone_map.zones:
            if zone.status == ZoneStatus.BROKEN:
                continue

            # Test if price is in the zone
            if zone.price_low <= candle.high and zone.price_high >= candle.low:
                if zone.status == ZoneStatus.ACTIVE:
                    zone.status = ZoneStatus.TESTED
                    zone.last_reaction = candle.timestamp
                    logger.info(
                        "%s %s TESTED at %s",
                        zone.zone_type.upper(),
                        zone.zone_id[:8],
                        candle.timestamp.strftime("%H:%M"),
                    )

            # Check if zone is broken (15m close beyond zone)
            if zone.zone_type == "resistance" and candle.close > zone.price_high:
                zone.status = ZoneStatus.BROKEN
                logger.info(
                    "RESISTANCE %s BROKEN — 15m close above %.2f",
                    zone.zone_id[:8],
                    zone.price_high,
                )
                # Polarity flip: broken resistance becomes support candidate
                self._add_zone(
                    "support",
                    zone.midpoint,
                    ["polarity_flip"],
                    candle.timestamp,
                )

            elif zone.zone_type == "support" and candle.close < zone.price_low:
                zone.status = ZoneStatus.BROKEN
                logger.info(
                    "SUPPORT %s BROKEN — 15m close below %.2f",
                    zone.zone_id[:8],
                    zone.price_low,
                )
                self._add_zone(
                    "resistance",
                    zone.midpoint,
                    ["polarity_flip"],
                    candle.timestamp,
                )

        # Mark held zones (tested but price reversed)
        for zone in self.zone_map.zones:
            if zone.status == ZoneStatus.TESTED:
                if zone.zone_type == "resistance" and candle.close < zone.price_low:
                    zone.status = ZoneStatus.HELD
                    zone.reaction_count += 1
                    logger.info("RESISTANCE %s HELD", zone.zone_id[:8])
                elif zone.zone_type == "support" and candle.close > zone.price_high:
                    zone.status = ZoneStatus.HELD
                    zone.reaction_count += 1
                    logger.info("SUPPORT %s HELD", zone.zone_id[:8])

        # Remove stale zones far from current price
        self.zone_map.zones = [
            z
            for z in self.zone_map.zones
            if abs(z.midpoint - current_price) < self.stale_distance
            or z.status != ZoneStatus.BROKEN
        ]

        self.zone_map.last_updated = candle.timestamp

    def on_swing_point(self, swing: SwingPoint) -> None:
        """Register a new 15m swing point — may update or create zones."""
        if swing.timeframe != "15m":
            return
        # Check if swing is near an existing zone
        for zone in self.zone_map.zones:
            if abs(swing.price - zone.midpoint) < self.zone_proximity:
                zone.reaction_count += 1
                zone.last_reaction = swing.timestamp
                return
        # New isolated swing — don't create a zone from a single swing
        # (zones need clusters or other confluence)

    def get_zone_map(self) -> ZoneMap:
        return self.zone_map

    def is_price_near_zone(
        self, price: float, proximity: float | None = None
    ) -> SRZone | None:
        """Return the zone if price is within proximity of any active zone."""
        prox = proximity or self.zone_proximity
        for zone in self.zone_map.zones:
            if zone.status in (ZoneStatus.BROKEN,):
                continue
            if zone.price_low - prox <= price <= zone.price_high + prox:
                return zone
        return None

    def reset(self) -> None:
        self.zone_map = ZoneMap(session_date=date.today())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _add_zone(
        self,
        zone_type: Literal["support", "resistance"],
        anchor_price: float,
        sources: list[str],
        created_at: datetime,
    ) -> None:
        half_width = self.min_zone_width / 2.0
        zone = SRZone(
            zone_id=uuid.uuid4().hex[:12],
            zone_type=zone_type,
            price_low=anchor_price - half_width,
            price_high=anchor_price + half_width,
            strength=ZoneStrength.B,
            source=sources,
            reaction_count=1,
            last_reaction=created_at,
            status=ZoneStatus.ACTIVE,
            created_at=created_at,
        )
        self.zone_map.zones.append(zone)

    def _build_swing_cluster_zones(
        self, swings: list[SwingPoint], now: datetime
    ) -> None:
        """Group nearby 15m swing points into zones."""
        if not swings:
            return

        highs = sorted(
            [s for s in swings if s.swing_type == "high"], key=lambda s: s.price
        )
        lows = sorted(
            [s for s in swings if s.swing_type == "low"], key=lambda s: s.price
        )

        # Cluster highs into resistance zones
        for cluster in self._cluster_prices([s.price for s in highs]):
            if len(cluster) >= 2:
                mid = sum(cluster) / len(cluster)
                self._add_zone("resistance", mid, ["15m_swing_cluster"], now)

        # Cluster lows into support zones
        for cluster in self._cluster_prices([s.price for s in lows]):
            if len(cluster) >= 2:
                mid = sum(cluster) / len(cluster)
                self._add_zone("support", mid, ["15m_swing_cluster"], now)

    def _cluster_prices(
        self, prices: list[float], threshold: float | None = None
    ) -> list[list[float]]:
        """Simple clustering: group prices within threshold of each other."""
        if not prices:
            return []
        threshold = threshold or self.zone_proximity
        clusters: list[list[float]] = [[prices[0]]]
        for p in prices[1:]:
            if abs(p - clusters[-1][-1]) <= threshold:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        return clusters

    def _merge_overlapping(self) -> None:
        """Merge zones that overlap."""
        merged = True
        while merged:
            merged = False
            new_zones: list[SRZone] = []
            used = set()
            zones = self.zone_map.zones
            for i, z1 in enumerate(zones):
                if i in used:
                    continue
                for j, z2 in enumerate(zones):
                    if j <= i or j in used:
                        continue
                    if z1.zone_type != z2.zone_type:
                        continue
                    # Check overlap
                    if z1.price_low <= z2.price_high and z2.price_low <= z1.price_high:
                        # Merge
                        z1.price_low = min(z1.price_low, z2.price_low)
                        z1.price_high = max(z1.price_high, z2.price_high)
                        # Cap width
                        if z1.width > self.max_zone_width:
                            mid = z1.midpoint
                            z1.price_low = mid - self.max_zone_width / 2
                            z1.price_high = mid + self.max_zone_width / 2
                        z1.source = list(set(z1.source + z2.source))
                        z1.reaction_count += z2.reaction_count
                        used.add(j)
                        merged = True
                new_zones.append(z1)
                used.add(i)
            self.zone_map.zones = new_zones

    def _rank_zones(self) -> None:
        """Assign strength ratings based on confluence and reactions."""
        for zone in self.zone_map.zones:
            score = 0
            score += zone.reaction_count
            score += len(zone.source) * 2  # Confluence bonus

            # Source-specific bonuses
            if "prior_day_high" in zone.source or "prior_day_low" in zone.source:
                score += 3
            if "overnight_high" in zone.source or "overnight_low" in zone.source:
                score += 2
            if "15m_swing_cluster" in zone.source:
                score += 2

            if score >= 7:
                zone.strength = ZoneStrength.S
            elif score >= 4:
                zone.strength = ZoneStrength.A
            else:
                zone.strength = ZoneStrength.B

    def _trim_to_max(self) -> None:
        """Keep only the top N zones by strength."""
        if len(self.zone_map.zones) <= self.max_active_zones:
            return
        strength_order = {ZoneStrength.S: 0, ZoneStrength.A: 1, ZoneStrength.B: 2}
        self.zone_map.zones.sort(key=lambda z: strength_order[z.strength])
        self.zone_map.zones = self.zone_map.zones[: self.max_active_zones]
