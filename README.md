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

# install
pip install -e ".[dev]"

# configure secrets (optional — crypto runs without them)
cp .env.example .env
# edit .env with your Twelve Data API key (forex only)
```

### Getting a forex data key (Twelve Data)

OANDA (the spec's original source) does not accept Nigerian accounts. Because this
system is **paper-only** — fills are simulated by `PaperBroker` + the shared
`CostModel` — forex needs only a **data feed**, not a broker. Twelve Data is a
key-only signup with no brokerage KYC:

1. Sign up free at <https://twelvedata.com/>.
2. Copy your **API key** from the dashboard.
3. Put it into `.env`:
   ```
   TWELVEDATA_API_KEY=your_key_here
   ```
If absent, forex components degrade gracefully and crypto still runs.

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

## Deployment & observation runbook (M6)

Deploy on a small VPS or Raspberry Pi and let it run **8–12 continuous weeks with parameters frozen**. Mid-run parameter changes reset the clock to week zero (the engine warns and records a fingerprint to enforce this).

```bash
# on the box (paths match the systemd units)
sudo mkdir -p /opt/trading-system && cd /opt/trading-system
git clone https://github.com/ukemeikot/trading-system.git .
python -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env      # add TWELVEDATA_API_KEY if trading GBP/USD

# install the service + weekly report timer
sudo cp systemd/tsys-paper.service systemd/tsys-report.service systemd/tsys-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tsys-paper.service     # starts paper trading (restart-recovers open positions)
sudo systemctl enable --now tsys-report.timer      # weekly observation report (Mon 00:05 UTC)

journalctl -u tsys-paper -f                         # live decision log (JSON)
python -m tsys.frameworks.entrypoints.main_report --db data/tsys.sqlite --weeks 1   # ad-hoc report
```

The weekly report and the F2 gates below are what decide whether a real-money conversation ever begins.

## Gates before any live money (verbatim from spec Part F2)

Fund only if paper trading shows, over **≥8–12 continuous weeks with no mid-run parameter changes**: positive net return after costs; max drawdown < 15%; live-paper results within reason of backtest expectations (if live-paper is much worse, suspect slippage modeling or lookahead bugs). Even then, realistic expectation is **~0.5–2%/month with losing weeks**. The original "$10/week on $100" target is **not** a system requirement — it is explicitly out of scope as an expectation.

## Project status

Implementation proceeds **milestone by milestone (M0 → M6)** per spec Part E; order and gates do not change. See [docs/SPEC.md](docs/SPEC.md#part-e--milestones).

- **M0 — Skeleton & guardrails** ✅ CI (ruff + import-linter + mypy --strict + pytest), config with `mode: live` refusal, JSON logging, port ABCs, `LiveBrokerStub`. A forbidden import in `domain/` fails the import-linter contract.
- **M1 — Domain core** ✅ Entities, values, indicators (atr/vwap/ema/rsi), `CostModel` (exact Decimal cost math, F1 round-trip property test), `PositionSizer` (min-notional floor for $100 accounts), `RiskPolicy`, `RegimeClassifier` — 47 tests, `mypy --strict` clean.
- **M2 — Data in** ✅ `DownloadHistory` + `CcxtHistory`/forex history (lazy SDK imports) + `ParquetCandleStore`, boundary normalization proving an **identical Candle schema across markets**, `CsvCalendarSource` + `ImportCalendar` with the >7-day stale-calendar failsafe. Forex degrades gracefully without creds. 69 tests.
- **M3 — Backtester** ✅ Custom **event-driven engine** that fills via the *same* domain `CostModel` the PaperBroker uses (backtest == paper by construction), **lookahead-impossible** (entries fill at the next bar, never the signal-candle close), risk + sizing enforced, next-open/stop/target/time-stop exits. `RunBacktest` + `RunWalkForward`, buy-and-hold & random-entry baselines, cost-drag / breakeven-win-rate reporting. 81 tests. *(backtesting.py was dropped as the engine — its flat-commission broker can't express our maker/taker + spread + slippage + post-only fills without diverging from paper; see the engine module docstring.)*
- **M4 — Strategies & validation** ✅ `momentum` (EMA-cross), `meanrev` (RSI-extreme), and the primary `quiet_scalper` (session filter, session-anchored VWAP bands, quiet/trend regime gate, scheduled-news blackout, volatility-spike breaker, post-only arm→trigger entries) — all pure `on_candle`, using streaming indicators. **Validation battery** (`RunValidation`): min-trade count, cost-drag kill (>40%), 2× slippage stress, **news + regime filter ablations**, dual fee-schedule run — with pass/fail per criterion. *A failing strategy still produces a valid report; the deliverable is honest evidence, not a green number.* 99 tests.
  - *Some circuit breakers are live-only (see M5):* the spread-blowout breaker needs a tick spread; the consecutive-loss breaker needs trade-outcome feedback — both are enforced in the live engine, not the pure `on_candle`.
- **M5 — Paper engine, live data** ✅ `StreamAndTrade` (feed→strategy→risk→broker→persist, event-driven), `PaperBroker` filling against live prices via the *same* `CostModel` and the *same* shared exit logic (`domain/execution.py`) as the backtester, stateful `RiskManager` (HWM, daily-loss halt, **kill-switch latch**, consecutive-loss halt), `SqliteTradeRepository` decision log + latency histograms, `ReplaySession` (`--replay` drives the identical code path), reconnecting feed with exponential backoff, live `CcxtFeed`, restart-recovery of open positions from the DB, and `GenerateDailyReport` (latency p50/p99, vetoes, halts). 122 tests, incl. e2e replay/kill-switch/reconnect/restart-recovery.
- **M6 — Observation period** 🟡 Tooling ready; the 8–12 weeks are calendar time, not code. Weekly automated report (`main_report`: net return after costs, max DD, trades/vetoes, latency p99, filter activations — blackouts hit, breakers fired), **parameter-freeze guard** (a changed risk/cost/strategy fingerprint prints a reset-the-clock warning and is recorded in the `runs` table), and systemd units (`tsys-paper.service` + a weekly `tsys-report.timer`). 128 tests.
- **M7 — Live mode & Rust hot path** ⛔ Out of scope. Requires M6 exit + a written go-decision; there is no live-order code.

```bash
python -m tsys.frameworks.entrypoints.main_paper --strategy quiet_scalper --pair BTC/USDT --market crypto --timeframe 1m           # live paper
python -m tsys.frameworks.entrypoints.main_paper --strategy quiet_scalper --pair BTC/USDT --timeframe 1m --replay                  # replay a recorded run
python -m tsys.frameworks.entrypoints.main_report --db data/tsys.sqlite --weeks 1                                                  # weekly observation report
```

> **Paper only.** `main_paper` refuses to start unless `mode: paper` (spec F4). There is no live-order code path; `LiveBrokerStub` raises.

```bash
python -m tsys.frameworks.entrypoints.main_download --years 2               # crypto needs no keys
python -m tsys.frameworks.entrypoints.main_backtest --strategy buy_and_hold --pair BTC/USDT --timeframe 1h
python -m tsys.frameworks.entrypoints.main_walkforward --strategy buy_and_hold --pair BTC/USDT --timeframe 1h
```

> **Forex data source:** OANDA does not accept Nigerian accounts. Because this system is paper-only (fills are simulated by `PaperBroker` + `CostModel`), forex needs only a **data feed**, not a broker — the adapter targets **Twelve Data** (key-only signup, GBP/USD). See `.env.example`.

### Dev quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows: .venv\Scripts\activate)
pip install -e ".[dev]"
ruff check src tests
lint-imports
mypy --strict src/tsys/domain src/tsys/application
pytest
```
