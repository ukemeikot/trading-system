"""CcxtHistory -> HistoricalDataSource (crypto, Binance by default).

ccxt is imported lazily so importing this module (and the whole adapter layer)
does not require ccxt to be installed — tests inject a fake client. Public OHLCV
needs no API keys.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from tsys.adapters.feeds.normalize import candle_from_ccxt
from tsys.domain.entities import Candle
from tsys.domain.values import Pair

# milliseconds per timeframe unit
_TF_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class _OHLCVClient(Protocol):
    """The slice of a ccxt exchange we depend on (keeps us testable)."""

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None, limit: int | None
    ) -> list[list[float]]: ...


class CcxtHistory:
    """Implements the HistoricalDataSource port (structural — see ports.py)."""

    def __init__(
        self,
        client: _OHLCVClient | None = None,
        exchange_id: str = "binance",
        page_limit: int = 1000,
    ) -> None:
        self._client = client if client is not None else _make_exchange(exchange_id)
        self._page_limit = page_limit

    def fetch_candles(
        self, pair: Pair, timeframe: str, start: datetime, end: datetime
    ) -> Sequence[Candle]:
        if timeframe not in _TF_MS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        step = _TF_MS[timeframe]
        since = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        out: list[Candle] = []
        while since <= end_ms:
            rows = self._client.fetch_ohlcv(pair.symbol, timeframe, since, self._page_limit)
            if not rows:
                break
            for row in rows:
                ts_ms = int(row[0])
                if ts_ms > end_ms:
                    return out
                out.append(candle_from_ccxt(row, pair, timeframe))
            last_ts = int(rows[-1][0])
            next_since = last_ts + step
            if next_since <= since:  # no forward progress -> avoid infinite loop
                break
            since = next_since
        return out


def _make_exchange(exchange_id: str) -> Any:
    import ccxt  # lazy: only needed for real downloads

    exchange_cls = getattr(ccxt, exchange_id)
    return exchange_cls({"enableRateLimit": True})
