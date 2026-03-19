"""Virtual account — paper trading with simulated balance."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .models import Bias, Trade, TradeSignal, TradeStatus

logger = logging.getLogger(__name__)

STATE_FILE = Path("trading_bot_state.json")


@dataclass
class AccountState:
    initial_balance: Decimal
    balance: Decimal
    equity: Decimal
    peak_equity: Decimal
    daily_start_equity: Decimal
    daily_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    consecutive_losses: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    current_trade: Optional[Trade] = None
    trade_history: list[Trade] = field(default_factory=list)
    last_trade_date: Optional[str] = None
    kill_switch_active: bool = False
    kill_switch_reason: str = ""

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100

    @property
    def max_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return float((self.peak_equity - self.equity) / self.peak_equity * 100)

    @property
    def total_return_pct(self) -> float:
        if self.initial_balance <= 0:
            return 0.0
        return float((self.equity - self.initial_balance) / self.initial_balance * 100)


class VirtualAccount:
    """Paper trading account with persistent state."""

    def __init__(self, initial_balance: Decimal = Decimal("200.00")):
        self.state = AccountState(
            initial_balance=initial_balance,
            balance=initial_balance,
            equity=initial_balance,
            peak_equity=initial_balance,
            daily_start_equity=initial_balance,
        )

    def reset_daily(self, date_str: str):
        """Reset daily tracking at start of new trading day."""
        if self.state.last_trade_date != date_str:
            self.state.daily_start_equity = self.state.equity
            self.state.daily_pnl = Decimal("0")
            self.state.last_trade_date = date_str
            self.state.kill_switch_active = False
            self.state.kill_switch_reason = ""
            logger.info(f"New trading day: {date_str}, equity: ${self.state.equity:.2f}")

    def open_trade(
        self,
        signal: TradeSignal,
        position_size: Decimal,
        risk_amount: Decimal,
        timestamp: datetime,
    ) -> Trade:
        """Open a new virtual trade."""
        self.state.total_trades += 1
        trade = Trade(
            id=self.state.total_trades,
            signal=signal,
            position_size=position_size,
            risk_amount=risk_amount,
            status=TradeStatus.OPEN,
            entry_price=signal.entry_price,
            opened_at=timestamp,
        )
        self.state.current_trade = trade
        logger.info(
            f"TRADE OPENED #{trade.id}: {signal.direction.value} "
            f"{position_size} @ {signal.entry_price}, "
            f"SL={signal.stop_loss}, TP={signal.take_profit}"
        )
        return trade

    def close_trade(
        self,
        exit_price: Decimal,
        timestamp: datetime,
        reason: TradeStatus,
    ) -> Optional[Trade]:
        """Close the current trade and update account."""
        trade = self.state.current_trade
        if trade is None:
            return None

        trade.close(exit_price, timestamp, reason)

        # Update balance
        self.state.balance += trade.pnl
        self.state.equity = self.state.balance
        self.state.daily_pnl += trade.pnl
        self.state.total_pnl += trade.pnl

        # Track wins/losses
        if trade.pnl > 0:
            self.state.winning_trades += 1
            self.state.consecutive_losses = 0
        elif trade.pnl < 0:
            self.state.losing_trades += 1
            self.state.consecutive_losses += 1

        # Update peak equity
        if self.state.equity > self.state.peak_equity:
            self.state.peak_equity = self.state.equity

        self.state.trade_history.append(trade)
        self.state.current_trade = None

        logger.info(
            f"TRADE CLOSED #{trade.id}: {reason.value}, "
            f"exit={exit_price}, PnL=${trade.pnl:.2f}, "
            f"balance=${self.state.balance:.2f}"
        )
        return trade

    def check_sl_tp(self, candle: Candle) -> Optional[TradeStatus]:
        """Check if current candle hits SL or TP."""
        trade = self.state.current_trade
        if trade is None:
            return None

        signal = trade.signal

        if signal.direction == Bias.LONG:
            if candle.low <= signal.stop_loss:
                return TradeStatus.CLOSED_SL
            if candle.high >= signal.take_profit:
                return TradeStatus.CLOSED_TP
        else:  # SHORT
            if candle.high >= signal.stop_loss:
                return TradeStatus.CLOSED_SL
            if candle.low <= signal.take_profit:
                return TradeStatus.CLOSED_TP

        return None

    def get_summary(self) -> str:
        """Get account summary string."""
        s = self.state
        avg_pnl = s.total_pnl / s.total_trades if s.total_trades else Decimal("0")

        # Calculate average R:R of winning trades
        winning = [t for t in s.trade_history if t.pnl > 0]
        avg_win_rr = (
            sum(t.signal.risk_reward for t in winning) / len(winning)
            if winning else Decimal("0")
        )

        lines = [
            "=" * 50,
            "       VIRTUAL ACCOUNT SUMMARY",
            "=" * 50,
            f"  Initial Balance:  ${s.initial_balance:.2f}",
            f"  Current Balance:  ${s.balance:.2f}",
            f"  Total P&L:        ${s.total_pnl:+.2f} ({s.total_return_pct:+.1f}%)",
            f"  Peak Equity:      ${s.peak_equity:.2f}",
            f"  Max Drawdown:     {s.max_drawdown_pct:.1f}%",
            "-" * 50,
            f"  Total Trades:     {s.total_trades}",
            f"  Wins:             {s.winning_trades}",
            f"  Losses:           {s.losing_trades}",
            f"  Win Rate:         {s.win_rate:.1f}%",
            f"  Avg P&L/Trade:    ${avg_pnl:+.2f}",
            f"  Avg Win R:R:      {avg_win_rr:.2f}",
            f"  Consec. Losses:   {s.consecutive_losses}",
            "=" * 50,
        ]
        return "\n".join(lines)

    def save_state(self, path: Path = STATE_FILE):
        """Save account state to JSON."""
        data = {
            "balance": str(self.state.balance),
            "equity": str(self.state.equity),
            "peak_equity": str(self.state.peak_equity),
            "total_pnl": str(self.state.total_pnl),
            "total_trades": self.state.total_trades,
            "winning_trades": self.state.winning_trades,
            "losing_trades": self.state.losing_trades,
            "consecutive_losses": self.state.consecutive_losses,
            "last_trade_date": self.state.last_trade_date,
        }
        path.write_text(json.dumps(data, indent=2))
        logger.info(f"State saved to {path}")

    def load_state(self, path: Path = STATE_FILE):
        """Load account state from JSON."""
        if not path.exists():
            return
        data = json.loads(path.read_text())
        self.state.balance = Decimal(data["balance"])
        self.state.equity = Decimal(data["equity"])
        self.state.peak_equity = Decimal(data["peak_equity"])
        self.state.total_pnl = Decimal(data["total_pnl"])
        self.state.total_trades = data["total_trades"]
        self.state.winning_trades = data["winning_trades"]
        self.state.losing_trades = data["losing_trades"]
        self.state.consecutive_losses = data["consecutive_losses"]
        self.state.last_trade_date = data.get("last_trade_date")
        logger.info(f"State loaded: balance=${self.state.balance:.2f}")


# Fix missing import for check_sl_tp
from .models import Candle  # noqa: E402
