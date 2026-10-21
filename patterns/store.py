"""Persistent store for pattern occurrences and their full status history (SQLite, stdlib only).

Rules
- An occurrence is keyed by symbol|timeframe|pattern|direction|anchor_ts|detector_version. A new
  detector version writes NEW rows; older versions' rows are never touched.
- Status history rows are append-only (INSERT OR IGNORE on (occ_id, seq)): re-running the replay never
  rewrites what the agent knew at an earlier bar. Mutable columns on the occurrence row (current
  status, levels, updated_ts) follow the latest replay.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

from .engine import Occurrence, outcomes
from .core import Series

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("PATTERNS_DATA_DIR", os.path.join(ROOT, "data", "patterns"))
DB_PATH = os.path.join(DATA_DIR, "patterns.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pattern_runs (
  symbol TEXT NOT NULL, timeframe TEXT NOT NULL, version TEXT NOT NULL,
  last_bar_ts INTEGER NOT NULL, n_bars INTEGER NOT NULL, errors_json TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, timeframe, version));
CREATE TABLE IF NOT EXISTS pattern_occurrences (
  occ_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, version TEXT NOT NULL,
  pattern TEXT NOT NULL, direction TEXT, category TEXT, maturity TEXT,
  anchor_ts INTEGER NOT NULL, start_ts INTEGER, end_ts INTEGER,
  status TEXT NOT NULL, reason TEXT,
  first_seen_ts INTEGER NOT NULL, updated_ts INTEGER NOT NULL,
  confirmed_ts INTEGER, confirmed_price REAL,
  breakout_level REAL, invalidation_level REAL,
  pivots_json TEXT, lines_json TEXT, meta_json TEXT, params_json TEXT);
CREATE INDEX IF NOT EXISTS ix_occ_lookup ON pattern_occurrences(symbol, timeframe, version, status);
CREATE TABLE IF NOT EXISTS pattern_status_history (
  occ_id TEXT NOT NULL, seq INTEGER NOT NULL, ts INTEGER NOT NULL, status TEXT NOT NULL, price REAL,
  breakout_level REAL, invalidation_level REAL, reason TEXT,
  PRIMARY KEY (occ_id, seq));
"""


@contextmanager
def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def occ_id(symbol: str, timeframe: str, version: str, o: Occurrence, anchor_ts: int) -> str:
    return f"{symbol}|{timeframe}|{o.pattern}|{o.direction or 'neutral'}|{anchor_ts}|{version}"


def get_run(symbol: str, timeframe: str, version: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM pattern_runs WHERE symbol=? AND timeframe=? AND version=?",
                        (symbol, timeframe, version)).fetchone()
        return dict(r) if r else None


def save(symbol: str, timeframe: str, version: str, series: Series, occs: list[Occurrence], errors: dict,
         params: dict | None = None) -> None:
    now = int(time.time())
    ts = lambda i: int(series.t[min(max(i, 0), series.n - 1)])
    with connect() as con:
        for o in occs:
            oid = occ_id(symbol, timeframe, version, o, ts(o.anchor))
            con.execute(
                """INSERT INTO pattern_occurrences
                   (occ_id,symbol,timeframe,version,pattern,direction,category,maturity,anchor_ts,start_ts,end_ts,
                    status,reason,first_seen_ts,updated_ts,confirmed_ts,confirmed_price,breakout_level,
                    invalidation_level,pivots_json,lines_json,meta_json,params_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(occ_id) DO UPDATE SET
                    start_ts=excluded.start_ts, end_ts=excluded.end_ts, status=excluded.status,
                    reason=excluded.reason, updated_ts=excluded.updated_ts, confirmed_ts=excluded.confirmed_ts,
                    confirmed_price=excluded.confirmed_price, breakout_level=excluded.breakout_level,
                    invalidation_level=excluded.invalidation_level, pivots_json=excluded.pivots_json,
                    lines_json=excluded.lines_json, meta_json=excluded.meta_json""",
                (oid, symbol, timeframe, version, o.pattern, o.direction, o.category, o.maturity, ts(o.anchor),
                 ts(o.start), ts(o.end), o.status, o.reason, ts(o.first_seen), ts(o.updated),
                 ts(o.confirmed_idx) if o.confirmed_idx is not None else None,
                 float(series.c[o.confirmed_idx]) if o.confirmed_idx is not None else None,
                 o.breakout_level, o.invalidation_level,
                 json.dumps([(ts(i), p, lab) for i, p, lab in o.pivots]),
                 json.dumps([{**ln, "x0": ts(ln["x0"]), "x1": ts(ln["x1"])} for ln in o.lines]),
                 json.dumps({k: v for k, v in o.meta.items() if k != "group_key"}, default=str),
                 json.dumps(params or {}, default=str)))
            for seq, h in enumerate(o.history):
                con.execute(
                    "INSERT OR IGNORE INTO pattern_status_history VALUES (?,?,?,?,?,?,?,?)",
                    (oid, seq, ts(h["idx"]), h["status"], h["price"], h["breakout_level"],
                     h["invalidation_level"], h["reason"]))
        con.execute(
            """INSERT INTO pattern_runs VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol,timeframe,version) DO UPDATE SET last_bar_ts=excluded.last_bar_ts,
                 n_bars=excluded.n_bars, errors_json=excluded.errors_json, updated_at=excluded.updated_at""",
            (symbol, timeframe, version, int(series.t[-1]), series.n, json.dumps(errors), now, now))


def load(symbol: str, timeframe: str, version: str, series: Series, status: str | None = None,
         pattern: str | None = None) -> list[dict]:
    """Stored occurrences as API dicts, newest first. Realised outcomes are computed from `series`
    (forward bars) at read time; they are never stored as if final."""
    sql = "SELECT * FROM pattern_occurrences WHERE symbol=? AND timeframe=? AND version=?"
    args: list = [symbol, timeframe, version]
    if status:
        sql += " AND status=?"
        args.append(status)
    if pattern:
        sql += " AND pattern=?"
        args.append(pattern)
    sql += " ORDER BY anchor_ts DESC"
    out = []
    with connect() as con:
        rows = con.execute(sql, args).fetchall()
        for r in rows:
            hist = con.execute("SELECT ts,status,price,breakout_level,invalidation_level,reason "
                               "FROM pattern_status_history WHERE occ_id=? ORDER BY seq", (r["occ_id"],)).fetchall()
            d = {
                "occ_id": r["occ_id"], "pattern": r["pattern"], "direction": r["direction"],
                "category": r["category"], "maturity": r["maturity"], "timeframe": r["timeframe"],
                "status": r["status"], "reason": r["reason"], "anchor_ts": r["anchor_ts"],
                "start_ts": r["start_ts"], "end_ts": r["end_ts"], "first_seen_ts": r["first_seen_ts"],
                "updated_ts": r["updated_ts"], "confirmed_ts": r["confirmed_ts"],
                "confirmed_price": r["confirmed_price"], "breakout_level": r["breakout_level"],
                "invalidation_level": r["invalidation_level"], "detector_version": r["version"],
                "pivots": [{"ts": a, "price": b, "label": c} for a, b, c in json.loads(r["pivots_json"] or "[]")],
                "lines": [{"label": ln.get("label"), "ts0": ln["x0"], "y0": ln["y0"], "ts1": ln["x1"], "y1": ln["y1"]}
                          for ln in json.loads(r["lines_json"] or "[]")],
                "meta": json.loads(r["meta_json"] or "{}"),
                "history": [dict(h) for h in hist],
            }
            d["outcomes"] = _outcomes_from_ts(series, r["confirmed_ts"])
            out.append(d)
    return out


def _outcomes_from_ts(series: Series, confirmed_ts: int | None):
    if confirmed_ts is None:
        return None
    import numpy as np
    idx = int(np.searchsorted(series.t, confirmed_ts))
    if idx >= series.n or series.t[idx] != confirmed_ts:
        return None
    class _O:  # minimal shim so engine.outcomes() can be reused
        confirmed_idx = idx
    return outcomes(series, _O())  # type: ignore[arg-type]
