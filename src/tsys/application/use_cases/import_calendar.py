"""ImportCalendar use case (SPEC M2 / D2.3).

Loads scheduled high-impact events from the CalendarSource and reports staleness.
A stale calendar does not stop crypto; it disqualifies *forex* (the strategy
refuses to trade GBP/USD without a fresh calendar) — enforced downstream in M4.
`require_fresh()` raises StaleCalendar for callers that must not proceed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from tsys.application.ports import CalendarSource, Clock
from tsys.domain.entities import NewsEvent
from tsys.domain.exceptions import StaleCalendar


@dataclass(frozen=True, slots=True)
class CalendarImport:
    events: Sequence[NewsEvent]
    stale: bool


class ImportCalendar:
    def __init__(
        self, source: CalendarSource, clock: Clock, logger: logging.Logger | None = None
    ) -> None:
        self._source = source
        self._clock = clock
        self._log = logger or logging.getLogger("tsys.calendar")

    def run(self) -> CalendarImport:
        stale = self._source.is_stale(self._clock.now())
        events = self._source.load_events()
        if stale:
            self._log.warning(
                "calendar.stale",
                extra={"events": len(events), "action": "forex trading disqualified"},
            )
        else:
            self._log.info("calendar.loaded", extra={"events": len(events)})
        return CalendarImport(events=events, stale=stale)

    def require_fresh(self) -> Sequence[NewsEvent]:
        result = self.run()
        if result.stale:
            raise StaleCalendar(
                "calendar is older than its freshness window; refusing to trade forex "
                "(SPEC D2.3 stale-calendar failsafe)"
            )
        return result.events
