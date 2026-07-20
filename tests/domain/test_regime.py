"""RegimeClassifier — quiet vs trending gate (SPEC D2.3c)."""

from __future__ import annotations

import math

from tsys.domain.regime import Regime, RegimeClassifier, RegimeInputs


def test_quiet_when_low_vol_and_no_trend() -> None:
    clf = RegimeClassifier()
    inp = RegimeInputs(
        atr_pct=0.4, atr_pct_median_20d=0.6, ema_fast=100.0, ema_slow=100.1, atr_5m=1.0
    )
    assert clf.classify(inp) is Regime.QUIET
    assert clf.qualifies(inp)


def test_trending_vetoes_even_if_quiet_vol() -> None:
    clf = RegimeClassifier(trend_veto_mult=0.5)
    # |ema_fast - ema_slow| = 1.0 >= 0.5 * atr_5m (0.5) -> trend in force
    inp = RegimeInputs(
        atr_pct=0.3, atr_pct_median_20d=0.6, ema_fast=101.0, ema_slow=100.0, atr_5m=1.0
    )
    assert clf.classify(inp) is Regime.TRENDING
    assert not clf.qualifies(inp)


def test_active_when_vol_above_median() -> None:
    clf = RegimeClassifier()
    inp = RegimeInputs(
        atr_pct=0.9, atr_pct_median_20d=0.6, ema_fast=100.0, ema_slow=100.05, atr_5m=1.0
    )
    assert clf.classify(inp) is Regime.ACTIVE


def test_unknown_on_nan() -> None:
    clf = RegimeClassifier()
    inp = RegimeInputs(
        atr_pct=math.nan, atr_pct_median_20d=0.6, ema_fast=100.0, ema_slow=100.0, atr_5m=1.0
    )
    assert clf.classify(inp) is Regime.UNKNOWN
