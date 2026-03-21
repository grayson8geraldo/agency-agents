"""Trading Bot Orchestrator — wires all agents together and runs the main loop."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.config import load_config, get_point_value, get_tick_size
from bot.data_feed import DataFeed
from bot.entry_scanner import EntrySignalScanner
from bot.market_structure import MarketStructureAnalyzer
from bot.models import (
    Candle,
    ExitReason,
    SessionConfig,
    SessionState,
)
from bot.risk_manager import RiskManager
from bot.session_controller import SessionController
from bot.sr_zones import SRZoneMapper

EST = ZoneInfo("US/Eastern")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-24s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


class TradingBotOrchestrator:
    """Master coordinator — loads config, initializes agents, runs the main loop."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.cfg = load_config(config_path)
        self.point_value = get_point_value(self.cfg)
        self.tick_size = get_tick_size(self.cfg)

        # --- Initialize agents ---
        struct_cfg = self.cfg.get("structure", {})
        self.structure = MarketStructureAnalyzer(
            depth_1m=struct_cfg.get("zigzag_depth_1m", 3),
            depth_15m=struct_cfg.get("zigzag_depth_15m", 2),
            min_swing_distance=struct_cfg.get("min_swing_distance", 2.0),
            lookback_swings=struct_cfg.get("lookback_swings", 6),
        )

        zones_cfg = self.cfg.get("zones", {})
        self.zones = SRZoneMapper(
            max_active_zones=zones_cfg.get("max_active_zones", 10),
            zone_proximity_points=zones_cfg.get("zone_proximity_points", 3.0),
            stale_zone_distance=zones_cfg.get("stale_zone_distance", 50.0),
            min_zone_width=zones_cfg.get("min_zone_width", 1.0),
            max_zone_width=zones_cfg.get("max_zone_width", 6.0),
        )

        entry_cfg = self.cfg.get("entry", {})
        risk_cfg = self.cfg.get("risk", {})
        self.scanner = EntrySignalScanner(
            confirmation_candle_body_pct=entry_cfg.get("confirmation_candle_body_pct", 0.60),
            confirmation_candle_min_range=entry_cfg.get("confirmation_candle_min_range", 3.0),
            trigger_expiry_bars=entry_cfg.get("trigger_expiry_bars", 5),
            max_trigger_distance=entry_cfg.get("max_trigger_distance", 5.0),
            confirmation_timeout_bars=entry_cfg.get("confirmation_timeout_bars", 10),
            impulse_min_points=struct_cfg.get("impulse_min_points", 8.0),
            risk_reward_minimum=risk_cfg.get("risk_reward_minimum", 3.0),
            zone_proximity=zones_cfg.get("zone_proximity_points", 3.0),
        )
        self.scanner.set_max_attempts(risk_cfg.get("max_attempts_per_day", 2))
        self.scanner.set_zone_mapper(self.zones)

        trail_cfg = self.cfg.get("trailing", {})
        self.risk_mgr = RiskManager(
            risk_per_trade_dollars=risk_cfg.get("risk_per_trade_dollars", 100.0),
            risk_reward_minimum=risk_cfg.get("risk_reward_minimum", 3.0),
            max_position_size=risk_cfg.get("max_position_size", 1),
            breakeven_r_threshold=trail_cfg.get("breakeven_r_threshold", 1.0),
            aggressive_trail_r_threshold=trail_cfg.get("aggressive_trail_r_threshold", 2.0),
            parabolic_candle_count=trail_cfg.get("parabolic_candle_count", 3),
            zone_stall_timeout_bars=trail_cfg.get("zone_stall_timeout_bars", 3),
            stop_buffer_ticks=trail_cfg.get("stop_buffer_ticks", 2),
            tick_size=self.tick_size,
            point_value=self.point_value,
        )

        sess_cfg = self.cfg.get("session", {})
        session_config = SessionConfig(
            trading_start=_parse_time(sess_cfg.get("trading_start", "09:30")),
            new_setup_cutoff=_parse_time(sess_cfg.get("new_setup_cutoff", "11:00")),
            trading_end=_parse_time(sess_cfg.get("trading_end", "11:30")),
            force_close_deadline=_parse_time(sess_cfg.get("force_close", "13:00")),
            max_entries_per_day=risk_cfg.get("max_entries_per_day", 3),
            max_attempts_per_day=risk_cfg.get("max_attempts_per_day", 2),
            max_consecutive_loss_days=risk_cfg.get("max_consecutive_loss_days", 3),
        )
        self.session = SessionController(session_config)

        self.data_feed = DataFeed(asset=self.cfg.get("system", {}).get("asset", "MES"))

        # 15m candle accumulator for live aggregation
        self._1m_bucket: list[Candle] = []

    # ------------------------------------------------------------------
    # Backtest mode
    # ------------------------------------------------------------------
    def run_backtest(self, csv_1m: str, prior_day_csv: str | None = None) -> str:
        """Run the bot on historical 1m candle data from CSV."""
        logger.info("=== BACKTEST START ===")
        logger.info("Asset: %s | Point value: $%.2f", self.cfg["system"]["asset"], self.point_value)

        # Load data
        candles_1m = self.data_feed.load_csv(csv_1m, timeframe="1m")
        if not candles_1m:
            logger.error("No candle data loaded")
            return "No data"

        # Load prior day for zone building
        prior_candles: list[Candle] = []
        if prior_day_csv:
            prior_candles = self.data_feed.load_csv(prior_day_csv, timeframe="1m")

        # Build pre-session zones
        prior_15m = self.data_feed.aggregate_to_15m(prior_candles) if prior_candles else []
        # Feed prior 15m through structure analyzer to get swing points
        prior_swings = []
        for c15 in prior_15m:
            events = self.structure.on_candle(c15)
            prior_swings.extend([e for e in events if hasattr(e, "swing_type")])
        self.structure.reset()  # Reset for the actual session

        self.zones.build_pre_session_zones(
            prior_day_candles=prior_candles,
            overnight_candles=[],
            swing_points_15m=prior_swings,
        )

        # Initialize session
        if not self.session.initialize():
            return self.session.generate_report()

        # Main loop: iterate over 1m candles
        for candle in self.data_feed.iter_candles(candles_1m):
            now = candle.timestamp.replace(tzinfo=EST) if candle.timestamp.tzinfo is None else candle.timestamp

            # Update session state
            state = self.session.update(now)

            if state in (SessionState.CLOSED, SessionState.ERROR):
                break

            # Force close check
            if self.session.should_force_close(now) and self.risk_mgr.has_position:
                result = self.risk_mgr.force_close(candle.close, ExitReason.SESSION_CLOSE)
                if result:
                    self.session.record_trade_result(result)
                break

            # Feed candle to structure analyzer (1m)
            structure_events = self.structure.on_candle(candle)

            # Aggregate to 15m and feed
            self._1m_bucket.append(candle)
            if len(self._1m_bucket) >= 15:
                candle_15m = self.data_feed._merge_bucket(self._1m_bucket, "15m")
                self._1m_bucket.clear()
                self.structure.on_candle(candle_15m)
                self.zones.on_candle_15m(candle_15m, candle.close)

            # Get current state
            trend = self.structure.get_trend("1m")
            mss = self.structure.get_last_mss()
            nearby_zone = self.zones.is_price_near_zone(candle.close)
            swings_1m = self.structure.get_swings("1m")

            # --- Risk Manager: manage open position ---
            if self.risk_mgr.has_position:
                # Determine nearest target zone
                zone_map = self.zones.get_zone_map()
                if self.risk_mgr.position and self.risk_mgr.position.direction == "short":
                    target_zone = zone_map.nearest_support(candle.close)
                else:
                    target_zone = zone_map.nearest_resistance(candle.close)

                trade_result = self.risk_mgr.on_candle(candle, swings_1m, target_zone)
                if trade_result:
                    self.session.record_trade_result(trade_result)
                continue  # Don't scan for new entries while position is open

            # --- Entry Scanner: look for new setups ---
            if state in (SessionState.ACTIVE, SessionState.WINDING_DOWN):
                if self.session.can_new_setup() or self.scanner.state.value not in ("idle",):
                    signal = self.scanner.on_candle(
                        candle=candle,
                        trend=trend,
                        mss=mss,
                        nearby_zone=nearby_zone,
                        current_price=candle.close,
                    )

                    if signal and self.session.can_new_entry():
                        # Route signal to risk manager
                        position = self.risk_mgr.open_position(signal)
                        if position:
                            logger.info(
                                "TRADE LIFECYCLE — Signal → Position opened %s at %.2f",
                                position.direction.upper(),
                                position.entry_price,
                            )

        # --- Close any remaining position ---
        if self.risk_mgr.has_position:
            last_candle = candles_1m[-1] if candles_1m else None
            if last_candle:
                result = self.risk_mgr.force_close(last_candle.close, ExitReason.SESSION_CLOSE)
                if result:
                    self.session.record_trade_result(result)

        # --- Finalize ---
        stats = self.session.close_session()
        report = self.session.generate_report()
        logger.info("=== BACKTEST COMPLETE ===")
        print("\n" + report)
        return report


def _parse_time(t: str) -> time:
    parts = t.split(":")
    return time(int(parts[0]), int(parts[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="ES/MES Reversal Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["backtest"],
        default="backtest",
        help="Run mode (currently only backtest is supported)",
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to 1-minute candle CSV (columns: datetime,open,high,low,close,volume)",
    )
    parser.add_argument(
        "--prior-day",
        default=None,
        help="Path to prior day 1m CSV (for zone building)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml",
    )
    args = parser.parse_args()

    bot = TradingBotOrchestrator(config_path=args.config)
    bot.run_backtest(csv_1m=args.data, prior_day_csv=args.prior_day)


if __name__ == "__main__":
    main()
