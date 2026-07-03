"""
BSE segment scraper — revenue-by-segment for an Indian company, straight from the
company's own quarterly result filing on BSE ("Segment-wise Revenue, Results,
Total Assets and Total Liabilities").

Flow: resolve NSE symbol/name -> BSE scrip code (name-matched to avoid namesakes)
-> latest "Result" announcement PDF -> parse the Gross-Segment-Revenue table ->
{segments:[{name, revenue_cr, pct}], period, source_url}.

Free (BSE public API + result PDF via pypdf). Disk-cached 7 days. Never raises.
NOTE: BSE blocks datacenter IPs, so this works from a normal/India IP (local) but
needs an outbound proxy on cloud hosts (e.g. Render).
"""

import os
import re
import io
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

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "bse")
TTL = 7 * 24 * 3600
_lock = threading.Lock()

_HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
_SEARCH = "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w?Type=SS&text={q}"
_ANN = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
        "pageno=1&strCat=Result&strPrevDate={frm}&strToDate={to}&strSearch=P&strscrip={code}&strType=C")
_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/{base}/{name}"


def _sess():
    s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
    s.headers.update(_HEADERS)
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


def _norm(s):
    return re.sub(r"\b(ltd|limited|ltd\.)\b", "", (s or "").lower()).replace("&", " ").replace(".", " ")


def _resolve_scrip_code(symbol, name):
    """NSE symbol/name -> BSE scrip code, name-matched so a famous namesake
    (e.g. APOLLO -> Apollo Tyres) doesn't win over the real company."""
    sym_up = (symbol or "").upper()
    ck = f"code_{sym_up}"
    cached = _read_cache(ck)
    if cached is not None:
        return cached.get("code")
    code = None
    try:
        s = _sess()
        target = " ".join(_norm(name or symbol).split())
        # NAME first — BSE symbol search returns famous namesakes (searching "APOLLO"
        # only returns Apollo Tyres); the company NAME search is reliable. BSE search is
        # picky about long names, so also try trimmed variants ("...Limited" removed, and
        # the first two words).
        queries = []
        if name:
            queries.append(name)
            n2 = re.sub(r"\b(limited|ltd\.?)\b", "", name, flags=re.I).strip()
            if n2 and n2 != name:
                queries.append(n2)
            words = n2.split()
            if len(words) > 2:
                queries.append(" ".join(words[:2]))
        queries.append(symbol)
        seen_q = set()
        for q in queries:
            if not q or q.lower() in seen_q:
                continue
            seen_q.add(q.lower())
            r = s.get(_SEARCH.format(q=q), timeout=15)
            if r.status_code != 200:
                continue
            # Each option: liclick('500510','LARSEN  TOUBRO LTD') ... <span>LT&nbsp;&nbsp;ISIN&nbsp;&nbsp;500510</span>
            entries = re.findall(r"liclick\('(\d{6})','([^']*)'\).*?<span>([^<]+)</span>", r.text, re.S)
            if not entries:
                continue
            parsed = []
            for cd, nm, span in entries:
                nse_sym = re.split(r"(?:&nbsp;)+|\s{2,}", span.strip())[0].strip().upper()
                parsed.append((cd, nm, nse_sym))
            # 1) Exact NSE-symbol match — kills namesakes (APOLLO -> Apollo Micro, not Tyres).
            best = next((cd for cd, nm, ns in parsed if ns == sym_up), None)
            # 2) Exact company-name match.
            if not best:
                best = next((cd for cd, nm, ns in parsed if " ".join(_norm(nm).split()) == target), None)
            # 3) Name contains (only when we searched by a name variant — avoids namesakes).
            if not best and q != symbol:
                best = next((cd for cd, nm, ns in parsed
                             if target and (target in " ".join(_norm(nm).split()))), None)
            if best:
                code = best
                break
    except Exception as e:
        print(f"[bse] scrip-code resolve failed for {symbol}: {e}")
    if code:
        _write_cache(ck, {"code": code})
    return code


def _result_attachments(code):
    """Latest 'Result' filing attachment names (newest first)."""
    try:
        s = _sess()
        to = time.strftime("%Y%m%d")
        frm = time.strftime("%Y%m%d", time.localtime(time.time() - 400 * 24 * 3600))
        r = s.get(_ANN.format(code=code, frm=frm, to=to), timeout=25)
        rows = json.loads(r.text).get("Table", []) or []
        return [row.get("ATTACHMENTNAME") for row in rows if row.get("ATTACHMENTNAME")]
    except Exception as e:
        print(f"[bse] announcements fetch failed for {code}: {e}")
        return []


def _parse_segment_pdf(content):
    """Find and parse the Gross-Segment-Revenue table in a result PDF."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        return None
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if not re.search(r"segment[-\s]*wise\s+revenue|segment\s+revenue", text, re.I):
            continue
        # Isolate the revenue block: from "Gross segment revenue"/"Segment Revenue"
        # up to the next sub-table ("Segment Result"/"Segment Assets").
        start = re.search(r"(gross\s+segment\s+revenue|segment\s+revenue|1\s*\)?\s*segment\s+revenue)", text, re.I)
        block = text[start.start():] if start else text
        end = re.search(r"segment\s+result|segment\s+asset|capital\s+employ", block, re.I)
        if end:
            block = block[:end.start()]
        segs = []
        for line in block.splitlines():
            # e.g. "1 Infrastructure Projects 34004.23 32148.62 ..."  (grab name + FIRST number).
            # The leading serial number is sometimes doubled or the first letter dropped by
            # pypdf ("1 1 nfrastructure ..."), so allow one stray digit before the name.
            m = re.match(r"\s*\d+\s*[\).]?\s+(?:\d+\s+)?([A-Za-z][A-Za-z0-9 &/,'\-]+?)\s+([\d,]+\.\d{1,2})", line)
            if not m:
                continue
            nm = re.sub(r"\s+", " ", m.group(1)).strip()
            nm = re.sub(r"[\s\d,]+$", "", nm).strip(" -,&")  # drop trailing mangled numbers
            nm = nm[0].upper() + nm[1:] if nm else nm
            if len(nm) < 3 or re.search(r"total|less|inter[\s-]*segment|unalloc", nm, re.I):
                continue
            val = None
            try:
                val = float(m.group(2).replace(",", ""))
            except Exception:
                continue
            if val and val > 0:
                segs.append({"name": nm, "revenue_cr": round(val)})
        # De-dupe by name, keep first (latest-quarter column).
        seen, uniq = set(), []
        for s in segs:
            k = s["name"].lower()
            if k not in seen:
                seen.add(k)
                uniq.append(s)
        if len(uniq) >= 2:
            total = sum(s["revenue_cr"] for s in uniq)
            if total > 0:
                for s in uniq:
                    s["pct"] = round(s["revenue_cr"] / total * 100, 1)
                return uniq
    return None


def fetch_bse_segments(symbol, name=None):
    """
    Return {'segments': [{name, revenue_cr, pct}], 'source': 'BSE result filing'}
    for the company, or {} when unavailable (single-segment company, image-only PDF,
    or BSE unreachable). Cached 7 days. Never raises.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    ck = f"seg_{sym}"
    cached = _read_cache(ck)
    if cached is not None:
        return cached
    result = {}
    with _lock:
        cached = _read_cache(ck)
        if cached is not None:
            return cached
        try:
            code = _resolve_scrip_code(sym, name)
            if not code:
                return {}
            s = _sess()
            for att in _result_attachments(code)[:4]:
                for base in ("AttachHis", "AttachLive"):
                    try:
                        r = s.get(_ATTACH.format(base=base, name=att), timeout=40)
                        if r.content[:4] != b"%PDF":
                            continue
                        segs = _parse_segment_pdf(r.content)
                        if segs:
                            result = {
                                "segments": segs,
                                "source": "BSE quarterly result filing",
                                "bse_code": code,
                            }
                            raise StopIteration
                    except StopIteration:
                        raise
                    except Exception:
                        continue
        except StopIteration:
            pass
        except Exception as e:
            print(f"[bse] segment fetch failed for {sym}: {e}")
        _write_cache(ck, result)  # cache negatives too (avoids re-hitting BSE every run)
    return result


if __name__ == "__main__":
    import sys
    out = fetch_bse_segments(sys.argv[1] if len(sys.argv) > 1 else "LT",
                             sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(out, indent=2, ensure_ascii=False))
