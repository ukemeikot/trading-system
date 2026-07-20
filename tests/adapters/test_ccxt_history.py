"""CcxtHistory pagination against a fake OHLCV client (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from tsys.adapters.feeds.ccxt_history import CcxtHistory
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)
MIN_MS = 60_000


class FakeExchange:
    """Serves 1m candles from an in-memory series, paginating like ccxt."""

    def __init__(self, start_ms: int, count: int) -> None:
        self._rows = [
            [start_ms + i * MIN_MS, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1.0]
            for i in range(count)
        ]
        self.calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None, limit: int | None
    ) -> list[list[float]]:
        self.calls += 1
        s = since or 0
        page = [r for r in self._rows if r[0] >= s]
        return page[: (limit or 1000)]


def test_paginates_and_normalizes() -> None:
    start_ms = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    fake = FakeExchange(start_ms, count=2500)  # > page_limit to force pagination
    hist = CcxtHistory(client=fake, page_limit=1000)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 3, tzinfo=UTC)
    candles = hist.fetch_candles(BTC, "1m", start, end)
    assert len(candles) == 2500
    assert fake.calls >= 3  # 2500 / 1000 -> at least 3 pages
    # strictly increasing, all within range, right pair/timeframe
    ts = [c.ts for c in candles]
    assert ts == sorted(ts)
    assert all(start <= c.ts <= end for c in candles)
    assert all(c.pair is BTC and c.timeframe == "1m" for c in candles)


def test_stops_at_end_bound() -> None:
    start_ms = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    fake = FakeExchange(start_ms, count=100)
    hist = CcxtHistory(client=fake, page_limit=1000)
    candles = hist.fetch_candles(
        BTC, "1m", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, 0, 9, tzinfo=UTC)
    )
    assert len(candles) == 10  # minutes 0..9 inclusive
