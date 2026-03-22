"""Exchange connector using ccxt.

Handles fetching OHLCV data and placing/managing orders.
Supports both live and paper trading modes.
Paper mode connects to the exchange read-only for real market data
but simulates orders and tracks a virtual balance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import ccxt
import structlog

from config import BotConfig
from models import Bias, Candle, Position

logger = structlog.get_logger(__name__)


class ExchangeConnector:
    """Unified exchange interface for the trading bot."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.symbol = config.symbol
        self._paper = config.trading_mode == "paper"
        self._paper_balance = config.paper_balance
        self._paper_orders: list[dict[str, Any]] = []

        # Always connect to exchange for real market data
        exchange_class = getattr(ccxt, config.exchange.exchange_id)

        if self._paper:
            # Read-only connection — no API keys needed
            self._exchange = exchange_class(
                {
                    "enableRateLimit": True,
                    "options": {"defaultType": "swap"},
                }
            )
            logger.info(
                "exchange.paper_mode",
                balance=self._paper_balance,
                exchange=config.exchange.exchange_id,
            )
        else:
            self._exchange = exchange_class(
                {
                    "apiKey": config.exchange.api_key,
                    "secret": config.exchange.api_secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "swap"},
                }
            )
            logger.info("exchange.live_mode", exchange=config.exchange.exchange_id)

    def fetch_candles(
        self,
        timeframe: str,
        limit: int = 200,
        since: int | None = None,
    ) -> list[Candle]:
        """Fetch OHLCV candles from the exchange."""
        if self._exchange is None:
            logger.error("exchange.no_connection_paper_mode")
            return []

        try:
            ohlcv = self._exchange.fetch_ohlcv(
                self.symbol, timeframe, since=since, limit=limit
            )
        except ccxt.BaseError as e:
            logger.error("exchange.fetch_error", error=str(e))
            return []

        candles = []
        for row in ohlcv:
            candles.append(
                Candle(
                    timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        return candles

    def get_balance(self) -> float:
        """Get available USDT balance."""
        if self._paper:
            return self._paper_balance

        try:
            balance = self._exchange.fetch_balance()
            return float(balance.get("USDT", {}).get("free", 0))
        except ccxt.BaseError as e:
            logger.error("exchange.balance_error", error=str(e))
            return 0.0

    def update_paper_balance(self, pnl: float) -> float:
        """Update virtual paper balance after a trade closes. Returns new balance."""
        self._paper_balance += pnl
        logger.info("exchange.paper_balance_update", pnl=pnl, balance=self._paper_balance)
        return self._paper_balance

    def place_limit_order(self, position: Position) -> dict[str, Any] | None:
        """Place a limit order for the given position."""
        side = "buy" if position.direction == Bias.LONG else "sell"

        if self._paper:
            logger.info(
                "exchange.paper_order",
                side=side,
                price=position.entry_price,
                size=position.size,
                sl=position.stop_loss,
                tp=position.take_profit,
            )
            return {
                "id": f"paper-{datetime.now(timezone.utc).timestamp()}",
                "status": "open",
                "side": side,
                "price": position.entry_price,
                "amount": position.size,
            }

        if self._exchange is None:
            return None

        try:
            order = self._exchange.create_order(
                symbol=self.symbol,
                type="limit",
                side=side,
                amount=position.size,
                price=position.entry_price,
                params={
                    "stopLoss": {"triggerPrice": position.stop_loss},
                    "takeProfit": {"triggerPrice": position.take_profit},
                },
            )
            logger.info("exchange.order_placed", order_id=order["id"], side=side)
            return order
        except ccxt.BaseError as e:
            logger.error("exchange.order_error", error=str(e))
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if self._paper:
            logger.info("exchange.paper_cancel", order_id=order_id)
            return True

        if self._exchange is None:
            return False

        try:
            self._exchange.cancel_order(order_id, self.symbol)
            return True
        except ccxt.BaseError as e:
            logger.error("exchange.cancel_error", error=str(e))
            return False

    def get_current_price(self) -> float | None:
        """Get the latest price for the symbol."""
        try:
            ticker = self._exchange.fetch_ticker(self.symbol)
            return float(ticker["last"])
        except ccxt.BaseError as e:
            logger.error("exchange.ticker_error", error=str(e))
            return None
