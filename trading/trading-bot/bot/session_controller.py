"""Session Controller — trading window management and session lifecycle."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import (
    DailyStats,
    ExitReason,
    SessionConfig,
    SessionState,
    TradeResult,
)

logger = logging.getLogger(__name__)

EST = ZoneInfo("US/Eastern")


class SessionController:
    """Controls trading session timing, enforces windows, manages daily limits."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        self.config = config or SessionConfig()
        self._state = SessionState.INITIALIZING
        self._stats = DailyStats(session_date=date.today())
        self._consecutive_loss_days = 0
        self._events: list[tuple[datetime, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def stats(self) -> DailyStats:
        return self._stats

    def initialize(self) -> bool:
        """Run pre-session checks. Returns True if ready to trade."""
        now_est = datetime.now(EST)
        today = now_est.date()

        # Check consecutive losses
        if self._consecutive_loss_days >= self.config.max_consecutive_loss_days:
            logger.warning(
                "SKIP DAY — %d consecutive losing days (limit %d)",
                self._consecutive_loss_days,
                self.config.max_consecutive_loss_days,
            )
            self._state = SessionState.CLOSED
            return False

        self._stats = DailyStats(session_date=today)
        self._state = SessionState.READY
        self._log_event("System initialized, state=READY")
        logger.info("SESSION READY — Waiting for %s EST", self.config.trading_start)
        return True

    def update(self, now: datetime | None = None) -> SessionState:
        """Update session state based on current time. Call on every tick/candle."""
        if now is None:
            now = datetime.now(EST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=EST)

        current_time = now.time()

        if self._state == SessionState.READY:
            if current_time >= self.config.trading_start:
                self._state = SessionState.ACTIVE
                self._log_event("Session ACTIVE — trading window open")
                logger.info("SESSION ACTIVE — Trading window open")

        elif self._state == SessionState.ACTIVE:
            if current_time >= self.config.trading_end:
                self._state = SessionState.POSITION_ONLY
                self._log_event("Session POSITION_ONLY — no new entries")
                logger.info("SESSION POSITION_ONLY — No new entries after %s", self.config.trading_end)
            elif current_time >= self.config.new_setup_cutoff:
                if self._state != SessionState.WINDING_DOWN:
                    self._state = SessionState.WINDING_DOWN
                    self._log_event("Session WINDING_DOWN — no new setups")
                    logger.info("SESSION WINDING DOWN — No new setups after %s", self.config.new_setup_cutoff)

        elif self._state == SessionState.WINDING_DOWN:
            if current_time >= self.config.trading_end:
                self._state = SessionState.POSITION_ONLY
                self._log_event("Session POSITION_ONLY — no new entries")

        elif self._state == SessionState.POSITION_ONLY:
            if current_time >= self.config.force_close_deadline:
                self._log_event("Force close deadline reached")
                logger.info("FORCE CLOSE DEADLINE — Closing any open positions")

        return self._state

    def can_new_setup(self) -> bool:
        """Can the scanner start looking for new Step 1?"""
        return self._state == SessionState.ACTIVE

    def can_new_entry(self) -> bool:
        """Can a new entry be triggered?"""
        return self._state in (SessionState.ACTIVE, SessionState.WINDING_DOWN)

    def should_force_close(self, now: datetime | None = None) -> bool:
        """Should we force close all positions?"""
        if now is None:
            now = datetime.now(EST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=EST)
        return now.time() >= self.config.force_close_deadline

    def record_trade_result(self, result: TradeResult) -> None:
        """Record a completed trade."""
        self._stats.trade_results.append(result)
        self._stats.total_pnl_points += result.pnl_points
        self._stats.total_pnl_dollars += result.pnl_dollars
        self._stats.total_pnl_r += result.r_multiple

        if result.pnl_points > 0:
            self._stats.wins += 1
        elif result.pnl_points < 0:
            self._stats.losses += 1
        else:
            self._stats.break_even_exits += 1

        self._stats.entries_triggered += 1

        # Track drawdown
        if self._stats.total_pnl_dollars < self._stats.max_drawdown_dollars:
            self._stats.max_drawdown_dollars = self._stats.total_pnl_dollars

    def close_session(self) -> DailyStats:
        """Finalize the session and return stats."""
        self._state = SessionState.CLOSED
        self._log_event("Session CLOSED")

        # Update consecutive loss days
        if self._stats.total_pnl_dollars < 0:
            self._consecutive_loss_days += 1
        else:
            self._consecutive_loss_days = 0

        logger.info(
            "SESSION CLOSED — %d trades, %.1fR, $%.2f",
            self._stats.entries_triggered,
            self._stats.total_pnl_r,
            self._stats.total_pnl_dollars,
        )
        return self._stats

    def set_error(self, reason: str) -> None:
        """Set session to error state."""
        self._state = SessionState.ERROR
        self._log_event(f"ERROR: {reason}")
        logger.error("SESSION ERROR — %s", reason)

    def reset(self) -> None:
        """Reset for testing or new day."""
        self._state = SessionState.INITIALIZING
        self._stats = DailyStats(session_date=date.today())
        self._events.clear()

    def get_remaining_window(self, now: datetime | None = None) -> timedelta:
        """Return time remaining in the active trading window."""
        if now is None:
            now = datetime.now(EST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=EST)

        end = datetime.combine(now.date(), self.config.trading_end, tzinfo=EST)
        remaining = end - now
        return max(remaining, timedelta(0))

    def generate_report(self) -> str:
        """Generate a text session report."""
        s = self._stats
        lines = [
            f"# Session Report — {s.session_date}",
            "",
            "## Performance",
            f"| Metric              | Value       |",
            f"|---------------------|-------------|",
            f"| Setups Detected     | {s.setups_detected:<11} |",
            f"| Entries Triggered   | {s.entries_triggered:<11} |",
            f"| Wins / Losses       | {s.wins} / {s.losses:<8} |",
            f"| Break-Even Exits    | {s.break_even_exits:<11} |",
            f"| Net P&L (points)    | {s.total_pnl_points:<+11.2f} |",
            f"| Net P&L (R)         | {s.total_pnl_r:<+11.2f} |",
            f"| Net P&L ($)         | ${s.total_pnl_dollars:<+10.2f} |",
            f"| Max Drawdown ($)    | ${s.max_drawdown_dollars:<10.2f} |",
            "",
        ]

        if s.trade_results:
            lines.append("## Trades")
            for i, tr in enumerate(s.trade_results, 1):
                lines.append(
                    f"  {i}. {tr.direction.upper()} | "
                    f"Entry {tr.entry_price:.2f} → Exit {tr.exit_price:.2f} | "
                    f"P&L {tr.pnl_points:+.2f} pts ({tr.r_multiple:+.1f}R) | "
                    f"{tr.exit_reason.value}"
                )

        lines.append("")
        lines.append("## Events")
        for ts, event in self._events:
            lines.append(f"  {ts.strftime('%H:%M:%S')} — {event}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _log_event(self, event: str) -> None:
        self._events.append((datetime.now(EST), event))
