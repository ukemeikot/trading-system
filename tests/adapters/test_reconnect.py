"""ReconnectingFeed — resumes with backoff after the stream raises (SPEC M5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from tsys.adapters.feeds.reconnect import ReconnectingFeed
from tsys.application.ports import MarketDataFeed
from tsys.domain.entities import Candle, Tick
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)


def _candles(n: int) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [Candle(ts=start + timedelta(minutes=i), pair=BTC, timeframe="1m",
                   open=100, high=100, low=100, close=100, volume=1) for i in range(n)]


class FlakyFeed(MarketDataFeed):
    """Yields from a shared cursor; raises once after `break_at` on the first pass."""

    def __init__(self, candles: list[Candle], state: dict) -> None:
        self._candles = candles
        self._state = state

    async def stream_candles(self, timeframe: str) -> AsyncIterator[Candle]:
        while self._state["i"] < len(self._candles):
            i = self._state["i"]
            if i == self._state["break_at"] and not self._state["broke"]:
                self._state["broke"] = True
                raise ConnectionError("network cable pulled")
            self._state["i"] = i + 1
            yield self._candles[i]

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        return
        yield


async def test_reconnects_and_delivers_all_candles() -> None:
    candles = _candles(6)
    shared = {"i": 0, "break_at": 3, "broke": False}
    slept: list[float] = []

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    feed = ReconnectingFeed(lambda: FlakyFeed(candles, shared), base_delay=1.0, sleep=fake_sleep)
    got = [c async for c in feed.stream_candles("1m")]
    assert len(got) == 6  # all delivered despite the mid-stream failure
    assert slept  # backoff was applied at least once


async def test_gives_up_after_max_retries() -> None:
    async def fake_sleep(d: float) -> None:
        pass

    class AlwaysFails(MarketDataFeed):
        async def stream_candles(self, timeframe: str) -> AsyncIterator[Candle]:
            raise ConnectionError("down")
            yield  # pragma: no cover

        async def stream_ticks(self) -> AsyncIterator[Tick]:
            return
            yield

    feed = ReconnectingFeed(lambda: AlwaysFails(), max_retries=2, sleep=fake_sleep)
    import pytest
    with pytest.raises(ConnectionError):
        _ = [c async for c in feed.stream_candles("1m")]
