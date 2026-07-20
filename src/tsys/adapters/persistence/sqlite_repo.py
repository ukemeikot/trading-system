"""SqliteTradeRepository + SqliteLatencyRecorder (SPEC M5).

Uses stdlib sqlite3 (no extra dependency). The port methods are async to fit the
event loop; the underlying writes are quick synchronous SQLite calls, which is
appropriate for a low-rate paper system (aiosqlite could drop in later). Every
fill, decision (incl. vetoes), equity point and latency sample is persisted so
the run is fully reconstructable — debugging a trading system without a decision
log is impossible (B4.4).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from tsys.application.ports import Clock, LatencyRecorder, TradeRepository
from tsys.domain.entities import Fill, Position
from tsys.domain.values import Market, Pair, Side

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


class SqliteTradeRepository(TradeRepository):
    def __init__(self, path: str | Path = "data/tsys.sqlite") -> None:
        p = Path(path)
        if p.parent and str(p.parent) not in ("", "."):
            p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- TradeRepository port ---------------------------------------------
    async def record_fill(self, fill: Fill) -> None:
        self._conn.execute(
            "INSERT INTO fills(ts,pair,side,quantity,price,fee,order_client_id) "
            "VALUES(?,?,?,?,?,?,?)",
            (fill.ts.isoformat(), fill.pair.symbol, fill.side.value, fill.quantity,
             fill.price, fill.fee, fill.order_client_id),
        )
        self._conn.commit()

    async def record_decision(self, decision: dict[str, object]) -> None:
        d = dict(decision)
        ts = str(d.pop("ts", ""))
        kind = str(d.pop("kind", "signal"))
        pair = d.pop("pair", None)
        approved = d.pop("approved", None)
        reason = str(d.pop("reason", ""))
        self._conn.execute(
            "INSERT INTO decisions(ts,kind,pair,approved,reason,detail) VALUES(?,?,?,?,?,?)",
            (ts, kind, pair, (None if approved is None else int(bool(approved))), reason,
             json.dumps(d, default=str)),
        )
        self._conn.commit()

    async def record_equity(self, ts: datetime, equity: float) -> None:
        self._conn.execute(
            "INSERT INTO equity(ts,equity) VALUES(?,?)", (ts.isoformat(), equity)
        )
        self._conn.commit()

    async def load_open_positions(self) -> Sequence[Position]:
        rows = self._conn.execute("SELECT * FROM positions").fetchall()
        return [
            Position(
                pair=Pair.parse(r["pair"], Market(r["market"])), side=Side(r["side"]),
                quantity=r["quantity"], entry_price=r["entry_price"], stop_price=r["stop_price"],
                opened_at=datetime.fromisoformat(r["opened_at"]),
            )
            for r in rows
        ]

    # -- position snapshot (restart-recovery) -----------------------------
    async def upsert_position(self, position: Position) -> None:
        self._conn.execute(
            "INSERT INTO positions(pair,market,side,quantity,entry_price,stop_price,opened_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(pair) DO UPDATE SET "
            "market=excluded.market,side=excluded.side,quantity=excluded.quantity,"
            "entry_price=excluded.entry_price,stop_price=excluded.stop_price,"
            "opened_at=excluded.opened_at",
            (position.pair.symbol, position.pair.market.value, position.side.value,
             position.quantity, position.entry_price, position.stop_price,
             position.opened_at.isoformat()),
        )
        self._conn.commit()

    async def clear_position(self, pair: Pair) -> None:
        self._conn.execute("DELETE FROM positions WHERE pair=?", (pair.symbol,))
        self._conn.commit()

    # -- reporting queries ------------------------------------------------
    def count_decisions_by_kind(self, day: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) c FROM decisions WHERE ts LIKE ? GROUP BY kind", (f"{day}%",)
        ).fetchall()
        return {r["kind"]: r["c"] for r in rows}

    def count_fills(self, day: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) c FROM fills WHERE ts LIKE ?", (f"{day}%",)
        ).fetchone()
        return int(row["c"])

    def latency_samples(self, day: str) -> dict[str, list[float]]:
        rows = self._conn.execute(
            "SELECT stage, micros FROM latency WHERE ts LIKE ?", (f"{day}%",)
        ).fetchall()
        out: dict[str, list[float]] = {}
        for r in rows:
            out.setdefault(r["stage"], []).append(r["micros"])
        return out

    def last_equity(self) -> float | None:
        row = self._conn.execute("SELECT equity FROM equity ORDER BY id DESC LIMIT 1").fetchone()
        return None if row is None else float(row["equity"])


class SqliteLatencyRecorder(LatencyRecorder):
    """Writes latency samples to the same DB the repository owns (UTC ts via Clock)."""

    def __init__(self, repo: SqliteTradeRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def record(self, stage: str, micros: float) -> None:
        self._repo._conn.execute(  # noqa: SLF001 (same package, intentional)
            "INSERT INTO latency(ts,stage,micros) VALUES(?,?,?)",
            (self._clock.now().isoformat(), stage, micros),
        )
        self._repo._conn.commit()
