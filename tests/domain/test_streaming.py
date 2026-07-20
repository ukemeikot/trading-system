"""Streaming indicators must match the batch definitions after warmup."""

from __future__ import annotations

import numpy as np
import pytest

from tsys.domain.indicators import atr as batch_atr
from tsys.domain.indicators import ema as batch_ema
from tsys.domain.indicators import rsi as batch_rsi
from tsys.domain.strategies.streaming import (
    StreamingATR,
    StreamingEMA,
    StreamingRSI,
    StreamingStdev,
)

CLOSES = [10.0, 11, 9, 12, 13, 11, 14, 15, 13, 16, 12, 17, 14, 18, 15, 19, 16, 20]
HIGHS = [c + 0.7 for c in CLOSES]
LOWS = [c - 0.6 for c in CLOSES]


def test_streaming_ema_matches_batch() -> None:
    s = StreamingEMA(5)
    out = [s.update(c) for c in CLOSES]
    assert out[-1] == pytest.approx(batch_ema(CLOSES, 5)[-1])


def test_streaming_atr_matches_batch() -> None:
    s = StreamingATR(5)
    out = [s.update(h, low, c) for h, low, c in zip(HIGHS, LOWS, CLOSES, strict=True)]
    assert out[-1] == pytest.approx(batch_atr(HIGHS, LOWS, CLOSES, 5)[-1])


def test_streaming_rsi_matches_batch() -> None:
    s = StreamingRSI(5)
    out = [s.update(c) for c in CLOSES]
    assert out[-1] == pytest.approx(batch_rsi(CLOSES, 5)[-1])


def test_streaming_indicators_return_none_during_warmup() -> None:
    ema = StreamingEMA(5)
    assert ema.update(1.0) is None
    assert [ema.update(x) for x in (2.0, 3.0, 4.0)] == [None, None, None]
    assert ema.update(5.0) is not None  # 5th value -> seeded


def test_streaming_stdev_matches_numpy() -> None:
    s = StreamingStdev(4)
    vals = [1.0, 3.0, 2.0, 4.0, 6.0]
    out = [s.update(v) for v in vals]
    assert out[-1] == pytest.approx(float(np.std(vals[-4:])))  # population stdev
