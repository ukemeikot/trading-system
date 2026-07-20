"""Strategy registry — maps a name to a constructed pure strategy (SPEC M3/M4).

Composition detail (frameworks): entrypoints look strategies up by name and pass
per-strategy params from strategies.yaml, the market, and (for quiet_scalper) the
imported news calendar. Ablation flags let the validation battery toggle the news
and regime filters (D2.7).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tsys.domain.entities import NewsEvent
from tsys.domain.strategies.baselines import BuyAndHold, RandomEntry
from tsys.domain.strategies.meanrev import MeanRev
from tsys.domain.strategies.momentum import Momentum
from tsys.domain.strategies.quiet_scalper import QuietScalper
from tsys.domain.values import Market

_NAMES = ["buy_and_hold", "random_entry", "momentum", "meanrev", "quiet_scalper"]


def build_strategy(
    name: str,
    strategies_cfg: dict[str, Any] | None = None,
    market: Market = Market.CRYPTO,
    news_events: Sequence[NewsEvent] | None = None,
    use_news_filter: bool = True,
    use_regime_filter: bool = True,
) -> Any:
    cfg = strategies_cfg or {}
    p = cfg.get(name, {}) if isinstance(cfg, dict) else {}

    if name == "buy_and_hold":
        return BuyAndHold()
    if name == "random_entry":
        return RandomEntry(seed=int(p.get("seed", 1)))
    if name == "momentum":
        return Momentum(
            ema_fast=int(p.get("ema_fast", 20)), ema_slow=int(p.get("ema_slow", 50)),
            atr_period=int(p.get("atr_period", 14)),
            atr_stop_mult=float(p.get("atr_stop_mult", 2.0)),
        )
    if name == "meanrev":
        return MeanRev(
            rsi_period=int(p.get("rsi_period", 14)),
            rsi_oversold=float(p.get("rsi_oversold", 30)),
            rsi_overbought=float(p.get("rsi_overbought", 70)),
            atr_period=int(p.get("atr_period", 14)),
            atr_stop_mult=float(p.get("atr_stop_mult", 1.5)),
        )
    if name == "quiet_scalper":
        sessions = p.get("sessions", {})
        key = "GBP/USD" if market is Market.FOREX else "crypto"
        regime = p.get("regime", {})
        return QuietScalper(
            market=market,
            sessions=sessions.get(key),
            band_k=float(p.get("vwap_band_k", 2.0)),
            atr_stop_mult=float(p.get("atr_stop_mult", 1.2)),
            hold_cap_minutes=int(p.get("hold_cap_minutes", 30)),
            entry_timeout_minutes=int(p.get("entry_limit_timeout_minutes", 2)),
            regime_median_window_days=int(regime.get("atr_median_window_days", 20)),
            trend_veto_mult=float(regime.get("trend_veto_mult", 0.5)),
            news_events=list(news_events) if news_events else None,
            use_news_filter=use_news_filter,
            use_regime_filter=use_regime_filter,
        )
    raise KeyError(f"unknown strategy: {name!r} (available: {available()})")


def available() -> list[str]:
    return list(_NAMES)
