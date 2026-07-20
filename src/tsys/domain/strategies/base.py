"""Strategy protocol — the pure contract every strategy implements (SPEC B4.2).

on_candle() takes market data + the strategy's own state and returns a Signal or
None. No network, no clock reads, no broker access — identically runnable in
backtest and paper modes. State is passed in and returned so the function stays
pure (no hidden mutation), which makes the determinism test (F1) trivially hold.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from tsys.domain.entities import Candle, Signal

StateT = TypeVar("StateT")


class Strategy(Protocol[StateT]):
    name: str

    def initial_state(self) -> StateT:
        """Return a fresh state object for a new run."""
        ...

    def on_candle(self, candle: Candle, state: StateT) -> tuple[Signal | None, StateT]:
        """Process one *closed* candle. Return (signal_or_none, new_state)."""
        ...
