"""Exchange connector using ccxt.

Handles fetching OHLCV data and placing/managing orders.
Supports both live and paper trading modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import ccxt
import structlog

from ..config import BotConfig
from ..models import Bias, Candle, Position

logger = structlog.get_logger(__name__)


class ExchangeConnector:
    """Unified exchange interface for the trading bot."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.symbol = config.symbol
        self._paper = config.trading_mode == "paper"

        if self._paper:
            logger.info("exchange.paper_mode")
            self._exchange = None
        else:
            exchange_class = getattr(ccxt, config.exchange.exchange_id)
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
            return 1000.0  # Default paper balance

        if self._exchange is None:
            return 0.0

        try:
            balance = self._exchange.fetch_balance()
            return float(balance.get("USDT", {}).get("free", 0))
        except ccxt.BaseError as e:
            logger.error("exchange.balance_error", error=str(e))
            return 0.0

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
        if self._exchange is None:
            return None

        try:
            ticker = self._exchange.fetch_ticker(self.symbol)
            return float(ticker["last"])
        except ccxt.BaseError as e:
            logger.error("exchange.ticker_error", error=str(e))
            return None
