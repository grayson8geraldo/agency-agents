"""Configuration for ORB + Session Analysis trading bot."""

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

# ── Session Windows (NY time) ──────────────────────────────────────────────

@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time  # NY time
    end: time    # NY time

# Asia: previous day 19:00 → 00:00 NY
# London: 02:00 → 05:00 NY (core impulse window)
# NY ORB: 09:30 → 09:45 NY
# NY Trading: 09:30 → 16:00 NY
ASIA_SESSION = SessionWindow("Asia", time(19, 0), time(0, 0))
LONDON_SESSION = SessionWindow("London", time(2, 0), time(5, 0))
NY_ORB_WINDOW = SessionWindow("ORB", time(9, 30), time(9, 45))
NY_SESSION = SessionWindow("New York", time(9, 30), time(16, 0))


# ── Strategy Parameters ───────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    symbol: str = "BTC/USDT"
    orb_timeframe: str = "15m"       # ORB range timeframe
    entry_timeframe: str = "5m"      # Entry signal timeframe
    min_displacement_candles: int = 3 # Minimum consecutive candles for displacement
    max_displacement_candles: int = 5 # Maximum to look for
    displacement_body_ratio: float = 0.55  # Min body/range ratio for "strong" candle
    engulfing_required: bool = True   # Primary trigger
    zone_hold_fallback: bool = True   # Backup trigger
    zone_hold_lookback: int = 3       # Candles to check for zone hold


# ── Risk Management Parameters ────────────────────────────────────────────

@dataclass
class RiskConfig:
    initial_balance: Decimal = Decimal("200.00")
    risk_per_trade_pct: Decimal = Decimal("0.01")     # 1% per trade
    max_risk_per_trade_pct: Decimal = Decimal("0.02")  # 2% hard cap
    min_risk_reward: Decimal = Decimal("1.5")
    max_risk_reward: Decimal = Decimal("2.2")
    default_risk_reward: Decimal = Decimal("2.0")
    sl_buffer_pct: Decimal = Decimal("0.0005")         # 0.05% buffer
    max_daily_loss_pct: Decimal = Decimal("0.05")      # 5% daily loss kill switch
    max_consecutive_losses: int = 5
    max_drawdown_pct: Decimal = Decimal("0.15")        # 15% max drawdown
    max_open_positions: int = 1                         # One trade at a time


# ── Bot Configuration ─────────────────────────────────────────────────────

@dataclass
class BotConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    exchange_id: str = "binance"
    log_level: str = "INFO"
    poll_interval_seconds: int = 10  # How often to check for new candles in live mode
