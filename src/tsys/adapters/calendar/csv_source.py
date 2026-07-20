"""CsvCalendarSource -> CalendarSource (SPEC D2.3a).

Reads config/calendar.csv (a weekly manual-import fallback the user pastes into).
Comment lines starting with '#' are ignored; the remaining rows have the header
    timestamp_utc,country,event,impact

Staleness (SPEC D2.3 failsafe): the file is stale if it was last modified more
than `stale_after_days` ago — pasting a fresh export updates the mtime. When
stale, the strategy refuses to trade forex.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tsys.application.ports import CalendarSource
from tsys.domain.entities import NewsEvent
from tsys.domain.values import Impact

_IMPACT = {"low": Impact.LOW, "medium": Impact.MEDIUM, "high": Impact.HIGH}


class CsvCalendarSource(CalendarSource):
    def __init__(self, path: str | Path, stale_after_days: int = 7) -> None:
        self._path = Path(path)
        self._stale_after = timedelta(days=stale_after_days)

    def load_events(self) -> Sequence[NewsEvent]:
        events: list[NewsEvent] = []
        text = self._path.read_text(encoding="utf-8")
        rows = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        for row in csv.DictReader(rows):
            events.append(
                NewsEvent(
                    ts=_parse_ts(row["timestamp_utc"]),
                    country=row["country"].strip(),
                    title=row["event"].strip(),
                    impact=_IMPACT.get(row["impact"].strip().lower(), Impact.HIGH),
                )
            )
        events.sort(key=lambda e: e.ts)
        return events

    def is_stale(self, now: datetime) -> bool:
        if not self._path.exists():
            return True
        mtime = datetime.fromtimestamp(self._path.stat().st_mtime, tz=UTC)
        return (now - mtime) > self._stale_after


def _parse_ts(raw: str) -> datetime:
    s = raw.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
