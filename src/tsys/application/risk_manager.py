"""RiskManager — the stateful wrapper around the pure RiskPolicy (SPEC C2/M5).

The *rules* live in domain.RiskPolicy; the mutable state (equity high-water mark,
daily accounting, kill-switch latch, per-instrument consecutive losses) lives here
in the application layer, exactly as B2 prescribes. The live engine marks equity
each candle, asks whether to flatten/halt, and evaluates every proposed entry.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from tsys.domain.entities import Order
from tsys.domain.risk import PortfolioState, RiskDecision, RiskPolicy


class RiskManager:
    def __init__(self, policy: RiskPolicy, starting_equity: Decimal) -> None:
        self._policy = policy
        self._equity = starting_equity
        self._hwm = starting_equity
        self._day_start_equity = starting_equity
        self._day: date | None = None
        self._open_positions = 0
        self._by_pair: dict[str, int] = defaultdict(int)
        self._consec_losses: dict[str, int] = defaultdict(int)
        self._kill_latched = False
        self._consec_limit = 3  # D2.3b: 3 consecutive losses -> instrument done for the day

    # -- state updates ----------------------------------------------------
    def mark(self, equity: Decimal, now: datetime) -> None:
        """Update mark-to-market equity and roll daily accounting at the UTC day boundary."""
        if self._day != now.date():
            self._day = now.date()
            self._day_start_equity = equity
            self._by_pair.clear()  # counts are re-derived from positions; safe to reset daily view
            self._consec_losses.clear()
        self._equity = equity
        if equity > self._hwm:
            self._hwm = equity

    def record_open(self, pair_symbol: str) -> None:
        self._open_positions += 1
        self._by_pair[pair_symbol] += 1

    def record_close(self, pair_symbol: str, net_pnl: Decimal) -> None:
        self._open_positions = max(0, self._open_positions - 1)
        self._by_pair[pair_symbol] = max(0, self._by_pair[pair_symbol] - 1)
        if net_pnl < 0:
            self._consec_losses[pair_symbol] += 1
        else:
            self._consec_losses[pair_symbol] = 0

    # -- queries ----------------------------------------------------------
    def _state(self) -> PortfolioState:
        return PortfolioState(
            equity=self._equity, high_water_mark=self._hwm,
            day_start_equity=self._day_start_equity,
            day_realized_pnl=self._equity - self._day_start_equity,
            open_positions=self._open_positions, positions_by_pair=dict(self._by_pair),
        )

    @property
    def equity(self) -> Decimal:
        return self._equity

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_latched

    def check_halt(self) -> tuple[bool, str]:
        """Should the engine flatten everything and stop opening? (kill switch latches)."""
        state = self._state()
        if self._kill_latched or self._policy.kill_switch_tripped(state):
            self._kill_latched = True
            return True, "kill switch: drawdown limit hit (manual restart required)"
        if self._policy.daily_limit_tripped(state):
            return True, "daily loss limit hit (halted until next UTC day)"
        return False, ""

    def evaluate(self, order: Order, pair_symbol: str) -> RiskDecision:
        if self._kill_latched:
            return RiskDecision(False, "kill switch active (manual restart required)")
        if self._consec_losses[pair_symbol] >= self._consec_limit:
            return RiskDecision(
                False, f"{pair_symbol} done for the day ({self._consec_limit} consecutive losses)"
            )
        return self._policy.evaluate(order, self._state())
