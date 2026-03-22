"""Trading Bot Orchestrator — wires all agents together and runs the main loop."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time as _time
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
    # Core candle processing — shared between backtest and paper modes
    # ------------------------------------------------------------------
    def _process_candle(self, candle: Candle) -> None:
        """Process a single 1m candle through the full strategy pipeline.

        This is the core logic used by both backtest and paper trading modes.
        """
        now = candle.timestamp.replace(tzinfo=EST) if candle.timestamp.tzinfo is None else candle.timestamp

        # Update session state
        state = self.session.update(now)

        if state in (SessionState.CLOSED, SessionState.ERROR):
            return

        # Force close check
        if self.session.should_force_close(now) and self.risk_mgr.has_position:
            result = self.risk_mgr.force_close(candle.close, ExitReason.SESSION_CLOSE)
            if result:
                self.session.record_trade_result(result)
                self._on_trade_closed(result)
            return

        # Feed candle to structure analyzer (1m)
        self.structure.on_candle(candle)

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
            zone_map = self.zones.get_zone_map()
            if self.risk_mgr.position and self.risk_mgr.position.direction == "short":
                target_zone = zone_map.nearest_support(candle.close)
            else:
                target_zone = zone_map.nearest_resistance(candle.close)

            trade_result = self.risk_mgr.on_candle(candle, swings_1m, target_zone)
            if trade_result:
                self.session.record_trade_result(trade_result)
                self._on_trade_closed(trade_result)
            return  # Don't scan for new entries while position is open

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
                    # Check paper account balance before opening
                    if self._paper_account and not self._paper_account.can_afford_trade(
                        self.risk_mgr.risk_per_trade
                    ):
                        logger.warning(
                            "PAPER ACCOUNT — Insufficient balance ($%.2f) for trade risk ($%.2f)",
                            self._paper_account.balance,
                            self.risk_mgr.risk_per_trade,
                        )
                        return

                    position = self.risk_mgr.open_position(signal)
                    if position:
                        logger.info(
                            "TRADE LIFECYCLE — Signal → Position opened %s at %.2f",
                            position.direction.upper(),
                            position.entry_price,
                        )

    def _on_trade_closed(self, result) -> None:
        """Hook called when a trade is closed — updates paper account."""
        if self._paper_account:
            self._paper_account.record_trade(result)

    # ------------------------------------------------------------------
    # Paper account reference (set by run_paper, None in backtest)
    # ------------------------------------------------------------------
    _paper_account = None

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
            self._process_candle(candle)

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

    # ------------------------------------------------------------------
    # Paper Trading mode — real data, virtual $200 balance
    # ------------------------------------------------------------------
    def run_paper(self, initial_balance: float = 200.0) -> str:
        """Run paper trading on live market data with a virtual balance.

        Uses yfinance for real-time (delayed ~15min) ES futures data.
        The full strategy runs exactly as in backtest — same agents,
        same rules, same risk management — but on live candles with
        a virtual account tracking P&L.

        Usage:
            python main.py --mode paper --balance 200
        """
        from bot.live_feed import create_live_feed
        from bot.paper_account import PaperAccount

        asset = self.cfg.get("system", {}).get("asset", "MES")
        paper_cfg = self.cfg.get("paper", {})
        poll_interval = paper_cfg.get("poll_interval_seconds", 60)

        # --- Initialize paper account ---
        account = PaperAccount(
            initial_balance=initial_balance,
            state_file=paper_cfg.get("state_file", "paper_account_state.json"),
        )
        self._paper_account = account

        # --- Initialize live feed (Polygon.io or yfinance) ---
        polygon_cfg = self.cfg.get("polygon", {})
        provider = paper_cfg.get("data_provider", "polygon")
        api_key = polygon_cfg.get("api_key") or None

        feed = create_live_feed(
            provider=provider,
            asset=asset,
            poll_interval=poll_interval,
            api_key=api_key,
        )

        # --- Graceful shutdown ---
        shutdown_requested = False

        def _handle_signal(signum, frame):
            nonlocal shutdown_requested
            shutdown_requested = True
            logger.info("Shutdown signal received — closing gracefully...")

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        # =====================================================================
        #  PAPER TRADING MAIN LOOP
        # =====================================================================
        logger.info("=" * 60)
        logger.info("  PAPER TRADING MODE")
        logger.info("  Asset: %s | Point value: $%.2f", asset, self.point_value)
        logger.info("  Virtual Balance: $%.2f", account.balance)
        logger.info("  Risk per trade: $%.2f", self.risk_mgr.risk_per_trade)
        logger.info("  Poll interval: %ds", poll_interval)
        logger.info("  Strategy: ES/MES Reversal (same as backtest)")
        logger.info("=" * 60)

        # --- Wait for market to open ---
        if not feed.is_market_open():
            logger.info("Market is closed. Waiting for RTH (9:30 AM ET)...")
            feed.wait_for_market_open()

        # --- Warm-up: fetch prior day data for zone building ---
        logger.info("Warming up — loading historical data for structure + zones...")
        warmup_candles = feed.fetch_historical_1m(days=2)

        if warmup_candles:
            # Split into prior-day and today candles
            today = datetime.now(EST).date()
            prior_candles = [c for c in warmup_candles if c.timestamp.date() < today]
            today_candles = [c for c in warmup_candles if c.timestamp.date() == today]

            # Build zones from prior day
            if prior_candles:
                prior_15m = feed.aggregate_to_15m(prior_candles)
                prior_swings = []
                for c15 in prior_15m:
                    events = self.structure.on_candle(c15)
                    prior_swings.extend([e for e in events if hasattr(e, "swing_type")])
                self.structure.reset()

                self.zones.build_pre_session_zones(
                    prior_day_candles=prior_candles,
                    overnight_candles=[],
                    swing_points_15m=prior_swings,
                )
                logger.info(
                    "Zone warm-up complete — %d prior-day candles, %d zones built",
                    len(prior_candles),
                    len(self.zones.get_zone_map().zones),
                )

            # Process today's candles that already happened (catch up)
            if today_candles:
                logger.info("Catching up on %d candles from today...", len(today_candles))
                # Initialize session before processing
                self.session.initialize()
                for candle in today_candles:
                    self._process_candle(candle)
                logger.info("Catch-up complete. Switching to live polling.")
            else:
                self.session.initialize()
        else:
            logger.warning("No historical data available — starting cold")
            self.session.initialize()

        # --- Live polling loop ---
        logger.info("Live polling started. Press Ctrl+C to stop.")
        candles_processed = 0

        while not shutdown_requested:
            # Check account health
            if account.is_blown:
                logger.warning("PAPER ACCOUNT DEPLETED — Balance: $%.2f. Stopping.", account.balance)
                break

            # Check market hours
            if not feed.is_market_open():
                # Session end — close any open positions
                if self.risk_mgr.has_position:
                    price = feed.get_current_price()
                    if price:
                        result = self.risk_mgr.force_close(price, ExitReason.SESSION_CLOSE)
                        if result:
                            self.session.record_trade_result(result)
                            account.record_trade(result)

                logger.info("Market closed. Session over.")
                break

            # Check session state
            now = datetime.now(EST)
            state = self.session.update(now)
            if state in (SessionState.CLOSED, SessionState.ERROR):
                logger.info("Session state: %s — stopping.", state.value)
                break

            # Fetch new candles
            new_candles = feed.fetch_latest_candles()

            for candle in new_candles:
                self._process_candle(candle)
                candles_processed += 1

                # Update unrealized P&L in paper account
                if self.risk_mgr.has_position and self.risk_mgr.position:
                    pos = self.risk_mgr.position
                    unrealized_pts = pos.unrealized_pnl(candle.close)
                    unrealized_dollars = unrealized_pts * self.point_value * pos.contracts
                    account.update_unrealized(unrealized_dollars)

            # Status update every poll
            if new_candles:
                last = new_candles[-1]
                pos_str = "FLAT"
                if self.risk_mgr.has_position and self.risk_mgr.position:
                    p = self.risk_mgr.position
                    pos_str = (
                        f"{p.direction.upper()} @ {p.entry_price:.2f} | "
                        f"Stop: {p.current_stop:.2f} | "
                        f"P&L: {p.unrealized_pnl(last.close):+.2f} pts"
                    )
                logger.info(
                    "LIVE — %s | Price: %.2f | Balance: $%.2f | Equity: $%.2f | %s",
                    last.timestamp.strftime("%H:%M:%S"),
                    last.close,
                    account.balance,
                    account.equity,
                    pos_str,
                )

            # Wait for next poll
            _time.sleep(poll_interval)

        # =====================================================================
        #  SESSION END
        # =====================================================================

        # Close any remaining position
        if self.risk_mgr.has_position:
            price = feed.get_current_price()
            if price:
                result = self.risk_mgr.force_close(price, ExitReason.SESSION_CLOSE)
                if result:
                    self.session.record_trade_result(result)
                    account.record_trade(result)

        # Generate reports
        stats = self.session.close_session()
        session_report = self.session.generate_report()
        account_summary = account.get_summary()

        logger.info("=== PAPER TRADING SESSION COMPLETE ===")
        print("\n" + session_report)
        print(account_summary)

        return session_report + "\n" + account_summary


def _parse_time(t: str) -> time:
    parts = t.split(":")
    return time(int(parts[0]), int(parts[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="ES/MES Reversal Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["backtest", "paper"],
        default="backtest",
        help="Run mode: 'backtest' for CSV replay, 'paper' for live data with virtual balance",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Path to 1-minute candle CSV (required for backtest mode)",
    )
    parser.add_argument(
        "--prior-day",
        default=None,
        help="Path to prior day 1m CSV (for zone building in backtest)",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=200.0,
        help="Initial virtual balance for paper trading (default: $200)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--reset-account",
        action="store_true",
        help="Reset paper account to initial balance before starting",
    )
    args = parser.parse_args()

    bot = TradingBotOrchestrator(config_path=args.config)

    if args.mode == "backtest":
        if not args.data:
            parser.error("--data is required for backtest mode")
        bot.run_backtest(csv_1m=args.data, prior_day_csv=args.prior_day)

    elif args.mode == "paper":
        if args.reset_account:
            from bot.paper_account import PaperAccount
            paper_cfg = bot.cfg.get("paper", {})
            acct = PaperAccount(
                initial_balance=args.balance,
                state_file=paper_cfg.get("state_file", "paper_account_state.json"),
            )
            acct.reset()
            logger.info("Paper account reset to $%.2f", args.balance)

        bot.run_paper(initial_balance=args.balance)


if __name__ == "__main__":
    main()
