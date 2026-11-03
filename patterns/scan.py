"""Market scanner: the data behind the pattern pages, the screener and the backtests.

A background build analyses every stock in the universe (the Nifty Total Market list in tools/nse_sector_map) once on its
daily chart: it runs the pattern engine (results persist in the pattern store), then saves ONE small file per stock with
what the screens need - current pattern occurrences, technical measures (moving averages, 52-week / all-time distances,
average daily range, turnover, relative-strength input, returns), any horizontal resistance, every historical confirmed
pattern as a backtest trade, the NSE index membership, the market cap and the last ~160 candles for the chart view.
Searching (patterns/screen_engine.py) only reads those files, so filtering is instant.

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

from .features import _ema, _sma, metrics, resistance, resistance_trades, trades  # noqa: F401  (_ema/_sma re-exported for callers and tests)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("PATTERN_SCAN_DIR", os.path.join(ROOT, "data", "pattern_scan"))
SYMBOL_DIR = os.path.join(DATA_DIR, "symbols")
INDEX_FILE = os.path.join(DATA_DIR, "indices.json")
BENCH_FILE = os.path.join(DATA_DIR, "benchmarks.json")
FUNDAMENTALS_FILE = os.path.join(ROOT, "data", "screens", "universe.json")
IST_OFFSET = 19800
DAY = 86400

# official NSE index constituent lists = the "index" filter (large / mid / small / micro cap)
INDEX_URLS = {
    "large": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",       # NIFTY 100
    "mid": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",   # NIFTY MIDCAP 150
    "small": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",  # NIFTY SMALLCAP 250
    "micro": "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",  # NIFTY MICROCAP 250
}
INDEX_LABEL = {"large": "Large Cap (Nifty 100)", "mid": "Mid Cap (Nifty Midcap 150)",
               "small": "Small Cap (Nifty Smallcap 250)", "micro": "Micro Cap (Nifty Microcap 250)"}
BENCHMARKS = {"nifty50": "^NSEI", "nifty500": "^CRSLDX"}          # what a sector's strength is measured against
MA_PERIODS = (10, 20, 50, 100, 200)
CONFIRMED_WINDOW_BARS = 10          # a confirmation counts as "recent" for this many bars
CHART_BARS = 160
CLOSE_BARS = 520                    # closes kept per stock (about 2 years) for sector rotation
PATTERN_YEARS = 5                   # the pattern engine's window

_lock = threading.Lock()
_mem: dict = {"stamp": None, "rows": {}}


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


def refresh_benchmarks() -> None:
    """Daily closes (about 2 years) of the benchmark indices, for the sector-rotation (RRG) filter."""
    try:
        import yfinance as yf
        out = {}
        for key, ticker in BENCHMARKS.items():
            h = yf.Ticker(ticker).history(period="3y", interval="1d")
            rows = [[int(ts.timestamp()), round(float(c), 2)] for ts, c in zip(h.index, h["Close"]) if c == c]
            if rows:
                out[key] = rows[-CLOSE_BARS:]
        if out:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(BENCH_FILE, "w", encoding="utf-8") as fh:
                json.dump(out, fh)
    except Exception as e:
        print(f"[pattern_scan] benchmark refresh failed: {e}")


# ------------------------------------------------------------------ per-stock analysis
def _market_cap_cr(symbol: str, price: float | None) -> float | None:
    """Market cap in Rs crore: the Screener figure the stock page shows when known, else Yahoo's share count x the latest
    close. None when neither is available."""
    try:
        with open(FUNDAMENTALS_FILE, encoding="utf-8") as fh:
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
        from tools.live_chart_yf import get_candles
        full = get_candles(sym, interval="1d", period="max")      # all-time measures need the whole history
        if not full or len(full) < 60:
            return {"symbol": sym, "ok": False, "reason": "not enough price history"}
        last = full[-1]
        # the pattern engine works on the last five years only (that window also tells it whether the listing date is known)
        window = [c for c in full if c["time"] >= last["time"] - int(PATTERN_YEARS * 365.25 * DAY)]
        res = service.get_patterns(sym, "1d", lambda *_: window)
        times = [c["time"] for c in window]
        row = {
            "symbol": sym, "name": item["name"], "sector": item["sector"], "index": item.get("index"),
            "as_of": last["time"], "market_cap_cr": _market_cap_cr(sym, last["close"]),
            **metrics(full),
            "resistance": resistance(full),
            "occurrences": _current(res.get("occurrences") or [], times),
            "trades": trades(res.get("occurrences") or [], window) + resistance_trades(full),
            "closes": [[c["time"], round(c["close"], 2)] for c in full[-CLOSE_BARS:]],
            "candles": [[c["time"], round(c["open"], 2), round(c["high"], 2), round(c["low"], 2), round(c["close"], 2),
                         round(c.get("volume") or 0)] for c in full[-CHART_BARS:]],
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
        fresh = {s for s, r in _load_all().items() if time.time() - r.get("scanned_at", 0) < 12 * 3600 and "trades" in r}
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
    refresh_benchmarks()
    _write_progress(building=False, total=total, done=done, errors=errors, started=started, finished=int(time.time()))


def status() -> dict:
    prog = {}
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as fh:
            prog = json.load(fh)
    except Exception:
        pass
    running = _proc is not None and _proc.poll() is None
    if prog.get("building") and not running and _proc is not None:   # the scan process died: do not claim it is still working
        prog["building"] = False
    return {"building": bool(prog.get("building")), "done": prog.get("done", 0), "total": prog.get("total", 0),
            "errors": prog.get("errors", 0), "started": prog.get("started"), "finished": prog.get("finished"),
            "have": len(_load_all()), "universe": len(universe())}


def refresh_resistance(workers: int = 8) -> int:
    """Recompute only the horizontal-resistance field of every scanned stock (after a change of the rule), without a full rescan."""
    from concurrent.futures import ThreadPoolExecutor
    from tools.live_chart_yf import get_candles

    def one(f):
        path = os.path.join(SYMBOL_DIR, f)
        try:
            with open(path, encoding="utf-8") as fh:
                row = json.load(fh)
            candles = get_candles(row["symbol"], interval="1d", period="max")
            if not candles or len(candles) < 60:
                return 0
            row["resistance"] = resistance(candles[-520:])
            row["trades"] = [t for t in (row.get("trades") or []) if t[0] != "horizontal-resistance"] + resistance_trades(candles)
            with open(path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(row, fh)
            os.replace(path + ".tmp", path)
            return 1
        except Exception as e:
            print(f"[pattern_scan] resistance {f}: {e}", flush=True)
            return 0

    files = [f for f in os.listdir(SYMBOL_DIR) if f.endswith(".json")]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return sum(ex.map(one, files))


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
        os.makedirs(DATA_DIR, exist_ok=True)
        log = open(os.path.join(DATA_DIR, "scan.log"), "a", encoding="utf-8")
        _proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        return True


# ------------------------------------------------------------------ reading
def _fundamentals() -> dict:
    try:
        with open(FUNDAMENTALS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _load_all() -> dict:
    """{symbol: row}: the per-stock files joined with the Screener fundamentals and a relative-strength rating, re-built
    only when the files changed."""
    try:
        files = [f for f in os.listdir(SYMBOL_DIR) if f.endswith(".json")]
        stamp = (len(files), max((os.path.getmtime(os.path.join(SYMBOL_DIR, f)) for f in files), default=0.0),
                 os.path.getmtime(FUNDAMENTALS_FILE) if os.path.exists(FUNDAMENTALS_FILE) else 0.0)
    except FileNotFoundError:
        return {}
    if stamp == _mem["stamp"]:
        return _mem["rows"]
    funda = _fundamentals()
    rows = {}
    for f in files:
        try:
            with open(os.path.join(SYMBOL_DIR, f), encoding="utf-8") as fh:
                r = json.load(fh)
        except Exception:
            continue
        fd = funda.get(r["symbol"]) or {}
        for k in ("pe", "eps", "eps_growth", "debt_equity", "promoter", "div_yield", "payout", "net_profit_cr", "volatility"):
            v = fd.get(k)
            r[k] = v if isinstance(v, (int, float)) else None
        from screens.metrics import is_financial
        if is_financial(r.get("sector")):
            r["debt_equity"] = None
        r["free_float"] = (100.0 - r["promoter"]) if isinstance(r.get("promoter"), (int, float)) else None
        rows[r["symbol"]] = r
    raws = sorted(r["rs_raw"] for r in rows.values() if isinstance(r.get("rs_raw"), (int, float)))
    for r in rows.values():                      # RS rating 1-99: where the stock's performance ranks among all scanned stocks
        v = r.get("rs_raw")
        if isinstance(v, (int, float)) and len(raws) > 1:
            import bisect
            r["rs"] = max(1, min(99, round(bisect.bisect_left(raws, v) / (len(raws) - 1) * 98 + 1)))
        else:
            r["rs"] = None
    _mem["stamp"], _mem["rows"] = stamp, rows
    return rows


def benchmarks() -> dict:
    try:
        with open(BENCH_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def options() -> dict:
    from . import screen_engine as eng
    return eng.options()


def search(pattern, f: dict, include_candles: bool = False) -> dict:
    from . import screen_engine as eng
    return eng.search(pattern, f, include_candles=include_candles)


def backtest(pattern: str, f: dict) -> dict:
    from . import screen_engine as eng
    return eng.backtest(pattern, f)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Scan the universe for chart patterns")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--refresh-resistance", action="store_true")
    a = ap.parse_args()
    if a.refresh_resistance:
        print("[pattern_scan] resistance refreshed for", refresh_resistance(), "stocks", flush=True)
    elif a.run:
        os.makedirs(DATA_DIR, exist_ok=True)
        _run_scan(a.force, a.workers, [x for x in a.only.split(",") if x] or None)


# ------------------------------------------------------------------ keeping the data current
AUTOSCAN_AFTER_HOURS = 18
_funda_proc = None


def autoscan_loop(poll_seconds: int = 1800) -> None:
    """Background thread of the web server: when the scanned prices are older than AUTOSCAN_AFTER_HOURS, start a rescan
    (it skips stocks already scanned in the last 12 hours), then top up missing Screener fundamentals. The scan itself
    runs in its own processes, so the server stays responsive."""
    import subprocess
    import sys
    time.sleep(120)                                    # let the server finish starting first
    while True:
        try:
            rows = _load_all()
            newest = max((r.get("scanned_at", 0) for r in rows.values()), default=0)
            stale = time.time() - newest > AUTOSCAN_AFTER_HOURS * 3600
            if (stale or not rows) and not status().get("building"):
                build()
            funda = _fundamentals()
            if len(funda) < len(rows) or any(not (funda.get(s) or {}).get("fund_ok", False) for s in rows):
                global _funda_proc
                if not status().get("building") and (_funda_proc is None or _funda_proc.poll() is not None):
                    _funda_proc = subprocess.Popen([sys.executable, "-m", "screens.build_cli"], cwd=ROOT,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except Exception as e:
            print(f"[pattern_scan] autoscan: {e}", flush=True)
        time.sleep(poll_seconds)
