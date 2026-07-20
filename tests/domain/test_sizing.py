"""PositionSizer — fixed-fractional math and the $100-account min-notional floor."""

from __future__ import annotations

from decimal import Decimal

from tsys.domain.sizing import NotionalBounds, PositionSizer
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)


def test_fixed_fractional_quantity() -> None:
    sizer = PositionSizer(NotionalBounds(min_notional=Decimal("10")))
    # equity 1000, risk 1% -> $10 risk; stop distance $50 -> qty 0.2; notional 0.2*100=20
    r = sizer.size(equity=1000, risk_pct=1, entry_price=100, stop_distance=50, pair=BTC)
    assert r.ok
    assert r.quantity == Decimal("0.2")
    assert r.notional == Decimal("20")
    assert not r.clamped


def test_stop_less_order_rejected() -> None:
    sizer = PositionSizer(NotionalBounds(min_notional=Decimal("10")))
    r = sizer.size(equity=1000, risk_pct=1, entry_price=100, stop_distance=0, pair=BTC)
    assert not r.ok
    assert "stop-less" in r.reason


def test_small_account_clamps_to_min_notional() -> None:
    # $100 account, 0.75% risk = $0.75; tiny stop would size below min notional.
    sizer = PositionSizer(
        NotionalBounds(min_notional=Decimal("10")), max_risk_multiple=Decimal(100)
    )
    # risk 0.75, stop 50 -> qty 0.015, notional 1.5 (< min 10) -> clamp up to 10.
    r = sizer.size(equity=100, risk_pct=0.75, entry_price=100, stop_distance=50, pair=BTC)
    assert r.clamped
    assert r.notional == Decimal("10")
    assert r.quantity == Decimal("0.1")


def test_clamp_that_blows_risk_budget_is_rejected() -> None:
    # A min notional far above the risk-implied size pushes realized risk past the guard.
    sizer = PositionSizer(
        NotionalBounds(min_notional=Decimal("1000")), max_risk_multiple=Decimal(2)
    )
    r = sizer.size(equity=100, risk_pct=0.75, entry_price=100, stop_distance=5, pair=BTC)
    assert not r.ok
    assert "risk" in r.reason.lower()


def test_qty_step_rounds_down() -> None:
    sizer = PositionSizer(
        NotionalBounds(min_notional=Decimal("1"), qty_step=Decimal("0.001"))
    )
    r = sizer.size(equity=1000, risk_pct=1, entry_price=100, stop_distance=33, pair=BTC)
    # raw qty = 10/33 = 0.30303...; floored to 0.001 step -> 0.303
    assert r.quantity == Decimal("0.303")
