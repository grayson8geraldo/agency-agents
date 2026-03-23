"""Main entry point — runs the ICT trading bot with sample or live data."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from loguru import logger

from trading.bot.models import Candle
from trading.bot.orchestrator import TradingBotOrchestrator


def generate_demo_data() -> (
    tuple[list[Candle], list[Candle], list[Candle], list[Candle]]
):
    """Generate synthetic candle data that simulates a full ICT setup.

    Creates a scenario:
    - M15: bearish structure that flips bullish (CHoCH)
    - Asian session range with a sweep of the low
    - M1 CHoCH after the sweep
    - M5 order block before impulse
    - Price reaching the liquidity target

    Returns (candles_m15, candles_m5, candles_m1, candles_post_entry).
    """
    EST = timezone(timedelta(hours=-5))

    # ── M15 Candles: 48+ hours of data ──
    # Build a bearish structure that flips bullish
    base_time = datetime(2024, 1, 15, 10, 0, tzinfo=EST)
    m15: list[Candle] = []

    # M15 data: 50+ candles for reliable swing detection (lookback=3 needs 3+ each side)
    # Structure: early equal highs → long bearish → CHoCH to bullish
    all_prices = [
        # -- Block 1: Rally up creating equal highs (future TP targets) --
        (1.0840, 1.0848, 1.0838, 1.0845),
        (1.0845, 1.0855, 1.0842, 1.0852),
        (1.0852, 1.0865, 1.0850, 1.0862),
        (1.0862, 1.0878, 1.0860, 1.0875),
        (1.0875, 1.0890, 1.0872, 1.0888),
        (1.0888, 1.0900, 1.0885, 1.0895),   # SH at 1.0900
        (1.0895, 1.0898, 1.0882, 1.0885),   # Down
        (1.0885, 1.0888, 1.0875, 1.0878),   # Down
        (1.0878, 1.0882, 1.0870, 1.0875),   # Down
        (1.0875, 1.0880, 1.0868, 1.0878),   # SL / bounce
        (1.0878, 1.0885, 1.0875, 1.0882),   # Up
        (1.0882, 1.0892, 1.0880, 1.0890),
        (1.0890, 1.0901, 1.0888, 1.0895),   # Equal SH at 1.0901 (TP target!)
        (1.0895, 1.0898, 1.0880, 1.0882),   # Down
        (1.0882, 1.0885, 1.0872, 1.0875),   # Down
        (1.0875, 1.0878, 1.0865, 1.0868),   # Down
        # -- Block 2: Bearish trend begins (7-swing bearish staircase) --
        (1.0868, 1.0870, 1.0855, 1.0858),
        (1.0858, 1.0860, 1.0845, 1.0848),
        (1.0848, 1.0852, 1.0838, 1.0842),   # LL
        (1.0842, 1.0855, 1.0840, 1.0852),   # LH retrace
        (1.0852, 1.0856, 1.0842, 1.0845),
        (1.0845, 1.0848, 1.0832, 1.0835),   # LL
        (1.0835, 1.0838, 1.0828, 1.0830),
        (1.0830, 1.0845, 1.0828, 1.0842),   # LH retrace
        (1.0842, 1.0846, 1.0835, 1.0838),
        (1.0838, 1.0840, 1.0825, 1.0828),   # LL
        (1.0828, 1.0832, 1.0820, 1.0822),
        (1.0822, 1.0835, 1.0820, 1.0832),   # LH retrace
        (1.0832, 1.0836, 1.0825, 1.0828),
        (1.0828, 1.0830, 1.0815, 1.0818),   # LL
        (1.0818, 1.0822, 1.0812, 1.0815),
        (1.0815, 1.0828, 1.0812, 1.0825),   # LH retrace
        (1.0825, 1.0828, 1.0818, 1.0820),
        (1.0820, 1.0822, 1.0808, 1.0810),   # LL
        (1.0810, 1.0815, 1.0805, 1.0808),
        (1.0808, 1.0820, 1.0805, 1.0818),   # LH retrace
        (1.0818, 1.0822, 1.0812, 1.0815),
        (1.0815, 1.0818, 1.0800, 1.0802),   # LL (deepest)
        # -- Block 3: CHoCH — breaks above last LH → BULLISH --
        (1.0802, 1.0810, 1.0798, 1.0808),
        (1.0808, 1.0818, 1.0805, 1.0815),
        (1.0815, 1.0825, 1.0812, 1.0822),   # Close above LH = CHoCH!
        (1.0822, 1.0835, 1.0820, 1.0832),   # Continuation
        (1.0832, 1.0842, 1.0828, 1.0838),   # More continuation
    ]
    for i, (o, h, l, c) in enumerate(all_prices):
        m15.append(Candle(
            time=base_time + timedelta(minutes=15 * i),
            open=o, high=h, low=l, close=c,
        ))

    # ── M1 Candles: Asian session + sweep + CHoCH ──
    asia_start = datetime(2024, 1, 15, 20, 0, tzinfo=EST)
    m1: list[Candle] = []

    # Asian session range: 20:00-00:00 EST, range ~1.0815-1.0835
    for i in range(240):  # 4 hours of M1
        t = asia_start + timedelta(minutes=i)
        base = 1.0825 + 0.0005 * (i % 7 - 3)  # Range-bound
        m1.append(Candle(
            time=t,
            open=base,
            high=base + 0.0005,
            low=base - 0.0005,
            close=base + 0.0002 * (1 if i % 3 else -1),
        ))

    # Post-session: sweep the Asian low (~1.0810)
    sweep_start = datetime(2024, 1, 16, 2, 0, tzinfo=EST)
    # Bearish push below Asian low
    sweep_prices = [
        (1.0820, 1.0823, 1.0812, 1.0815),
        (1.0815, 1.0818, 1.0808, 1.0810),
        (1.0810, 1.0813, 1.0802, 1.0805),  # Below Asia low
        (1.0805, 1.0808, 1.0798, 1.0800),  # Deepest sweep
        (1.0800, 1.0812, 1.0798, 1.0810),  # Bounce starts
        (1.0810, 1.0818, 1.0808, 1.0815),
        (1.0815, 1.0822, 1.0812, 1.0818),  # Swing high at 1.0822
        (1.0818, 1.0820, 1.0808, 1.0810),
        (1.0810, 1.0812, 1.0800, 1.0802),  # New low
        (1.0802, 1.0815, 1.0800, 1.0812),
        (1.0812, 1.0820, 1.0810, 1.0818),  # Another swing high at 1.0820
        (1.0818, 1.0817, 1.0808, 1.0810),
        (1.0810, 1.0814, 1.0804, 1.0808),
        (1.0808, 1.0825, 1.0806, 1.0822),  # CHoCH! Close above 1.0820
        (1.0822, 1.0832, 1.0820, 1.0830),  # Continuation up
    ]
    for i, (o, h, l, c) in enumerate(sweep_prices):
        m1.append(Candle(
            time=sweep_start + timedelta(minutes=i),
            open=o, high=h, low=l, close=c,
        ))

    # ── M5 Candles: order block before impulse ──
    ob_start = datetime(2024, 1, 16, 1, 45, tzinfo=EST)
    m5: list[Candle] = []

    m5_prices = [
        (1.0820, 1.0822, 1.0810, 1.0812),
        (1.0812, 1.0815, 1.0802, 1.0805),
        (1.0805, 1.0808, 1.0798, 1.0800),  # Sweep low
        # Order block (consolidation) — 3 tight candles in narrow range
        (1.0800, 1.0806, 1.0798, 1.0804),
        (1.0804, 1.0806, 1.0800, 1.0802),
        (1.0802, 1.0805, 1.0799, 1.0803),
        # Strong impulse up (breaks M1 structure → CHoCH)
        (1.0803, 1.0830, 1.0802, 1.0828),
        (1.0828, 1.0845, 1.0825, 1.0842),
    ]
    for i, (o, h, l, c) in enumerate(m5_prices):
        m5.append(Candle(
            time=ob_start + timedelta(minutes=5 * i),
            open=o, high=h, low=l, close=c,
        ))

    # ── Post-entry candles (for backtesting — price rallies to TP) ──
    post_entry: list[Candle] = []
    post_start = datetime(2024, 1, 16, 3, 0, tzinfo=EST)
    post_prices = [
        (1.0832, 1.0842, 1.0828, 1.0840),
        (1.0840, 1.0855, 1.0838, 1.0852),
        (1.0852, 1.0862, 1.0848, 1.0858),
        (1.0858, 1.0872, 1.0855, 1.0870),
        (1.0870, 1.0882, 1.0868, 1.0880),
        (1.0880, 1.0892, 1.0878, 1.0890),
        (1.0890, 1.0905, 1.0888, 1.0902),  # TP hit at ~1.0900
    ]
    for i, (o, h, l, c) in enumerate(post_prices):
        post_entry.append(Candle(
            time=post_start + timedelta(minutes=15 * i),
            open=o, high=h, low=l, close=c,
        ))

    return m15, m5, m1, post_entry


def run_demo() -> None:
    """Run the pipeline with synthetic demo data."""
    logger.info("Generating demo data for ICT strategy simulation...")
    m15, m5, m1, post_entry = generate_demo_data()

    orchestrator = TradingBotOrchestrator(instrument="EUR/USD")
    state = orchestrator.run(
        candles_m15=m15,
        candles_m5=m5,
        candles_m1=m1,
        candles_post_entry=post_entry,
    )

    orchestrator.print_summary(state)


def run_live(exchange_id: str, symbol: str) -> None:
    """Run the pipeline with live data from a CCXT exchange.

    Requires ccxt to be installed: pip install ccxt
    """
    try:
        import ccxt
    except ImportError:
        logger.error("ccxt is required for live mode: pip install ccxt")
        sys.exit(1)

    exchange_class = getattr(ccxt, exchange_id, None)
    if exchange_class is None:
        logger.error("Unknown exchange: {}", exchange_id)
        sys.exit(1)

    exchange = exchange_class({"enableRateLimit": True})
    logger.info("Fetching data from {} for {}...", exchange_id, symbol)

    def fetch_candles(timeframe: str, limit: int) -> list[Candle]:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return [
            Candle(
                time=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in ohlcv
        ]

    candles_m15 = fetch_candles("15m", 200)
    candles_m5 = fetch_candles("5m", 100)
    candles_m1 = fetch_candles("1m", 500)

    orchestrator = TradingBotOrchestrator(instrument=symbol)
    state = orchestrator.run(
        candles_m15=candles_m15,
        candles_m5=candles_m5,
        candles_m1=candles_m1,
    )

    orchestrator.print_summary(state)


def main() -> None:
    parser = argparse.ArgumentParser(description="ICT Trading Bot — 5-Step Pipeline")
    parser.add_argument(
        "--mode",
        choices=["demo", "live"],
        default="demo",
        help="Run mode: 'demo' with synthetic data or 'live' with exchange data",
    )
    parser.add_argument("--exchange", default="binance", help="CCXT exchange ID (for live mode)")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair (for live mode)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if not args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    if args.mode == "demo":
        run_demo()
    else:
        run_live(args.exchange, args.symbol)


if __name__ == "__main__":
    main()
