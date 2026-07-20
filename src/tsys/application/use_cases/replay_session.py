"""ReplaySession — run a recorded day through the identical live engine (SPEC M5).

It is a thin marker over StreamAndTrade: replay is NOT a separate code path, it is
the same StreamAndTrade wired with a ReplayFeed and a SimulatedClock. Keeping it a
named use case makes the "identical code path" guarantee explicit.
"""

from __future__ import annotations

from tsys.application.use_cases.stream_and_trade import StreamAndTrade, StreamResult


class ReplaySession:
    def __init__(self, engine: StreamAndTrade) -> None:
        self._engine = engine

    async def run(self) -> StreamResult:
        return await self._engine.run()
