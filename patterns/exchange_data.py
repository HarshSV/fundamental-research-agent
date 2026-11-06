"""Exchange data the scanner pages need, read from NSE's public files and APIs and kept as small JSON files in data/exchange/:

  listings    date of listing, face value (EQUITY_L.csv)               -> Recent IPOs, IPO Setups, "listed after" filter
  fno         the F&O stock list (fo_mktlots.csv)                       -> "F&O only" filter
  bands       today's price band of every security and the revisions   -> Circuit Revision List, "exclude 5% / 2% circuit stocks"
              found by comparing the daily sec_list files
  asm         the ASM (additional surveillance) long and short term     -> ASM markers and "exclude ASM" filter
  deals       bulk and block deals; each day's file is appended          -> Bulk Deals, Block Deals, block-deal marker
  calendar    announced board meetings for financial results            -> Results Calendar (upcoming), "results coming soon" marker
  results     when each company filed each quarter's results            -> Earnings Gap Up / Positive Earnings Reaction, Results Calendar
  orders      corporate announcements about orders and contracts         -> Order Wins
  indices     all NSE indices with returns                              -> Sector Indices

Nothing is invented: a feed that cannot be read keeps the last good copy and reports the error; a stock missing from a list simply
has no value for it (never False for "unknown")."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.environ.get("EXCHANGE_DATA_DIR", os.path.join(ROOT, "data", "exchange"))
STALE_SECONDS = 6 * 3600
BAND_DAYS = 30
DEAL_KEEP_DAYS = 120
ORDER_DAYS = 14
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
ARCHIVE = "https://nsearchives.nseindia.com/content"

_lock = threading.Lock()
_state = {"running": False, "last": 0.0, "errors": {}}
_mem: dict = {}


# ------------------------------------------------------------------ storage
def _path(name: str) -> str:
    return os.path.join(DIR, f"{name}.json")


def load(name: str):
    """The stored feed, or None if it has never been read. Cached in memory by file time."""
    p = _path(name)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    hit = _mem.get(name)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(p, encoding="utf-8") as fh:
            v = json.load(fh)
    except Exception:
        return None
    _mem[name] = (mt, v)
    return v


def _save(name: str, value) -> None:
    os.makedirs(DIR, exist_ok=True)
    tmp = _path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh)
    os.replace(tmp, _path(name))


# ------------------------------------------------------------------ http
def _text(url: str) -> str | None:
    try:
        r = requests.get(url, headers=UA, timeout=40)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({**UA, "Referer": "https://www.nseindia.com/", "Accept": "application/json, text/plain, */*"})
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-financial-results", timeout=25)
    return s


def _json(s: requests.Session, url: str):
    last = None
    for attempt in range(3):
        try:
            r = s.get(url, timeout=60)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "failed")


def _iso(d: str, fmt: str) -> str | None:
    try:
        return datetime.strptime(d.strip(), fmt).date().isoformat()
    except Exception:
        return None


# ------------------------------------------------------------------ feeds
def _listings() -> dict:
    t = _text(f"{ARCHIVE}/equities/EQUITY_L.csv")
    if not t:
        raise RuntimeError("EQUITY_L.csv not reachable")
    out = {}
    for row in csv.DictReader(io.StringIO(t)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        sym = row.get("SYMBOL")
        listed = _iso(row.get("DATE OF LISTING", ""), "%d-%b-%Y")
        if sym and listed:
            out[sym] = {"listed": listed, "face_value": row.get("FACE VALUE"), "series": row.get("SERIES"), "name": row.get("NAME OF COMPANY")}
    return out


def _fno() -> list:
    t = _text(f"{ARCHIVE}/fo/fo_mktlots.csv")
    if not t:
        raise RuntimeError("fo_mktlots.csv not reachable")
    syms = []
    for i, row in enumerate(csv.reader(io.StringIO(t))):
        if i < 1 or len(row) < 2:
            continue
        s = row[1].strip()
        if s and s.upper() != "SYMBOL":
            syms.append(s)
    return sorted(set(syms))


def _bands() -> dict:
    """Today's band per symbol and the revisions seen between consecutive daily files (effective date = the later file's date)."""
    days = {}
    d = date.today()
    for back in range(0, BAND_DAYS + 1):
        day = d - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        t = _text(f"{ARCHIVE}/equities/sec_list_{day:%d%m%Y}.csv")
        if not t:
            continue
        m = {}
        for row in csv.DictReader(io.StringIO(t)):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if row.get("Symbol"):
                m[row["Symbol"]] = row.get("Band", "")
        if m:
            days[day.isoformat()] = m
    if not days:
        raise RuntimeError("no sec_list file reachable")
    order = sorted(days)
    current = days[order[-1]]
    revisions = []
    for a, b in zip(order, order[1:]):
        for sym, band in days[b].items():
            before = days[a].get(sym)
            if before is not None and before != band:
                revisions.append({"date": b, "symbol": sym, "from": before, "to": band})
    revisions.sort(key=lambda r: r["date"], reverse=True)
    return {"as_of": order[-1], "band": current, "revisions": revisions}


def _asm(s) -> dict:
    j = _json(s, "https://www.nseindia.com/api/reportASM")
    out = {}
    for kind in ("longterm", "shortterm"):
        for r in ((j.get(kind) or {}).get("data") or []):
            sym = (r.get("symbol") or r.get("asmSymbol") or "").strip()
            if sym:
                out[sym] = {"kind": "LT" if kind == "longterm" else "ST", "stage": r.get("asmSurvIndicator"), "code": r.get("survCode"),
                            "name": r.get("companyName"), "date": r.get("asmTime")}
    if not out and (j.get("longterm") or j.get("shortterm")):
        sample = ((j.get("longterm") or {}).get("data") or [{}])[0]
        raise RuntimeError(f"ASM rows had no symbol field; keys: {sorted(sample)}")
    return out


def _deals() -> dict:
    hist = load("deals") or {"bulk": [], "block": []}
    for kind in ("bulk", "block"):
        t = _text(f"{ARCHIVE}/equities/{kind}.csv")
        if not t:
            continue
        seen = {(x["date"], x["symbol"], x["client"], x["side"], x["qty"]) for x in hist[kind]}
        for row in csv.DictReader(io.StringIO(t)):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            d = _iso(row.get("Date", ""), "%d-%b-%Y")
            if not d or not row.get("Symbol"):
                continue
            try:
                qty = int(float(row.get("Quantity Traded", "0").replace(",", "")))
                price = float(row.get("Trade Price / Wght. Avg. Price", "0").replace(",", ""))
            except ValueError:
                continue
            rec = {"date": d, "symbol": row["Symbol"], "name": row.get("Security Name"), "client": row.get("Client Name"),
                   "side": row.get("Buy/Sell"), "qty": qty, "price": price}
            if (rec["date"], rec["symbol"], rec["client"], rec["side"], rec["qty"]) not in seen:
                hist[kind].append(rec)
    cutoff = (date.today() - timedelta(days=DEAL_KEEP_DAYS)).isoformat()
    for kind in ("bulk", "block"):
        hist[kind] = sorted([x for x in hist[kind] if x["date"] >= cutoff], key=lambda x: (x["date"], x["symbol"]), reverse=True)
    return hist


def _calendar(s) -> list:
    rows = _json(s, "https://www.nseindia.com/api/event-calendar")
    out = []
    for r in rows if isinstance(rows, list) else []:
        d = _iso(r.get("date", ""), "%d-%b-%Y")
        if d and r.get("symbol"):
            out.append({"symbol": r["symbol"], "name": r.get("company"), "purpose": r.get("purpose"), "date": d, "desc": r.get("bm_desc")})
    return out


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ENDED = re.compile(r"(?:quarter|period|half[- ]year|year)\s+ended\s+(?:on\s+)?([^.;]{6,40})", re.I)
_DAYMON = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s,/-]+([A-Za-z]{3,9})[\s,/-]+(\d{4})")
_MONDAY = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})")


def _quarter_end(text: str) -> str | None:
    """The quarter-end date a results announcement says it covers ('...results for the quarter ended September 30, 2026'), or None."""
    m = _ENDED.search(text or "")
    if not m:
        return None
    seg = m.group(1)
    for rx, order in ((_DAYMON, "dmy"), (_MONDAY, "mdy")):
        g = rx.search(seg)
        if not g:
            continue
        d, mon, y = (g.group(1), g.group(2), g.group(3)) if order == "dmy" else (g.group(2), g.group(1), g.group(3))
        mon = _MONTHS.get(mon[:3].lower())
        if mon in (3, 6, 9, 12):
            try:
                return date(int(y), mon, int(d)).isoformat()
            except ValueError:
                return None
    return None


def _results(s) -> dict:
    """symbol -> {quarter_end(iso): earliest filing time 'YYYY-MM-DDTHH:MM:SS'}, read from 'Outcome of Board Meeting' and 'Integrated
    Filing- Financial' announcements whose text names the period. The first run reads about 4 months; later runs only the last 2 weeks
    and merge. (NSE's financial-results API no longer lists the current quarter, so it is not used.)"""
    out: dict = load("results") or {}
    days_back = 14 if out else 130
    today = date.today()
    end = today
    while (today - end).days < days_back:
        start = max(end - timedelta(days=9), today - timedelta(days=days_back))
        try:
            rows = _json(s, f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}")
        except Exception:
            rows = []
        for r in rows if isinstance(rows, list) else []:
            subj = r.get("desc") or ""
            if subj not in ("Outcome of Board Meeting", "Integrated Filing- Financial"):
                continue
            q = _quarter_end(r.get("attchmntText") or "")
            sym = r.get("symbol")
            ts = r.get("an_dt") or r.get("sort_date") or ""
            try:
                ts = datetime.strptime(ts.strip(), "%d-%b-%Y %H:%M:%S").isoformat()
            except ValueError:
                continue
            if not sym or not q or not re.search(r"result", r.get("attchmntText") or "", re.I):
                continue
            cur = out.setdefault(sym, {})
            if q not in cur or ts < cur[q]:
                cur[q] = ts
        end = start - timedelta(days=1)
        time.sleep(0.8)
    if not out:
        raise RuntimeError("no results announcements found")
    return out


# An "order win" is an announcement whose subject says an order / contract was bagged, awarded or received, or a press release /
# update whose text says so. Regulatory "orders passed against the company" and the like are excluded.
_ORDER_SUBJECT = re.compile(r"bagging|receiving of orders|award of (an? )?(order|contract)|letter of (award|intent)|receipt of (an? )?order|new orders?|order (win|inflow|book)", re.I)
_ORDER_TEXT = re.compile(r"(secured|bagged|received|awarded|won|win|bags|receipt of|letter of (award|intent)|loa|loi)[^.]{0,80}(order|orders|contract|contracts)|(order|contract)[^.]{0,60}(awarded|secured|received)", re.I)
_ORDER_EXCLUDE = re.compile(r"action\(s\) taken|orders? passed|court|tribunal|nclt|sebi|penalt|newspaper|trading window|credit rating|loss of share|duplicate|record date", re.I)


def _orders(s) -> list:
    to = date.today()
    rows = _json(s, f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={(to - timedelta(days=ORDER_DAYS)):%d-%m-%Y}&to_date={to:%d-%m-%Y}")
    out = []
    for r in rows if isinstance(rows, list) else []:
        subject, text = r.get("desc") or "", r.get("attchmntText") or ""
        if _ORDER_EXCLUDE.search(subject):
            continue
        is_order = bool(_ORDER_SUBJECT.search(subject)) or (re.search(r"press release|updates?|general", subject, re.I) and _ORDER_TEXT.search(text))
        if not is_order:
            continue
        out.append({"time": r.get("an_dt") or r.get("sort_date"), "symbol": r.get("symbol"), "name": r.get("sm_name"), "subject": subject,
                    "text": text[:900], "file": r.get("attchmntFile")})
    out.sort(key=lambda x: x["time"] or "", reverse=True)
    return out


def _indices(s) -> list:
    j = _json(s, "https://www.nseindia.com/api/allIndices")
    keep = ("index", "key", "last", "variation", "percentChange", "open", "high", "low", "previousClose", "yearHigh", "yearLow", "perChange30d", "perChange365d", "pe", "pb", "dy")
    return [{k: r.get(k) for k in keep} for r in (j.get("data") or []) if r.get("index")]


# ------------------------------------------------------------------ refresh
def refresh(force: bool = False) -> dict:
    """Read every feed (about a minute). A feed that fails keeps its last good copy; errors are reported in status()."""
    with _lock:
        if _state["running"]:
            return status()
        if not force and time.time() - _state["last"] < STALE_SECONDS and load("listings") is not None:
            return status()
        _state["running"] = True
    errors = {}
    try:
        sess = None

        def need():
            nonlocal sess
            if sess is None:
                sess = _session()
            return sess

        jobs = [("listings", _listings), ("fno", _fno), ("bands", _bands), ("deals", _deals),
                ("asm", lambda: _asm(need())), ("calendar", lambda: _calendar(need())), ("results", lambda: _results(need())),
                ("orders", lambda: _orders(need())), ("indices", lambda: _indices(need()))]
        for name, fn in jobs:
            try:
                _save(name, fn())
            except Exception as e:  # keep the last good copy
                errors[name] = str(e)[:160]
        _save("meta", {"at": time.time(), "errors": errors})
    finally:
        with _lock:
            _state.update({"running": False, "last": time.time(), "errors": errors})
    return status()


def status() -> dict:
    meta = load("meta") or {}
    return {"running": _state["running"], "at": meta.get("at"), "errors": _state["errors"] or meta.get("errors", {}),
            "have": [n for n in ("listings", "fno", "bands", "asm", "deals", "calendar", "results", "orders", "indices") if os.path.exists(_path(n))]}


def ensure_fresh() -> None:
    """Start a background read when the data is missing or older than a few hours (never blocks the caller)."""
    meta = load("meta") or {}
    if _state["running"] or (meta.get("at") and time.time() - meta["at"] < STALE_SECONDS):
        return
    threading.Thread(target=refresh, kwargs={"force": True}, daemon=True).start()
