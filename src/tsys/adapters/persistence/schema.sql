-- SQLite schema for the paper-trading decision log & persistence (SPEC M5).
-- Everything is logged: fills, every decision (incl. risk vetoes), equity, latency.

CREATE TABLE IF NOT EXISTS fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,           -- ISO-8601 UTC
    pair            TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    price           REAL NOT NULL,
    fee             REAL NOT NULL,
    order_client_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS decisions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,                  -- signal | veto | fill | halt | exit
    pair     TEXT,
    approved INTEGER,                        -- 1/0/NULL
    reason   TEXT NOT NULL DEFAULT '',
    detail   TEXT NOT NULL DEFAULT '{}'      -- JSON
);

CREATE TABLE IF NOT EXISTS equity (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    equity REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS latency (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    stage  TEXT NOT NULL,                    -- tick_to_signal | signal_to_order
    micros REAL NOT NULL
);

-- Parameter-freeze audit (SPEC M6): each run records a fingerprint of the risk/
-- cost/strategy params. A changed fingerprint means the observation clock resets.
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    param_hash TEXT NOT NULL
);

-- Snapshot of open positions for restart-recovery (one row per pair).
CREATE TABLE IF NOT EXISTS positions (
    pair        TEXT PRIMARY KEY,
    market      TEXT NOT NULL,
    side        TEXT NOT NULL,
    quantity    REAL NOT NULL,
    entry_price REAL NOT NULL,
    stop_price  REAL NOT NULL,
    opened_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fills_ts     ON fills(ts);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_equity_ts    ON equity(ts);
CREATE INDEX IF NOT EXISTS idx_latency_ts   ON latency(ts);
