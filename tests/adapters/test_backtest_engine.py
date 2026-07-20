"""EventDrivenBacktestEngine — determinism, fee-effect, lookahead-impossibility, exits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tsys.adapters.backtest.engine_adapter import EventDrivenBacktestEngine
from tsys.application.dto import BacktestConfig
from tsys.domain.costs import CostConfig, CostModel, CryptoCosts, ForexPairCosts, Liquidity
from tsys.domain.entities import Candle, OrderType, Signal, SignalKind
from tsys.domain.risk import RiskLimits
from tsys.domain.sizing import NotionalBounds
from tsys.domain.strategies.baselines import BuyAndHold
from tsys.domain.values import Direction, Market, Pair

BTC = Pair("BTC", "USDT", Market.CRYPTO)
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _costs() -> CostConfig:
    return CostConfig(
        crypto=CryptoCosts(
            taker_fee_pct=Decimal("0.10"), maker_fee_pct=Decimal("0.02"),
            slippage_pct=Decimal("0.05"),
        ),
        forex={"GBP/USD": ForexPairCosts(spread_pips=Decimal("1.8"))},
    )


def _config(equity: str = "1000", risk: str = "1", slip: str = "1") -> BacktestConfig:
    return BacktestConfig(
        initial_equity=Decimal(equity), risk_pct=Decimal(risk), costs=_costs(),
        risk_limits=RiskLimits(), bounds=NotionalBounds(min_notional=Decimal("10")),
        slippage_multiplier=Decimal(slip),
    )


def _series(prices: list[float], minutes: int = 60) -> list[Candle]:
    """Flat candles (o=h=l=c=price) unless overridden — deterministic OHLC."""
    return [
        Candle(ts=T0 + timedelta(minutes=minutes * i), pair=BTC, timeframe="1m",
               open=p, high=p, low=p, close=p, volume=1.0)
        for i, p in enumerate(prices)
    ]


# -- scripted test strategies --------------------------------------------

@dataclass(slots=True)
class _Once:
    done: bool = False


class EnterThenExit:
    """Enter LONG (market) on the first candle, emit EXIT on every later candle."""

    name = "enter_then_exit"

    def __init__(self, stop: float) -> None:
        self._stop = stop

    def initial_state(self) -> _Once:
        return _Once()

    def on_candle(self, candle: Candle, state: _Once) -> tuple[Signal | None, _Once]:
        if not state.done:
            state.done = True
            return (
                Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                       direction=Direction.LONG, stop_price=self._stop,
                       order_type=OrderType.MARKET), state,
            )
        return (
            Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.EXIT,
                   direction=Direction.LONG), state,
        )


class EnterHold:
    """Enter LONG once with stop/target/max_hold, then do nothing (managed exits)."""

    name = "enter_hold"

    def __init__(self, stop: float, target: float | None = None,
                 order_type: OrderType = OrderType.MARKET, limit: float | None = None,
                 max_hold: int | None = None) -> None:
        self._stop, self._target = stop, target
        self._ot, self._limit, self._max_hold = order_type, limit, max_hold

    def initial_state(self) -> _Once:
        return _Once()

    def on_candle(self, candle: Candle, state: _Once) -> tuple[Signal | None, _Once]:
        if state.done:
            return None, state
        state.done = True
        return (
            Signal(ts=candle.ts, pair=candle.pair, kind=SignalKind.ENTER,
                   direction=Direction.LONG, stop_price=self._stop, target_price=self._target,
                   order_type=self._ot, limit_price=self._limit, max_hold_minutes=self._max_hold),
            state,
        )


# -- tests ----------------------------------------------------------------

def test_determinism_same_inputs_same_output() -> None:
    eng = EventDrivenBacktestEngine()
    candles = _series([100, 101, 102, 101, 103, 104, 100, 105])
    r1 = eng.run(BuyAndHold(), candles, _config())
    r2 = eng.run(BuyAndHold(), candles, _config())
    assert r1.trades == r2.trades
    assert r1.final_equity == r2.final_equity
    assert r1.equity_curve == r2.equity_curve


def test_fee_effect_zero_move_loses_exactly_costs() -> None:
    """On a flat series, a round trip loses exactly the CostModel's round-trip cost."""
    eng = EventDrivenBacktestEngine()
    candles = _series([100.0, 100.0, 100.0, 100.0])  # perfectly flat
    result = eng.run(EnterThenExit(stop=90.0), candles, _config())
    assert result.trade_count == 1
    trade = result.trades[0]
    # Expected cost from the shared CostModel (taker entry, taker exit).
    expected = CostModel(_costs()).round_trip(
        100.0, trade.quantity, BTC, Liquidity.TAKER, Liquidity.TAKER
    )
    assert trade.net_pnl == expected.net_pnl_at_zero_move
    assert result.final_equity == result.initial_equity + expected.net_pnl_at_zero_move


def test_no_lookahead_entry_fills_at_next_open_not_signal_close() -> None:
    eng = EventDrivenBacktestEngine()
    # signal on candle 0 (close 100); candle 1 opens at 200 -> fill must reflect 200, not 100.
    candles = [
        Candle(ts=T0, pair=BTC, timeframe="1m", open=100, high=100, low=100, close=100, volume=1),
        Candle(ts=T0 + timedelta(minutes=1), pair=BTC, timeframe="1m",
               open=200, high=200, low=200, close=200, volume=1),
        Candle(ts=T0 + timedelta(minutes=2), pair=BTC, timeframe="1m",
               open=200, high=200, low=200, close=200, volume=1),
    ]
    result = eng.run(EnterHold(stop=90.0), candles, _config())
    entry = result.trades[0] if result.trades else None
    if entry is None:  # position may still be open at end -> forced close still records the trade
        entry = eng.run(EnterHold(stop=90.0), candles, _config()).trades[0]
    # entry fill = next-bar open (200) * (1 + taker slippage), never the signal close (100).
    assert entry.entry_price > 199.0  # ~200.1, definitely not ~100


def test_target_exit() -> None:
    eng = EventDrivenBacktestEngine()
    candles = [
        Candle(ts=T0, pair=BTC, timeframe="1m", open=100, high=100, low=100, close=100, volume=1),
        Candle(ts=T0 + timedelta(minutes=1), pair=BTC, timeframe="1m",
               open=100, high=100, low=100, close=100, volume=1),  # entry fill here
        Candle(ts=T0 + timedelta(minutes=2), pair=BTC, timeframe="1m",
               open=100, high=110, low=100, close=105, volume=1),  # target 108 hit
    ]
    result = eng.run(EnterHold(stop=95.0, target=108.0), candles, _config())
    assert result.trades[0].exit_reason == "target"


def test_stop_exit() -> None:
    eng = EventDrivenBacktestEngine()
    candles = [
        Candle(ts=T0, pair=BTC, timeframe="1m", open=100, high=100, low=100, close=100, volume=1),
        Candle(ts=T0 + timedelta(minutes=1), pair=BTC, timeframe="1m",
               open=100, high=100, low=100, close=100, volume=1),
        Candle(ts=T0 + timedelta(minutes=2), pair=BTC, timeframe="1m",
               open=100, high=100, low=90, close=92, volume=1),  # stop 95 hit
    ]
    result = eng.run(EnterHold(stop=95.0, target=108.0), candles, _config())
    assert result.trades[0].exit_reason == "stop"


def test_time_stop_exit() -> None:
    eng = EventDrivenBacktestEngine()
    candles = _series([100.0] * 40, minutes=1)  # 40 one-minute bars, flat
    result = eng.run(EnterHold(stop=95.0, target=200.0, max_hold=30), candles, _config())
    assert result.trades[0].exit_reason == "time_stop"


def test_post_only_limit_unfilled_is_cancelled() -> None:
    eng = EventDrivenBacktestEngine()
    # Buy limit at 95 but price never trades down to 95 -> no fill, no trade.
    candles = _series([100.0, 101.0, 102.0, 103.0], minutes=1)
    strat = EnterHold(stop=90.0, order_type=OrderType.POST_ONLY, limit=95.0)
    result = eng.run(strat, candles, _config())
    assert result.trade_count == 0


def test_buy_and_hold_profits_on_rising_series() -> None:
    eng = EventDrivenBacktestEngine()
    candles = _series([100, 110, 120, 130, 140, 150])
    result = eng.run(BuyAndHold(), candles, _config())
    assert result.trade_count == 1
    assert result.net_return_pct > 0
