"""Entrypoint: walk-forward evaluation (SPEC M3), and in M4 the validation battery.

    python -m tsys.frameworks.entrypoints.main_walkforward --strategy buy_and_hold \
        --pair BTC/USDT --market crypto --timeframe 1h
"""

from __future__ import annotations

import argparse

from tsys.adapters.backtest.engine_adapter import EventDrivenBacktestEngine
from tsys.adapters.persistence.parquet_store import ParquetCandleStore
from tsys.application.use_cases.run_walkforward import RunWalkForward
from tsys.domain.values import Market, Pair
from tsys.frameworks.config import load_settings
from tsys.frameworks.entrypoints.main_backtest import build_config
from tsys.frameworks.registry import available, build_strategy
from tsys.frameworks.reporting import format_walkforward


def main() -> None:
    p = argparse.ArgumentParser(description="Run walk-forward evaluation.")
    p.add_argument("--strategy", required=True, help=f"one of: {', '.join(available())}")
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--market", default="crypto", choices=["crypto", "forex"])
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--equity", type=float, default=100.0)
    p.add_argument("--config", default="config/settings.yaml")
    args = p.parse_args()

    settings = load_settings(args.config)
    pair = Pair.parse(args.pair, Market(args.market))
    candles = list(ParquetCandleStore().read(pair, args.timeframe))
    if not candles:
        print(f"No candles for {pair.symbol} {args.timeframe}. Run main_download first.")
        return

    strategy = build_strategy(args.strategy)
    config = build_config(settings, args.equity, None, 1.0)
    report = RunWalkForward(EventDrivenBacktestEngine()).run(strategy, candles, config)
    print(format_walkforward(report))


if __name__ == "__main__":
    main()
