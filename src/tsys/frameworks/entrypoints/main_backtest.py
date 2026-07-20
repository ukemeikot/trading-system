"""Entrypoint: run a single backtest (SPEC M3).

    python -m tsys.frameworks.entrypoints.main_backtest --strategy buy_and_hold \
        --pair BTC/USDT --market crypto --timeframe 1h
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from tsys.adapters.backtest.engine_adapter import EventDrivenBacktestEngine
from tsys.adapters.persistence.parquet_store import ParquetCandleStore
from tsys.application.dto import BacktestConfig
from tsys.application.use_cases.run_backtest import RunBacktest
from tsys.domain.sizing import NotionalBounds
from tsys.domain.values import Market, Pair
from tsys.frameworks.config import (
    AppSettings,
    build_cost_config,
    build_risk_limits,
    load_settings,
)
from tsys.frameworks.registry import available, build_strategy
from tsys.frameworks.reporting import format_backtest


def build_config(
    settings: AppSettings, equity: float, risk_pct: float | None, slip_mult: float
) -> BacktestConfig:
    rp = risk_pct if risk_pct is not None else settings.risk.risk_per_trade_pct
    return BacktestConfig(
        initial_equity=Decimal(str(equity)),
        risk_pct=Decimal(str(rp)),
        costs=build_cost_config(settings),
        risk_limits=build_risk_limits(settings),
        bounds=NotionalBounds(min_notional=Decimal("10")),
        slippage_multiplier=Decimal(str(slip_mult)),
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Run a backtest.")
    p.add_argument("--strategy", required=True, help=f"one of: {', '.join(available())}")
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--market", default="crypto", choices=["crypto", "forex"])
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--equity", type=float, default=100.0)
    p.add_argument("--risk-pct", type=float, default=None)
    p.add_argument("--slippage-mult", type=float, default=1.0)
    p.add_argument("--config", default="config/settings.yaml")
    args = p.parse_args()

    settings = load_settings(args.config)
    pair = Pair.parse(args.pair, Market(args.market))
    candles = list(ParquetCandleStore().read(pair, args.timeframe))
    if not candles:
        print(
            f"No candles for {pair.symbol} {args.timeframe}. Run main_download first "
            "(or check the pair/timeframe)."
        )
        return

    strategy = build_strategy(args.strategy)
    config = build_config(settings, args.equity, args.risk_pct, args.slippage_mult)
    result = RunBacktest(EventDrivenBacktestEngine()).run(strategy, candles, config)
    print(format_backtest(result, title=f"{args.strategy} {pair.symbol} {args.timeframe}"))


if __name__ == "__main__":
    main()
