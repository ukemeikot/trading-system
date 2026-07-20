"""RegimeClassifier — is the tape quiet & ranging (tradeable) or trending (veto)?

SPEC D2.3(c):
  - quiet: ATR(14, 5m) as % of price is below its 20-day median.
  - trend veto: |EMA(20) - EMA(200)| on 5m must be < 0.5 * ATR(14, 5m); otherwise
    a trend is in force and mean reversion is vetoed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Regime(StrEnum):
    QUIET = "quiet"  # low vol, no strong trend — scalper may trade
    TRENDING = "trending"  # strong trend in force — veto
    ACTIVE = "active"  # elevated vol but no clear trend — veto (not quiet)
    UNKNOWN = "unknown"  # insufficient data


@dataclass(frozen=True, slots=True)
class RegimeInputs:
    atr_pct: float  # ATR(14,5m) / price * 100
    atr_pct_median_20d: float  # 20-day median of atr_pct
    ema_fast: float  # EMA(20) on 5m
    ema_slow: float  # EMA(200) on 5m
    atr_5m: float  # ATR(14,5m) in price units


class RegimeClassifier:
    def __init__(self, trend_veto_mult: float = 0.5) -> None:
        self._trend_veto_mult = trend_veto_mult

    def is_quiet(self, atr_pct: float, atr_pct_median_20d: float) -> bool:
        return atr_pct < atr_pct_median_20d

    def has_trend(self, ema_fast: float, ema_slow: float, atr_5m: float) -> bool:
        return abs(ema_fast - ema_slow) >= self._trend_veto_mult * atr_5m

    def classify(self, inp: RegimeInputs) -> Regime:
        import math

        vals = (inp.atr_pct, inp.atr_pct_median_20d, inp.ema_fast, inp.ema_slow, inp.atr_5m)
        if any(math.isnan(v) for v in vals):
            return Regime.UNKNOWN
        if self.has_trend(inp.ema_fast, inp.ema_slow, inp.atr_5m):
            return Regime.TRENDING
        if not self.is_quiet(inp.atr_pct, inp.atr_pct_median_20d):
            return Regime.ACTIVE
        return Regime.QUIET

    def qualifies(self, inp: RegimeInputs) -> bool:
        """True only in the QUIET regime — the scalper's entry gate."""
        return self.classify(inp) is Regime.QUIET
