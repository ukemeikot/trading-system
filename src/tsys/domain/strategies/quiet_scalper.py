"""Quiet Window Scalper — the primary strategy (SPEC D2). Pure, on 1m candles.

Short-duration VWAP mean reversion in low-volatility windows. Fades small
overextensions of session-anchored VWAP bands back to the anchor, flat within
30 minutes. Trades only in quiet, ranging tape, avoids scheduled news by
construction, and halts on unscheduled volatility spikes.

Filters (all gating a new entry), in the order they veto:
  1. session window (D2.2)                       — time-of-day only
  2. volatility-spike halt (D2.3b)               — 1m range > mult * ATR(14,1m)
  3. scheduled-news blackout (D2.3a)             — toggle via use_news_filter
  4. quiet/ranging regime (D2.3c)                — toggle via use_regime_filter
  5. band arm -> rejection-confirmation trigger  — post-only limit entry (D2.4)

Ablation: use_news_filter / use_regime_filter toggle filters 3 and 4 so the
validation battery can measure each filter's contribution (D2.7).

Not modelled here (live-only, M5 — they need tick spread / trade-outcome feedback
that a pure on_candle does not receive): the spread-blowout and consecutive-loss
circuit breakers. Documented rather than silently omitted.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tsys.domain.entities import Candle, NewsEvent, OrderType, Signal, SignalKind
from tsys.domain.regime import RegimeClassifier, RegimeInputs
from tsys.domain.strategies.streaming import StreamingATR, StreamingEMA
from tsys.domain.values import BlackoutWindow, Direction, Market


def _parse_sessions(windows: list[str]) -> list[tuple[int, int]]:
    """['08:00-11:00', ...] -> [(minute_of_day_start, end), ...]."""
    out: list[tuple[int, int]] = []
    for w in windows:
        start_s, _, end_s = w.partition("-")
        out.append((_mod(start_s), _mod(end_s)))
    return out


def _mod(hhmm: str) -> int:
    h, _, m = hhmm.strip().partition(":")
    return int(h) * 60 + int(m)


def _default_sessions(market: Market) -> list[tuple[int, int]]:
    if market is Market.FOREX:
        return [( _mod("08:00"), _mod("11:00")), (_mod("13:30"), _mod("16:00"))]
    return [(_mod("07:00"), _mod("16:00"))]


@dataclass(slots=True)
class QuietScalperState:
    atr1m: StreamingATR
    atr5m: StreamingATR
    ema20_5m: StreamingEMA
    ema200_5m: StreamingEMA
    atr_pct_hist: deque[float]
    # session VWAP + residual accumulators (reset each session anchor)
    cum_pv: float = 0.0
    cum_v: float = 0.0
    n: int = 0
    sum_r: float = 0.0
    sum_r2: float = 0.0
    prev_in_session: bool = False
    prev_date: object = None
    # 5m bucket aggregation
    bucket_key: datetime | None = None
    b_high: float = 0.0
    b_low: float = 0.0
    b_close: float = 0.0
    atr5m_val: float | None = None
    ema20_val: float | None = None
    ema200_val: float | None = None
    last5m_close: float | None = None
    # entry arming + halts
    armed_long: bool = False
    armed_short: bool = False
    halt_until: datetime | None = None
    meta: dict[str, object] = field(default_factory=dict)


class QuietScalper:
    name = "quiet_scalper"

    def __init__(
        self,
        market: Market = Market.CRYPTO,
        sessions: list[str] | None = None,
        band_k: float = 2.0,
        atr_stop_mult: float = 1.2,
        atr_period: int = 14,
        hold_cap_minutes: int = 30,
        entry_timeout_minutes: int = 2,
        vol_spike_mult: float = 3.0,
        vol_spike_halt_minutes: int = 60,
        min_session_bars: int = 20,
        news_events: list[NewsEvent] | None = None,
        use_news_filter: bool = True,
        use_regime_filter: bool = True,
        regime_median_window_days: int = 20,
        trend_veto_mult: float = 0.5,
    ) -> None:
        self._market = market
        self._sessions = _parse_sessions(sessions) if sessions else _default_sessions(market)
        self._k = band_k
        self._stop_mult = atr_stop_mult
        self._atr_period = atr_period
        self._hold_cap = hold_cap_minutes
        self._entry_timeout = entry_timeout_minutes
        self._spike_mult = vol_spike_mult
        self._spike_halt = vol_spike_halt_minutes
        self._min_bars = min_session_bars
        self._use_news = use_news_filter
        self._use_regime = use_regime_filter
        self._trend_veto = trend_veto_mult
        self._regime = RegimeClassifier(trend_veto_mult)
        # 5m bars per day * window -> bounded history for the ATR% median
        self._hist_len = regime_median_window_days * 24 * 12
        self._blackouts: list[BlackoutWindow] = [e.blackout() for e in (news_events or [])]

    def initial_state(self) -> QuietScalperState:
        return QuietScalperState(
            atr1m=StreamingATR(self._atr_period),
            atr5m=StreamingATR(self._atr_period),
            ema20_5m=StreamingEMA(20),
            ema200_5m=StreamingEMA(200),
            atr_pct_hist=deque(maxlen=self._hist_len),
        )

    # -- filters ----------------------------------------------------------
    def _in_session(self, ts: datetime) -> bool:
        mod = ts.hour * 60 + ts.minute
        return any(start <= mod < end for start, end in self._sessions)

    def _blackout_blocks(self, ts: datetime) -> bool:
        return self._use_news and any(w.blocks_entry(ts) for w in self._blackouts)

    def _blackout_requires_flat(self, ts: datetime) -> bool:
        return self._use_news and any(w.requires_flat(ts) for w in self._blackouts)

    def _regime_ok(self, state: QuietScalperState, price: float) -> bool:
        if not self._use_regime:
            return True
        if (
            state.atr5m_val is None or state.ema20_val is None
            or state.ema200_val is None or len(state.atr_pct_hist) < 2
        ):
            return False
        atr_pct = state.atr5m_val / price * 100 if price else float("nan")
        inp = RegimeInputs(
            atr_pct=atr_pct, atr_pct_median_20d=statistics.median(state.atr_pct_hist),
            ema_fast=state.ema20_val, ema_slow=state.ema200_val, atr_5m=state.atr5m_val,
        )
        return self._regime.qualifies(inp)

    # -- 5m aggregation for the regime filter -----------------------------
    def _update_5m(self, candle: Candle, state: QuietScalperState) -> None:
        key = candle.ts.replace(minute=candle.ts.minute - candle.ts.minute % 5, second=0,
                                microsecond=0)
        if state.bucket_key is None:
            state.bucket_key = key
            state.b_high, state.b_low, state.b_close = candle.high, candle.low, candle.close
            return
        if key != state.bucket_key:
            # finalize the completed 5m bar
            state.atr5m_val = state.atr5m.update(state.b_high, state.b_low, state.b_close)
            state.ema20_val = state.ema20_5m.update(state.b_close)
            state.ema200_val = state.ema200_5m.update(state.b_close)
            state.last5m_close = state.b_close
            if state.atr5m_val is not None and state.b_close:
                state.atr_pct_hist.append(state.atr5m_val / state.b_close * 100)
            state.bucket_key = key
            state.b_high, state.b_low, state.b_close = candle.high, candle.low, candle.close
        else:
            state.b_high = max(state.b_high, candle.high)
            state.b_low = min(state.b_low, candle.low)
            state.b_close = candle.close

    def on_candle(
        self, candle: Candle, state: QuietScalperState
    ) -> tuple[Signal | None, QuietScalperState]:
        ts = candle.ts
        trailing_atr = state.atr1m.value  # ATR *before* this bar, for spike detection
        atr1m = state.atr1m.update(candle.high, candle.low, candle.close)
        self._update_5m(candle, state)

        # -- session anchor: reset VWAP/residual accumulators on a new session
        in_sess = self._in_session(ts)
        new_session = in_sess and (not state.prev_in_session or state.prev_date != ts.date())
        if new_session:
            state.cum_pv = state.cum_v = 0.0
            state.n = 0
            state.sum_r = state.sum_r2 = 0.0
            state.armed_long = state.armed_short = False
        state.prev_in_session, state.prev_date = in_sess, ts.date()

        # -- update session VWAP (equal-weight fallback when volume is 0, e.g. forex)
        vwap: float | None = None
        if in_sess:
            tp = (candle.high + candle.low + candle.close) / 3.0
            w = candle.volume if candle.volume > 0 else 1.0
            state.cum_pv += tp * w
            state.cum_v += w
            vwap = state.cum_pv / state.cum_v if state.cum_v > 0 else None
            if vwap is not None:
                r = candle.close - vwap
                state.n += 1
                state.sum_r += r
                state.sum_r2 += r * r

        # -- 2. volatility-spike halt (flatten + halt new entries). Compare this bar's
        #       range to the *trailing* ATR so the spike bar can't inflate its own gate.
        if (
            trailing_atr is not None and trailing_atr > 0
            and (candle.high - candle.low) > self._spike_mult * trailing_atr
        ):
            state.halt_until = ts + timedelta(minutes=self._spike_halt)
            state.armed_long = state.armed_short = False
            return _exit(candle, "volatility spike halt"), state

        # -- 3. scheduled-news force-flat
        if self._blackout_requires_flat(ts):
            state.armed_long = state.armed_short = False
            return _exit(candle, "news blackout flatten"), state

        # -- entry gating
        halted = state.halt_until is not None and ts < state.halt_until
        tradeable = (
            in_sess and not halted and not self._blackout_blocks(ts)
            and atr1m is not None and atr1m > 0 and vwap is not None and state.n >= self._min_bars
        )
        if not tradeable or not self._regime_ok(state, candle.close):
            state.armed_long = state.armed_short = False
            return None, state

        assert vwap is not None and atr1m is not None
        stdev = _stdev(state.n, state.sum_r, state.sum_r2)
        lower = vwap - self._k * stdev
        upper = vwap + self._k * stdev
        close = candle.close

        # -- 5. arm on a band pierce, enter on the rejection-confirmation candle
        if state.armed_long:
            if close > lower:  # closed back inside -> trigger long
                state.armed_long = False
                return _enter(candle, Direction.LONG, limit=close, target=vwap,
                              stop=close - self._stop_mult * atr1m,
                              hold=self._hold_cap, timeout=self._entry_timeout), state
        elif close <= lower:
            state.armed_long = True

        if state.armed_short:
            if close < upper:  # closed back inside -> trigger short
                state.armed_short = False
                return _enter(candle, Direction.SHORT, limit=close, target=vwap,
                              stop=close + self._stop_mult * atr1m,
                              hold=self._hold_cap, timeout=self._entry_timeout), state
        elif close >= upper:
            state.armed_short = True

        return None, state


def _stdev(n: int, sum_r: float, sum_r2: float) -> float:
    if n <= 0:
        return 0.0
    var = sum_r2 / n - (sum_r / n) ** 2
    return var**0.5 if var > 0 else 0.0


def _exit(candle: Candle, reason: str) -> Signal:
    return Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                  direction=Direction.LONG, reason=reason)


def _enter(
    candle: Candle, direction: Direction, limit: float, target: float, stop: float,
    hold: int, timeout: int,
) -> Signal:
    return Signal(
        ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER, direction=direction,
        stop_price=stop, target_price=target, order_type=OrderType.POST_ONLY, limit_price=limit,
        max_hold_minutes=hold, reason="quiet-window band fade",
        meta={"entry_timeout_minutes": timeout},
    )
