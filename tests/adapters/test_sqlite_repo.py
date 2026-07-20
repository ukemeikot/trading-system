"""SqliteTradeRepository + SqliteLatencyRecorder persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tsys.adapters.clock import SimulatedClock
from tsys.adapters.persistence.sqlite_repo import SqliteLatencyRecorder, SqliteTradeRepository
from tsys.domain.entities import Fill, Position
from tsys.domain.values import Market, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)
TS = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)


def _repo(tmp_path: Path) -> SqliteTradeRepository:
    return SqliteTradeRepository(tmp_path / "t.sqlite")


async def test_record_and_count_fills(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.record_fill(Fill(ts=TS, pair=BTC, side=Side.BUY, quantity=1.0, price=100.0, fee=0.1))
    assert repo.count_fills("2024-01-02") == 1
    assert repo.count_fills("2024-01-03") == 0


async def test_record_decisions_by_kind(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.record_decision({"ts": TS.isoformat(), "kind": "veto", "reason": "x"})
    await repo.record_decision({"ts": TS.isoformat(), "kind": "veto", "reason": "y"})
    await repo.record_decision({"ts": TS.isoformat(), "kind": "halt", "reason": "z"})
    counts = repo.count_decisions_by_kind("2024-01-02")
    assert counts["veto"] == 2 and counts["halt"] == 1


async def test_equity_and_last(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.record_equity(TS, 100.0)
    await repo.record_equity(TS, 101.5)
    assert repo.last_equity() == 101.5


async def test_position_snapshot_roundtrip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    pos = Position(pair=BTC, side=Side.BUY, quantity=0.5, entry_price=100.0, stop_price=95.0,
                   opened_at=TS)
    await repo.upsert_position(pos)
    loaded = await repo.load_open_positions()
    assert len(loaded) == 1
    got = loaded[0]
    assert got.pair.symbol == "BTC/USDT" and got.side is Side.BUY and got.entry_price == 100.0
    await repo.clear_position(BTC)
    assert await repo.load_open_positions() == []


async def test_latency_samples(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rec = SqliteLatencyRecorder(repo, SimulatedClock(TS))
    for v in (10.0, 20.0, 30.0):
        await rec.record("tick_to_signal", v)
    samples = repo.latency_samples("2024-01-02")
    assert sorted(samples["tick_to_signal"]) == [10.0, 20.0, 30.0]
