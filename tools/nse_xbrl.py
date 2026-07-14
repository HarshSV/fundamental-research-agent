"""
NSE XBRL fundamentals — REAL, standalone, audited financial statements pulled
straight from a company's own filing with NSE (the source document every other
vendor re-parses).

Why this exists: Screener/yfinance/Angel One don't expose itemized standalone
line items (Inventory, Cost of materials consumed, ...). NSE publishes each
result as machine-tagged XBRL — no API key, free, and it IS the audited filing.

Taxonomies:
  - Non-financials -> Ind-AS taxonomy  (XBRL url contains 'INDAS_')  -> has
    Inventories / CostOfMaterialsConsumed etc.
  - Banks/NBFCs    -> Banking taxonomy (XBRL url contains 'BANKING_') -> NO
    inventory/COGS tags (the concept doesn't apply) -> ratios like Inventory
    Turnover are correctly N/A, never fabricated.

Design mirrors the other scrapers: curl_cffi (real-browser TLS), disk cache,
never raises. Values in XBRL are absolute rupees; we expose ₹ crore (value/1e7).

NOTE: NSE blocks datacenter IPs. Works from a normal/India IP (local); on a
cloud host route through NSE_PROXY_URL.
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

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "nse_xbrl")
TTL = 12 * 3600
_lock = threading.Lock()

_RESULTS_API = ("https://www.nseindia.com/api/corporates-financial-results"
                "?index=equities&symbol={sym}&period={period}")
_NS = "in-bse-fin"  # every NSE Ind-AS / Banking result uses this fact namespace

# Companies whose business model has no inventory — Inventory Turnover is N/A by
# definition, not by missing data. (Belt-and-suspenders on top of taxonomy check.)
_NON_INVENTORY = ("bank", "financ", "finance", "nbfc", "insurance", "insurer",
                  "life ", "assurance", "gic ", "amc", "asset management",
                  "fintech", "housing finance", "capital", "securities", "broking")


# --------------------------------------------------------------------------- #
# HTTP + cache
# --------------------------------------------------------------------------- #
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


def _get_text(url, retries=3):
    last = None
    for _ in range(retries):
        try:
            r = _session().get(url, timeout=30)
            if r.status_code == 200 and len(r.text) > 200:
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)
            time.sleep(1.5)
    print(f"[nse_xbrl] GET failed ({url}): {last}")
    return None


# --------------------------------------------------------------------------- #
# Filing discovery
# --------------------------------------------------------------------------- #
def fetch_filings(symbol, period="Annual", standalone=False):
    """List a company's filings (newest first) as
    [{to_date, consolidated, audited, taxonomy, xbrl}]. `taxonomy` is 'INDAS',
    'BANKING' or 'OTHER' (from the XBRL filename). period: 'Annual'|'Quarterly'."""
    sym = symbol.strip().upper().replace(".NS", "")
    txt = _get_text(_RESULTS_API.format(sym=sym, period=period))
    if not txt:
        return []
    try:
        rows = json.loads(txt)
    except Exception:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        xbrl = (r.get("xbrl") or "").strip()
        if not xbrl or xbrl.endswith("/-"):
            continue
        is_standalone = r.get("consolidated") == "Non-Consolidated"
        want_standalone = bool(standalone)
        if want_standalone != is_standalone:
            continue
        fname = xbrl.rsplit("/", 1)[-1].upper()
        taxonomy = "INDAS" if fname.startswith("INDAS") else "BANKING" if fname.startswith("BANKING") else "OTHER"
        out.append({
            "to_date": r.get("toDate"),
            "consolidated": r.get("consolidated"),
            "audited": r.get("audited"),
            "relating_to": r.get("relatingTo"),
            "taxonomy": taxonomy,
            "xbrl": xbrl,
        })
    return out


# --------------------------------------------------------------------------- #
# XBRL parsing
# --------------------------------------------------------------------------- #
def _parse_xbrl(xml):
    """Return (contexts, facts). contexts: {id: {'type','date','dim'}}. facts:
    {tag: [(context_id, float_value)]}. `dim` flags segment/dimensional contexts
    (we ignore those for company-level totals)."""
    contexts = {}
    for m in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', xml, re.S):
        cid, body = m.group(1), m.group(2)
        dim = ("explicitMember" in body) or ("xbrldi" in body)
        inst = re.search(r"<xbrli:instant>([^<]+)</xbrli:instant>", body)
        ed = re.search(r"<xbrli:endDate>([^<]+)</xbrli:endDate>", body)
        if inst:
            contexts[cid] = {"type": "instant", "date": inst.group(1).strip(), "dim": dim}
        elif ed:
            contexts[cid] = {"type": "duration", "date": ed.group(1).strip(), "dim": dim}
    facts = {}
    for m in re.finditer(rf'<{_NS}:([A-Za-z0-9]+)[^>]*contextRef="([^"]+)"[^>]*>([^<]+)</{_NS}:[A-Za-z0-9]+>', xml):
        tag, cid, raw = m.group(1), m.group(2), m.group(3).strip()
        try:
            val = float(raw)
        except Exception:
            continue
        facts.setdefault(tag, []).append((cid, val))
    return contexts, facts


def _to_cr(v):
    return round(v / 1e7, 2) if isinstance(v, (int, float)) else None


def _annual_context(contexts, facts, probe_tag="RevenueFromOperations"):
    """In an annual filing there are two duration contexts (the quarter and the
    full year). NSE mislabels the annual context's START date, so we can't trust
    dates — instead pick the duration context whose probe value (revenue) is the
    LARGEST. That is the full-year column; reuse its id for every flow line."""
    best_cid, best_val = None, -1.0
    for cid, val in facts.get(probe_tag, []):
        c = contexts.get(cid)
        if not c or c["dim"] or c["type"] != "duration":
            continue
        if abs(val) > best_val:
            best_cid, best_val = cid, abs(val)
    return best_cid


def _fact_in_context(facts, tag, cid):
    for c, v in facts.get(tag, []):
        if c == cid:
            return v
    return None


def _latest_instant_value(contexts, facts, tag):
    """Value of an instant (balance-sheet) tag at its latest reported date, plus
    that date. Ignores dimensional contexts."""
    best = None
    for cid, val in facts.get(tag, []):
        c = contexts.get(cid)
        if not c or c["dim"] or c["type"] != "instant":
            continue
        if best is None or c["date"] > best[0]:
            best = (c["date"], val)
    return best  # (date, value) or None


def _fetch_parsed(xbrl_url):
    xml = _get_text(xbrl_url)
    if not xml:
        return None, None
    return _parse_xbrl(xml)


# --------------------------------------------------------------------------- #
# Inventory Turnover (first concrete ratio, per the manager's formula)
# --------------------------------------------------------------------------- #
_COGS_TAGS = {
    "Cost of materials consumed": "CostOfMaterialsConsumed",
    "Purchases of stock-in-trade": "PurchasesOfStockInTrade",
    "Changes in inventories": "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade",
}


def _fy_label(to_date):
    """'31-Mar-2024' -> 'FY24'."""
    try:
        return f"FY{to_date[-2:]}"
    except Exception:
        return to_date or "—"


def _compute_pair(cur, prev, sym=None, name=None):
    """Compute Inventory Turnover from a current + prior ANNUAL filing pair.
    Returns (result_dict, None) or (None, reason)."""
    ctx_c, facts_c = _fetch_parsed(cur["xbrl"])
    ctx_p, facts_p = _fetch_parsed(prev["xbrl"])
    if not facts_c or not facts_p:
        return None, "Could not download/parse the XBRL filings."

    # Numerator: COGS (a+b+c) from the current year's full-year (annual) column.
    acid = _annual_context(ctx_c, facts_c)
    components, cogs, have_any = {}, 0.0, False
    for label, tag in _COGS_TAGS.items():
        v = _fact_in_context(facts_c, tag, acid) if acid else None
        cr = _to_cr(v) if v is not None else None
        components[label] = cr
        if cr is not None:
            cogs += cr
            have_any = True
    if not have_any or cogs == 0:
        return None, "No Cost-of-materials / Purchases lines in the filing — not a goods business."

    # Denominator: average of the two consecutive year-end Inventories.
    inv_cur = _latest_instant_value(ctx_c, facts_c, "Inventories")
    inv_prev = _latest_instant_value(ctx_p, facts_p, "Inventories")
    if not inv_cur or not inv_prev or not inv_cur[1] or not inv_prev[1]:
        return None, "Inventory line not found (or zero) in one of the two annual balance sheets — not a goods business."
    inv_cur_cr, inv_prev_cr = _to_cr(inv_cur[1]), _to_cr(inv_prev[1])

    # ACCURACY FIX: NSE's annual XBRL only tags the CURRENT year-end balance
    # sheet — never a prior-year comparative. So the "prior year" figure above
    # comes from a DIFFERENT filing (that year's own annual XBRL), which is
    # wrong whenever the company restates prior-year comparatives (e.g. after a
    # merger/amalgamation — confirmed for Tata Steel FY24, which absorbed
    # Neelachal Ispat Nigam Ltd). The company's OWN current-year filing shows
    # the correctly RESTATED comparative; extract it (deterministically, from
    # PDF word positions — no LLM) and use it in place of the separate-filing
    # figure, but ONLY if the extraction's own current-year value matches the
    # already-trusted XBRL figure (i.e. we know we read the right row).
    restated_note = None
    if sym:
        try:
            from tools.bse_restated_inventory import fetch_restated_prior_inventory
            r = fetch_restated_prior_inventory(sym, name, cur["to_date"], inv_cur_cr)
            if r and r.get("value_cr") is not None:
                inv_prev_cr = r["value_cr"]
                restated_note = r.get("source_url")
        except Exception as e:
            print(f"[nse_xbrl] restated-inventory lookup skipped: {e}")

    avg_inv = round((inv_cur_cr + inv_prev_cr) / 2, 2)
    ratio = round(cogs / avg_inv, 2) if avg_inv else None

    note = ("Consolidated, audited — Cost of Goods Sold from NSE XBRL; prior-year "
            "Inventory is the company's own RESTATED comparative (verified against "
            "the filing), so both years are on the same reporting basis."
            if restated_note else
            "Consolidated, audited — computed from the company's own NSE XBRL result filings.")

    sources = [{"period": cur.get("to_date"), "url": cur["xbrl"]},
               {"period": prev.get("to_date"), "url": prev["xbrl"]}]
    if restated_note:
        sources.append({"period": f"{prev.get('to_date')} (restated, as reported in the {cur.get('to_date')} filing)",
                         "url": restated_note})

    # Confidence: 1.0 when the prior-year figure is the restated comparator from
    # the current filing (same basis as the numerator); 0.95 when it comes from a
    # separate prior-year filing (two clearly-disclosed sources, small basis risk).
    confidence = 1.0 if restated_note else 0.95

    return {
        "value": ratio, "unit": "x",
        "confidence": confidence,
        "estimated": False,
        "period": f"{_fy_label(cur['to_date'])} (consolidated)",
        "numerator": {"label": "Cost of Goods Sold (a + b + c)", "value_cr": round(cogs, 2),
                      "components": components},
        "denominator": {"label": "Average Inventory (opening + closing) ÷ 2", "value_cr": avg_inv,
                        "inventory_by_year": {inv_cur[0]: inv_cur_cr, inv_prev[0]: inv_prev_cr}},
        "sources": sources,
        "note": note,
    }, None


def _annual_standalone_filings(sym):
    """Audited CONSOLIDATED annual filings, newest-first, de-duplicated by year
    (NSE lists each filing twice). Name kept for compatibility with callers."""
    annuals = fetch_filings(sym, period="Annual", standalone=False)
    annuals = [a for a in annuals if a.get("audited") == "Audited"] or annuals
    seen, uniq = set(), []
    for a in annuals:
        d = a.get("to_date")
        if d and d not in seen:
            seen.add(d)
            uniq.append(a)
    return uniq


def _yr_from_to_date(td):
    try:
        return int(str(td)[-4:])
    except Exception:
        return None


def _try_year(sym, name, ar_years, annuals, target_year):
    """Try to compute Inventory Turnover for one fiscal year: Annual Report
    first, then NSE XBRL for that same year. Returns (result_dict, None) or
    (None, reason) — never raises."""
    try:
        from tools.annual_report_financials import fetch_inventory_turnover_from_annual_report
        if target_year in ar_years:
            ar = fetch_inventory_turnover_from_annual_report(sym, name, target_year, consolidated=True)
            if ar.get("applicable"):
                return ar, None
    except Exception as e:
        print(f"[nse_xbrl] Annual Report path errored for {sym} FY{target_year}: {e}")

    def _yr(d):
        try:
            return int(str(d)[-4:])
        except Exception:
            return 0
    idx = None
    for i in range(len(annuals) - 1):
        if _yr(annuals[i]["to_date"]) == target_year:
            idx = i
            break
    if idx is None:
        return None, f"No published Annual Report or NSE result filing yet for FY{str(target_year)[-2:]}."
    if annuals[idx]["taxonomy"] == "BANKING":
        return None, "Not applicable — banking-taxonomy filing has no Inventory / Cost-of-materials lines."
    return _compute_pair(annuals[idx], annuals[idx + 1], sym=sym, name=name)


def fetch_inventory_turnover(symbol, name=None, to_date=None):
    """
    Inventory Turnover = COGS (a+b+c) / Average Inventory. PRIMARY source is the
    company's own Annual Report (per the Source Hierarchy — ranks above the
    quarterly/annual Reg-33 result filing): both years' figures sit in the SAME
    document, on the same reporting basis, and the statements extract cleanly
    (no jumbled-text reconstruction needed). Falls back to the NSE XBRL Reg-33
    filing (proven, but needs the restated-comparative patch — see
    bse_restated_inventory.py) only if the Annual Report path fails for that year.

    `to_date` selects which year-end to compute (e.g. '31-Mar-2024'); when it's
    explicit we compute exactly that year (N/A if it genuinely isn't published
    yet). When it's None (default load) we walk newest-to-oldest and return the
    FIRST year that actually computes — e.g. skip FY26 straight to FY25 if
    FY26's filing isn't out yet, rather than showing a blank "latest year".
    Always returns `available_periods` for the UI year-picker. Returns
    {'applicable': False} for lenders/no-inventory businesses — never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"invturn_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Inventory Turnover"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business with no inventory."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import list_annual_report_years
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []
    annuals = _annual_standalone_filings(sym)

    def _yr(d):
        try:
            return int(str(d)[-4:])
        except Exception:
            return 0
    xbrl_years = [_yr(a["to_date"]) for a in annuals]
    all_years = sorted(set(ar_years) | set(xbrl_years), reverse=True)
    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in all_years] or None

    if not all_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report or NSE filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    # Explicit year requested -> compute exactly that one (N/A is an honest answer).
    if to_date:
        target_year = _yr_from_to_date(to_date) or all_years[0]
        computed, reason = _try_year(sym, name, ar_years, annuals, target_year)
        out = ({**base, "applicable": True, "selected_period": f"31-Mar-{target_year}",
                "available_periods": available, **computed} if computed else
               {**base, "applicable": False, "reason": reason,
                "selected_period": f"31-Mar-{target_year}", "available_periods": available})
        _write_cache(ckey, out)
        return out

    # No year requested -> walk newest-to-oldest, return the first that computes.
    # Cap the cascade at a few years: each attempt is a real PDF fetch+parse
    # (seconds), and if the two most recent years both come back "not a goods
    # business" the company is structurally a services/financial business —
    # trying all the way back to FY97 just to confirm that again is pure
    # latency for nothing (this is what made IT-services symbols take 80s+).
    # A genuine "not published yet" reason DOES keep cascading, since that's
    # exactly the case (this year not out, prior year is) we're trying to
    # skip past.
    MAX_PROBE_YEARS = 4
    first_reason = None
    goods_business_fail_streak = 0
    for probed, target_year in enumerate(all_years):
        computed, reason = _try_year(sym, name, ar_years, annuals, target_year)
        if computed:
            out = {**base, "applicable": True, "selected_period": f"31-Mar-{target_year}",
                   "available_periods": available, **computed}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = reason
        if "not a goods business" in (reason or "").lower():
            goods_business_fail_streak += 1
            if goods_business_fail_streak >= 2:
                break  # two years running with no COGS/inventory -> structurally not a goods business
        else:
            goods_business_fail_streak = 0
        if probed + 1 >= MAX_PROBE_YEARS:
            break  # bound worst-case latency regardless of reason
    last_reason = first_reason or "Not applicable for this company."
    out = {**base, "applicable": False, "reason": last_reason,
           "selected_period": f"31-Mar-{all_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Receivables Turnover — Revenue from Operations ÷ Average Trade Receivables.
# Sourced from the Annual Report only (no NSE XBRL Reg-33 fallback yet — the
# Annual Report is the spec's #1-ranked source anyway, and it's already what
# Inventory Turnover reuses across ratios via the shared cached extraction).
# --------------------------------------------------------------------------- #
def fetch_receivables_turnover(symbol, name=None, to_date=None):
    """
    Receivables Turnover = Revenue from Operations ÷ Average Trade Receivables
    (Revenue from Operations used as a proxy for Net Credit Sales — Indian
    Annual Reports don't split cash vs. credit sales). Same year-selection
    behaviour as `fetch_inventory_turnover`: explicit `to_date` computes
    exactly that year; `to_date=None` walks newest-to-oldest and returns the
    first year that actually computes. Returns {'applicable': False} for
    lenders/financial businesses (receivables concept differs — loans/advances
    instead) — never a fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"recvturn_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Receivables Turnover"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(receivables concept differs — loans/advances instead)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_receivables_turnover_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_receivables_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        # `r` is spread regardless of applicability — an N/A result can still
        # carry real partial figures worth showing, not just a reason string.
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    # No year requested -> walk newest-to-oldest (capped, same rationale as
    # Inventory Turnover's cascade), return the first year that computes.
    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_receivables_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Payables Turnover — Purchases (a+b) ÷ Average Trade Payables. Sourced from
# the Annual Report only, same rationale as Receivables Turnover.
# --------------------------------------------------------------------------- #
def fetch_payables_turnover(symbol, name=None, to_date=None):
    """
    Payables Turnover = Purchases ÷ Average Trade Payables (Purchases = Cost
    of materials consumed + Purchases of stock-in-trade, falling back to
    COGS minus the inventory movement only if that split isn't available).
    Same year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses — never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"payturn_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Payables Turnover"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business with no trade payables."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_payables_turnover_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_payables_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        # `r` is spread regardless of applicability — an N/A result can still
        # carry real partial figures worth showing, not just a reason string.
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_payables_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Asset Turnover — Revenue from Operations ÷ Average Total Assets. Sourced
# from the Annual Report only, same rationale as Receivables/Payables Turnover.
# --------------------------------------------------------------------------- #
def fetch_asset_turnover(symbol, name=None, to_date=None):
    """
    Asset Turnover = Revenue from Operations ÷ Average Total Assets. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses — never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"assetturn_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Asset Turnover"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(asset base is fundamentally different — loans/investments, not operating assets)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_asset_turnover_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_asset_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        # `r` is spread regardless of applicability — an N/A result can still
        # carry real partial figures worth showing, not just a reason string.
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_asset_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Working Capital Turnover — Revenue from Operations ÷ Average Working
# Capital (Total Current Assets − Total Current Liabilities). Sourced from
# the Annual Report only, same rationale as the other turnover ratios.
# --------------------------------------------------------------------------- #
def fetch_working_capital_turnover(symbol, name=None, to_date=None):
    """
    Working Capital Turnover = Revenue from Operations ÷ Average Working
    Capital. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses, and also
    when Average Working Capital is zero/negative (per spec — never silently
    reports a sign-inverted or meaningless ratio). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"wcturn_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Working Capital Turnover"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(current assets/liabilities concept differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_working_capital_turnover_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    # Note: `r` is spread in BOTH the applicable and N/A cases below — an N/A
    # result (e.g. negative Average Working Capital) still carries real
    # numerator/denominator figures worth showing, not just a reason string,
    # so those fields must survive into the final response either way.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_working_capital_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_working_capital_turnover_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_result is None:
            first_result = (target_year, r)
    first_year, first_r = first_result or (ar_years[0], {"reason": "Not applicable for this company."})
    out = {**base, "selected_period": f"31-Mar-{first_year}", "available_periods": available, **first_r}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Current Ratio — Total Current Assets ÷ Total Current Liabilities, closing
# balance only (point-in-time, not averaged). Sourced from the Annual Report
# only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_current_ratio(symbol, name=None, to_date=None):
    """
    Current Ratio = Total Current Assets ÷ Total Current Liabilities (closing
    balance, current year only). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses — never a fabricated number. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"currentratio_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Current Ratio"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(current assets/liabilities concept differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_current_ratio_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_current_ratio_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_current_ratio_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Quick Ratio — (Total Current Assets − Inventories) ÷ Total Current
# Liabilities, closing balance only (point-in-time, not averaged). Sourced
# from the Annual Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_quick_ratio(symbol, name=None, to_date=None):
    """
    Quick Ratio = (Total Current Assets − Inventories) ÷ Total Current
    Liabilities (closing balance, current year only). Same year-selection
    behaviour as `fetch_inventory_turnover`. Returns {'applicable': False}
    for lenders/financial businesses — never a fabricated number. Cached;
    never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"quickratio_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Quick Ratio"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(current assets/liabilities concept differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_quick_ratio_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_quick_ratio_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_quick_ratio_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Cash Ratio — Cash and Cash Equivalents ÷ Total Current Liabilities, closing
# balance only (point-in-time, not averaged). Sourced from the Annual Report
# only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_cash_ratio(symbol, name=None, to_date=None):
    """
    Cash Ratio = Cash and Cash Equivalents ÷ Total Current Liabilities
    (closing balance, current year only). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses — never a fabricated number. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"cashratio_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Cash Ratio"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(current assets/liabilities concept differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_cash_ratio_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_cash_ratio_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_cash_ratio_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Gross Profit Margin — (Revenue − COGS) ÷ Revenue, reusing the same COGS
# components validated for Inventory Turnover. Sourced from the Annual Report
# only, same rationale as Asset/Working Capital Turnover.
# --------------------------------------------------------------------------- #
def fetch_gross_profit_margin(symbol, name=None, to_date=None):
    """
    Gross Profit Margin = (Revenue from Operations − COGS) ÷ Revenue from
    Operations. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses — never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"gpm_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Gross Profit Margin"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(no goods-based Cost of Goods Sold to derive Gross Profit from)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_gross_profit_margin_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_gross_profit_margin_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_gross_profit_margin_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Operating Profit Margin (EBITDA-basis) — (Revenue − COGS − Employee Benefit
# Expense − Other Expenses) ÷ Revenue. Sourced from the Annual Report only,
# same rationale as Gross Profit Margin.
# --------------------------------------------------------------------------- #
def fetch_operating_profit_margin(symbol, name=None, to_date=None):
    """
    Operating Profit Margin (EBITDA-basis) = (Revenue − COGS − Employee
    Benefit Expense − Other Expenses) ÷ Revenue. Same year-selection
    behaviour as `fetch_inventory_turnover`. Returns {'applicable': False}
    for lenders/financial businesses — never a fabricated number. Cached;
    never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"opm_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Operating Profit Margin"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(no goods-based operating cost structure to derive Operating Profit from)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_operating_profit_margin_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_operating_profit_margin_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_operating_profit_margin_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Net Profit Margin — Profit After Tax (owners-attributable) ÷ Revenue.
# Sourced from the Annual Report only, same rationale as Gross/Operating
# Profit Margin. Applicable to ALL industries per spec (only banks/NBFC/
# insurance excluded) — unlike the COGS-based margins, this ratio doesn't
# require a goods-based cost structure, so it does NOT gate on _NON_INVENTORY
# the same way; it's still excluded for lenders per spec's own industry list.
# --------------------------------------------------------------------------- #
def fetch_net_profit_margin(symbol, name=None, to_date=None):
    """
    Net Profit Margin = Profit After Tax (owners-attributable) ÷ Revenue from
    Operations. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses — never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"npm_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Net Profit Margin"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(Revenue from Operations isn't a comparable base for banks/NBFCs/insurers)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_net_profit_margin_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_net_profit_margin_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_net_profit_margin_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Return on Equity (ROE) — Profit After Tax (owners-attributable) ÷ Average
# Total Equity (owners-attributable). Sourced from the Annual Report only,
# same rationale as Net Profit Margin.
# --------------------------------------------------------------------------- #
def fetch_return_on_equity(symbol, name=None, to_date=None):
    """
    Return on Equity = Profit After Tax (owners-attributable) ÷ Average Total
    Equity (owners-attributable). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses and for negative-equity companies (per
    spec — never a spurious positive ratio). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"roe_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Return on Equity"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(equity structure and capital adequacy rules differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_return_on_equity_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    # `r` is spread in BOTH the applicable and N/A cases — negative equity is
    # a real, worth-showing finding (like negative Working Capital), not just
    # a bare reason string.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_return_on_equity_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_return_on_equity_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_result is None:
            first_result = (target_year, r)
    first_year, first_r = first_result or (ar_years[0], {"reason": "Not applicable for this company."})
    out = {**base, "selected_period": f"31-Mar-{first_year}", "available_periods": available, **first_r}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Return on Capital Employed (ROCE) — EBIT (Profit Before Tax + Finance
# Costs) ÷ Average Capital Employed (Total Assets − Total Current
# Liabilities). Sourced from the Annual Report only, same rationale as
# Working Capital Turnover (also uses a negative-denominator N/A guard).
# --------------------------------------------------------------------------- #
def fetch_return_on_capital_employed(symbol, name=None, to_date=None):
    """
    ROCE = EBIT ÷ Average Capital Employed. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, and when Average Capital Employed is
    zero/negative (never a meaningless ratio). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"roce_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Return on Capital Employed"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(capital structure and capital adequacy rules differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_return_on_capital_employed_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    # `r` is spread in BOTH the applicable and N/A cases — a negative Capital
    # Employed is a real, worth-showing finding, not just a reason string.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_return_on_capital_employed_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_return_on_capital_employed_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_result is None:
            first_result = (target_year, r)
    first_year, first_r = first_result or (ar_years[0], {"reason": "Not applicable for this company."})
    out = {**base, "selected_period": f"31-Mar-{first_year}", "available_periods": available, **first_r}
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Debt-to-Equity Ratio — Total Debt (Long-term + Short-term Borrowings +
# Current Maturities) ÷ Total Equity (owners-attributable), both CLOSING
# balance. Sourced from the Annual Report only, same rationale as Current
# Ratio (point-in-time, no averaging).
# --------------------------------------------------------------------------- #
def fetch_debt_to_equity(symbol, name=None, to_date=None):
    """
    Debt-to-Equity = Total Debt ÷ Total Equity (owners-attributable), both
    closing balance. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, and for negative/zero-equity companies
    (per spec — never a spurious ratio). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"de_{sym}_{to_date or 'latest'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Debt-to-Equity"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable — this is a lender/financial business "
                         "(capital structure and leverage rules differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_debt_to_equity_from_annual_report)
        ar_years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[nse_xbrl] Annual Report year list skipped for {sym}: {e}")
        ar_years = []

    if not ar_years:
        out = {**base, "applicable": False,
               "reason": "No Annual Report filings found for this company.", "available_periods": None}
        _write_cache(ckey, out)
        return out

    available = [{"to_date": f"31-Mar-{y}", "label": f"FY{str(y)[-2:]}"} for y in ar_years]

    # `r` is spread in BOTH the applicable and N/A cases — negative equity is
    # a real, worth-showing finding, not just a reason string.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_debt_to_equity_from_annual_report(sym, name, target_year, consolidated=True)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_debt_to_equity_from_annual_report(sym, name, target_year, consolidated=True)
        if r.get("applicable"):
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_result is None:
            first_result = (target_year, r)
    first_year, first_r = first_result or (ar_years[0], {"reason": "Not applicable for this company."})
    out = {**base, "selected_period": f"31-Mar-{first_year}", "available_periods": available, **first_r}
    _write_cache(ckey, out)
    return out


if __name__ == "__main__":
    import sys
    for s in (sys.argv[1:] or ["TATASTEEL", "ASIANPAINT", "HDFCBANK"]):
        print(f"\n===== {s} =====")
        print(json.dumps(fetch_inventory_turnover(s), indent=2))
