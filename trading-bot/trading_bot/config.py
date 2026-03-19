"""Configuration for ORB + Session Analysis forex trading bot."""

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

# ── Session Windows (NY time) ──────────────────────────────────────────────
#
# Forex sessions in New York time:
#   Asia (Tokyo):   19:00 – 04:00 NY  (previous day evening → early morning)
#   London:         03:00 – 05:00 NY  (core impulse — overlap with late Asia)
#   London Full:    02:00 – 12:00 NY
#   New York:       09:30 – 17:00 NY  (NYSE open → forex close)
#   ORB Window:     09:30 – 09:45 NY  (first 15m after NYSE open)

@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time  # NY time
    end: time    # NY time

ASIA_SESSION = SessionWindow("Asia", time(19, 0), time(4, 0))
LONDON_SESSION = SessionWindow("London", time(2, 0), time(5, 0))
NY_ORB_WINDOW = SessionWindow("ORB", time(9, 30), time(9, 45))
NY_SESSION = SessionWindow("New York", time(9, 30), time(17, 0))


# ── Forex Pair Configuration ─────────────────────────────────────────────

# Pip definitions: most pairs have pip at 4th decimal (0.0001),
# JPY pairs have pip at 2nd decimal (0.01)
PAIR_CONFIG = {
    "EURUSD=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "EUR/USD"},
    "GBPUSD=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "GBP/USD"},
    "USDJPY=X": {"pip": Decimal("0.01"),   "pip_value_per_lot": Decimal("6.67"),  "name": "USD/JPY"},
    "USDCHF=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "USD/CHF"},
    "AUDUSD=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "AUD/USD"},
    "NZDUSD=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "NZD/USD"},
    "USDCAD=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "USD/CAD"},
    "EURGBP=X": {"pip": Decimal("0.0001"), "pip_value_per_lot": Decimal("10.00"), "name": "EUR/GBP"},
    "EURJPY=X": {"pip": Decimal("0.01"),   "pip_value_per_lot": Decimal("6.67"),  "name": "EUR/JPY"},
    "GBPJPY=X": {"pip": Decimal("0.01"),   "pip_value_per_lot": Decimal("6.67"),  "name": "GBP/JPY"},
}

DEFAULT_PAIR = "EURUSD=X"


def get_pip_size(symbol: str) -> Decimal:
    """Get pip size for a forex pair."""
    cfg = PAIR_CONFIG.get(symbol)
    if cfg:
        return cfg["pip"]
    # Default: assume standard 4-decimal pair
    return Decimal("0.0001")


def get_pip_value(symbol: str) -> Decimal:
    """Get pip value per standard lot (100,000 units) in USD."""
    cfg = PAIR_CONFIG.get(symbol)
    if cfg:
        return cfg["pip_value_per_lot"]
    return Decimal("10.00")


def get_pair_name(symbol: str) -> str:
    """Get human-readable pair name."""
    cfg = PAIR_CONFIG.get(symbol)
    if cfg:
        return cfg["name"]
    return symbol.replace("=X", "")


# ── Strategy Parameters ───────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    symbol: str = DEFAULT_PAIR
    orb_timeframe: str = "15m"       # ORB range timeframe
    entry_timeframe: str = "5m"      # Entry signal timeframe
    min_displacement_candles: int = 3 # Minimum consecutive candles for displacement
    max_displacement_candles: int = 5
    displacement_body_ratio: float = 0.50  # Min body/range ratio for "strong" candle
    engulfing_required: bool = True   # Primary trigger
    zone_hold_fallback: bool = True   # Backup trigger
    zone_hold_lookback: int = 3       # Candles to check for zone hold


# ── Risk Management Parameters ────────────────────────────────────────────

@dataclass
class RiskConfig:
    initial_balance: Decimal = Decimal("200.00")  # USD
    risk_per_trade_pct: Decimal = Decimal("0.01")     # 1% per trade
    max_risk_per_trade_pct: Decimal = Decimal("0.02")  # 2% hard cap
    min_risk_reward: Decimal = Decimal("1.5")
    max_risk_reward: Decimal = Decimal("2.2")
    default_risk_reward: Decimal = Decimal("2.0")
    sl_buffer_pips: Decimal = Decimal("2")             # 2 pips buffer for SL
    max_daily_loss_pct: Decimal = Decimal("0.05")      # 5% daily loss kill switch
    max_consecutive_losses: int = 5
    max_drawdown_pct: Decimal = Decimal("0.15")        # 15% max drawdown
    max_open_positions: int = 1                         # One trade at a time
    # Forex lot sizing: with $200 we use micro lots (0.01 lot = 1000 units)
    min_lot_size: Decimal = Decimal("0.01")            # Micro lot
    max_lot_size: Decimal = Decimal("0.10")            # Max for small account


# ── Bot Configuration ─────────────────────────────────────────────────────

@dataclass
class BotConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    log_level: str = "INFO"
    poll_interval_seconds: int = 30  # How often to check for new candles in live mode
