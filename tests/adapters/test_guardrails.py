"""Adapter guardrails: the live broker is a stub that can never route an order,
and the clocks behave."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tsys.adapters.brokers.live_stub import LiveBrokerStub
from tsys.adapters.clock import SimulatedClock, SystemClock
from tsys.domain.entities import Order, OrderType
from tsys.domain.values import Market, Pair, Side


@pytest.mark.asyncio
async def test_live_broker_stub_refuses_to_submit() -> None:
    order = Order(
        ts=datetime(2025, 1, 1, tzinfo=UTC),
        pair=Pair("BTC", "USDT", Market.CRYPTO),
        side=Side.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
        stop_price=95.0,
    )
    with pytest.raises(NotImplementedError, match="paper-only"):
        await LiveBrokerStub().submit(order)


def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_simulated_clock_is_injected() -> None:
    t = datetime(2025, 1, 1, 12, tzinfo=UTC)
    clk = SimulatedClock(t)
    assert clk.now() == t
    clk.set(datetime(2025, 1, 2, tzinfo=UTC))
    assert clk.now() == datetime(2025, 1, 2, tzinfo=UTC)


def test_simulated_clock_requires_tzaware() -> None:
    with pytest.raises(ValueError):
        SimulatedClock(datetime(2025, 1, 1))
