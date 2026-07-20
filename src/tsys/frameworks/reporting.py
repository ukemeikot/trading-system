"""Text presenters for backtest / walk-forward results (SPEC M3/M4).

Reports state achieved win rate and breakeven win rate side by side, and cost
drag, per the spec — profitability is not a pass condition, honest numbers are.
"""

from __future__ import annotations

from tsys.application.dto import BacktestResult, WalkForwardReport
from tsys.application.use_cases.daily_report import DailyReport
from tsys.application.use_cases.validate import ValidationReport


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


def format_validation(report: ValidationReport) -> str:
    verdict = "PASS" if report.passed_all else "FAIL"
    out = [
        f"=== Validation: {report.strategy}  [{verdict}] ===",
        "  (a failing strategy still yields a valid report -- evidence, not a green number)",
    ]
    for c in report.criteria:
        mark = "PASS" if c.passed else "FAIL"
        out.append(f"  [{mark}] {c.name}: {c.detail}")
    out.append("  --- baseline ---")
    out.append("  " + format_backtest(report.baseline, "default fees").replace("\n", "\n  "))
    if report.alt_fee is not None:
        out.append("  --- dual fee schedule (venue maker/taker) ---")
        out.append("  " + format_backtest(report.alt_fee, "venue fees").replace("\n", "\n  "))
    return "\n".join(out)


def format_daily_report(report: DailyReport) -> str:
    lines = [
        f"=== Daily report: {report.day} ===",
        f"  fills         : {report.fills}",
        f"  risk vetoes   : {report.vetoes}",
        f"  halts fired   : {report.halts}",
        f"  final equity  : {report.final_equity if report.final_equity is not None else 'n/a'}",
        "  latency (us)  :",
    ]
    if not report.latency:
        lines.append("    (none recorded)")
    for stage, (p50, p99) in report.latency.items():
        lines.append(f"    {stage:<16} p50={p50:.1f} p99={p99:.1f}")
    return "\n".join(lines)


def _fmt_pct(v: float) -> str:
    return "n/a" if v == float("inf") else f"{v:.1f}%"
