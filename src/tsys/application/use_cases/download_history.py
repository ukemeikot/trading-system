"""DownloadHistory use case (SPEC M2).

Iterates pairs x timeframes, fetches historical candles from the per-market
HistoricalDataSource, and persists them via the CandleRepository. Forex degrades
gracefully: if no forex source is wired (data-provider key absent), those pairs
are skipped with a clear log line and crypto still downloads.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from tsys.application.ports import CandleRepository, HistoricalDataSource
from tsys.domain.values import Market, Pair


@dataclass(frozen=True, slots=True)
class DownloadEntry:
    pair: str
    timeframe: str
    rows: int
    skipped: bool
    reason: str = ""


@dataclass(slots=True)
class DownloadReport:
    entries: list[DownloadEntry] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(e.rows for e in self.entries)

    @property
    def skipped(self) -> list[DownloadEntry]:
        return [e for e in self.entries if e.skipped]


class DownloadHistory:
    def __init__(
        self,
        sources: Mapping[Market, HistoricalDataSource | None],
        repository: CandleRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sources = sources
        self._repo = repository
        self._log = logger or logging.getLogger("tsys.download")

    def run(
        self,
        pairs: Sequence[Pair],
        timeframes: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> DownloadReport:
        report = DownloadReport()
        for pair in pairs:
            source = self._sources.get(pair.market)
            if source is None:
                reason = f"no data source for market {pair.market.value} (skipping)"
                self._log.warning("download.skip", extra={"pair": pair.symbol, "reason": reason})
                for tf in timeframes:
                    report.entries.append(DownloadEntry(pair.symbol, tf, 0, True, reason))
                continue
            for tf in timeframes:
                candles = source.fetch_candles(pair, tf, start, end)
                rows = self._repo.write(pair, tf, candles)
                self._log.info(
                    "download.ok", extra={"pair": pair.symbol, "timeframe": tf, "rows": rows}
                )
                report.entries.append(DownloadEntry(pair.symbol, tf, rows, False))
        return report
