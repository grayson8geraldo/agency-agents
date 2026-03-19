"""Entry point for ORB + Session Analysis trading bot."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from decimal import Decimal

from .config import BotConfig, NY_TZ, UTC_TZ, RiskConfig, StrategyConfig


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_live(args):
    """Run live paper trading."""
    from .engine import TradingEngine

    config = BotConfig(
        strategy=StrategyConfig(symbol=args.symbol),
        risk=RiskConfig(initial_balance=Decimal(args.balance)),
        exchange_id=args.exchange,
        poll_interval_seconds=args.interval,
    )
    engine = TradingEngine(config)
    engine.run_live()


def cmd_backtest(args):
    """Run backtest on historical data."""
    from .backtester import Backtester

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC_TZ)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC_TZ)

    config = BotConfig(
        strategy=StrategyConfig(symbol=args.symbol),
        risk=RiskConfig(initial_balance=Decimal(args.balance)),
        exchange_id=args.exchange,
        log_level=args.log_level,
    )
    backtester = Backtester(config)
    account = backtester.run(start, end, args.symbol)

    if args.save:
        account.save_state()


def cmd_status(args):
    """Show current account status."""
    from .virtual_account import VirtualAccount

    account = VirtualAccount()
    account.load_state()
    print(account.get_summary())


def main():
    parser = argparse.ArgumentParser(
        description="ORB + Session Analysis Trading Bot (Paper Trading)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # ── live ──
    live_parser = subparsers.add_parser("live", help="Run live paper trading")
    live_parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair")
    live_parser.add_argument("--balance", default="200", help="Initial virtual balance")
    live_parser.add_argument("--exchange", default="binance", help="Exchange to use")
    live_parser.add_argument("--interval", type=int, default=30, help="Poll interval (seconds)")

    # ── backtest ──
    bt_parser = subparsers.add_parser("backtest", help="Run backtest on historical data")
    bt_parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair")
    bt_parser.add_argument("--balance", default="200", help="Initial virtual balance")
    bt_parser.add_argument("--exchange", default="binance", help="Exchange to use")
    bt_parser.add_argument(
        "--start", required=True, help="Start date (YYYY-MM-DD)",
    )
    bt_parser.add_argument(
        "--end", required=True, help="End date (YYYY-MM-DD)",
    )
    bt_parser.add_argument("--save", action="store_true", help="Save state after backtest")

    # ── status ──
    subparsers.add_parser("status", help="Show account status")

    args = parser.parse_args()
    setup_logging(args.log_level)

    if args.command == "live":
        cmd_live(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
