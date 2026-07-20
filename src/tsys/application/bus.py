"""A minimal asyncio event bus (SPEC B4.1: event-driven, not polling).

Events are domain objects; the bus is an application orchestration detail.
Handlers are async and are dispatched by the event's concrete type. Kept
deliberately tiny — one process, in-memory. Full pub/sub tests land in M2.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable

Handler = Callable[[object], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: object) -> None:
        """Dispatch to every handler registered for the event's exact type, in
        subscription order. Handlers run sequentially so ordering is deterministic
        (SPEC F1 determinism requirement)."""
        for handler in self._handlers.get(type(event), ()):
            await handler(event)

    def handler_count(self, event_type: type) -> int:
        return len(self._handlers.get(event_type, ()))
