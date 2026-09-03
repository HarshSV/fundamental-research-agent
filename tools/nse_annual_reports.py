"""
NSE annual-report source - the fallback for companies BSE doesn't list.

Our whole fundamentals pipeline was originally BSE-only (bse_scraper's
scrip-code resolution + BSE's AnnualReport_New API). But a large chunk of
NSE-listed companies (esp. smaller/SME names like AAKASH - Aakash
Exploration Services) simply aren't on BSE at all, so BSE resolution
returns nothing and EVERY ratio comes back N/A even though the company's
Annual Report is freely available on NSE (this is the same source Screener
uses - visible as "from nse" on its Documents tab).

NSE exposes annual reports at:
  https://www.nseindia.com/api/annual-reports?index=equities&symbol=<SYM>
returning a `data` list of {fromYr, toYr, fileName} - fileName is the
direct PDF (or, for older years, a .zip wrapping the PDF) on
nsearchives.nseindia.com. Fiscal year is `toYr` (a 2024-2025 report is
FY2025, matching our BSE convention where "Year" is the year the FY ends).

NSE's API requires a homepage cookie hit first and blocks datacenter IPs -
same constraint already documented for tools/nse_xbrl.py; works from a
normal/India IP locally, needs NSE_PROXY_URL on a cloud host. Never raises.
"""

import os
import io
import json
import time
import zipfile

try:
    from tools import ssl_bootstrap  # noqa: F401 - Windows TLS fix
except Exception:
    pass

try:
    from curl_cffi import requests as _http
    _HAVE_CFFI = True
except Exception:
    import requests as _http
    _HAVE_CFFI = False

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "nse_ar")
_TTL = 90 * 24 * 3600

_session = None
_session_primed_at = 0.0


def _sess():
    """A cookie-primed NSE session (reused; re-primed every ~10 min). NSE
    403s any request that arrives without the cookies its homepage sets."""
    global _session, _session_primed_at
    now = time.time()
    if _session is None or (now - _session_primed_at) > 600:
        s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/",
        })
        proxy = os.getenv("NSE_PROXY_URL", "").strip()
        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        try:
            s.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass
        _session, _session_primed_at = s, now
    return _session


def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(_CACHE_DIR, f"{safe}.json")


def _read_cache(key):
    try:
        p = _cache_path(key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= _TTL:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _write_cache(key, payload):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def nse_annual_reports(symbol):
    """Returns {year(int): pdf_or_zip_url} for the given NSE symbol, newest
    first is NOT guaranteed by the dict but the caller sorts. Empty dict if
    NSE has nothing (or the symbol isn't NSE-listed). Cached 90 days."""
    sym = symbol.strip().upper().replace(".NS", "")
    ck = f"nse_ar_{sym}"
    cached = _read_cache(ck)
    if cached is not None:
        return {int(k): v for k, v in cached.items()}
    out = {}
    try:
        r = _sess().get(
            f"https://www.nseindia.com/api/annual-reports?index=equities&symbol={sym}",
            timeout=20,
        )
        data = json.loads(r.text).get("data", []) or []
        for row in data:
            to_yr = row.get("toYr")
            fn = row.get("fileName") or ""
            if to_yr and str(to_yr).isdigit() and fn.startswith("http"):
                yr = int(to_yr)
                # Prefer a real PDF over a .zip when the same year appears twice.
                if yr not in out or (out[yr].endswith(".zip") and not fn.endswith(".zip")):
                    out[yr] = fn
    except Exception as e:
        print(f"[nse_annual_reports] lookup failed for {sym}: {e}")
    if out:
        _write_cache(ck, {str(k): v for k, v in out.items()})
    return out


def nse_annual_report_years(symbol):
    """Fiscal years (ints, newest first) NSE has an Annual Report for."""
    return sorted(nse_annual_reports(symbol).keys(), reverse=True)


def nse_annual_report_pdf_url(symbol, year):
    """The NSE Annual Report URL for one fiscal year, or None."""
    return nse_annual_reports(symbol).get(int(year))


def download_nse_pdf_bytes(url):
    """Download a NSE Annual Report. Handles both a direct PDF and the .zip
    wrapper NSE uses for some older years (returns the first PDF inside the
    zip). Returns raw PDF bytes, or None on failure."""
    try:
        content = _sess().get(url, timeout=90, headers={"Referer": "https://www.nseindia.com/"}).content
    except Exception as e:
        print(f"[nse_annual_reports] download failed for {url}: {e}")
        return None
    if not content:
        return None
    # Direct PDF.
    if content[:5] == b"%PDF-" or url.lower().endswith(".pdf"):
        if content[:5] == b"%PDF-":
            return content
    # Zip-wrapped (older NSE filings): pull the first .pdf member out.
    if content[:2] == b"PK" or url.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for nm in zf.namelist():
                    if nm.lower().endswith(".pdf"):
                        return zf.read(nm)
        except Exception as e:
            print(f"[nse_annual_reports] zip extract failed for {url}: {e}")
            return None
    return content if content[:5] == b"%PDF-" else None
