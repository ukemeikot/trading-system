"""Entrypoint: live paper trading, and --replay of a recorded day (SPEC M5).

Composition root. Refuses to start unless mode is 'paper' (F4). Live crypto uses a
reconnecting ccxt feed; --replay drives the identical StreamAndTrade path from
stored Parquet candles with a SimulatedClock.

    python -m tsys.frameworks.entrypoints.main_paper --strategy quiet_scalper \
        --pair BTC/USDT --market crypto --timeframe 1m
    python -m tsys.frameworks.entrypoints.main_paper --strategy quiet_scalper --replay \
        --pair BTC/USDT --timeframe 1m
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from tsys.adapters.brokers.paper import PaperBroker
from tsys.adapters.calendar.csv_source import CsvCalendarSource
from tsys.adapters.clock import SimulatedClock, SystemClock
from tsys.adapters.feeds.ccxt_feed import CcxtFeed
from tsys.adapters.feeds.reconnect import ReconnectingFeed
from tsys.adapters.feeds.replay_feed import ReplayFeed
from tsys.adapters.persistence.parquet_store import ParquetCandleStore
from tsys.adapters.persistence.sqlite_repo import SqliteLatencyRecorder, SqliteTradeRepository
from tsys.application.ports import Clock, MarketDataFeed
from tsys.application.risk_manager import RiskManager
from tsys.application.use_cases.daily_report import GenerateDailyReport
from tsys.application.use_cases.replay_session import ReplaySession
from tsys.application.use_cases.stream_and_trade import StreamAndTrade
from tsys.domain.costs import CostModel
from tsys.domain.risk import RiskPolicy
from tsys.domain.sizing import NotionalBounds, PositionSizer
from tsys.domain.values import Market, Pair
from tsys.frameworks.config import (
    build_cost_config,
    build_risk_limits,
    ensure_paper_mode,
    load_settings,
    load_strategies,
    param_fingerprint,
)
from tsys.frameworks.registry import available, build_strategy
from tsys.frameworks.reporting import format_daily_report


def main() -> None:
    p = argparse.ArgumentParser(description="Paper trading (live or --replay).")
    p.add_argument("--strategy", required=True, help=f"one of: {', '.join(available())}")
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--market", default="crypto", choices=["crypto", "forex"])
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--equity", type=float, default=100.0)
    p.add_argument("--replay", action="store_true", help="replay stored candles instead of live")
    p.add_argument("--db", default="data/tsys.sqlite")
    p.add_argument("--config", default="config/settings.yaml")
    args = p.parse_args()

    settings = load_settings(args.config)
    ensure_paper_mode(settings)  # refuse to start if mode: live (F4)
    market = Market(args.market)
    pair = Pair.parse(args.pair, market)

    cost = CostModel(build_cost_config(settings))
    broker = PaperBroker(cost, starting_cash=Decimal(str(args.equity)))
    risk = RiskManager(RiskPolicy(build_risk_limits(settings)), Decimal(str(args.equity)))
    sizer = PositionSizer(NotionalBounds(min_notional=Decimal("10")))
    repo = SqliteTradeRepository(args.db)
    strategies_cfg = load_strategies()
    news = list(CsvCalendarSource(settings.calendar.path).load_events())
    strategy = build_strategy(args.strategy, strategies_cfg, market=market, news_events=news)

    feed: MarketDataFeed
    clock: Clock
    day: str
    if args.replay:
        candles = list(ParquetCandleStore().read(pair, args.timeframe))
        if not candles:
            print(f"No candles for {pair.symbol} {args.timeframe}. Run main_download first.")
            return
        feed = ReplayFeed(candles)
        clock = SimulatedClock(candles[0].ts)
        day = candles[0].ts.date().isoformat()
    else:
        clock = SystemClock()
        feed = ReconnectingFeed(lambda: CcxtFeed(pair))
        day = clock.now().date().isoformat()

    # Parameter-freeze guard (SPEC M6): a changed fingerprint resets the observation clock.
    fingerprint = param_fingerprint(settings, strategies_cfg)
    previous = repo.last_param_hash()
    if previous is not None and previous != fingerprint:
        print("WARNING: risk/cost/strategy parameters changed since the last run -> the M6 "
              "observation clock resets to week zero (do not change parameters mid-run).")
    repo.record_run(clock.now().isoformat(), fingerprint)

    latency = SqliteLatencyRecorder(repo, clock)
    engine = StreamAndTrade(
        feed, strategy, broker, risk, sizer, repo, latency, clock, args.timeframe,
        risk_pct=Decimal(str(settings.risk.risk_per_trade_pct)),
    )
    runner = ReplaySession(engine) if args.replay else engine
    result = asyncio.run(runner.run())
    print(f"processed {result.candles} candles: {result.fills} fills, "
          f"{result.vetoes} vetoes, halted={result.halted}")
    print(format_daily_report(GenerateDailyReport(repo).run(day)))
    repo.close()


if __name__ == "__main__":
    main()
