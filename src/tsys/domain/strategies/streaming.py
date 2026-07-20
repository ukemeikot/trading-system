"""Streaming (incremental) indicators for candle-by-candle strategies.

Pure, stdlib-only, O(1) per update. These match the batch definitions in
domain.indicators (EMA seeded with SMA, Wilder smoothing for ATR/RSI) but update
one value at a time so a strategy's on_candle stays cheap and lookahead-free.
Each returns None until it has enough history to produce a value.
"""

from __future__ import annotations


class StreamingEMA:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._alpha = 2.0 / (period + 1.0)
        self._buf: list[float] = []
        self.value: float | None = None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._buf.append(x)
            if len(self._buf) == self.period:
                self.value = sum(self._buf) / self.period
            return self.value
        self.value = self._alpha * x + (1.0 - self._alpha) * self.value
        return self.value


class StreamingATR:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._prev_close: float | None = None
        self._trs: list[float] = []
        self.value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        if self.value is None:
            self._trs.append(tr)
            if len(self._trs) == self.period:
                self.value = sum(self._trs) / self.period
            return self.value
        self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


class StreamingRSI:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._prev: float | None = None
        self._gains: list[float] = []
        self._losses: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self.value: float | None = None

    def update(self, close: float) -> float | None:
        if self._prev is None:
            self._prev = close
            return None
        delta = close - self._prev
        self._prev = close
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        if self._avg_gain is None or self._avg_loss is None:
            self._gains.append(gain)
            self._losses.append(loss)
            if len(self._gains) == self.period:
                self._avg_gain = sum(self._gains) / self.period
                self._avg_loss = sum(self._losses) / self.period
                self.value = self._compute()
            return self.value
        self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
        self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
        self.value = self._compute()
        return self.value

    def _compute(self) -> float:
        assert self._avg_gain is not None and self._avg_loss is not None
        if self._avg_loss == 0:
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


class StreamingStdev:
    """Rolling population standard deviation over a fixed window (for VWAP bands)."""

    def __init__(self, window: int) -> None:
        if window <= 1:
            raise ValueError("window must be > 1")
        self.window = window
        self._buf: list[float] = []

    def update(self, x: float) -> float | None:
        self._buf.append(x)
        if len(self._buf) > self.window:
            self._buf.pop(0)
        if len(self._buf) < self.window:
            return None
        mean = sum(self._buf) / self.window
        var = sum((v - mean) ** 2 for v in self._buf) / self.window
        return float(var**0.5)
