"""Screening universe: build per-company metrics in the background, persist them, evaluate screens.

The universe is the NSE sector-mapped company list (tools/nse_sector_map). Building it fetches each
company's Screener page and daily prices (both cached by their own modules), so it is slow the first time
(minutes) and resumable: results are saved as they arrive and a restart skips companies already done
unless they are older than STALE_SECONDS."""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import metrics
from .definitions import BY_ID, CRITERIA, SCREENS, THRESHOLDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("SCREENS_DATA_DIR", os.path.join(ROOT, "data", "screens"))
PATH = os.path.join(DATA_DIR, "universe.json")
STALE_SECONDS = 24 * 3600
WORKERS = 2  # kept low on purpose: four parallel workers got the Screener site timing out on us

_lock = threading.Lock()
_state = {"building": False, "done": 0, "total": 0, "started": None, "finished": None, "errors": 0}
_cache: dict | None = None


def _names() -> dict:
    try:
        with open(os.path.join(ROOT, "cache", "nse_company_names.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def universe_symbols() -> list[str]:
    from tools.nse_sector_map import all_symbols_by_sector
    return sorted({s for syms in all_symbols_by_sector().values() for s in syms})


_cache_mtime = 0.0


def load() -> dict:
    """The universe, re-read whenever the file changes on disk (a build may run in another process)."""
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = os.path.getmtime(PATH)
        except OSError:
            mtime = 0.0
        if _cache is None or mtime > _cache_mtime:
            try:
                with open(PATH, encoding="utf-8") as fh:
                    _cache = json.load(fh)
                _cache_mtime = mtime
            except Exception:
                _cache = _cache or {}
        return _cache


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, PATH)


def status() -> dict:
    data = load()
    return {**_state, "have": len(data), "universe": len(universe_symbols())}


def _build_one(sym: str, name: str | None, fetch_candles) -> tuple[str, dict | None]:
    try:
        from tools.screener_scraper import fetch_screener_financials
        fin = fetch_screener_financials(sym, name)
        candles = fetch_candles(sym, "1d", "5y")
        if not fin and not candles:
            return sym, None
        m = metrics.compute(fin, candles)
        m["name"] = name or sym
        m["as_of"] = int(time.time())
        return sym, m
    except Exception as e:  # one bad company must never stop the build
        print(f"[screens] {sym}: {type(e).__name__}: {e}")
        return sym, None


def build(fetch_candles, force: bool = False) -> bool:
    """Start a background build. Returns False if one is already running."""
    with _lock:
        if _state["building"]:
            return False
        _state.update(building=True, done=0, errors=0, started=int(time.time()), finished=None)

    def run():
        try:
            data = dict(load())
            names = _names()
            syms = universe_symbols()
            now = time.time()
            todo = [s for s in syms if force or s not in data or now - data[s].get("as_of", 0) > STALE_SECONDS]
            _state["total"] = len(todo)
            since_save = 0
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for sym, m in ex.map(lambda s: _build_one(s, names.get(s), fetch_candles), todo):
                    _state["done"] += 1
                    if m is None:
                        _state["errors"] += 1
                    else:
                        data[sym] = m
                    since_save += 1
                    if since_save >= 20:
                        _save(data)
                        _swap(data)
                        since_save = 0
            _save(data)
            _swap(data)
        finally:
            _state.update(building=False, finished=int(time.time()))

    threading.Thread(target=run, daemon=True, name="screens-build").start()
    return True


def _swap(data: dict) -> None:
    global _cache, _cache_mtime
    with _lock:
        _cache = dict(data)
        try:
            _cache_mtime = os.path.getmtime(PATH)
        except OSError:
            pass


# -- evaluation -------------------------------------------------------------------------------
def _percentile(values: list[float], pct: float) -> float | None:
    vs = sorted(values)
    if not vs:
        return None
    k = (len(vs) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)


def _cut_points(data: dict) -> dict:
    return {
        "avg_volume": _percentile([m["avg_volume"] for m in data.values() if m.get("avg_volume")], THRESHOLDS["volume_pct"]),
        "volatility": _percentile([m["volatility"] for m in data.values() if m.get("volatility")], THRESHOLDS["vol_pct"]),
    }


def _passes(crit_id: str, m: dict, cuts: dict) -> bool:
    _, metric, op, key = CRITERIA[crit_id]
    v = m.get(metric)
    if v is None:  # unknown never matches
        return False
    if op == "<=":
        return v <= THRESHOLDS[key]
    if op == ">=":
        return v >= THRESHOLDS[key]
    if op == "pos<=":
        return 0 < v <= THRESHOLDS[key]
    cut = cuts.get(metric)
    if cut is None:
        return False
    return v >= cut if op == "pct>=" else v <= cut


def evaluate(screen_id: str, data: dict | None = None) -> list[dict]:
    data = load() if data is None else data
    cuts = _cut_points(data)
    crits = BY_ID[screen_id][4]
    out = []
    for sym, m in data.items():
        if all(_passes(c, m, cuts) for c in crits):
            out.append({"symbol": sym, **m})
    metric_keys = [CRITERIA[c][1] for c in crits]
    out.sort(key=lambda r: -(r.get("market_cap_cr") or 0))
    for r in out:
        r["matched"] = {k: r.get(k) for k in metric_keys}
    return out


def counts() -> dict[str, int]:
    data = load()
    cuts = _cut_points(data)
    return {s[0]: sum(1 for m in data.values() if all(_passes(c, m, cuts) for c in s[4])) for s in SCREENS}


def criteria_text(screen_id: str) -> list[str]:
    return [CRITERIA[c][0] for c in BY_ID[screen_id][4]]
