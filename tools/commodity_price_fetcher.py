"""
NICHE-14 pathway (A.5 Pricing Power, 5B leg) - commodity input-cost proxy.

Neither MCX nor LME offers a free, programmatic, HISTORICAL commodity price
feed: MCX's free pages are per-contract futures bhavcopy (not a clean spot
index), and LME's free tier is current-year-only (no historical trend
possible) - full history is a paid product for both. User-approved
substitute, locked in with the approved plan: FRED (St. Louis Fed), which
republishes the IMF's "Global price of <commodity>" primary-commodity price
indices - free, no API key required, clean historical monthly CSV via
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>`.

IMPORTANT - every source/citation field that references this MUST say
"FRED (proxy for MCX/LME - no free historical MCX/LME feed exists)", never
claim it's literally MCX/LME. See `_SOURCE_LABEL` below; every result dict
returned by `fetch_commodity_price_series` carries it under "source".

Design mirrors tools/crisil_scraper.py's convention: session helper w/
Chrome UA fallback, disk cache keyed on the actual query term (the FRED
series ID, not the company symbol - the same series is shared across every
company mapped to that commodity), explicit CHECKED/NOT_FOUND/ERROR result
states, never raises, __main__ smoke-test block.

Series IDs below were fetched and eyeballed live against real-world
commodity price knowledge before being locked in here (see this module's
__main__ block / the implementation report) - none were guessed.
"""

import os
import re
import json
import time
import threading

try:
    from tools import ssl_bootstrap  # noqa: F401  (Windows TLS fix; no-op on cloud)
except Exception:
    pass

try:
    from curl_cffi import requests as _http
    _HAVE_CFFI = True
except Exception:  # pragma: no cover
    import requests as _http
    _HAVE_CFFI = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "commodity_prices")
TTL = 7 * 24 * 3600  # FRED's IMF commodity indices update monthly at most - no need for daily refresh

_SOURCE_LABEL = "FRED (proxy for MCX/LME - no free historical MCX/LME feed exists)"

_lock = threading.Lock()

# Sector name -> {commodity_name, fred_series_id}. Keyed EXACTLY off the 25
# sector strings tools/nse_sector_map.get_nse_sector returns (parsed from
# frontend/src/lib/nseSectorMap.js - the single source of truth). Only
# sectors with an obvious, defensible dominant input commodity are mapped;
# everything else honestly returns None from get_company_commodity rather
# than guessing a commodity or an LLM-fabricated series (per CLAUDE.md:
# unknown/not-quantifiable must never become a guess). Generic across every
# company in a sector - no ticker-specific logic anywhere in this map.
_SECTOR_COMMODITY_MAP = {
    "Metals & Mining": {"commodity_name": "Iron Ore", "fred_series_id": "PIORECRUSDM"},
    "Oil, Gas & Consumable Fuels": {"commodity_name": "Crude Oil (WTI)", "fred_series_id": "POILWTIUSDM"},
    "Chemicals": {"commodity_name": "Crude Oil (WTI)", "fred_series_id": "POILWTIUSDM"},
    # Paints (ASIANPAINT/BERGER etc) sit under NSE's "Consumer Durables"
    # sector bucket alongside non-paint durables - coarse, sector-level
    # mapping only (documented limitation, same as A.4's sector-CAGR proxy);
    # crude-oil-derived resins/solvents are still the dominant input for the
    # paint names that dominate this sector's market cap.
    "Consumer Durables": {"commodity_name": "Crude Oil (WTI)", "fred_series_id": "POILWTIUSDM"},
    "Automobile & Auto Components": {"commodity_name": "Rubber", "fred_series_id": "PRUBBUSDM"},
    "Fast Moving Consumer Goods (FMCG)": {"commodity_name": "Palm Oil", "fred_series_id": "PPOILUSDM"},
    "Textiles": {"commodity_name": "Cotton", "fred_series_id": "PCOTTINDUSDM"},
    "Construction Materials (Cement)": {"commodity_name": "Coal (Australian thermal)", "fred_series_id": "PCOALAUUSDM"},
}


def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key):
    try:
        p = _cache_path(key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= TTL:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _write_cache(key, payload):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def _session():
    if _HAVE_CFFI:
        return _http.Session(impersonate="chrome")
    s = _http.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
    return s


def get_company_commodity(sym, sector, description=None):
    """Static-map lookup by NSE sector only (LLM fallback intentionally not
    built this pass - see the approved plan: a missing mapping should
    honestly flow through to Insufficient Data downstream, which is correct
    behavior either way, not a bug). Returns
    {"commodity_name", "fred_series_id"} or None (never a guess) if the
    sector isn't in `_SECTOR_COMMODITY_MAP` or `sector` itself is falsy.
    Generic across every company - no symbol-specific branching."""
    if not sector:
        return None
    entry = _SECTOR_COMMODITY_MAP.get(sector)
    if not entry:
        return None
    return dict(entry)


def _parse_fred_csv(text, series_id):
    """FRED's CSV is `DATE,<SERIES_ID>` header then `YYYY-MM-DD,<value>` rows;
    missing months are represented as '.' - dropped, never coerced to 0."""
    out = []
    lines = (text or "").strip().splitlines()
    if not lines:
        return out
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        date_s, val_s = parts[0].strip(), parts[1].strip()
        if not date_s or not val_s or val_s == ".":
            continue
        try:
            out.append({"date": date_s, "value": float(val_s)})
        except ValueError:
            continue
    return out


def fetch_commodity_price_series(fred_series_id, start_date=None, end_date=None):
    """Fetch a FRED "Global price of <commodity>" monthly series (no API key
    needed for the CSV endpoint). Disk-cached 7 days, keyed on the series ID
    (not the company symbol - many companies share one series). Never
    raises. `start_date`/`end_date` (YYYY-MM-DD) filter the cached/fetched
    series client-side; FRED's CSV endpoint itself always returns full
    history, which is cheap for these monthly series (a few hundred rows).

    Returns:
      {"status": "OK", "series": [{"date","value"}, ...], "source": "..."}
      {"status": "NOT_FOUND", "reason": "..."}
      {"status": "ERROR", "reason": "..."}
      {"status": "NOT_CHECKED", "reason": "..."} - manual/document-only mode

    Same guard convention as tools.crisil_scraper.fetch_crisil_rationale:
    in tools.manual_mode's document-only manual workflow, this NEVER
    reaches live fred.stlouisfed.org. A.5 (this function's only caller) is
    currently batch_enabled=False - never invoked by
    document_analysis_engine.run_qualitative_analysis's automatic batch at
    all - so this guard is currently unreachable in practice, not a fix for
    an active leak; added anyway so the "never fetch live in manual mode,
    full stop" invariant holds regardless of batch_enabled status or any
    future direct caller, rather than relying on that flag alone.
    """
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        return {"status": "NOT_CHECKED",
                "reason": "Live FRED commodity-price lookup skipped in the document-only manual workflow."}
    if not fred_series_id:
        return {"status": "NOT_FOUND", "reason": "No FRED series ID supplied."}

    cache_key = fred_series_id
    cached = _read_cache(cache_key)
    if cached is not None:
        series = cached.get("series") or []
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_series_id}"
        try:
            s = _session()
            r = s.get(url, timeout=30)
            if r.status_code == 404:
                return {"status": "NOT_FOUND", "reason": f"FRED series {fred_series_id} does not exist (404)."}
            if r.status_code != 200:
                return {"status": "ERROR", "reason": f"FRED returned HTTP {r.status_code} for {fred_series_id}."}
            text = r.text if hasattr(r, "text") else r.content.decode("utf-8", "ignore")
            series = _parse_fred_csv(text, fred_series_id)
            if not series:
                return {"status": "NOT_FOUND", "reason": f"FRED series {fred_series_id} returned no usable rows."}
            with _lock:
                _write_cache(cache_key, {"series": series})
        except Exception as e:
            return {"status": "ERROR", "reason": f"FRED fetch failed for {fred_series_id}: {e}"}

    if start_date:
        series = [p for p in series if p["date"] >= start_date]
    if end_date:
        series = [p for p in series if p["date"] <= end_date]
    if not series:
        return {"status": "NOT_FOUND", "reason": f"No {fred_series_id} data points in the requested date range."}

    return {"status": "OK", "series": series, "source": _SOURCE_LABEL, "fred_series_id": fred_series_id}


if __name__ == "__main__":
    print("=== fetch_commodity_price_series smoke test ===")
    for sid in ["POILWTIUSDM", "PCOPPUSDM", "PPOILUSDM", "PIORECRUSDM", "PRUBBUSDM", "PCOTTINDUSDM", "PCOALAUUSDM"]:
        res = fetch_commodity_price_series(sid)
        if res["status"] == "OK":
            last5 = res["series"][-5:]
            print(f"{sid}: OK, {len(res['series'])} points, last 5 = {last5}")
        else:
            print(f"{sid}: {res['status']} - {res.get('reason')}")

    print("\n=== get_company_commodity smoke test ===")
    from tools.nse_sector_map import get_nse_sector
    for sym in ["TATASTEEL", "JSWSTEEL", "ASIANPAINT", "MRF", "CEAT", "ITC", "HINDUNILVR", "TCS", "HDFCBANK"]:
        sector = get_nse_sector(sym)
        commodity = get_company_commodity(sym, sector)
        print(f"{sym}: sector={sector!r} -> commodity={commodity}")
