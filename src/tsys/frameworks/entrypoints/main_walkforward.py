"""Entrypoint: walk-forward evaluation + the validation battery (SPEC M3/M4).

    python -m tsys.frameworks.entrypoints.main_walkforward --strategy quiet_scalper \
        --pair BTC/USDT --market crypto --timeframe 1m

For research strategies (momentum/meanrev/quiet_scalper) this prints a walk-forward
report AND the validation battery (D2.7) with pass/fail per criterion. Baselines
print walk-forward only. A failing strategy still produces a valid report — the
deliverable is honest evidence, not a green number.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from tsys.adapters.backtest.engine_adapter import EventDrivenBacktestEngine
from tsys.adapters.calendar.csv_source import CsvCalendarSource
from tsys.adapters.persistence.parquet_store import ParquetCandleStore
from tsys.application.use_cases.run_walkforward import RunWalkForward
from tsys.application.use_cases.validate import RunValidation
from tsys.domain.costs import CostConfig, CryptoCosts, ForexPairCosts
from tsys.domain.values import Market, Pair
from tsys.frameworks.config import load_settings, load_strategies
from tsys.frameworks.entrypoints.main_backtest import build_config
from tsys.frameworks.registry import available, build_strategy
from tsys.frameworks.reporting import format_validation, format_walkforward

_MIN_TRADES = {"momentum": 100, "meanrev": 100, "quiet_scalper": 300}


def _venue_fee_config(base: CostConfig) -> CostConfig:
    """A maker-favourable venue schedule for the dual fee-schedule run (SPEC D2.5)."""
    return CostConfig(
        crypto=CryptoCosts(
            taker_fee_pct=Decimal("0.02"), maker_fee_pct=Decimal("0.00"),
            slippage_pct=Decimal("0.02"),
        ),
        forex={s: ForexPairCosts(spread_pips=fx.spread_pips) for s, fx in base.forex.items()},
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Walk-forward + validation battery.")
    p.add_argument("--strategy", required=True, help=f"one of: {', '.join(available())}")
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--market", default="crypto", choices=["crypto", "forex"])
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--equity", type=float, default=100.0)
    p.add_argument("--config", default="config/settings.yaml")
    args = p.parse_args()

    settings = load_settings(args.config)
    strategies_cfg = load_strategies()
    market = Market(args.market)
    pair = Pair.parse(args.pair, market)
    candles = list(ParquetCandleStore().read(pair, args.timeframe))
    if not candles:
        print(f"No candles for {pair.symbol} {args.timeframe}. Run main_download first.")
        return

    news = list(CsvCalendarSource(settings.calendar.path).load_events())
    config = build_config(settings, args.equity, None, 1.0)
    engine = EventDrivenBacktestEngine()

    def build(news_on: bool, regime_on: bool):  # type: ignore[no-untyped-def]
        return build_strategy(
            args.strategy, strategies_cfg, market=market, news_events=news,
            use_news_filter=news_on, use_regime_filter=regime_on,
        )

    report = RunWalkForward(engine).run(build(True, True), candles, config)
    print(format_walkforward(report))

    if args.strategy in _MIN_TRADES:
        validation = RunValidation(engine).run(
            strategy_name=args.strategy, build=build, candles=candles, config=config,
            min_trades=_MIN_TRADES[args.strategy],
            include_ablation=(args.strategy == "quiet_scalper"),
            alt_fee_config=_venue_fee_config(config.costs),
        )
        print()
        print(format_validation(validation))


if __name__ == "__main__":
    main()
