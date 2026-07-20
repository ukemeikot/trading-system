"""Indicator math — numpy only, no mocks."""

from __future__ import annotations

import numpy as np

from tsys.domain.indicators import atr, ema, rsi, vwap


def test_ema_constant_series_equals_constant() -> None:
    out = ema([5.0] * 10, period=3)
    # first two nan (need `period` values), then all equal to 5.
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert np.allclose(out[2:], 5.0)


def test_ema_length_and_warmup() -> None:
    out = ema(np.arange(1, 11, dtype=float), period=5)
    assert out.shape == (10,)
    assert np.count_nonzero(np.isnan(out)) == 4  # first period-1 are nan


def test_ema_no_lookahead() -> None:
    # value at i must not change when future data is appended.
    full = ema([1.0, 2, 3, 4, 5, 6, 7, 8], period=3)
    partial = ema([1.0, 2, 3, 4, 5], period=3)
    assert np.allclose(full[:5][~np.isnan(full[:5])], partial[~np.isnan(partial)])


def test_atr_positive_and_warmup() -> None:
    high = np.array([10, 11, 12, 13, 14, 15], dtype=float)
    low = np.array([9, 10, 11, 12, 13, 14], dtype=float)
    close = np.array([9.5, 10.5, 11.5, 12.5, 13.5, 14.5], dtype=float)
    out = atr(high, low, close, period=3)
    assert out.shape == (6,)
    valid = out[~np.isnan(out)]
    assert np.all(valid > 0)


def test_rsi_all_gains_is_100() -> None:
    out = rsi(np.arange(1, 20, dtype=float), period=14)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 100.0)


def test_rsi_bounds() -> None:
    rng = np.array([1, 2, 1.5, 3, 2, 4, 3, 5, 2, 6, 1, 7, 3, 8, 2, 9, 4, 10], dtype=float)
    out = rsi(rng, period=5)
    valid = out[~np.isnan(out)]
    assert np.all((valid >= 0) & (valid <= 100))


def test_vwap_cumulative() -> None:
    price = np.array([10.0, 20.0, 30.0])
    volume = np.array([1.0, 1.0, 1.0])
    out = vwap(price, volume)
    assert np.isclose(out[0], 10.0)
    assert np.isclose(out[1], 15.0)
    assert np.isclose(out[2], 20.0)


def test_vwap_session_reset() -> None:
    price = np.array([10.0, 20.0, 100.0, 200.0])
    volume = np.array([1.0, 1.0, 1.0, 1.0])
    sessions = np.array([0, 0, 1, 1], dtype=np.int64)
    out = vwap(price, volume, sessions)
    assert np.isclose(out[1], 15.0)  # session 0
    assert np.isclose(out[2], 100.0)  # session 1 resets
    assert np.isclose(out[3], 150.0)
