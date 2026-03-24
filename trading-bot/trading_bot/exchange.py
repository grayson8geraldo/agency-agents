"""Forex data fetcher — real market data via yfinance (free, no auth)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

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

# yfinance max lookback from today per interval
YF_MAX_LOOKBACK_DAYS = {
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

        df = None
        for attempt in range(3):
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
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"Retry {attempt + 1}/3 for {pair_name} {timeframe}: {e}")
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to fetch {pair_name} {timeframe} after 3 attempts: {e}")
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

        yfinance requires that start be within the last N days from today
        (e.g. 60 days for 5m/15m). This method clamps the start date
        accordingly and warns if the requested range is truncated.
        """
        max_lookback = YF_MAX_LOOKBACK_DAYS.get(timeframe, 60)
        now = datetime.now(UTC_TZ)
        earliest_allowed = now - timedelta(days=max_lookback - 2)  # 2-day safety margin
        pair_name = get_pair_name(symbol)

        actual_start = start
        if start < earliest_allowed:
            actual_start = earliest_allowed
            logger.warning(
                f"{pair_name} {timeframe}: clamping start from {start.date()} "
                f"to {actual_start.date()} (yfinance {max_lookback}-day limit)"
            )

        if actual_start >= end:
            logger.error(
                f"{pair_name} {timeframe}: entire range {start.date()} → {end.date()} "
                f"is beyond yfinance {max_lookback}-day limit"
            )
            return []

        # Fetch in a single request (within the allowed window)
        all_candles = self.fetch_candles(
            symbol, timeframe,
            start=actual_start, end=end,
        )

        start_utc = start.astimezone(UTC_TZ) if start.tzinfo else start.replace(tzinfo=UTC_TZ)
        end_utc = end.astimezone(UTC_TZ) if end.tzinfo else end.replace(tzinfo=UTC_TZ)

        # Filter to exact range
        filtered = [
            c for c in all_candles
            if start_utc <= c.timestamp <= end_utc
        ]

        logger.info(
            f"Fetched {len(filtered)} {timeframe} candles for {pair_name} "
            f"from {actual_start.date()} to {end.date()}"
        )
        return filtered

    def get_current_price(self, symbol: str) -> Decimal:
        """Get current market price."""
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            raise ValueError(f"No current price data for {symbol}")
        last_close = data["Close"].iloc[-1]
        return Decimal(str(round(last_close, 6)))
