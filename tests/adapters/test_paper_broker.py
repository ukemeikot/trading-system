"""PaperBroker — fills via the shared CostModel; MTM equity; restart-recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tsys.adapters.brokers.paper import PaperBroker
from tsys.domain.costs import CostConfig, CostModel, CryptoCosts, ForexPairCosts
from tsys.domain.entities import Order, OrderType, Position
from tsys.domain.values import Market, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)
TS = datetime(2024, 1, 1, tzinfo=UTC)


def _model() -> CostModel:
    return CostModel(CostConfig(
        crypto=CryptoCosts(Decimal("0.10"), Decimal("0.02"), Decimal("0.05")),
        forex={"GBP/USD": ForexPairCosts(spread_pips=Decimal("1.8"))},
    ))


def _order(side: Side, ot: OrderType = OrderType.MARKET, reduce_only: bool = False) -> Order:
    return Order(ts=TS, pair=BTC, side=side, quantity=1.0, order_type=ot,
                 stop_price=95.0, reduce_only=reduce_only)


async def test_round_trip_zero_move_loses_exactly_costs() -> None:
    b = PaperBroker(_model(), Decimal("1000"))
    b.mark(BTC, 100.0)
    entry = await b.submit(_order(Side.BUY))
    assert entry is not None and entry.price > 100  # taker slippage up
    b.mark(BTC, 100.0)
    await b.submit(_order(Side.SELL, reduce_only=True))
    # matches CostModel.round_trip total cost of 0.30 on this config
    assert abs(await b.equity() - 999.70) < 1e-9


async def test_maker_entry_has_no_slippage() -> None:
    b = PaperBroker(_model(), Decimal("1000"))
    b.mark(BTC, 100.0)
    fill = await b.submit(_order(Side.BUY, OrderType.POST_ONLY))
    assert fill is not None and fill.price == 100.0  # maker: no slippage


async def test_equity_marks_to_market_open_position() -> None:
    b = PaperBroker(_model(), Decimal("1000"))
    b.mark(BTC, 100.0)
    await b.submit(_order(Side.BUY, OrderType.POST_ONLY))  # entry at 100, maker fee 0.02
    b.mark(BTC, 110.0)
    # cash = 1000 - 0.02; unrealized = (110-100)*1 = 10
    assert abs(await b.equity() - (1000 - 0.02 + 10)) < 1e-9


async def test_submit_without_mark_raises() -> None:
    b = PaperBroker(_model(), Decimal("1000"))
    with pytest.raises(RuntimeError, match="mark"):
        await b.submit(_order(Side.BUY))


async def test_reduce_only_without_position_returns_none() -> None:
    b = PaperBroker(_model(), Decimal("1000"))
    b.mark(BTC, 100.0)
    assert await b.submit(_order(Side.SELL, reduce_only=True)) is None


async def test_restore_position_then_equity() -> None:
    b = PaperBroker(_model(), Decimal("1000"))
    b.restore_position(Position(pair=BTC, side=Side.BUY, quantity=2.0, entry_price=100.0,
                               stop_price=95.0, opened_at=TS))
    b.mark(BTC, 105.0)
    positions = await b.open_positions()
    assert len(positions) == 1 and positions[0].quantity == 2.0
    assert abs(await b.equity() - (1000 + (105 - 100) * 2)) < 1e-9
