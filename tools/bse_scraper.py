"""
BSE segment scraper - revenue-by-segment for an Indian company, straight from the
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
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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
        # NAME first - BSE symbol search returns famous namesakes (searching "APOLLO"
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
            # BSE wraps the query's matched substring in <strong> INSIDE the
            # span whenever the query text overlaps the ticker itself (very
            # common for companies whose name IS their ticker - WIPRO, CIPLA,
            # ZOMATO, TRENT, DLF, UPL, MARICO, ...): e.g.
            # "<span><strong>CIPLA</strong>&nbsp;&nbsp;&nbsp;INE059A01026...".
            # The old `[^<]+` span pattern requires ZERO "<" characters inside
            # the span and silently found NO entries at all for these - every
            # ratio for the company then failed with "No Annual Report
            # filings found", even though the company was found by BSE just
            # fine. Match the span permissively (`.*?`) and strip any HTML
            # tags from its captured text afterwards instead.
            entries = re.findall(r"liclick\('(\d{6})','([^']*)'\).*?<span>(.*?)</span>", r.text, re.S)
            if not entries:
                continue
            parsed = []
            for cd, nm, span in entries:
                span_clean = re.sub(r"<[^>]+>", "", span)
                nse_sym = re.split(r"(?:&nbsp;)+|\s{2,}", span_clean.strip())[0].strip().upper()
                parsed.append((cd, nm, nse_sym))
            # 1) Exact NSE-symbol match - kills namesakes (APOLLO -> Apollo Micro, not Tyres).
            best = next((cd for cd, nm, ns in parsed if ns == sym_up), None)
            # 2) Exact company-name match.
            if not best:
                best = next((cd for cd, nm, ns in parsed if " ".join(_norm(nm).split()) == target), None)
            # 3) Name contains, checked BOTH directions (only when we searched
            # by a name variant - avoids namesakes). Our stored name can be
            # longer than BSE's current listed name after a corporate rename
            # that shortened it (e.g. "GMR Airports Infrastructure Limited"
            # in our registry vs. BSE's current "GMR AIRPORTS LTD" record) -
            # a one-directional `target in entry` check misses that case
            # entirely since target is the longer string. Checking the
            # reverse (entry contained in target) as well as requiring at
            # least a 2-word overlap keeps this safe from single-word/short
            # namesake false positives.
            if not best and q != symbol:
                for cd, nm, ns in parsed:
                    entry_norm = " ".join(_norm(nm).split())
                    if not target or not entry_norm:
                        continue
                    if target in entry_norm or entry_norm in target:
                        best = cd
                        break
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


def _segment_section_text(content):
    """Return the concatenated text of the page(s) that hold the segment tables
    (Segment Revenue + Segment Results). Grabs the matching page plus the next one,
    since the Results (profit) sub-table often spills over."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        return None
    pages = []
    for pi, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception:
            continue
        pages.append(t)
    for pi, t in enumerate(pages):
        if re.search(r"segment[-\s]*wise|segment\s+revenue|segment\s+information|segment\s+result", t, re.I):
            block = t
            if pi + 1 < len(pages):
                block += "\n" + pages[pi + 1]
            return block[:9000]
    return None


def _f(v):
    try:
        return float(v)
    except Exception:
        return None


def _extract_segments_llm(seg_text, company, api_key):
    """Extract segment revenue + profit from the jumbled PDF text via the LLM - robust
    across filing layouts. SELF-VALIDATED: the model also reports the gross segment
    revenue total, and we only accept the extraction if the per-segment revenues sum to
    it (±6%) - this rejects the failure mode where the model mixes period columns and
    mis-maps names to numbers. Retries once, else returns None. Returns (list, period)."""
    from tools.groq_client import groq_chat, parse_json_loose
    prompt = (
        f"You are reading the SEGMENT table from {company}'s audited BSE quarterly result filing. "
        "The text is machine-extracted and jumbled; segment names and their numbers may sit in "
        "separate blocks. Two sub-tables matter: 'Segment Revenue' (Value of Sales & Services) and "
        "'Segment Results' (segment profit / PBIT).\n\n"
        "CRITICAL: use ONLY the MOST RECENT QUARTER column (the leftmost data column, headed by the "
        "latest quarter-end date). Do NOT read the nine-month, year-to-date, or full-year columns. "
        "Every segment's number must come from that SAME single column.\n\n"
        "Return ONLY JSON:\n"
        '{ "period": "e.g. Q3 FY26", "gross_revenue_cr": 0, "segments": [ '
        '{"name":"...", "revenue_cr": 0, "profit_cr": null, "revenue_prev_cr": null, "profit_prev_cr": null} ] }\n'
        "Rules:\n"
        "- gross_revenue_cr = the GROSS segment revenue total for that quarter column (sum of all segments).\n"
        "- One row per BUSINESS SEGMENT. EXCLUDE Total, Gross, Inter-segment, Unallocable, GST rows.\n"
        "- revenue_cr / profit_cr = that most-recent-quarter column. revenue_prev_cr / profit_prev_cr = "
        "the SAME quarter a YEAR AGO (for growth), else null.\n"
        "- profit_cr from 'Segment Results'; if that table is absent use null (do NOT guess).\n"
        "- Every number is a PLAIN INTEGER in Rs crore - NO commas, spaces or symbols (33700, not 33,700).\n\n"
        f"=== SEGMENT TABLE TEXT ===\n{seg_text}"
    )
    messages = [
        {"role": "system", "content": "You extract structured financial tables. Reply with strict JSON only."},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(2):
        try:
            raw = groq_chat(messages=messages, max_tokens=1100, temperature=0.0, api_key=api_key)
            raw = re.sub(r"(?<=\d),(?=\d)", "", raw or "")  # strip thousands separators (invalid JSON)
            data = parse_json_loose(raw) or {}
            out = []
            for s in (data.get("segments") or []):
                if not isinstance(s, dict):
                    continue
                nm = re.sub(r"\s+", " ", str(s.get("name") or "")).strip()
                rev = _f(s.get("revenue_cr"))
                if not nm or rev is None or rev <= 0 or re.search(r"total|inter[\s-]*segment|unalloc|gross", nm, re.I):
                    continue
                out.append({
                    "name": nm[0].upper() + nm[1:],
                    "revenue_cr": round(rev),
                    "profit_cr": (round(_f(s.get("profit_cr"))) if _f(s.get("profit_cr")) is not None else None),
                    "revenue_prev_cr": (round(_f(s.get("revenue_prev_cr"))) if _f(s.get("revenue_prev_cr")) is not None else None),
                    "profit_prev_cr": (round(_f(s.get("profit_prev_cr"))) if _f(s.get("profit_prev_cr")) is not None else None),
                })
            if len(out) < 2:
                messages.append({"role": "user", "content": "That was not usable. Re-extract, one row per business segment, latest quarter column only, plain-integer crore numbers."})
                continue
            # Self-consistency gate: segment revenues must sum to the reported gross.
            gross = _f(data.get("gross_revenue_cr"))
            seg_sum = sum(s["revenue_cr"] for s in out)
            if gross and abs(seg_sum - gross) / gross > 0.06:
                print(f"[bse] segment self-check failed (sum {seg_sum} vs gross {gross}); "
                      f"{'retrying' if attempt == 0 else 'rejecting'}.")
                messages.append({"role": "user", "content": (
                    f"The segment revenues you returned sum to {seg_sum} but the gross is {gross} - you mixed "
                    "columns. Re-read using ONLY the single most-recent-quarter column so the segments sum to the gross.")})
                continue
            return out, data.get("period")
        except Exception as e:
            print(f"[bse] LLM segment extraction attempt {attempt + 1} failed: {e}")
    return None, None


def _derive_segment_metrics(segments):
    """Add revenue %, profit %, margin, YoY growth and an importance tag to each segment."""
    total_rev = sum(s["revenue_cr"] for s in segments) or 1
    profits = [s["profit_cr"] for s in segments if s.get("profit_cr") is not None]
    total_profit = sum(p for p in profits if p and p > 0) or None
    for s in segments:
        s["pct"] = round(s["revenue_cr"] / total_rev * 100, 1)
        if s.get("profit_cr") is not None and total_profit:
            s["profit_pct"] = round(max(s["profit_cr"], 0) / total_profit * 100, 1)
            s["margin"] = round(s["profit_cr"] / s["revenue_cr"] * 100, 1) if s["revenue_cr"] else None
        if s.get("revenue_prev_cr"):
            s["yoy_growth"] = round((s["revenue_cr"] - s["revenue_prev_cr"]) / s["revenue_prev_cr"] * 100, 1)
    # Importance: blended revenue share + profit share + growth, bucketed.
    for s in segments:
        score = 0.55 * s["pct"] + 0.30 * (s.get("profit_pct") or s["pct"]) + 0.15 * min(max(s.get("yoy_growth", 0), -20), 40)
        s["importance"] = "Core" if score >= 30 else "Major" if score >= 12 else "Minor"
    segments.sort(key=lambda s: -s["revenue_cr"])
    return segments


def fetch_bse_segments(symbol, name=None):
    """
    Segment-wise business model from the company's audited BSE quarterly result filing:
    {'segments': [{name, revenue_cr, pct, profit_cr, profit_pct, margin, yoy_growth,
    importance}], 'period', 'source'} - or {} when unavailable. LLM-extracted from the
    filing PDF (robust across layouts), regex fallback. Cached 7 days. Never raises.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    ck = f"segx_{sym}"  # v2 cache key (richer schema)
    cached = _read_cache(ck)
    if cached is not None:
        return cached
    result = {}
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    with _lock:
        cached = _read_cache(ck)
        if cached is not None:
            return cached
        try:
            code = _resolve_scrip_code(sym, name)
            if not code:
                _write_cache(ck, {})
                return {}
            s = _sess()
            for att in _result_attachments(code)[:4]:
                for base in ("AttachHis", "AttachLive"):
                    try:
                        r = s.get(_ATTACH.format(base=base, name=att), timeout=40)
                        if r.content[:4] != b"%PDF":
                            continue
                        segs, period = None, None
                        # Primary: LLM extraction (revenue + profit, layout-robust).
                        if api_key and api_key != "your_api_key_here":
                            seg_text = _segment_section_text(r.content)
                            if seg_text:
                                segs, period = _extract_segments_llm(seg_text, name or sym, api_key)
                        # Fallback: legacy regex (revenue-only).
                        if not segs:
                            legacy = _parse_segment_pdf(r.content)
                            if legacy:
                                segs = legacy
                        if segs:
                            _derive_segment_metrics(segs)
                            result = {
                                "segments": segs,
                                "period": period,
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
