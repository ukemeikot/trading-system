"""Text presenters for backtest / walk-forward results (SPEC M3/M4).

Reports state achieved win rate and breakeven win rate side by side, and cost
drag, per the spec — profitability is not a pass condition, honest numbers are.
"""

from __future__ import annotations

from tsys.application.dto import BacktestResult, WalkForwardReport


def format_backtest(result: BacktestResult, title: str = "Backtest") -> str:
    lines = [
        f"=== {title} ===",
        f"  trades           : {result.trade_count}",
        f"  net return       : {result.net_return_pct:+.2f}%",
        f"  net PnL          : {float(result.net_pnl):+.4f}",
        f"  gross PnL        : {float(result.gross_pnl):+.4f}",
        f"  total costs      : {float(result.total_costs):.4f}",
        f"  cost drag        : {_fmt_pct(result.cost_drag_pct)}  "
        f"(kill if > 40%)",
        f"  win rate         : {result.win_rate:.1f}%",
        f"  breakeven win rt : {result.breakeven_win_rate:.1f}%  "
        f"({'above' if result.win_rate >= result.breakeven_win_rate else 'below'} breakeven)",
        f"  max drawdown     : {result.max_drawdown_pct:.2f}%",
        f"  risk vetoes      : {result.vetoes}",
        f"  equity           : {float(result.initial_equity):.2f} -> "
        f"{float(result.final_equity):.2f}",
    ]
    return "\n".join(lines)


def format_walkforward(report: WalkForwardReport) -> str:
    out = [f"=== Walk-forward: {report.strategy} ==="]
    for fold in report.folds:
        r = fold.result
        out.append(
            f"  [{fold.label}] trades={r.trade_count} net={r.net_return_pct:+.2f}% "
            f"maxDD={r.max_drawdown_pct:.2f}% cost_drag={_fmt_pct(r.cost_drag_pct)} "
            f"win={r.win_rate:.1f}%/be={r.breakeven_win_rate:.1f}%"
        )
    return "\n".join(out)


def _fmt_pct(v: float) -> str:
    return "n/a" if v == float("inf") else f"{v:.1f}%"
