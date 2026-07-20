"""TwelveDataHistory pagination against a fake fetch (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tsys.adapters.feeds.twelvedata_history import TwelveDataHistory
from tsys.domain.values import Market, Pair

GBP = Pair("GBP", "USD", Market.FOREX)


class FakeFetch:
    """Serves 1min forex values from an in-memory series, paginating by start_date."""

    def __init__(self, start: datetime, count: int) -> None:
        self._values = [
            {
                "datetime": (start + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
                "open": "1.2700", "high": "1.2705", "low": "1.2695", "close": "1.2702",
            }
            for i in range(count)
        ]
        self.calls = 0

    def __call__(self, params: dict[str, str]) -> dict:
        self.calls += 1
        start = datetime.strptime(params["start_date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        size = int(params["outputsize"])
        page = [
            v for v in self._values
            if datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC) >= start
        ]
        return {"status": "ok", "values": page[:size]}


def test_paginates_and_normalizes() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    fake = FakeFetch(start, count=1200)
    hist = TwelveDataHistory(api_key="x", fetch=fake, page_size=500)
    candles = hist.fetch_candles(GBP, "1m", start, datetime(2024, 1, 2, tzinfo=UTC))
    assert len(candles) == 1200
    assert fake.calls >= 3  # 1200 / 500 -> at least 3 pages
    ts = [c.ts for c in candles]
    assert ts == sorted(ts)
    assert all(c.pair is GBP and c.timeframe == "1m" for c in candles)


def test_stops_at_end_bound() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    fake = FakeFetch(start, count=100)
    hist = TwelveDataHistory(api_key="x", fetch=fake, page_size=500)
    candles = hist.fetch_candles(
        GBP, "1m", start, datetime(2024, 1, 1, 0, 9, tzinfo=UTC)
    )
    assert len(candles) == 10  # minutes 0..9 inclusive
