"""Session detection — Asia, London, New York with liquidity sweep analysis."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal

from .config import NY_TZ, UTC_TZ, ASIA_SESSION, LONDON_SESSION
from .models import Bias, Candle, SessionAnalysis, SessionData

logger = logging.getLogger(__name__)


def _to_ny(dt: datetime) -> datetime:
    """Convert any datetime to NY timezone."""
    return dt.astimezone(NY_TZ)


def _ny_time(dt: datetime) -> time:
    """Get NY-local time from a datetime."""
    return _to_ny(dt).time()


def _is_in_asia(candle: Candle, trade_date: datetime) -> bool:
    """
    Asia session: previous day 19:00 → current day 00:00 NY.
    This captures the Asian trading session as seen from NY time.
    """
    ny_dt = _to_ny(candle.timestamp)
    ny_t = ny_dt.time()
    ny_date = ny_dt.date()
    trade_ny_date = _to_ny(trade_date).date()

    # Previous day 19:00-23:59
    prev_date = trade_ny_date - timedelta(days=1)
    if ny_date == prev_date and ny_t >= time(19, 0):
        return True
    # Current day 00:00-01:59 (tail of Asia)
    if ny_date == trade_ny_date and ny_t < time(2, 0):
        return True
    return False


def _is_in_london(candle: Candle, trade_date: datetime) -> bool:
    """London session: 02:00 → 05:00 NY (core impulse window)."""
    ny_dt = _to_ny(candle.timestamp)
    ny_t = ny_dt.time()
    ny_date = ny_dt.date()
    trade_ny_date = _to_ny(trade_date).date()

    if ny_date != trade_ny_date:
        return False
    return time(2, 0) <= ny_t < time(5, 0)


def extract_session_candles(
    candles: list[Candle],
    trade_date: datetime,
    session: str,
) -> list[Candle]:
    """Extract candles belonging to a specific session for a given trade date."""
    if session == "asia":
        return [c for c in candles if _is_in_asia(c, trade_date)]
    elif session == "london":
        return [c for c in candles if _is_in_london(c, trade_date)]
    return []


def build_session_data(name: str, candles: list[Candle]) -> SessionData:
    """Build session summary from candles."""
    if not candles:
        return SessionData(
            name=name,
            high=Decimal("0"),
            low=Decimal("999999"),
            open_price=Decimal("0"),
            close_price=Decimal("0"),
            candles=[],
        )
    return SessionData(
        name=name,
        high=max(c.high for c in candles),
        low=min(c.low for c in candles),
        open_price=candles[0].open,
        close_price=candles[-1].close,
        candles=candles,
    )


def analyze_sessions(
    candles_15m: list[Candle],
    trade_date: datetime,
) -> SessionAnalysis:
    """
    Analyze Asia and London sessions to determine NY trading bias.

    Rules:
    - London swept Asia lows only → NY bias = LONG (reversal up)
    - London swept Asia highs only → NY bias = SHORT (reversal down)
    - London swept both sides → CONTINUATION
    - London swept neither → NO_TRADE
    """
    asia_candles = extract_session_candles(candles_15m, trade_date, "asia")
    london_candles = extract_session_candles(candles_15m, trade_date, "london")

    asia = build_session_data("Asia", asia_candles)
    london = build_session_data("London", london_candles)

    if not asia_candles or not london_candles:
        logger.warning(
            f"Missing session data for {trade_date.date()}: "
            f"Asia={len(asia_candles)}, London={len(london_candles)} candles"
        )
        return SessionAnalysis(
            asia=asia,
            london=london,
            london_swept_asia_low=False,
            london_swept_asia_high=False,
            bias=Bias.NO_TRADE,
        )

    swept_low = london.low < asia.low
    swept_high = london.high > asia.high

    if swept_low and swept_high:
        bias = Bias.CONTINUATION
    elif swept_low and not swept_high:
        bias = Bias.LONG
    elif swept_high and not swept_low:
        bias = Bias.SHORT
    else:
        bias = Bias.NO_TRADE

    logger.info(
        f"Session analysis {trade_date.date()}: "
        f"Asia [{asia.low}-{asia.high}], "
        f"London swept_low={swept_low} swept_high={swept_high} → bias={bias.value}"
    )

    return SessionAnalysis(
        asia=asia,
        london=london,
        london_swept_asia_low=swept_low,
        london_swept_asia_high=swept_high,
        bias=bias,
    )
