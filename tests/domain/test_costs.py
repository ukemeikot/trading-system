"""CostModel — exact cost arithmetic, including the F1 round-trip property test."""

from __future__ import annotations

from decimal import Decimal

from tsys.domain.costs import (
    CostConfig,
    CostModel,
    CryptoCosts,
    ForexPairCosts,
    Liquidity,
)
from tsys.domain.values import Market, Money, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)
GBP = Pair("GBP", "USD", Market.FOREX)


def _model() -> CostModel:
    return CostModel(
        CostConfig(
            crypto=CryptoCosts(
                taker_fee_pct=Decimal("0.10"),
                maker_fee_pct=Decimal("0.02"),
                slippage_pct=Decimal("0.05"),
            ),
            forex={"GBP/USD": ForexPairCosts(spread_pips=Decimal("1.8"))},
        )
    )


def test_crypto_round_trip_taker_exact() -> None:
    rt = _model().round_trip(price=100, quantity=1, pair=BTC)
    # slippage 0.05% each side -> price cost 0.10; fees 0.10005 + 0.09995 = 0.20
    assert rt.price_cost == Decimal("0.10")
    assert rt.fee_cost == Decimal("0.20000")
    assert rt.total_cost == Money(Decimal("0.30000"), "USDT")


def test_f1_property_zero_move_round_trip_loses_exactly_costs() -> None:
    """F1: equity after a zero-move round trip = start - (fees + spread + slippage), exactly."""
    model = _model()
    start = Money(Decimal("100"), "USDT")
    rt = model.round_trip(price=100, quantity=1, pair=BTC)
    end = start + Money(rt.net_pnl_at_zero_move, "USDT")
    assert end == Money(Decimal("99.70000"), "USDT")


def test_maker_entry_has_no_slippage() -> None:
    model = _model()
    taker = model.fill_price(100, Side.BUY, BTC, Liquidity.TAKER)
    maker = model.fill_price(100, Side.BUY, BTC, Liquidity.MAKER)
    assert maker == Decimal("100")
    assert taker > maker


def test_forex_round_trip_is_full_spread() -> None:
    rt = _model().round_trip(price=Decimal("1.3000"), quantity=10000, pair=GBP)
    # 1.8 pips * 0.0001 * 10000 units = 1.8 quote; zero commission.
    assert rt.fee_cost == Decimal("0")
    assert rt.price_cost == Decimal("1.8000")


def test_forex_has_no_commission() -> None:
    fee = _model().fee(Decimal("13000"), GBP, Liquidity.TAKER)
    assert fee == Money(Decimal("0"), "USD")
