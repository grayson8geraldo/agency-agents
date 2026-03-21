"""Data Feed abstraction — provides candle data to the trading system."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Candle

logger = logging.getLogger(__name__)


class DataFeed:
    """Abstract data feed that can be backed by CSV files or live data."""

    def __init__(self, asset: str = "MES") -> None:
        self.asset = asset
        self._bar_index_1m = 0
        self._bar_index_15m = 0

    def load_csv(
        self,
        path: str | Path,
        timeframe: str = "1m",
        date_format: str = "%Y-%m-%d %H:%M:%S",
    ) -> list[Candle]:
        """Load candle data from a CSV file.

        Expected columns: datetime, open, high, low, close, volume (optional)
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")

        candles: list[Candle] = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Support various column name conventions
                ts_str = (
                    row.get("datetime")
                    or row.get("date")
                    or row.get("timestamp")
                    or row.get("time")
                    or ""
                )
                candle = Candle(
                    timestamp=datetime.strptime(ts_str.strip(), date_format),
                    open=float(row.get("open", row.get("Open", 0))),
                    high=float(row.get("high", row.get("High", 0))),
                    low=float(row.get("low", row.get("Low", 0))),
                    close=float(row.get("close", row.get("Close", 0))),
                    volume=float(row.get("volume", row.get("Volume", 0))),
                    timeframe=timeframe,
                    bar_index=self._next_bar_index(timeframe),
                )
                candles.append(candle)

        logger.info("Loaded %d %s candles from %s", len(candles), timeframe, path)
        return candles

    def iter_candles(self, candles: list[Candle]) -> Iterator[Candle]:
        """Iterate over candles (for backtesting)."""
        yield from candles

    def aggregate_to_15m(self, candles_1m: list[Candle]) -> list[Candle]:
        """Aggregate 1-minute candles into 15-minute candles."""
        if not candles_1m:
            return []

        result: list[Candle] = []
        bucket: list[Candle] = []

        for candle in candles_1m:
            minute = candle.timestamp.minute
            # Start a new 15m bucket at 0, 15, 30, 45
            if minute % 15 == 0 and bucket:
                result.append(self._merge_bucket(bucket, "15m"))
                bucket = []
            bucket.append(candle)

        # Don't forget the last incomplete bucket
        if bucket:
            result.append(self._merge_bucket(bucket, "15m"))

        logger.info("Aggregated %d 1m candles → %d 15m candles", len(candles_1m), len(result))
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

    def _next_bar_index(self, timeframe: str) -> int:
        if timeframe == "1m":
            idx = self._bar_index_1m
            self._bar_index_1m += 1
            return idx
        idx = self._bar_index_15m
        self._bar_index_15m += 1
        return idx

    def reset(self) -> None:
        self._bar_index_1m = 0
        self._bar_index_15m = 0
