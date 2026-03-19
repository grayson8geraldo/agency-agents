#!/usr/bin/env python3
"""
Crypto Futures Trading Bot — Multi-Agent System
================================================

Agents involved:
  1. Quant Strategist     — Signal generation, backtesting, Sharpe optimization
  2. Crypto Risk Manager  — Kelly sizing, drawdown control, kill switches
  3. Crypto Market Analyst — Multi-factor market analysis
  4. Trading Bot Developer — Order execution, monitoring, fault tolerance
  5. On-Chain Analyst      — Whale tracking, exchange flows, network health

Usage:
  python main.py backtest              # Backtest with REAL Binance data
  python main.py backtest --sample     # Backtest with generated sample data (offline)
  python main.py paper [minutes]       # Live paper trading (needs network)
  python main.py analyze [symbol]      # Analyze a pair (needs network)
  python main.py analyze --sample      # Analyze with sample data (offline)
  python main.py status                # Show strategy and risk parameters

Virtual balance: $200 → target $1,200 in 14 days using futures with leverage.
When network is available, data is REAL (from Binance). All trades are VIRTUAL.
Use --sample flag for offline testing with realistic generated data.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from engine.signal_generator import SignalGenerator
from engine.risk_manager import RiskManager
from engine.virtual_exchange import VirtualExchange
from engine.backtester import Backtester


USE_SAMPLE = "--sample" in sys.argv


def _get_data(symbols=None, days=None):
    """Fetch data from Binance or generate sample data."""
    if symbols is None:
        symbols = cfg.TRADING_PAIRS
    if days is None:
        days = cfg.LOOKBACK_DAYS

    if USE_SAMPLE:
        from utils.sample_data import generate_multiple_pairs
        print("  [SAMPLE MODE] Using generated data (no network required)")
        return generate_multiple_pairs(symbols, days=days, timeframe_minutes=15, seed=42)
    else:
        from utils.data_fetcher import fetch_multiple_pairs
        return fetch_multiple_pairs(symbols, timeframe=cfg.CANDLE_TIMEFRAME, days=days)


def cmd_backtest():
    """Run historical backtest."""
    print("\n[1/3] Fetching data...")
    data = _get_data()

    print("\n[2/3] Running backtest...")
    bt = Backtester(cfg)
    results = bt.run(data, verbose=True)

    print("\n[3/3] Saving results...")
    bt.exchange.save_trades()
    print(f"  Trade log: {cfg.TRADE_LOG_FILE}")

    return results


def cmd_paper(duration_minutes: int = 60):
    """Run live paper trading (requires network)."""
    if USE_SAMPLE:
        print("\n  Paper trading with sample data is not supported.")
        print("  Use 'backtest --sample' instead for offline testing.")
        return
    from engine.paper_trader import PaperTrader
    trader = PaperTrader(cfg)
    trader.run(duration_minutes=duration_minutes, interval_seconds=60)


def cmd_analyze(symbol: str = "BTC/USDT"):
    """Analyze a specific trading pair."""
    print(f"\n  Analyzing {symbol}...")

    if USE_SAMPLE:
        from utils.sample_data import generate_ohlcv
        print("  [SAMPLE MODE] Using generated data")
        df = generate_ohlcv(symbol, days=7, timeframe_minutes=15, seed=42)
    else:
        from utils.data_fetcher import fetch_ohlcv, get_exchange, fetch_funding_rate, fetch_ticker
        print("  Fetching data from Binance...")
        exchange = get_exchange()
        df = fetch_ohlcv(symbol, cfg.CANDLE_TIMEFRAME, days=7, exchange=exchange)

    print(f"  {len(df)} candles loaded")

    sg = SignalGenerator(cfg)

    # Market summary (Market Analyst)
    summary = sg.get_market_summary(df)
    print(f"\n  === Market Summary: {symbol} ===")
    for k, v in summary.items():
        print(f"  {k:>20}: {v}")

    # Current signal (Quant Strategist)
    signal = sg.evaluate_current(df, symbol)
    if signal:
        print(f"\n  === Active Signal ===")
        print(f"  Type:       {signal.signal_type.value}")
        print(f"  Entry:      {signal.entry_price:.2f}")
        print(f"  Stop Loss:  {signal.stop_loss:.2f}")
        print(f"  Take Profit:{signal.take_profit:.2f}")
        print(f"  Confidence: {signal.confidence:.0%}")
        print(f"  Leverage:   {signal.leverage}x")
        print(f"  Regime:     {signal.volatility_regime}")
        print(f"  Reason:     {signal.reason}")
    else:
        print("\n  No active signal — conditions not met.")

    # Funding rate & ticker (only with real data)
    if not USE_SAMPLE:
        from utils.data_fetcher import fetch_funding_rate, fetch_ticker, get_exchange
        exchange = get_exchange()
        fr = fetch_funding_rate(symbol, exchange)
        print(f"\n  Funding rate: {fr:.4%}")
        if abs(fr) > 0.001:
            direction = "Longs pay shorts" if fr > 0 else "Shorts pay longs"
            print(f"  -> {direction} (contrarian signal)")

        ticker = fetch_ticker(symbol, exchange)
        if ticker:
            print(f"\n  Current price: ${ticker.get('last', 'N/A')}")
            print(f"  24h volume:    ${ticker.get('quoteVolume', 0):,.0f}")
            print(f"  24h change:    {ticker.get('percentage', 0):.2f}%")

    # Risk assessment
    rm = RiskManager(cfg)
    print(f"\n  === Risk Parameters ===")
    report = rm.get_risk_report()
    for k, v in report.items():
        print(f"  {k:>20}: {v}")


def cmd_status():
    """Print current strategy configuration and risk parameters."""
    print("\n" + "=" * 60)
    print("  CRYPTO FUTURES TRADING STRATEGY — Configuration")
    print("=" * 60)

    print("\n  --- Account ---")
    print(f"  Starting balance:   ${cfg.STARTING_BALANCE:.2f}")
    print(f"  Target:             ${cfg.TARGET_BALANCE:.2f}")
    print(f"  Required return:    {(cfg.TARGET_BALANCE / cfg.STARTING_BALANCE - 1) * 100:.0f}%")
    print(f"  Time horizon:       {cfg.TRADING_DAYS} days")

    print("\n  --- Strategy ---")
    print(f"  Primary timeframe:  {cfg.CANDLE_TIMEFRAME}")
    print(f"  Confirmation:       {cfg.CONFIRMATION_TIMEFRAME}")
    print(f"  EMA:                {cfg.EMA_FAST}/{cfg.EMA_SLOW}")
    print(f"  RSI:                {cfg.RSI_PERIOD} (long>{cfg.RSI_LONG_THRESHOLD}, short<{cfg.RSI_SHORT_THRESHOLD})")
    print(f"  RR ratio:           {cfg.REWARD_RISK_RATIO}:1")
    print(f"  Volume threshold:   {cfg.VOLUME_THRESHOLD}x average")

    print("\n  --- Risk Management ---")
    print(f"  Default leverage:   {cfg.DEFAULT_LEVERAGE}x")
    print(f"  Max leverage:       {cfg.MAX_LEVERAGE}x")
    print(f"  Max risk/trade:     {cfg.MAX_RISK_PER_TRADE:.0%}")
    print(f"  Max positions:      {cfg.MAX_CONCURRENT_POSITIONS}")
    print(f"  Daily loss limit:   {cfg.DAILY_LOSS_LIMIT:.0%}")
    print(f"  Weekly loss limit:  {cfg.WEEKLY_LOSS_LIMIT:.0%}")
    print(f"  Max drawdown:       {cfg.MAX_DRAWDOWN:.0%}")
    print(f"  Kill switch:        {cfg.KILL_SWITCH_DRAWDOWN:.0%}")
    print(f"  Kelly fraction:     {cfg.KELLY_FRACTION} (half-Kelly)")

    print("\n  --- Fees ---")
    print(f"  Maker fee:          {cfg.MAKER_FEE:.2%}")
    print(f"  Taker fee:          {cfg.TAKER_FEE:.2%}")
    print(f"  Slippage est:       {cfg.SLIPPAGE:.2%}")

    print("\n  --- Trading Pairs ---")
    for pair in cfg.TRADING_PAIRS:
        print(f"    - {pair}")

    print("\n  --- Agents ---")
    print("    1. Quant Strategist     — Signals, backtesting, Sharpe optimization")
    print("    2. Crypto Risk Manager  — Kelly sizing, drawdown, kill switches")
    print("    3. Crypto Market Analyst — TA + fundamentals + sentiment")
    print("    4. Trading Bot Developer — Execution, monitoring, fault tolerance")
    print("    5. On-Chain Analyst      — Whales, flows, network health")
    print("=" * 60)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("Commands: backtest | paper [minutes] | analyze [symbol] | status")
        print("Add --sample flag for offline testing with generated data.")
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "backtest":
        cmd_backtest()
    elif command == "paper":
        minutes = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 60
        cmd_paper(minutes)
    elif command == "analyze":
        symbol = None
        for arg in sys.argv[2:]:
            if arg != "--sample" and "/" in arg:
                symbol = arg
        if symbol is None:
            symbol = "BTC/USDT"
        cmd_analyze(symbol)
    elif command == "status":
        cmd_status()
    else:
        print(f"Unknown command: {command}")
        print("Commands: backtest | paper [minutes] | analyze [symbol] | status")
        sys.exit(1)


if __name__ == "__main__":
    main()
