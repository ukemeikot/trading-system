"""OandaHistory -> HistoricalDataSource (forex, OANDA v20 practice).

oandapyV20 is imported lazily. If credentials are absent, construction fails with
a clear error and the caller skips forex (SPEC B1/M2: forex degrades gracefully,
crypto still runs). Tests inject a fake client.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from tsys.adapters.feeds.normalize import candle_from_oanda
from tsys.domain.entities import Candle
from tsys.domain.values import Pair

# domain timeframe -> OANDA granularity code
_GRANULARITY: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
}


class _OandaClient(Protocol):
    def candles(self, instrument: str, params: dict[str, object]) -> dict[str, object]: ...


class OandaHistory:
    """Implements the HistoricalDataSource port (structural)."""

    def __init__(self, client: _OandaClient, page_count: int = 5000) -> None:
        self._client = client
        self._page_count = page_count

    def fetch_candles(
        self, pair: Pair, timeframe: str, start: datetime, end: datetime
    ) -> Sequence[Candle]:
        if timeframe not in _GRANULARITY:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        instrument = f"{pair.base}_{pair.quote}"  # OANDA uses e.g. GBP_USD
        params = {
            "granularity": _GRANULARITY[timeframe],
            "from": start.isoformat(),
            "to": end.isoformat(),
            "price": "M",  # midpoint candles
            "count": self._page_count,
        }
        payload = self._client.candles(instrument, params)
        raw = payload.get("candles", []) if isinstance(payload, dict) else []
        out: list[Candle] = []
        for c in raw:
            if not c.get("complete", True):  # skip the still-forming candle (no lookahead)
                continue
            out.append(candle_from_oanda(c, pair, timeframe))
        return out


def make_oanda_client(access_token: str, environment: str = "practice") -> _OandaClient:
    """Build a real OANDA v20 client (lazy import). Only called when creds are present."""
    from oandapyV20 import API
    from oandapyV20.endpoints import instruments as _instruments

    api = API(access_token=access_token, environment=environment)

    class _Client:
        def candles(self, instrument: str, params: dict[str, object]) -> dict[str, object]:
            req = _instruments.InstrumentsCandles(instrument=instrument, params=params)
            api.request(req)
            return dict(req.response)

    return _Client()
