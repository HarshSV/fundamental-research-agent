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
FUND_STALE_SECONDS = 20 * 3600   # fundamentals are read from Screener again once they are older than this
WORKERS = 1  # kept low on purpose: four workers got Screener timing out on us, and two with 3,100 companies got HTTP 429 (which also blanks the stock pages)

_lock = threading.Lock()
_FUNDAMENTAL_KEYS = ("eps", "pe", "market_cap_cr", "promoter", "div_yield", "payout", "cover", "debt_equity",
                     "net_profit_cr", "eps_growth", "fund_ok", "fund_at", "fund_src", "fund_full", "nse_filled", "fund_tries")
PARTIAL_RETRY_SECONDS = 30 * 60   # a row built from a headline-only page is read again after this long, not the next day
_state = {"building": False, "done": 0, "total": 0, "started": None, "finished": None, "errors": 0}
_cache: dict | None = None


def _names() -> dict:
    try:
        with open(os.path.join(ROOT, "cache", "nse_company_names.json"), encoding="utf-8") as fh:
            names = json.load(fh)
    except Exception:
        names = {}
    try:
        from tools import bse_universe
        names.update({s: b["name"] for s, b in bse_universe.info().items() if s not in names})
    except Exception:
        pass
    return names


def universe_symbols() -> list[str]:
    from tools.nse_sector_map import all_symbols_by_sector
    syms = {s for ss in all_symbols_by_sector().values() for s in ss}
    try:        # plus the BSE-only companies (tools/bse_universe.py)
        from tools import bse_universe
        syms |= set(bse_universe.info())
    except Exception:
        pass
    return sorted(syms)


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


def _yahoo_fin(sym: str) -> dict | None:
    """Yahoo Finance's trailing P/E and dividend yield in the shape metrics.compute reads, or None."""
    try:
        import yfinance as yf
        from tools.live_chart_yf import _to_symbol
        i = yf.Ticker(_to_symbol(sym)).info or {}
        pe, dy = i.get("trailingPE"), i.get("dividendYield")
        if not isinstance(pe, (int, float)) and not isinstance(dy, (int, float)):
            return None
        return {"info": {"trailingPE": float(pe) if isinstance(pe, (int, float)) and pe > 0 else None,
                         "dividendYield": float(dy) / 100.0 if isinstance(dy, (int, float)) else None,
                         "marketCap": i.get("marketCap")}}
    except Exception:
        return None


def is_partial(row: dict | None) -> bool:
    """A stored row built from a page that gave only headline ratios (P/E, dividend yield): earnings, promoter holding,
    profit and debt are missing although the company reports them. Rows saved before `fund_full` existed are judged by
    those fields."""
    if not row or not row.get("fund_ok"):
        return False
    if row.get("fund_full") is not None:
        return not row["fund_full"]
    return row.get("promoter") is None and row.get("net_profit_cr") is None and row.get("eps") is None


def partial_due(row: dict | None, now: float | None = None) -> bool:
    """A partial row that is old enough to be read again: after 30 minutes, then 1h, 2h, 4h ... up to the normal daily
    refresh, so a page that never parses is not hammered."""
    if not is_partial(row):
        return False
    now = time.time() if now is None else now
    wait = min(FUND_STALE_SECONDS, PARTIAL_RETRY_SECONDS * (2 ** int(row.get("fund_tries") or 0)))
    return now - (row.get("fund_at") or 0) > wait


def _nse_fill(sym: str, m: dict) -> list[str]:
    """Fill what is still missing in `m` from NSE's own company record (Market Lens). Only positive figures are taken:
    that API reports 0 both for a real zero and for "not available", and an unknown must never become a zero."""
    try:
        import requests
        from tools.company_profile import _UA
        r = requests.get(f"https://marketlens.nseindia.com/api/stocks/{sym}", headers=_UA, timeout=20)
        d = (r.json() or {}).get("data") if r.status_code == 200 else None
    except Exception:
        return []
    if not d:
        return []
    from screens.metrics import is_financial
    from tools.nse_sector_map import get_nse_sector
    pos = lambda k: d.get(k) if isinstance(d.get(k), (int, float)) and d.get(k) > 0 else None
    want = {"pe": pos("peRatio"), "promoter": pos("promoterHolding"), "div_yield": pos("divYield"), "net_profit_cr": (pos("netProfit") / 10.0 if pos("netProfit") else None)}   # NSE reports rupees in millions
    if not is_financial(get_nse_sector(sym)):
        want["debt_equity"] = pos("debtToEquity")
    filled = []
    for k, v in want.items():
        if m.get(k) is None and v is not None:
            m[k] = float(v)
            filled.append(k)
    return filled


def _build_one(sym: str, name: str | None, fetch_candles) -> tuple[str, dict | None]:
    try:
        from tools import bse_universe
        bse_universe.prime(sym)            # a BSE-only company is read from Screener by its BSE code and from Yahoo by its trading symbol
        from tools.screener_scraper import fetch_screener_financials, wait_if_down
        from tools import screener_scraper as _sc
        time.sleep(5.0)                    # a read is 3 or more requests and Screener rate-limits us at about one request every 3 seconds
        fin = None
        for attempt in range(8):               # Screener throttles under load: retry before recording "no fundamentals"
            wait_if_down()                     # paused after an HTTP 429: wait it out instead of recording a Yahoo-only row
            fin = fetch_screener_financials(sym, name, fresh=True)
            if fin and fin.get("info"):
                break
            if time.time() >= _sc._DOWN_UNTIL and attempt >= 2:
                break                          # not rate-limited and still nothing: this company really has no usable page
            time.sleep(1.5 * (attempt + 1))
        if not (fin and fin.get("info")):
            # Banks / some companies have no income-statement layout the full parser accepts; their headline ratios
            # (P/E, dividend yield) are still on the page.
            from tools.screener_scraper import fetch_screener_moat_data
            top = fetch_screener_moat_data(sym, name) or {}
            if top.get("pe") is not None or top.get("dividend_yield") is not None:
                dy = top.get("dividend_yield")
                fin = {"info": {"trailingPE": top.get("pe"), "dividendYield": dy / 100.0 if dy is not None else None}}
        src = "screener"
        full = bool(fin and fin.get("info") and (fin.get("financial_arrays") or {}).get("income_stmt"))
        if not (fin and fin.get("info")):
            # Some Screener pages come back without any figures. Yahoo Finance's headline ratios are the last resort, and are
            # marked as such (their earnings basis can differ from Screener's).
            fin = _yahoo_fin(sym)
            src = "yahoo" if fin else src
            full = False
        candles = fetch_candles(sym, "1d", "5y")
        if not fin and not candles:
            return sym, None
        m = metrics.compute(fin, candles)
        m["name"] = name or sym
        m["fund_src"] = src if m.get("fund_ok") else None
        m["fund_full"] = full if m.get("fund_ok") else None
        m["nse_filled"] = _nse_fill(sym, m) if (m.get("fund_ok") and not full) else []
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
            todo = [s for s in syms if force or s not in data or not data[s].get("fund_ok") or now - (data[s].get("fund_at") or 0) > FUND_STALE_SECONDS
                    or partial_due(data[s], now)]
            try:        # BSE-only companies first (their stock pages have no saved Screener read yet), the biggest first
                from tools import bse_universe
                info = bse_universe.info()
                todo.sort(key=lambda s: (0, -(info[s].get("mktcap_cr") or 0)) if s in info else (1, 0))
            except Exception:
                pass
            _state["total"] = len(todo)
            since_save = 0
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for sym, m in ex.map(lambda s: _build_one(s, names.get(s), fetch_candles), todo):
                    _state["done"] += 1
                    if m is None:
                        _state["errors"] += 1
                    else:
                        old = data.get(sym) or {}
                        if not m.get("fund_ok") and old.get("fund_ok"):
                            # Screener failed this time: keep the last good fundamentals rather than blanking them
                            for k in _FUNDAMENTAL_KEYS:
                                m[k] = old.get(k)
                        elif m.get("fund_ok") and not m.get("fund_full") and old.get("fund_full"):
                            # only a headline page came back: keep the earlier complete figures it cannot replace
                            for k in _FUNDAMENTAL_KEYS:
                                if m.get(k) is None and old.get(k) is not None:
                                    m[k] = old.get(k)
                        m["fund_tries"] = (int(old.get("fund_tries") or 0) + 1) if (m.get("fund_ok") and not m.get("fund_full")) else 0
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
