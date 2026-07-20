"""RiskPolicy — pure Approve/Reject decision logic (SPEC C2).

Stateless: it reads a snapshot of portfolio state plus a proposed order and
returns a decision. The stateful wrapper that tracks the equity high-water mark
and flattens/halts lives in application (M5); the *rules* live here.

Rules enforced:
  - stop-less entries rejected (every position must carry a hard stop).
  - max concurrent positions; max positions per pair.
  - daily loss limit (halt for the UTC day).
  - kill switch: drawdown from high-water mark.
Exits (reduce_only) are always permitted so positions can be flattened.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from tsys.domain.entities import Order


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_concurrent_positions: int = 3
    max_positions_per_pair: int = 1
    daily_loss_limit_pct: Decimal = Decimal("3")
    kill_switch_drawdown_pct: Decimal = Decimal("15")


@dataclass(frozen=True, slots=True)
class PortfolioState:
    equity: Decimal
    high_water_mark: Decimal
    day_start_equity: Decimal
    day_realized_pnl: Decimal = Decimal(0)
    open_positions: int = 0
    positions_by_pair: Mapping[str, int] = field(default_factory=dict)

    @property
    def drawdown_pct(self) -> Decimal:
        if self.high_water_mark <= 0:
            return Decimal(0)
        return (self.high_water_mark - self.equity) / self.high_water_mark * Decimal(100)

    @property
    def day_loss_pct(self) -> Decimal:
        if self.day_start_equity <= 0:
            return Decimal(0)
        return -self.day_realized_pnl / self.day_start_equity * Decimal(100)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.approved


class RiskPolicy:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    def kill_switch_tripped(self, state: PortfolioState) -> bool:
        return state.drawdown_pct >= self._limits.kill_switch_drawdown_pct

    def daily_limit_tripped(self, state: PortfolioState) -> bool:
        return state.day_loss_pct >= self._limits.daily_loss_limit_pct

    def evaluate(self, order: Order, state: PortfolioState) -> RiskDecision:
        # Exits always allowed — we must be able to flatten under any condition.
        if order.reduce_only:
            return RiskDecision(True)

        if self.kill_switch_tripped(state):
            return RiskDecision(
                False,
                f"kill switch: drawdown {state.drawdown_pct:.2f}% "
                f">= {self._limits.kill_switch_drawdown_pct}%",
            )
        if self.daily_limit_tripped(state):
            return RiskDecision(
                False,
                f"daily loss limit: {state.day_loss_pct:.2f}% "
                f">= {self._limits.daily_loss_limit_pct}%",
            )
        if order.stop_price is None:
            return RiskDecision(False, "stop-less order rejected (hard stop required)")

        pair_count = state.positions_by_pair.get(order.pair.symbol, 0)
        if pair_count >= self._limits.max_positions_per_pair:
            return RiskDecision(
                False,
                f"max positions per pair reached for {order.pair.symbol} "
                f"({pair_count}/{self._limits.max_positions_per_pair})",
            )
        if state.open_positions >= self._limits.max_concurrent_positions:
            return RiskDecision(
                False,
                f"max concurrent positions reached "
                f"({state.open_positions}/{self._limits.max_concurrent_positions})",
            )
        return RiskDecision(True)
