"""RunValidation — the strategy validation battery (SPEC D2.7 / M4).

Produces trustworthy *evidence*, not a green number: a strategy that FAILS these
criteria still yields a valid report (the M4 deliverable is honest reporting, and
failed strategies are parked, not tuned). Criteria:

  1. min trade count        (>=100 momentum/meanrev, >=300 quiet_scalper)
  2. cost-drag kill         (fails if cost drag > 40% of gross PnL — D2.5)
  3. survives 2x slippage   (net return >= breakeven under doubled slippage — D2.7#4)
  4. news-filter ablation   (filter ON must not worsen the tail vs OFF — D2.7#2)
  5. regime-filter ablation (same, for the regime gate — D2.7#3)
  6. dual fee schedule      (report net under default vs venue fees — D2.5), reported

Ablation uses a builder(news_on, regime_on) so the harness can rebuild the
strategy with a filter disabled. Strategies without those filters skip 4/5.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from tsys.application.dto import BacktestConfig, BacktestResult
from tsys.application.ports import BacktestEngine
from tsys.domain.costs import CostConfig
from tsys.domain.entities import Candle
from tsys.domain.strategies.base import Strategy

StrategyBuilder = Callable[[bool, bool], Strategy[Any]]


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class ValidationReport:
    strategy: str
    baseline: BacktestResult
    criteria: list[Criterion] = field(default_factory=list)
    alt_fee: BacktestResult | None = None  # dual fee-schedule run

    @property
    def passed_all(self) -> bool:
        return all(c.passed for c in self.criteria)


def _worst_trade(result: BacktestResult) -> float:
    """Most negative single-trade net PnL (a proxy for tail loss). 0 if no trades."""
    if not result.trades:
        return 0.0
    return float(min(t.net_pnl for t in result.trades))


class RunValidation:
    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    def run(
        self,
        strategy_name: str,
        build: StrategyBuilder,
        candles: Sequence[Candle],
        config: BacktestConfig,
        min_trades: int,
        include_ablation: bool = False,
        alt_fee_config: CostConfig | None = None,
    ) -> ValidationReport:
        candles = list(candles)
        baseline = self._engine.run(build(True, True), candles, config)
        criteria: list[Criterion] = [
            Criterion(
                "min_trades",
                baseline.trade_count >= min_trades,
                f"{baseline.trade_count} trades (need >= {min_trades})",
            ),
            Criterion(
                "cost_drag_<=_40%",
                baseline.cost_drag_pct <= 40.0,
                f"cost drag {_pct(baseline.cost_drag_pct)} (kill if > 40%)",
            ),
        ]

        stress = self._engine.run(
            build(True, True), candles, replace(config, slippage_multiplier=Decimal(2))
        )
        criteria.append(
            Criterion(
                "survives_2x_slippage",
                stress.net_return_pct >= 0.0,
                f"net {stress.net_return_pct:+.2f}% under 2x slippage (need >= 0)",
            )
        )

        if include_ablation:
            no_news = self._engine.run(build(False, True), candles, config)
            criteria.append(
                Criterion(
                    "news_filter_reduces_tail",
                    _worst_trade(baseline) >= _worst_trade(no_news),
                    f"worst trade on={_worst_trade(baseline):.4f} off={_worst_trade(no_news):.4f}",
                )
            )
            no_regime = self._engine.run(build(True, False), candles, config)
            base_worst, off_worst = _worst_trade(baseline), _worst_trade(no_regime)
            criteria.append(
                Criterion(
                    "regime_filter_reduces_tail",
                    base_worst >= off_worst,
                    f"worst trade on={base_worst:.4f} off={off_worst:.4f}",
                )
            )

        alt = None
        if alt_fee_config is not None:
            alt = self._engine.run(
                build(True, True), candles, replace(config, costs=alt_fee_config)
            )

        return ValidationReport(
            strategy=strategy_name, baseline=baseline, criteria=criteria, alt_fee=alt
        )


def _pct(v: float) -> str:
    return "n/a" if v == float("inf") else f"{v:.1f}%"
