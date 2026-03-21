"""Core data models for the trading system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Literal


# ---------------------------------------------------------------------------
# Candle
# ---------------------------------------------------------------------------
@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: Literal["1m", "15m", "daily"] = "1m"
    bar_index: int = 0

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low

    @property
    def body_pct(self) -> float:
        if self.range_size == 0:
            return 0.0
        return self.body_size / self.range_size

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


# ---------------------------------------------------------------------------
# Swing Points & Trend
# ---------------------------------------------------------------------------
class SwingClassification(str, Enum):
    HH = "HH"  # Higher High
    HL = "HL"  # Higher Low
    LH = "LH"  # Lower High
    LL = "LL"  # Lower Low
    INITIAL = "INITIAL"  # First swing, no prior reference


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    CONSOLIDATION = "consolidation"
    UNKNOWN = "unknown"


@dataclass
class SwingPoint:
    timestamp: datetime
    price: float
    swing_type: Literal["high", "low"]
    classification: SwingClassification
    timeframe: Literal["1m", "15m"]
    confirmed: bool = False
    bar_index: int = 0


@dataclass
class TrendState:
    direction: TrendDirection
    swing_sequence: list[SwingPoint] = field(default_factory=list)
    last_updated: datetime | None = None

    @property
    def swing_count(self) -> int:
        return len(self.swing_sequence)


# ---------------------------------------------------------------------------
# Market Structure Shift
# ---------------------------------------------------------------------------
@dataclass
class MarketStructureShift:
    direction: Literal["bullish", "bearish"]
    trigger_swing: SwingPoint
    confirmation_swing: SwingPoint
    invalidation_price: float
    timestamp: datetime
    confidence: Literal["high", "medium"] = "medium"
    invalidated: bool = False


# ---------------------------------------------------------------------------
# Support / Resistance Zones
# ---------------------------------------------------------------------------
class ZoneStrength(str, Enum):
    S = "S"  # S-tier — highest confluence
    A = "A"  # A-tier — strong
    B = "B"  # B-tier — moderate


class ZoneStatus(str, Enum):
    ACTIVE = "active"
    TESTED = "tested"
    HELD = "held"
    BROKEN = "broken"


@dataclass
class SRZone:
    zone_id: str
    zone_type: Literal["support", "resistance"]
    price_low: float
    price_high: float
    strength: ZoneStrength
    source: list[str] = field(default_factory=list)
    reaction_count: int = 0
    last_reaction: datetime | None = None
    status: ZoneStatus = ZoneStatus.ACTIVE
    created_at: datetime | None = None
    timeframe: Literal["15m", "daily"] = "15m"

    @property
    def midpoint(self) -> float:
        return (self.price_low + self.price_high) / 2.0

    @property
    def width(self) -> float:
        return self.price_high - self.price_low


@dataclass
class ZoneMap:
    session_date: date
    zones: list[SRZone] = field(default_factory=list)
    last_updated: datetime | None = None

    def nearest_support(self, price: float) -> SRZone | None:
        supports = [
            z for z in self.zones
            if z.zone_type == "support"
            and z.status in (ZoneStatus.ACTIVE, ZoneStatus.TESTED, ZoneStatus.HELD)
            and z.price_high <= price
        ]
        if not supports:
            return None
        return max(supports, key=lambda z: z.midpoint)

    def nearest_resistance(self, price: float) -> SRZone | None:
        resistances = [
            z for z in self.zones
            if z.zone_type == "resistance"
            and z.status in (ZoneStatus.ACTIVE, ZoneStatus.TESTED, ZoneStatus.HELD)
            and z.price_low >= price
        ]
        if not resistances:
            return None
        return min(resistances, key=lambda z: z.midpoint)


# ---------------------------------------------------------------------------
# Entry Signal Scanner
# ---------------------------------------------------------------------------
class SetupState(str, Enum):
    IDLE = "idle"
    IMPULSE_DETECTED = "impulse_detected"
    MSS_AT_ZONE = "mss_at_zone"
    CONFIRMATION = "confirmation"
    TRIGGER_ACTIVE = "trigger_active"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    DISCARDED = "discarded"


@dataclass
class TradeSignal:
    signal_id: str
    direction: Literal["long", "short"]
    entry_price: float
    stop_loss: float
    target_price: float
    risk_points: float
    reward_points: float
    risk_reward_ratio: float
    confirmation_candle_ts: datetime | None = None
    trigger_expiry: datetime | None = None
    sr_zone_id: str = ""
    mss_direction: str = ""
    setup_quality: Literal["A+", "A", "B"] = "B"


@dataclass
class SetupLog:
    session_date: date
    setup_number: int
    steps_completed: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    signal: TradeSignal | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Position / Risk Management
# ---------------------------------------------------------------------------
class TrailPhase(str, Enum):
    NONE = "none"
    STRUCTURAL = "structural"
    AGGRESSIVE = "aggressive"
    TARGET_ZONE = "target_zone"


class PositionStatus(str, Enum):
    ACTIVE = "active"
    BREAK_EVEN = "break_even"
    TRAILING = "trailing"
    CLOSED = "closed"


class ExitReason(str, Enum):
    STOP_LOSS = "stop_loss"
    BREAK_EVEN_STOP = "break_even_stop"
    TRAILING_STOP = "trailing_stop"
    TARGET_REACHED = "target_reached"
    ZONE_STALL = "zone_stall"
    SESSION_CLOSE = "session_close"
    EMERGENCY = "emergency"


@dataclass
class StopAdjustment:
    old_price: float
    new_price: float
    reason: str
    timestamp: datetime


@dataclass
class Position:
    position_id: str
    direction: Literal["long", "short"]
    entry_price: float
    entry_time: datetime
    contracts: int
    initial_stop: float
    current_stop: float
    target_price: float
    initial_risk_points: float
    status: PositionStatus = PositionStatus.ACTIVE
    trail_phase: TrailPhase = TrailPhase.NONE
    stop_history: list[StopAdjustment] = field(default_factory=list)

    @property
    def current_risk_points(self) -> float:
        if self.direction == "long":
            return self.entry_price - self.current_stop
        return self.current_stop - self.entry_price

    def unrealized_pnl(self, current_price: float) -> float:
        if self.direction == "long":
            return current_price - self.entry_price
        return self.entry_price - current_price

    def unrealized_r(self, current_price: float) -> float:
        if self.initial_risk_points == 0:
            return 0.0
        return self.unrealized_pnl(current_price) / self.initial_risk_points


@dataclass
class TradeResult:
    position_id: str
    direction: Literal["long", "short"]
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    contracts: int
    pnl_points: float
    pnl_dollars: float
    r_multiple: float
    exit_reason: ExitReason
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    stop_adjustments: int = 0


# ---------------------------------------------------------------------------
# Session Controller
# ---------------------------------------------------------------------------
class SessionState(str, Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    ACTIVE = "active"
    WINDING_DOWN = "winding_down"
    POSITION_ONLY = "position_only"
    CLOSED = "closed"
    ERROR = "error"


@dataclass
class SessionConfig:
    trading_start: time = field(default_factory=lambda: time(9, 30))
    new_setup_cutoff: time = field(default_factory=lambda: time(11, 0))
    trading_end: time = field(default_factory=lambda: time(11, 30))
    force_close_deadline: time = field(default_factory=lambda: time(13, 0))
    max_entries_per_day: int = 3
    max_attempts_per_day: int = 2
    max_consecutive_loss_days: int = 3
    timezone: str = "US/Eastern"


@dataclass
class DailyStats:
    session_date: date | None = None
    setups_detected: int = 0
    entries_triggered: int = 0
    wins: int = 0
    losses: int = 0
    break_even_exits: int = 0
    total_pnl_points: float = 0.0
    total_pnl_dollars: float = 0.0
    total_pnl_r: float = 0.0
    max_drawdown_dollars: float = 0.0
    trade_results: list[TradeResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Inter-Agent Messages
# ---------------------------------------------------------------------------
@dataclass
class AgentMessage:
    source: str
    target: str
    message_type: str
    payload: dict = field(default_factory=dict)
    timestamp: datetime | None = None
    priority: Literal["normal", "high", "critical"] = "normal"
    sequence_id: int = 0
