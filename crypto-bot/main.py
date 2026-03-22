"""Main entry point for the Crypto MTFA Trading Bot.

Runs an event loop that:
1. Fetches candle data on each timeframe interval
2. Routes data through the orchestrator pipeline
3. Places/manages orders via the exchange connector
"""

from __future__ import annotations

import time

import structlog

from .config import BotConfig
from .core.orchestrator import TradeOrchestrator
from .exchange.connector import ExchangeConnector
from .models import PositionStatus, TradingState
from .utils.logging import setup_logging

logger = structlog.get_logger(__name__)

# Approximate seconds per timeframe (for sleep intervals)
TF_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def main() -> None:
    """Boot the trading bot and enter the main loop."""
    config = BotConfig()
    setup_logging(config.log_level)

    logger.info(
        "bot.starting",
        symbol=config.symbol,
        mode=config.trading_mode,
        htf=config.timeframes.htf,
        mtf=config.timeframes.mtf,
        ltf=config.timeframes.ltf,
    )

    exchange = ExchangeConnector(config)
    orchestrator = TradeOrchestrator(config)

    ltf_interval = TF_SECONDS.get(config.timeframes.ltf, 900)
    mtf_interval = TF_SECONDS.get(config.timeframes.mtf, 3600)
    htf_interval = TF_SECONDS.get(config.timeframes.htf, 86400)

    htf_counter = 0
    mtf_counter = 0

    logger.info("bot.running", ltf_interval=ltf_interval)

    try:
        while True:
            loop_start = time.time()
            balance = exchange.get_balance()

            # ── HTF tick (every htf_interval / ltf_interval cycles) ──
            htf_cycles = max(1, htf_interval // ltf_interval)
            if htf_counter % htf_cycles == 0:
                htf_candles = exchange.fetch_candles(config.timeframes.htf, limit=200)
                if htf_candles:
                    orchestrator.tick_htf(htf_candles)

            # ── MTF tick ──
            mtf_cycles = max(1, mtf_interval // ltf_interval)
            if mtf_counter % mtf_cycles == 0:
                mtf_candles = exchange.fetch_candles(config.timeframes.mtf, limit=200)
                if mtf_candles:
                    orchestrator.tick_mtf(mtf_candles)

            # ── LTF tick (every cycle) ──
            ltf_candles = exchange.fetch_candles(config.timeframes.ltf, limit=200)
            if ltf_candles:
                # Remember position before tick to detect exits
                had_position = orchestrator.active_position
                position = orchestrator.tick_ltf(ltf_candles, balance)

                if position is not None and position.status == PositionStatus.PENDING:
                    order = exchange.place_limit_order(position)
                    if order:
                        orchestrator.risk.on_position_filled(position)

                # Sync paper balance when a position was closed
                if (
                    had_position is not None
                    and orchestrator.active_position is None
                    and had_position.pnl != 0
                    and exchange._paper
                ):
                    exchange.update_paper_balance(had_position.pnl)
                    balance = exchange.get_balance()

            # ── Status log ──
            _log_status(orchestrator, balance)

            htf_counter += 1
            mtf_counter += 1

            # Sleep until next LTF candle
            elapsed = time.time() - loop_start
            sleep_time = max(0, ltf_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("bot.stopped_by_user")
    except Exception:
        logger.exception("bot.fatal_error")
        raise


def _log_status(orchestrator: TradeOrchestrator, balance: float) -> None:
    """Log current bot status."""
    pos = orchestrator.active_position
    logger.info(
        "bot.status",
        state=orchestrator.state.value,
        balance=balance,
        daily_pnl=orchestrator.risk.daily_pnl,
        consecutive_losses=orchestrator.risk.consecutive_losses,
        has_position=pos is not None,
        position_direction=pos.direction.value if pos else None,
    )


if __name__ == "__main__":
    main()
