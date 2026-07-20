"""GenerateDailyReport — the weekly/daily automated summary (SPEC M5/M6).

Reads the decision log for a UTC day and reports: net equity, trades taken,
risk vetoes, halts (circuit-breaker/kill-switch activations), and latency p50/p99
per stage. Depends on a structural query source (SqliteTradeRepository satisfies
it) so the application layer stays decoupled from SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class DailyReportSource(Protocol):
    def count_fills(self, day: str) -> int: ...
    def count_decisions_by_kind(self, day: str) -> dict[str, int]: ...
    def latency_samples(self, day: str) -> dict[str, list[float]]: ...
    def last_equity(self) -> float | None: ...


@dataclass(slots=True)
class DailyReport:
    day: str
    fills: int
    vetoes: int
    halts: int
    final_equity: float | None
    latency: dict[str, tuple[float, float]] = field(default_factory=dict)  # stage -> (p50, p99)


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0..100). 0.0 for an empty sample."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = max(1, min(len(ordered), round(pct / 100.0 * len(ordered))))
    return ordered[k - 1]


class GenerateDailyReport:
    def __init__(self, source: DailyReportSource) -> None:
        self._src = source

    def run(self, day: str) -> DailyReport:
        kinds = self._src.count_decisions_by_kind(day)
        latency = {
            stage: (percentile(samples, 50), percentile(samples, 99))
            for stage, samples in self._src.latency_samples(day).items()
        }
        return DailyReport(
            day=day,
            fills=self._src.count_fills(day),
            vetoes=kinds.get("veto", 0),
            halts=kinds.get("halt", 0),
            final_equity=self._src.last_equity(),
            latency=latency,
        )
