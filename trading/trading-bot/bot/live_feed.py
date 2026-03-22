"""Live Data Feed — real-time 1m candles via yfinance for ES/MES futures."""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import yfinance as yf

from .models import Candle

logger = logging.getLogger(__name__)

EST = ZoneInfo("US/Eastern")

# yfinance ticker symbols for futures
TICKER_MAP = {
    "ES": "ES=F",   # E-mini S&P 500 futures
    "MES": "ES=F",  # Micro E-mini (same price, smaller contract) — yfinance has ES=F only
    "NQ": "NQ=F",   # E-mini Nasdaq 100
    "MNQ": "NQ=F",  # Micro Nasdaq
    "YM": "YM=F",   # E-mini Dow
    "MYM": "YM=F",  # Micro Dow
    "RTY": "RTY=F", # E-mini Russell 2000
}


class LiveFeed:
    """Fetches real-time 1-minute candles from Yahoo Finance.

    Yahoo Finance provides ~15-min delayed data for futures.
    For paper trading this is sufficient — same price action, slight delay.
    """

    def __init__(self, asset: str = "MES", poll_interval: int = 60) -> None:
        self.asset = asset
        self.ticker_symbol = TICKER_MAP.get(asset, "ES=F")
        self.poll_interval = poll_interval  # seconds between polls
        self._ticker = yf.Ticker(self.ticker_symbol)
        self._bar_index_1m = 0
        self._bar_index_15m = 0
        self._last_candle_ts: datetime | None = None
        self._1m_bucket: list[Candle] = []

        logger.info(
            "LIVE FEED — Asset: %s → Ticker: %s | Poll: %ds",
            asset,
            self.ticker_symbol,
            poll_interval,
        )

    def fetch_historical_1m(self, days: int = 1) -> list[Candle]:
        """Fetch recent 1m candles for warm-up (structure/zone building).

        yfinance allows up to 7 days of 1m data.
        """
        logger.info("Fetching %d day(s) of 1m historical data for %s...", days, self.ticker_symbol)
        df = self._ticker.history(period=f"{days}d", interval="1m")

        if df.empty:
            logger.warning("No historical data returned for %s", self.ticker_symbol)
            return []

        candles: list[Candle] = []
        for ts, row in df.iterrows():
            candle = Candle(
                timestamp=ts.to_pydatetime().astimezone(EST),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0)),
                timeframe="1m",
                bar_index=self._next_bar_index("1m"),
            )
            candles.append(candle)

        logger.info("Loaded %d historical 1m candles", len(candles))
        return candles

    def fetch_latest_candles(self) -> list[Candle]:
        """Fetch the most recent 1m candles since last poll.

        Returns only NEW candles not seen before.
        """
        # Fetch last 1 day of 1m data — we'll filter to only new candles
        df = self._ticker.history(period="1d", interval="1m")

        if df.empty:
            return []

        new_candles: list[Candle] = []
        for ts, row in df.iterrows():
            candle_ts = ts.to_pydatetime().astimezone(EST)

            # Skip candles we've already processed
            if self._last_candle_ts and candle_ts <= self._last_candle_ts:
                continue

            candle = Candle(
                timestamp=candle_ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0)),
                timeframe="1m",
                bar_index=self._next_bar_index("1m"),
            )
            new_candles.append(candle)

        if new_candles:
            self._last_candle_ts = new_candles[-1].timestamp
            logger.debug("Fetched %d new 1m candles, latest: %s", len(new_candles), self._last_candle_ts)

        return new_candles

    def get_current_price(self) -> float | None:
        """Get the latest price for the asset."""
        try:
            info = self._ticker.fast_info
            return float(info.get("lastPrice", 0)) or None
        except Exception:
            # Fallback: fetch latest 1m candle
            df = self._ticker.history(period="1d", interval="1m")
            if not df.empty:
                return float(df["Close"].iloc[-1])
            return None

    def aggregate_to_15m(self, candles_1m: list[Candle]) -> list[Candle]:
        """Aggregate 1m candles into 15m candles."""
        if not candles_1m:
            return []

        result: list[Candle] = []
        bucket: list[Candle] = []

        for candle in candles_1m:
            minute = candle.timestamp.minute
            if minute % 15 == 0 and bucket:
                result.append(self._merge_bucket(bucket, "15m"))
                bucket = []
            bucket.append(candle)

        if bucket:
            result.append(self._merge_bucket(bucket, "15m"))

        return result

    def _merge_bucket(self, bucket: list[Candle], timeframe: str) -> Candle:
        return Candle(
            timestamp=bucket[0].timestamp,
            open=bucket[0].open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=bucket[-1].close,
            volume=sum(c.volume for c in bucket),
            timeframe=timeframe,
            bar_index=self._next_bar_index(timeframe),
        )

    def is_market_open(self) -> bool:
        """Check if futures market is currently in regular trading hours (RTH).

        ES/MES RTH: 9:30 AM — 4:00 PM Eastern, Mon—Fri.
        """
        now = datetime.now(EST)
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        t = now.time()
        return time(9, 30) <= t < time(16, 0)

    def wait_for_market_open(self) -> None:
        """Block until market opens (RTH)."""
        while not self.is_market_open():
            now = datetime.now(EST)
            logger.info(
                "Market closed. Current time: %s EST. Waiting...",
                now.strftime("%H:%M:%S"),
            )
            _time.sleep(60)

    def _next_bar_index(self, timeframe: str) -> int:
        if timeframe == "1m":
            idx = self._bar_index_1m
            self._bar_index_1m += 1
            return idx
        idx = self._bar_index_15m
        self._bar_index_15m += 1
        return idx
