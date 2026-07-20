"""Config loading + the paper-only guardrail (SPEC F4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tsys.frameworks.config import (
    RefuseToStart,
    build_cost_config,
    build_risk_limits,
    ensure_paper_mode,
    load_settings,
    param_fingerprint,
)


def test_real_settings_load_and_are_paper() -> None:
    s = load_settings("config/settings.yaml")
    assert s.mode == "paper"
    ensure_paper_mode(s)  # must not raise


def test_refuses_live_mode() -> None:
    s = load_settings("config/settings.yaml")
    live = s.model_copy(update={"mode": "live"})
    with pytest.raises(RefuseToStart, match="F2"):
        ensure_paper_mode(live)


def test_build_cost_config_from_settings() -> None:
    cfg = build_cost_config(load_settings("config/settings.yaml"))
    assert cfg.crypto.taker_fee_pct == Decimal("0.1")
    assert cfg.forex["GBP/USD"].spread_pips == Decimal("1.8")


def test_build_risk_limits_from_settings() -> None:
    limits = build_risk_limits(load_settings("config/settings.yaml"))
    assert limits.max_concurrent_positions == 3
    assert limits.kill_switch_drawdown_pct == Decimal("15")


def test_param_fingerprint_stable_and_change_sensitive() -> None:
    s = load_settings("config/settings.yaml")
    cfg = {"quiet_scalper": {"vwap_band_k": 2.0}}
    fp1 = param_fingerprint(s, cfg)
    assert fp1 == param_fingerprint(s, cfg)  # stable / deterministic
    # a changed strategy parameter changes the fingerprint (M6 clock would reset)
    assert fp1 != param_fingerprint(s, {"quiet_scalper": {"vwap_band_k": 2.5}})
    # a changed risk parameter changes it too
    changed = s.model_copy(update={"risk": s.risk.model_copy(update={"risk_per_trade_pct": 2.0})})
    assert fp1 != param_fingerprint(changed, cfg)
