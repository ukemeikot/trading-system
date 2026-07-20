# Multi-Market Trading System

An event-driven, **paper-trading-first** automated trading system for **crypto** (Binance via `ccxt`) and **forex** (GBP/USD via OANDA v20 practice). Built for very small capital ($100), so pessimistic cost modeling (fees, spread, slippage) is a first-class concern.

The complete and authoritative specification lives in **[docs/SPEC.md](docs/SPEC.md)** — it is the single source of truth. This README summarizes; the spec governs.

> ⚠️ **Paper trading only.** There are no live-order code paths. `LiveBroker` exists only as a stub that raises `NotImplementedError`, and the app **refuses to start** if `mode: live`. Live mode is a separate, deliberate future step gated on the criteria in Part F of the spec.

---

## Honest expectations

No legitimate low-risk strategy yields $10/week on $100 (that would be ~10%/week ≈ 14,000%/yr). If the primary strategy survives validation, a realistic outcome is roughly **0–3% per month net of costs, with losing weeks and losing months**. Dollar targets are **outputs** of the system, never inputs to position sizing. If validation shows no edge after costs, the correct action is to **discard the strategy, not tune it until the backtest looks good**.

**No privileged or non-public information, ever.** Strategies premised on insider information, paid "signal/leak" groups, or front-running order flow are illegal and permanently out of scope.

---

## Architecture (Clean Architecture, four layers)

Source-code dependencies point **inward only** — enforced in CI by `import-linter`.

```
frameworks/   (ccxt, OANDA, SQLite, websockets, systemd, Telegram — entrypoints, DI)
  adapters/   (feeds, brokers, persistence, calendar, backtest engine, notifiers)
    application/  (use cases, ports/ABCs, asyncio event bus)
      domain/     (entities, indicators, cost model, sizing, risk, strategies — pure)
```

`domain/` is pure Python (stdlib + numpy only): no I/O, no async, no clock reads, no third-party trading libs. The same domain strategy and cost model run identically in backtest, paper, and (future) live — structurally guaranteed, not by convention.

## Instruments

- **Crypto:** BTC/USDT, ETH/USDT (Binance, public data — no API keys needed)
- **Forex:** GBP/USD only (OANDA practice account)

## Strategies

- **Quiet Window Scalper** (primary) — short-duration VWAP mean reversion in low-volatility windows, max 30-min hold, news-blackout + regime filter + circuit breakers.
- **Momentum** (baseline) — EMA-cross trend following on 4h candles.
- **Mean Reversion** (baseline) — RSI-extreme reversion on 1h candles.

See Part D of the spec for full rules.

---

## Setup

> Prerequisites: Python 3.11+. `uv` (recommended) or `pip`.

```bash
# clone
git clone https://github.com/ukemeikot/trading-system.git
cd trading-system

# install (once pyproject.toml is in place — M0)
uv sync            # or: pip install -e .

# configure secrets (optional — crypto runs without them)
cp .env.example .env
# edit .env with your OANDA practice credentials
```

### Getting an OANDA practice token

1. Create a free demo account at <https://www.oanda.com/> (fxTrade Practice).
2. In the account portal, go to **Manage API Access** and generate a personal access token.
3. Copy your **Account ID** (format `xxx-xxx-xxxxxxxx-xxx`).
4. Put both into `.env`:
   ```
   OANDA_API_TOKEN=your_token_here
   OANDA_ACCOUNT_ID=your_account_id_here
   ```
If these are absent, forex components degrade gracefully and crypto still runs.

## Running (entrypoints)

Each entrypoint is a composition root — it reads config, constructs adapters, and injects them into use cases. *(Available as milestones land — see Part E.)*

```bash
python -m tsys.frameworks.entrypoints.main_download      # download historical data → Parquet
python -m tsys.frameworks.entrypoints.main_backtest      # run a backtest
python -m tsys.frameworks.entrypoints.main_walkforward   # walk-forward validation report
python -m tsys.frameworks.entrypoints.main_paper         # live paper trading (default mode: paper)
python -m tsys.frameworks.entrypoints.main_paper --replay <session>   # replay a recorded day
```

## Testing

```bash
pytest -q                    # all tests (no live network — recorded fixtures only)
pytest tests/domain -q       # pure domain tests (the bulk; no mocks)
lint-imports                 # verify the dependency rule
mypy src/tsys/domain src/tsys/application --strict
```

---

## Gates before any live money (verbatim from spec Part F2)

Fund only if paper trading shows, over **≥8–12 continuous weeks with no mid-run parameter changes**: positive net return after costs; max drawdown < 15%; live-paper results within reason of backtest expectations (if live-paper is much worse, suspect slippage modeling or lookahead bugs). Even then, realistic expectation is **~0.5–2%/month with losing weeks**. The original "$10/week on $100" target is **not** a system requirement — it is explicitly out of scope as an expectation.

## Project status

Implementation proceeds **milestone by milestone (M0 → M6)** per spec Part E; order and gates do not change. See [docs/SPEC.md](docs/SPEC.md#part-e--milestones).

- **M0 — Skeleton & guardrails** ✅ CI (ruff + import-linter + mypy --strict + pytest), config with `mode: live` refusal, JSON logging, port ABCs, `LiveBrokerStub`. A forbidden import in `domain/` fails the import-linter contract.
- **M1 — Domain core** ✅ Entities, values, indicators (atr/vwap/ema/rsi), `CostModel` (exact Decimal cost math, F1 round-trip property test), `PositionSizer` (min-notional floor for $100 accounts), `RiskPolicy`, `RegimeClassifier` — 47 tests, `mypy --strict` clean.
- **M2 — Data in** ⬜ next.

### Dev quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows: .venv\Scripts\activate)
pip install -e ".[dev]"
ruff check src tests
lint-imports
mypy --strict src/tsys/domain src/tsys/application
pytest
```
