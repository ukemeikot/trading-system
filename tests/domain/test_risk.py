"""RiskPolicy — pure veto rules (SPEC C2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tsys.domain.entities import Order, OrderType
from tsys.domain.risk import PortfolioState, RiskLimits, RiskPolicy
from tsys.domain.values import Market, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)
TS = datetime(2025, 1, 1, tzinfo=UTC)


def _entry(stop: float | None = 95.0, pair: Pair = BTC) -> Order:
    return Order(
        ts=TS, pair=pair, side=Side.BUY, quantity=1.0, order_type=OrderType.LIMIT, stop_price=stop
    )


def _flat_state(**kw: object) -> PortfolioState:
    base: dict[str, object] = dict(
        equity=Decimal("100"), high_water_mark=Decimal("100"), day_start_equity=Decimal("100")
    )
    base.update(kw)
    return PortfolioState(**base)  # type: ignore[arg-type]


def test_approves_valid_entry() -> None:
    assert RiskPolicy().evaluate(_entry(), _flat_state()).approved


def test_rejects_stop_less_entry() -> None:
    d = RiskPolicy().evaluate(_entry(stop=None), _flat_state())
    assert not d.approved and "stop-less" in d.reason


def test_rejects_when_max_per_pair_reached() -> None:
    d = RiskPolicy().evaluate(_entry(), _flat_state(positions_by_pair={"BTC/USDT": 1}))
    assert not d.approved and "per pair" in d.reason


def test_rejects_when_max_concurrent_reached() -> None:
    limits = RiskLimits(max_concurrent_positions=3, max_positions_per_pair=5)
    d = RiskPolicy(limits).evaluate(_entry(), _flat_state(open_positions=3))
    assert not d.approved and "concurrent" in d.reason


def test_kill_switch_trips_on_drawdown() -> None:
    state = _flat_state(equity=Decimal("84"), high_water_mark=Decimal("100"))
    d = RiskPolicy().evaluate(_entry(), state)
    assert not d.approved and "kill switch" in d.reason


def test_daily_loss_limit_trips() -> None:
    state = _flat_state(day_realized_pnl=Decimal("-3.5"), day_start_equity=Decimal("100"))
    d = RiskPolicy().evaluate(_entry(), state)
    assert not d.approved and "daily loss" in d.reason


def test_exit_allowed_even_when_halted() -> None:
    exit_order = Order(
        ts=TS, pair=BTC, side=Side.SELL, quantity=1.0, order_type=OrderType.MARKET, reduce_only=True
    )
    halted = _flat_state(equity=Decimal("50"), high_water_mark=Decimal("100"))  # kill switch active
    assert RiskPolicy().evaluate(exit_order, halted).approved


def test_determinism_same_inputs_same_decision() -> None:
    policy = RiskPolicy()
    order, state = _entry(), _flat_state()
    first = policy.evaluate(order, state)
    second = policy.evaluate(order, state)
    assert first == second
