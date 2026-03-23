"""Paper trading runner — runs the ICT pipeline on real forex data with a virtual €200 account.

Usage:
    # Set your OANDA demo token (free: https://www.oanda.com/demo-account/tpa/personal_token)
    export OANDA_API_TOKEN="your-demo-token-here"

    # Run paper trading
    python -m trading.bot.paper_trading --symbol EUR/USD

    # Or with Twelve Data (free key: https://twelvedata.com)
    export TWELVE_DATA_KEY="your-key"
    python -m trading.bot.paper_trading --symbol EUR/USD

    # One-shot mode (run pipeline once and exit)
    python -m trading.bot.paper_trading --symbol EUR/USD --once

    # Continuous mode (monitor every N minutes)
    python -m trading.bot.paper_trading --symbol EUR/USD --interval 5
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from loguru import logger

from trading.bot.forex_data import ForexDataProvider
from trading.bot.models import Candle, PipelinePhase, TradeResult
from trading.bot.orchestrator import TradingBotOrchestrator
from trading.bot.paper_account import PaperAccount


class PaperTradingRunner:
    """Runs the ICT strategy pipeline on real data with a virtual account.

    Flow:
        1. Fetch real M15/M5/M1 candles from forex data provider
        2. Run ICT 5-step pipeline (bias → sweep → CHoCH → OB → target)
        3. If pipeline produces a trade signal → open paper position
        4. Monitor open positions against real prices
        5. Log results to paper account (persistent JSON state)
    """

    def __init__(
        self,
        symbol: str = "EUR/USD",
        account_file: str = "paper_account.json",
    ) -> None:
        self.symbol = symbol
        self.data = ForexDataProvider()
        self.orchestrator = TradingBotOrchestrator(instrument=symbol)
        self.account = PaperAccount.load(account_file)

    def run_once(self) -> None:
        """Execute one full cycle: fetch data → pipeline → manage positions."""
        logger.info("=" * 60)
        logger.info("PAPER TRADING — {} — {}", self.symbol, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        logger.info("Balance: €{:.2f} | Open positions: {}", self.account.balance, len(self.account.open_positions))
        logger.info("=" * 60)

        # 1. Check and update any open positions first
        if self.account.open_positions:
            self._monitor_positions()
            return  # Don't look for new trades while one is open

        # 2. Fetch real candle data
        try:
            candles_m15, candles_m5, candles_m1 = self._fetch_all_data()
        except Exception as e:
            logger.error("Failed to fetch market data: {}", e)
            return

        if not candles_m15 or not candles_m5 or not candles_m1:
            logger.warning("Incomplete data — skipping this cycle")
            return

        # 3. Run ICT pipeline
        state = self.orchestrator.run(
            candles_m15=candles_m15,
            candles_m5=candles_m5,
            candles_m1=candles_m1,
        )

        # 4. If pipeline produced a trade signal → open paper position
        if state.phase == PipelinePhase.POSITION_ACTIVE and state.trade_signal:
            trade = state.trade_signal
            logger.info(
                "SIGNAL: {} @ {} | SL: {} | TP: {} | R:R 1:{:.1f}",
                "BUY" if trade.bias.value == "BULLISH" else "SELL",
                trade.entry, trade.stop_loss, trade.take_profit, trade.rr_ratio,
            )

            # Check if current price is near the entry (within 5 pips)
            try:
                price_data = self.data.get_current_price(self.symbol)
                current = price_data["mid"]
                distance_pips = abs(current - trade.entry) / 0.0001

                if distance_pips <= 5:
                    # Price is at the order block — "fill" the limit order
                    position = self.account.open_position(trade, self.symbol)
                    if position:
                        logger.info("Limit order FILLED at market price {:.5f}", current)
                else:
                    # Place as pending order — will check next cycle
                    logger.info(
                        "Limit order PENDING — current price {:.5f} is {:.1f} pips from entry {:.5f}",
                        current, distance_pips, trade.entry,
                    )
                    # Still open it — the strategy says set limit and wait
                    position = self.account.open_position(trade, self.symbol)
            except Exception as e:
                logger.warning("Could not get current price for fill check: {}", e)
                # Open anyway with the signal entry
                self.account.open_position(trade, self.symbol)
        else:
            reason = state.termination_reason or state.phase.value
            logger.info("No trade today: {}", reason)

        # 5. Print summary
        self.orchestrator.print_summary(state)
        self.account.print_status()

    def run_continuous(self, interval_minutes: int = 5) -> None:
        """Run the paper trading loop continuously.

        Args:
            interval_minutes: Minutes between each check cycle.
        """
        logger.info("Starting continuous paper trading: {} every {}min", self.symbol, interval_minutes)
        self.account.print_status()

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                logger.info("\nStopping paper trading...")
                self.account.print_status()
                break
            except Exception as e:
                logger.error("Error in trading cycle: {}", e)

            logger.info("Next check in {} minutes... (Ctrl+C to stop)", interval_minutes)
            try:
                time.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("\nStopping paper trading...")
                self.account.print_status()
                break

    # -- Internal --

    def _fetch_all_data(self) -> tuple[list[Candle], list[Candle], list[Candle]]:
        """Fetch M15, M5, M1 candles from the data provider."""
        logger.info("Fetching real market data for {}...", self.symbol)

        candles_m15 = self.data.fetch_candles(self.symbol, "M15", count=200)
        candles_m5 = self.data.fetch_candles(self.symbol, "M5", count=100)
        candles_m1 = self.data.fetch_candles(self.symbol, "M1", count=500)

        logger.info(
            "Data loaded: {} M15, {} M5, {} M1 candles",
            len(candles_m15), len(candles_m5), len(candles_m1),
        )
        return candles_m15, candles_m5, candles_m1

    def _monitor_positions(self) -> None:
        """Check open positions against current market price."""
        try:
            price_data = self.data.get_current_price(self.symbol)
        except Exception as e:
            logger.warning("Cannot get price to check positions: {}", e)
            return

        current = price_data["mid"]
        logger.info("Current {} price: {:.5f} (bid: {:.5f}, ask: {:.5f})",
                     self.symbol, current, price_data["bid"], price_data["ask"])

        for position in self.account.open_positions:
            before_status = position.status
            self.account.check_position(position, current)

            if position.status != before_status:
                # Position was closed
                self.account.print_status()
            else:
                # Still open — show unrealized P&L
                if position.direction == "BUY":
                    unrealized_pips = (current - position.entry_price) / 0.0001
                else:
                    unrealized_pips = (position.entry_price - current) / 0.0001
                unrealized_eur = unrealized_pips * position.lot_size * 10.0
                logger.info(
                    "Position #{} {} — unrealized: {:.1f} pips (€{:+.2f}) | SL: {} | TP: {}",
                    position.id, position.direction,
                    unrealized_pips, unrealized_eur,
                    position.stop_loss, position.take_profit,
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ICT Paper Trading Bot — €200 virtual account on real forex data"
    )
    parser.add_argument(
        "--symbol", default="EUR/USD",
        help="Forex pair (EUR/USD, GBP/USD, USD/JPY, etc.)",
    )
    parser.add_argument(
        "--account-file", default="paper_account.json",
        help="Path to paper account state file",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run pipeline once and exit (default: continuous)",
    )
    parser.add_argument(
        "--interval", type=int, default=5,
        help="Minutes between checks in continuous mode (default: 5)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Reset account to €200 and clear trade history",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show account status and exit",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if not args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    # Reset account
    if args.reset:
        account = PaperAccount(state_file=args.account_file)
        account.save()
        logger.info("Account reset to €200.00")
        account.print_status()
        return

    # Status only
    if args.status:
        account = PaperAccount.load(args.account_file)
        account.print_status()
        return

    # Run paper trading
    runner = PaperTradingRunner(
        symbol=args.symbol,
        account_file=args.account_file,
    )

    if args.once:
        runner.run_once()
    else:
        runner.run_continuous(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
