"""Pattern scanner: which stocks are forming / about to break out of / have just confirmed a given chart pattern.

A background build analyses every stock in the universe (the Nifty Total Market list in tools/nse_sector_map) once on its
daily chart: it runs the pattern engine (results persist in the pattern store), then saves ONE small file per stock with
what the screen needs - current pattern occurrences, EMA/SMA levels, returns, market cap, NSE index membership and the
last ~160 daily candles for the chart view. Searching then only reads those files, so filtering is instant.

Nothing is guessed: a value that cannot be computed (too few bars, market cap unavailable, not in any NSE index) is
None and never satisfies a filter on it - it is shown as "-" and is never treated as zero."""
from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("PATTERN_SCAN_DIR", os.path.join(ROOT, "data", "pattern_scan"))
SYMBOL_DIR = os.path.join(DATA_DIR, "symbols")
INDEX_FILE = os.path.join(DATA_DIR, "indices.json")
IST_OFFSET = 19800

# official NSE index constituent lists = the "index" filter (large / mid / small / micro cap)
INDEX_URLS = {
    "large": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",       # NIFTY 100
    "mid": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",   # NIFTY MIDCAP 150
    "small": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",  # NIFTY SMALLCAP 250
    "micro": "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",  # NIFTY MICROCAP 250
}
INDEX_LABEL = {"large": "Large Cap (Nifty 100)", "mid": "Mid Cap (Nifty Midcap 150)",
               "small": "Small Cap (Nifty Smallcap 250)", "micro": "Micro Cap (Nifty Microcap 250)"}
MA_PERIODS = (10, 20, 50, 100, 200)
CONFIRMED_WINDOW_BARS = 10          # a confirmation counts as "recent" for this many bars
CHART_BARS = 160

_lock = threading.Lock()
_mem: dict = {"mtime": 0.0, "rows": {}}


# ------------------------------------------------------------------ universe + index membership
def _names() -> dict:
    try:
        with open(os.path.join(ROOT, "cache", "nse_company_names.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def universe() -> list[dict]:
    """[{symbol, name, sector}] for every company in the sector-mapped universe."""
    from tools import nse_sector_map as sm
    names = _names()
    out = []
    for sector, syms in sm.all_symbols_by_sector().items():
        for s in syms:
            out.append({"symbol": s, "name": names.get(s) or s, "sector": sector})
    return sorted(out, key=lambda x: x["symbol"])


def index_membership(max_age_days: int = 7) -> dict:
    """{symbol: 'large'|'mid'|'small'|'micro'} from NSE's own index lists; cached on disk."""
    try:
        if os.path.exists(INDEX_FILE) and time.time() - os.path.getmtime(INDEX_FILE) < max_age_days * 86400:
            with open(INDEX_FILE, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    import requests
    out: dict = {}
    for cls, url in INDEX_URLS.items():
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
            if r.status_code != 200:
                continue
            for row in csv.DictReader(io.StringIO(r.text)):
                sym = (row.get("Symbol") or "").strip().upper()
                if sym:
                    out.setdefault(sym, cls)
        except Exception as e:
            print(f"[pattern_scan] index list {cls} failed: {e}")
    if out:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(INDEX_FILE, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
        return out
    try:  # stale copy is better than none
        with open(INDEX_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


# ------------------------------------------------------------------ per-stock analysis
def _ema(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _sma(vals: list[float], n: int) -> float | None:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _market_cap_cr(symbol: str, price: float | None) -> float | None:
    """Market cap in Rs crore: the Screener figure the stock page shows when known, else Yahoo's share count x the latest
    close. None when neither is available."""
    try:
        with open(os.path.join(ROOT, "data", "screens", "universe.json"), encoding="utf-8") as fh:
            v = (json.load(fh).get(symbol) or {}).get("market_cap_cr")
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    except Exception:
        pass
    try:
        import yfinance as yf
        from tools.live_chart_yf import _to_symbol
        fi = yf.Ticker(_to_symbol(symbol)).fast_info
        mc = fi.get("market_cap")
        if not (isinstance(mc, (int, float)) and mc > 0):
            sh = fi.get("shares")
            mc = sh * price if isinstance(sh, (int, float)) and sh > 0 and isinstance(price, (int, float)) and price > 0 else None
        if isinstance(mc, (int, float)) and mc > 0:
            return round(float(mc) / 1e7, 2)
    except Exception:
        pass
    return None


def _current(occs: list[dict], times: list[int]) -> list[dict]:
    """Occurrences that matter right now: still forming, awaiting breakout, or confirmed within the last few bars."""
    cutoff = times[-CONFIRMED_WINDOW_BARS] if len(times) >= CONFIRMED_WINDOW_BARS else times[0]
    keep = []
    for o in occs:
        st = o.get("status")
        if st in ("forming", "awaiting_breakout") or (st == "confirmed" and (o.get("confirmed_ts") or 0) >= cutoff):
            keep.append({
                "pattern": o["pattern"], "status": st, "direction": o.get("direction"),
                "start_ts": o.get("start_ts"), "end_ts": o.get("end_ts"), "confirmed_ts": o.get("confirmed_ts"),
                "breakout": o.get("breakout_level"), "invalidation": o.get("invalidation_level"),
                "lines": [{"label": ln.get("label"), "ts0": ln.get("ts0"), "y0": ln.get("y0"), "ts1": ln.get("ts1"), "y1": ln.get("y1")}
                          for ln in (o.get("lines") or [])],
            })
    return keep


def scan_one(item: dict) -> dict:
    """Analyse one stock and write its file. Safe to run in a worker process; never raises."""
    sym = item["symbol"]
    try:
        from patterns import service
        from screens.metrics import _return
        from tools.live_chart_yf import get_candles
        candles = get_candles(sym, interval="1d", period="5y")
        if not candles or len(candles) < 60:
            return {"symbol": sym, "ok": False, "reason": "not enough price history"}
        res = service.get_patterns(sym, "1d", lambda *_: candles)
        closes = [c["close"] for c in candles]
        times = [c["time"] for c in candles]
        last = candles[-1]
        year_ago = last["time"] - 365 * 86400
        hi52 = max((c["high"] for c in candles if c["time"] >= year_ago), default=None)
        has_year = candles[0]["time"] <= year_ago + 7 * 86400
        row = {
            "symbol": sym, "name": item["name"], "sector": item["sector"], "index": item.get("index"),
            "as_of": last["time"], "price": last["close"], "market_cap_cr": _market_cap_cr(sym, last["close"]),
            "ret_1m": _return(candles, 30), "ret_3m": _return(candles, 91),
            "pct_from_52w_high": ((hi52 - last["close"]) / hi52 * 100.0) if (hi52 and has_year) else None,
            "ema": {str(n): _ema(closes, n) for n in MA_PERIODS},
            "sma": {str(n): _sma(closes, n) for n in MA_PERIODS},
            "occurrences": _current(res.get("occurrences") or [], times),
            "candles": [[c["time"], round(c["open"], 2), round(c["high"], 2), round(c["low"], 2), round(c["close"], 2),
                         round(c.get("volume") or 0)] for c in candles[-CHART_BARS:]],
            "scanned_at": int(time.time()),
        }
        os.makedirs(SYMBOL_DIR, exist_ok=True)
        tmp = os.path.join(SYMBOL_DIR, f"{sym}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(row, fh)
        os.replace(tmp, os.path.join(SYMBOL_DIR, f"{sym}.json"))
        return {"symbol": sym, "ok": True}
    except Exception as e:  # one bad company must never stop the scan
        return {"symbol": sym, "ok": False, "reason": f"{type(e).__name__}: {e}"[:120]}


# ------------------------------------------------------------------ background build
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
_proc = None


def _write_progress(**kw) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
            json.dump(kw, fh)
    except Exception:
        pass


def _run_scan(force: bool, workers: int | None, only: list[str] | None) -> None:
    """The scan itself (runs in its own process: `python -m patterns.scan --run`)."""
    started = int(time.time())
    idx = index_membership()
    items = [dict(u, index=idx.get(u["symbol"])) for u in universe() if not only or u["symbol"] in only]
    if not force:
        fresh = {s for s, r in _load_all().items() if time.time() - r.get("scanned_at", 0) < 12 * 3600}
        items = [i for i in items if i["symbol"] not in fresh]
    total, done, errors = len(items), 0, 0
    _write_progress(building=True, total=total, done=0, errors=0, started=started, finished=None)
    n = workers or max(2, min(8, (os.cpu_count() or 4) - 2))
    with ProcessPoolExecutor(max_workers=n) as ex:
        for r in ex.map(scan_one, items, chunksize=1):
            done += 1
            if not r.get("ok"):
                errors += 1
                print(f"[pattern_scan] {r['symbol']}: {r.get('reason')}", flush=True)
            if done % 5 == 0 or done == total:
                _write_progress(building=True, total=total, done=done, errors=errors, started=started, finished=None)
    _write_progress(building=False, total=total, done=done, errors=errors, started=started, finished=int(time.time()))


def status() -> dict:
    prog = {}
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as fh:
            prog = json.load(fh)
    except Exception:
        pass
    running = _proc is not None and _proc.poll() is None
    if prog.get("building") and not running:   # the scan process died: do not claim it is still working
        prog["building"] = False
    return {"building": bool(prog.get("building")), "done": prog.get("done", 0), "total": prog.get("total", 0),
            "errors": prog.get("errors", 0), "started": prog.get("started"), "finished": prog.get("finished"),
            "have": len(_load_all()), "universe": len(universe())}


def build(force: bool = False, workers: int | None = None, only: list[str] | None = None) -> bool:
    """Start the scan in a separate process (the web server only reads its results). False if one is already running.
    Stocks scanned within the last 12 hours are skipped unless `force`."""
    global _proc
    import subprocess
    import sys
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return False
        cmd = [sys.executable, "-m", "patterns.scan", "--run"]
        if force:
            cmd.append("--force")
        if workers:
            cmd += ["--workers", str(workers)]
        if only:
            cmd += ["--only", ",".join(only)]
        log = open(os.path.join(DATA_DIR, "scan.log"), "a", encoding="utf-8") if os.path.isdir(DATA_DIR) else subprocess.DEVNULL
        _proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        return True


# ------------------------------------------------------------------ reading + filtering
def _load_all() -> dict:
    """{symbol: row}, re-read only when the folder changed."""
    try:
        files = [f for f in os.listdir(SYMBOL_DIR) if f.endswith(".json")]
        mt = max((os.path.getmtime(os.path.join(SYMBOL_DIR, f)) for f in files), default=0.0)
    except FileNotFoundError:
        return {}
    if mt == _mem["mtime"] and len(_mem["rows"]) == len(files):
        return _mem["rows"]
    rows = {}
    for f in files:
        try:
            with open(os.path.join(SYMBOL_DIR, f), encoding="utf-8") as fh:
                r = json.load(fh)
            rows[r["symbol"]] = r
        except Exception:
            continue
    _mem["mtime"], _mem["rows"] = mt, rows
    return rows


def options() -> dict:
    uni = universe()
    sectors = sorted({u["sector"] for u in uni})
    caps = [r["market_cap_cr"] for r in _load_all().values() if isinstance(r.get("market_cap_cr"), (int, float))]
    return {
        "indices": [{"id": k, "label": v} for k, v in INDEX_LABEL.items()],
        "sectors": sectors,
        "ma_periods": list(MA_PERIODS),
        "statuses": [{"id": "forming", "label": "Forming"}, {"id": "awaiting_breakout", "label": "Awaiting breakout"},
                     {"id": "confirmed", "label": "Confirmed (last %d sessions)" % CONFIRMED_WINDOW_BARS}],
        "market_cap_cr": {"min": min(caps) if caps else None, "max": max(caps) if caps else None},
    }


def _match(values: list, have: list) -> bool:
    """values = what the user ticked; have = what the stock offers. A stock matches when it has at least one ticked option;
    nothing ticked means no restriction."""
    return not values or any(v in set(have) for v in values)


def _ma_ok(row: dict, kind: str, spec: dict) -> bool:
    periods = [str(p) for p in (spec or {}).get("periods") or []]
    if not periods:
        return True
    price = row.get("price")
    side = (spec or {}).get("side", "above")
    ok = []
    for p in periods:
        v = (row.get(kind) or {}).get(p)
        ok.append(isinstance(v, (int, float)) and isinstance(price, (int, float)) and (price > v if side == "above" else price < v))
    return any(ok)


_STATUS_RANK = {"awaiting_breakout": 0, "forming": 1, "confirmed": 2}


def search(pattern: str, f: dict, include_candles: bool = False) -> dict:
    rows = _load_all()
    mc = f.get("mcap") or {}
    lo, hi = mc.get("min"), mc.get("max")
    ind, sec, stat = f.get("indices") or {}, f.get("sectors") or {}, f.get("status") or {}
    q = (f.get("q") or "").strip().lower()
    out = []
    for r in rows.values():
        occ = [o for o in r["occurrences"] if o["pattern"] == pattern]
        if not occ:
            continue
        if stat.get("values") and not _match(stat["values"], [o["status"] for o in occ]):
            continue
        if stat.get("values"):
            occ = [o for o in occ if o["status"] in stat["values"]] or occ
        if ind.get("values") and not _match(ind["values"], [r.get("index")] if r.get("index") else []):
            continue
        if sec.get("values") and not _match(sec["values"], [r.get("sector")]):
            continue
        cap = r.get("market_cap_cr")
        if (lo is not None or hi is not None) and not isinstance(cap, (int, float)):
            continue
        if lo is not None and cap < lo:
            continue
        if hi is not None and cap > hi:
            continue
        if not _ma_ok(r, "ema", f.get("ema")) or not _ma_ok(r, "sma", f.get("dma")):
            continue
        if q and q not in r["symbol"].lower() and q not in (r.get("name") or "").lower():
            continue
        best = sorted(occ, key=lambda o: (_STATUS_RANK.get(o["status"], 9), -(o.get("end_ts") or 0)))[0]
        row = {k: r.get(k) for k in ("symbol", "name", "sector", "index", "price", "market_cap_cr", "ret_1m", "ret_3m",
                                      "pct_from_52w_high", "as_of")}
        row["occurrence"] = best
        row["occurrence_count"] = len(occ)
        if include_candles:
            row["candles"] = r["candles"]
        out.append(row)
    sort = f.get("sort") or "status"
    if sort == "market_cap":
        out.sort(key=lambda x: -(x["market_cap_cr"] or -1))
    elif sort == "name":
        out.sort(key=lambda x: x["name"] or x["symbol"])
    else:
        out.sort(key=lambda x: (_STATUS_RANK.get(x["occurrence"]["status"], 9), -(x["market_cap_cr"] or -1)))
    page = max(1, int(f.get("page") or 1))
    size = min(100, max(1, int(f.get("page_size") or 50)))
    return {"pattern": pattern, "total": len(out), "page": page, "page_size": size,
            "rows": out[(page - 1) * size: page * size], "scan": status()}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Scan the universe for chart patterns")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if a.run:
        os.makedirs(DATA_DIR, exist_ok=True)
        _run_scan(a.force, a.workers, [x for x in a.only.split(",") if x] or None)
