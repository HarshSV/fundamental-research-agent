"""
NSE Corporate Governance quarterly filing (SEBI LODR Reg. 27) — real board
composition, committee composition, and meeting-attendance data, straight
from the company's own quarterly Corporate Governance Report filing.

Confirmed-working NSE endpoints:
* https://www.nseindia.com/api/corporate-governance-master?index=equities&symbol=X
  -> list of quarterly filings (recordId, date) for a symbol, newest-first.
* https://www.nseindia.com/api/corporate-governance?index=equities&symbol=X&recId=N
  -> the full quarterly filing detail: cobod (board composition), coc
  (committee composition), bodmeeting (board meeting attendance),
  meetingcomm (committee meeting attendance), and more.

Design mirrors tools/shareholding_scraper.py: curl_cffi (real-browser TLS
fingerprint), disk cache, never raises.
"""

import os
import json
import time
import threading

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

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "governance")
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
                print(f"[governance] NSE warmup failed: {e}")
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


def fetch_latest_governance_filing(symbol):
    """Real quarterly Corporate Governance Report detail for the most
    recent filed quarter - board composition, committee composition,
    board/committee meeting attendance. Returns a dict with keys
    'cobod','coc','bodmeeting','meetingcomm' (each NSE's raw structure)
    plus 'as_of_quarter', or {} on failure/no data. Never raises."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    ckey = f"cg_{sym}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    s = _get_session()
    try:
        master_url = f"{_HOME}/api/corporate-governance-master?index=equities&symbol={sym}"
        r = s.get(master_url, headers={"Referer": f"{_HOME}/get-quotes/equity?symbol={sym}"}, timeout=20)
        master = json.loads(r.text) if r.status_code == 200 else {}
    except Exception as e:
        print(f"[governance] master fetch failed for {sym}: {e}")
        master = {}

    rows = (master or {}).get("data") or []
    if not rows:
        return {}
    latest = rows[0]
    rec_id = latest.get("recordId")
    as_of_quarter = latest.get("date")
    if not rec_id:
        return {}

    try:
        detail_url = f"{_HOME}/api/corporate-governance?index=equities&symbol={sym}&recId={rec_id}"
        r = s.get(detail_url, headers={"Referer": f"{_HOME}/get-quotes/equity?symbol={sym}"}, timeout=20)
        detail = json.loads(r.text) if r.status_code == 200 else {}
    except Exception as e:
        print(f"[governance] detail fetch failed for {sym} recId={rec_id}: {e}")
        detail = {}

    if not detail:
        return {}

    def _first_data(key):
        rows = detail.get(key) or []
        return rows[0].get("data") if rows and isinstance(rows[0], dict) else None

    cobod_raw = _first_data("cobod") or {}
    out = {
        "as_of_quarter": as_of_quarter,
        "cobod": (cobod_raw.get("CompositionBOD") if isinstance(cobod_raw, dict) else cobod_raw) or [],
        "coc": _first_data("coc") or {},
        "bodmeeting": _first_data("bodmeeting") or [],
        "meetingcomm": _first_data("meetingcomm") or [],
    }
    if out["cobod"] or out["coc"]:
        _write_cache(ckey, out)
    return out
