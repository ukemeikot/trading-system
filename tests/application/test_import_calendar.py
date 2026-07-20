"""ImportCalendar use case — staleness reporting and the forex failsafe."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from tsys.adapters.clock import SimulatedClock
from tsys.application.use_cases.import_calendar import ImportCalendar
from tsys.domain.entities import NewsEvent
from tsys.domain.exceptions import StaleCalendar
from tsys.domain.values import Impact

NOW = datetime(2026, 7, 20, tzinfo=UTC)
EVENTS = [NewsEvent(ts=NOW, country="UK", title="CPI", impact=Impact.HIGH)]


class FakeCalendar:
    def __init__(self, stale: bool) -> None:
        self._stale = stale

    def load_events(self) -> Sequence[NewsEvent]:
        return EVENTS

    def is_stale(self, now: datetime) -> bool:
        return self._stale


def test_run_reports_fresh() -> None:
    uc = ImportCalendar(FakeCalendar(stale=False), SimulatedClock(NOW))
    result = uc.run()
    assert result.stale is False
    assert list(result.events) == EVENTS


def test_run_reports_stale() -> None:
    uc = ImportCalendar(FakeCalendar(stale=True), SimulatedClock(NOW))
    assert uc.run().stale is True


def test_require_fresh_raises_when_stale() -> None:
    uc = ImportCalendar(FakeCalendar(stale=True), SimulatedClock(NOW))
    with pytest.raises(StaleCalendar, match="forex"):
        uc.require_fresh()


def test_require_fresh_returns_events_when_fresh() -> None:
    uc = ImportCalendar(FakeCalendar(stale=False), SimulatedClock(NOW))
    assert list(uc.require_fresh()) == EVENTS
