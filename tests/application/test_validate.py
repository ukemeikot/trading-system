"""RunValidation battery — criteria are computed and honestly reported."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tsys.adapters.backtest.engine_adapter import EventDrivenBacktestEngine
from tsys.application.dto import BacktestConfig
from tsys.application.use_cases.validate import RunValidation
from tsys.domain.costs import CostConfig, CryptoCosts, ForexPairCosts
from tsys.domain.entities import Candle
from tsys.domain.risk import RiskLimits
from tsys.domain.sizing import NotionalBounds
from tsys.domain.strategies.meanrev import MeanRev
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


def _oscillating(n: int) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    out = []
    for i in range(n):
        base = 100 + (5 if i % 6 < 3 else -5)  # forces RSI extremes for meanrev
        out.append(Candle(ts=start + timedelta(hours=i), pair=BTC, timeframe="1h",
                          open=base, high=base + 1, low=base - 1, close=base, volume=10))
    return out


def test_validation_report_has_all_core_criteria() -> None:
    def build(news_on: bool, regime_on: bool) -> MeanRev:
        return MeanRev(rsi_period=3, atr_period=3)

    report = RunValidation(EventDrivenBacktestEngine()).run(
        "meanrev", build, _oscillating(120), _config(), min_trades=100,
    )
    names = {c.name for c in report.criteria}
    assert {"min_trades", "cost_drag_<=_40%", "survives_2x_slippage"} <= names
    # report is always produced, pass or fail — evidence, not a green number.
    assert isinstance(report.passed_all, bool)
    assert report.baseline.trade_count >= 0


def test_min_trades_criterion_fails_on_small_sample() -> None:
    def build(news_on: bool, regime_on: bool) -> MeanRev:
        return MeanRev(rsi_period=3, atr_period=3)

    report = RunValidation(EventDrivenBacktestEngine()).run(
        "meanrev", build, _oscillating(30), _config(), min_trades=100,
    )
    min_trades = next(c for c in report.criteria if c.name == "min_trades")
    assert not min_trades.passed  # 30 candles cannot yield 100 trades


def test_ablation_criteria_included_when_requested() -> None:
    def build(news_on: bool, regime_on: bool) -> MeanRev:
        return MeanRev(rsi_period=3, atr_period=3)

    report = RunValidation(EventDrivenBacktestEngine()).run(
        "meanrev", build, _oscillating(60), _config(), min_trades=100, include_ablation=True,
    )
    names = {c.name for c in report.criteria}
    assert "news_filter_reduces_tail" in names
    assert "regime_filter_reduces_tail" in names


def test_dual_fee_run_present_when_alt_config_given() -> None:
    def build(news_on: bool, regime_on: bool) -> MeanRev:
        return MeanRev(rsi_period=3, atr_period=3)

    alt = CostConfig(
        crypto=CryptoCosts(Decimal("0.02"), Decimal("0.00"), Decimal("0.02")),
        forex={"GBP/USD": ForexPairCosts(spread_pips=Decimal("1.8"))},
    )
    report = RunValidation(EventDrivenBacktestEngine()).run(
        "meanrev", build, _oscillating(120), _config(), min_trades=100, alt_fee_config=alt,
    )
    assert report.alt_fee is not None
