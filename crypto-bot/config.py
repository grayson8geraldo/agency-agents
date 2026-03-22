"""Bot configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _float(key: str, default: float = 0.0) -> float:
    return float(_env(key, str(default)))


def _int(key: str, default: int = 0) -> int:
    return int(_env(key, str(default)))


@dataclass(frozen=True)
class ExchangeConfig:
    exchange_id: str = field(default_factory=lambda: _env("EXCHANGE_ID", "binanceusdm"))
    api_key: str = field(default_factory=lambda: _env("EXCHANGE_API_KEY"))
    api_secret: str = field(default_factory=lambda: _env("EXCHANGE_API_SECRET"))


@dataclass(frozen=True)
class TimeframeConfig:
    htf: str = field(default_factory=lambda: _env("HTF_TIMEFRAME", "1d"))
    mtf: str = field(default_factory=lambda: _env("MTF_TIMEFRAME", "1h"))
    ltf: str = field(default_factory=lambda: _env("LTF_TIMEFRAME", "15m"))


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = field(default_factory=lambda: _float("RISK_PER_TRADE_PCT", 1.0))
    tp_mode: str = field(default_factory=lambda: _env("TP_MODE", "STATIC"))
    rr_ratio: float = field(default_factory=lambda: _float("RR_RATIO", 3.0))
    max_daily_loss_pct: float = field(default_factory=lambda: _float("MAX_DAILY_LOSS_PCT", 3.0))
    max_consecutive_losses: int = field(default_factory=lambda: _int("MAX_CONSECUTIVE_LOSSES", 3))
    sl_buffer_pct: float = field(default_factory=lambda: _float("SL_BUFFER_PCT", 0.05))
    cooldown_candles: int = field(default_factory=lambda: _int("COOLDOWN_CANDLES", 20))


@dataclass(frozen=True)
class StructureConfig:
    swing_lookback: int = field(default_factory=lambda: _int("SWING_LOOKBACK", 3))
    min_bos_distance_pct: float = field(default_factory=lambda: _float("MIN_BOS_DISTANCE_PCT", 0.5))
    min_displacement_pct: float = field(default_factory=lambda: _float("MIN_DISPLACEMENT_PCT", 1.5))
    equal_level_tolerance_pct: float = field(default_factory=lambda: _float("EQUAL_LEVEL_TOLERANCE_PCT", 0.1))
    max_ob_age_candles: int = field(default_factory=lambda: _int("MAX_OB_AGE_CANDLES", 100))
    chop_zone_low: float = field(default_factory=lambda: _float("CHOP_ZONE_LOW", 0.45))
    chop_zone_high: float = field(default_factory=lambda: _float("CHOP_ZONE_HIGH", 0.55))


@dataclass(frozen=True)
class ExecutionConfig:
    max_confluence_window: int = field(default_factory=lambda: _int("MAX_CONFLUENCE_WINDOW", 12))
    pin_bar_wick_ratio: float = field(default_factory=lambda: _float("PIN_BAR_WICK_RATIO", 0.6))
    displacement_body_multiplier: float = field(default_factory=lambda: _float("DISPLACEMENT_BODY_MULTIPLIER", 2.0))


@dataclass(frozen=True)
class BotConfig:
    symbol: str = field(default_factory=lambda: _env("SYMBOL", "BTC/USDT:USDT"))
    trading_mode: str = field(default_factory=lambda: _env("TRADING_MODE", "paper"))
    paper_balance: float = field(default_factory=lambda: _float("PAPER_BALANCE", 200.0))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    timeframes: TimeframeConfig = field(default_factory=TimeframeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    structure: StructureConfig = field(default_factory=StructureConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
