"""
Risk Manager Engine — Crypto Risk Manager agent logic.
Implements Kelly criterion, drawdown control, position sizing, and kill switches.
"""

import math
from dataclasses import dataclass, field
from enum import Enum


class RiskMode(Enum):
    NORMAL = "normal"
    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"
    HALTED = "halted"


@dataclass
class TradeResult:
    pnl: float
    is_win: bool


@dataclass
class RiskState:
    equity: float
    peak_equity: float
    day_start_equity: float
    week_start_equity: float
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    total_win_amount: float = 0.0
    total_loss_amount: float = 0.0
    mode: RiskMode = RiskMode.NORMAL
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    trade_history: list = field(default_factory=list)


class RiskManager:
    """
    Implements the Crypto Risk Manager agent's logic:
    - Kelly-based position sizing
    - Drawdown monitoring & mode switching
    - Daily/weekly loss limits
    - Kill switch
    """

    def __init__(self, config):
        self.config = config
        self.state = RiskState(
            equity=config.STARTING_BALANCE,
            peak_equity=config.STARTING_BALANCE,
            day_start_equity=config.STARTING_BALANCE,
            week_start_equity=config.STARTING_BALANCE,
        )

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown from peak as a fraction."""
        if self.state.peak_equity <= 0:
            return 0.0
        return 1.0 - (self.state.equity / self.state.peak_equity)

    @property
    def win_rate(self) -> float:
        if self.state.total_trades == 0:
            return self.config.DEFAULT_WIN_RATE
        return self.state.winning_trades / self.state.total_trades

    @property
    def avg_win(self) -> float:
        if self.state.winning_trades == 0:
            return 0.0
        return self.state.total_win_amount / self.state.winning_trades

    @property
    def avg_loss(self) -> float:
        losing = self.state.total_trades - self.state.winning_trades
        if losing == 0:
            return 0.0
        return self.state.total_loss_amount / losing

    @property
    def profit_factor(self) -> float:
        if self.state.total_loss_amount == 0:
            return float("inf") if self.state.total_win_amount > 0 else 0.0
        return self.state.total_win_amount / self.state.total_loss_amount

    def kelly_fraction(self) -> float:
        """Calculate half-Kelly fraction for position sizing."""
        if self.state.total_trades < self.config.MIN_TRADES_FOR_KELLY:
            wr = self.config.DEFAULT_WIN_RATE
            wl_ratio = self.config.DEFAULT_WIN_LOSS_RATIO
        else:
            wr = self.win_rate
            if self.avg_loss == 0:
                return self.config.KELLY_FRACTION
            wl_ratio = self.avg_win / self.avg_loss

        if wl_ratio <= 0:
            return 0.0

        kelly = (wr * wl_ratio - (1 - wr)) / wl_ratio
        kelly = max(0.0, kelly)
        return kelly * self.config.KELLY_FRACTION  # Half-Kelly

    def get_max_leverage(self) -> int:
        """Get maximum allowed leverage based on current risk mode."""
        mode = self.state.mode
        if mode == RiskMode.AGGRESSIVE:
            return self.config.MAX_LEVERAGE
        elif mode == RiskMode.NORMAL:
            return self.config.DEFAULT_LEVERAGE
        elif mode == RiskMode.DEFENSIVE:
            return 5
        else:
            return 0

    def get_max_risk_per_trade(self) -> float:
        """Get max risk per trade based on mode, using config values."""
        base_risk = self.config.MAX_RISK_PER_TRADE
        mode = self.state.mode
        if mode == RiskMode.AGGRESSIVE:
            return base_risk * 1.5
        elif mode == RiskMode.NORMAL:
            return base_risk
        elif mode == RiskMode.DEFENSIVE:
            return base_risk * 0.7  # 70% of normal (was 50% — too harsh for recovery)
        return 0.0

    def calculate_position_size(
        self, confidence: float = 1.0, entry_price: float = 0.0, stop_loss: float = 0.0
    ) -> float:
        """
        Calculate position size in USD using proper risk-based sizing.
        Risk amount = equity × max_risk_pct × confidence
        Position size = risk_amount / sl_distance_pct

        This ensures we always risk the intended % of equity per trade,
        regardless of how wide/tight the stop loss is.
        """
        if self.state.mode == RiskMode.HALTED:
            return 0.0

        confidence = max(0.5, min(1.0, confidence))
        max_risk = self.get_max_risk_per_trade()
        leverage = self.get_max_leverage()

        # Calculate SL distance as fraction of entry price
        if entry_price > 0 and stop_loss > 0:
            sl_distance_pct = abs(entry_price - stop_loss) / entry_price
        else:
            sl_distance_pct = 0.02  # Fallback: assume 2% SL distance

        # Prevent division by zero or unreasonably tight stops
        sl_distance_pct = max(sl_distance_pct, 0.001)

        # Risk amount in USD
        risk_amount = self.state.equity * max_risk * confidence

        # Position size = risk / SL distance
        size = risk_amount / sl_distance_pct

        # Secondary cap: Kelly criterion (only when proven profitable edge)
        kelly = self.kelly_fraction()
        if self.state.total_trades >= self.config.MIN_TRADES_FOR_KELLY and kelly > 0:
            if self.avg_loss != 0:
                wl_ratio = self.avg_win / abs(self.avg_loss)
                breakeven_wr = 1.0 / (1.0 + wl_ratio)
            else:
                breakeven_wr = 0.5
            if self.win_rate > breakeven_wr:
                kelly_risk = self.state.equity * kelly
                kelly_cap = kelly_risk / sl_distance_pct
                size = min(size, kelly_cap)

        # Reduce for consecutive losses (only in NORMAL mode — defensive mode already reduces risk)
        if self.state.mode == RiskMode.NORMAL:
            if self.state.consecutive_losses >= self.config.CONSECUTIVE_LOSS_REDUCE:
                size *= 0.75

        # Never more than equity × max leverage
        size = min(size, self.state.equity * leverage)

        # Absolute USD cap to prevent runaway compounding
        max_pos = getattr(self.config, 'MAX_POSITION_SIZE_USD', float('inf'))
        size = min(size, max_pos)

        # Minimum position size for small accounts
        min_size = self.state.equity * max(self.config.MIN_POSITION_SIZE_PCT, 0.01)
        return max(min_size, size)

    def calculate_leverage(self, volatility_regime: str) -> int:
        """Select leverage based on volatility regime and risk mode."""
        max_lev = self.get_max_leverage()

        regime_leverage = {
            "LOW": min(max_lev, 5),
            "MEDIUM": min(max_lev, 4),
            "HIGH": min(max_lev, 3),
            "EXTREME": min(max_lev, 2),
        }
        lev = regime_leverage.get(volatility_regime, self.config.DEFAULT_LEVERAGE)
        return max(self.config.MIN_LEVERAGE, min(lev, max_lev))

    def check_daily_limit(self) -> bool:
        """Return True if daily loss limit has NOT been hit."""
        if self.state.day_start_equity <= 0:
            return False
        daily_loss = -self.state.daily_pnl / self.state.day_start_equity
        return daily_loss < self.config.DAILY_LOSS_LIMIT

    def check_weekly_limit(self) -> bool:
        """Return True if weekly loss limit has NOT been hit."""
        if self.state.week_start_equity <= 0:
            return False
        weekly_loss = -self.state.weekly_pnl / self.state.week_start_equity
        return weekly_loss < self.config.WEEKLY_LOSS_LIMIT

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed. Returns (allowed, reason)."""
        if self.state.mode == RiskMode.HALTED:
            return False, "KILL SWITCH: Trading halted due to excessive drawdown"

        if self.drawdown_pct >= self.config.KILL_SWITCH_DRAWDOWN:
            self.state.mode = RiskMode.HALTED
            return False, f"KILL SWITCH: Drawdown {self.drawdown_pct:.1%} exceeds {self.config.KILL_SWITCH_DRAWDOWN:.0%}"

        if not self.check_daily_limit():
            return False, f"Daily loss limit hit ({self.config.DAILY_LOSS_LIMIT:.0%})"

        if not self.check_weekly_limit():
            return False, f"Weekly loss limit hit ({self.config.WEEKLY_LOSS_LIMIT:.0%})"

        if self.state.consecutive_losses >= self.config.CONSECUTIVE_LOSS_HALT:
            return False, f"{self.state.consecutive_losses} consecutive losses — trading halted for review"

        return True, "OK"

    def update_mode(self):
        """Update risk mode based on current state."""
        dd = self.drawdown_pct

        if dd >= self.config.KILL_SWITCH_DRAWDOWN:
            self.state.mode = RiskMode.HALTED
        elif dd >= self.config.MAX_DRAWDOWN or self.state.consecutive_losses >= self.config.CONSECUTIVE_LOSS_DEFENSIVE:
            self.state.mode = RiskMode.DEFENSIVE
        elif (
            self.state.equity >= self.config.STARTING_BALANCE * 1.5
            and self.win_rate >= 0.60
            and self.state.total_trades >= 20
        ):
            self.state.mode = RiskMode.AGGRESSIVE
        else:
            self.state.mode = RiskMode.NORMAL

    def record_trade(self, pnl: float, close_reason: str = ""):
        """Record a completed trade and update all risk state."""
        is_win = pnl > 0
        self.state.trade_history.append(TradeResult(pnl=pnl, is_win=is_win))
        self.state.total_trades += 1
        self.state.equity += pnl
        self.state.daily_pnl += pnl
        self.state.weekly_pnl += pnl

        # TIME_STOP near breakeven is a scratch, not a real loss — don't penalize streaks
        is_scratch = close_reason == "TIME_STOP" and abs(pnl) < self.state.equity * 0.005

        if is_win:
            self.state.winning_trades += 1
            self.state.total_win_amount += pnl
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
        elif is_scratch:
            # Scratch trade: count in stats but don't affect consecutive loss streak
            self.state.total_loss_amount += abs(pnl)
        else:
            self.state.total_loss_amount += abs(pnl)
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0

        # Update peak
        if self.state.equity > self.state.peak_equity:
            self.state.peak_equity = self.state.equity

        self.update_mode()

    def new_day(self):
        """Reset daily counters. Consecutive losses only reset after wins, not by time."""
        self.state.day_start_equity = self.state.equity
        self.state.daily_pnl = 0.0

    def new_week(self):
        """Reset weekly counters."""
        self.state.week_start_equity = self.state.equity
        self.state.weekly_pnl = 0.0

    def get_risk_report(self) -> dict:
        """Generate a risk status report."""
        return {
            "equity": round(self.state.equity, 2),
            "peak_equity": round(self.state.peak_equity, 2),
            "drawdown_pct": round(self.drawdown_pct * 100, 2),
            "mode": self.state.mode.value,
            "total_trades": self.state.total_trades,
            "win_rate": round(self.win_rate * 100, 2),
            "profit_factor": round(self.profit_factor, 2),
            "kelly_fraction": round(self.kelly_fraction(), 4),
            "consecutive_losses": self.state.consecutive_losses,
            "consecutive_wins": self.state.consecutive_wins,
            "daily_pnl": round(self.state.daily_pnl, 2),
            "weekly_pnl": round(self.state.weekly_pnl, 2),
            "max_leverage": self.get_max_leverage(),
        }
