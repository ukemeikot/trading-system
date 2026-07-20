"""Entities: Candle, Tick, Signal, Order, Fill, Position, NewsEvent.

Pure — stdlib only. Every entity is JSON-serializable for the decision log
(see B4.4); use `to_dict()` where a serializable form is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from tsys.domain.values import BlackoutWindow, Direction, Impact, Pair, Side


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"  # maker-only entry (SPEC D2.4/D2.5)


class SignalKind(StrEnum):
    ENTER = "enter"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class Candle:
    """A closed OHLCV candle. Strategies only ever see *closed* candles (no lookahead)."""

    ts: datetime  # candle open time, UTC, tz-aware
    pair: Pair
    timeframe: str  # e.g. "1m", "1h", "4h"
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Candle.ts must be timezone-aware (UTC)")


@dataclass(frozen=True, slots=True)
class Tick:
    """A best-bid/ask quote."""

    ts: datetime
    pair: Pair
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's intent. Pure output of on_candle(); carries the stop the risk
    manager will enforce (stop-less entries are rejected — C2)."""

    ts: datetime
    pair: Pair
    kind: SignalKind
    direction: Direction
    stop_price: float | None = None
    target_price: float | None = None
    reason: str = ""
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Order:
    """A proposed or placed order."""

    ts: datetime
    pair: Pair
    side: Side
    quantity: float
    order_type: OrderType
    stop_price: float | None = None  # required for entries (risk manager enforces)
    limit_price: float | None = None
    reduce_only: bool = False
    client_id: str = ""


@dataclass(frozen=True, slots=True)
class Fill:
    """A (partial or full) execution of an order."""

    ts: datetime
    pair: Pair
    side: Side
    quantity: float
    price: float
    fee: float = 0.0  # in quote currency
    order_client_id: str = ""


@dataclass(slots=True)
class Position:
    """An open position. Mutable (quantity/stop can change over its life)."""

    pair: Pair
    side: Side
    quantity: float
    entry_price: float
    stop_price: float
    opened_at: datetime

    @property
    def notional(self) -> float:
        return abs(self.quantity) * self.entry_price

    def unrealized_pnl(self, mark_price: float) -> float:
        return self.side.sign * (mark_price - self.entry_price) * abs(self.quantity)


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """A scheduled high-impact economic event (SPEC D2.3)."""

    ts: datetime  # event time T, UTC
    country: str
    title: str
    impact: Impact

    def blackout(
        self,
        pre_entry_block: timedelta = timedelta(minutes=30),
        force_flat: timedelta = timedelta(minutes=10),
        reentry_after: timedelta = timedelta(minutes=45),
    ) -> BlackoutWindow:
        """Build the [T-30, T+45] blackout with a T-10 force-flat boundary."""
        return BlackoutWindow(
            start=self.ts - pre_entry_block,
            force_flat_by=self.ts - force_flat,
            end=self.ts + reentry_after,
            reason=f"{self.country} {self.title}",
        )
