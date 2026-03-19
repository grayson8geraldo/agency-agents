"""Virtual forex account — paper trading with simulated balance."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .config import get_pair_name, get_pip_size, get_pip_value
from .models import Bias, Candle, Trade, TradeSignal, TradeStatus

logger = logging.getLogger(__name__)

STATE_FILE = Path("forex_bot_state.json")


@dataclass
class AccountState:
    initial_balance: Decimal
    balance: Decimal
    equity: Decimal
    peak_equity: Decimal
    daily_start_equity: Decimal
    daily_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    total_pnl_pips: Decimal = Decimal("0")
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
    """Forex paper trading account with persistent state."""

    def __init__(
        self,
        initial_balance: Decimal = Decimal("200.00"),
        symbol: str = "EURUSD=X",
    ):
        self.symbol = symbol
        self.pip_size = get_pip_size(symbol)
        self.pip_value_per_lot = get_pip_value(symbol)
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
        lot_size: Decimal,
        risk_amount: Decimal,
        timestamp: datetime,
    ) -> Trade:
        """Open a new virtual forex trade."""
        self.state.total_trades += 1
        trade = Trade(
            id=self.state.total_trades,
            signal=signal,
            lot_size=lot_size,
            risk_amount=risk_amount,
            pip_size=self.pip_size,
            pip_value=self.pip_value_per_lot,
            status=TradeStatus.OPEN,
            entry_price=signal.entry_price,
            opened_at=timestamp,
        )
        self.state.current_trade = trade

        sl_pips = abs(signal.entry_price - signal.stop_loss) / self.pip_size
        tp_pips = abs(signal.take_profit - signal.entry_price) / self.pip_size

        logger.info(
            f"TRADE #{trade.id}: {signal.direction.value} "
            f"{get_pair_name(self.symbol)} {lot_size} lot @ {signal.entry_price:.5f}, "
            f"SL={signal.stop_loss:.5f} ({sl_pips:.1f} pips), "
            f"TP={signal.take_profit:.5f} ({tp_pips:.1f} pips)"
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
        self.state.total_pnl_pips += trade.pnl_pips

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
            f"CLOSED #{trade.id}: {reason.value}, "
            f"exit={exit_price:.5f}, PnL=${trade.pnl:.2f} ({trade.pnl_pips:+.1f} pips), "
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
        pair_name = get_pair_name(self.symbol)

        avg_pnl = s.total_pnl / s.total_trades if s.total_trades else Decimal("0")
        avg_pnl_pips = s.total_pnl_pips / s.total_trades if s.total_trades else Decimal("0")

        winning = [t for t in s.trade_history if t.pnl > 0]
        losing = [t for t in s.trade_history if t.pnl < 0]
        avg_win = sum(t.pnl for t in winning) / len(winning) if winning else Decimal("0")
        avg_loss = sum(t.pnl for t in losing) / len(losing) if losing else Decimal("0")
        avg_win_pips = sum(t.pnl_pips for t in winning) / len(winning) if winning else Decimal("0")
        avg_loss_pips = sum(t.pnl_pips for t in losing) / len(losing) if losing else Decimal("0")

        profit_factor = abs(sum(t.pnl for t in winning) / sum(t.pnl for t in losing)) \
            if losing and sum(t.pnl for t in losing) != 0 else Decimal("0")

        lines = [
            "=" * 55,
            "       FOREX VIRTUAL ACCOUNT SUMMARY",
            "=" * 55,
            f"  Pair:             {pair_name}",
            f"  Initial Balance:  ${s.initial_balance:.2f}",
            f"  Current Balance:  ${s.balance:.2f}",
            f"  Total P&L:        ${s.total_pnl:+.2f} ({s.total_return_pct:+.1f}%)",
            f"  Total P&L (pips): {s.total_pnl_pips:+.1f}",
            f"  Peak Equity:      ${s.peak_equity:.2f}",
            f"  Max Drawdown:     {s.max_drawdown_pct:.1f}%",
            "-" * 55,
            f"  Total Trades:     {s.total_trades}",
            f"  Wins:             {s.winning_trades}",
            f"  Losses:           {s.losing_trades}",
            f"  Win Rate:         {s.win_rate:.1f}%",
            f"  Avg P&L/Trade:    ${avg_pnl:+.2f} ({avg_pnl_pips:+.1f} pips)",
            f"  Avg Win:          ${avg_win:+.2f} ({avg_win_pips:+.1f} pips)",
            f"  Avg Loss:         ${avg_loss:+.2f} ({avg_loss_pips:+.1f} pips)",
            f"  Profit Factor:    {profit_factor:.2f}",
            f"  Consec. Losses:   {s.consecutive_losses}",
            "=" * 55,
        ]
        return "\n".join(lines)

    def save_state(self, path: Path = STATE_FILE):
        """Save account state to JSON."""
        data = {
            "symbol": self.symbol,
            "balance": str(self.state.balance),
            "equity": str(self.state.equity),
            "peak_equity": str(self.state.peak_equity),
            "total_pnl": str(self.state.total_pnl),
            "total_pnl_pips": str(self.state.total_pnl_pips),
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
        self.symbol = data.get("symbol", self.symbol)
        self.state.balance = Decimal(data["balance"])
        self.state.equity = Decimal(data["equity"])
        self.state.peak_equity = Decimal(data["peak_equity"])
        self.state.total_pnl = Decimal(data["total_pnl"])
        self.state.total_pnl_pips = Decimal(data.get("total_pnl_pips", "0"))
        self.state.total_trades = data["total_trades"]
        self.state.winning_trades = data["winning_trades"]
        self.state.losing_trades = data["losing_trades"]
        self.state.consecutive_losses = data["consecutive_losses"]
        self.state.last_trade_date = data.get("last_trade_date")
        logger.info(f"State loaded: balance=${self.state.balance:.2f}")
