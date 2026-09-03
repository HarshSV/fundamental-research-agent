"""
NSE Insider Trading disclosures (SEBI PIT Regulations, Regulation 7(2)) -
real promoter/director/KMP transaction filings, straight from NSE's own
disclosure feed.

Confirmed-working NSE endpoint:
* https://www.nseindia.com/api/corporates-pit?index=equities&symbol=X&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
  -> list of Regulation 7(2) disclosures for the date window: acquirer name,
  category (Promoter/Director/KMP/Immediate relative), transaction type
  (Buy/Sell), shares transacted, transaction value, holding before/after,
  and a remarks field.

Design mirrors tools/governance_scraper.py: curl_cffi (real-browser TLS
fingerprint), disk cache, never raises.
"""

import os
import json
import time
import threading
import datetime

try:
    from tools import ssl_bootstrap  # noqa: F401
except Exception:
    pass

try:
    from curl_cffi import requests as _http
    _HAVE_CFFI = True
except Exception:  # pragma: no cover
    import requests as _http
    _HAVE_CFFI = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "insider_trading")
TTL = 12 * 3600

_HOME = "https://www.nseindia.com"
_lock = threading.Lock()
_session = None
_session_ts = 0.0


def _get_session():
    global _session, _session_ts
    with _lock:
        if _session is None or (time.time() - _session_ts) > 300:
            _session = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
            if not _HAVE_CFFI:
                _session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
            try:
                _session.get(_HOME, timeout=15)
            except Exception as e:
                print(f"[insider_trading] NSE warmup failed: {e}")
            _session_ts = time.time()
        return _session


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


def fetch_insider_trades(symbol, quarters=8):
    """Real Regulation 7(2) insider-trading disclosures for `symbol` across
    the last `quarters` quarters (~730 days for 8 quarters). Returns a list
    of dicts (NSE's own field names, newest first) - each row real: a named
    acquirer/relative, transaction type (Buy/Sell), date, shares, value,
    holding before/after, and remarks. Empty list on failure/no data. Never
    raises.

    Same guard convention as tools.crisil_scraper.fetch_crisil_rationale:
    in tools.manual_mode's document-only manual workflow, this NEVER
    reaches live nseindia.com. Every qualitative caller (D.1.x/D.2.x/R.2.x)
    already converts a falsy/empty result to None before scoring (e.g.
    `score_selling_frequency(rows if rows else None)`), so returning []
    here - this function's own existing "no data" contract - collapses to
    the same honest SEARCH_INCONCLUSIVE outcome as a real empty fetch,
    never a fabricated "confirmed zero trades" finding."""
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        return []
    sym = (symbol or "").strip().upper().replace(".NS", "")
    ckey = f"pit_{sym}_{quarters}q"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    to_dt = datetime.date.today()
    from_dt = to_dt - datetime.timedelta(days=quarters * 91 + 14)
    from_str = from_dt.strftime("%d-%m-%Y")
    to_str = to_dt.strftime("%d-%m-%Y")

    s = _get_session()
    try:
        url = f"{_HOME}/api/corporates-pit?index=equities&symbol={sym}&from_date={from_str}&to_date={to_str}"
        r = s.get(url, headers={"Referer": f"{_HOME}/get-quotes/equity?symbol={sym}"}, timeout=20)
        data = json.loads(r.text) if r.status_code == 200 else {}
    except Exception as e:
        print(f"[insider_trading] fetch failed for {sym}: {e}")
        data = {}

    rows = (data or {}).get("data") or []
    if rows:
        _write_cache(ckey, rows)
    return rows
