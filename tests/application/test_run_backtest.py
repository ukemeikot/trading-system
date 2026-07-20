"""RunBacktest / RunWalkForward use cases over the real engine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tsys.adapters.backtest.engine_adapter import EventDrivenBacktestEngine
from tsys.application.dto import BacktestConfig
from tsys.application.use_cases.run_backtest import RunBacktest
from tsys.application.use_cases.run_walkforward import Fold, RunWalkForward
from tsys.domain.costs import CostConfig, CryptoCosts, ForexPairCosts
from tsys.domain.entities import Candle
from tsys.domain.risk import RiskLimits
from tsys.domain.sizing import NotionalBounds
from tsys.domain.strategies.baselines import BuyAndHold
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)


def _config() -> BacktestConfig:
    return BacktestConfig(
        initial_equity=Decimal("1000"), risk_pct=Decimal("1"),
        costs=CostConfig(
            crypto=CryptoCosts(Decimal("0.10"), Decimal("0.02"), Decimal("0.05")),
            forex={"GBP/USD": ForexPairCosts(spread_pips=Decimal("1.8"))},
        ),
        risk_limits=RiskLimits(), bounds=NotionalBounds(min_notional=Decimal("10")),
    )


def _candles(start: datetime, n: int) -> list[Candle]:
    return [
        Candle(ts=start + timedelta(hours=i), pair=BTC, timeframe="1h",
               open=100 + i, high=100 + i, low=100 + i, close=100 + i, volume=1)
        for i in range(n)
    ]


class _FakeRepo:
    def __init__(self, candles: Sequence[Candle]) -> None:
        self._candles = candles

    def write(self, pair: Pair, timeframe: str, candles: Sequence[Candle]) -> int:
        return 0

    def read(self, pair: Pair, timeframe: str) -> Sequence[Candle]:
        return self._candles

    def has(self, pair: Pair, timeframe: str) -> bool:
        return True


def test_run_backtest_delegates() -> None:
    uc = RunBacktest(EventDrivenBacktestEngine())
    result = uc.run(BuyAndHold(), _candles(datetime(2024, 1, 1, tzinfo=UTC), 10), _config())
    assert result.trade_count == 1


def test_run_from_repo_reads_candles() -> None:
    repo = _FakeRepo(_candles(datetime(2024, 1, 1, tzinfo=UTC), 10))
    uc = RunBacktest(EventDrivenBacktestEngine())
    result = uc.run_from_repo(BuyAndHold(), repo, BTC, "1h", _config())
    assert result.trade_count == 1


def test_walkforward_splits_by_fold_window() -> None:
    candles = (
        _candles(datetime(2024, 6, 1, tzinfo=UTC), 5)
        + _candles(datetime(2025, 6, 1, tzinfo=UTC), 5)
    )
    report = RunWalkForward(EventDrivenBacktestEngine()).run(BuyAndHold(), candles, _config())
    assert report.strategy == "buy_and_hold"
    labels = [f.label for f in report.folds]
    assert labels == ["train_2022_2024", "validate_2025+"]
    # each fold saw its own 5 candles -> buy&hold makes exactly one trade per fold
    assert all(f.result.trade_count == 1 for f in report.folds)


def test_walkforward_custom_folds() -> None:
    candles = _candles(datetime(2024, 1, 1, tzinfo=UTC), 48)
    folds = [
        Fold("jan", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)),
        Fold("empty", datetime(2030, 1, 1, tzinfo=UTC), datetime(2030, 1, 2, tzinfo=UTC)),
    ]
    report = RunWalkForward(EventDrivenBacktestEngine()).run(
        BuyAndHold(), candles, _config(), folds
    )
    assert report.folds[0].result.trade_count == 1
    assert report.folds[1].result.trade_count == 0  # empty window
