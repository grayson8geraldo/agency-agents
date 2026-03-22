"""Live Data Feed — real-time 1m candles via yfinance or Polygon.io."""

from __future__ import annotations

import logging
import os
import time as _time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from .models import Candle

logger = logging.getLogger(__name__)

EST = ZoneInfo("US/Eastern")


class BaseLiveFeed(ABC):
    """Abstract base for live data feeds."""

    def __init__(self, asset: str = "MES", poll_interval: int = 60) -> None:
        self.asset = asset
        self.poll_interval = poll_interval
        self._bar_index_1m = 0
        self._bar_index_15m = 0
        self._last_candle_ts: datetime | None = None

    @abstractmethod
    def fetch_historical_1m(self, days: int = 1) -> list[Candle]:
        ...

    @abstractmethod
    def fetch_latest_candles(self) -> list[Candle]:
        ...

    @abstractmethod
    def get_current_price(self) -> float | None:
        ...

    def aggregate_to_15m(self, candles_1m: list[Candle]) -> list[Candle]:
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
        """ES/MES RTH: 9:30 AM — 4:00 PM Eastern, Mon—Fri."""
        now = datetime.now(EST)
        if now.weekday() >= 5:
            return False
        t = now.time()
        return time(9, 30) <= t < time(16, 0)

    def wait_for_market_open(self) -> None:
        while not self.is_market_open():
            now = datetime.now(EST)
            logger.info("Market closed. Current time: %s EST. Waiting...", now.strftime("%H:%M:%S"))
            _time.sleep(60)

    def _next_bar_index(self, timeframe: str) -> int:
        if timeframe == "1m":
            idx = self._bar_index_1m
            self._bar_index_1m += 1
            return idx
        idx = self._bar_index_15m
        self._bar_index_15m += 1
        return idx


# ======================================================================
# Polygon.io Feed
# ======================================================================

# Polygon ticker format for futures
POLYGON_TICKER_MAP = {
    "ES": "C:ESZ2025",   # E-mini S&P 500 — active front-month contract
    "MES": "C:MESZ2025", # Micro E-mini S&P 500
    "NQ": "C:NQZ2025",   # E-mini Nasdaq
    "MNQ": "C:MNQZ2025", # Micro Nasdaq
}


def _get_polygon_futures_ticker(asset: str) -> str:
    """Get the active front-month Polygon ticker for the given asset.

    Polygon futures tickers follow: C:{symbol}{month_code}{year}
    Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun,
                 N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
    CME ES/MES quarterly contracts: H (Mar), M (Jun), U (Sep), Z (Dec)
    """
    now = datetime.now()
    year = now.year
    month = now.month

    # Quarterly expiry months and codes for ES/MES
    quarterly = [(3, "H"), (6, "M"), (9, "U"), (12, "Z")]

    # Find the next expiry
    for exp_month, code in quarterly:
        if month <= exp_month:
            return f"C:{asset}{code}{year}"

    # Rolled to next year Q1
    return f"C:{asset}H{year + 1}"


class PolygonFeed(BaseLiveFeed):
    """Fetches 1-minute candles from Polygon.io REST API.

    Polygon.io free tier: 5 API calls/min, delayed data.
    Needs POLYGON_API_KEY environment variable or passed in config.
    """

    def __init__(
        self,
        asset: str = "MES",
        poll_interval: int = 60,
        api_key: str | None = None,
    ) -> None:
        super().__init__(asset, poll_interval)

        self.api_key = api_key or os.environ.get("POLYGON_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Polygon.io API key required. Set POLYGON_API_KEY env var "
                "or polygon.api_key in config.yaml"
            )

        from polygon import RESTClient
        self._client = RESTClient(api_key=self.api_key)

        self.ticker = _get_polygon_futures_ticker(asset)

        logger.info(
            "POLYGON FEED — Asset: %s → Ticker: %s | Poll: %ds | API key: ...%s",
            asset,
            self.ticker,
            poll_interval,
            self.api_key[-4:] if len(self.api_key) >= 4 else "****",
        )

    def fetch_historical_1m(self, days: int = 2) -> list[Candle]:
        """Fetch historical 1m bars from Polygon.io."""
        now = datetime.now(EST)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")

        logger.info("Polygon: fetching 1m bars for %s from %s to %s...", self.ticker, start, end)

        candles: list[Candle] = []
        try:
            bars = self._client.get_aggs(
                ticker=self.ticker,
                multiplier=1,
                timespan="minute",
                from_=start,
                to=end,
                limit=50000,
            )

            if not bars:
                # Fallback: try with SPY if futures ticker doesn't work
                logger.warning("No data for %s, trying SPY as fallback...", self.ticker)
                self.ticker = "SPY"
                bars = self._client.get_aggs(
                    ticker="SPY",
                    multiplier=1,
                    timespan="minute",
                    from_=start,
                    to=end,
                    limit=50000,
                )

            if bars:
                for bar in bars:
                    ts = datetime.fromtimestamp(bar.timestamp / 1000, tz=EST)
                    candle = Candle(
                        timestamp=ts,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=float(bar.volume or 0),
                        timeframe="1m",
                        bar_index=self._next_bar_index("1m"),
                    )
                    candles.append(candle)
                logger.info("Polygon: loaded %d historical 1m candles", len(candles))
            else:
                logger.warning("Polygon: no bars returned")

        except Exception as e:
            logger.error("Polygon API error: %s", e)

        return candles

    def fetch_latest_candles(self) -> list[Candle]:
        """Fetch the most recent 1m candles since last poll."""
        now = datetime.now(EST)
        # Fetch last 2 hours to be safe
        start = (now - timedelta(hours=2)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")

        new_candles: list[Candle] = []
        try:
            bars = self._client.get_aggs(
                ticker=self.ticker,
                multiplier=1,
                timespan="minute",
                from_=start,
                to=end,
                limit=5000,
            )

            if bars:
                for bar in bars:
                    ts = datetime.fromtimestamp(bar.timestamp / 1000, tz=EST)

                    # Skip already processed candles
                    if self._last_candle_ts and ts <= self._last_candle_ts:
                        continue

                    candle = Candle(
                        timestamp=ts,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=float(bar.volume or 0),
                        timeframe="1m",
                        bar_index=self._next_bar_index("1m"),
                    )
                    new_candles.append(candle)

            if new_candles:
                self._last_candle_ts = new_candles[-1].timestamp
                logger.debug(
                    "Polygon: %d new 1m candles, latest: %s",
                    len(new_candles),
                    self._last_candle_ts,
                )

        except Exception as e:
            logger.error("Polygon fetch error: %s", e)

        return new_candles

    def get_current_price(self) -> float | None:
        """Get latest price via Polygon snapshot or last bar."""
        try:
            # Try last close from recent bars
            now = datetime.now(EST)
            bars = self._client.get_aggs(
                ticker=self.ticker,
                multiplier=1,
                timespan="minute",
                from_=(now - timedelta(hours=1)).strftime("%Y-%m-%d"),
                to=now.strftime("%Y-%m-%d"),
                limit=5,
                sort="desc",
            )
            if bars:
                return float(bars[0].close)
        except Exception as e:
            logger.error("Polygon price fetch error: %s", e)
        return None


# ======================================================================
# Yahoo Finance Feed (fallback)
# ======================================================================

YFINANCE_TICKER_MAP = {
    "ES": "ES=F",
    "MES": "ES=F",
    "NQ": "NQ=F",
    "MNQ": "NQ=F",
    "YM": "YM=F",
    "MYM": "YM=F",
    "RTY": "RTY=F",
}


class YFinanceFeed(BaseLiveFeed):
    """Fetches 1-minute candles from Yahoo Finance (free, ~15min delay)."""

    def __init__(self, asset: str = "MES", poll_interval: int = 60) -> None:
        super().__init__(asset, poll_interval)
        import yfinance as yf

        self.ticker_symbol = YFINANCE_TICKER_MAP.get(asset, "ES=F")
        self._ticker = yf.Ticker(self.ticker_symbol)

        logger.info(
            "YFINANCE FEED — Asset: %s → Ticker: %s | Poll: %ds",
            asset,
            self.ticker_symbol,
            poll_interval,
        )

    def fetch_historical_1m(self, days: int = 1) -> list[Candle]:
        logger.info("Fetching %d day(s) of 1m data for %s...", days, self.ticker_symbol)
        df = self._ticker.history(period=f"{days}d", interval="1m")
        if df.empty:
            logger.warning("No historical data for %s", self.ticker_symbol)
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
        df = self._ticker.history(period="1d", interval="1m")
        if df.empty:
            return []

        new_candles: list[Candle] = []
        for ts, row in df.iterrows():
            candle_ts = ts.to_pydatetime().astimezone(EST)
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
            logger.debug("yfinance: %d new 1m candles, latest: %s", len(new_candles), self._last_candle_ts)

        return new_candles

    def get_current_price(self) -> float | None:
        try:
            info = self._ticker.fast_info
            return float(info.get("lastPrice", 0)) or None
        except Exception:
            df = self._ticker.history(period="1d", interval="1m")
            if not df.empty:
                return float(df["Close"].iloc[-1])
            return None


# ======================================================================
# Factory
# ======================================================================

# Keep backward compatibility
LiveFeed = YFinanceFeed


def create_live_feed(
    provider: str = "polygon",
    asset: str = "MES",
    poll_interval: int = 60,
    api_key: str | None = None,
) -> BaseLiveFeed:
    """Create a live feed instance based on provider name.

    Args:
        provider: "polygon" or "yfinance"
        asset: Trading asset (e.g., "MES", "ES")
        poll_interval: Seconds between data polls
        api_key: API key (required for polygon)
    """
    if provider == "polygon":
        return PolygonFeed(asset=asset, poll_interval=poll_interval, api_key=api_key)
    elif provider == "yfinance":
        return YFinanceFeed(asset=asset, poll_interval=poll_interval)
    else:
        raise ValueError(f"Unknown data provider: {provider}. Use 'polygon' or 'yfinance'.")
