"""StreamAndTrade — the live paper engine (SPEC M5).

feed -> strategy -> risk -> broker -> persist, event-driven off one candle stream.
Uses the SAME pure strategy, CostModel (via the paper broker) and exit logic
(domain.execution.check_exit) as the backtester, so paper == backtest by
construction; only fill *timing* differs (paper fills at the current price — C1).
Everything is logged: every signal, veto, fill, equity point and latency sample.
`--replay` drives this exact code path from recorded candles.

Circuit breakers in force: kill-switch + daily-loss halt and the consecutive-loss
halt (RiskManager), plus the volatility-spike halt (emitted by quiet_scalper).
The spread-blowout breaker needs a live tick spread (tick path only) — documented,
not silently dropped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from tsys.application.ports import Clock, LatencyRecorder, MarketDataFeed, TradeRepository
from tsys.application.risk_manager import RiskManager
from tsys.domain.costs import Liquidity
from tsys.domain.entities import Candle, Fill, Order, OrderType, Position, Signal, SignalKind
from tsys.domain.execution import OpenPosition, check_exit
from tsys.domain.sizing import PositionSizer
from tsys.domain.strategies.base import Strategy
from tsys.domain.values import Pair


class PaperBrokerPort(Protocol):
    """What the engine needs from a paper broker (kept structural so application
    does not import the adapter). `mark` and `restore_position` are paper-specific
    and deliberately not on the generic Broker port."""

    def mark(self, pair: Pair, price: float) -> None: ...
    async def submit(self, order: Order) -> Fill | None: ...
    async def equity(self) -> float: ...
    def restore_position(self, position: Position) -> None: ...


@dataclass(slots=True)
class StreamResult:
    candles: int = 0
    fills: int = 0
    vetoes: int = 0
    halted: bool = False


def _d(x: float | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


class StreamAndTrade:
    def __init__(
        self,
        feed: MarketDataFeed,
        strategy: Strategy[Any],
        broker: PaperBrokerPort,
        risk: RiskManager,
        sizer: PositionSizer,
        repo: TradeRepository,
        latency: LatencyRecorder,
        clock: Clock,
        timeframe: str,
        risk_pct: Decimal,
    ) -> None:
        self._feed = feed
        self._strategy = strategy
        self._broker = broker
        self._risk = risk
        self._sizer = sizer
        self._repo = repo
        self._latency = latency
        self._clock = clock
        self._timeframe = timeframe
        self._risk_pct = risk_pct
        self._pos: OpenPosition | None = None
        self._halted = False

    async def run(self) -> StreamResult:
        result = StreamResult()
        await self._recover_positions()
        state = self._strategy.initial_state()
        async for candle in self._feed.stream_candles(self._timeframe):
            state = await self._on_candle(candle, state, result)
            result.candles += 1
        result.halted = self._halted
        return result

    async def _recover_positions(self) -> None:
        for pos in await self._repo.load_open_positions():
            self._broker.restore_position(pos)
            self._pos = OpenPosition(
                side=pos.side, quantity=_d(pos.quantity), entry_ref=pos.entry_price,
                entry_fill=pos.entry_price, entry_fee=Decimal(0), stop_price=pos.stop_price,
                target_price=None, max_hold_minutes=None, opened_ts=pos.opened_at,
            )

    async def _on_candle(self, candle: Candle, state: Any, result: StreamResult) -> Any:
        self._broker.mark(candle.pair, candle.close)
        equity = _d(await self._broker.equity())
        self._risk.mark(equity, candle.ts)
        await self._repo.record_equity(candle.ts, float(equity))

        # circuit breaker: kill-switch / daily-loss halt -> flatten + stop opening
        halt, reason = self._risk.check_halt()
        if halt:
            if self._pos is not None:
                await self._close(self._pos, candle, candle.close, Liquidity.TAKER, "halt")
            self._halted = True
            await self._repo.record_decision(
                {"ts": candle.ts.isoformat(), "kind": "halt", "pair": candle.pair.symbol,
                 "reason": reason}
            )
            return state

        # manage the open position's exits (shared logic with the backtester)
        if self._pos is not None:
            ex = check_exit(self._pos, candle)
            if ex is not None:
                await self._close(self._pos, candle, ex.ref_price, ex.liquidity, ex.reason)

        # feed the closed candle to the pure strategy (measure processing latency)
        t0 = time.perf_counter_ns()
        signal, state = self._strategy.on_candle(candle, state)
        t_sig = time.perf_counter_ns()
        await self._latency.record("tick_to_signal", (t_sig - t0) / 1000.0)

        if signal is not None:
            await self._act(signal, candle, t_sig, result)
        return state

    async def _act(self, signal: Signal, candle: Candle, t_sig: int, result: StreamResult) -> None:
        if signal.kind is SignalKind.EXIT:
            if self._pos is not None:
                await self._close(self._pos, candle, candle.close, Liquidity.TAKER, "signal_exit")
            return
        if self._pos is not None or self._halted:
            return  # one position at a time, or halted

        if signal.stop_price is None:
            await self._veto(candle, signal, "stop-less entry", result)
            return
        is_limit = signal.order_type in (OrderType.LIMIT, OrderType.POST_ONLY)
        ref = signal.limit_price if (is_limit and signal.limit_price is not None) else candle.close
        stop_distance = abs(ref - signal.stop_price)
        sizing = self._sizer.size(
            self._risk.equity, self._risk_pct, ref, stop_distance, candle.pair
        )
        if not sizing.ok:
            await self._veto(candle, signal, f"sizing: {sizing.reason}", result)
            return

        order = Order(
            ts=candle.ts, pair=candle.pair, side=signal.direction.entry_side,
            quantity=float(sizing.quantity), order_type=signal.order_type,
            stop_price=signal.stop_price, limit_price=signal.limit_price,
        )
        decision = self._risk.evaluate(order, candle.pair.symbol)
        if not decision.approved:
            await self._veto(candle, signal, decision.reason, result)
            return

        self._broker.mark(candle.pair, ref)  # paper: fill at the reference price ± cost
        fill = await self._broker.submit(order)
        await self._latency.record("signal_to_order", (time.perf_counter_ns() - t_sig) / 1000.0)
        if fill is None:
            return
        self._pos = OpenPosition(
            side=order.side, quantity=_d(order.quantity), entry_ref=ref, entry_fill=fill.price,
            entry_fee=_d(fill.fee), stop_price=signal.stop_price, target_price=signal.target_price,
            max_hold_minutes=signal.max_hold_minutes, opened_ts=candle.ts,
        )
        self._risk.record_open(candle.pair.symbol)
        await self._repo.record_fill(fill)
        await self._repo.record_decision(
            {"ts": candle.ts.isoformat(), "kind": "fill", "pair": candle.pair.symbol,
             "approved": True, "reason": signal.reason, "side": order.side.value,
             "price": fill.price, "qty": order.quantity}
        )
        await self._snapshot(candle)
        result.fills += 1

    async def _close(
        self, pos: OpenPosition, candle: Candle, ref: float, liquidity: Liquidity, reason: str
    ) -> None:
        self._broker.mark(candle.pair, ref)
        exit_order = Order(
            ts=candle.ts, pair=candle.pair, side=pos.side.opposite, quantity=float(pos.quantity),
            order_type=OrderType.LIMIT if liquidity is Liquidity.MAKER else OrderType.MARKET,
            reduce_only=True,
        )
        fill = await self._broker.submit(exit_order)
        self._pos = None
        if fill is None:
            return
        sign = Decimal(pos.side.sign)
        net = (
            sign * (_d(fill.price) - _d(pos.entry_fill)) * pos.quantity
            - pos.entry_fee - _d(fill.fee)
        )
        self._risk.record_close(candle.pair.symbol, net)
        await self._repo.record_fill(fill)
        await self._repo.record_decision(
            {"ts": candle.ts.isoformat(), "kind": "exit", "pair": candle.pair.symbol,
             "reason": reason, "price": fill.price, "net_pnl": float(net)}
        )
        await self._clear_snapshot(candle.pair)

    async def _veto(
        self, candle: Candle, signal: Signal, reason: str, result: StreamResult
    ) -> None:
        result.vetoes += 1
        await self._repo.record_decision(
            {"ts": candle.ts.isoformat(), "kind": "veto", "pair": candle.pair.symbol,
             "approved": False, "reason": reason, "signal": signal.reason}
        )

    async def _snapshot(self, candle: Candle) -> None:
        upsert = getattr(self._repo, "upsert_position", None)
        if upsert is not None and self._pos is not None:
            await upsert(
                Position(pair=candle.pair, side=self._pos.side,
                         quantity=float(self._pos.quantity), entry_price=self._pos.entry_fill,
                         stop_price=self._pos.stop_price, opened_at=self._pos.opened_ts)
            )

    async def _clear_snapshot(self, pair: Pair) -> None:
        clear = getattr(self._repo, "clear_position", None)
        if clear is not None:
            await clear(pair)
