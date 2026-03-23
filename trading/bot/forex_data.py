"""Real-time forex data provider using free public APIs.

Data sources (no API key required):
    1. Primary:   OANDA public candle API (demo/practice environment)
    2. Fallback:  Twelve Data free tier (up to 800 req/day, needs key)
    3. Fallback:  Alpha Vantage (5 req/min free tier, needs key)

For paper trading, OANDA demo is recommended — free, no key needed for price data.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from trading.bot.models import Candle

# OANDA instrument mapping (forex pair → OANDA format)
_OANDA_INSTRUMENTS = {
    "EUR/USD": "EUR_USD",
    "GBP/USD": "GBP_USD",
    "USD/JPY": "USD_JPY",
    "USD/CHF": "USD_CHF",
    "AUD/USD": "AUD_USD",
    "NZD/USD": "NZD_USD",
    "USD/CAD": "USD_CAD",
    "EUR/GBP": "EUR_GBP",
    "EUR/JPY": "EUR_JPY",
    "GBP/JPY": "GBP_JPY",
}

# Timeframe mapping
_TF_MAP = {
    "M1": "M1",
    "M5": "M5",
    "M15": "M15",
    "H1": "H1",
    "H4": "H4",
    "D": "D",
}


class ForexDataProvider:
    """Fetches real forex OHLCV candle data from free APIs.

    Usage:
        provider = ForexDataProvider()
        candles = provider.fetch_candles("EUR/USD", "M15", count=200)
    """

    # OANDA public demo API (no auth needed for price data)
    OANDA_BASE = "https://api-fxpractice.oanda.com"

    def __init__(self, oanda_token: str | None = None, twelve_data_key: str | None = None) -> None:
        """Initialize data provider.

        Args:
            oanda_token: OANDA demo account API token (free at oanda.com/demo-account).
                         If None, tries config.json, then env var OANDA_API_TOKEN.
            twelve_data_key: Twelve Data API key as fallback. If None, tries config.json, then TWELVE_DATA_KEY.
        """
        import os
        config = self._load_config()
        self.oanda_token = oanda_token or os.environ.get("OANDA_API_TOKEN", "") or config.get("oanda_token", "")
        self.twelve_data_key = twelve_data_key or os.environ.get("TWELVE_DATA_KEY", "") or config.get("twelve_data_key", "")

    @staticmethod
    def _load_config() -> dict:
        """Try to load config.json from the bot directory."""
        for path in ("config.json", "trading/bot/config.json"):
            try:
                return json.loads(Path(path).read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                continue
        return {}

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 200,
    ) -> list[Candle]:
        """Fetch candles from the best available source.

        Args:
            symbol: Forex pair (e.g. "EUR/USD").
            timeframe: "M1", "M5", "M15", "H1", "H4", "D".
            count: Number of candles to fetch (max ~5000 for OANDA).

        Returns:
            List of Candle objects, oldest first.
        """
        # Try OANDA first (best for forex)
        if self.oanda_token:
            try:
                return self._fetch_oanda(symbol, timeframe, count)
            except Exception as e:
                logger.warning("OANDA failed: {} — trying fallback", e)

        # Fallback: Twelve Data
        if self.twelve_data_key:
            try:
                return self._fetch_twelve_data(symbol, timeframe, count)
            except Exception as e:
                logger.warning("Twelve Data failed: {} — no more sources", e)

        raise RuntimeError(
            "No data source available. Set OANDA_API_TOKEN (free demo account at oanda.com) "
            "or TWELVE_DATA_KEY (free at twelvedata.com)."
        )

    def get_current_price(self, symbol: str) -> dict[str, float]:
        """Get current bid/ask price.

        Returns:
            {"bid": float, "ask": float, "mid": float}
        """
        if self.oanda_token:
            try:
                return self._get_oanda_price(symbol)
            except Exception as e:
                logger.warning("OANDA price failed: {}", e)

        # Fallback: use last M1 candle close
        try:
            candles = self.fetch_candles(symbol, "M1", count=1)
            if candles:
                price = candles[-1].close
                spread = 0.00015  # ~1.5 pips typical EUR/USD spread
                return {
                    "bid": price - spread / 2,
                    "ask": price + spread / 2,
                    "mid": price,
                }
        except Exception:
            pass

        raise RuntimeError(f"Cannot get price for {symbol}")

    # -- OANDA --

    def _fetch_oanda(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        instrument = _OANDA_INSTRUMENTS.get(symbol)
        if instrument is None:
            raise ValueError(f"Unknown symbol for OANDA: {symbol}. Supported: {list(_OANDA_INSTRUMENTS.keys())}")

        granularity = _TF_MAP.get(timeframe, timeframe)
        url = (
            f"{self.OANDA_BASE}/v3/instruments/{instrument}/candles"
            f"?granularity={granularity}&count={count}&price=M"
        )

        data = self._http_get(url, headers={"Authorization": f"Bearer {self.oanda_token}"})
        candles = []
        for c in data.get("candles", []):
            if not c.get("complete", True):
                continue
            mid = c["mid"]
            candles.append(Candle(
                time=datetime.fromisoformat(c["time"].replace("000Z", "+00:00").rstrip("Z") + "+00:00")
                     if "Z" in c["time"]
                     else datetime.fromisoformat(c["time"]),
                open=float(mid["o"]),
                high=float(mid["h"]),
                low=float(mid["l"]),
                close=float(mid["c"]),
                volume=int(c.get("volume", 0)),
            ))

        logger.info("OANDA: fetched {} {} candles for {}", len(candles), timeframe, symbol)
        return candles

    def _get_oanda_price(self, symbol: str) -> dict[str, float]:
        instrument = _OANDA_INSTRUMENTS.get(symbol)
        if instrument is None:
            raise ValueError(f"Unknown symbol: {symbol}")

        url = f"{self.OANDA_BASE}/v3/instruments/{instrument}/candles?granularity=S5&count=1&price=BA"
        data = self._http_get(url, headers={"Authorization": f"Bearer {self.oanda_token}"})

        candle = data["candles"][-1]
        bid_close = float(candle["bid"]["c"])
        ask_close = float(candle["ask"]["c"])
        return {
            "bid": bid_close,
            "ask": ask_close,
            "mid": (bid_close + ask_close) / 2,
        }

    # -- Twelve Data --

    def _fetch_twelve_data(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        tf_map = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D": "1day"}
        interval = tf_map.get(timeframe)
        if interval is None:
            raise ValueError(f"Unsupported timeframe for Twelve Data: {timeframe}")

        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval={interval}&outputsize={count}"
            f"&apikey={self.twelve_data_key}"
        )

        data = self._http_get(url)

        if "values" not in data:
            raise RuntimeError(f"Twelve Data error: {data.get('message', 'unknown')}")

        candles = []
        for v in reversed(data["values"]):  # Reverse: API returns newest first
            candles.append(Candle(
                time=datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
                open=float(v["open"]),
                high=float(v["high"]),
                low=float(v["low"]),
                close=float(v["close"]),
            ))

        logger.info("Twelve Data: fetched {} {} candles for {}", len(candles), timeframe, symbol)
        return candles

    # -- HTTP --

    def _http_get(self, url: str, headers: dict | None = None, retries: int = 3) -> dict:
        """Make an HTTP GET request with retries."""
        req = urllib.request.Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Rate limited, waiting {}s...", wait)
                    time.sleep(wait)
                    continue
                raise
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                raise

        raise RuntimeError(f"Failed after {retries} retries: {url}")
