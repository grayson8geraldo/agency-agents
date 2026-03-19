"""ORB + Session Analysis strategy engine for forex."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from .config import NY_TZ, StrategyConfig, get_pip_size
from .models import (
    Bias, Candle, Displacement, ORBRange, SessionAnalysis,
    TradeSignal, TriggerType, Zone, ZoneType,
)

logger = logging.getLogger(__name__)


def _to_ny(dt: datetime) -> datetime:
    return dt.astimezone(NY_TZ)


# ── ORB Range ──────────────────────────────────────────────────────────────

def compute_orb(candles_15m: list[Candle], trade_date: datetime) -> ORBRange:
    """
    Extract the 09:30–09:45 NY 15-minute candle as the ORB range.
    For forex, we look for the candle at or closest to 09:30 NY.
    """
    trade_ny_date = _to_ny(trade_date).date()
    orb_start = time(9, 30)
    orb_end = time(9, 45)

    best_candle = None
    for c in candles_15m:
        ny_dt = _to_ny(c.timestamp)
        if ny_dt.date() != trade_ny_date:
            continue
        ny_t = ny_dt.time()
        if orb_start <= ny_t < orb_end:
            best_candle = c
            break

    if best_candle is None:
        # Fallback: use the 15m candle closest to 09:30
        for c in candles_15m:
            ny_dt = _to_ny(c.timestamp)
            if ny_dt.date() != trade_ny_date:
                continue
            ny_t = ny_dt.time()
            if time(9, 15) <= ny_t <= time(9, 45):
                best_candle = c
                break

    if best_candle is None:
        logger.warning(f"No ORB candle found for {trade_ny_date}")
        return ORBRange(
            high=Decimal("0"), low=Decimal("0"),
            timestamp=trade_date, is_valid=False,
        )

    orb = ORBRange(
        high=best_candle.high,
        low=best_candle.low,
        timestamp=best_candle.timestamp,
    )
    logger.info(f"ORB range: [{orb.low:.5f} – {orb.high:.5f}]")
    return orb


# ── Displacement Detection ────────────────────────────────────────────────

def _find_consecutive_directional(
    candles: list[Candle],
    bullish: bool,
    min_count: int,
    body_ratio_min: float,
) -> list[list[Candle]]:
    """Find groups of consecutive bullish or bearish candles."""
    groups = []
    current_group: list[Candle] = []

    for c in candles:
        is_match = c.is_bullish if bullish else c.is_bearish
        strong_body = float(c.body_ratio) >= body_ratio_min

        if is_match and strong_body:
            current_group.append(c)
        else:
            if len(current_group) >= min_count:
                groups.append(list(current_group))
            current_group = []

    if len(current_group) >= min_count:
        groups.append(list(current_group))

    return groups


def detect_displacement(
    candles_5m: list[Candle],
    orb: ORBRange,
    bias: Bias,
    config: StrategyConfig,
) -> Optional[Displacement]:
    """
    Look for 3+ consecutive directional candles breaking ORB range.
    The last candle's BODY must close beyond the ORB boundary.
    """
    if bias == Bias.LONG:
        groups = _find_consecutive_directional(
            candles_5m, bullish=True,
            min_count=config.min_displacement_candles,
            body_ratio_min=config.displacement_body_ratio,
        )
        for group in groups:
            if group[-1].close > orb.high:
                logger.info(
                    f"Bullish displacement: {len(group)} candles, "
                    f"broke ORB high {orb.high:.5f}"
                )
                return Displacement("bullish", group, broke_orb=True)

    elif bias == Bias.SHORT:
        groups = _find_consecutive_directional(
            candles_5m, bullish=False,
            min_count=config.min_displacement_candles,
            body_ratio_min=config.displacement_body_ratio,
        )
        for group in groups:
            if group[-1].close < orb.low:
                logger.info(
                    f"Bearish displacement: {len(group)} candles, "
                    f"broke ORB low {orb.low:.5f}"
                )
                return Displacement("bearish", group, broke_orb=True)

    elif bias == Bias.CONTINUATION:
        for bullish in [True, False]:
            groups = _find_consecutive_directional(
                candles_5m, bullish=bullish,
                min_count=config.min_displacement_candles,
                body_ratio_min=config.displacement_body_ratio,
            )
            for group in groups:
                direction = "bullish" if bullish else "bearish"
                target = orb.high if bullish else orb.low
                if (bullish and group[-1].close > target) or \
                   (not bullish and group[-1].close < target):
                    logger.info(f"Continuation displacement: {direction}")
                    return Displacement(direction, group, broke_orb=True)

    return None


# ── Zone Identification ───────────────────────────────────────────────────

def find_order_block(
    candles_5m: list[Candle],
    displacement: Displacement,
) -> Optional[Zone]:
    """
    Find the last opposite candle before the impulse (Order Block).
    For bullish: last bearish candle before the bullish run.
    For bearish: last bullish candle before the bearish run.
    """
    first_impulse = displacement.candles[0]
    first_idx = None
    for i, c in enumerate(candles_5m):
        if c.timestamp == first_impulse.timestamp:
            first_idx = i
            break

    if first_idx is None or first_idx == 0:
        return None

    pre_impulse = candles_5m[:first_idx]

    if displacement.direction == "bullish":
        bearish = [c for c in pre_impulse if c.is_bearish]
        if not bearish:
            return None
        ob = bearish[-1]
        return Zone(ZoneType.ORDER_BLOCK, ob.high, ob.low, "bullish")
    else:
        bullish = [c for c in pre_impulse if c.is_bullish]
        if not bullish:
            return None
        ob = bullish[-1]
        return Zone(ZoneType.ORDER_BLOCK, ob.high, ob.low, "bearish")


def find_fvg(
    candles_5m: list[Candle],
    displacement: Displacement,
) -> Optional[Zone]:
    """
    Find Fair Value Gap within the impulse candles.
    FVG = gap between candle[i-1].high and candle[i+1].low (bullish)
         or candle[i-1].low and candle[i+1].high (bearish).
    """
    imp = displacement.candles
    if len(imp) < 3:
        return None

    for i in range(1, len(imp) - 1):
        prev_c = imp[i - 1]
        next_c = imp[i + 1]

        if displacement.direction == "bullish":
            gap_low = prev_c.high
            gap_high = next_c.low
            if gap_high > gap_low:
                return Zone(ZoneType.FVG, gap_high, gap_low, "bullish")
        else:
            gap_high = prev_c.low
            gap_low = next_c.high
            if gap_high > gap_low:
                return Zone(ZoneType.FVG, gap_high, gap_low, "bearish")

    return None


def identify_zone(
    candles_5m: list[Candle],
    displacement: Displacement,
) -> Optional[Zone]:
    """Find the best zone: prefer Order Block, fallback to FVG."""
    ob = find_order_block(candles_5m, displacement)
    fvg = find_fvg(candles_5m, displacement)

    if ob and fvg:
        last_close = displacement.candles[-1].close
        ob_dist = abs(last_close - ob.midpoint)
        fvg_dist = abs(last_close - fvg.midpoint)
        zone = ob if ob_dist <= fvg_dist else fvg
    else:
        zone = ob or fvg

    if zone:
        logger.info(f"Zone: {zone.zone_type.value} [{zone.low:.5f}–{zone.high:.5f}]")
    return zone


# ── Entry Trigger ─────────────────────────────────────────────────────────

def detect_engulfing(prev: Candle, curr: Candle, direction: str) -> bool:
    """Engulfing pattern: current candle body fully covers previous candle body."""
    if direction == "bullish":
        return (curr.is_bullish and
                curr.body_high > prev.body_high and
                curr.body_low <= prev.body_low)
    else:
        return (curr.is_bearish and
                curr.body_low < prev.body_low and
                curr.body_high >= prev.body_high)


def detect_zone_hold(
    candles: list[Candle],
    zone: Zone,
    direction: str,
    lookback: int = 3,
) -> bool:
    """
    Backup trigger: zone holds price (wicks rejecting from zone)
    and price starts moving in bias direction.
    """
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    if not recent:
        return False

    if direction == "bullish":
        wicks_touching = any(
            c.low <= zone.high and c.low >= zone.low for c in recent
        )
        body_above = recent[-1].close > zone.high
        return wicks_touching and body_above
    else:
        wicks_touching = any(
            c.high >= zone.low and c.high <= zone.high for c in recent
        )
        body_below = recent[-1].close < zone.low
        return wicks_touching and body_below


def check_entry_trigger(
    candles_5m: list[Candle],
    zone: Zone,
    displacement: Displacement,
    config: StrategyConfig,
) -> Optional[tuple[TriggerType, Candle]]:
    """
    Check if price has pulled back to zone and triggered an entry.
    Returns (trigger_type, signal_candle) or None.
    """
    direction = displacement.direction

    last_impulse_ts = displacement.candles[-1].timestamp
    post_displacement = [c for c in candles_5m if c.timestamp > last_impulse_ts]

    if len(post_displacement) < 2:
        return None

    # Check if price has pulled back to the zone
    zone_candles = []
    for c in post_displacement:
        if direction == "bullish":
            if c.low <= zone.high:
                zone_candles.append(c)
        else:
            if c.high >= zone.low:
                zone_candles.append(c)

    if not zone_candles:
        return None

    # Check for engulfing pattern within zone candles
    if config.engulfing_required:
        for i in range(1, len(zone_candles)):
            if detect_engulfing(zone_candles[i - 1], zone_candles[i], direction):
                logger.info(f"Engulfing trigger at {zone_candles[i].timestamp}")
                return (TriggerType.ENGULFING, zone_candles[i])

    # Fallback: zone hold
    if config.zone_hold_fallback:
        if detect_zone_hold(zone_candles, zone, direction, config.zone_hold_lookback):
            logger.info(f"Zone hold trigger at {zone_candles[-1].timestamp}")
            return (TriggerType.ZONE_HOLD, zone_candles[-1])

    return None


# ── Full Strategy Pipeline ────────────────────────────────────────────────

def generate_signal(
    candles_15m: list[Candle],
    candles_5m: list[Candle],
    trade_date: datetime,
    session_analysis: SessionAnalysis,
    config: StrategyConfig,
) -> Optional[TradeSignal]:
    """
    Run the full ORB + Session Analysis strategy pipeline.
    Returns a TradeSignal if all conditions are met, None otherwise.
    """
    bias = session_analysis.bias

    if bias == Bias.NO_TRADE:
        logger.info(f"No trade: session bias is NO_TRADE for {_to_ny(trade_date).date()}")
        return None

    # Step 1: Compute ORB range
    orb = compute_orb(candles_15m, trade_date)
    if not orb.is_valid:
        return None

    # Filter 5m candles to only those after ORB (09:45+ NY)
    orb_end = orb.timestamp + timedelta(minutes=15)
    candles_after_orb = [c for c in candles_5m if c.timestamp >= orb_end]

    if not candles_after_orb:
        return None

    # Step 2: Detect displacement
    displacement = detect_displacement(candles_after_orb, orb, bias, config)
    if not displacement:
        logger.debug(f"No displacement for {_to_ny(trade_date).date()}")
        return None

    # Step 3: Identify zone
    zone = identify_zone(candles_5m, displacement)
    if not zone:
        logger.debug(f"No zone for {_to_ny(trade_date).date()}")
        return None
    displacement.zone = zone

    # Step 4: Check entry trigger
    trigger = check_entry_trigger(candles_5m, zone, displacement, config)
    if not trigger:
        logger.debug(f"No entry trigger for {_to_ny(trade_date).date()}")
        return None

    trigger_type, signal_candle = trigger
    entry_price = signal_candle.close
    signal_direction = Bias.LONG if displacement.direction == "bullish" else Bias.SHORT

    # Preliminary SL based on zone type
    pip_size = get_pip_size(config.symbol)
    if zone.zone_type == ZoneType.ORDER_BLOCK:
        if signal_direction == Bias.LONG:
            raw_sl = zone.low - pip_size * 2  # 2 pip buffer
        else:
            raw_sl = zone.high + pip_size * 2
    else:  # FVG — SL at 50%
        raw_sl = zone.midpoint

    # Preliminary TP at R:R 2.0
    risk = abs(entry_price - raw_sl)
    if signal_direction == Bias.LONG:
        raw_tp = entry_price + risk * 2
    else:
        raw_tp = entry_price - risk * 2

    signal = TradeSignal(
        direction=signal_direction,
        entry_price=entry_price,
        stop_loss=raw_sl,
        take_profit=raw_tp,
        zone=zone,
        trigger_type=trigger_type,
        timestamp=signal_candle.timestamp,
    )

    logger.info(
        f"SIGNAL: {signal.direction.value} {config.symbol} @ {entry_price:.5f}, "
        f"SL={raw_sl:.5f}, TP={raw_tp:.5f}, R:R={signal.risk_reward:.2f}, "
        f"trigger={trigger_type.value}"
    )
    return signal
