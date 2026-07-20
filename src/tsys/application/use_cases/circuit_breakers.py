"""EnforceCircuitBreakers — the unscheduled-news breakers (SPEC D2.3b / M5).

Where each breaker lives:
  - volatility-spike halt : emitted by quiet_scalper (candle-derivable)
  - kill-switch + daily-loss + consecutive-loss halts : RiskManager
  - spread-blowout halt : HERE — it needs a live tick spread, so it only activates
    on the tick path. On the candle-replay path there is no spread, so it is inert
    (documented, not silently dropped).

The spread-blowout monitor keeps a trailing window of spreads and flags a blowout
when the live spread exceeds `mult` x the trailing median (default 2.5x, D2.3b).
"""

from __future__ import annotations

import statistics
from collections import deque


class SpreadBlowoutMonitor:
    def __init__(self, mult: float = 2.5, window: int = 3600, min_samples: int = 30) -> None:
        self._mult = mult
        self._spreads: deque[float] = deque(maxlen=window)  # ~1h of 1s spreads
        self._min = min_samples

    def update(self, spread: float) -> None:
        self._spreads.append(spread)

    def is_blown_out(self, spread: float) -> bool:
        if len(self._spreads) < self._min:
            return False
        median = statistics.median(self._spreads)
        return median > 0 and spread > self._mult * median
