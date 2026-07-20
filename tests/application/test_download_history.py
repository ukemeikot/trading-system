"""DownloadHistory use case with fake ports — crypto downloads, forex degrades gracefully."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from tsys.application.use_cases.download_history import DownloadHistory
from tsys.domain.entities import Candle
from tsys.domain.values import Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)
ETH = Pair("ETH", "USDT", Market.CRYPTO)
GBP = Pair("GBP", "USD", Market.FOREX)
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 2, tzinfo=UTC)


class FakeSource:
    def fetch_candles(
        self, pair: Pair, timeframe: str, start: datetime, end: datetime
    ) -> Sequence[Candle]:
        return [
            Candle(
                ts=START, pair=pair, timeframe=timeframe,
                open=1, high=2, low=0.5, close=1.5, volume=10,
            )
        ]


class FakeRepo:
    def __init__(self) -> None:
        self.writes: dict[tuple[str, str], int] = {}

    def write(self, pair: Pair, timeframe: str, candles: Sequence[Candle]) -> int:
        self.writes[(pair.symbol, timeframe)] = len(candles)
        return len(candles)

    def read(self, pair: Pair, timeframe: str) -> Sequence[Candle]:
        return []

    def has(self, pair: Pair, timeframe: str) -> bool:
        return (pair.symbol, timeframe) in self.writes


def test_downloads_crypto_writes_every_pair_timeframe() -> None:
    repo = FakeRepo()
    uc = DownloadHistory({Market.CRYPTO: FakeSource(), Market.FOREX: None}, repo)
    report = uc.run([BTC, ETH], ["1m", "1h"], START, END)
    assert repo.writes == {
        ("BTC/USDT", "1m"): 1, ("BTC/USDT", "1h"): 1,
        ("ETH/USDT", "1m"): 1, ("ETH/USDT", "1h"): 1,
    }
    assert report.total_rows == 4
    assert report.skipped == []


def test_forex_skipped_when_source_absent() -> None:
    repo = FakeRepo()
    uc = DownloadHistory({Market.CRYPTO: FakeSource(), Market.FOREX: None}, repo)
    report = uc.run([BTC, GBP], ["1m"], START, END)
    assert ("BTC/USDT", "1m") in repo.writes
    assert ("GBP/USD", "1m") not in repo.writes  # forex not written
    skipped = report.skipped
    assert len(skipped) == 1 and skipped[0].pair == "GBP/USD"


def test_forex_downloads_when_source_present() -> None:
    repo = FakeRepo()
    uc = DownloadHistory({Market.CRYPTO: FakeSource(), Market.FOREX: FakeSource()}, repo)
    report = uc.run([GBP], ["1m", "4h"], START, END)
    assert report.total_rows == 2 and report.skipped == []
