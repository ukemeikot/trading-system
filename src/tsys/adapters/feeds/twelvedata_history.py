"""TwelveDataHistory -> HistoricalDataSource (forex, GBP/USD).

Twelve Data is a key-only data API (no brokerage KYC) — chosen because OANDA does
not accept Nigerian accounts and, since the system is paper-only, forex needs only
a data feed. HTTP uses stdlib urllib (no extra dependency); tests inject a fake
`fetch` so no network is hit. Pages forward by advancing the start cursor.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from tsys.adapters.feeds.normalize import candle_from_twelvedata
from tsys.domain.entities import Candle
from tsys.domain.values import Pair

# domain timeframe -> Twelve Data interval code
_INTERVAL: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
}
_STEP_MIN: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}

_BASE_URL = "https://api.twelvedata.com/time_series"

# A fetch takes the query params and returns the decoded JSON payload.
Fetch = Callable[[dict[str, str]], dict]


class TwelveDataHistory:
    """Implements the HistoricalDataSource port (structural)."""

    def __init__(self, api_key: str, fetch: Fetch | None = None, page_size: int = 5000) -> None:
        self._key = api_key
        self._fetch = fetch or _http_get
        self._page = page_size

    def fetch_candles(
        self, pair: Pair, timeframe: str, start: datetime, end: datetime
    ) -> Sequence[Candle]:
        if timeframe not in _INTERVAL:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        step = timedelta(minutes=_STEP_MIN[timeframe])
        out: list[Candle] = []
        cursor = start
        while cursor <= end:
            params = {
                "symbol": pair.symbol,
                "interval": _INTERVAL[timeframe],
                "start_date": cursor.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
                "outputsize": str(self._page),
                "order": "ASC",
                "timezone": "UTC",
                "apikey": self._key,
            }
            payload = self._fetch(params)
            values = payload.get("values") or []
            if not values:
                break
            for v in values:
                candle = candle_from_twelvedata(v, pair, timeframe)
                if candle.ts > end:
                    return out
                out.append(candle)
            nxt = out[-1].ts + step
            if nxt <= cursor:  # no forward progress -> stop
                break
            cursor = nxt
        return out


def _http_get(params: dict[str, str]) -> dict:
    url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (fixed https host)
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error: {data.get('message')}")
    return data if isinstance(data, dict) else {}
