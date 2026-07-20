"""PositionSizer — fixed-fractional sizing from an ATR-based stop distance (SPEC C2).

qty = (equity * risk_pct) / stop_distance_per_unit

A $100 account must still produce a valid order size, so a per-market notional
floor/ceiling is applied. Clamping to the floor can push realized risk above the
target; that is surfaced (`clamped`, `effective_risk`) rather than hidden, and a
`max_risk_multiple` guard rejects sizes whose clamped risk is unacceptable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from tsys.domain.values import Pair


def _dec(x: Decimal | int | str | float) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


@dataclass(frozen=True, slots=True)
class SizingResult:
    ok: bool
    quantity: Decimal
    notional: Decimal
    risk_amount: Decimal  # intended risk (equity * risk_pct)
    effective_risk: Decimal  # actual risk after clamping = quantity * stop_distance
    clamped: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class NotionalBounds:
    min_notional: Decimal
    max_notional: Decimal | None = None
    qty_step: Decimal | None = None  # round quantity down to this increment


class PositionSizer:
    def __init__(self, bounds: NotionalBounds, max_risk_multiple: Decimal = Decimal(2)) -> None:
        self._b = bounds
        self._max_risk_multiple = max_risk_multiple

    def size(
        self,
        equity: Decimal | float,
        risk_pct: Decimal | float,
        entry_price: Decimal | float,
        stop_distance: Decimal | float,
        pair: Pair,
    ) -> SizingResult:
        eq = _dec(equity)
        rp = _dec(risk_pct)
        px = _dec(entry_price)
        sd = _dec(stop_distance)

        zero = Decimal(0)
        if sd <= zero:
            return self._reject(zero, "stop_distance must be positive (stop-less order)")
        if px <= zero:
            return self._reject(zero, "entry_price must be positive")

        risk_amount = eq * rp / Decimal(100)
        qty = risk_amount / sd
        notional = qty * px
        clamped = False

        if notional < self._b.min_notional:
            notional = self._b.min_notional
            qty = notional / px
            clamped = True
        elif self._b.max_notional is not None and notional > self._b.max_notional:
            notional = self._b.max_notional
            qty = notional / px
            clamped = True

        if self._b.qty_step is not None and self._b.qty_step > zero:
            qty = (qty / self._b.qty_step).to_integral_value(rounding=ROUND_DOWN) * self._b.qty_step
            notional = qty * px

        if qty <= zero:
            return self._reject(risk_amount, "sized quantity rounds to zero")

        effective_risk = qty * sd
        if effective_risk > risk_amount * self._max_risk_multiple:
            return SizingResult(
                ok=False,
                quantity=qty,
                notional=notional,
                risk_amount=risk_amount,
                effective_risk=effective_risk,
                clamped=clamped,
                reason=(
                    f"clamped notional forces risk {effective_risk} > "
                    f"{self._max_risk_multiple}x target {risk_amount}"
                ),
            )

        return SizingResult(
            ok=True,
            quantity=qty,
            notional=notional,
            risk_amount=risk_amount,
            effective_risk=effective_risk,
            clamped=clamped,
            reason="clamped to notional floor" if clamped else "",
        )

    def _reject(self, risk_amount: Decimal, reason: str) -> SizingResult:
        z = Decimal(0)
        return SizingResult(
            ok=False,
            quantity=z,
            notional=z,
            risk_amount=risk_amount,
            effective_risk=z,
            clamped=False,
            reason=reason,
        )
