"""Cross-boundary data shapes for backtesting (SPEC M3).

Money/PnL is carried as Decimal (exact, consistent with the CostModel); prices are
floats (market data); ratios/returns are floats. These types are produced by the
backtest engine (adapter) and consumed by use cases and reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from tsys.domain.costs import CostConfig
from tsys.domain.risk import RiskLimits
from tsys.domain.sizing import NotionalBounds
from tsys.domain.values import Side


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Everything the engine needs that is not the strategy or the candles."""

    initial_equity: Decimal
    risk_pct: Decimal
    costs: CostConfig
    risk_limits: RiskLimits
    bounds: NotionalBounds
    slippage_multiplier: Decimal = Decimal(1)  # for the double-slippage stress test
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class Trade:
    entry_ts: datetime
    exit_ts: datetime
    side: Side
    quantity: Decimal
    entry_price: float
    exit_price: float
    gross_pnl: Decimal  # price move * qty (before costs)
    costs: Decimal  # fees + spread/slippage attributable to this trade
    net_pnl: Decimal  # gross - costs
    exit_reason: str

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0


@dataclass(slots=True)
class BacktestResult:
    initial_equity: Decimal
    final_equity: Decimal
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    vetoes: int = 0  # risk/veto decisions logged

    # -- metrics ----------------------------------------------------------
    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def net_return_pct(self) -> float:
        if self.initial_equity == 0:
            return 0.0
        return float((self.final_equity - self.initial_equity) / self.initial_equity * 100)

    @property
    def gross_pnl(self) -> Decimal:
        return sum((t.gross_pnl for t in self.trades), Decimal(0))

    @property
    def net_pnl(self) -> Decimal:
        return sum((t.net_pnl for t in self.trades), Decimal(0))

    @property
    def total_costs(self) -> Decimal:
        return sum((t.costs for t in self.trades), Decimal(0))

    @property
    def cost_drag_pct(self) -> float:
        """Costs as a fraction of gross PnL magnitude (SPEC D2.5 kill criterion).

        100% means costs equal gross PnL. Undefined (returns inf) if gross is zero
        but costs were paid."""
        gross = abs(self.gross_pnl)
        if gross == 0:
            return float("inf") if self.total_costs > 0 else 0.0
        return float(self.total_costs / gross * 100)

    @property
    def wins(self) -> list[Trade]:
        return [t for t in self.trades if t.is_win]

    @property
    def losses(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_win]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.wins) / len(self.trades) * 100

    @property
    def avg_win(self) -> Decimal:
        w = self.wins
        return sum((t.net_pnl for t in w), Decimal(0)) / len(w) if w else Decimal(0)

    @property
    def avg_loss(self) -> Decimal:
        """Average loss magnitude (positive number)."""
        losing = self.losses
        if not losing:
            return Decimal(0)
        return -sum((t.net_pnl for t in losing), Decimal(0)) / len(losing)

    @property
    def breakeven_win_rate(self) -> float:
        """The win rate at which this payoff geometry breaks even:
        breakeven = avg_loss / (avg_win + avg_loss) (SPEC D2.4)."""
        denom = self.avg_win + self.avg_loss
        if denom == 0:
            return 0.0
        return float(self.avg_loss / denom * 100)

    @property
    def max_drawdown_pct(self) -> float:
        peak: Decimal | None = None
        max_dd = 0.0
        for _, eq in self.equity_curve:
            if peak is None or eq > peak:
                peak = eq
            if peak and peak > 0:
                dd = float((peak - eq) / peak * 100)
                max_dd = max(max_dd, dd)
        return max_dd


@dataclass(frozen=True, slots=True)
class FoldResult:
    label: str
    start: datetime
    end: datetime
    result: BacktestResult


@dataclass(slots=True)
class WalkForwardReport:
    strategy: str
    folds: list[FoldResult] = field(default_factory=list)
