"""
NSE Corporate Filings & Announcements — real earnings-call transcripts and
investor presentations, sourced directly from
https://www.nseindia.com/companies-listing/corporate-filings-announcements
(the exchange's own `corporate-announcements` API, not a third-party mirror).

Used by B.4.2 (Clarity in guidance) / B.4.3 (Openness in investor
communication) per the spec's sourcing path: NSE -> corporate filings ->
search company/symbol -> Investor Presentation / Earnings Call Transcript ->
Outlook & Guidance.

Design mirrors tools/nse_xbrl.py: curl_cffi (real-browser TLS fingerprint,
no cookie handshake needed for this API in practice), disk cache, never
raises.
"""

import os
import re
import io
import json
import time

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

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "nse_announcements")
TTL = 6 * 3600

_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}"

_TRANSCRIPT_TEXT = re.compile(r"transcript.{0,40}earnings|earnings.{0,40}call.{0,20}transcript", re.I)
_PRESENTATION_TEXT = re.compile(r"investor presentation", re.I)


def _session():
    s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
    s.headers.update({"Referer": "https://www.nseindia.com/",
                      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
    proxy = os.getenv("NSE_PROXY_URL", "").strip()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


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


def fetch_announcements(symbol):
    """Raw corporate-announcements list for a symbol, newest first. Never raises."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    ckey = f"ann_{sym}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    rows = []
    try:
        r = _session().get(_ANNOUNCEMENTS_API.format(sym=sym), timeout=30)
        if r.status_code == 200:
            rows = json.loads(r.text) or []
    except Exception as e:
        print(f"[nse_announcements] fetch failed for {sym}: {e}")
        rows = []
    _write_cache(ckey, rows)
    return rows


def fetch_transcript_url(symbol, name=None):
    """Latest earnings-call transcript PDF URL filed with NSE (newest
    'Transcript of the Earnings...Call' announcement). None if not found."""
    for row in fetch_announcements(symbol):
        text = f"{row.get('attchmntText') or ''} {row.get('desc') or ''}"
        if _TRANSCRIPT_TEXT.search(text):
            url = (row.get("attchmntFile") or "").strip()
            if url:
                return url
    return None


def fetch_investor_presentation_url(symbol, name=None):
    """Latest Investor Presentation PDF URL filed with NSE. None if not found."""
    for row in fetch_announcements(symbol):
        text = f"{row.get('attchmntText') or ''} {row.get('desc') or ''}"
        if _PRESENTATION_TEXT.search(text):
            url = (row.get("attchmntFile") or "").strip()
            if url:
                return url
    return None


_LIGATURE_MAP = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})


def download_pdf_text(url, max_chars=40000, max_pages=30):
    """Download an NSE-hosted announcement attachment and extract its
    text. Handles both a direct PDF and NSE's .zip wrapper used for many
    older filings (confirmed real: SUZLON's 2014 preferential-issue
    lock-in disclosure is only available as a .zip - a plain PdfReader
    call on zip bytes fails silently and this function used to just
    return '' for every zip-wrapped attachment, a real, systemic gap
    affecting every older announcement filed this way, not just one
    company). Pulls the first .pdf member out of the zip when present.
    Cached per-URL. Returns '' on any failure. Never raises."""
    if not url:
        return ""
    import hashlib
    ckey = "pdf_" + hashlib.md5(url.encode("utf-8")).hexdigest() + f"_{max_chars}_{max_pages}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached.get("text", "")
    text = ""
    try:
        from pypdf import PdfReader
        s = _session()
        r = s.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) >= 5000:
            content = r.content
            if content[:2] == b"PK" or url.lower().endswith(".zip"):
                import zipfile
                content = None
                try:
                    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                        for nm in zf.namelist():
                            if nm.lower().endswith(".pdf"):
                                content = zf.read(nm)
                                break
                except Exception as e:
                    print(f"[nse_announcements] zip extract failed ({url}): {e}")
            if content:
                reader = PdfReader(io.BytesIO(content))
                parts = []
                for page in reader.pages[:max_pages]:
                    try:
                        parts.append((page.extract_text() or "").translate(_LIGATURE_MAP))
                    except Exception:
                        continue
                    if sum(len(p) for p in parts) > max_chars:
                        break
                text = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()[:max_chars]
                if len(text) > 800:
                    _write_cache(ckey, {"text": text})
    except Exception as e:
        print(f"[nse_announcements] transcript download failed ({url}): {e}")
    return text if len(text) > 800 else ""
