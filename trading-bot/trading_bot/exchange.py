"""Exchange data fetcher — real market data via public API (no auth required)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import ccxt

from .config import UTC_TZ
from .models import Candle

logger = logging.getLogger(__name__)

# Timeframe → milliseconds
TF_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class ExchangeFetcher:
    """Fetches real OHLCV data from Binance public API (no API key needed)."""

    def __init__(self, exchange_id: str = "binance"):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})
        self._markets_loaded = False
        logger.info(f"Initialized {exchange_id} fetcher (public data only)")

    def _ensure_markets(self):
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._markets_loaded = True

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[Candle]:
        """Fetch OHLCV candles from exchange."""
        self._ensure_markets()
        since_ms = int(since.timestamp() * 1000) if since else None
        raw = self.exchange.fetch_ohlcv(
            symbol, timeframe, since=since_ms, limit=limit
        )
        candles = []
        for row in raw:
            ts, o, h, l, c, v = row
            candles.append(Candle(
                timestamp=datetime.fromtimestamp(ts / 1000, tz=UTC_TZ),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(l)),
                close=Decimal(str(c)),
                volume=Decimal(str(v)),
            ))
        return candles

    def fetch_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch all candles in a date range (handles pagination)."""
        all_candles: list[Candle] = []
        current = start
        tf_ms = TF_MS.get(timeframe, 300_000)

        while current < end:
            batch = self.fetch_candles(symbol, timeframe, since=current, limit=1000)
            if not batch:
                break

            for c in batch:
                if c.timestamp >= end:
                    break
                if not all_candles or c.timestamp > all_candles[-1].timestamp:
                    all_candles.append(c)

            last_ts = batch[-1].timestamp
            next_ts = last_ts + timedelta(milliseconds=tf_ms)
            if next_ts <= current:
                break
            current = next_ts

        logger.info(
            f"Fetched {len(all_candles)} {timeframe} candles for {symbol} "
            f"from {start.date()} to {end.date()}"
        )
        return all_candles

    def get_current_price(self, symbol: str) -> Decimal:
        """Get current market price."""
        self._ensure_markets()
        ticker = self.exchange.fetch_ticker(symbol)
        return Decimal(str(ticker["last"]))
