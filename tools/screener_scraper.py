"""
Screener.in shareholding + concall source.

Free, public, and covers essentially every NSE/BSE-listed company with ~12 quarters
of promoter / FII / DII / Government / Public holding — which fixes the "Awaiting NSE
Filing / N/A" gaps and powers the real multi-quarter ownership / FII-DII / promoter
trend charts. Also surfaces the latest concall transcript links for the AI summary.

Design: curl_cffi (real-browser TLS), disk cache (12h), never raises.
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

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "screener")
TTL = 12 * 3600

_lock = threading.Lock()


def _num(s):
    try:
        v = float(str(s).replace(",", "").replace("%", "").replace("&nbsp;", "").strip())
        return v
    except Exception:
        return None


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


def _get(url):
    try:
        if _HAVE_CFFI:
            s = _http.Session(impersonate="chrome")
        else:
            s = _http.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
        r = s.get(url, timeout=25)
        if r.status_code == 200 and len(r.text) > 2000:
            return r.text
    except Exception as e:
        print(f"[screener] GET failed ({url}): {e}")
    return None


def _parse_shareholding(html):
    """Parse the quarterly shareholding-pattern table into series by holder class."""
    msec = re.search(r'id=["\']shareholding["\'].*?</section>', html, re.S)
    if not msec:
        return None
    sec = msec.group(0)
    mq = re.search(r'id=["\']quarterly-shp["\'].*?</table>', sec, re.S)
    block = mq.group(0) if mq else sec
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S)
    if not rows:
        return None

    quarters = []
    series = {"promoter": [], "fii": [], "dii": [], "government": [], "public": [], "others": []}
    num_holders = []
    label_map = [("promoter", "promoter"), ("fii", "fii"), ("dii", "dii"),
                 ("government", "government"), ("public", "public"), ("other", "others")]

    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        clean = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", "").replace("+", "").strip() for c in cells]
        clean = [c for c in clean if c != ""]
        if not clean:
            continue
        # Header row = the 12 quarter labels
        if re.match(r"^[A-Za-z]{3}\s+\d{4}$", clean[0]):
            quarters = clean[:]
            continue
        label = clean[0].lower()
        vals = [_num(c) for c in clean[1:]]
        if "shareholder" in label:
            num_holders = vals
            continue
        for key, dst in label_map:
            if key in label:
                series[dst] = vals
                break

    if not quarters or not series["promoter"]:
        return None

    n = len(quarters)
    def at(arr, i):
        return arr[i] if (arr and i < len(arr) and arr[i] is not None) else None
    latest_i = n - 1

    return {
        "status": "ok",
        "source": "Screener",
        "quarters": quarters,
        "as_of_quarter": quarters[latest_i],
        "promoter": series["promoter"],
        "fii": series["fii"],
        "dii": series["dii"],
        "government": series["government"],
        "public": series["public"],
        "num_shareholders": num_holders,
        "latest": {
            "promoter": at(series["promoter"], latest_i),
            "fii": at(series["fii"], latest_i),
            "dii": at(series["dii"], latest_i),
            "government": at(series["government"], latest_i),
            "public": at(series["public"], latest_i),
        },
        "prev": {
            "promoter": at(series["promoter"], latest_i - 1),
            "fii": at(series["fii"], latest_i - 1),
            "dii": at(series["dii"], latest_i - 1),
            "public": at(series["public"], latest_i - 1),
        },
    }


def _parse_concall_links(html):
    """Latest concall transcript links, newest-first (from Screener's Concalls list)."""
    links = []
    # Screener's Concalls section lists each call newest-first with a "Transcript"
    # anchor (usually a BSE AnnPdfOpen link that serves the PDF).
    msec = re.search(r"Concalls</h3>.*?</ul>", html, re.S)
    area = msec.group(0) if msec else html
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*[^<]*Transcript[^<]*</a>', area, re.I):
        u = m.group(1)
        if u not in links:
            links.append(u)
    if not links:  # fallback: any transcript-ish PDF anywhere on the page
        for m in re.finditer(r'href=["\']([^"\']+\.pdf)["\']', html, re.I):
            u = m.group(1)
            if re.search(r"transcri|concall|earnings", u, re.I) and u not in links:
                links.append(u)
    return links[:5]


def _parse_concall_list(html):
    """Per-month concall entries (newest first): [{date, url}]. url is the
    transcript PDF link for that month (None if Screener has no transcript yet)."""
    out = []
    msec = re.search(r"Concalls</h3>.*?</ul>", html, re.S)
    if not msec:
        return out
    seen = {}
    for li in re.findall(r"<li[^>]*>(.*?)</li>", msec.group(0), re.S):
        d = re.search(r"([A-Z][a-z]{2}\s+\d{4})", li)
        if not d:
            continue
        date = d.group(1)
        tr = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*[^<]*Transcript[^<]*</a>', li, re.I)
        url = tr.group(1) if tr else None
        # Dedup by month; keep the entry that actually has a transcript link.
        if date not in seen:
            seen[date] = {"date": date, "url": url}
            out.append(seen[date])
        elif url and not seen[date]["url"]:
            seen[date]["url"] = url
    return out[:8]


def download_transcript(url, max_chars=14000):
    """Download a single transcript PDF (BSE/company link) and extract its text.
    Cached per-URL. Returns '' on any failure. Never raises."""
    if not url:
        return ""
    import hashlib
    ckey = "tr_" + hashlib.md5(url.encode("utf-8")).hexdigest()
    cached = _read_cache(ckey)
    if cached is not None:
        return cached.get("text", "")
    text = ""
    try:
        from pypdf import PdfReader
        import io as _io
        s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
        r = s.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) >= 5000:
            reader = PdfReader(_io.BytesIO(r.content))
            parts = []
            for page in reader.pages[:16]:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
                if sum(len(p) for p in parts) > max_chars:
                    break
            text = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()[:max_chars]
            if len(text) > 800:
                _write_cache(ckey, {"text": text})
    except Exception as e:
        print(f"[screener] transcript download failed ({url}): {e}")
    return text if len(text) > 800 else ""


def fetch_concall_list(symbol, name=None):
    """Public: per-month concall entries for the UI tabs (newest first)."""
    sym = symbol.strip().upper().replace(".NS", "")
    try:
        return (fetch_screener(sym, name) or {}).get("concall_list") or []
    except Exception:
        return []


# Known renames/demergers where the NSE symbol no longer matches Screener's slug.
_SYMBOL_MAP = {"TATAMOTORS": "TMCV", "M&M": "M_M", "BAJAJ-AUTO": "BAJAJ_AUTO"}


def _search_slug(query):
    """Hit Screener's search API (tiny JSON) and return the first company's slug."""
    if not query:
        return None
    try:
        import urllib.parse
        s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
        r = s.get(f"https://www.screener.in/api/company/search/?q={urllib.parse.quote(query)}", timeout=15)
        if r.status_code == 200:
            data = json.loads(r.text)
            if data and isinstance(data, list):
                m = re.search(r"/company/([^/]+)/", data[0].get("url", ""))
                if m:
                    return m.group(1)
    except Exception as e:
        print(f"[screener] search failed for {query!r}: {e}")
    return None


def _resolve_slug(sym, name=None):
    """Screener slug can differ from the NSE symbol (renames/demergers, e.g.
    TATAMOTORS -> TMCV; small caps indexed by BSE code). Resolve via a known map,
    then symbol search, then company-name search."""
    if sym in _SYMBOL_MAP:
        return _SYMBOL_MAP[sym]
    for q in (sym, name):
        slug = _search_slug(q)
        if slug:
            return slug
    return None


def fetch_screener(symbol, name=None):
    """
    Public entry point. Returns {shareholding: {...}, concall_links: [...]} or a
    safe empty payload. Never raises. `name` (company long name) helps resolve
    renamed/demerged tickers whose NSE symbol no longer matches Screener's slug.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    cached = _read_cache(sym)
    if cached is not None:
        return cached

    with _lock:
        cached = _read_cache(sym)
        if cached is not None:
            return cached
        html = None
        for suffix in ("consolidated/", ""):
            html = _get(f"https://www.screener.in/company/{sym}/{suffix}")
            if html:
                break
        if html is None:
            # Slug differs from the NSE symbol (rename/demerger) -> resolve via search.
            slug = _resolve_slug(sym, name)
            if slug and slug.upper() != sym:
                for suffix in ("consolidated/", ""):
                    html = _get(f"https://www.screener.in/company/{slug}/{suffix}")
                    if html:
                        print(f"[screener] resolved {sym} -> slug {slug}.")
                        break
        result = {"shareholding": None, "concall_links": []}
        if html:
            try:
                result["shareholding"] = _parse_shareholding(html)
            except Exception as e:
                print(f"[screener] shareholding parse error for {sym}: {e}")
            try:
                result["concall_links"] = _parse_concall_links(html)
                result["concall_list"] = _parse_concall_list(html)
            except Exception as e:
                print(f"[screener] concall parse error for {sym}: {e}")
        if result["shareholding"]:
            _write_cache(sym, result)
        return result


def fetch_concall_text(symbol, max_chars=14000, name=None):
    """
    Download the latest concall / earnings-call transcript PDF (from Screener's
    document links) and extract its text, so the AI summary is grounded in the
    ACTUAL transcript rather than inferred. Cached per symbol. Returns
    {"text": str, "url": str} or {"text": "", "url": None}. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"concall_{sym}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    out = {"text": "", "url": None}
    try:
        links = (fetch_screener(sym, name) or {}).get("concall_links") or []
        if not links:
            return out
        try:
            from pypdf import PdfReader
        except Exception as e:
            print(f"[screener] pypdf unavailable: {e}")
            return out
        import io as _io
        if _HAVE_CFFI:
            s = _http.Session(impersonate="chrome")
        else:
            s = _http.Session()
        for url in links[:3]:
            try:
                r = s.get(url, timeout=30)
                if r.status_code != 200 or len(r.content) < 5000:
                    continue
                reader = PdfReader(_io.BytesIO(r.content))
                parts = []
                for page in reader.pages[:16]:
                    try:
                        parts.append(page.extract_text() or "")
                    except Exception:
                        continue
                    if sum(len(p) for p in parts) > max_chars:
                        break
                text = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()
                if len(text) > 800:
                    out = {"text": text[:max_chars], "url": url}
                    _write_cache(ckey, out)
                    print(f"[screener] concall transcript fetched for {sym} ({len(out['text'])} chars).")
                    break
            except Exception as e:
                print(f"[screener] transcript download failed ({url}): {e}")
                continue
    except Exception as e:
        print(f"[screener] concall fetch error for {sym}: {e}")
    return out


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "ONGC"
    print(json.dumps(fetch_screener(arg), indent=2)[:1200])
    print("--- concall ---")
    c = fetch_concall_text(arg)
    print("url:", c["url"], "| chars:", len(c["text"]))
    print(c["text"][:500])
