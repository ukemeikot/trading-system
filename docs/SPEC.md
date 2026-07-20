# Multi-Market Trading System — Consolidated Specification
### System · Clean Architecture · Strategy · Milestones (single source of truth)

> **Instructions for Claude Code:** This is the complete and only specification — it consolidates the system spec, the strategy spec, and the architecture/milestones addendum. Build milestone by milestone (Part E), in order. Each milestone has exit criteria — verify them (run the tests, run the demo commands) before moving on. Ask the user before making architectural decisions not covered here. **Paper trading only:** do NOT write live-order code paths that transmit real orders; the `LiveBroker` may exist only as a stub raising `NotImplementedError`, and the app must refuse to start if `mode: live`.

---

# Part A — Project Overview & Ground Rules

An event-driven, paper-trading-first automated trading system covering **crypto** (via `ccxt` / `ccxt.pro`) and **forex** (via OANDA v20 practice API). Designed for very small capital ($100), so cost modeling (fees, spread, slippage) is a first-class concern, not an afterthought.

**Instruments:** Crypto — BTC/USDT, ETH/USDT. Forex — **GBP/USD** (the sole forex instrument).

**Explicit non-goals:**
- No HFT / latency arbitrage. Strategies operate on 1m candles or slower.
- No live trading until the gates in Part F are passed. Live mode is a separate, deliberate future step.
- No low-level language (Rust/C++) initially. A Rust hot-path rewrite is a far-future phase, gated on measured evidence (Part F §3).
- **No privileged or non-public information, ever.** Strategies premised on insider information, paid "signal/leak" groups, or front-running order flow are illegal (insider trading / wire fraud) and permanently out of scope. In practice these are scam funnels aimed at small accounts.

**Design priorities, in order:** correctness → pessimistic cost modeling → observability → iteration speed → raw performance.

**Honest expectations (keep in README):** No legitimate low-risk strategy yields $10/week on $100 (10%/week ≈ 14,000%/yr). If the strategy in Part D survives validation, a realistic outcome is roughly **0–3% per month net of costs, with losing weeks and losing months**. Dollar targets are outputs of the system, never inputs to position sizing. If validation shows no edge after costs, the correct action is to discard the strategy, not tune it until the backtest looks good.

---

# Part B — Tech Stack & Clean Architecture

## B1. Tech stack

- Python 3.11+, `asyncio` with `uvloop`
- `ccxt` (REST/historical) and `ccxt.pro` if available, else raw `websockets` against exchange WS endpoints, for crypto market data (Binance default; no API keys needed for public data)
- OANDA v20 REST + streaming API for forex (practice account; user supplies `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` via `.env`; if absent, forex components degrade gracefully and crypto still runs)
- `pandas` + `numpy`; `pyarrow` for Parquet storage
- `vectorbt` OR `backtesting.py` for backtesting (pick one, justify in a comment; prefer whichever installs cleanly)
- SQLite (`sqlite3` or `aiosqlite`) for persistence
- `pydantic` v2 for config and message schemas
- `structlog` or stdlib `logging` with JSON output
- `pytest` + `pytest-asyncio`; `import-linter`; `mypy`
- Optional: `numba` for measured hot computations; `python-telegram-bot` for notifications (config flag, off by default)

Package management: `uv` or `pip` with `pyproject.toml`. Pin versions.

## B2. Layering rules

Four layers. **The Dependency Rule is absolute: source-code dependencies point inward only.** Inner layers know nothing about outer layers. Enforced with `import-linter` in CI.

```
+-----------------------------------------------------------+
|  frameworks/   (outermost: ccxt, OANDA, SQLite,           |
|                 websockets, systemd, Telegram)            |
|  +-----------------------------------------------------+  |
|  |  adapters/   (gateways implementing ports,          |  |
|  |               presenters, repositories)             |  |
|  |  +-----------------------------------------------+  |  |
|  |  |  application/  (use cases, ports/ABCs,        |  |  |
|  |  |                 event bus orchestration)      |  |  |
|  |  |  +-----------------------------------------+  |  |  |
|  |  |  |  domain/  (entities, value objects,     |  |  |  |
|  |  |  |  strategy logic, risk rules — pure      |  |  |  |
|  |  |  |  Python, zero third-party imports       |  |  |  |
|  |  |  |  except stdlib + numpy)                 |  |  |  |
|  |  |  +-----------------------------------------+  |  |  |
|  |  +-----------------------------------------------+  |  |
|  +-----------------------------------------------------+  |
+-----------------------------------------------------------+
```

### Layer contents

**`domain/` — Enterprise rules. Pure. No I/O, no async, no clock reads, no ccxt/OANDA/SQLite imports.**
- Entities & value objects: `Candle`, `Tick`, `Signal`, `Order`, `Fill`, `Position`, `EquityCurve`, `Money`, `Pair`, `Market` (enum), `NewsEvent`, `BlackoutWindow`.
- Domain services (pure): `CostModel` (fees/spread/slippage math), `PositionSizer` (fixed-fractional + ATR stop distance), indicator math (`atr`, `vwap`, `ema`, `rsi`), `RegimeClassifier` (quiet/trending), and the strategies (`QuietScalper`, `Momentum`, `MeanRev`) as pure `on_candle(candle, state) -> Signal | None`.
- `RiskPolicy`: pure decision logic — portfolio state + proposed order → Approve/Reject(reason). (The stateful wrapper tracking equity high-water mark lives in application; the rules live here.)
- 90% of unit tests live here and run with zero mocks.

**`application/` — Use cases and ports. Depends only on `domain/`.**
- Ports (ABCs / Protocols): `MarketDataFeed`, `Broker`, `TradeRepository`, `CalendarSource`, `Notifier`, `Clock`, `LatencyRecorder`.
- Use cases (one class each): `StreamAndTrade` (feed → strategy → risk → broker → persist; contains event-bus wiring), `RunBacktest`, `RunWalkForward`, `DownloadHistory`, `ImportCalendar`, `GenerateDailyReport`, `ReplaySession` (the `--replay` mode), `EnforceCircuitBreakers` (volatility spike / spread blowout / consecutive-loss / kill-switch orchestration over domain rules).
- The asyncio event bus lives here as an orchestration detail; events themselves are domain objects.

**`adapters/` — Implementations of ports. Depends on `application/` + `domain/`.**
- `CcxtFeed`, `OandaFeed` → `MarketDataFeed`; both normalize to domain `Candle`/`Tick` at the boundary (normalization lives here, not domain).
- `PaperBroker` (uses domain `CostModel`), `LiveBrokerStub` → `Broker`.
- `SqliteTradeRepository` → `TradeRepository`; `CsvCalendarSource` (+ optional `ForexFactoryCalendarSource`) → `CalendarSource`; `TelegramNotifier`, `LogNotifier` → `Notifier`; `SystemClock`, `SimulatedClock` → `Clock`.
- Backtest-library adapter (`VectorbtEngine` or `BacktestingPyEngine`) — the third-party lib is quarantined here so it can be swapped.

**`frameworks/` — outermost: infrastructure + entrypoints.**
- `main_paper.py`, `main_backtest.py`, `main_walkforward.py`, `main_download.py` — composition roots: read config, construct adapters, inject into use cases. **Dependency injection happens ONLY here**, by plain constructor passing (no DI framework).
- Config loading (pydantic-settings), logging setup, systemd unit, CLI parsing.

## B3. Repository layout

```
trading-system/
├── pyproject.toml
├── .env.example                  # OANDA_API_TOKEN=, OANDA_ACCOUNT_ID=, TELEGRAM_* (optional)
├── .importlinter                 # enforces the dependency rule
├── config/
│   ├── settings.yaml             # pairs, timeframes, risk params, fees, mode=paper
│   ├── strategies.yaml           # per-strategy params
│   └── calendar.csv              # scheduled high-impact events (manual import fallback)
├── src/tsys/
│   ├── domain/
│   │   ├── entities.py           # Candle, Order, Fill, Position, ...
│   │   ├── values.py             # Money, Pair, Market, BlackoutWindow
│   │   ├── indicators.py         # atr, vwap, ema, rsi (numpy only)
│   │   ├── costs.py              # CostModel
│   │   ├── sizing.py             # PositionSizer
│   │   ├── risk.py               # RiskPolicy (pure rules)
│   │   ├── regime.py             # RegimeClassifier
│   │   └── strategies/
│   │       ├── base.py           # Strategy protocol
│   │       ├── quiet_scalper.py
│   │       ├── momentum.py
│   │       └── meanrev.py
│   ├── application/
│   │   ├── ports.py              # all ABCs/Protocols
│   │   ├── bus.py
│   │   ├── use_cases/
│   │   │   ├── stream_and_trade.py
│   │   │   ├── run_backtest.py
│   │   │   ├── run_walkforward.py
│   │   │   ├── download_history.py
│   │   │   ├── import_calendar.py
│   │   │   ├── replay_session.py
│   │   │   ├── circuit_breakers.py
│   │   │   └── daily_report.py
│   │   └── dto.py                # cross-boundary data shapes if needed
│   ├── adapters/
│   │   ├── feeds/ (ccxt_feed.py, oanda_feed.py, normalize.py)
│   │   ├── brokers/ (paper.py, live_stub.py)
│   │   ├── persistence/ (sqlite_repo.py, schema.sql)
│   │   ├── calendar/ (csv_source.py)
│   │   ├── backtest/ (engine_adapter.py)
│   │   └── notify/ (log_notifier.py, telegram_notifier.py)
│   └── frameworks/
│       ├── config.py
│       ├── logging_setup.py
│       └── entrypoints/ (main_paper.py, main_backtest.py, main_walkforward.py, main_download.py)
├── systemd/tsys-paper.service
├── tests/
│   ├── domain/                   # pure, no mocks, fast — the bulk
│   ├── application/              # use cases with fake ports
│   ├── adapters/                 # against recorded fixtures
│   └── e2e/                      # replay-mode end-to-end
└── data/                         # gitignored (Parquet: data/parquet/{market}/{pair}/{tf}.parquet)
```

### `.importlinter` (CI-enforced)

```ini
[importlinter]
root_package = tsys

[importlinter:contract:layers]
name = Clean architecture layers
type = layers
layers =
    tsys.frameworks
    tsys.adapters
    tsys.application
    tsys.domain
```

CI fails if, e.g., `domain/` imports ccxt or `application/` imports sqlite3. Additionally add a `forbidden` contract: `domain/` may import only stdlib + numpy (forbid ccxt, pandas, aiosqlite, websockets inside domain).

### Why this pays off here
- Backtest/paper/live use the *same* domain strategy and cost model with different adapters — "identically runnable" becomes structurally guaranteed rather than a convention.
- The future Rust hot path becomes a drop-in adapter implementing `MarketDataFeed`/order routing, with zero changes to domain or application.
- Strategy research iterates in a pure, mock-free layer — the fastest possible test loop.

## B4. Core design rules

1. **Event-driven, not polling.** Feeds push `Candle`/`Tick` events onto the bus; strategies subscribe; signals flow to risk; approved orders flow to the broker. One asyncio process.
2. **Strategies are pure functions.** `on_candle()` takes market data + own state, returns `Signal | None`. No network, no clock reads, no broker access. Identically runnable in backtest and paper modes — non-negotiable.
3. **One cost model, used everywhere.** The same fee/spread/slippage function serves the backtester and the PaperBroker. Never let backtest costs and paper costs diverge.
4. **Everything logged.** Every signal (including risk-vetoed ones, with reason), every fill, every equity update, every latency sample. Debugging a trading system without a decision log is impossible.
5. **Market-agnostic downstream.** After boundary normalization, nothing below the data layer knows whether a pair is crypto or forex, except the cost model (per-market fee/spread config).

## B5. Cross-cutting conventions

- All timestamps UTC, `datetime` with tzinfo, injected via the `Clock` port (never `datetime.now()` outside `SystemClock`).
- Domain raises domain exceptions (`RiskRejected`, `StaleCalendar`); adapters translate infra errors into port-level errors; entrypoints decide restart/backoff.
- Every event and decision serializable to JSON for the decision log.
- Type hints everywhere; `mypy --strict` on `domain/` and `application/` at minimum.

---

# Part C — Cost Model & Risk Rules

## C1. Cost model (pessimistic — this is where hobby bots secretly fail)

Configurable in `settings.yaml`, defaults:

- **Crypto:** taker fee 0.10% per side; slippage 0.05% per fill (market orders assumed).
- **Forex:** spread from config per pair — default **GBP/USD 1.8 pips**, applied on entry and exit; no commission (spread-based pricing).
- Fills execute at next candle open (backtest) or current best price ± slippage (paper), never at signal-candle close.
- No lookahead: strategies only ever see closed candles.

## C2. Risk Manager rules (system-wide defaults, all configurable)

- Position size: fixed-fractional, risk **1%** of current equity per trade, sized from ATR-based stop distance. Floor/ceiling on notional so a $100 account produces valid order sizes (crypto min notionals; forex micro-units on OANDA).
- Max 3 concurrent positions; max 1 position per pair.
- Hard stop-loss on every position (ATR-based, set by strategy, enforced by risk manager — reject stop-less orders).
- Daily loss limit: −3% of equity → flatten all, halt trading until next UTC day.
- Kill switch: −15% drawdown from equity high-water mark → flatten all, halt, require manual restart flag.
- Every rejection logged with reason to the `decisions` table.

---

# Part D — Strategy Specs

## D1. Baseline strategies (research pair)

- **`momentum.py`** — trend-following on 4h candles: EMA cross + ATR trend filter, ATR stops. Parameters in `strategies.yaml`.
- **`meanrev.py`** — RSI-extreme mean reversion on 1h candles for ranging conditions, ATR stops.
- Rules for research: walk-forward testing (train 2022–2024, validate 2025+), never tune parameters on the test set, reject anything with fewer than ~100 trades in backtest — small samples lie. Simple strategies overfit less.

## D2. Primary strategy — "Quiet Window Scalper" (max 30-min hold)

Implemented as `domain/strategies/quiet_scalper.py` plus calendar logic surfaced through `NewsEvent`/`BlackoutWindow` domain objects and the `CalendarSource` port. All parameters in `strategies.yaml`. Must pass the full validation battery (D2.7) and paper gates (Part F) before any capital discussion. **Do not weaken any risk rule to improve backtest results.**

### D2.1 Concept
Short-duration mean reversion on highly liquid instruments during low-volatility windows. Price in quiet regimes oscillates around a fair-value anchor (VWAP); we fade small overextensions back to the anchor and are flat again within minutes. All known volatility events are avoided by construction; unknown ones are handled by a circuit breaker.

- **Hold time:** target 5–20 minutes, hard cap **30 minutes** (time-stop: flatten at 30 min regardless of PnL).
- **Direction:** long and short.
- **Frequency:** 0–6 trades/day per instrument. Zero-trade days are correct behavior, not a bug.

### D2.2 Instruments & sessions
- **Crypto:** BTC/USDT, ETH/USDT only (deepest books, tightest spreads).
- **Forex (paper via OANDA):** **GBP/USD** only.
- **Session filter:** crypto 07:00–16:00 UTC (EU/US overlap edges); GBP/USD 08:00–11:00 UTC (London morning — GBP's most liquid hours) and 13:30–16:00 UTC (London/New York overlap). No weekend forex; crypto weekends allowed but subject to the regime filter (weekend books are thinner).

### D2.3 News-avoidance protocol (core of the strategy)

**(a) Scheduled-event blackout.** Maintain a calendar of high-impact scheduled events; refuse new positions in a window around them; force-flatten any open position before the window starts.
- **Source:** free economic calendar feed (Forex Factory export / investing.com CSV), with a weekly manual-import fallback: `config/calendar.csv` the user can paste into, so the system never depends on scraping.
- **Blocked events (minimum set):** US — CPI, PPI, NFP, FOMC decisions + minutes + press conferences, GDP, retail sales, PCE, weekly jobless claims. **UK (critical for GBP/USD)** — BoE rate decisions + MPC minutes + Governor press conferences, UK CPI, UK GDP, UK labour-market report (claimant count / average earnings), UK retail sales, UK PMIs. Other majors' central banks (ECB, BoJ) as spillover risk. For crypto additionally: major exchange/regulatory hearing dates and scheduled token unlocks if trading alts later (not applicable to BTC/ETH majors initially).
- **Blackout window:** no new entries from **T−30 min**; force-flat by **T−10 min**; no re-entry until **T+45 min** AND until the regime filter re-qualifies.
- **Stale-calendar failsafe:** if `calendar.csv` is >7 days old, the strategy refuses to trade forex at all and logs why.

**(b) Unscheduled-news circuit breaker.** Scheduled events are the easy part; the ones that cut scalpers up are unscheduled (hacks, headlines, flash moves). Handle mechanically:
- **Volatility spike halt:** if the 1-minute realized range exceeds `spike_mult × ATR(14, 1m)` (default 3×), immediately flatten at market and halt new entries for 60 minutes.
- **Spread blowout halt:** if live spread exceeds `2.5×` its trailing 1-hour median, do not enter; if in a position, tighten management (exit at anchor touch rather than full target).
- **Consecutive-loss halt:** 3 losing trades in a row on one instrument → that instrument is done for the day.

**(c) Regime filter (only trade quiet, ranging tape).**
- ATR(14) on 5m candles as % of price must be **below its 20-day median** (quiet regime).
- Trend veto: |EMA(20) − EMA(200)| on 5m must be < `0.5 × ATR(14, 5m)` — no strong trend in force. Mean reversion in a trend is how scalpers get run over.

### D2.4 Entry / exit rules (all params in `strategies.yaml`)

Anchor: **session-anchored VWAP** (daily anchor 00:00 UTC for crypto; session open for GBP/USD). Bands: VWAP ± `k × stdev` of (price − VWAP) over the session, default k = 2.0.

**Long setup (short is the mirror image):**
1. All filters pass (session, blackout, regime, circuit breakers clear).
2. Price touches or pierces the lower band on a 1m close.
3. Trigger: next 1m candle closes back inside the band (rejection confirmation — never catch the falling knife on the touch itself).
4. Entry: **post-only limit order** at or better than the trigger close (maker fill; if unfilled in 2 minutes, cancel — never chase with a market order on entry).

**Exit (first to occur):**
- **Target:** VWAP touch (limit order resting from entry).
- **Stop:** entry − `1.2 × ATR(14, 1m)`, enforced by the Risk Manager as always.
- **Time stop:** 30 minutes after fill → market-flatten.
- **Event stop:** approaching blackout window or circuit breaker fired → flatten.

Expected geometry: average win ≈ 0.6–1.0 × ATR, average loss ≈ 1.2 × ATR, so the strategy needs win rate > ~60% in-regime to be net positive after costs. The backtest report must state achieved win rate and breakeven win rate side by side.

### D2.5 Cost control (existential at this hold time)
A 30-minute scalp lives or dies on fees. With 0.1% taker both ways, round-trip cost ≈ 0.25% incl. slippage — often larger than the target itself. Therefore:
- **Maker-only entries** (post-only). Exits: target is maker; stop/time-stop are taker (unavoidable).
- **Venue selection matters more than signal quality:** prefer venues/tiers with 0.00–0.02% maker fees. Run the backtest twice — once with default pessimistic fees (C1) and once with the intended venue's actual maker/taker schedule — and report both.
- **Kill criterion:** if cost drag > 40% of gross PnL in backtest, the strategy fails validation regardless of net result.

### D2.6 Strategy-specific risk (inherits C2, plus)
- Risk per trade: **0.75%** of equity (tighter than system default; frequency is higher).
- Max **1** concurrent position for this strategy across all instruments.
- Daily loss limit **−2%** for this strategy (inside the system-wide −3%).
- No overnight anything: flat outside session windows by construction.

### D2.7 Validation plan (before paper, before money)
1. Walk-forward per Part E M3 mechanics (train 2022–2024, validate 2025+), 1m data. Minimum **300 trades** in-sample; reject otherwise.
2. **News-filter ablation:** run the identical strategy with the blackout filter OFF. The report must show the filter's contribution. If it doesn't materially reduce tail losses, the "quiet window" premise is wrong — investigate before proceeding.
3. Regime-filter ablation: same, for the ATR regime gate.
4. Slippage stress test: double the slippage assumption; strategy must remain ≥ breakeven or it fails.
5. Dual fee-schedule runs per D2.5.
6. Then ≥8 weeks paper trading, zero parameter changes mid-run, per Part F gates.

### D2.8 Explicitly out of scope
- Any use of material non-public information, paid "signal/leak" groups, or front-running order flow (illegal; scam funnel).
- Trading during high-impact news to "catch the move" — a different, much higher-risk strategy class that contradicts this design.
- Increasing position size or loosening stops to reach a dollar target. Dollar targets are outputs, not inputs.

---

# Part E — Milestones

Each milestone = a PR-sized unit with a demo command and exit criteria. Claude Code will compress the calendar, but the **order and gates do not change**. The multi-week duration in M6 is real-world observation time and cannot be compressed.

### M0 — Skeleton & guardrails (effort: small)
Repo scaffold per B3, pyproject, import-linter wired into CI/pre-commit, config loading, logging, empty ports, `mode: live` refusal implemented.
**Demo:** `import-linter` passes; a deliberate `import ccxt` inside `domain/` fails CI.
**Exit:** config/eventing groundwork in place; `pytest` green (even if few tests).

### M1 — Domain core (effort: medium)
Entities, values, indicators, `CostModel`, `PositionSizer`, `RiskPolicy`, `RegimeClassifier`. Full unit-test suite including the round-trip cost property test and determinism test (Part F §1).
**Demo:** `pytest tests/domain -q` — target >90% coverage on domain.
**Exit:** cost math proven exact; sizing produces valid order sizes for a $100 account (min-notional floor logic tested).

### M2 — Data in (effort: medium)
`DownloadHistory` use case + ccxt/OANDA adapters + Parquet storage + boundary normalization. Historical data: BTC/USDT, ETH/USDT (Binance, 1m + 1h + 4h, 2+ years) and **GBP/USD** (OANDA, 1m + 1h + 4h, 2+ years, if creds present — else skip with a clear log message). Calendar import (`config/calendar.csv` → `NewsEvent`s) with staleness detection.
**Demo:** `python -m tsys.frameworks.entrypoints.main_download` produces the Parquet files; stale-calendar refusal demonstrated.
**Exit:** normalization tests prove identical schema across markets; event bus publish/subscribe test passes.

### M3 — Backtester (effort: medium-large)
`RunBacktest` + `RunWalkForward` use cases, backtest-library adapter, shared `CostModel` injected, lookahead-impossible API, walk-forward report (per-fold return, max DD, trade count, cost drag, achieved vs breakeven win rate). Default folds: train 2022–2024, validate 2025+.
**Demo:** buy-and-hold and random-entry baselines produce cost-adjusted equity curves; a test proves fees reduce PnL by the expected amount on a synthetic series; a lookahead attempt (strategy that peeks at the next candle) is demonstrated to be impossible through the engine API.
**Exit:** all of the above green.

### M4 — Strategies & validation (effort: large; this is the real work)
Implement `momentum`, `meanrev`, `quiet_scalper` (with news blackout + regime gate + circuit-breaker rules as domain logic). Run the full validation battery: walk-forward (≥100 trades momentum/meanrev, ≥300 quiet_scalper), news-filter ablation, regime ablation, double-slippage stress, dual fee-schedule runs, cost-drag kill criterion (>40% → fail).
**Demo:** `main_walkforward` emits a written validation report per strategy with pass/fail per criterion.
**Exit:** honest reports exist. NOTE: a strategy *failing* validation still passes this milestone — the deliverable is trustworthy evidence, not a green number. Failed strategies are parked, not tuned-until-green. (Profitability is NOT an acceptance criterion — honest reporting is.)

### M5 — Paper engine, live data (effort: large)
`StreamAndTrade` + `ReplaySession`, WebSocket feeds (crypto mandatory; GBP/USD via OANDA streaming if creds) with reconnect/exponential backoff, `PaperBroker` filling against live prices with the shared cost model, stateful risk wrapper (HWM, daily limits, kill switch), circuit breakers live, SQLite persistence, decision log, latency instrumentation (tick-received → signal-emitted → order-submitted, p50/p99 histograms to DB), daily summary report, systemd unit, restart-recovery of open paper positions from DB.
**Demo:** `--replay` of one recorded day through the identical live code path fills the DB (fills, equity curve, decisions incl. vetoes, latency histograms); forced-crash kill-switch test passes (prices forced down → flatten + halt); pull-the-network-cable reconnect test passes; report prints latency p50/p99.
**Exit:** all of the above green.

### M6 — Observation period (calendar time: 8–12 weeks minimum, not compressible)
Deploy on VPS/Pi as systemd service. Freeze parameters. Weekly automated report: net return after costs, max DD, cost drag %, trades taken/vetoed, latency p99, filter activations (blackouts hit, circuit breakers fired). **Mid-run parameter changes reset the clock to week zero.**
**Exit (= Part F gates):** ≥8–12 continuous weeks, positive net after costs, max DD <15%, live-paper ≈ backtest expectations. Only then does a conversation about real money begin — with the explicit understanding that ~0.5–2%/month is the realistic ceiling, not $10/week on $100.

### M7 — (Conditional, far future) Live mode & Rust hot path
Out of scope now. Live mode requires M6 exit + a written go-decision. Rust adapter only per Part F §3 entry criteria (recorded p99 evidence of an internal bottleneck).

### Definition of Done (every milestone)
- Import-linter and mypy clean; tests green; no network calls in tests (recorded fixtures only).
- Every new decision path writes to the decision log.
- README updated with the milestone's demo command.
- No weakening of risk rules, cost pessimism, or validation gates to make results look better — if a gate seems wrong, raise it with the user; never silently change it.

---

# Part F — Testing, Gates & Future Phases

## F1. Testing requirements
- Unit tests for: cost model math, position sizing math, risk vetoes, normalization, event bus.
- Property test: PaperBroker equity after a round-trip trade with zero price movement = starting equity − (fees + spread + slippage), exactly.
- Determinism test: same candle stream through strategy+risk twice → identical decision log.
- No test may hit live network; use recorded fixtures.
- Test layout mirrors layers: `tests/domain` (pure, no mocks — the bulk), `tests/application` (fake ports), `tests/adapters` (fixtures), `tests/e2e` (replay mode).

## F2. Gates before any live money (document in README verbatim; do not implement live mode)
Fund only if paper trading shows, over ≥8–12 continuous weeks with no mid-run parameter changes: positive net return after costs; max drawdown < 15%; live-paper results within reason of backtest expectations (if live-paper is much worse, suspect slippage modeling or lookahead bugs). Even then, realistic expectation is ~0.5–2%/month with losing weeks. The original "$10/week on $100" target is not a system requirement — it is explicitly out of scope as an expectation.

## F3. Future phase (DO NOT BUILD NOW) — Rust hot path
Only if latency instrumentation shows *internal processing* (not network) is a measured bottleneck under real load (e.g., tick-level strategies across many pairs saturating the event loop): rewrite the market-data parser and order router as a Rust module via PyO3/maturin — as a drop-in adapter implementing the `MarketDataFeed`/order-routing ports — keeping domain, application, and persistence in Python. Entry criteria must cite recorded p99 numbers from the latency table. Rationale: network round-trip (20–100ms) dominates end-to-end latency; Python internal dispatch (~0.1–1ms) is ~1% of the budget, so rewrites are unjustified until measurements say otherwise. A full-Rust engine (tokio) is considered only after the hybrid is genuinely outgrown.

## F4. Operational notes
- All timestamps UTC everywhere.
- Config default `mode: paper`; the app must refuse to start if `mode: live` (raise with a message pointing to F2).
- Deployment target: small VPS or Raspberry Pi; idle CPU near zero; `uvloop` enabled. If crypto latency ever matters, host near the exchange (e.g., AWS Tokyo for Binance) — a deployment choice, not a code change.
- README must include: setup steps, how to get an OANDA practice token, how to run each entrypoint, the F2 gates verbatim, and the honest-expectations paragraph from Part A.
