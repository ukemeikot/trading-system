"""GeneratePeriodReport — the weekly observation report (SPEC M6).

Aggregates the decision log over a date window into the numbers M6 tracks: net
return after costs, max drawdown, trades taken / vetoed, halts, filter activations
(blackouts hit, volatility-spike breakers fired, stop/target/time exits), and
latency p50/p99. Depends on a structural source (SqliteTradeRepository satisfies
it) so the application layer stays decoupled from SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tsys.application.use_cases.daily_report import percentile


class PeriodReportSource(Protocol):
    def fills_between(self, start: str, end: str) -> int: ...
    def kind_counts_between(self, start: str, end: str) -> dict[str, int]: ...
    def exit_reason_counts_between(self, start: str, end: str) -> dict[str, int]: ...
    def equity_between(self, start: str, end: str) -> list[tuple[str, float]]: ...
    def latency_between(self, start: str, end: str) -> dict[str, list[float]]: ...


@dataclass(slots=True)
class PeriodReport:
    start: str
    end: str
    fills: int
    vetoes: int
    halts: int
    net_return_pct: float
    max_drawdown_pct: float
    filter_activations: dict[str, int] = field(default_factory=dict)
    latency: dict[str, tuple[float, float]] = field(default_factory=dict)  # stage -> (p50, p99)


def _max_drawdown(curve: list[tuple[str, float]]) -> float:
    peak: float | None = None
    worst = 0.0
    for _, eq in curve:
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            worst = max(worst, (peak - eq) / peak * 100.0)
    return worst


def _categorize(reason: str) -> str | None:
    r = reason.lower()
    if "spike" in r:
        return "volatility_spike"
    if "blackout" in r:
        return "news_blackout"
    if "kill switch" in r or "daily loss" in r or r.startswith("halt"):
        return "risk_halt"
    if "stop" in r and "time" not in r:
        return "stop_out"
    if "time" in r:
        return "time_stop"
    if "target" in r:
        return "target_hit"
    if "signal" in r:
        return "signal_exit"
    return None


class GeneratePeriodReport:
    def __init__(self, source: PeriodReportSource) -> None:
        self._src = source

    def run(self, start: str, end: str) -> PeriodReport:
        """start inclusive, end exclusive (ISO date or datetime strings)."""
        curve = self._src.equity_between(start, end)
        net = 0.0
        if len(curve) >= 2 and curve[0][1] != 0:
            net = (curve[-1][1] - curve[0][1]) / curve[0][1] * 100.0

        activations: dict[str, int] = {}
        for reason, count in self._src.exit_reason_counts_between(start, end).items():
            cat = _categorize(reason)
            if cat is not None:
                activations[cat] = activations.get(cat, 0) + count

        kinds = self._src.kind_counts_between(start, end)
        latency = {
            stage: (percentile(s, 50), percentile(s, 99))
            for stage, s in self._src.latency_between(start, end).items()
        }
        return PeriodReport(
            start=start, end=end,
            fills=self._src.fills_between(start, end),
            vetoes=kinds.get("veto", 0),
            halts=kinds.get("halt", 0),
            net_return_pct=net,
            max_drawdown_pct=_max_drawdown(curve),
            filter_activations=activations,
            latency=latency,
        )
