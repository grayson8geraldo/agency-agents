"""Data models for the MTFA trading bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────


class Bias(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SwingType(Enum):
    HIGH = "SWING_HIGH"
    LOW = "SWING_LOW"


class OBType(Enum):
    DEMAND = "DEMAND"
    SUPPLY = "SUPPLY"


class ZoneName(Enum):
    EXTREME_DISCOUNT = "EXTREME_DISCOUNT"
    DISCOUNT = "DISCOUNT"
    CHOP = "CHOP"
    PREMIUM = "PREMIUM"
    EXTREME_PREMIUM = "EXTREME_PREMIUM"


class TradingState(Enum):
    SCANNING = "SCANNING"
    MAPPING = "MAPPING"
    WAITING = "WAITING"
    CONFIRMING = "CONFIRMING"
    IN_TRADE = "IN_TRADE"
    COOLDOWN = "COOLDOWN"
    HALTED = "HALTED"


class PositionStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_SL = "CLOSED_SL"
    CANCELLED = "CANCELLED"


class RejectionPattern(Enum):
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"
    BULLISH_PIN_BAR = "BULLISH_PIN_BAR"
    BEARISH_PIN_BAR = "BEARISH_PIN_BAR"
    BULLISH_DISPLACEMENT = "BULLISH_DISPLACEMENT"
    BEARISH_DISPLACEMENT = "BEARISH_DISPLACEMENT"


# ── Core Data Structures ──────────────────────────────────────


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)


@dataclass
class SwingPoint:
    type: SwingType
    price: float
    timestamp: datetime
    index: int


@dataclass
class SwingRange:
    low: float
    high: float
    bias: Bias

    @property
    def size(self) -> float:
        return self.high - self.low

    @property
    def equilibrium(self) -> float:
        return self.low + self.size * 0.5

    def price_position(self, price: float) -> float:
        """Return 0.0–1.0 representing where price sits in the range."""
        if self.size == 0:
            return 0.5
        return (price - self.low) / self.size


@dataclass
class BOSEvent:
    bias: Bias
    broken_level: float
    timestamp: datetime


@dataclass
class OrderBlock:
    type: OBType
    low: float
    high: float
    timestamp: datetime
    candle_index: int
    mitigated: bool = False
    mitigation_count: int = 0
    priority: str = "PROXIMAL"  # EXTREME or PROXIMAL
    confluences: list[str] = field(default_factory=list)

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


@dataclass
class LiquidityPool:
    type: str  # EQUAL_HIGHS, EQUAL_LOWS, PDH, PDL
    level: float
    count: int = 1


@dataclass
class FairValueGap:
    low: float
    high: float
    direction: Bias
    timestamp: datetime

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


# ── Agent Outputs ─────────────────────────────────────────────


@dataclass
class HTFAnalysis:
    bias: Bias
    swing_range: SwingRange
    last_bos: BOSEvent
    swing_points: list[SwingPoint]
    structure_valid: bool


@dataclass
class PremiumDiscountZones:
    extreme_discount: tuple[float, float]
    discount: tuple[float, float]
    chop_zone: tuple[float, float]
    premium: tuple[float, float]
    extreme_premium: tuple[float, float]
    equilibrium: float


@dataclass
class MTFAnalysis:
    zones: PremiumDiscountZones
    active_pois: list[OrderBlock]
    liquidity_pools: list[LiquidityPool]
    current_price_zone: ZoneName
    trade_permission: Bias | None


@dataclass
class SweepEvent:
    direction: Bias
    sweep_extreme: float
    level_swept: float
    candle: Candle


@dataclass
class MSSEvent:
    direction: Bias
    broken_level: float
    confirmation_close: float
    candle: Candle


@dataclass
class RejectionEvent:
    pattern: RejectionPattern
    candle: Candle
    fvg: FairValueGap | None = None


@dataclass
class EntrySignal:
    direction: Bias
    entry_price: float
    stop_loss: float
    sweep: SweepEvent
    mss: MSSEvent
    rejection: RejectionEvent
    poi: OrderBlock


@dataclass
class Position:
    direction: Bias
    entry_price: float
    stop_loss: float
    take_profit: float
    size: float
    risk_amount: float
    rr_ratio: float
    tp_mode: str
    status: PositionStatus = PositionStatus.PENDING
    fill_price: float | None = None
    exit_price: float | None = None
    pnl: float = 0.0
    opened_at: datetime | None = None
    closed_at: datetime | None = None


@dataclass
class TradeJournalEntry:
    trade_id: str
    symbol: str
    direction: Bias
    htf_bias: Bias
    swing_range: SwingRange
    poi: OrderBlock
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    outcome: PositionStatus
    pnl: float
    rr_achieved: float
    opened_at: datetime
    closed_at: datetime
