"""RunBacktest use case (SPEC M3).

Thin orchestration over the BacktestEngine port: load candles (optionally from the
CandleRepository) and run the pure strategy through the engine with the shared
CostModel. All the real work is in the engine; this keeps the composition simple.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tsys.application.dto import BacktestConfig, BacktestResult
from tsys.application.ports import BacktestEngine, CandleRepository
from tsys.domain.entities import Candle
from tsys.domain.strategies.base import Strategy
from tsys.domain.values import Pair


class RunBacktest:
    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    def run(
        self, strategy: Strategy[Any], candles: Sequence[Candle], config: BacktestConfig
    ) -> BacktestResult:
        return self._engine.run(strategy, candles, config)

    def run_from_repo(
        self,
        strategy: Strategy[Any],
        repo: CandleRepository,
        pair: Pair,
        timeframe: str,
        config: BacktestConfig,
    ) -> BacktestResult:
        return self._engine.run(strategy, list(repo.read(pair, timeframe)), config)
