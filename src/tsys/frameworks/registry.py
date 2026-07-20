"""Strategy registry — maps a name to a constructed pure strategy (SPEC M3/M4).

Composition detail (frameworks): entrypoints look strategies up by name and pass
per-strategy params from strategies.yaml. Baselines take no params; real strategies
(M4) read their block from the config dict.
"""

from __future__ import annotations

from typing import Any

from tsys.domain.strategies.baselines import BuyAndHold, RandomEntry

# name -> factory(params: dict) -> strategy
_BASELINES: dict[str, Any] = {
    "buy_and_hold": lambda p: BuyAndHold(),
    "random_entry": lambda p: RandomEntry(seed=int(p.get("seed", 1))),
}


def build_strategy(name: str, strategies_cfg: dict[str, Any] | None = None) -> Any:
    cfg = strategies_cfg or {}
    params = cfg.get(name, {}) if isinstance(cfg, dict) else {}
    if name in _BASELINES:
        return _BASELINES[name](params)
    raise KeyError(f"unknown strategy: {name!r} (available: {sorted(available())})")


def available() -> list[str]:
    return sorted(_BASELINES)
