"""
CRISIL Ratings rationale source (PORTAL-07 in the Document Pathway Reference).

Public, free, no login: crisilratings.com exposes a JSON "rating result
listing" search behind its Credit Ratings List page, and rationale documents
are plain static HTML pages under /mnt/winshare/Ratings/RatingList/RatingDocs/.
Both were confirmed live (network-request capture + direct GET) before this
was written - this is not a guessed integration.

Design: curl_cffi (real-browser TLS, same as tools/screener_scraper.py),
disk cache (24h - rating rationales change on rating actions, not
intraday), never raises. Returns an explicit NOT_FOUND / ACCESS_RESTRICTED
result rather than None on failure, per the DON'T/DO INSTEAD hallucination
guardrails (zero-result != clean).
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

from bs4 import BeautifulSoup

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "crisil")
TTL = 24 * 3600

SEARCH_URL = (
    "https://www.crisilratings.com/content/crisilratings/en/home/our-business/ratings/"
    "credit-ratings-list/_jcr_content/wrapper_100_par/columncontrol_copy/container-100-1/"
    "ratingresultlisting.results.json"
)
DOC_BASE = "https://www.crisilratings.com"

_lock = threading.Lock()


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


def _norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\b(ltd|limited|ltd\.|pvt|private)\b", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _search_company(session, company_name):
    """Query CRISIL's rating-result-listing search for a company name. Returns
    the raw doc list (each a rated-instrument row) for the best-matching
    company, or None if nothing usable came back."""
    try:
        filters = json.dumps({"company_name": company_name})
        r = session.get(
            SEARCH_URL,
            params={"cmd": "CR", "start": 0, "limit": 25, "filters": filters},
            timeout=20,
        )
        if r.status_code != 200 or not r.text:
            return None
        outer = r.json()
        docs_raw = outer.get("docs")
        if not docs_raw:
            return None
        # `docs` is itself a JSON string keyed by companyCode -> [instrument rows].
        docs = json.loads(docs_raw) if isinstance(docs_raw, str) else docs_raw
        if not docs:
            return None

        target_norm = _norm_name(company_name)
        best_rows, best_score = None, -1
        for _code, rows in docs.items():
            if not rows:
                continue
            row_name = rows[0].get("companyName", "")
            score = 2 if _norm_name(row_name) == target_norm else (
                1 if target_norm and target_norm in _norm_name(row_name) else 0
            )
            if score > best_score:
                best_score, best_rows = score, rows
        return best_rows
    except Exception as e:
        print(f"[crisil_scraper] search failed for {company_name!r}: {e}")
        return None


def _latest_rationale_doc(rows):
    """Among a company's rated-instrument rows, pick the most recently dated
    rationale document (filenames embed the rationale date)."""
    def _doc_date(row):
        fname = row.get("prDocument") or ""
        m = re.search(r"_([A-Za-z]+ \d{1,2}[,_ ]+ ?\d{4})_RR_", fname.replace("%20", " "))
        if not m:
            return None
        for fmt in ("%B %d_ %Y", "%B %d, %Y", "%B %d %Y"):
            try:
                return time.strptime(m.group(1).replace(",", "_").replace("__", "_"), fmt)
            except Exception:
                continue
        return None

    dated = [(row, _doc_date(row)) for row in rows if row.get("prDocument")]
    dated = [d for d in dated if d[1] is not None] or [(row, None) for row in rows if row.get("prDocument")]
    if not dated:
        return None
    dated.sort(key=lambda d: d[1] or time.gmtime(0), reverse=True)
    return dated[0][0]


def _extract_key_rating_drivers(html):
    """Pull the 'Key Rating Drivers & Detailed Description' section (Strengths
    + Weakness bullets) out of a CRISIL rationale page's plain-text rendering.
    The page is old-style table markup with no useful classes/ids, so this
    slices on the section headings themselves (verified stable across the
    ITC/Reliance rationale pages checked while building this)."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    m = re.search(
        r"Key Rating Drivers.*?(?=\n(?:Liquidity|ESG profile|Rating Sensitivity|Outlook)\b)",
        text, re.S,
    )
    krd = m.group().strip() if m else None

    rationale_m = re.search(r"Detailed Rationale\n(.*?)(?=\nAnalytical Approach\b)", text, re.S)
    detailed_rationale = rationale_m.group(1).strip() if rationale_m else None

    date_m = re.search(r"^([A-Za-z]+ \d{1,2}, \d{4})\s*\|", text, re.M)
    rationale_date = date_m.group(1) if date_m else None

    return {
        "key_rating_drivers": krd,
        "detailed_rationale": detailed_rationale,
        "rationale_date": rationale_date,
    }


def fetch_crisil_rationale(company_name, symbol=None, force=False):
    """
    PORTAL-07: fetch the latest CRISIL rating rationale for a company and
    extract its 'Key Rating Drivers & Detailed Description' section (the
    qualitative-evidence source for A.2's moat scoring).

    Returns a dict:
      {"result": "CHECKED", "rating": ..., "outlook": ..., "rationale_date": ...,
       "key_rating_drivers": "...", "detailed_rationale": "...", "url": "...",
       "retrieved_at": "..."}
    or, on any failure to locate/parse a rationale:
      {"result": "NOT_DISCLOSED" | "SEARCH_INCONCLUSIVE" | "ACCESS_RESTRICTED",
       "note": "..."}
    Never raises.
    """
    # Keyed on the ACTUAL search term (company_name), not just `symbol` - CRISIL's
    # search is name-driven, so a prior failed search using a bare ticker (e.g. a
    # caller that didn't have the full company name yet) must not poison a later,
    # correct search using the real name for the same symbol. Confirmed bug: an
    # earlier bulk-refresh test call passed name=None (fell back to the ticker),
    # cached NOT_DISCLOSED under the symbol-only key, and a subsequent correct
    # call with the real name kept reading that stale negative result back out.
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        # Document-only manual workflow: never reach live crisilratings.com.
        # A.2.x's own AR-evidence fetchers already search the uploaded
        # Credit Rating Report (extra_manual_document_types) as the
        # document-based equivalent of this pathway.
        return {"result": "NOT_CHECKED",
                "note": "Live CRISIL lookup skipped in the document-only manual workflow - "
                        "see the uploaded Credit Rating Report evidence pathway instead."}

    cache_key = f"{(symbol or '').upper()}_{(company_name or '').strip().upper()}"
    if not force:
        cached = _read_cache(cache_key)
        if cached is not None:
            return cached

    if not company_name:
        result = {"result": "SEARCH_INCONCLUSIVE", "note": "No company name supplied for CRISIL search."}
        _write_cache(cache_key, result)
        return result

    with _lock:
        try:
            session = _session()
            rows = _search_company(session, company_name)
            if not rows:
                result = {
                    "result": "NOT_DISCLOSED",
                    "note": f"No CRISIL-rated instrument found for '{company_name}' - company may be "
                            f"unrated by CRISIL, or rated under a different registered name.",
                }
                _write_cache(cache_key, result)
                return result

            doc_row = _latest_rationale_doc(rows)
            if not doc_row:
                result = {"result": "SEARCH_INCONCLUSIVE", "note": "CRISIL search matched a company but no rationale document was listed."}
                _write_cache(cache_key, result)
                return result

            base_path = doc_row.get("ratingFileBasePath", "/mnt/winshare/Ratings/RatingList/RatingDocs/")
            doc_url = DOC_BASE + base_path.rstrip("/") + "/" + doc_row["prDocument"].replace(" ", "%20")

            r = session.get(doc_url, timeout=25)
            if r.status_code == 403:
                result = {"result": "ACCESS_RESTRICTED", "note": f"CRISIL rationale page returned 403: {doc_url}"}
                _write_cache(cache_key, result)
                return result
            if r.status_code != 200 or len(r.text) < 500:
                result = {"result": "SEARCH_INCONCLUSIVE", "note": f"CRISIL rationale page fetch failed (status {r.status_code}): {doc_url}"}
                _write_cache(cache_key, result)
                return result

            extracted = _extract_key_rating_drivers(r.text)
            if not extracted.get("key_rating_drivers"):
                result = {
                    "result": "SEARCH_INCONCLUSIVE",
                    "note": "CRISIL rationale page fetched but 'Key Rating Drivers' section could not be parsed out.",
                    "url": doc_url,
                }
                _write_cache(cache_key, result)
                return result

            result = {
                "result": "CHECKED",
                "company_name": doc_row.get("companyName"),
                "rating": doc_row.get("rating"),
                "outlook": doc_row.get("outlook"),
                "industry_name": doc_row.get("industryName"),
                "url": doc_url,
                **extracted,
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            _write_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"[crisil_scraper] fetch_crisil_rationale failed for {company_name!r}: {e}")
            result = {"result": "SEARCH_INCONCLUSIVE", "note": f"CRISIL fetch raised: {e}"}
            _write_cache(cache_key, result)
            return result


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "ITC Limited"
    print(json.dumps(fetch_crisil_rationale(name, force=True), indent=2))
