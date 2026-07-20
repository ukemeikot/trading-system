"""CostModel — the single source of fee/spread/slippage truth (B4.3).

The *same* model serves the backtester and the PaperBroker; backtest and paper
costs can never diverge. All arithmetic is Decimal so the F1 round-trip property
test holds exactly.

Pessimism (SPEC C1 defaults):
  - crypto: taker 0.10%/side, maker 0.02%/side, slippage 0.05%/taker-fill.
  - forex : spread per pair (GBP/USD 1.8 pips), crossed on entry and exit; no commission.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tsys.domain.values import Money, Pair, Side


class Liquidity(StrEnum):
    """Whether a fill takes liquidity (crosses the book) or makes it (rests)."""

    MAKER = "maker"
    TAKER = "taker"


def _dec(x: Decimal | int | str | float) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


@dataclass(frozen=True, slots=True)
class CryptoCosts:
    taker_fee_pct: Decimal  # percent, e.g. Decimal("0.10")
    maker_fee_pct: Decimal
    slippage_pct: Decimal  # percent, applied to taker fills only


@dataclass(frozen=True, slots=True)
class ForexPairCosts:
    spread_pips: Decimal
    pip_size: Decimal = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class CostConfig:
    crypto: CryptoCosts
    forex: dict[str, ForexPairCosts]  # keyed by pair symbol, e.g. "GBP/USD"


@dataclass(frozen=True, slots=True)
class RoundTripCost:
    """Decomposition of the cost of opening and closing a position at one price."""

    entry_price: Decimal
    exit_price: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    price_cost: Decimal  # loss from slippage/spread (>= 0)
    fee_cost: Decimal  # entry_fee + exit_fee
    total_cost: Money  # price_cost + fee_cost, as Money

    @property
    def net_pnl_at_zero_move(self) -> Decimal:
        """PnL of the round trip when price does not move = -(total cost)."""
        return -(self.price_cost + self.fee_cost)


class CostModel:
    """Computes fill prices and fees. Market-aware; nothing else in the system is."""

    def __init__(self, config: CostConfig) -> None:
        self._cfg = config

    # -- fill price -------------------------------------------------------
    def fill_price(
        self, reference_price: Decimal | float, side: Side, pair: Pair, liquidity: Liquidity
    ) -> Decimal:
        """Adjust a reference (mid) price for slippage (crypto taker) or half-spread (forex)."""
        p = _dec(reference_price)
        if pair.market.value == "crypto":
            if liquidity is Liquidity.MAKER:
                return p  # a resting limit does not cross the book
            slip = self._cfg.crypto.slippage_pct / Decimal(100)
            return p * (Decimal(1) + Decimal(side.sign) * slip)
        # forex: cross the half-spread regardless of liquidity
        fx = self._forex(pair)
        half_spread = fx.spread_pips * fx.pip_size / Decimal(2)
        return p + Decimal(side.sign) * half_spread

    # -- fees -------------------------------------------------------------
    def fee(self, notional: Decimal | float, pair: Pair, liquidity: Liquidity) -> Money:
        """Commission on a fill. Forex is spread-priced (zero commission)."""
        n = _dec(notional)
        if pair.market.value == "crypto":
            pct = (
                self._cfg.crypto.maker_fee_pct
                if liquidity is Liquidity.MAKER
                else self._cfg.crypto.taker_fee_pct
            )
            return Money(n * pct / Decimal(100), pair.quote)
        return Money(Decimal(0), pair.quote)

    # -- round trip -------------------------------------------------------
    def round_trip(
        self,
        price: Decimal | float,
        quantity: Decimal | float,
        pair: Pair,
        entry_liquidity: Liquidity = Liquidity.TAKER,
        exit_liquidity: Liquidity = Liquidity.TAKER,
    ) -> RoundTripCost:
        """Cost of buying then selling `quantity` at the same reference `price`."""
        p = _dec(price)
        qty = _dec(quantity)
        entry_price = self.fill_price(p, Side.BUY, pair, entry_liquidity)
        exit_price = self.fill_price(p, Side.SELL, pair, exit_liquidity)
        entry_fee = self.fee(entry_price * qty, pair, entry_liquidity).amount
        exit_fee = self.fee(exit_price * qty, pair, exit_liquidity).amount
        # At zero price move, (exit_price - entry_price) is <= 0; the negative is the cost.
        price_cost = (entry_price - exit_price) * qty
        fee_cost = entry_fee + exit_fee
        return RoundTripCost(
            entry_price=entry_price,
            exit_price=exit_price,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            price_cost=price_cost,
            fee_cost=fee_cost,
            total_cost=Money(price_cost + fee_cost, pair.quote),
        )

    def _forex(self, pair: Pair) -> ForexPairCosts:
        try:
            return self._cfg.forex[pair.symbol]
        except KeyError:
            raise ValueError(f"no forex cost config for {pair.symbol}") from None
