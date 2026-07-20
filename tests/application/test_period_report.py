"""GeneratePeriodReport — weekly observation aggregation (SPEC M6)."""

from __future__ import annotations

from tsys.application.use_cases.period_report import GeneratePeriodReport


class FakeSource:
    def __init__(self, curve, kinds, exit_reasons, latency, fills):  # type: ignore[no-untyped-def]
        self._curve = curve
        self._kinds = kinds
        self._exit_reasons = exit_reasons
        self._latency = latency
        self._fills = fills

    def fills_between(self, start: str, end: str) -> int:
        return self._fills

    def kind_counts_between(self, start: str, end: str) -> dict[str, int]:
        return self._kinds

    def exit_reason_counts_between(self, start: str, end: str) -> dict[str, int]:
        return self._exit_reasons

    def equity_between(self, start: str, end: str) -> list[tuple[str, float]]:
        return self._curve

    def latency_between(self, start: str, end: str) -> dict[str, list[float]]:
        return self._latency


def test_net_return_and_max_drawdown() -> None:
    src = FakeSource(
        curve=[("t0", 100.0), ("t1", 90.0), ("t2", 105.0)],
        kinds={}, exit_reasons={}, latency={}, fills=0,
    )
    r = GeneratePeriodReport(src).run("2026-07-01", "2026-07-08")
    assert abs(r.net_return_pct - 5.0) < 1e-9      # 100 -> 105
    assert abs(r.max_drawdown_pct - 10.0) < 1e-9   # peak 100 -> trough 90


def test_filter_activations_categorized() -> None:
    src = FakeSource(
        curve=[("t0", 100.0), ("t1", 100.0)],
        kinds={"veto": 4, "halt": 1},
        exit_reasons={
            "volatility spike halt": 2, "news blackout flatten": 1, "stop": 3, "target": 5,
            "time_stop": 2, "kill switch: drawdown limit hit": 1,
        },
        latency={"tick_to_signal": [10.0, 20.0, 30.0, 40.0]},
        fills=7,
    )
    r = GeneratePeriodReport(src).run("2026-07-01", "2026-07-08")
    assert r.fills == 7 and r.vetoes == 4 and r.halts == 1
    fa = r.filter_activations
    assert fa["volatility_spike"] == 2
    assert fa["news_blackout"] == 1
    assert fa["stop_out"] == 3
    assert fa["target_hit"] == 5
    assert fa["time_stop"] == 2
    assert fa["risk_halt"] == 1
    p50, p99 = r.latency["tick_to_signal"]
    assert p99 >= p50 > 0


def test_empty_period_is_flat() -> None:
    r = GeneratePeriodReport(FakeSource([], {}, {}, {}, 0)).run("2026-07-01", "2026-07-08")
    assert r.net_return_pct == 0.0 and r.max_drawdown_pct == 0.0 and r.fills == 0
