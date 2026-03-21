"""Integration test — run the full pipeline with synthetic data."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import load_config, get_point_value, get_tick_size
from bot.data_feed import DataFeed
from bot.entry_scanner import EntrySignalScanner
from bot.market_structure import MarketStructureAnalyzer
from bot.models import Candle, SessionConfig, SessionState
from bot.risk_manager import RiskManager
from bot.session_controller import SessionController
from bot.sr_zones import SRZoneMapper

EST = ZoneInfo("US/Eastern")


def generate_morning_reversal_scenario() -> list[Candle]:
    """Generate synthetic 1m candles simulating a morning impulse + reversal.

    Scenario: Market opens at 5400, rallies to ~5420 (resistance zone),
    then reverses down.
    """
    candles = []
    base_time = datetime(2026, 3, 20, 9, 30, tzinfo=EST)
    price = 5400.0
    idx = 0

    # Phase 1: Strong uptrend (09:30 - 09:50) — ~20 candles up
    for i in range(20):
        move = 1.0 + (i % 3) * 0.25  # Varying move sizes
        o = price
        h = price + move + 0.5
        l = price - 0.25
        c = price + move
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=idx),
            open=o, high=h, low=l, close=c,
            timeframe="1m", bar_index=idx,
        ))
        price = c
        idx += 1

    # Phase 2: First pullback — 3 candles down (creating swing high)
    peak = price
    for i in range(3):
        move = 1.5
        o = price
        h = price + 0.25
        l = price - move - 0.25
        c = price - move
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=idx),
            open=o, high=h, low=l, close=c,
            timeframe="1m", bar_index=idx,
        ))
        price = c
        idx += 1

    # Phase 3: Bounce attempt — 3 candles up (lower high)
    for i in range(3):
        move = 1.0
        o = price
        h = price + move + 0.25
        l = price - 0.25
        c = price + move
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=idx),
            open=o, high=h, low=l, close=c,
            timeframe="1m", bar_index=idx,
        ))
        price = c
        idx += 1

    # Phase 4: Break lower — creating lower low (MSS)
    for i in range(5):
        move = 2.0
        o = price
        h = price + 0.25
        l = price - move - 0.5
        c = price - move
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=idx),
            open=o, high=h, low=l, close=c,
            timeframe="1m", bar_index=idx,
        ))
        price = c
        idx += 1

    # Phase 5: Small bounce (lower high confirmation)
    for i in range(3):
        move = 0.75
        o = price
        h = price + move + 0.25
        l = price - 0.25
        c = price + move
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=idx),
            open=o, high=h, low=l, close=c,
            timeframe="1m", bar_index=idx,
        ))
        price = c
        idx += 1

    # Phase 6: Big bearish confirmation candle
    o = price
    h = price + 0.5
    l = price - 4.5
    c = price - 4.0
    candles.append(Candle(
        timestamp=base_time + timedelta(minutes=idx),
        open=o, high=h, low=l, close=c,
        timeframe="1m", bar_index=idx,
    ))
    price = c
    idx += 1

    # Phase 7: Trigger and continuation down (for profit target)
    for i in range(40):
        move = 0.5 + (i % 4) * 0.25
        o = price
        h = price + 0.5
        l = price - move - 0.5
        c = price - move
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=idx),
            open=o, high=h, low=l, close=c,
            timeframe="1m", bar_index=idx,
        ))
        price = c
        idx += 1

    return candles


def test_market_structure_analyzer():
    """Test that the ZigZag correctly detects swings."""
    print("=" * 60)
    print("TEST: Market Structure Analyzer")
    print("=" * 60)

    msa = MarketStructureAnalyzer(depth_1m=2, min_swing_distance=1.5)
    candles = generate_morning_reversal_scenario()

    swings_found = 0
    mss_found = 0
    for candle in candles:
        events = msa.on_candle(candle)
        for e in events:
            if hasattr(e, "swing_type"):
                swings_found += 1
            elif hasattr(e, "direction"):
                mss_found += 1
                print(f"  MSS: {e.direction} at {e.timestamp.strftime('%H:%M')}")

    trend = msa.get_trend("1m")
    print(f"  Swings detected: {swings_found}")
    print(f"  MSS events: {mss_found}")
    print(f"  Final trend: {trend.direction.value}")
    print(f"  PASS" if swings_found > 0 else "  FAIL")
    print()


def test_sr_zone_mapper():
    """Test zone building from prior day data."""
    print("=" * 60)
    print("TEST: S/R Zone Mapper")
    print("=" * 60)

    mapper = SRZoneMapper()
    # Simulate prior day candles
    prior_candles = [
        Candle(timestamp=datetime(2026, 3, 19, 10, 0), open=5380, high=5420, low=5375, close=5410, timeframe="1m"),
        Candle(timestamp=datetime(2026, 3, 19, 14, 0), open=5410, high=5425, low=5395, close=5405, timeframe="1m"),
    ]
    zone_map = mapper.build_pre_session_zones(prior_candles, [], [])
    print(f"  Zones created: {len(zone_map.zones)}")
    for z in zone_map.zones:
        print(f"    {z.zone_type}: {z.price_low:.2f}–{z.price_high:.2f} [{z.strength.value}] {z.source}")
    print(f"  PASS" if len(zone_map.zones) > 0 else "  FAIL")
    print()


def test_session_controller():
    """Test session state machine."""
    print("=" * 60)
    print("TEST: Session Controller")
    print("=" * 60)

    sc = SessionController()
    assert sc.initialize()
    assert sc.state == SessionState.READY

    # Before market open
    t1 = datetime(2026, 3, 20, 9, 29, tzinfo=EST)
    sc.update(t1)
    assert sc.state == SessionState.READY

    # Market open
    t2 = datetime(2026, 3, 20, 9, 30, tzinfo=EST)
    sc.update(t2)
    assert sc.state == SessionState.ACTIVE

    # Winding down
    t3 = datetime(2026, 3, 20, 11, 0, tzinfo=EST)
    sc.update(t3)
    assert sc.state == SessionState.WINDING_DOWN

    # Position only
    t4 = datetime(2026, 3, 20, 11, 30, tzinfo=EST)
    sc.update(t4)
    assert sc.state == SessionState.POSITION_ONLY

    print("  All state transitions correct")
    print("  PASS")
    print()


def test_full_pipeline():
    """Run the full orchestration pipeline with synthetic data."""
    print("=" * 60)
    print("TEST: Full Pipeline Integration")
    print("=" * 60)

    cfg = load_config("config.yaml")

    # Agents
    msa = MarketStructureAnalyzer(depth_1m=2, min_swing_distance=1.5)
    mapper = SRZoneMapper(zone_proximity_points=3.0)
    scanner = EntrySignalScanner(
        confirmation_candle_body_pct=0.5,  # Relaxed for synthetic data
        confirmation_candle_min_range=2.0,
        impulse_min_points=5.0,
        risk_reward_minimum=3.0,
        zone_proximity=5.0,
    )
    rm = RiskManager(point_value=get_point_value(cfg), tick_size=get_tick_size(cfg))
    sc = SessionController()

    # Build zones with a resistance zone around 5420
    prior_candles = [
        Candle(timestamp=datetime(2026, 3, 19, 10, 0), open=5395, high=5422, low=5390, close=5415, timeframe="1m"),
    ]
    mapper.build_pre_session_zones(prior_candles, [], [])

    sc.initialize()
    candles = generate_morning_reversal_scenario()

    signals_generated = 0
    positions_opened = 0
    trades_closed = 0

    for candle in candles:
        now = candle.timestamp
        sc.update(now)

        if sc.state in (SessionState.CLOSED, SessionState.ERROR):
            break

        # Structure analysis
        events = msa.on_candle(candle)
        trend = msa.get_trend("1m")
        mss = msa.get_last_mss()
        nearby_zone = mapper.is_price_near_zone(candle.close, proximity=5.0)

        # Position management
        if rm.has_position:
            swings = msa.get_swings("1m")
            zone_map = mapper.get_zone_map()
            target_zone = zone_map.nearest_support(candle.close)
            result = rm.on_candle(candle, swings, target_zone)
            if result:
                trades_closed += 1
                sc.record_trade_result(result)
                print(f"  Trade closed: {result.pnl_points:+.2f} pts ({result.r_multiple:+.1f}R) — {result.exit_reason.value}")
            continue

        # Entry scanning
        if sc.can_new_entry():
            signal = scanner.on_candle(candle, trend, mss, nearby_zone, candle.close)
            if signal:
                signals_generated += 1
                pos = rm.open_position(signal)
                if pos:
                    positions_opened += 1
                    print(f"  Position opened: {pos.direction} at {pos.entry_price:.2f}")

    # Close any remaining
    if rm.has_position and candles:
        result = rm.force_close(candles[-1].close, ExitReason.SESSION_CLOSE)
        if result:
            trades_closed += 1
            sc.record_trade_result(result)

    stats = sc.close_session()
    print(f"\n  Signals: {signals_generated}")
    print(f"  Positions: {positions_opened}")
    print(f"  Trades closed: {trades_closed}")
    print(f"  P&L: {stats.total_pnl_points:+.2f} pts ({stats.total_pnl_r:+.1f}R, ${stats.total_pnl_dollars:+.2f})")
    print(f"  PASS (pipeline ran to completion)")
    print()


if __name__ == "__main__":
    test_market_structure_analyzer()
    test_sr_zone_mapper()
    test_session_controller()
    test_full_pipeline()
    print("All tests completed.")
