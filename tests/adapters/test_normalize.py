"""Boundary normalization — crypto and forex must produce an identical Candle schema."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

from tsys.adapters.feeds.normalize import candle_from_ccxt, candle_from_twelvedata
from tsys.domain.entities import Candle
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)
GBP = Pair("GBP", "USD", Market.FOREX)

# 2024-01-02T00:00:00Z in ms
CCXT_ROW = [1704153600000, 42000.0, 42100.5, 41950.0, 42050.25, 12.5]
TD_VALUE = {
    "datetime": "2024-01-02 08:00:00",
    "open": "1.2700",
    "high": "1.2725",
    "low": "1.2690",
    "close": "1.2710",
}


def test_ccxt_row_to_candle() -> None:
    c = candle_from_ccxt(CCXT_ROW, BTC, "1m")
    assert c.ts == datetime(2024, 1, 2, 0, 0, tzinfo=UTC)
    assert (c.open, c.high, c.low, c.close, c.volume) == (42000.0, 42100.5, 41950.0, 42050.25, 12.5)
    assert c.pair is BTC and c.timeframe == "1m"


def test_twelvedata_value_to_candle() -> None:
    c = candle_from_twelvedata(TD_VALUE, GBP, "1h")
    assert c.ts == datetime(2024, 1, 2, 8, 0, tzinfo=UTC)
    assert (c.open, c.high, c.low, c.close) == (1.27, 1.2725, 1.269, 1.271)
    assert c.volume == 0.0  # forex is spread-priced; no meaningful volume
    assert c.pair is GBP and c.timeframe == "1h"


def test_identical_schema_across_markets() -> None:
    """Exit criterion: normalization proves an identical schema across markets."""
    crypto = candle_from_ccxt(CCXT_ROW, BTC, "1m")
    forex = candle_from_twelvedata(TD_VALUE, GBP, "1h")
    assert type(crypto) is Candle and type(forex) is Candle
    # Same fields, same runtime types for every field.
    names = [f.name for f in fields(Candle)]
    assert [type(getattr(crypto, n)) for n in names] == [type(getattr(forex, n)) for n in names]


def test_twelvedata_daily_bar_date_only() -> None:
    c = candle_from_twelvedata({**TD_VALUE, "datetime": "2024-03-10"}, GBP, "1d")
    assert c.ts == datetime(2024, 3, 10, 0, 0, tzinfo=UTC)
