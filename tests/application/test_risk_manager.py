"""RiskManager — HWM, daily-loss halt, kill-switch latch, consecutive-loss."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tsys.application.risk_manager import RiskManager
from tsys.domain.entities import Order, OrderType
from tsys.domain.risk import RiskLimits, RiskPolicy
from tsys.domain.values import Market, Pair, Side

BTC = Pair("BTC", "USDT", Market.CRYPTO)
D1 = datetime(2024, 1, 1, 12, tzinfo=UTC)
D2 = datetime(2024, 1, 2, 12, tzinfo=UTC)


def _rm(equity: str = "1000") -> RiskManager:
    return RiskManager(RiskPolicy(RiskLimits()), Decimal(equity))


def _entry(stop: float | None = 95.0) -> Order:
    return Order(ts=D1, pair=BTC, side=Side.BUY, quantity=1.0, order_type=OrderType.MARKET,
                 stop_price=stop)


def test_valid_entry_approved() -> None:
    rm = _rm()
    rm.mark(Decimal("1000"), D1)
    assert rm.evaluate(_entry(), "BTC/USDT").approved


def test_kill_switch_latches_on_drawdown() -> None:
    rm = _rm()
    rm.mark(Decimal("1000"), D1)  # hwm = 1000
    rm.mark(Decimal("840"), D1)   # -16% drawdown
    halt, reason = rm.check_halt()
    assert halt and "kill switch" in reason
    assert rm.kill_switch_active
    # latched even after recovery
    rm.mark(Decimal("1000"), D1)
    assert rm.check_halt()[0]
    assert not rm.evaluate(_entry(), "BTC/USDT").approved


def test_daily_loss_limit_halts_then_resets_next_day() -> None:
    rm = _rm()
    rm.mark(Decimal("1000"), D1)  # day start 1000
    rm.mark(Decimal("960"), D1)   # -4% on the day
    assert rm.check_halt()[0]
    rm.mark(Decimal("960"), D2)   # new UTC day -> day start resets to 960
    assert not rm.check_halt()[0]


def test_consecutive_losses_block_instrument_for_day() -> None:
    rm = _rm()
    rm.mark(Decimal("1000"), D1)
    for _ in range(3):
        rm.record_close("BTC/USDT", Decimal("-1"))
    d = rm.evaluate(_entry(), "BTC/USDT")
    assert not d.approved and "consecutive losses" in d.reason


def test_a_win_resets_consecutive_losses() -> None:
    rm = _rm()
    rm.mark(Decimal("1000"), D1)
    rm.record_close("BTC/USDT", Decimal("-1"))
    rm.record_close("BTC/USDT", Decimal("-1"))
    rm.record_close("BTC/USDT", Decimal("5"))  # win resets
    rm.record_close("BTC/USDT", Decimal("-1"))
    assert rm.evaluate(_entry(), "BTC/USDT").approved


def test_stop_less_entry_rejected_via_policy() -> None:
    rm = _rm()
    rm.mark(Decimal("1000"), D1)
    assert not rm.evaluate(_entry(stop=None), "BTC/USDT").approved
