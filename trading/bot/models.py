"""Data models for the ICT trading bot pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Bias(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class PipelinePhase(Enum):
    INITIALIZED = "INITIALIZED"
    BIAS_DETERMINED = "BIAS_DETERMINED"
    SESSION_MAPPED = "SESSION_MAPPED"
    SWEEP_DETECTED = "SWEEP_DETECTED"
    M1_CONFIRMED = "M1_CONFIRMED"
    ORDER_PLACED = "ORDER_PLACED"
    POSITION_ACTIVE = "POSITION_ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class TradeResult(Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    NO_TRADE = "NO_TRADE"
    EXPIRED = "EXPIRED"


class SweepStatus(Enum):
    WAITING = "WAITING"
    MONITORING = "MONITORING"
    SWEPT = "SWEPT"
    EXPIRED = "EXPIRED"


class ConfirmationStatus(Enum):
    MONITORING = "MONITORING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


@dataclass
class SwingPoint:
    """A swing high or swing low on any timeframe."""
    price: float
    time: datetime
    type: str  # "HH", "HL", "LH", "LL", "SH" (swing high), "SL" (swing low)

    def __repr__(self) -> str:
        return f"SwingPoint({self.type} @ {self.price} at {self.time:%H:%M})"


@dataclass
class Candle:
    """OHLCV candle data."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_top(self) -> float:
        return max(self.open, self.close)

    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        return self.high - self.low


@dataclass
class BiasSignal:
    """Output from Market Structure Analyst (Step 1)."""
    bias: Bias
    choch_confirmed: bool
    choch_level: Optional[float] = None
    choch_candle_time: Optional[datetime] = None
    key_structural_high: Optional[float] = None
    key_structural_low: Optional[float] = None
    invalidation_level: Optional[float] = None
    swing_points: list[SwingPoint] = field(default_factory=list)
    confidence: str = "MEDIUM"
    notes: str = ""


@dataclass
class AsiaSession:
    """Asian session range data."""
    high: float
    low: float
    start: datetime
    end: datetime


@dataclass
class SweepSignal:
    """Output from Session Liquidity Tracker (Step 2)."""
    status: SweepStatus
    daily_bias: Bias
    asia_session: Optional[AsiaSession] = None
    sweep_side: Optional[str] = None  # "LOW" or "HIGH"
    sweep_price: Optional[float] = None
    sweep_time: Optional[datetime] = None
    depth_pips: Optional[float] = None
    notes: str = ""


@dataclass
class ConfirmationSignal:
    """Output from Microstructure Confirmer (Step 3)."""
    status: ConfirmationStatus
    daily_bias: Bias
    choch_level: Optional[float] = None
    break_candle_time: Optional[datetime] = None
    break_candle_close: Optional[float] = None
    post_sweep_extreme: Optional[float] = None
    swing_points_tracked: int = 0
    time_since_sweep_minutes: Optional[float] = None
    notes: str = ""


@dataclass
class OrderBlock:
    """An identified order block zone."""
    upper: float
    lower: float
    candle_count: int
    impulse_size: float
    timeframe: str = "M5"

    @property
    def range_size(self) -> float:
        return self.upper - self.lower


@dataclass
class OrderSignal:
    """Output from Order Block Executor (Step 4)."""
    action: str  # "PLACE_ORDER", "REJECTED_LOW_RR", "REJECTED_NO_OB"
    order_type: Optional[str] = None  # "BUY_LIMIT", "SELL_LIMIT"
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_pips: Optional[float] = None
    order_block: Optional[OrderBlock] = None
    expiry_time: Optional[datetime] = None


@dataclass
class LiquidityTarget:
    """A liquidity target for take-profit."""
    price: float
    target_type: str  # "EQUAL_HIGHS", "EQUAL_LOWS", "PDH", "PDL", "SESSION_HIGH", "SESSION_LOW", "TRENDLINE"
    description: str = ""


@dataclass
class TradeSignal:
    """Output from Liquidity Target Manager (Step 5)."""
    bias: Bias
    entry: float
    stop_loss: float
    take_profit: float
    risk_pips: float
    reward_pips: float
    rr_ratio: float
    target: Optional[LiquidityTarget] = None
    management: str = "HANDS_OFF"


@dataclass
class TradeOutcome:
    """Final trade result."""
    result: TradeResult
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pips: float = 0.0
    rr_achieved: float = 0.0
    duration_hours: float = 0.0
    notes: str = ""


@dataclass
class PipelineState:
    """Full state of one day's trading pipeline."""
    date: str
    instrument: str
    phase: PipelinePhase = PipelinePhase.INITIALIZED
    bias_signal: Optional[BiasSignal] = None
    sweep_signal: Optional[SweepSignal] = None
    confirmation_signal: Optional[ConfirmationSignal] = None
    order_signal: Optional[OrderSignal] = None
    trade_signal: Optional[TradeSignal] = None
    outcome: Optional[TradeOutcome] = None
    termination_reason: Optional[str] = None
    logs: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        timestamp = datetime.utcnow().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
