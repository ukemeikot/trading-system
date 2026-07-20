"""ParquetCandleStore — CandleRepository backed by Parquet files (SPEC B3).

Layout: data/parquet/{market}/{base}-{quote}/{tf}.parquet
Schema is identical across markets (the normalization guarantee): a fixed column
set with the timestamp stored as UTC epoch milliseconds for portability.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from tsys.application.ports import CandleRepository
from tsys.domain.entities import Candle
from tsys.domain.values import Pair

COLUMNS = ["ts_ms", "open", "high", "low", "close", "volume"]


class ParquetCandleStore(CandleRepository):
    def __init__(self, base_dir: str | Path = "data/parquet") -> None:
        self._base = Path(base_dir)

    def path_for(self, pair: Pair, timeframe: str) -> Path:
        return self._base / pair.market.value / f"{pair.base}-{pair.quote}" / f"{timeframe}.parquet"

    def write(self, pair: Pair, timeframe: str, candles: Sequence[Candle]) -> int:
        path = self.path_for(pair, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            {
                "ts_ms": [int(c.ts.timestamp() * 1000) for c in candles],
                "open": [c.open for c in candles],
                "high": [c.high for c in candles],
                "low": [c.low for c in candles],
                "close": [c.close for c in candles],
                "volume": [c.volume for c in candles],
            },
            columns=COLUMNS,
        )
        df.to_parquet(path, engine="pyarrow", index=False)
        return len(df)

    def read(self, pair: Pair, timeframe: str) -> Sequence[Candle]:
        path = self.path_for(pair, timeframe)
        if not path.exists():
            return []
        df = pd.read_parquet(path, engine="pyarrow")
        return [
            Candle(
                ts=datetime.fromtimestamp(int(row.ts_ms) / 1000.0, tz=UTC),
                pair=pair,
                timeframe=timeframe,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in df.itertuples(index=False)
        ]

    def has(self, pair: Pair, timeframe: str) -> bool:
        return self.path_for(pair, timeframe).exists()
