"""Mean reversion — RSI extremes (SPEC D1).

Long/short reversion on the configured timeframe (1h by default): go long when RSI
falls below the oversold threshold, short when it rises above overbought; exit when
RSI returns through the midline (50). Hard ATR stop on entry. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass

from tsys.domain.entities import Candle, OrderType, Signal, SignalKind
from tsys.domain.strategies.streaming import StreamingATR, StreamingRSI
from tsys.domain.values import Direction


@dataclass(slots=True)
class MeanRevState:
    rsi: StreamingRSI
    atr: StreamingATR
    side: Direction | None = None  # current intended position side, for exit logic


class MeanRev:
    name = "meanrev"

    def __init__(
        self, rsi_period: int = 14, rsi_oversold: float = 30.0, rsi_overbought: float = 70.0,
        atr_period: int = 14, atr_stop_mult: float = 1.5,
    ) -> None:
        self._rp, self._os, self._ob = rsi_period, rsi_oversold, rsi_overbought
        self._ap, self._stop_mult = atr_period, atr_stop_mult

    def initial_state(self) -> MeanRevState:
        return MeanRevState(rsi=StreamingRSI(self._rp), atr=StreamingATR(self._ap))

    def on_candle(self, candle: Candle, state: MeanRevState) -> tuple[Signal | None, MeanRevState]:
        rsi = state.rsi.update(candle.close)
        atr = state.atr.update(candle.high, candle.low, candle.close)
        if rsi is None or atr is None or atr <= 0:
            return None, state

        # Exit when RSI crosses back through the midline.
        if state.side is Direction.LONG and rsi >= 50:
            state.side = None
            return (
                Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                       direction=Direction.LONG, reason="rsi reverted to mid"),
                state,
            )
        if state.side is Direction.SHORT and rsi <= 50:
            state.side = None
            return (
                Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                       direction=Direction.SHORT, reason="rsi reverted to mid"),
                state,
            )

        # Entries at extremes (only when flat).
        if state.side is None:
            if rsi < self._os:
                state.side = Direction.LONG
                return (
                    Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                           direction=Direction.LONG,
                           stop_price=candle.close - self._stop_mult * atr,
                           order_type=OrderType.MARKET, reason="rsi oversold"),
                    state,
                )
            if rsi > self._ob:
                state.side = Direction.SHORT
                return (
                    Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                           direction=Direction.SHORT,
                           stop_price=candle.close + self._stop_mult * atr,
                           order_type=OrderType.MARKET, reason="rsi overbought"),
                    state,
                )
        return None, state
