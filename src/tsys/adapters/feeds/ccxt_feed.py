"""CcxtFeed -> MarketDataFeed (live crypto candles, SPEC M5).

Polls closed OHLCV candles via ccxt and yields each newly-closed candle exactly
once. ccxt is imported lazily (network-only; tests use ReplayFeed). Wrap this in
ReconnectingFeed for backoff/reconnect. ccxt.pro's watch_ohlcv could replace the
poll loop later; polling keeps the dependency surface minimal and is ample for
1m+ candles where network round-trip dominates latency (SPEC F3).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from tsys.adapters.feeds.normalize import candle_from_ccxt
from tsys.application.ports import MarketDataFeed
from tsys.domain.entities import Candle, Tick
from tsys.domain.values import Pair

_TF_SECONDS: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
}


class CcxtFeed(MarketDataFeed):
    def __init__(
        self, pair: Pair, client: Any | None = None, exchange_id: str = "binance",
        poll_seconds: float | None = None,
    ) -> None:
        self._pair = pair
        self._client = client if client is not None else _make_exchange(exchange_id)
        self._poll = poll_seconds

    async def stream_candles(self, timeframe: str) -> AsyncIterator[Candle]:
        if timeframe not in _TF_SECONDS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        poll = self._poll if self._poll is not None else max(2.0, _TF_SECONDS[timeframe] / 4.0)
        last_ts_ms = 0
        while True:
            rows = await asyncio.to_thread(
                self._client.fetch_ohlcv, self._pair.symbol, timeframe, None, 2
            )
            # the last row is the still-forming candle; the one before it is closed.
            if len(rows) >= 2:
                closed = rows[-2]
                ts_ms = int(closed[0])
                if ts_ms > last_ts_ms:
                    last_ts_ms = ts_ms
                    yield candle_from_ccxt(closed, self._pair, timeframe)
            await asyncio.sleep(poll)

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        return
        yield  # pragma: no cover


def _make_exchange(exchange_id: str) -> Any:
    import ccxt  # lazy: network only

    return getattr(ccxt, exchange_id)({"enableRateLimit": True})
