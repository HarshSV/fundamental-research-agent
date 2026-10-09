"""Angel One SmartAPI historical-candle collector.

Throttled, resumable, checkpointed (fetch_log), retryable, idempotent, gap-aware.
A successful HTTP/API response is NEVER assumed to be complete: every chunk is verified
against what was requested (see verify_chunk) because getCandleData silently truncates
the OLDEST part of an over-long range instead of returning an error.

Uses its own SmartConnect session (not the app's live-quote session) and never prints
credentials or TOTP codes.
"""
import datetime as dt
import json
import os
import tempfile
import time

from . import config, store
from .timeutil import parse_angel_ts, session_date

_ANCHOR = dt.date(2000, 1, 3)
SLACK_DAYS = 6   # weekend + a holiday or two between requested edge and first/last trading day


class RateLimited(Exception):
    pass


def chunk_grid(start: dt.date, end: dt.date, days=config.CHUNK_DAYS):
    """Deterministic, fixed-anchor chunks covering [start, end] -> resumable & idempotent."""
    k0 = (start - _ANCHOR).days // days
    k1 = (end - _ANCHOR).days // days
    out = []
    for k in range(k0, k1 + 1):
        cs = _ANCHOR + dt.timedelta(days=k * days)
        ce = cs + dt.timedelta(days=days - 1)
        out.append((max(cs, start), min(ce, end)))
    return out


def verify_chunk(req_start: dt.date, req_end: dt.date, bar_ts, today: dt.date):
    """Return (status, detail) comparing what was requested with what came back.
    status: ok | empty | late_start | early_end | suspect_truncated | off_session"""
    if not bar_ts:
        return "empty", "no bars returned"
    first = dt.date.fromisoformat(session_date(min(bar_ts)))
    last = dt.date.fromisoformat(session_date(max(bar_ts)))
    notes = []
    status = "ok"
    if (first - req_start).days > SLACK_DAYS:
        status = "late_start"
        notes.append(f"requested start {req_start} but first bar {first}")
    if req_end < today and (req_end - last).days > SLACK_DAYS:
        status = "early_end" if status == "ok" else status
        notes.append(f"requested end {req_end} but last bar {last}")
    if first < req_start or last > req_end:
        status = "off_range"
        notes.append(f"bars {first}..{last} outside requested {req_start}..{req_end}")
    span = (req_end - req_start).days + 1
    if span > 95:
        status = "suspect_truncated"
        notes.append("requested span exceeds provider's safe window")
    return status, "; ".join(notes) or f"{first}..{last}"


class AngelHistory:
    def __init__(self, min_delay=2.0, max_delay=12.0, cooldown=20.0, log=print):
        self.delay = min_delay * 1.5
        self.min_delay, self.max_delay = min_delay, max_delay
        self.log = log
        self.s = None
        self.requests = 0
        self.rate_limit_hits = 0
        self._last = 0.0
        self.tokens = None
        self.cooldown = cooldown
        self.trace_path = os.path.join(config.DATA_DIR, "collector_attempts.log")

    def _trace(self, attempt, outcome):
        """Attempt-level log so the real provider throttle can be measured, not guessed."""
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(self.trace_path, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.1f},{outcome},attempt={attempt},delay={self.delay:.1f}\n")

    # ---- auth (credentials from .env, never printed) ----
    def login(self):
        import pyotp
        from dotenv import load_dotenv
        from SmartApi import SmartConnect
        load_dotenv(os.path.join(config.ROOT, ".env"))
        self.s = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
        r = self.s.generateSession(os.getenv("ANGEL_CLIENT_CODE"), os.getenv("ANGEL_PASSWORD"),
                                   pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET").strip()).now())
        if not r.get("status"):
            raise RuntimeError(f"Angel login failed: {r.get('message')}")
        self.log("[collector] Angel session established")

    # ---- instrument mapping (same scrip master the app already caches) ----
    def scrip_master(self):
        if self.tokens is None:
            path = os.path.join(tempfile.gettempdir(), "navrist_angel_scrip_master.json")
            if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
                with open(path, "r", encoding="utf-8") as f:
                    self.tokens = json.load(f)
            else:
                import requests
                self.tokens = requests.get(
                    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json", timeout=60).json()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.tokens, f)
        return self.tokens

    def resolve(self, symbol):
        """NSE cash-equity token for a symbol ('-EQ' series) or an NSE index by exact name."""
        sym = symbol.strip().upper()
        sm = self.scrip_master()
        for i in sm:
            if i.get("exch_seg") == "NSE" and i.get("symbol") == f"{sym}-EQ":
                return {"exch": "NSE", "token": i["token"], "trading_symbol": i["symbol"], "kind": "equity"}
        for i in sm:
            if i.get("exch_seg") == "NSE" and i.get("instrumenttype") == "AMXIDX" \
                    and sym in (i.get("name", "").upper(), i.get("symbol", "").upper()):
                return {"exch": "NSE", "token": i["token"], "trading_symbol": i["symbol"], "kind": "index"}
        return None

    # ---- throttled request ----
    def _wait(self):
        gap = time.time() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.time()

    def candles(self, exch, token, interval, d0: dt.date, d1: dt.date, max_attempts=6):
        payload = {"exchange": exch, "symboltoken": token, "interval": config.ANGEL_INTERVAL[interval],
                   "fromdate": f"{d0} 09:15", "todate": f"{d1} 15:30"}
        relogged = False
        for attempt in range(1, max_attempts + 1):
            self._wait()
            self.requests += 1
            self._trace(attempt, "request")
            try:
                d = self.s.getCandleData(payload)
                if isinstance(d, dict) and d.get("status") is False:
                    msg = str(d.get("message", "")).lower()
                    if "rate" in msg or d.get("errorcode") in ("AB1010", "AB1004"):
                        raise RateLimited(msg)
                    if ("token" in msg or "session" in msg) and not relogged:
                        self.login(); relogged = True; continue
                    return None, attempt, f"api error {d.get('errorcode')}: {str(d.get('message'))[:120]}"
                self.delay = max(self.min_delay, self.delay * 0.97)   # slowly recover speed
                return (d.get("data") or []), attempt, None
            except RateLimited:
                pass
            except Exception as e:      # SDK raises on the plain-text rate-limit body
                if "exceeding access rate" not in str(e) and "rate" not in str(e).lower():
                    if attempt == max_attempts:
                        return None, attempt, f"exception: {str(e)[:160]}"
                    time.sleep(2 * attempt)
                    continue
            self.rate_limit_hits += 1
            self._trace(attempt, "rate_limited")
            self.delay = min(self.max_delay, self.delay * 1.25)
            time.sleep(self.cooldown)
        return None, max_attempts, "rate limited after retries"


def _to_rows(data):
    rows = []
    for r in data:
        ts = parse_angel_ts(r[0])
        vals = [None if x is None else float(x) for x in r[1:6]]
        rows.append((ts, *vals))
    return rows


def backfill_symbol(client: AngelHistory, con, symbol, interval=config.INTERVAL, years=3.0,
                    today=None, force=False):
    """Fetch every missing/open chunk for one symbol. Safe to interrupt and re-run."""
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(seconds=config.IST_OFFSET_SEC))).date()
    inst = con.execute("SELECT exch,token FROM instruments WHERE symbol=?", (symbol,)).fetchone()
    if inst is None:
        m = client.resolve(symbol)
        if m is None:
            return {"symbol": symbol, "error": "no Angel instrument token (not an NSE -EQ symbol / index)"}
        with store.tx(con):
            con.execute("INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?)",
                        (symbol, m["exch"], m["token"], m["trading_symbol"], m["kind"], int(time.time())))
        inst = (m["exch"], m["token"])
    exch, token = inst
    start = today - dt.timedelta(days=int(years * 365.25))
    summary = {"symbol": symbol, "chunks": 0, "fetched": 0, "skipped": 0, "bars_new": 0, "problems": []}
    now_ts = time.time()
    for d0, d1 in chunk_grid(start, today):
        summary["chunks"] += 1
        key = (symbol, interval, str(d0), str(d1))
        row = con.execute("SELECT status FROM fetch_log WHERE symbol=? AND interval=? AND chunk_start=? AND chunk_end=?", key).fetchone()
        closed = d1 < today
        if row and row[0] in ("ok", "late_start", "empty") and closed and not force:
            summary["skipped"] += 1
            continue
        data, attempts, err = client.candles(exch, token, interval, d0, d1)
        summary["fetched"] += 1
        if data is None:
            status, detail, rows = "error", err, []
        else:
            rows = _to_rows(data)
            # a bar is only usable once COMPLETE; drop the in-progress one
            rows = [r for r in rows if r[0] + config.BAR_SECONDS <= now_ts]
            status, detail = verify_chunk(d0, d1, [r[0] for r in rows], today)
            ins, same, rev = store.upsert_candles(con, symbol, interval, rows)
            summary["bars_new"] += ins
            if rev:
                detail += f"; {rev} revised bars"
        if status not in ("ok",):
            summary["problems"].append((str(d0), str(d1), status, detail))
        with store.tx(con):
            con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (*key, status, len(rows), min((r[0] for r in rows), default=None),
                         max((r[0] for r in rows), default=None), attempts, detail, int(time.time())))
    return summary
