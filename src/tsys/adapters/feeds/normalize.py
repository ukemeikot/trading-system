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


def candle_from_oanda(candle: dict, pair: Pair, timeframe: str) -> Candle:
    """OANDA v20 candle dict -> Candle.

    OANDA shape: {"time": "2024-01-02T08:00:00.000000000Z", "volume": 123,
                  "mid": {"o": "1.2", "h": "1.3", "l": "1.1", "c": "1.25"}}.
    We read mid prices (bid/ask spread is modeled by the CostModel, not baked in).
    """
    ohlc = candle["mid"]
    return Candle(
        ts=_parse_oanda_time(candle["time"]),
        pair=pair,
        timeframe=timeframe,
        open=float(ohlc["o"]),
        high=float(ohlc["h"]),
        low=float(ohlc["l"]),
        close=float(ohlc["c"]),
        volume=float(candle["volume"]),
    )


def _parse_oanda_time(raw: str) -> datetime:
    """OANDA RFC3339 timestamps carry nanosecond precision; Python parses up to
    microseconds, so truncate the fractional part to 6 digits."""
    s = raw.replace("Z", "+00:00")
    if "." in s:
        head, _, tail = s.partition(".")
        frac, _, tz = tail.partition("+")
        s = f"{head}.{frac[:6]}+{tz}" if tz else f"{head}.{frac[:6]}"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
