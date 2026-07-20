"""Ports — the ABCs the adapters implement (SPEC B2, application layer).

These reference only domain types. Adapters (outer layer) provide concrete
implementations; entrypoints inject them. Nothing here imports a third-party
trading library — that quarantine is the whole point of the layering.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tsys.domain.entities import Candle, Fill, NewsEvent, Order, Position, Tick
from tsys.domain.values import Pair

if TYPE_CHECKING:
    from tsys.application.dto import BacktestConfig, BacktestResult
    from tsys.domain.strategies.base import Strategy


class Clock(ABC):
    """Time source. Never call datetime.now() outside a Clock (SPEC B5)."""

    @abstractmethod
    def now(self) -> datetime:
        """Current time, UTC, tz-aware."""


class HistoricalDataSource(ABC):
    """Bulk historical candle fetch (REST). Separate from the live MarketDataFeed:
    downloads are a batch job, streaming is event-driven (M5)."""

    @abstractmethod
    def fetch_candles(
        self, pair: Pair, timeframe: str, start: datetime, end: datetime
    ) -> Sequence[Candle]:
        """Return closed candles in [start, end], oldest first, normalized to domain."""


class CandleRepository(ABC):
    """Persistence for historical candles (Parquet on disk in the default adapter)."""

    @abstractmethod
    def write(self, pair: Pair, timeframe: str, candles: Sequence[Candle]) -> int:
        """Persist candles; return the number of rows written."""

    @abstractmethod
    def read(self, pair: Pair, timeframe: str) -> Sequence[Candle]:
        """Load previously-persisted candles, oldest first."""

    @abstractmethod
    def has(self, pair: Pair, timeframe: str) -> bool:
        """True if any candles are stored for this pair/timeframe."""


class MarketDataFeed(ABC):
    """A source of normalized market data. Implementations normalize to domain
    Candle/Tick at the boundary (normalization lives in adapters, not here)."""

    @abstractmethod
    def stream_candles(self, timeframe: str) -> AsyncIterator[Candle]:
        """Yield closed candles as they arrive."""

    @abstractmethod
    def stream_ticks(self) -> AsyncIterator[Tick]:
        """Yield best bid/ask ticks as they arrive."""


class Broker(ABC):
    """Order routing + position/equity access. PaperBroker and LiveBrokerStub
    implement this. The live path is a stub that raises (paper-only guardrail)."""

    @abstractmethod
    async def submit(self, order: Order) -> Fill | None:
        """Submit an order; return a Fill if it executed, else None (e.g. unfilled limit)."""

    @abstractmethod
    async def open_positions(self) -> Sequence[Position]:
        ...

    @abstractmethod
    async def equity(self) -> float:
        ...


class TradeRepository(ABC):
    """Persistence for fills, positions, equity, and the decision log."""

    @abstractmethod
    async def record_fill(self, fill: Fill) -> None:
        ...

    @abstractmethod
    async def record_decision(self, decision: dict[str, object]) -> None:
        """Append a JSON-serializable decision (incl. risk vetoes) to the decision log."""

    @abstractmethod
    async def record_equity(self, ts: datetime, equity: float) -> None:
        ...

    @abstractmethod
    async def load_open_positions(self) -> Sequence[Position]:
        """For restart-recovery of open paper positions (SPEC M5)."""


class CalendarSource(ABC):
    """Source of scheduled high-impact events."""

    @abstractmethod
    def load_events(self) -> Sequence[NewsEvent]:
        ...

    @abstractmethod
    def is_stale(self, now: datetime) -> bool:
        """True if the calendar is older than its freshness window (SPEC D2.3 failsafe)."""


class Notifier(ABC):
    @abstractmethod
    async def notify(self, message: str) -> None:
        ...


class LatencyRecorder(ABC):
    """Records tick-received -> signal-emitted -> order-submitted samples (SPEC M5)."""

    @abstractmethod
    async def record(self, stage: str, micros: float) -> None:
        ...


class BacktestEngine(ABC):
    """Runs a pure strategy over closed candles with the shared CostModel.

    Quarantined behind a port so a future engine (vectorbt/Rust) can slot in. The
    default adapter is a custom event-driven engine that fills via the SAME
    domain CostModel the PaperBroker uses — so backtest and paper costs cannot
    diverge (SPEC B4.3), and the API is lookahead-impossible by construction."""

    @abstractmethod
    def run(
        self,
        strategy: Strategy[Any],
        candles: Sequence[Candle],
        config: BacktestConfig,
    ) -> BacktestResult:
        ...
