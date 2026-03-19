"""
Configuration for the Crypto Trading Strategy System.
All parameters are tunable. Virtual balance mode by default.
"""

# ─── Account Settings ─────────────────────────────────────────────
STARTING_BALANCE = 200.0        # USD virtual balance
TARGET_BALANCE = 1200.0         # Target in 14 days
TRADING_DAYS = 14               # Strategy horizon

# ─── Exchange Settings ────────────────────────────────────────────
EXCHANGE = "bybit"
USE_TESTNET = True              # Use virtual/paper trading
TRADING_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
]

# ─── Leverage & Position Sizing ───────────────────────────────────
DEFAULT_LEVERAGE = 10
MAX_LEVERAGE = 20
MIN_LEVERAGE = 3
MAX_RISK_PER_TRADE = 0.05      # 5% of equity
MAX_CONCURRENT_POSITIONS = 3
MAX_POSITION_SIZE_USD = 500.0    # Absolute cap per trade to prevent runaway compounding

# ─── Risk Management ─────────────────────────────────────────────
DAILY_LOSS_LIMIT = 0.15         # 15% of day-start equity
WEEKLY_LOSS_LIMIT = 0.25        # 25% of week-start equity
MAX_DRAWDOWN = 0.40             # 40% from peak
KILL_SWITCH_DRAWDOWN = 0.50     # 50% from peak — halt all trading
MARGIN_RATIO_MIN = 1.5          # 150% margin ratio minimum

# ─── Strategy Parameters ─────────────────────────────────────────
# EMA
EMA_FAST = 9
EMA_SLOW = 21

# RSI
RSI_PERIOD = 14
RSI_LONG_THRESHOLD = 55
RSI_SHORT_THRESHOLD = 45
RSI_OVERBOUGHT = 75
RSI_OVERSOLD = 25

# MACD
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Bollinger Bands
BB_PERIOD = 20
BB_STD = 2.0

# ATR
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 2.0        # SL = ATR × this (wider to avoid premature stops)
ATR_TRAILING_MULTIPLIER = 1.0  # Trailing stop distance

# Volume
VOLUME_THRESHOLD = 1.3          # Volume must be > 1.3× average

# ─── Trade Management ────────────────────────────────────────────
REWARD_RISK_RATIO = 2.5         # TP at 2.5× SL distance
PARTIAL_TP_RATIO = 0.5          # Take 50% off at 1:1 RR
TIME_STOP_HOURS = 4             # Close if no movement after 4h
TRAILING_ACTIVATION_RR = 1.5    # Activate trailing at 1.5× risk

# ─── Volatility Regime Thresholds (ATR percentile) ───────────────
VOL_LOW = 25                    # Below 25th percentile
VOL_MEDIUM = 50                 # 25th–50th
VOL_HIGH = 75                   # 50th–75th
# Above 75th = Extreme

# ─── Fees (Bybit Futures) ────────────────────────────────────────
MAKER_FEE = 0.0001              # 0.01%
TAKER_FEE = 0.0006              # 0.06%
SLIPPAGE = 0.0005               # 0.05% estimated slippage

# ─── Data Settings ────────────────────────────────────────────────
CANDLE_TIMEFRAME = "15m"        # Primary timeframe
CONFIRMATION_TIMEFRAME = "1h"   # Confirmation timeframe
LOOKBACK_DAYS = 90              # Days of historical data for backtesting

# ─── Logging ──────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE = "trading_bot.log"
TRADE_LOG_FILE = "trades.json"

# ─── Kelly Criterion ─────────────────────────────────────────────
KELLY_FRACTION = 0.5            # Half-Kelly for safety
MIN_TRADES_FOR_KELLY = 10       # Minimum trades before using Kelly sizing
DEFAULT_WIN_RATE = 0.58         # Assumed win rate before enough data
DEFAULT_WIN_LOSS_RATIO = 2.0    # Assumed avg_win/avg_loss
MIN_POSITION_SIZE_PCT = 0.0     # No forced minimum — let Kelly decide

# ─── Defensive Mode Triggers ─────────────────────────────────────
SIGNAL_COOLDOWN_BARS = 8        # Minimum bars between signals per symbol (2h at 15m)
MIN_CONFIDENCE = 0.70           # Skip signals below this confidence

CONSECUTIVE_LOSS_REDUCE = 2     # Reduce size after N consecutive losses
CONSECUTIVE_LOSS_DEFENSIVE = 3  # Enter defensive mode after N losses
CONSECUTIVE_LOSS_HALT = 5       # Halt trading after N losses
CONSECUTIVE_WIN_RESTORE = 2     # Restore full size after N wins
