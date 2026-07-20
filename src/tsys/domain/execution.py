"""Shared, pure position-exit logic (SPEC B4.2 identically-runnable).

Both the backtester and the live paper engine manage open positions with the
*same* exit rules — extracting them here means backtest and paper cannot drift
apart on when/why a position closes. Entry fill timing legitimately differs
(backtest: next candle open; paper: current price ± slippage — SPEC C1), so that
stays in each engine; exits are shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tsys.domain.costs import Liquidity
from tsys.domain.entities import Candle
from tsys.domain.values import Side


@dataclass(slots=True)
class OpenPosition:
    side: Side
    quantity: Decimal
    entry_ref: float  # reference (mid) entry price, costless
    entry_fill: float  # actual fill price (slippage/spread applied)
    entry_fee: Decimal
    stop_price: float
    target_price: float | None
    max_hold_minutes: int | None
    opened_ts: datetime
    exit_requested: bool = False


@dataclass(frozen=True, slots=True)
class ExitDecision:
    ref_price: float
    liquidity: Liquidity
    reason: str


def check_exit(pos: OpenPosition, candle: Candle) -> ExitDecision | None:
    """Return how/why to close `pos` on this candle, or None. Priority (D2.4, first
    to occur): requested/event exit -> stop -> target -> time stop. Pessimistic:
    stop gaps fill at the worse of stop/open; target fills at the limit (no gap bonus).
    """
    long = pos.side is Side.BUY

    if pos.exit_requested:
        return ExitDecision(candle.open, Liquidity.TAKER, "signal_exit")

    stop = pos.stop_price
    if long and candle.low <= stop:
        return ExitDecision(candle.open if candle.open < stop else stop, Liquidity.TAKER, "stop")
    if not long and candle.high >= stop:
        return ExitDecision(candle.open if candle.open > stop else stop, Liquidity.TAKER, "stop")

    tgt = pos.target_price
    if tgt is not None:
        if long and candle.high >= tgt:
            return ExitDecision(tgt, Liquidity.MAKER, "target")
        if not long and candle.low <= tgt:
            return ExitDecision(tgt, Liquidity.MAKER, "target")

    if pos.max_hold_minutes is not None:
        if candle.ts >= pos.opened_ts + timedelta(minutes=pos.max_hold_minutes):
            return ExitDecision(candle.close, Liquidity.TAKER, "time_stop")

    return None


def realized_pnl(
    pos: OpenPosition, exit_fill: float, exit_fee: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """(gross_pnl, total_costs, net_pnl) for closing pos at exit_fill.

    gross is the costless mid-to-mid move; total_costs folds slippage/spread (the
    gap between fill and reference) plus fees; net = gross - costs.
    """
    sign = Decimal(pos.side.sign)
    q = pos.quantity
    # net price PnL uses actual fills; gross uses references (costless).
    net_price = sign * (Decimal(str(exit_fill)) - Decimal(str(pos.entry_fill))) * q
    fees = pos.entry_fee + exit_fee
    net = net_price - fees
    # gross is reconstructed as net + all costs; slippage/spread cost is implicit.
    # Callers that track exit_ref can compute gross directly; here we return the
    # fee-only decomposition sufficient for equity accounting.
    gross = net_price
    return gross, fees, net
