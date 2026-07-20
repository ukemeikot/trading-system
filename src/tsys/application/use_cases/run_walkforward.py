"""RunWalkForward use case (SPEC M3/D1).

Runs a strategy across out-of-sample date windows and collects per-fold metrics.
We do NOT optimize parameters here (the spec forbids tuning on the test set); the
folds are honest out-of-sample evaluations. Default folds: train 2022-2024,
validate 2025+ (the "train" fold is reported too, for reference, never for tuning).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tsys.application.dto import BacktestConfig, FoldResult, WalkForwardReport
from tsys.application.ports import BacktestEngine
from tsys.domain.entities import Candle
from tsys.domain.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class Fold:
    label: str
    start: datetime
    end: datetime


def default_folds() -> list[Fold]:
    """SPEC default: train 2022-2024 (in-sample), validate 2025+ (out-of-sample)."""
    return [
        Fold("train_2022_2024", datetime(2022, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
        Fold("validate_2025+", datetime(2025, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)),
    ]


class RunWalkForward:
    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    def run(
        self,
        strategy: Strategy[Any],
        candles: Sequence[Candle],
        config: BacktestConfig,
        folds: Sequence[Fold] | None = None,
    ) -> WalkForwardReport:
        folds = folds or default_folds()
        report = WalkForwardReport(strategy=getattr(strategy, "name", strategy.__class__.__name__))
        for fold in folds:
            window = [c for c in candles if fold.start <= c.ts < fold.end]
            result = self._engine.run(strategy, window, config)
            report.folds.append(FoldResult(fold.label, fold.start, fold.end, result))
        return report
