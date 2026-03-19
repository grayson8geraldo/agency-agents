"""Data models for the trading bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class Bias(Enum):
    LONG = "long"
    SHORT = "short"
    CONTINUATION = "continuation"
    NO_TRADE = "no_trade"


class ZoneType(Enum):
    ORDER_BLOCK = "order_block"
    FVG = "fvg"


class TriggerType(Enum):
    ENGULFING = "engulfing"
    ZONE_HOLD = "zone_hold"


class TradeStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED_TP = "closed_tp"
    CLOSED_SL = "closed_sl"
    CLOSED_MANUAL = "closed_manual"
    CANCELLED = "cancelled"


# ── Candle ─────────────────────────────────────────────────────────────────

@dataclass
class Candle:
    timestamp: datetime  # UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def body_high(self) -> Decimal:
        return max(self.open, self.close)

    @property
    def body_low(self) -> Decimal:
        return min(self.open, self.close)

    @property
    def body_size(self) -> Decimal:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> Decimal:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_ratio(self) -> Decimal:
        if self.range_size == 0:
            return Decimal("0")
        return self.body_size / self.range_size


# ── Session Analysis ───────────────────────────────────────────────────────

@dataclass
class SessionData:
    name: str
    high: Decimal
    low: Decimal
    open_price: Decimal
    close_price: Decimal
    candles: list[Candle] = field(default_factory=list)


@dataclass
class SessionAnalysis:
    asia: SessionData
    london: SessionData
    london_swept_asia_low: bool
    london_swept_asia_high: bool
    bias: Bias


# ── ORB ────────────────────────────────────────────────────────────────────

@dataclass
class ORBRange:
    high: Decimal
    low: Decimal
    timestamp: datetime
    is_valid: bool = True


# ── Zone ───────────────────────────────────────────────────────────────────

@dataclass
class Zone:
    zone_type: ZoneType
    high: Decimal
    low: Decimal
    direction: str  # "bullish" or "bearish"

    @property
    def midpoint(self) -> Decimal:
        return (self.high + self.low) / 2


# ── Displacement ──────────────────────────────────────────────────────────

@dataclass
class Displacement:
    direction: str  # "bullish" or "bearish"
    candles: list[Candle]
    broke_orb: bool
    zone: Optional[Zone] = None


# ── Trade Signal ──────────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    direction: Bias  # LONG or SHORT
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    zone: Zone
    trigger_type: TriggerType
    timestamp: datetime
    risk_reward: Decimal = Decimal("0")

    def __post_init__(self):
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        if risk > 0:
            self.risk_reward = reward / risk


# ── Trade ──────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    id: int
    signal: TradeSignal
    position_size: Decimal
    risk_amount: Decimal
    status: TradeStatus = TradeStatus.OPEN
    entry_price: Decimal = Decimal("0")
    exit_price: Optional[Decimal] = None
    pnl: Decimal = Decimal("0")
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    def close(self, exit_price: Decimal, timestamp: datetime, reason: TradeStatus):
        self.exit_price = exit_price
        self.closed_at = timestamp
        self.status = reason
        if self.signal.direction == Bias.LONG:
            self.pnl = (exit_price - self.entry_price) * self.position_size
        else:
            self.pnl = (self.entry_price - exit_price) * self.position_size
