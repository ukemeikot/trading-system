"""Behavioural tests for the three strategies (SPEC D1/D2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tsys.domain.entities import Candle, OrderType, SignalKind
from tsys.domain.strategies.meanrev import MeanRev
from tsys.domain.strategies.momentum import Momentum
from tsys.domain.strategies.quiet_scalper import QuietScalper
from tsys.domain.values import Direction, Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)


def _candles(closes: list[float], start: datetime, step_min: int = 60,
             spread: float = 0.5) -> list[Candle]:
    return [
        Candle(ts=start + timedelta(minutes=step_min * i), pair=BTC, timeframe="1m",
               open=c, high=c + spread, low=c - spread, close=c, volume=10.0)
        for i, c in enumerate(closes)
    ]


def _run(strategy, candles):  # type: ignore[no-untyped-def]
    state = strategy.initial_state()
    out = []
    for c in candles:
        sig, state = strategy.on_candle(c, state)
        if sig is not None:
            out.append(sig)
    return out


# -- momentum -------------------------------------------------------------

def test_momentum_enters_long_on_bullish_cross_then_exits() -> None:
    strat = Momentum(ema_fast=2, ema_slow=4, atr_period=2, atr_stop_mult=2.0)
    closes = [10, 10, 10, 10, 10] + [11, 12, 13, 14, 15] + [14, 12, 10, 8, 6]
    sigs = _run(strat, _candles([float(x) for x in closes], datetime(2024, 1, 1, tzinfo=UTC)))
    kinds = [(s.kind, s.direction) for s in sigs]
    assert (SignalKind.ENTER, Direction.LONG) in kinds
    assert (SignalKind.EXIT, Direction.LONG) in kinds
    enter = next(s for s in sigs if s.kind is SignalKind.ENTER)
    assert enter.stop_price is not None and enter.stop_price < 15  # ATR stop below entry
    assert enter.order_type is OrderType.MARKET


# -- meanrev --------------------------------------------------------------

def test_meanrev_long_on_oversold_then_exit_on_midline() -> None:
    strat = MeanRev(rsi_period=3, rsi_oversold=30, rsi_overbought=70, atr_period=3)
    closes = [20, 19, 18, 17, 16, 15, 14] + [15, 17, 19, 21, 23]  # dump then rip
    sigs = _run(strat, _candles([float(x) for x in closes], datetime(2024, 1, 1, tzinfo=UTC)))
    kinds = [(s.kind, s.direction) for s in sigs]
    assert (SignalKind.ENTER, Direction.LONG) in kinds
    assert (SignalKind.EXIT, Direction.LONG) in kinds


def test_meanrev_short_on_overbought() -> None:
    strat = MeanRev(rsi_period=3, rsi_oversold=30, rsi_overbought=70, atr_period=3)
    closes = [10, 11, 12, 13, 14, 15, 16, 17]  # steady rip -> overbought
    sigs = _run(strat, _candles([float(x) for x in closes], datetime(2024, 1, 1, tzinfo=UTC)))
    assert any(s.kind is SignalKind.ENTER and s.direction is Direction.SHORT for s in sigs)


# -- quiet_scalper --------------------------------------------------------

def _in_session_start() -> datetime:
    return datetime(2024, 1, 1, 8, 0, tzinfo=UTC)  # 08:00 UTC, inside crypto session


def test_quiet_scalper_no_trade_outside_session() -> None:
    strat = QuietScalper(use_news_filter=False, use_regime_filter=False, min_session_bars=3)
    # 03:00 UTC is outside the crypto 07:00-16:00 window
    candles = _candles([100, 90, 100] * 5, datetime(2024, 1, 1, 3, 0, tzinfo=UTC), step_min=1)
    assert _run(strat, candles) == []


def test_quiet_scalper_band_fade_enters_post_only() -> None:
    strat = QuietScalper(
        use_news_filter=False, use_regime_filter=False, min_session_bars=5, band_k=1.5,
        atr_period=3,
    )
    start = _in_session_start()
    # warmup with oscillation to build VWAP + stdev, then pierce below and recover.
    closes = [100, 101, 99, 100.5, 99.5, 100, 101, 99] + [95.0, 99.0]
    candles = _candles(closes, start, step_min=1)
    sigs = _run(strat, candles)
    enters = [s for s in sigs if s.kind is SignalKind.ENTER]
    assert enters, "expected a band-fade entry"
    e = enters[0]
    assert e.direction is Direction.LONG
    assert e.order_type is OrderType.POST_ONLY  # maker-only entry (D2.5)
    assert e.target_price is not None  # VWAP target
    assert e.max_hold_minutes == 30  # 30-min hard cap (D2.1)
    assert e.limit_price is not None


def test_quiet_scalper_volatility_spike_flattens() -> None:
    strat = QuietScalper(use_news_filter=False, use_regime_filter=False, min_session_bars=3,
                         vol_spike_mult=3.0, atr_period=3)
    start = _in_session_start()
    candles = _candles([100.0] * 6, start, step_min=1, spread=0.2)  # calm -> small ATR
    # a candle with a huge range triggers the spike halt
    candles.append(Candle(ts=start + timedelta(minutes=6), pair=BTC, timeframe="1m",
                          open=100, high=130, low=70, close=100, volume=10))
    sigs = _run(strat, candles)
    assert any(s.kind is SignalKind.EXIT and "spike" in s.reason for s in sigs)


def test_quiet_scalper_news_blackout_flattens() -> None:
    from tsys.domain.entities import NewsEvent
    from tsys.domain.values import Impact
    start = _in_session_start()
    # event at 08:30; force-flat window is [08:20, 09:15]
    event = NewsEvent(ts=start + timedelta(minutes=30), country="US", title="CPI",
                      impact=Impact.HIGH)
    strat = QuietScalper(use_news_filter=True, use_regime_filter=False, min_session_bars=3,
                         news_events=[event])
    candles = _candles([100.0] * 40, start, step_min=1)
    sigs = _run(strat, candles)
    assert any(s.kind is SignalKind.EXIT and "blackout" in s.reason for s in sigs)
