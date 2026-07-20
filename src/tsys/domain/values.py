"""Value objects: Money, Pair, Market (enum), Side, BlackoutWindow.

Pure — stdlib only. Money uses Decimal for exact cost arithmetic (see F1: the
round-trip cost property test must hold *exactly*).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Market(StrEnum):
    """The two markets this system trades. Downstream code is market-agnostic
    except the cost model (per-market fee/spread config)."""

    CRYPTO = "crypto"
    FOREX = "forex"


class Side(StrEnum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        """+1 for BUY, -1 for SELL."""
        return 1 if self is Side.BUY else -1


class Direction(StrEnum):
    """Signal direction (a strategy's intent)."""

    LONG = "long"
    SHORT = "short"

    @property
    def entry_side(self) -> Side:
        return Side.BUY if self is Direction.LONG else Side.SELL


class Impact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Pair:
    """A tradable instrument, e.g. Pair('BTC', 'USDT', Market.CRYPTO)."""

    base: str
    quote: str
    market: Market

    @property
    def symbol(self) -> str:
        return f"{self.base}/{self.quote}"

    @classmethod
    def parse(cls, symbol: str, market: Market) -> Pair:
        base, _, quote = symbol.partition("/")
        if not base or not quote:
            raise ValueError(f"invalid pair symbol: {symbol!r}")
        return cls(base=base, quote=quote, market=market)

    def __str__(self) -> str:
        return self.symbol


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary amount. Arithmetic stays in Decimal so cost math is exact."""

    amount: Decimal
    currency: str = "USD"

    @classmethod
    def of(cls, amount: Decimal | int | str | float, currency: str = "USD") -> Money:
        # float goes through str() to avoid binary-float noise.
        return cls(Decimal(str(amount)), currency)

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        return Money(self.amount * Decimal(factor), self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


@dataclass(frozen=True, slots=True)
class BlackoutWindow:
    """A time window during which new entries are refused / positions force-flat.

    See SPEC D2.3: derived from a NewsEvent as [T-30, T+45] with a force-flat
    boundary at T-10.
    """

    start: datetime  # earliest time new entries are blocked (T-30)
    force_flat_by: datetime  # open positions must be flat before this (T-10)
    end: datetime  # earliest re-entry (T+45)
    reason: str = ""

    def blocks_entry(self, ts: datetime) -> bool:
        return self.start <= ts < self.end

    def requires_flat(self, ts: datetime) -> bool:
        return self.force_flat_by <= ts < self.end
