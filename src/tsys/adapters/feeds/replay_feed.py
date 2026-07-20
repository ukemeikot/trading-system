"""ReplayFeed -> MarketDataFeed (SPEC M5 --replay).

Replays recorded candles through the *identical* live StreamAndTrade code path, so
a recorded day can be re-run deterministically with no network. Filters to the
requested timeframe.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from tsys.application.ports import MarketDataFeed
from tsys.domain.entities import Candle, Tick


class ReplayFeed(MarketDataFeed):
    def __init__(self, candles: Sequence[Candle]) -> None:
        self._candles = list(candles)

    async def stream_candles(self, timeframe: str) -> AsyncIterator[Candle]:
        for candle in self._candles:
            if candle.timeframe == timeframe:
                yield candle

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        return
        yield  # pragma: no cover - makes this an (empty) async generator
