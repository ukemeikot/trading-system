"""LiveBrokerStub — the paper-only guardrail (SPEC ground rules).

Live order routing is deliberately NOT implemented. This stub exists so the
Broker port has a 'live' shape, but every method raises. No code path here can
transmit a real order. Live mode requires the SPEC F2 gates + a written go-decision.
"""

from __future__ import annotations

from collections.abc import Sequence

from tsys.application.ports import Broker
from tsys.domain.entities import Fill, Order, Position

_MESSAGE = (
    "Live trading is not implemented. This system is paper-only until the gates in "
    "docs/SPEC.md Part F2 are passed and a live path is deliberately built (M7)."
)


class LiveBrokerStub(Broker):
    async def submit(self, order: Order) -> Fill | None:
        raise NotImplementedError(_MESSAGE)

    async def open_positions(self) -> Sequence[Position]:
        raise NotImplementedError(_MESSAGE)

    async def equity(self) -> float:
        raise NotImplementedError(_MESSAGE)
