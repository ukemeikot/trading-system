"""Clock adapters (SPEC B2). SystemClock reads the wall clock; SimulatedClock is
driven manually for backtests/replay so time is injected, never read implicitly."""

from __future__ import annotations

from datetime import UTC, datetime

from tsys.application.ports import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimulatedClock(Clock):
    """A clock whose time is set explicitly. Used in backtest/replay so the domain
    never depends on the wall clock."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("SimulatedClock start must be tz-aware (UTC)")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, ts: datetime) -> None:
        self._now = ts
