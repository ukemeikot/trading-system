"""Entrypoint: the weekly observation report (SPEC M6).

Reads the paper-trading decision log and prints net return after costs, max
drawdown, trades/vetoes/halts, filter activations and latency p50/p99 for a
window. Intended to run on a weekly schedule (systemd timer / cron) during the
observation period.

    python -m tsys.frameworks.entrypoints.main_report --db data/tsys.sqlite --weeks 1
    python -m tsys.frameworks.entrypoints.main_report --from 2026-07-01 --to 2026-07-08
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from tsys.adapters.clock import SystemClock
from tsys.adapters.persistence.sqlite_repo import SqliteTradeRepository
from tsys.application.use_cases.period_report import GeneratePeriodReport
from tsys.frameworks.reporting import format_period_report


def main() -> None:
    p = argparse.ArgumentParser(description="Weekly observation report.")
    p.add_argument("--db", default="data/tsys.sqlite")
    p.add_argument("--weeks", type=int, default=1, help="window size ending today (if no --from)")
    p.add_argument("--from", dest="start", default=None, help="inclusive start date YYYY-MM-DD")
    p.add_argument("--to", dest="end", default=None, help="exclusive end date YYYY-MM-DD")
    args = p.parse_args()

    today = SystemClock().now().date()
    end = args.end or (today + timedelta(days=1)).isoformat()
    start = args.start or (today - timedelta(weeks=args.weeks)).isoformat()

    repo = SqliteTradeRepository(args.db)
    report = GeneratePeriodReport(repo).run(start, end)
    print(format_period_report(report))
    repo.close()


if __name__ == "__main__":
    main()
