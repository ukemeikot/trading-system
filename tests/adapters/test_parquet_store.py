"""ParquetCandleStore round-trip + path layout."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tsys.adapters.persistence.parquet_store import ParquetCandleStore
from tsys.domain.entities import Candle
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)
GBP = Pair("GBP", "USD", Market.FOREX)


def _candles(pair: Pair, tf: str, n: int) -> list[Candle]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Candle(
            ts=base.replace(minute=i),
            pair=pair,
            timeframe=tf,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1.0 + i,
        )
        for i in range(n)
    ]


def test_write_read_round_trip(tmp_path: Path) -> None:
    store = ParquetCandleStore(tmp_path)
    candles = _candles(BTC, "1m", 5)
    assert not store.has(BTC, "1m")
    written = store.write(BTC, "1m", candles)
    assert written == 5
    assert store.has(BTC, "1m")
    loaded = store.read(BTC, "1m")
    assert list(loaded) == candles


def test_path_layout(tmp_path: Path) -> None:
    store = ParquetCandleStore(tmp_path)
    p = store.path_for(GBP, "4h")
    assert p == tmp_path / "forex" / "GBP-USD" / "4h.parquet"


def test_read_missing_returns_empty(tmp_path: Path) -> None:
    store = ParquetCandleStore(tmp_path)
    assert list(store.read(BTC, "1h")) == []


def test_schema_identical_across_markets(tmp_path: Path) -> None:
    store = ParquetCandleStore(tmp_path)
    store.write(BTC, "1m", _candles(BTC, "1m", 3))
    store.write(GBP, "1m", _candles(GBP, "1m", 3))
    import pandas as pd

    crypto_cols = list(pd.read_parquet(store.path_for(BTC, "1m")).columns)
    forex_cols = list(pd.read_parquet(store.path_for(GBP, "1m")).columns)
    assert crypto_cols == forex_cols
