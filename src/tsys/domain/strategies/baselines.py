"""Baseline strategies (SPEC M3): buy-and-hold and random-entry.

These exist so a real strategy's cost-adjusted equity curve can be judged against
naive references. They are pure and deterministic (random-entry seeds its own PRNG
from its state so a rerun reproduces the identical decision log — F1).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from tsys.domain.entities import Candle, OrderType, Signal, SignalKind
from tsys.domain.values import Direction


@dataclass(slots=True)
class BuyAndHoldState:
    entered: bool = False


class BuyAndHold:
    """Enter long on the first candle, never exit (held to end-of-data)."""

    name = "buy_and_hold"

    def __init__(self, stop_frac: float = 0.99) -> None:
        # A nominal far-away stop so the risk manager accepts the (stop-required) entry.
        self._stop_frac = stop_frac

    def initial_state(self) -> BuyAndHoldState:
        return BuyAndHoldState()

    def on_candle(
        self, candle: Candle, state: BuyAndHoldState
    ) -> tuple[Signal | None, BuyAndHoldState]:
        if state.entered:
            return None, state
        state.entered = True
        signal = Signal(
            ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER, direction=Direction.LONG,
            stop_price=candle.close * self._stop_frac, order_type=OrderType.MARKET,
            reason="buy_and_hold entry",
        )
        return signal, state


@dataclass(slots=True)
class RandomEntryState:
    rng: random.Random
    in_trade: bool = False


class RandomEntry:
    """Randomly enter/exit with fixed probability per bar. Deterministic given a seed."""

    name = "random_entry"

    def __init__(
        self, seed: int = 1, enter_prob: float = 0.02, exit_prob: float = 0.1,
        stop_frac: float = 0.98,
    ) -> None:
        self._seed = seed
        self._enter_prob = enter_prob
        self._exit_prob = exit_prob
        self._stop_frac = stop_frac

    def initial_state(self) -> RandomEntryState:
        return RandomEntryState(rng=random.Random(self._seed))

    def on_candle(
        self, candle: Candle, state: RandomEntryState
    ) -> tuple[Signal | None, RandomEntryState]:
        if state.in_trade:
            if state.rng.random() < self._exit_prob:
                state.in_trade = False
                return (
                    Signal(
                        ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                        direction=Direction.LONG, reason="random exit",
                    ),
                    state,
                )
            return None, state
        if state.rng.random() < self._enter_prob:
            state.in_trade = True
            return (
                Signal(
                    ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                    direction=Direction.LONG, stop_price=candle.close * self._stop_frac,
                    order_type=OrderType.MARKET, reason="random entry",
                ),
                state,
            )
        return None, state
