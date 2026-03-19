"""
Virtual Exchange — Paper trading engine with realistic execution simulation.
Simulates order execution with slippage, fees, funding rates, and liquidation.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderStatus(Enum):
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    LIQUIDATED = "LIQUIDATED"


@dataclass
class Position:
    id: str
    symbol: str
    side: PositionSide
    entry_price: float
    size_usd: float           # Notional value
    leverage: int
    margin: float             # Collateral locked
    stop_loss: float
    take_profit: float
    partial_tp_taken: bool = False
    open_time: str = ""
    open_bar: int = 0              # Bar index at open (for backtester time stop)
    unrealized_pnl: float = 0.0
    funding_paid: float = 0.0


@dataclass
class TradeRecord:
    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size_usd: float
    leverage: int
    pnl: float
    fees: float
    funding: float
    net_pnl: float
    open_time: str
    close_time: str
    close_reason: str
    duration_minutes: float


class VirtualExchange:
    """
    Simulates a crypto futures exchange with:
    - Market/limit order execution
    - Slippage and fees
    - Funding rate charges
    - Liquidation mechanics
    - Position tracking
    - Trade history logging
    """

    def __init__(self, config):
        self.config = config
        self.balance = config.STARTING_BALANCE
        self.positions: dict[str, Position] = {}
        self.trade_history: list[TradeRecord] = []
        self.total_fees_paid = 0.0
        self.total_funding_paid = 0.0

    @property
    def equity(self) -> float:
        """Balance + unrealized PnL of all open positions."""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.balance + unrealized

    @property
    def used_margin(self) -> float:
        return sum(p.margin for p in self.positions.values())

    @property
    def free_margin(self) -> float:
        return self.equity - self.used_margin

    @property
    def margin_ratio(self) -> float:
        if self.used_margin == 0:
            return float("inf")
        return self.equity / self.used_margin

    def open_position(
        self,
        symbol: str,
        side: PositionSide,
        size_usd: float,
        entry_price: float,
        leverage: int,
        stop_loss: float,
        take_profit: float,
    ) -> Position | None:
        """Open a new futures position with virtual execution."""
        # Apply slippage
        slippage = entry_price * self.config.SLIPPAGE
        if side == PositionSide.LONG:
            fill_price = entry_price + slippage
        else:
            fill_price = entry_price - slippage

        # Calculate margin required
        margin = size_usd / leverage

        # Check available margin
        if margin > self.free_margin:
            size_usd = self.free_margin * leverage * 0.95  # Use 95% of available
            margin = size_usd / leverage
            if size_usd <= 0:
                return None

        # Check margin ratio after opening: (equity) / (used_margin + new_margin) >= min ratio
        new_used = self.used_margin + margin
        if new_used > 0 and self.equity / new_used < self.config.MARGIN_RATIO_MIN:
            return None

        # Lock margin and charge maker fee (limit order at current price)
        self.balance -= margin
        fee = size_usd * self.config.MAKER_FEE
        self.balance -= fee
        self.total_fees_paid += fee

        position = Position(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            size_usd=size_usd,
            leverage=leverage,
            margin=margin,
            stop_loss=stop_loss,
            take_profit=take_profit,
            open_time=datetime.now(timezone.utc).isoformat(),
        )

        self.positions[position.id] = position
        return position

    def update_positions(self, prices: dict[str, float], funding_rates: dict[str, float] = None, current_bar: int = 0):
        """
        Update all positions with current prices.
        Check for SL/TP/liquidation/time stop hits.
        """
        to_close = []
        to_partial = []

        # Time stop: bars per hour at 15m candles = 4
        time_stop_bars = int(getattr(self.config, 'TIME_STOP_HOURS', 4) * 4)

        for pid, pos in self.positions.items():
            price = prices.get(pos.symbol)
            if price is None:
                continue

            # Calculate unrealized PnL
            if pos.side == PositionSide.LONG:
                pos.unrealized_pnl = (price - pos.entry_price) / pos.entry_price * pos.size_usd
            else:
                pos.unrealized_pnl = (pos.entry_price - price) / pos.entry_price * pos.size_usd

            # Check liquidation (margin + unrealized PnL <= 0)
            if pos.margin + pos.unrealized_pnl <= 0:
                to_close.append((pid, price, "LIQUIDATED"))
                continue

            # Check stop loss
            if pos.side == PositionSide.LONG and price <= pos.stop_loss:
                to_close.append((pid, pos.stop_loss, "STOP_LOSS"))
                continue
            elif pos.side == PositionSide.SHORT and price >= pos.stop_loss:
                to_close.append((pid, pos.stop_loss, "STOP_LOSS"))
                continue

            # Partial take-profit at 1:1 RR
            if not pos.partial_tp_taken:
                sl_dist = abs(pos.entry_price - pos.stop_loss)
                if pos.side == PositionSide.LONG:
                    partial_tp_price = pos.entry_price + sl_dist
                    if price >= partial_tp_price:
                        to_partial.append((pid, partial_tp_price))
                else:
                    partial_tp_price = pos.entry_price - sl_dist
                    if price <= partial_tp_price:
                        to_partial.append((pid, partial_tp_price))

            # Check take profit
            if pos.side == PositionSide.LONG and price >= pos.take_profit:
                to_close.append((pid, pos.take_profit, "TAKE_PROFIT"))
                continue
            elif pos.side == PositionSide.SHORT and price <= pos.take_profit:
                to_close.append((pid, pos.take_profit, "TAKE_PROFIT"))
                continue

            # Time stop: close if position stagnant for too long
            if current_bar > 0 and pos.open_bar > 0:
                bars_held = current_bar - pos.open_bar
                if bars_held >= time_stop_bars:
                    # Only close if position is near breakeven (not trending)
                    pnl_pct = abs(pos.unrealized_pnl) / pos.margin if pos.margin > 0 else 0
                    if pnl_pct < 0.05:  # Less than 5% move on margin
                        to_close.append((pid, price, "TIME_STOP"))
                        continue

            # Apply funding rate (every 8 hours in real exchange, simplified here)
            if funding_rates and pos.symbol in funding_rates:
                fr = funding_rates[pos.symbol]
                funding_cost = pos.size_usd * abs(fr)
                if (pos.side == PositionSide.LONG and fr > 0) or \
                   (pos.side == PositionSide.SHORT and fr < 0):
                    # Pay funding
                    self.balance -= funding_cost
                    pos.funding_paid += funding_cost
                    self.total_funding_paid += funding_cost
                else:
                    # Receive funding
                    self.balance += funding_cost
                    pos.funding_paid -= funding_cost
                    self.total_funding_paid -= funding_cost

        # Execute partial take-profits (close 50% of position)
        partial_ratio = getattr(self.config, 'PARTIAL_TP_RATIO', 0.5)
        for pid, partial_price in to_partial:
            pos = self.positions.get(pid)
            if pos is None or pos.partial_tp_taken:
                continue
            close_amount = pos.size_usd * partial_ratio
            # Realize partial PnL
            if pos.side == PositionSide.LONG:
                partial_pnl = (partial_price - pos.entry_price) / pos.entry_price * close_amount
            else:
                partial_pnl = (pos.entry_price - partial_price) / pos.entry_price * close_amount
            fee = close_amount * self.config.MAKER_FEE
            self.total_fees_paid += fee
            net_partial = partial_pnl - fee
            # Return partial margin + profit
            partial_margin = pos.margin * partial_ratio
            self.balance += partial_margin + net_partial
            # Reduce position
            pos.size_usd -= close_amount
            pos.margin -= partial_margin
            pos.partial_tp_taken = True
            # Move stop-loss to breakeven after partial TP
            pos.stop_loss = pos.entry_price

        # Close positions that hit exit conditions
        for pid, exit_price, reason in to_close:
            self._close_position(pid, exit_price, reason)

    def close_position(self, position_id: str, current_price: float, reason: str = "MANUAL"):
        """Manually close a position."""
        self._close_position(position_id, current_price, reason)

    def _close_position(self, position_id: str, exit_price: float, reason: str):
        """Internal: close position, calculate PnL, record trade."""
        pos = self.positions.get(position_id)
        if pos is None:
            return

        # Apply slippage on exit
        slippage = exit_price * self.config.SLIPPAGE
        if pos.side == PositionSide.LONG:
            fill_price = exit_price - slippage
        else:
            fill_price = exit_price + slippage

        # Calculate realized PnL
        if pos.side == PositionSide.LONG:
            raw_pnl = (fill_price - pos.entry_price) / pos.entry_price * pos.size_usd
        else:
            raw_pnl = (pos.entry_price - fill_price) / pos.entry_price * pos.size_usd

        # Exit fee (maker)
        fee = pos.size_usd * self.config.MAKER_FEE
        self.total_fees_paid += fee

        net_pnl = raw_pnl - fee - pos.funding_paid

        if reason == "LIQUIDATED":
            net_pnl = -pos.margin  # Lose entire margin

        # Update balance
        self.balance += pos.margin + net_pnl

        # Parse open time for duration calculation
        try:
            open_dt = datetime.fromisoformat(pos.open_time)
            close_dt = datetime.now(timezone.utc)
            duration = (close_dt - open_dt).total_seconds() / 60
        except (ValueError, TypeError):
            duration = 0.0

        trade = TradeRecord(
            id=pos.id,
            symbol=pos.symbol,
            side=pos.side.value,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            size_usd=pos.size_usd,
            leverage=pos.leverage,
            pnl=round(raw_pnl, 4),
            fees=round(fee, 4),
            funding=round(pos.funding_paid, 4),
            net_pnl=round(net_pnl, 4),
            open_time=pos.open_time,
            close_time=datetime.now(timezone.utc).isoformat(),
            close_reason=reason,
            duration_minutes=round(duration, 1),
        )
        self.trade_history.append(trade)

        del self.positions[position_id]
        return trade

    def close_all_positions(self, prices: dict[str, float], reason: str = "CLOSE_ALL"):
        """Close all open positions at current prices."""
        for pid in list(self.positions.keys()):
            pos = self.positions[pid]
            price = prices.get(pos.symbol, pos.entry_price)
            self._close_position(pid, price, reason)

    def get_account_summary(self) -> dict:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "used_margin": round(self.used_margin, 2),
            "free_margin": round(self.free_margin, 2),
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
            "total_fees": round(self.total_fees_paid, 4),
            "total_funding": round(self.total_funding_paid, 4),
        }

    def get_performance_stats(self) -> dict:
        """Calculate comprehensive trading statistics."""
        if not self.trade_history:
            return {"message": "No trades yet"}

        pnls = [t.net_pnl for t in self.trade_history]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf")

        # Max drawdown calculation
        cumulative = []
        running = self.config.STARTING_BALANCE
        peak = running
        max_dd = 0
        for pnl in pnls:
            running += pnl
            cumulative.append(running)
            peak = max(peak, running)
            dd = (peak - running) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Sharpe approximation (assuming 15-minute bars)
        import numpy as np
        if len(pnls) > 1:
            returns = np.array(pnls) / self.config.STARTING_BALANCE
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 4) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        return {
            "total_trades": len(pnls),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "largest_win": round(max(wins), 2) if wins else 0,
            "largest_loss": round(min(losses), 2) if losses else 0,
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "final_equity": round(self.equity, 2),
            "return_pct": round((self.equity - self.config.STARTING_BALANCE) / self.config.STARTING_BALANCE * 100, 2),
            "total_fees": round(self.total_fees_paid, 2),
            "total_funding": round(self.total_funding_paid, 2),
        }

    def save_trades(self, filepath: str = None):
        """Save trade history to JSON file."""
        if filepath is None:
            filepath = self.config.TRADE_LOG_FILE
        trades = []
        for t in self.trade_history:
            trades.append({
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size_usd": t.size_usd,
                "leverage": t.leverage,
                "pnl": t.pnl,
                "fees": t.fees,
                "funding": t.funding,
                "net_pnl": t.net_pnl,
                "open_time": t.open_time,
                "close_time": t.close_time,
                "close_reason": t.close_reason,
                "duration_minutes": t.duration_minutes,
            })
        Path(filepath).write_text(json.dumps(trades, indent=2))
