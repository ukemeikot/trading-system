"""SQLite range queries + parameter-freeze audit (SPEC M6)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tsys.adapters.persistence.sqlite_repo import SqliteTradeRepository
from tsys.domain.entities import Fill
from tsys.domain.values import Market, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)


def _repo(tmp_path: Path) -> SqliteTradeRepository:
    return SqliteTradeRepository(tmp_path / "m6.sqlite")


async def test_range_queries_respect_bounds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    in_range = datetime(2026, 7, 3, 10, tzinfo=UTC)
    out_range = datetime(2026, 7, 20, 10, tzinfo=UTC)
    for ts in (in_range, out_range):
        await repo.record_fill(Fill(ts=ts, pair=BTC, side=Side.BUY, quantity=1, price=1, fee=0))
        await repo.record_equity(ts, 100.0)
    await repo.record_decision({"ts": in_range.isoformat(), "kind": "veto", "reason": "x"})
    await repo.record_decision(
        {"ts": in_range.isoformat(), "kind": "exit", "reason": "volatility spike halt"}
    )

    start, end = "2026-07-01", "2026-07-08"  # excludes the 2026-07-20 rows
    assert repo.fills_between(start, end) == 1
    assert repo.kind_counts_between(start, end).get("veto") == 1
    assert repo.exit_reason_counts_between(start, end).get("volatility spike halt") == 1
    assert len(repo.equity_between(start, end)) == 1


async def test_param_fingerprint_audit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert repo.last_param_hash() is None
    repo.record_run("2026-07-01T00:00:00+00:00", "abc123")
    repo.record_run("2026-07-08T00:00:00+00:00", "def456")
    assert repo.last_param_hash() == "def456"  # most recent
