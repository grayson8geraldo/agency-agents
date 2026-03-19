"""Forex data fetcher — real market data via yfinance (free, no auth)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import pandas as pd
import yfinance as yf

from .config import UTC_TZ, get_pair_name
from .models import Candle

logger = logging.getLogger(__name__)

# yfinance interval mapping
YF_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "1d",
}

# yfinance max period per interval
# 1m: 7 days, 5m: 60 days, 15m: 60 days, 1h: 730 days
YF_MAX_DAYS = {
    "1m": 7,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "1d": 10000,
}


class ForexFetcher:
    """Fetches real forex OHLCV data via Yahoo Finance (no API key needed)."""

    def __init__(self):
        logger.info("Initialized Yahoo Finance forex fetcher")

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        period: Optional[str] = None,
    ) -> list[Candle]:
        """
        Fetch OHLCV candles for a forex pair.

        Args:
            symbol: Yahoo Finance ticker (e.g. "EURUSD=X")
            timeframe: Candle interval ("5m", "15m", "1h", etc.)
            start: Start datetime (UTC)
            end: End datetime (UTC)
            period: Alternative to start/end (e.g. "5d", "1mo")
        """
        interval = YF_INTERVALS.get(timeframe, timeframe)
        ticker = yf.Ticker(symbol)
        pair_name = get_pair_name(symbol)

        try:
            if start and end:
                df = ticker.history(
                    interval=interval,
                    start=start.strftime("%Y-%m-%d"),
                    end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                )
            elif period:
                df = ticker.history(interval=interval, period=period)
            else:
                df = ticker.history(interval=interval, period="5d")
        except Exception as e:
            logger.error(f"Failed to fetch {pair_name} {timeframe}: {e}")
            return []

        if df.empty:
            logger.warning(f"No data returned for {pair_name} {timeframe}")
            return []

        candles = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC_TZ)
            else:
                ts = ts.astimezone(UTC_TZ)

            candles.append(Candle(
                timestamp=ts,
                open=Decimal(str(round(row["Open"], 6))),
                high=Decimal(str(round(row["High"], 6))),
                low=Decimal(str(round(row["Low"], 6))),
                close=Decimal(str(round(row["Close"], 6))),
                volume=Decimal(str(int(row.get("Volume", 0)))),
            ))

        logger.info(f"Fetched {len(candles)} {timeframe} candles for {pair_name}")
        return candles

    def fetch_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Fetch all candles in a date range.
        Handles yfinance limitations on max range per interval.
        """
        max_days = YF_MAX_DAYS.get(timeframe, 60)
        all_candles: list[Candle] = []
        current_start = start

        while current_start < end:
            chunk_end = min(current_start + timedelta(days=max_days - 1), end)

            batch = self.fetch_candles(
                symbol, timeframe,
                start=current_start, end=chunk_end,
            )

            for c in batch:
                if c.timestamp < start.astimezone(UTC_TZ):
                    continue
                if c.timestamp > end.astimezone(UTC_TZ):
                    break
                if not all_candles or c.timestamp > all_candles[-1].timestamp:
                    all_candles.append(c)

            current_start = chunk_end + timedelta(days=1)

        pair_name = get_pair_name(symbol)
        logger.info(
            f"Fetched {len(all_candles)} {timeframe} candles for {pair_name} "
            f"from {start.date()} to {end.date()}"
        )
        return all_candles

    def get_current_price(self, symbol: str) -> Decimal:
        """Get current market price."""
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            raise ValueError(f"No current price data for {symbol}")
        last_close = data["Close"].iloc[-1]
        return Decimal(str(round(last_close, 6)))
