"""Yahoo Finance sector and industry for every scanned company: a second source for "peers" when Screener cannot give them.

Screener rate-limits this machine, and a BSE-only company has no NSE sector, so its Peer Comparison stayed empty until Screener's industry
classification (screens/quarterly.py) reached it. Yahoo gives a sector and industry for about 90% of BSE-only companies and for NSE ones.
The collector reads them one company about every second (Yahoo's `info`), resumable, and saves data/screens/yahoo_industry.json:
{symbol: {"sector", "industry", "at"}}; a company Yahoo has nothing for is stored with None (read again after a week) and never guessed.

    python -m tools.yahoo_industry            # companies not read in the last 30 days, BSE-only first
    python -m tools.yahoo_industry --force    # everything
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "screens", "yahoo_industry.json")
FRESH_SECONDS = 30 * 86400          # a read that found an industry
RETRY_SECONDS = 7 * 86400           # a read that found nothing
PAUSE = 0.5
WORKERS = 3

_mem: dict = {"mt": None, "data": {}}


def load() -> dict:
    try:
        mt = os.path.getmtime(PATH)
    except OSError:
        return {}
    if _mem["mt"] != mt:
        try:
            with open(PATH, encoding="utf-8") as fh:
                _mem.update(mt=mt, data=json.load(fh))
        except Exception:
            pass
    return _mem["data"]


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, PATH)


def due(rec: dict | None, now: float) -> bool:
    if not rec or "fund" not in rec or "similar" not in rec or "roce" not in rec:     # older records (before these existed) are read again
        return True
    age = now - rec.get("at", 0)
    return age > (FRESH_SECONDS if rec.get("industry") else RETRY_SECONDS)


def _roce(t) -> float | None:
    """ROCE % = EBIT / capital employed (total assets less current liabilities), both from the latest annual statements Yahoo has. None
    when either figure is missing or capital employed is not positive (never zero, never a guess). Screener's own ROCE is used instead
    wherever that company has been read from Screener."""
    try:
        isnum = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v == v
        inc, bs = t.income_stmt, t.balance_sheet
        if inc is None or bs is None or inc.empty or bs.empty:
            return None
        ebit = None
        for row in ("EBIT", "Operating Income"):
            if row in inc.index and isnum(inc.at[row, inc.columns[0]]):
                ebit = float(inc.at[row, inc.columns[0]])
                break
        col = bs.columns[0]
        ta = bs.at["Total Assets", col] if "Total Assets" in bs.index else None
        cl = bs.at["Current Liabilities", col] if "Current Liabilities" in bs.index else None
        if ebit is None or not isnum(ta) or not isnum(cl) or ta - cl <= 0:
            return None
        return round(ebit / float(ta - cl) * 100.0, 2)
    except Exception:
        return None


def _similar(ticker: str) -> list | None:
    """Yahoo's "similar stocks" list for a ticker (up to 5, as base symbols without .NS / .BO), [] when it has none, None when the call
    failed (so it is tried again). An independent signal from the industry label."""
    try:
        import requests
        r = requests.get(f"https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{ticker}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            return None
        res = (r.json().get("finance") or {}).get("result") or []
        syms = ((res[0] if res else {}).get("recommendedSymbols") or [])
        return [s["symbol"].rsplit(".", 1)[0].upper() for s in syms if s.get("symbol")]
    except Exception:
        return None


def fetch_one(sym: str, old: dict | None = None) -> dict:
    """{"sector", "industry", "fund", "similar", "at"}; None / empty when Yahoo has nothing (or could not be reached). A fresh earlier
    read of the sector, industry and figures is reused; only what is missing is asked for again."""
    reuse = bool(old and "fund" in old and time.time() - old.get("at", 0) < FRESH_SECONDS and (old.get("industry") or old.get("fund")))
    out = {"sector": old.get("sector"), "industry": old.get("industry"), "at": old.get("at"), "fund": old.get("fund") or {}} if reuse \
        else {"sector": None, "industry": None, "at": time.time(), "fund": {}}
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import yfinance as yf
        from tools import bse_universe
        from tools.live_chart_yf import _to_symbol
        bse_universe.prime(sym)                       # a BSE-only company is priced by `<trading symbol>.BO`
        ticker = _to_symbol(sym)
        if not reuse:
            info = yf.Ticker(ticker).info or {}
            out["sector"] = info.get("sector") or None
            out["industry"] = info.get("industry") or None
            out["fund"] = _fund(info)
        sim = old.get("similar") if (old and "similar" in old) else _similar(ticker)
        if sim is not None:
            out["similar"] = sim
        if old and "roce" in old:
            out["roce"] = old["roce"]
        else:
            out["roce"] = _roce(yf.Ticker(ticker))          # None when Yahoo has no statements (recorded, so it is not asked for again soon)
    except Exception:
        pass
    return out


def _fund(info: dict) -> dict:
    """The headline figures the screener filters use, from the same Yahoo read. Yahoo reports 0 both for a real zero and for "not
    available", so a zero P/E, yield, debt or holding is unknown here (None), never shown or filtered on as zero. EPS may be negative."""
    isnum = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v == v
    pos = lambda k: float(info[k]) if isnum(info.get(k)) and info[k] > 0 else None
    eps = float(info["trailingEps"]) if isnum(info.get("trailingEps")) and info["trailingEps"] != 0 else None
    de = pos("debtToEquity")
    ins = pos("heldPercentInsiders")
    mc = pos("marketCap")
    return {"pe": pos("trailingPE"), "eps": eps, "debt_equity": round(de / 100.0, 2) if de is not None else None,   # Yahoo gives per cent
            "promoter": round(ins * 100.0, 2) if ins is not None else None,                                       # Yahoo's "insiders" are the promoters
            "div_yield": pos("dividendYield"), "market_cap_cr": round(mc / 1e7, 2) if mc else None}


def symbols() -> list[str]:
    """Every scanned company (the ones that can be peers), BSE-only first."""
    from tools import bse_universe
    d = os.path.join(ROOT, "data", "pattern_scan", "symbols")
    have = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    bse = bse_universe.info()
    return [s for s in have if s in bse] + [s for s in have if s not in bse]


def build(force: bool = False) -> None:
    data = dict(load())
    now = time.time()
    todo = [s for s in symbols() if force or due(data.get(s), now)]
    print(f"[yahoo_industry] {len(todo)} to read", flush=True)
    from concurrent.futures import ThreadPoolExecutor

    def one(s):
        r = fetch_one(s, data.get(s))
        time.sleep(PAUSE)
        return s, r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:           # Yahoo answers `info` slowly (several seconds): a few readers in parallel
        for n, (s, r) in enumerate(ex.map(one, todo), 1):
            data[s] = r
            if n % 25 == 0 or n == len(todo):
                _save(data)
                print(f"[yahoo_industry] {n}/{len(todo)} (with industry: {sum(1 for v in data.values() if v.get('industry'))})", flush=True)
    _save(data)


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    build(force="--force" in sys.argv)
    print("[yahoo_industry] done", flush=True)
