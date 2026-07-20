"""ReconnectingFeed -> MarketDataFeed (SPEC M5: reconnect with exponential backoff).

Wraps a feed *factory* and, if the underlying stream raises (dropped WebSocket,
network cable pulled), rebuilds it and retries with exponential backoff up to a
cap. Resets the backoff after any successful progress. The sleep function is
injectable so tests run without real delays.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from tsys.application.ports import MarketDataFeed
from tsys.domain.entities import Candle, Tick

FeedFactory = Callable[[], MarketDataFeed]
Sleep = Callable[[float], Awaitable[None]]


class ReconnectingFeed(MarketDataFeed):
    def __init__(
        self,
        factory: FeedFactory,
        max_retries: int = 8,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        sleep: Sleep | None = None,
    ) -> None:
        self._factory = factory
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._sleep = sleep or asyncio.sleep

    async def stream_candles(self, timeframe: str) -> AsyncIterator[Candle]:
        attempt = 0
        while True:
            feed = self._factory()
            try:
                async for candle in feed.stream_candles(timeframe):
                    attempt = 0  # progress -> reset backoff
                    yield candle
                return  # stream ended cleanly
            except Exception:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
                await self._sleep(delay)

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        attempt = 0
        while True:
            feed = self._factory()
            try:
                async for tick in feed.stream_ticks():
                    attempt = 0
                    yield tick
                return
            except Exception:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
                await self._sleep(delay)
