"""Paper Account — virtual balance tracking for paper trading mode."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import TradeResult

logger = logging.getLogger(__name__)


@dataclass
class AccountSnapshot:
    timestamp: datetime
    balance: float
    unrealized_pnl: float
    equity: float
    event: str = ""


class PaperAccount:
    """Tracks virtual balance, equity curve, and enforces margin limits."""

    def __init__(
        self,
        initial_balance: float = 200.0,
        state_file: str = "paper_account_state.json",
    ) -> None:
        self.initial_balance = initial_balance
        self._balance = initial_balance
        self._unrealized_pnl = 0.0
        self._trade_history: list[TradeResult] = []
        self._equity_curve: list[AccountSnapshot] = []
        self._state_file = Path(state_file)

        # Try to restore previous state
        self._load_state()

        self._snapshot("account_initialized")
        logger.info(
            "PAPER ACCOUNT — Balance: $%.2f | Initial: $%.2f",
            self._balance,
            self.initial_balance,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def balance(self) -> float:
        """Cash balance (realized only)."""
        return self._balance

    @property
    def equity(self) -> float:
        """Balance + unrealized P&L."""
        return self._balance + self._unrealized_pnl

    @property
    def unrealized_pnl(self) -> float:
        return self._unrealized_pnl

    @property
    def total_pnl(self) -> float:
        return self._balance - self.initial_balance

    @property
    def total_trades(self) -> int:
        return len(self._trade_history)

    @property
    def win_rate(self) -> float:
        if not self._trade_history:
            return 0.0
        wins = sum(1 for t in self._trade_history if t.pnl_dollars > 0)
        return wins / len(self._trade_history) * 100

    @property
    def is_blown(self) -> bool:
        """Account balance depleted — cannot continue trading."""
        return self._balance <= 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def can_afford_trade(self, risk_dollars: float) -> bool:
        """Check if account has enough balance for the risk."""
        return self._balance >= risk_dollars

    def update_unrealized(self, pnl_dollars: float) -> None:
        """Update unrealized P&L from open position."""
        self._unrealized_pnl = pnl_dollars

    def record_trade(self, result: TradeResult) -> None:
        """Record a completed trade and update balance."""
        self._balance += result.pnl_dollars
        self._unrealized_pnl = 0.0
        self._trade_history.append(result)

        self._snapshot(f"trade_closed_{result.exit_reason.value}")
        self._save_state()

        logger.info(
            "PAPER ACCOUNT — Trade P&L: $%+.2f | Balance: $%.2f | Total P&L: $%+.2f",
            result.pnl_dollars,
            self._balance,
            self.total_pnl,
        )

        if self.is_blown:
            logger.warning("PAPER ACCOUNT — BALANCE DEPLETED! Trading halted.")

    def get_summary(self) -> str:
        """Return formatted account summary."""
        wins = sum(1 for t in self._trade_history if t.pnl_dollars > 0)
        losses = sum(1 for t in self._trade_history if t.pnl_dollars < 0)
        be = sum(1 for t in self._trade_history if t.pnl_dollars == 0)

        peak = max((s.equity for s in self._equity_curve), default=self.initial_balance)
        trough = min((s.equity for s in self._equity_curve), default=self.initial_balance)
        max_dd = peak - trough if self._equity_curve else 0.0

        lines = [
            "",
            "=" * 50,
            "  PAPER ACCOUNT SUMMARY",
            "=" * 50,
            f"  Initial Balance:    ${self.initial_balance:>10.2f}",
            f"  Current Balance:    ${self._balance:>10.2f}",
            f"  Unrealized P&L:     ${self._unrealized_pnl:>+10.2f}",
            f"  Equity:             ${self.equity:>10.2f}",
            f"  Total P&L:          ${self.total_pnl:>+10.2f}",
            f"  Return:             {self.total_pnl / self.initial_balance * 100:>+10.1f}%",
            "-" * 50,
            f"  Total Trades:       {self.total_trades:>10}",
            f"  Wins / Losses / BE: {wins} / {losses} / {be}",
            f"  Win Rate:           {self.win_rate:>10.1f}%",
            f"  Max Drawdown:       ${max_dd:>10.2f}",
            "=" * 50,
            "",
        ]
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset account to initial state."""
        self._balance = self.initial_balance
        self._unrealized_pnl = 0.0
        self._trade_history.clear()
        self._equity_curve.clear()
        if self._state_file.exists():
            self._state_file.unlink()
        self._snapshot("account_reset")
        logger.info("PAPER ACCOUNT — Reset to $%.2f", self.initial_balance)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _save_state(self) -> None:
        """Save account state to JSON for recovery across restarts."""
        state = {
            "initial_balance": self.initial_balance,
            "balance": self._balance,
            "total_trades": self.total_trades,
            "total_pnl": self.total_pnl,
            "last_updated": datetime.now().isoformat(),
            "trades": [
                {
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl_dollars": t.pnl_dollars,
                    "r_multiple": t.r_multiple,
                    "exit_reason": t.exit_reason.value,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                }
                for t in self._trade_history
            ],
        }
        with open(self._state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self) -> None:
        """Load account state from JSON if exists."""
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            self._balance = state.get("balance", self.initial_balance)
            logger.info(
                "PAPER ACCOUNT — Restored state: balance=$%.2f, trades=%d",
                self._balance,
                state.get("total_trades", 0),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("PAPER ACCOUNT — Failed to load state: %s", e)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _snapshot(self, event: str) -> None:
        self._equity_curve.append(
            AccountSnapshot(
                timestamp=datetime.now(),
                balance=self._balance,
                unrealized_pnl=self._unrealized_pnl,
                equity=self.equity,
                event=event,
            )
        )
