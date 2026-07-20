"""Indicator math — numpy only, pure functions on 1-D float arrays.

Conventions:
- Inputs are numpy arrays ordered oldest -> newest.
- Outputs are the same length as the input; positions that cannot be computed
  yet (insufficient history) are numpy.nan.
- No lookahead: output[i] depends only on inputs[:i+1].
- Wilder's smoothing is used for ATR and RSI (the standard for these).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def _as_f64(a: NDArray[np.float64] | list[float]) -> FloatArray:
    return np.asarray(a, dtype=np.float64)


def ema(values: FloatArray | list[float], period: int) -> FloatArray:
    """Exponential moving average, seeded with the SMA of the first `period` values."""
    if period <= 0:
        raise ValueError("period must be positive")
    v = _as_f64(values)
    out = np.full(v.shape, np.nan, dtype=np.float64)
    if v.size < period:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = v[:period].mean()
    out[period - 1] = seed
    prev = seed
    for i in range(period, v.size):
        prev = alpha * v[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def _wilder(values: FloatArray, period: int) -> FloatArray:
    """Wilder's smoothing (RMA), seeded with the SMA of the first `period` values."""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size < period:
        return out
    seed = values[:period].mean()
    out[period - 1] = seed
    prev = seed
    for i in range(period, values.size):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def atr(
    high: FloatArray | list[float],
    low: FloatArray | list[float],
    close: FloatArray | list[float],
    period: int = 14,
) -> FloatArray:
    """Average True Range (Wilder). Length matches inputs; first `period` are nan."""
    h, low_a, c = _as_f64(high), _as_f64(low), _as_f64(close)
    if not (h.size == low_a.size == c.size):
        raise ValueError("high/low/close must be the same length")
    n = c.size
    tr = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return tr
    tr[0] = h[0] - low_a[0]
    prev_close = c[:-1]
    tr[1:] = np.maximum.reduce(
        [
            h[1:] - low_a[1:],
            np.abs(h[1:] - prev_close),
            np.abs(low_a[1:] - prev_close),
        ]
    )
    # Wilder over TR, but TR[0] exists so smooth from index 0.
    return _wilder(tr, period)


def rsi(close: FloatArray | list[float], period: int = 14) -> FloatArray:
    """Relative Strength Index (Wilder). Range 0..100; first `period` are nan."""
    c = _as_f64(close)
    n = c.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= period:
        return out
    delta = np.diff(c)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = _wilder(gains, period)
    avg_loss = _wilder(losses, period)
    # gains/losses are indexed off-by-one vs close (diff); align to close index i+1.
    for i in range(period, n):
        ag = avg_gain[i - 1]
        al = avg_loss[i - 1]
        if np.isnan(ag) or np.isnan(al):
            continue
        if al == 0.0:
            out[i] = 100.0
        else:
            rs = ag / al
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def vwap(
    price: FloatArray | list[float],
    volume: FloatArray | list[float],
    session_ids: NDArray[np.int64] | list[int] | None = None,
) -> FloatArray:
    """Volume-weighted average price, cumulative and *session-anchored*.

    If `session_ids` is given (one id per bar), the cumulative sums reset when the
    id changes — this is how the strategy anchors VWAP to 00:00 UTC (crypto) or
    the session open (GBP/USD). Without it, VWAP is cumulative over the whole array.
    """
    p = _as_f64(price)
    vol = _as_f64(volume)
    if p.size != vol.size:
        raise ValueError("price and volume must be the same length")
    if session_ids is None:
        cum_pv = np.cumsum(p * vol)
        cum_v = np.cumsum(vol)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cum_v > 0, cum_pv / cum_v, np.nan)

    ids = np.asarray(session_ids)
    out = np.full(p.size, np.nan, dtype=np.float64)
    run_pv = 0.0
    run_v = 0.0
    current: int | None = None
    for i in range(p.size):
        sid = int(ids[i])
        if sid != current:
            current = sid
            run_pv = 0.0
            run_v = 0.0
        run_pv += float(p[i]) * float(vol[i])
        run_v += float(vol[i])
        out[i] = run_pv / run_v if run_v > 0 else np.nan
    return out
