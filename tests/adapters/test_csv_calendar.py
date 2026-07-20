"""CsvCalendarSource parsing + staleness failsafe."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tsys.adapters.calendar.csv_source import CsvCalendarSource
from tsys.domain.values import Impact

SAMPLE = """# high-impact events, UTC
timestamp_utc,country,event,impact
2026-07-16T12:00:00Z,UK,BoE Rate Decision,high
2026-07-15T12:30:00Z,US,CPI,high
2026-07-14T09:00:00Z,UK,PMI,medium
"""


def _write(path: Path, text: str = SAMPLE) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_and_sorts_events(tmp_path: Path) -> None:
    src = CsvCalendarSource(_write(tmp_path / "calendar.csv"))
    events = src.load_events()
    assert len(events) == 3
    # sorted ascending by ts
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    boe = next(e for e in events if e.title == "BoE Rate Decision")
    assert boe.country == "UK" and boe.impact is Impact.HIGH
    assert events[0].ts == datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


def test_ignores_comment_lines(tmp_path: Path) -> None:
    text = "# a comment\n# another\n" + SAMPLE
    src = CsvCalendarSource(_write(tmp_path / "c.csv", text))
    assert len(src.load_events()) == 3


def test_fresh_file_not_stale(tmp_path: Path) -> None:
    src = CsvCalendarSource(_write(tmp_path / "c.csv"), stale_after_days=7)
    assert src.is_stale(datetime.now(UTC)) is False


def test_old_file_is_stale(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.csv")
    old = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    os.utime(path, (old, old))
    src = CsvCalendarSource(path, stale_after_days=7)
    assert src.is_stale(datetime.now(UTC)) is True


def test_missing_file_is_stale(tmp_path: Path) -> None:
    src = CsvCalendarSource(tmp_path / "nope.csv")
    assert src.is_stale(datetime.now(UTC)) is True
