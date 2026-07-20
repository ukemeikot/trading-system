"""Config loading + the paper-only guardrail (SPEC B2 frameworks, F4).

The app MUST refuse to start if mode != "paper". Dependency injection happens
only in entrypoints; this module just parses config and builds the domain value
objects (CostConfig, RiskLimits) the use cases need.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from tsys.domain.costs import CostConfig, CryptoCosts, ForexPairCosts
from tsys.domain.risk import RiskLimits


class RefuseToStart(RuntimeError):
    """Raised when config would put the system into an unsupported/unsafe state."""


class CryptoCostSettings(BaseModel):
    taker_fee_pct: float
    maker_fee_pct: float
    slippage_pct: float


class ForexPairSettings(BaseModel):
    spread_pips: float


class CostsSettings(BaseModel):
    crypto: CryptoCostSettings
    forex: dict[str, ForexPairSettings]


class RiskSettings(BaseModel):
    risk_per_trade_pct: float
    max_concurrent_positions: int
    max_positions_per_pair: int
    daily_loss_limit_pct: float
    kill_switch_drawdown_pct: float


class CircuitBreakerSettings(BaseModel):
    vol_spike_mult: float
    vol_spike_halt_minutes: int
    spread_blowout_mult: float
    consecutive_loss_halt: int


class CalendarSettings(BaseModel):
    path: str
    stale_after_days: int


class PairsSettings(BaseModel):
    crypto: list[str]
    forex: list[str]


class AppSettings(BaseModel):
    mode: str
    pairs: PairsSettings
    timeframes: list[str]
    costs: CostsSettings
    risk: RiskSettings
    circuit_breakers: CircuitBreakerSettings
    calendar: CalendarSettings


class Secrets(BaseSettings):
    """Secrets from .env / environment. Absent forex creds -> forex degrades
    gracefully; crypto still runs (SPEC B1). Forex data source is Twelve Data
    (OANDA does not accept Nigerian accounts; paper trading needs only data)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twelvedata_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def has_forex(self) -> bool:
        return bool(self.twelvedata_api_key)


def load_settings(path: str | Path = "config/settings.yaml") -> AppSettings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AppSettings.model_validate(raw)


def load_strategies(path: str | Path = "config/strategies.yaml") -> dict[str, object]:
    """Per-strategy params (strategies.yaml), passed to the strategy registry."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def ensure_paper_mode(settings: AppSettings) -> None:
    """Enforce the paper-only guardrail. See SPEC F2 for the live-money gates."""
    if settings.mode != "paper":
        raise RefuseToStart(
            f"mode is {settings.mode!r} but only 'paper' is supported. Live trading is "
            "out of scope until the gates in docs/SPEC.md Part F2 are passed. Refusing to start."
        )


def build_cost_config(settings: AppSettings) -> CostConfig:
    c = settings.costs.crypto
    return CostConfig(
        crypto=CryptoCosts(
            taker_fee_pct=Decimal(str(c.taker_fee_pct)),
            maker_fee_pct=Decimal(str(c.maker_fee_pct)),
            slippage_pct=Decimal(str(c.slippage_pct)),
        ),
        forex={
            symbol: ForexPairCosts(spread_pips=Decimal(str(fx.spread_pips)))
            for symbol, fx in settings.costs.forex.items()
        },
    )


def build_risk_limits(settings: AppSettings) -> RiskLimits:
    r = settings.risk
    return RiskLimits(
        max_concurrent_positions=r.max_concurrent_positions,
        max_positions_per_pair=r.max_positions_per_pair,
        daily_loss_limit_pct=Decimal(str(r.daily_loss_limit_pct)),
        kill_switch_drawdown_pct=Decimal(str(r.kill_switch_drawdown_pct)),
    )
