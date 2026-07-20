"""Momentum — EMA-cross trend following (SPEC D1).

Long/flat trend follower on the configured timeframe (4h by default): enter long
when the fast EMA crosses above the slow EMA (with an ATR trend filter that
requires real volatility and price on the trend side), exit on the opposite
cross. Hard ATR stop set on entry and enforced by the risk manager. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tsys.domain.entities import Candle, OrderType, Signal, SignalKind
from tsys.domain.strategies.streaming import StreamingATR, StreamingEMA
from tsys.domain.values import Direction


@dataclass(slots=True)
class MomentumState:
    fast: StreamingEMA
    slow: StreamingEMA
    atr: StreamingATR
    prev_fast: float | None = None
    prev_slow: float | None = None
    meta: dict[str, object] = field(default_factory=dict)


class Momentum:
    name = "momentum"

    def __init__(
        self, ema_fast: int = 20, ema_slow: int = 50, atr_period: int = 14,
        atr_stop_mult: float = 2.0,
    ) -> None:
        if ema_fast >= ema_slow:
            raise ValueError("ema_fast must be < ema_slow")
        self._ef, self._es, self._ap = ema_fast, ema_slow, atr_period
        self._stop_mult = atr_stop_mult

    def initial_state(self) -> MomentumState:
        return MomentumState(
            fast=StreamingEMA(self._ef), slow=StreamingEMA(self._es), atr=StreamingATR(self._ap)
        )

    def on_candle(
        self, candle: Candle, state: MomentumState
    ) -> tuple[Signal | None, MomentumState]:
        fast = state.fast.update(candle.close)
        slow = state.slow.update(candle.close)
        atr = state.atr.update(candle.high, candle.low, candle.close)

        signal: Signal | None = None
        pf, ps = state.prev_fast, state.prev_slow
        if fast is not None and slow is not None and pf is not None and ps is not None:
            crossed_up = pf <= ps and fast > slow
            crossed_down = pf >= ps and fast < slow
            if crossed_up and atr is not None and atr > 0 and candle.close > slow:
                signal = Signal(
                    ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                    direction=Direction.LONG, stop_price=candle.close - self._stop_mult * atr,
                    order_type=OrderType.MARKET, reason="ema cross up",
                )
            elif crossed_down:
                signal = Signal(
                    ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                    direction=Direction.LONG, reason="ema cross down",
                )

        state.prev_fast, state.prev_slow = fast, slow
        return signal, state
