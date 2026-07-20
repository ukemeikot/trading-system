"""Value objects & entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tsys.domain.entities import Candle, NewsEvent
from tsys.domain.values import BlackoutWindow, Impact, Market, Money, Pair, Side


def test_pair_parse_and_symbol() -> None:
    p = Pair.parse("BTC/USDT", Market.CRYPTO)
    assert p.base == "BTC" and p.quote == "USDT" and p.symbol == "BTC/USDT"


def test_pair_parse_invalid() -> None:
    with pytest.raises(ValueError):
        Pair.parse("BTCUSDT", Market.CRYPTO)


def test_side_helpers() -> None:
    assert Side.BUY.opposite is Side.SELL
    assert Side.BUY.sign == 1 and Side.SELL.sign == -1


def test_money_arithmetic_exact() -> None:
    a = Money.of("0.1")
    b = Money.of("0.2")
    assert (a + b) == Money(Decimal("0.3"))


def test_money_currency_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        Money.of(1, "USD") + Money.of(1, "USDT")


def test_candle_requires_tzaware() -> None:
    with pytest.raises(ValueError):
        Candle(
            ts=datetime(2025, 1, 1),  # naive
            pair=Pair("BTC", "USDT", Market.CRYPTO),
            timeframe="1m",
            open=1, high=2, low=0.5, close=1.5, volume=10,
        )


def test_newsevent_blackout_window() -> None:
    t = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    ev = NewsEvent(ts=t, country="UK", title="BoE Rate Decision", impact=Impact.HIGH)
    w: BlackoutWindow = ev.blackout()
    assert w.start == t - timedelta(minutes=30)
    assert w.force_flat_by == t - timedelta(minutes=10)
    assert w.end == t + timedelta(minutes=45)
    assert w.blocks_entry(t)  # at T, still blocked
    assert not w.blocks_entry(t + timedelta(minutes=46))
    assert w.requires_flat(t - timedelta(minutes=5))
