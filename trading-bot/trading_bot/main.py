"""Entry point for ORB + Session Analysis forex trading bot."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from decimal import Decimal

from .config import BotConfig, NY_TZ, UTC_TZ, DEFAULT_PAIR, PAIR_CONFIG, EXCLUDED_PAIRS
from .config import RiskConfig, StrategyConfig, get_pair_name


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)


def resolve_symbol(pair: str) -> str:
    """Resolve user-friendly pair name to Yahoo Finance ticker."""
    # If already a valid ticker, return as-is
    if pair in PAIR_CONFIG:
        return pair
    # Try common formats: EUR/USD → EURUSD=X, EURUSD → EURUSD=X
    clean = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    candidate = clean + "=X"
    if candidate in PAIR_CONFIG:
        return candidate
    # Return the cleaned version with =X suffix
    return candidate


def cmd_live(args):
    """Run live paper trading."""
    from .engine import TradingEngine

    symbol = resolve_symbol(args.symbol)
    config = BotConfig(
        strategy=StrategyConfig(symbol=symbol),
        risk=RiskConfig(initial_balance=Decimal(args.balance)),
        poll_interval_seconds=args.interval,
    )
    engine = TradingEngine(config)
    engine.run_live()


def cmd_live_all(args):
    """Run live paper trading on all active pairs."""
    from .engine import MultiPairEngine

    engine = MultiPairEngine(
        balance=Decimal(args.balance),
        interval=args.interval,
        state_dir=args.state_dir,
    )
    engine.run()


def cmd_backtest(args):
    """Run backtest on historical data."""
    from .backtester import Backtester

    symbol = resolve_symbol(args.symbol)
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC_TZ)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC_TZ)

    config = BotConfig(
        strategy=StrategyConfig(symbol=symbol),
        risk=RiskConfig(initial_balance=Decimal(args.balance)),
        log_level=args.log_level,
    )
    backtester = Backtester(config)
    account = backtester.run(start, end, symbol)

    if args.save:
        account.save_state()


def cmd_backtest_all(args):
    """Run backtest on all forex pairs."""
    from .backtester import Backtester

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC_TZ)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC_TZ)

    results = []
    for ticker, pair_cfg in sorted(PAIR_CONFIG.items()):
        if ticker in EXCLUDED_PAIRS:
            continue
        pair_name = pair_cfg["name"]
        print(f"\n{'#'*60}")
        print(f"  {pair_name}")
        print(f"{'#'*60}")

        config = BotConfig(
            strategy=StrategyConfig(symbol=ticker),
            risk=RiskConfig(initial_balance=Decimal(args.balance)),
            log_level=args.log_level,
        )
        backtester = Backtester(config)
        account = backtester.run(start, end, ticker)

        s = account.state
        results.append({
            "pair": pair_name,
            "trades": s.total_trades,
            "wins": s.winning_trades,
            "losses": s.losing_trades,
            "win_rate": s.win_rate,
            "pnl": s.total_pnl,
            "pnl_pips": s.total_pnl_pips,
            "return_pct": s.total_return_pct,
            "max_dd": s.max_drawdown_pct,
        })

    # Summary table
    print(f"\n\n{'='*85}")
    print("  ALL PAIRS BACKTEST SUMMARY")
    print(f"  Period: {args.start} → {args.end} | Balance: ${args.balance}")
    print(f"{'='*85}")
    print(
        f"{'Pair':<10} {'Trades':>6} {'Wins':>5} {'Loss':>5} "
        f"{'WR%':>6} {'Pips':>8} {'P&L':>9} {'Ret%':>7} {'MaxDD%':>7}"
    )
    print("-" * 85)

    total_pnl = Decimal("0")
    total_pips = Decimal("0")
    total_trades = 0

    for r in results:
        total_pnl += r["pnl"]
        total_pips += r["pnl_pips"]
        total_trades += r["trades"]
        print(
            f"{r['pair']:<10} {r['trades']:>6} {r['wins']:>5} {r['losses']:>5} "
            f"{r['win_rate']:>5.1f}% {r['pnl_pips']:>+7.1f} "
            f"{'${:+.2f}'.format(r['pnl']):>9} {r['return_pct']:>+6.1f}% "
            f"{r['max_dd']:>6.1f}%"
        )

    print("-" * 85)
    print(
        f"{'TOTAL':<10} {total_trades:>6} {'':>5} {'':>5} "
        f"{'':>6} {total_pips:>+7.1f} "
        f"{'${:+.2f}'.format(total_pnl):>9}"
    )
    print(f"{'='*85}\n")


def cmd_status(args):
    """Show current account status."""
    from .virtual_account import VirtualAccount

    account = VirtualAccount()
    account.load_state()
    print(account.get_summary())


def cmd_pairs(args):
    """List available forex pairs."""
    print(f"\n{'Ticker':<12} {'Pair':<10} {'Pip Size':<12} {'Pip Value/Lot'}")
    print("-" * 50)
    for ticker, cfg in sorted(PAIR_CONFIG.items()):
        print(f"{ticker:<12} {cfg['name']:<10} {cfg['pip']:<12} ${cfg['pip_value_per_lot']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="ORB + Session Analysis Forex Bot (Paper Trading on Real Data)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ── live ──
    live_p = subparsers.add_parser("live", help="Run live paper trading")
    live_p.add_argument("--symbol", default="EUR/USD", help="Forex pair (e.g. EUR/USD, GBP/USD)")
    live_p.add_argument("--balance", default="200", help="Initial virtual balance (USD)")
    live_p.add_argument("--interval", type=int, default=30, help="Poll interval (seconds)")

    # ── live-all ──
    la_p = subparsers.add_parser("live-all", help="Run live paper trading on all active pairs")
    la_p.add_argument("--balance", default="200", help="Initial virtual balance per pair (USD)")
    la_p.add_argument("--interval", type=int, default=30, help="Poll interval (seconds)")
    la_p.add_argument("--state-dir", default="state", help="Directory for per-pair state files")

    # ── backtest ──
    bt_p = subparsers.add_parser("backtest", help="Backtest on real historical data")
    bt_p.add_argument("--symbol", default="EUR/USD", help="Forex pair")
    bt_p.add_argument("--balance", default="200", help="Initial virtual balance (USD)")
    bt_p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    bt_p.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    bt_p.add_argument("--save", action="store_true", help="Save state after backtest")

    # ── backtest-all ──
    bta_p = subparsers.add_parser("backtest-all", help="Backtest all pairs")
    bta_p.add_argument("--balance", default="200", help="Initial virtual balance (USD)")
    bta_p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    bta_p.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")

    # ── status ──
    subparsers.add_parser("status", help="Show account status")

    # ── pairs ──
    subparsers.add_parser("pairs", help="List available forex pairs")

    args = parser.parse_args()
    setup_logging(args.log_level)

    commands = {
        "live": cmd_live,
        "live-all": cmd_live_all,
        "backtest": cmd_backtest,
        "backtest-all": cmd_backtest_all,
        "status": cmd_status,
        "pairs": cmd_pairs,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
