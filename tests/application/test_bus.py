"""Event bus pub/sub."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tsys.application.bus import EventBus


@dataclass
class Ping:
    n: int


@dataclass
class Pong:
    n: int


@pytest.mark.asyncio
async def test_publish_dispatches_to_matching_type() -> None:
    bus = EventBus()
    seen: list[int] = []

    async def on_ping(e: object) -> None:
        assert isinstance(e, Ping)
        seen.append(e.n)

    bus.subscribe(Ping, on_ping)
    await bus.publish(Ping(1))
    await bus.publish(Pong(2))  # no handler; ignored
    await bus.publish(Ping(3))
    assert seen == [1, 3]


@pytest.mark.asyncio
async def test_handlers_run_in_subscription_order() -> None:
    bus = EventBus()
    order: list[str] = []

    async def first(_: object) -> None:
        order.append("a")

    async def second(_: object) -> None:
        order.append("b")

    bus.subscribe(Ping, first)
    bus.subscribe(Ping, second)
    await bus.publish(Ping(0))
    assert order == ["a", "b"]
