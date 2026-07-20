"""End-to-end paper engine via replay (SPEC M5 demo/exit criteria), no network.

Covers: a recorded day replayed through the identical StreamAndTrade path fills
the DB (fills, equity, decisions incl. vetoes, latency); a forced drawdown trips
the kill switch (flatten + halt); restart-recovery of an open position from the
DB; and the daily report's latency p50/p99.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tsys.adapters.brokers.paper import PaperBroker
from tsys.adapters.clock import SimulatedClock
from tsys.adapters.feeds.replay_feed import ReplayFeed
from tsys.adapters.persistence.sqlite_repo import SqliteLatencyRecorder, SqliteTradeRepository
from tsys.application.risk_manager import RiskManager
from tsys.application.use_cases.daily_report import GenerateDailyReport
from tsys.application.use_cases.replay_session import ReplaySession
from tsys.application.use_cases.stream_and_trade import StreamAndTrade
from tsys.domain.costs import CostConfig, CostModel, CryptoCosts, ForexPairCosts
from tsys.domain.entities import Candle, Position, Signal, SignalKind
from tsys.domain.risk import RiskLimits, RiskPolicy
from tsys.domain.sizing import NotionalBounds, PositionSizer
from tsys.domain.values import Direction, Market, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)
T0 = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)


def _cost() -> CostModel:
    return CostModel(CostConfig(
        crypto=CryptoCosts(Decimal("0.10"), Decimal("0.02"), Decimal("0.05")),
        forex={"GBP/USD": ForexPairCosts(spread_pips=Decimal("1.8"))},
    ))


def _candle(i: int, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(ts=T0 + timedelta(minutes=i), pair=BTC, timeframe="1m",
                  open=o, high=h, low=low, close=c, volume=10.0)


@dataclass(slots=True)
class _S:
    i: int = 0


class EnterThenExit:
    """Enter long on candle 1, exit on candle 3."""

    name = "scripted"

    def __init__(self, stop_frac: float = 0.9) -> None:
        self._stop_frac = stop_frac

    def initial_state(self) -> _S:
        return _S()

    def on_candle(self, candle: Candle, state: _S) -> tuple[Signal | None, _S]:
        state.i += 1
        if state.i == 1:
            sig = Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                         direction=Direction.LONG, stop_price=candle.close * self._stop_frac)
            return sig, state
        if state.i == 3:
            return Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                          direction=Direction.LONG), state
        return None, state


def _engine(candles: list[Candle], strategy: object, tmp_path: Path,
            equity: str = "1000", min_notional: str = "10",
            risk_pct: str = "1"):  # type: ignore[no-untyped-def]
    repo = SqliteTradeRepository(tmp_path / "e2e.sqlite")
    clock = SimulatedClock(T0)
    broker = PaperBroker(_cost(), Decimal(equity))
    risk = RiskManager(RiskPolicy(RiskLimits()), Decimal(equity))
    sizer = PositionSizer(NotionalBounds(min_notional=Decimal(min_notional)))
    latency = SqliteLatencyRecorder(repo, clock)
    engine = StreamAndTrade(ReplayFeed(candles), strategy, broker, risk, sizer, repo, latency,
                            clock, "1m", risk_pct=Decimal(risk_pct))
    return engine, repo, broker


async def test_replay_fills_the_decision_log(tmp_path: Path) -> None:
    candles = [_candle(i, 100, 100.5, 99.5, 100) for i in range(5)]
    engine, repo, _ = _engine(candles, EnterThenExit(), tmp_path)
    result = await ReplaySession(engine).run()

    assert result.candles == 5
    assert result.fills == 1                     # one entry
    assert repo.count_fills("2024-01-02") == 2   # entry + exit fills persisted
    kinds = repo.count_decisions_by_kind("2024-01-02")
    assert kinds.get("fill", 0) == 1 and kinds.get("exit", 0) == 1
    assert repo.last_equity() is not None        # equity curve written
    assert repo.latency_samples("2024-01-02")    # latency recorded


async def test_kill_switch_flattens_and_halts(tmp_path: Path) -> None:
    # Enter at 100 with a tight stop and a full-equity position, then gap down hard:
    # the mark-to-market drawdown from the high-water mark trips the kill switch.
    candles = [
        _candle(0, 100, 100, 100, 100),   # enter here (stop = 90)
        _candle(1, 60, 61, 59, 60),       # -40% gap -> deep drawdown
        _candle(2, 60, 60, 60, 60),
    ]

    class EnterOnce:
        name = "enter_once"

        def initial_state(self) -> _S:
            return _S()

        def on_candle(self, candle: Candle, state: _S) -> tuple[Signal | None, _S]:
            state.i += 1
            if state.i == 1:
                return Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                              direction=Direction.LONG, stop_price=90.0), state
            return None, state

    # risk 10% + stop distance 10 -> qty 1, notional 100 (full equity), no clamp
    engine, repo, broker = _engine(candles, EnterOnce(), tmp_path, equity="100",
                                   min_notional="10", risk_pct="10")
    result = await engine.run()
    assert result.halted
    assert repo.count_decisions_by_kind("2024-01-02").get("halt", 0) >= 1
    assert await broker.open_positions() == []  # flattened


async def test_restart_recovery_of_open_position(tmp_path: Path) -> None:
    repo = SqliteTradeRepository(tmp_path / "e2e.sqlite")
    # a position exists ONLY in the DB (as if from a previous run)
    await repo.upsert_position(Position(pair=BTC, side=Side.BUY, quantity=1.0, entry_price=100.0,
                                        stop_price=95.0, opened_at=T0))
    repo.close()

    # feed a candle that trips the recovered stop -> it must be managed and closed
    candles = [_candle(0, 100, 100, 90, 92)]  # low 90 <= stop 95

    class Noop:
        name = "noop"

        def initial_state(self) -> _S:
            return _S()

        def on_candle(self, candle: Candle, state: _S) -> tuple[Signal | None, _S]:
            return None, state

    engine, repo2, broker = _engine(candles, Noop(), tmp_path)
    await engine.run()
    assert repo2.count_fills("2024-01-02") == 1                 # the recovered stop exit filled
    assert await repo2.load_open_positions() == []             # snapshot cleared


async def test_daily_report_latency_percentiles(tmp_path: Path) -> None:
    candles = [_candle(i, 100, 100.5, 99.5, 100) for i in range(5)]
    engine, repo, _ = _engine(candles, EnterThenExit(), tmp_path)
    await engine.run()
    report = GenerateDailyReport(repo).run("2024-01-02")
    assert report.fills == 2
    assert "tick_to_signal" in report.latency
    p50, p99 = report.latency["tick_to_signal"]
    assert p99 >= p50 >= 0.0
