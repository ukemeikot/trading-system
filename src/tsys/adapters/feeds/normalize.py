"""Boundary normalization — raw exchange payloads -> domain Candle/Tick.

This is where crypto and forex stop looking different. After this function,
nothing downstream knows or cares which market a candle came from (SPEC B4.5).
Normalization lives in the adapter layer, never in domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from tsys.domain.entities import Candle
from tsys.domain.values import Pair


def candle_from_ccxt(row: Sequence[float], pair: Pair, timeframe: str) -> Candle:
    """ccxt OHLCV row -> Candle. ccxt returns [ms_timestamp, o, h, l, c, v]."""
    ts_ms, open_, high, low, close, volume = row
    return Candle(
        ts=datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC),
        pair=pair,
        timeframe=timeframe,
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=float(volume),
    )


def candle_from_twelvedata(value: dict, pair: Pair, timeframe: str) -> Candle:
    """Twelve Data time_series value -> Candle.

    Shape: {"datetime": "2024-01-02 08:00:00", "open": "1.27", "high": "1.28",
            "low": "1.26", "close": "1.275"[, "volume": "0"]}.
    Forex series carry no meaningful volume (spread pricing) -> defaults to 0.0.
    (OANDA was the original spec source but does not accept Nigerian accounts;
    Twelve Data is a key-only data feed, and paper trading needs only data.)
    """
    return Candle(
        ts=_parse_twelvedata_time(value["datetime"]),
        pair=pair,
        timeframe=timeframe,
        open=float(value["open"]),
        high=float(value["high"]),
        low=float(value["low"]),
        close=float(value["close"]),
        volume=float(value.get("volume", 0.0) or 0.0),
    )


def _parse_twelvedata_time(raw: str) -> datetime:
    """Twelve Data timestamps are 'YYYY-MM-DD HH:MM:SS' (UTC when timezone=UTC is
    requested) or a bare date for daily bars."""
    s = raw.strip().replace(" ", "T")
    if "T" not in s:  # daily bar: date only
        s = f"{s}T00:00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
