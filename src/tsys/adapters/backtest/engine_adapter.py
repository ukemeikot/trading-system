"""EventDrivenBacktestEngine — the default BacktestEngine.

Why a custom engine (not vectorbt / backtesting.py): the spec's non-negotiables
are (B4.2) pure strategies identically runnable in backtest and paper, and (B4.3)
ONE cost model everywhere. Off-the-shelf libraries fill through their own broker
with a single flat commission and cannot express our per-market maker/taker fees,
per-pair spread, slippage, or post-only limit entries — using one would recreate
the backtest/paper cost divergence B4.3 forbids. This engine instead feeds closed
candles to the pure strategy and fills via the SAME domain CostModel the
PaperBroker (M5) uses. It is lookahead-impossible by construction: a strategy only
ever receives the current closed candle, and every entry fills at the *next* bar.

Fill model (pessimistic, deterministic):
  - MARKET entry: fills at the next candle's open (taker).
  - POST_ONLY/LIMIT entry: rests at limit_price; fills (maker) only if a later
    candle within the timeout trades through it; else cancelled.
  - Exit priority per bar (SPEC D2.4, first to occur): requested/event exit ->
    stop -> target -> time-stop. Stop gaps fill at the worse of stop/open; target
    fills at the limit price (no gap bonus). Exits skip the entry bar itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from tsys.application.dto import BacktestConfig, BacktestResult, Trade
from tsys.application.ports import BacktestEngine
from tsys.domain.costs import CostConfig, CostModel, CryptoCosts, ForexPairCosts, Liquidity
from tsys.domain.entities import Candle, Order, OrderType, Signal, SignalKind
from tsys.domain.execution import OpenPosition, check_exit
from tsys.domain.risk import PortfolioState, RiskPolicy
from tsys.domain.sizing import PositionSizer
from tsys.domain.strategies.base import Strategy
from tsys.domain.values import Direction, Pair, Side


def _d(x: float | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _scale_costs(costs: CostConfig, mult: Decimal) -> CostConfig:
    """Scale slippage (crypto) and spread (forex) for the double-slippage stress test."""
    if mult == 1:
        return costs
    c = costs.crypto
    return CostConfig(
        crypto=CryptoCosts(
            taker_fee_pct=c.taker_fee_pct,
            maker_fee_pct=c.maker_fee_pct,
            slippage_pct=c.slippage_pct * mult,
        ),
        forex={
            sym: ForexPairCosts(spread_pips=fx.spread_pips * mult, pip_size=fx.pip_size)
            for sym, fx in costs.forex.items()
        },
    )


@dataclass(slots=True)
class _Pending:
    direction: Direction
    order_type: OrderType
    limit_price: float | None
    stop_price: float
    target_price: float | None
    max_hold_minutes: int | None
    quantity: Decimal
    expiry_ts: datetime | None


class EventDrivenBacktestEngine(BacktestEngine):
    def run(
        self,
        strategy: Strategy[Any],
        candles: Sequence[Candle],
        config: BacktestConfig,
    ) -> BacktestResult:
        if not candles:
            return BacktestResult(config.initial_equity, config.initial_equity)

        pair = candles[0].pair
        cost = CostModel(_scale_costs(config.costs, config.slippage_multiplier))
        sizer = PositionSizer(config.bounds)
        policy = RiskPolicy(config.risk_limits)

        equity = config.initial_equity
        hwm = equity
        day_start_equity = equity
        day_realized = Decimal(0)
        current_day = candles[0].ts.date()

        position: OpenPosition | None = None
        pending: _Pending | None = None
        state = strategy.initial_state()
        trades: list[Trade] = []
        curve: list[tuple[datetime, Decimal]] = []
        vetoes = 0

        def close_position(pos: OpenPosition, ref: float, liquidity: Liquidity, reason: str,
                           ts: datetime) -> None:
            nonlocal position, equity, day_realized, hwm
            exit_side = pos.side.opposite
            fill = float(cost.fill_price(ref, exit_side, pair, liquidity))
            exit_fee = cost.fee(_d(fill) * pos.quantity, pair, liquidity).amount
            sign = Decimal(pos.side.sign)
            gross = sign * (_d(ref) - _d(pos.entry_ref)) * pos.quantity
            net_price = sign * (_d(fill) - _d(pos.entry_fill)) * pos.quantity
            fees = pos.entry_fee + exit_fee
            total_costs = (gross - net_price) + fees
            net = net_price - fees
            trades.append(
                Trade(
                    entry_ts=pos.opened_ts, exit_ts=ts, side=pos.side, quantity=pos.quantity,
                    entry_price=pos.entry_fill, exit_price=fill, gross_pnl=gross,
                    costs=total_costs, net_pnl=net, exit_reason=reason,
                )
            )
            equity += net
            day_realized += net
            hwm = max(hwm, equity)
            position = None

        for candle in candles:
            # -- day boundary: reset daily risk accounting
            if candle.ts.date() != current_day:
                current_day = candle.ts.date()
                day_start_equity = equity
                day_realized = Decimal(0)

            entry_bar = False

            # -- 1. resolve a pending entry against this candle
            if pending is not None:
                filled = _try_fill(pending, candle, cost, pair)
                if filled is not None:
                    ref, fill, liquidity = filled
                    entry_fee = cost.fee(_d(fill) * pending.quantity, pair, liquidity).amount
                    position = OpenPosition(
                        side=pending.direction.entry_side, quantity=pending.quantity,
                        entry_ref=ref, entry_fill=fill, entry_fee=entry_fee,
                        stop_price=pending.stop_price, target_price=pending.target_price,
                        max_hold_minutes=pending.max_hold_minutes, opened_ts=candle.ts,
                    )
                    pending = None
                    entry_bar = True
                elif pending.expiry_ts is not None and candle.ts >= pending.expiry_ts:
                    pending = None  # unfilled limit cancelled

            # -- 2. manage an open position (never on its own entry bar)
            if position is not None and not entry_bar:
                ex = check_exit(position, candle)
                if ex is not None:
                    close_position(position, ex.ref_price, ex.liquidity, ex.reason, candle.ts)

            # -- 3. feed the closed candle to the pure strategy
            signal, state = strategy.on_candle(candle, state)

            # -- 4. act on the signal
            if signal is not None:
                if signal.kind is SignalKind.EXIT and position is not None:
                    position.exit_requested = True  # flatten at next bar open
                elif signal.kind is SignalKind.ENTER and position is None and pending is None:
                    made = _prepare_entry(
                        signal, candle, equity, config, sizer, policy, pair,
                        PortfolioState(
                            equity=equity, high_water_mark=hwm,
                            day_start_equity=day_start_equity, day_realized_pnl=day_realized,
                        ),
                    )
                    if made is None:
                        vetoes += 1
                    else:
                        pending = made

            # -- 5. mark-to-market equity point (costless MTM of any open position)
            mtm = equity
            if position is not None:
                mtm = equity + Decimal(position.side.sign) * (
                    _d(candle.close) - _d(position.entry_fill)
                ) * position.quantity
            curve.append((candle.ts, mtm))

        # -- force-flatten any position left open at the end of the data
        if position is not None:
            close_position(position, candles[-1].close, Liquidity.TAKER, "end_of_data",
                           candles[-1].ts)

        return BacktestResult(
            initial_equity=config.initial_equity, final_equity=equity, trades=trades,
            equity_curve=curve, vetoes=vetoes,
        )


# -- module-level helpers (pure) ------------------------------------------


def _try_fill(
    pending: _Pending, candle: Candle, cost: CostModel, pair: Pair
) -> tuple[float, float, Liquidity] | None:
    """Return (reference_price, fill_price, liquidity) if the pending order fills."""
    side = pending.direction.entry_side
    if pending.order_type is OrderType.MARKET:
        ref = candle.open
        return ref, float(cost.fill_price(ref, side, pair, Liquidity.TAKER)), Liquidity.TAKER
    # POST_ONLY / LIMIT: rests at limit_price, fills maker if the bar trades through it
    limit = pending.limit_price
    if limit is None:
        return None
    if side is Side.BUY and candle.low <= limit:
        return limit, float(cost.fill_price(limit, side, pair, Liquidity.MAKER)), Liquidity.MAKER
    if side is Side.SELL and candle.high >= limit:
        return limit, float(cost.fill_price(limit, side, pair, Liquidity.MAKER)), Liquidity.MAKER
    return None


def _prepare_entry(
    signal: Signal, candle: Candle, equity: Decimal, config: BacktestConfig,
    sizer: PositionSizer, policy: RiskPolicy, pair: Pair, state: PortfolioState,
) -> _Pending | None:
    """Size + risk-check an entry. Returns a pending order, or None if vetoed."""
    if signal.stop_price is None:
        return None
    is_limit = signal.order_type in (OrderType.LIMIT, OrderType.POST_ONLY)
    ref = signal.limit_price if (is_limit and signal.limit_price is not None) else candle.close
    stop_distance = abs(ref - signal.stop_price)
    sizing = sizer.size(equity, config.risk_pct, ref, stop_distance, pair)
    if not sizing.ok:
        return None

    order = Order(
        ts=candle.ts, pair=pair, side=signal.direction.entry_side, quantity=float(sizing.quantity),
        order_type=signal.order_type, stop_price=signal.stop_price, limit_price=signal.limit_price,
    )
    if not policy.evaluate(order, state):
        return None

    expiry: datetime | None = None
    if is_limit:
        timeout = int(signal.meta.get("entry_timeout_minutes", 2))  # type: ignore[arg-type]
        expiry = candle.ts + timedelta(minutes=timeout)
    return _Pending(
        direction=signal.direction, order_type=signal.order_type, limit_price=signal.limit_price,
        stop_price=signal.stop_price, target_price=signal.target_price,
        max_hold_minutes=signal.max_hold_minutes, quantity=sizing.quantity, expiry_ts=expiry,
    )
