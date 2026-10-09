"""Permanent OHLCV store (SQLite, stdlib only - no new dependency, no cloud credentials).

Conventions
- `ts` = bar OPEN time, unix seconds (UTC instant). A bar is complete at ts + bar_seconds.
- Prices are stored exactly as the provider returned them. NULL = unknown (never 0).
- Writes are idempotent (PRIMARY KEY) and never overwrite: a re-fetch that disagrees with a
  stored bar is recorded as a `revised_bar` quality flag, the original is kept.
"""
import os
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
  symbol TEXT PRIMARY KEY, exch TEXT NOT NULL, token TEXT NOT NULL, trading_symbol TEXT,
  kind TEXT NOT NULL DEFAULT 'equity', mapped_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS candles (
  symbol TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  source TEXT NOT NULL, fetched_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, interval, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fetch_log (
  symbol TEXT NOT NULL, interval TEXT NOT NULL, chunk_start TEXT NOT NULL, chunk_end TEXT NOT NULL,
  status TEXT NOT NULL, n_bars INTEGER, first_ts INTEGER, last_ts INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0, detail TEXT, updated_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, interval, chunk_start, chunk_end));
CREATE TABLE IF NOT EXISTS quality_flags (
  symbol TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL, session TEXT,
  flag TEXT NOT NULL, severity TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, interval, ts, flag));
CREATE TABLE IF NOT EXISTS session_calendar (
  session TEXT PRIMARY KEY, is_trading INTEGER NOT NULL, n_reference INTEGER, n_present INTEGER,
  expected_slots TEXT, note TEXT, derived_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS session_quality (
  symbol TEXT NOT NULL, interval TEXT NOT NULL, session TEXT NOT NULL,
  n_bars INTEGER, verified INTEGER NOT NULL, reasons TEXT, checked_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, interval, session));
CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
  created_at INTEGER NOT NULL, as_of_ts INTEGER NOT NULL, forecast_timestamp INTEGER NOT NULL,
  horizon INTEGER NOT NULL, predicted_open REAL, predicted_high REAL, predicted_low REAL,
  predicted_close REAL, predicted_return REAL, direction_probability REAL,
  intervals_json TEXT, confidence TEXT NOT NULL, confidence_score REAL, regime TEXT,
  model_version TEXT, feature_version TEXT, ensemble_version TEXT, evidence_json TEXT,
  PRIMARY KEY (forecast_id, horizon));
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_key ON forecasts(symbol, timeframe, as_of_ts, horizon, model_version);
CREATE TABLE IF NOT EXISTS forecast_evaluations (
  forecast_id TEXT NOT NULL, horizon INTEGER NOT NULL, evaluated_at INTEGER NOT NULL,
  actual_open REAL, actual_high REAL, actual_low REAL, actual_close REAL,
  return_error REAL, close_error REAL, direction_correct INTEGER,
  in_interval_json TEXT, PRIMARY KEY (forecast_id, horizon));
CREATE TABLE IF NOT EXISTS daily_candles (
  symbol TEXT NOT NULL, date TEXT NOT NULL, raw_ts TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  source TEXT NOT NULL, fetched_at INTEGER NOT NULL, PRIMARY KEY (symbol, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS daily_fetch_log (
  symbol TEXT NOT NULL, chunk_start TEXT NOT NULL, chunk_end TEXT NOT NULL, status TEXT NOT NULL,
  n_bars INTEGER, first_date TEXT, last_date TEXT, attempts INTEGER NOT NULL DEFAULT 0, detail TEXT,
  updated_at INTEGER NOT NULL, PRIMARY KEY (symbol, chunk_start, chunk_end));
CREATE TABLE IF NOT EXISTS daily_quality_flags (
  symbol TEXT NOT NULL, date TEXT NOT NULL, flag TEXT NOT NULL, severity TEXT NOT NULL, detail TEXT,
  created_at INTEGER NOT NULL, PRIMARY KEY (symbol, date, flag));
CREATE TABLE IF NOT EXISTS daily_session_quality (
  symbol TEXT NOT NULL, date TEXT NOT NULL, verified INTEGER NOT NULL, reasons TEXT, PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS daily_calendar (
  date TEXT PRIMARY KEY, is_trading INTEGER NOT NULL, n_ref INTEGER, n_present INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS symbol_validation (
  symbol TEXT NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL, reasons_json TEXT,
  metrics_json TEXT, validated_at INTEGER NOT NULL, PRIMARY KEY (symbol, model_version));
CREATE TABLE IF NOT EXISTS model_registry (
  model_version TEXT PRIMARY KEY, family TEXT, feature_version TEXT, train_start TEXT, train_end TEXT,
  trained_at INTEGER, hyperparams_json TEXT, metrics_json TEXT, artifact_path TEXT,
  status TEXT NOT NULL, promoted_at INTEGER, notes TEXT);
"""


def connect(path=None):
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


@contextmanager
def tx(con):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def upsert_candles(con, symbol, interval, rows, source="angel_smartapi"):
    """rows: iterable of (ts, o, h, l, c, v). Returns (inserted, identical, revised).
    Existing rows are NEVER overwritten; a disagreeing re-fetch is flagged."""
    now = int(time.time())
    ins = same = rev = 0
    with tx(con):
        for ts, o, h, l, c, v in rows:
            cur = con.execute(
                "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                (symbol, interval, ts, o, h, l, c, v, source, now))
            if cur.rowcount:
                ins += 1
                continue
            old = con.execute("SELECT open,high,low,close,volume FROM candles WHERE symbol=? AND interval=? AND ts=?",
                              (symbol, interval, ts)).fetchone()
            if tuple(old) == (o, h, l, c, v):
                same += 1
            else:
                rev += 1
                con.execute("INSERT OR IGNORE INTO quality_flags VALUES (?,?,?,?,?,?,?,?)",
                            (symbol, interval, ts, None, "revised_bar", "warn",
                             f"stored={tuple(old)} refetched={(o, h, l, c, v)}", now))
    return ins, same, rev


def load_candles(con, symbol, interval=config.INTERVAL, start_ts=None, end_ts=None):
    q = "SELECT ts,open,high,low,close,volume FROM candles WHERE symbol=? AND interval=?"
    args = [symbol, interval]
    if start_ts is not None:
        q += " AND ts>=?"; args.append(start_ts)
    if end_ts is not None:
        q += " AND ts<=?"; args.append(end_ts)
    return con.execute(q + " ORDER BY ts", args).fetchall()
