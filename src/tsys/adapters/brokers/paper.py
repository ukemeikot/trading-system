"""PaperBroker — simulates fills against live prices with the shared CostModel.

The broker is the ledger: it applies fees/slippage (via the same domain CostModel
the backtester uses — SPEC B4.3) and tracks cash + one open position, exposing
mark-to-market equity for the risk manager. The engine controls *timing and price*
by marking the broker before each submit; the broker just executes at that mark.
Single position at a time (matches the strategies' one-position constraint).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from tsys.application.ports import Broker
from tsys.domain.costs import CostModel, Liquidity
from tsys.domain.entities import Fill, Order, OrderType, Position
from tsys.domain.values import Pair, Side


def _d(x: float | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


@dataclass(slots=True)
class _BrokerPos:
    pair: Pair
    side: Side
    quantity: Decimal
    entry_fill: float
    stop_price: float
    opened_ts: object


class PaperBroker(Broker):
    def __init__(
        self, cost_model: CostModel, starting_cash: Decimal, currency: str = "USD"
    ) -> None:
        self._cost = cost_model
        self._cash = starting_cash
        self._currency = currency
        self._pos: _BrokerPos | None = None
        self._marks: dict[str, float] = {}

    # -- price marking (adapter-specific; the engine drives this) ----------
    def mark(self, pair: Pair, price: float) -> None:
        self._marks[pair.symbol] = price

    @property
    def cash(self) -> Decimal:
        return self._cash

    # -- Broker port ------------------------------------------------------
    async def submit(self, order: Order) -> Fill | None:
        mark = self._marks.get(order.pair.symbol)
        if mark is None:
            raise RuntimeError(f"no mark price set for {order.pair.symbol}; call mark() first")
        liquidity = (
            Liquidity.MAKER
            if order.order_type in (OrderType.LIMIT, OrderType.POST_ONLY)
            else Liquidity.TAKER
        )
        fill_px = float(self._cost.fill_price(mark, order.side, order.pair, liquidity))
        qty = _d(order.quantity)
        fee = self._cost.fee(_d(fill_px) * qty, order.pair, liquidity).amount

        if order.reduce_only:
            pos = self._pos
            if pos is None:
                return None
            pnl = Decimal(pos.side.sign) * (_d(fill_px) - _d(pos.entry_fill)) * pos.quantity
            self._cash += pnl - fee
            self._pos = None
        else:
            self._cash -= fee
            self._pos = _BrokerPos(
                pair=order.pair, side=order.side, quantity=qty, entry_fill=fill_px,
                stop_price=order.stop_price if order.stop_price is not None else 0.0,
                opened_ts=order.ts,
            )
        return Fill(
            ts=order.ts, pair=order.pair, side=order.side, quantity=float(qty),
            price=fill_px, fee=float(fee), order_client_id=order.client_id,
        )

    async def open_positions(self) -> Sequence[Position]:
        if self._pos is None:
            return []
        p = self._pos
        return [
            Position(pair=p.pair, side=p.side, quantity=float(p.quantity), entry_price=p.entry_fill,
                     stop_price=p.stop_price, opened_at=p.opened_ts)  # type: ignore[arg-type]
        ]

    async def equity(self) -> float:
        """Mark-to-market equity = cash + unrealized PnL of the open position."""
        eq = self._cash
        if self._pos is not None:
            mark = self._marks.get(self._pos.pair.symbol)
            if mark is not None:
                eq += Decimal(self._pos.side.sign) * (_d(mark) - _d(self._pos.entry_fill)) \
                    * self._pos.quantity
        return float(eq)

    def restore_position(self, position: Position) -> None:
        """Restart-recovery: re-open a position loaded from the repository (SPEC M5)."""
        self._pos = _BrokerPos(
            pair=position.pair, side=position.side, quantity=_d(position.quantity),
            entry_fill=position.entry_price, stop_price=position.stop_price,
            opened_ts=position.opened_at,
        )
