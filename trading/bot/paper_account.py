"""Paper trading account — manages virtual €200 balance, positions, and trade history."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from trading.bot.models import Bias, TradeResult, TradeSignal


@dataclass
class Position:
    """An open paper trading position."""
    id: int
    symbol: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    risk_eur: float
    opened_at: datetime
    status: str = "OPEN"  # "OPEN", "TP_HIT", "SL_HIT", "CLOSED"
    exit_price: float | None = None
    closed_at: datetime | None = None
    pnl_eur: float = 0.0
    pnl_pips: float = 0.0


@dataclass
class PaperAccount:
    """Virtual forex trading account with full position and P&L tracking.

    All monetary values are in EUR.
    """
    initial_balance: float = 200.0
    balance: float = 200.0
    equity: float = 200.0
    risk_per_trade_pct: float = 1.0  # 1% risk per trade
    leverage: int = 30  # EU retail forex leverage cap
    positions: list[Position] = field(default_factory=list)
    trade_history: list[Position] = field(default_factory=list)
    next_id: int = 1
    state_file: str = "paper_account.json"

    # -- Balance & Risk --

    @property
    def risk_amount(self) -> float:
        """Max EUR to risk on a single trade."""
        return self.balance * (self.risk_per_trade_pct / 100.0)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "OPEN"]

    @property
    def total_trades(self) -> int:
        return len(self.trade_history)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trade_history if t.pnl_eur > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trade_history if t.pnl_eur <= 0)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_eur for t in self.trade_history)

    # -- Lot Size Calculation --

    def calculate_lot_size(self, risk_pips: float, pip_value_per_lot: float = 10.0) -> float:
        """Calculate lot size based on risk amount and stop-loss distance.

        For EUR/USD: 1 standard lot (100,000 units) = $10/pip.
        Micro lot (0.01) = $0.10/pip.

        Args:
            risk_pips: Distance from entry to stop-loss in pips.
            pip_value_per_lot: Value of 1 pip per standard lot (default $10 for EUR/USD).

        Returns:
            Lot size (e.g. 0.02 = 2 micro lots).
        """
        if risk_pips <= 0:
            return 0.0

        risk_eur = self.risk_amount
        # lot_size = risk_amount / (risk_pips * pip_value_per_lot)
        lot_size = risk_eur / (risk_pips * pip_value_per_lot)
        # Round down to 2 decimals (0.01 = 1 micro lot minimum)
        lot_size = max(0.01, round(lot_size, 2))

        # Check margin: lot_size * 100000 / leverage must not exceed balance
        required_margin = (lot_size * 100_000) / self.leverage
        if required_margin > self.balance:
            lot_size = round((self.balance * self.leverage) / 100_000, 2)
            lot_size = max(0.01, lot_size)

        return lot_size

    # -- Open Position --

    def open_position(self, trade: TradeSignal, symbol: str) -> Position | None:
        """Open a new paper position based on the ICT pipeline signal.

        Args:
            trade: TradeSignal from the orchestrator pipeline.
            symbol: Forex pair (e.g. "EUR/USD").

        Returns:
            The opened Position, or None if insufficient balance.
        """
        if self.open_positions:
            logger.warning("Already have an open position — max 1 at a time")
            return None

        lot_size = self.calculate_lot_size(trade.risk_pips)
        risk_eur = lot_size * trade.risk_pips * 10.0  # approximate

        if risk_eur > self.balance:
            logger.warning(
                "Insufficient balance: need €{:.2f} risk, have €{:.2f}",
                risk_eur, self.balance,
            )
            return None

        direction = "BUY" if trade.bias == Bias.BULLISH else "SELL"
        position = Position(
            id=self.next_id,
            symbol=symbol,
            direction=direction,
            entry_price=trade.entry,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            lot_size=lot_size,
            risk_eur=round(risk_eur, 2),
            opened_at=datetime.now(timezone.utc),
        )
        self.positions.append(position)
        self.next_id += 1

        logger.info(
            "PAPER TRADE OPENED #{}: {} {} @ {} | Lot: {} | Risk: €{:.2f} | SL: {} | TP: {}",
            position.id, direction, symbol, trade.entry,
            lot_size, risk_eur, trade.stop_loss, trade.take_profit,
        )
        self.save()
        return position

    # -- Check & Close Position --

    def check_position(self, position: Position, current_price: float) -> Position:
        """Check if current price hits TP or SL.

        Args:
            position: The open position to check.
            current_price: Current market price (bid for sells, ask for buys).

        Returns:
            The position (updated if closed).
        """
        if position.status != "OPEN":
            return position

        if position.direction == "BUY":
            if current_price >= position.take_profit:
                return self._close_position(position, position.take_profit, "TP_HIT")
            if current_price <= position.stop_loss:
                return self._close_position(position, position.stop_loss, "SL_HIT")
        else:  # SELL
            if current_price <= position.take_profit:
                return self._close_position(position, position.take_profit, "TP_HIT")
            if current_price >= position.stop_loss:
                return self._close_position(position, position.stop_loss, "SL_HIT")

        # Update unrealized P&L
        pip_size = 0.01 if position.entry_price > 10 else 0.0001
        if position.direction == "BUY":
            pips = (current_price - position.entry_price) / pip_size
        else:
            pips = (position.entry_price - current_price) / pip_size
        unrealized = pips * position.lot_size * 10.0
        self.equity = self.balance + unrealized

        return position

    def _close_position(self, position: Position, exit_price: float, reason: str) -> Position:
        """Close a position and update balance."""
        position.status = reason
        position.exit_price = exit_price
        position.closed_at = datetime.now(timezone.utc)

        pip_size = 0.01 if position.entry_price > 10 else 0.0001
        if position.direction == "BUY":
            position.pnl_pips = round((exit_price - position.entry_price) / pip_size, 1)
        else:
            position.pnl_pips = round((position.entry_price - exit_price) / pip_size, 1)

        position.pnl_eur = round(position.pnl_pips * position.lot_size * 10.0, 2)
        self.balance = round(self.balance + position.pnl_eur, 2)
        self.equity = self.balance

        self.trade_history.append(position)
        self.positions = [p for p in self.positions if p.id != position.id]

        result = "WIN" if position.pnl_eur > 0 else "LOSS"
        logger.info(
            "PAPER TRADE CLOSED #{} — {} | {:.1f} pips | €{:+.2f} | Balance: €{:.2f}",
            position.id, result, position.pnl_pips, position.pnl_eur, self.balance,
        )
        self.save()
        return position

    # -- Persistence --

    def save(self) -> None:
        """Save account state to JSON file."""
        data = {
            "initial_balance": self.initial_balance,
            "balance": self.balance,
            "equity": self.equity,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "leverage": self.leverage,
            "next_id": self.next_id,
            "positions": [self._pos_to_dict(p) for p in self.positions],
            "trade_history": [self._pos_to_dict(p) for p in self.trade_history],
        }
        Path(self.state_file).write_text(json.dumps(data, indent=2, default=str))

    @classmethod
    def load(cls, path: str = "paper_account.json") -> PaperAccount:
        """Load account state from JSON file, or create new."""
        if not os.path.exists(path):
            logger.info("No saved state — creating new paper account with €200")
            account = cls(state_file=path)
            account.save()
            return account

        data = json.loads(Path(path).read_text())
        account = cls(
            initial_balance=data["initial_balance"],
            balance=data["balance"],
            equity=data.get("equity", data["balance"]),
            risk_per_trade_pct=data.get("risk_per_trade_pct", 1.0),
            leverage=data.get("leverage", 30),
            next_id=data.get("next_id", 1),
            state_file=path,
        )
        account.positions = [cls._dict_to_pos(d) for d in data.get("positions", [])]
        account.trade_history = [cls._dict_to_pos(d) for d in data.get("trade_history", [])]
        logger.info("Loaded paper account: €{:.2f} balance, {} trades", account.balance, account.total_trades)
        return account

    @staticmethod
    def _pos_to_dict(p: Position) -> dict:
        return {
            "id": p.id,
            "symbol": p.symbol,
            "direction": p.direction,
            "entry_price": p.entry_price,
            "stop_loss": p.stop_loss,
            "take_profit": p.take_profit,
            "lot_size": p.lot_size,
            "risk_eur": p.risk_eur,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "status": p.status,
            "exit_price": p.exit_price,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "pnl_eur": p.pnl_eur,
            "pnl_pips": p.pnl_pips,
        }

    @staticmethod
    def _dict_to_pos(d: dict) -> Position:
        return Position(
            id=d["id"],
            symbol=d["symbol"],
            direction=d["direction"],
            entry_price=d["entry_price"],
            stop_loss=d["stop_loss"],
            take_profit=d["take_profit"],
            lot_size=d["lot_size"],
            risk_eur=d["risk_eur"],
            opened_at=datetime.fromisoformat(d["opened_at"]) if d.get("opened_at") else datetime.now(timezone.utc),
            status=d.get("status", "OPEN"),
            exit_price=d.get("exit_price"),
            closed_at=datetime.fromisoformat(d["closed_at"]) if d.get("closed_at") else None,
            pnl_eur=d.get("pnl_eur", 0.0),
            pnl_pips=d.get("pnl_pips", 0.0),
        )

    # -- Display --

    def print_status(self) -> None:
        """Print current account status."""
        print("\n" + "=" * 55)
        print("  PAPER TRADING ACCOUNT")
        print("=" * 55)
        print(f"  Balance:     €{self.balance:.2f}")
        print(f"  Equity:      €{self.equity:.2f}")
        print(f"  P&L:         €{self.total_pnl:+.2f} ({(self.total_pnl / self.initial_balance * 100):+.1f}%)")
        print(f"  Trades:      {self.total_trades} ({self.wins}W / {self.losses}L)")
        print(f"  Win rate:    {self.win_rate:.0f}%")
        print(f"  Risk/trade:  {self.risk_per_trade_pct}% (€{self.risk_amount:.2f})")
        print(f"  Leverage:    1:{self.leverage}")

        if self.open_positions:
            print(f"\n  Open positions:")
            for p in self.open_positions:
                print(f"    #{p.id} {p.direction} {p.symbol} @ {p.entry_price} "
                      f"| Lot: {p.lot_size} | SL: {p.stop_loss} | TP: {p.take_profit}")

        if self.trade_history:
            print(f"\n  Recent trades:")
            for t in self.trade_history[-5:]:
                result = "WIN" if t.pnl_eur > 0 else "LOSS"
                print(f"    #{t.id} {result} {t.direction} {t.symbol} "
                      f"| {t.pnl_pips:+.1f} pips | €{t.pnl_eur:+.2f}")

        print("=" * 55 + "\n")
