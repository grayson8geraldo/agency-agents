"""
Real market data fetcher using ccxt.
Pulls OHLCV data from Bybit (public endpoints, no API key needed).
"""

import time
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd


def get_exchange():
    """Create a Bybit exchange instance (public data only)."""
    exchange = ccxt.bybit({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    return exchange


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    days: int = 90,
    exchange: ccxt.Exchange = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candle data from Bybit Futures.
    Returns a DataFrame with columns: timestamp, open, high, low, close, volume.
    Handles Bybit's 200-candle limit per request with proper pagination.
    """
    if exchange is None:
        exchange = get_exchange()

    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    all_candles = []
    limit = 200  # Bybit max per request
    retries = 0

    while since < end_ms:
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            retries = 0
        except ccxt.NetworkError:
            retries += 1
            if retries > 4:
                print(f"Network error fetching {symbol}, giving up after 4 retries")
                break
            time.sleep(2 ** retries)
            continue
        except ccxt.ExchangeError as e:
            print(f"Exchange error fetching {symbol}: {e}")
            break

        if not candles:
            break

        # Sort candles by timestamp (Bybit may return in reverse order)
        candles.sort(key=lambda x: x[0])

        all_candles.extend(candles)
        since = candles[-1][0] + 1  # Next candle after last

        if len(candles) < limit:
            break

        time.sleep(exchange.rateLimit / 1000)

    if not all_candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_multiple_pairs(symbols: list, timeframe: str = "15m", days: int = 90) -> dict:
    """Fetch OHLCV data for multiple trading pairs."""
    exchange = get_exchange()
    data = {}
    for symbol in symbols:
        print(f"  Fetching {symbol} ({timeframe}, {days}d)...")
        data[symbol] = fetch_ohlcv(symbol, timeframe, days, exchange)
        print(f"  → {len(data[symbol])} candles")
    return data


def fetch_funding_rate(symbol: str = "BTC/USDT", exchange: ccxt.Exchange = None) -> float:
    """Fetch current funding rate for a perpetual futures contract."""
    if exchange is None:
        exchange = get_exchange()
    try:
        funding = exchange.fetch_funding_rate(symbol)
        return funding.get("fundingRate", 0.0)
    except Exception:
        return 0.0


def fetch_ticker(symbol: str = "BTC/USDT", exchange: ccxt.Exchange = None) -> dict:
    """Fetch current ticker data (price, volume, etc.)."""
    if exchange is None:
        exchange = get_exchange()
    try:
        return exchange.fetch_ticker(symbol)
    except Exception:
        return {}


def fetch_orderbook(symbol: str = "BTC/USDT", limit: int = 20, exchange: ccxt.Exchange = None) -> dict:
    """Fetch current orderbook."""
    if exchange is None:
        exchange = get_exchange()
    try:
        return exchange.fetch_order_book(symbol, limit=limit)
    except Exception:
        return {"bids": [], "asks": []}
