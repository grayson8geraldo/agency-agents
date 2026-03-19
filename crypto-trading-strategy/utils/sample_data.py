"""
Sample data generator for testing when exchange API is not available.
Generates realistic-looking OHLCV data based on geometric Brownian motion.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone


def generate_ohlcv(
    symbol: str = "BTC/USDT",
    days: int = 90,
    timeframe_minutes: int = 15,
    start_price: float = None,
    volatility: float = None,
    trend: float = 0.0001,
    seed: int = None,
) -> pd.DataFrame:
    """
    Generate realistic OHLCV data using geometric Brownian motion.

    Args:
        symbol: Trading pair (used to set default price/vol)
        days: Number of days of data
        timeframe_minutes: Candle interval in minutes
        start_price: Starting price (auto-detected from symbol)
        volatility: Per-bar volatility (auto-detected from symbol)
        trend: Drift per bar (positive = uptrend)
        seed: Random seed for reproducibility
    """
    if seed is not None:
        np.random.seed(seed)

    # Default prices and volatility per symbol
    defaults = {
        "BTC/USDT": {"price": 84000, "vol": 0.003},
        "ETH/USDT": {"price": 1900, "vol": 0.004},
        "SOL/USDT": {"price": 130, "vol": 0.006},
        "DOGE/USDT": {"price": 0.17, "vol": 0.008},
    }

    sym_defaults = defaults.get(symbol, {"price": 100, "vol": 0.005})
    if start_price is None:
        start_price = sym_defaults["price"]
    if volatility is None:
        volatility = sym_defaults["vol"]

    bars_per_day = 24 * 60 // timeframe_minutes
    total_bars = days * bars_per_day

    # Generate close prices via GBM
    returns = np.random.normal(trend, volatility, total_bars)
    prices = start_price * np.exp(np.cumsum(returns))

    # Add some regime changes (trending / mean-reverting / volatile)
    regime_length = bars_per_day * 3  # ~3 day regimes
    for i in range(0, total_bars, regime_length):
        regime = np.random.choice(["trend_up", "trend_down", "range", "volatile"], p=[0.3, 0.2, 0.3, 0.2])
        end = min(i + regime_length, total_bars)
        if regime == "trend_up":
            drift = np.linspace(0, volatility * 2, end - i)
            prices[i:end] *= np.exp(np.cumsum(np.random.normal(0.001, volatility * 0.5, end - i) + drift * 0.01))
        elif regime == "trend_down":
            drift = np.linspace(0, -volatility * 2, end - i)
            prices[i:end] *= np.exp(np.cumsum(np.random.normal(-0.001, volatility * 0.5, end - i) + drift * 0.01))
        elif regime == "volatile":
            prices[i:end] *= np.exp(np.cumsum(np.random.normal(0, volatility * 2, end - i)))
        # "range" keeps default

    # Normalize back to reasonable levels
    prices = prices / prices[0] * start_price

    # Generate OHLC from close
    opens = np.roll(prices, 1)
    opens[0] = start_price

    # High and low with realistic wicks
    wick_up = np.abs(np.random.normal(0, volatility * 0.5, total_bars))
    wick_down = np.abs(np.random.normal(0, volatility * 0.5, total_bars))
    highs = np.maximum(opens, prices) * (1 + wick_up)
    lows = np.minimum(opens, prices) * (1 - wick_down)

    # Generate volume (log-normal with time-of-day pattern)
    base_volume = np.random.lognormal(mean=10, sigma=1.5, size=total_bars)
    # Time-of-day volume pattern (higher during US/EU hours)
    tod_pattern = np.tile(
        np.concatenate([
            np.linspace(0.5, 0.8, bars_per_day // 6),    # Asian early
            np.linspace(0.8, 1.2, bars_per_day // 6),    # Asian late
            np.linspace(1.2, 1.8, bars_per_day // 6),    # EU open
            np.linspace(1.8, 2.0, bars_per_day // 6),    # US open
            np.linspace(2.0, 1.5, bars_per_day // 6),    # US afternoon
            np.linspace(1.5, 0.5, bars_per_day // 6),    # Night
        ]),
        days + 1,
    )[:total_bars]
    volume = base_volume * tod_pattern

    # Volume spikes on big moves
    price_change = np.abs(np.diff(prices, prepend=prices[0])) / prices
    volume *= (1 + price_change * 50)

    # Timestamps
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, periods=total_bars, freq=f"{timeframe_minutes}min", tz=timezone.utc)

    df = pd.DataFrame({
        "timestamp": timestamps[:total_bars],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volume,
    })

    return df


def generate_multiple_pairs(
    symbols: list = None,
    days: int = 90,
    timeframe_minutes: int = 15,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Generate sample data for multiple trading pairs with correlated moves."""
    if symbols is None:
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    data = {}
    for i, symbol in enumerate(symbols):
        print(f"  Generating {symbol} sample data ({days}d, {timeframe_minutes}m)...")
        df = generate_ohlcv(symbol, days=days, timeframe_minutes=timeframe_minutes, seed=seed + i)
        print(f"  → {len(df)} candles")
        data[symbol] = df

    return data
