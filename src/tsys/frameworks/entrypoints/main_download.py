"""Entrypoint: download historical data -> Parquet, and import the calendar.

Composition root (SPEC B2 frameworks): reads config, constructs adapters, injects
them into the use cases. Crypto downloads always; forex only if OANDA creds are
present (else it is skipped with a clear log line).

    python -m tsys.frameworks.entrypoints.main_download --years 2
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from tsys.adapters.calendar.csv_source import CsvCalendarSource
from tsys.adapters.clock import SystemClock
from tsys.adapters.feeds.ccxt_history import CcxtHistory
from tsys.adapters.feeds.twelvedata_history import TwelveDataHistory
from tsys.adapters.persistence.parquet_store import ParquetCandleStore
from tsys.application.ports import HistoricalDataSource
from tsys.application.use_cases.download_history import DownloadHistory
from tsys.application.use_cases.import_calendar import ImportCalendar
from tsys.domain.values import Market, Pair
from tsys.frameworks.config import Secrets, load_settings
from tsys.frameworks.logging_setup import configure_logging, get_logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Download historical market data to Parquet.")
    parser.add_argument("--years", type=float, default=2.0, help="lookback window in years")
    parser.add_argument("--config", default="config/settings.yaml")
    args = parser.parse_args()

    configure_logging()
    log = get_logger("tsys.download")
    settings = load_settings(args.config)
    secrets = Secrets()
    clock = SystemClock()

    end = clock.now()
    start = end - timedelta(days=round(args.years * 365))

    # Build per-market data sources. Forex is None unless a Twelve Data key is present.
    forex_source: HistoricalDataSource | None = None
    if secrets.has_forex:
        assert secrets.twelvedata_api_key is not None
        forex_source = TwelveDataHistory(secrets.twelvedata_api_key)
    else:
        log.warning("forex.creds_absent", action="forex download skipped; crypto continues")

    sources: dict[Market, HistoricalDataSource | None] = {
        Market.CRYPTO: CcxtHistory(),
        Market.FOREX: forex_source,
    }
    repo = ParquetCandleStore()
    download = DownloadHistory(sources, repo)

    pairs = [Pair.parse(s, Market.CRYPTO) for s in settings.pairs.crypto]
    pairs += [Pair.parse(s, Market.FOREX) for s in settings.pairs.forex]

    report = download.run(pairs, settings.timeframes, start, end)
    log.info(
        "download.done",
        total_rows=report.total_rows,
        files=len(report.entries) - len(report.skipped),
        skipped=len(report.skipped),
    )

    # Calendar import + staleness (SPEC D2.3 failsafe demonstration).
    cal = ImportCalendar(
        CsvCalendarSource(settings.calendar.path, settings.calendar.stale_after_days), clock
    )
    result = cal.run()
    if result.stale:
        log.warning("calendar.stale", events=len(result.events))
    else:
        log.info("calendar.fresh", events=len(result.events))


if __name__ == "__main__":
    main()
