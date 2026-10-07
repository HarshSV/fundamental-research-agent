"""
NSE XBRL fundamentals - REAL, standalone, audited financial statements pulled
straight from a company's own filing with NSE (the source document every other
vendor re-parses).

Why this exists: Screener/yfinance/Angel One don't expose itemized standalone
line items (Inventory, Cost of materials consumed, ...). NSE publishes each
result as machine-tagged XBRL - no API key, free, and it IS the audited filing.

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

try:
    from tools.db_ratio_reader import try_db_ratio as _db_try_db_ratio, write_db_ratio as _db_write_db_ratio
except Exception:  # pragma: no cover - DB unreachable/misconfigured falls through to live path
    def _db_try_db_ratio(symbol, ratio_no, consolidated=None, extraction_version=None):
        return None

    def _db_write_db_ratio(symbol, ratio_no, out, consolidated=True, extraction_version=None):
        pass


def try_db_ratio(symbol, ratio_no, consolidated=None):
    """Central, version-aware wrapper around `db_ratio_reader.try_db_ratio` -
    every one of this file's ~50 `fetch_X` wrappers calls this exact name
    (`try_db_ratio(sym, ratio_no)`), so shadowing the module-level name here
    (rather than editing each of those ~50 call sites individually) makes
    EVERY one of them - existing AND any future ratio added the same way -
    automatically version-aware with zero extra code at the call site. See
    `_current_extraction_version()` for what "version-aware" means and why
    it matters: without it, a Supabase row precomputed under OLDER
    extraction/calculation logic would be served forever regardless of any
    later code fix, since this DB fast-path sits BEFORE this file's own
    `_doc_tag_for_cache`-based cache invalidation entirely."""
    return _db_try_db_ratio(symbol, ratio_no, consolidated=consolidated,
                             extraction_version=_current_extraction_version())


def write_db_ratio(symbol, ratio_no, out, consolidated=True):
    """Central, version-aware wrapper around `db_ratio_reader.write_db_ratio`
    - same "shadow the name once, every caller benefits" reasoning as
    `try_db_ratio` above. Every live-computed result gets written back
    tagged with the CURRENT extraction version, so the next `try_db_ratio`
    call for it is a hit again immediately (self-healing), and a future
    extraction/logic fix will correctly treat it as stale without anyone
    needing to remember to bump anything at this call site."""
    return _db_write_db_ratio(symbol, ratio_no, out, consolidated=consolidated,
                               extraction_version=_current_extraction_version())


def _resolved_consolidated(sym, name, fiscal_year):
    """Replaces every call site below's previous hardcoded
    `consolidated=True` with the actual resolved basis for
    (sym, fiscal_year), per spec §3.1's "consolidated-first is a global
    rule, not a ratio-specific choice" - every one of these ~50 fetchers
    used to unconditionally request consolidated=True regardless of whether
    the company's Annual Report actually has consolidated statements;
    `tools.annual_report_financials._get_extracted_financials` already
    falls back to standalone internally when it's genuinely absent, but
    that fallback decision was never being fed back into the NEXT call for
    the same (sym, fiscal_year) - so every ratio for that company kept
    re-requesting (and re-discovering) consolidated=True from scratch.
    `select_statement_basis` caches its resolution per (symbol, fiscal_year)
    so this is one resolution shared by every ratio in a run, not one
    lookup per ratio. Defaults to True (consolidated-first) if the resolver
    itself fails - matches this module's pre-existing default, never a
    behaviour regression for a company the resolver can't reach."""
    try:
        from tools.statement_selector import select_statement_basis
        return select_statement_basis(sym, name, fiscal_year).selected_basis == "CONSOLIDATED"
    except Exception:
        return True


def _current_extraction_version():
    """Current Annual-Report shared-extraction/calculation logic version -
    reuses `tools.annual_report_financials._EXTRACTION_LOGIC_VERSION` (the
    SAME constant that already auto-invalidates every wrapper cache in that
    file via `_document_identity_tag`, and that gets bumped whenever a
    shared-extraction bug fix or a ratio's own formula changes).

    Passed to `try_db_ratio(..., extraction_version=...)` so a Supabase-
    precomputed row written under OLDER extraction/calculation logic is
    treated as a cache miss (falls through to a fresh live computation,
    which then writes back through `write_db_ratio` under the CURRENT
    version) rather than being served forever regardless of code fixes -
    the Supabase fast-path sits BEFORE this file's own `_doc_tag_for_cache`-
    based invalidation entirely, so without this, a formula/extraction fix
    could be fully correct in code and still show a stale result end-to-end
    for any company the precompute worker had already reached. Returns None
    (unversioned - unchanged prior behaviour) if the constant can't be
    imported for any reason, never raises."""
    try:
        from tools.annual_report_financials import _EXTRACTION_LOGIC_VERSION
        return _EXTRACTION_LOGIC_VERSION
    except Exception:
        return None


# Cache-key prefix -> ratio_no, for every ratio the DB fast-path covers (see
# tools/precompute_worker.py's RATIO_FETCHERS for the same mapping). Used by
# `_write_cache` below to mirror a freshly-computed LIVE "latest year" result
# into Supabase - the write-back half of try_db_ratio's read-back: once ANY
# request computes a company for real, every later request for it (by
# anyone) is instant, instead of only the background precompute job ever
# populating the database. Longest prefixes first so a short one (e.g. "de")
# can't accidentally prefix-match a longer one (e.g. "debtratio").
_RATIO_CACHE_PREFIXES = sorted([
    ("invturn", 1), ("recvturn", 3), ("payturn", 5), ("assetturn", 7),
    ("wcturn", 8), ("currentratio", 10), ("quickratio", 11), ("cashratio", 12),
    ("gpm", 14), ("opm", 15), ("npm", 16), ("roe", 18), ("roce", 19),
    ("debtratio", 21), ("de", 20), ("intcov", 22), ("finlev", 23),
    ("eps", 24), ("bvps", 25), ("sharesout", 100), ("revenueops", 26),
    ("dps", 27),
], key=lambda p: -len(p[0]))

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "nse_xbrl")
TTL = 12 * 3600
_lock = threading.Lock()


def _doc_tag_for_cache(symbol, to_date=None):
    """Document-identity tag for THIS module's own "latest" wrapper caches
    (keyed on `to_date or 'latest'`, not a fixed fiscal_year - these
    functions cache at the "which year is even latest" level, before they've
    internally probed which year actually computes). Companion to
    tools.annual_report_financials._document_identity_tag, which the SHARED
    extraction cache one layer below already uses - but this layer's cache
    check happens BEFORE that inner function is ever called, so a stale
    wrapper-level cache entry could still mask a freshly-uploaded document
    even after the inner layer became document-aware. Resolves the ACTUAL
    fiscal year this call would use (the explicit `to_date`'s year, or
    otherwise whatever `manual_cached_years` currently reports as newest -
    i.e. the same "walk newest-first" year every one of these wrapper
    functions already uses internally) and tags on that document's own
    identity. Falls back to "" (old symbol-only scoping) on any failure or
    when nothing is uploaded yet - never blocks a first-time fetch, and
    never raises."""
    try:
        from tools.annual_report_financials import _document_identity_tag
        year = None
        if to_date:
            try:
                year = int(str(to_date)[-4:])
            except Exception:
                year = None
        if year is None:
            from tools.ar_document_cache import manual_cached_years
            years = manual_cached_years(symbol)
            year = years[0] if years else None
        if year is None:
            return ""
        return _document_identity_tag(symbol, year)
    except Exception:
        return ""

# Manual Document Upload override - a user-uploaded XBRL filing, keyed by
# symbol, that fetch_filings()/_fetch_parsed() below check BEFORE the live
# NSE lookup. Every one of this module's fetch_* ratio functions already
# funnels through those two functions, so uploading a file here transparently
# feeds the entire existing ratio engine with no per-ratio changes. See
# tools/manual_document_pipeline.py for the upload/save side.
_MANUAL_XBRL_DIR = os.path.join(os.path.dirname(CACHE_DIR), "xbrl_manual")


def _manual_xbrl_path(symbol):
    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    return os.path.join(_MANUAL_XBRL_DIR, f"{sym}.xml")


def save_manual_xbrl(symbol, xml_text):
    """Persists a user-uploaded XBRL filing for `symbol`. Never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    os.makedirs(_MANUAL_XBRL_DIR, exist_ok=True)
    with open(_manual_xbrl_path(sym), "w", encoding="utf-8") as fh:
        fh.write(xml_text)


# --------------------------------------------------------------------------- #
# Manual Shareholding Pattern upload (Sr No 67/68's document source) - same
# save/read/parse shape as the Financial XBRL override above, kept separate
# since it's a distinct SEBI LODR filing type, not the Results/Statement
# XBRL. Uploaded via the same "Upload Documents -> Analyse" flow.
# --------------------------------------------------------------------------- #
_MANUAL_SHAREHOLDING_DIR = os.path.join(os.path.dirname(CACHE_DIR), "shareholding_manual")

# Real SEBI LODR Shareholding Pattern XBRL tag names, under the BSE
# `in-bse-shp` taxonomy - confirmed by direct inspection of an actual
# uploaded filing (ANURAS's Shareholding Pattern XBRL), not guessed. The
# original tag names here were guessed from the Ind-AS FINANCIAL-statement
# taxonomy's naming style and did not exist anywhere in the real SHP
# taxonomy at all, so every promoter-pledge/free-float lookup silently
# found nothing despite a genuinely valid, parseable file being uploaded.
# Multiple candidates kept per field (this file's existing "wide aliases"
# pattern) in case different filing years/versions vary slightly. A tag
# genuinely absent from the uploaded filing simply leaves that field None,
# not a fabricated 0.
_SHAREHOLDING_XBRL_TAGS = {
    "total_promoter_holding": ["NumberOfFullyPaidUpEquityShares", "NumberOfSharesUnderlyingOutstandingConvertibleSecurities"],
    "num_shares_pledged": ["NumberOfSharesEncumberedUnderPledged", "NumberOfSharesPledgedOrOtherwiseEncumberedByPromoter"],
    "total_shares": ["NumberOfFullyPaidUpEquityShares", "TotalNumberofSharesTotalVotingRights"],
    "institutional_holding": ["TotalSharesHeldByPublicInstitutions", "SharesHeldByInstitutions"],
    "public_holding": ["TotalSharesHeldByPublic", "SharesHeldByPublic"],
}
# Percentage-basis tags (already computed as a % in the filing itself,
# preferred over deriving a % from raw share counts when both a promoter-
# category context AND a total-entity context exist, since the raw
# NumberOfFullyPaidUpEquityShares tag above is reported once PER
# shareholder-category dimension, not just once for "promoter" vs "total" -
# the percentage tags are the more reliable cross-check).
_SHAREHOLDING_PCT_TAGS = {
    "pledge_pct": ["EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares"],
    "holding_pct": ["ShareholdingAsAPercentageOfTotalNumberOfShares"],
}


def _manual_shareholding_path(symbol):
    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    return os.path.join(_MANUAL_SHAREHOLDING_DIR, f"{sym}.xml")


def save_manual_shareholding(symbol, xml_text):
    """Persists a user-uploaded Shareholding Pattern filing for `symbol`. Never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    os.makedirs(_MANUAL_SHAREHOLDING_DIR, exist_ok=True)
    with open(_manual_shareholding_path(sym), "w", encoding="utf-8") as fh:
        fh.write(xml_text)


_SHP_NS = "in-bse-shp"

# Real BSE in-bse-shp taxonomy dimension member names for the two whole-
# category (non-dimensional-breakdown) contexts every Shareholding Pattern
# filing carries - confirmed by direct inspection of an actual uploaded
# filing. These facts live in DIMENSIONAL contexts (tagged with a
# CategoryOfShareholdersAxis explicitMember), which tools.nse_xbrl's shared
# _parse_xbrl()/_latest_instant_value() deliberately SKIP (they're built for
# the flat, non-dimensional financial-statement XBRL) - a dedicated,
# dimension-aware lookup is required here instead of reusing those.
_SHP_PROMOTER_MEMBER = "ShareholdingOfPromoterAndPromoterGroupMember"
_SHP_PUBLIC_MEMBER = "PublicShareholdingMember"


def _shp_context_ids_for_member(xml, member_name):
    """Every context id whose <xbrldi:explicitMember> names `member_name`
    (there is normally exactly one per filing, but be tolerant of more)."""
    ids = []
    for cid, body in re.findall(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', xml, re.S):
        if f":{member_name}<" in body:
            ids.append(cid)
    return ids


def _shp_fact_for_context(xml, tag, context_ids):
    for cid in context_ids:
        m = re.search(rf'<{_SHP_NS}:{tag}[^>]*contextRef="{re.escape(cid)}"[^>]*>([^<]*)</{_SHP_NS}:{tag}>', xml)
        if m:
            try:
                return float(m.group(1).strip())
            except ValueError:
                continue
    return None


def _shareholding_from_manual_upload(symbol):
    """Returns a dict shaped like tools.shareholding_scraper.fetch_shareholding()'s
    output ({promoter_holding_pct, promoter_pledge_pct, num_shares_pledged,
    total_promoter_holding, institutional_holding_pct, public_holding_pct,
    as_of_quarter, pledge_status}), sourced ONLY from the uploaded
    Shareholding Pattern XBRL - never live NSE/BSE. Returns None if no
    filing was uploaded for this symbol, or if the uploaded filing didn't
    tag enough facts to compute anything (never fabricates)."""
    sym = symbol.strip().upper().replace(".NS", "")
    p = _manual_shareholding_path(sym)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            xml = fh.read()
    except Exception as e:
        print(f"[nse_xbrl] manual shareholding filing unreadable for {sym}: {e}")
        return None

    promoter_ctx = _shp_context_ids_for_member(xml, _SHP_PROMOTER_MEMBER)
    public_ctx = _shp_context_ids_for_member(xml, _SHP_PUBLIC_MEMBER)

    total_promoter = _shp_fact_for_context(xml, "NumberOfFullyPaidUpEquityShares", promoter_ctx)
    pledged = _shp_fact_for_context(xml, "NumberOfSharesEncumberedUnderPledged", promoter_ctx)
    # This tag, reported WITHIN the promoter-category context, is already
    # pledged-shares as a percent of THAT category's own total (confirmed:
    # pledged / total_promoter on a real filing reproduces this figure
    # exactly) - i.e. already the approved formula's result, not a
    # different (company-wide) denominator.
    promoter_pledge_pct_direct = _shp_fact_for_context(
        xml, "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares", promoter_ctx)
    promoter_holding_pct_direct = _shp_fact_for_context(
        xml, "ShareholdingAsAPercentageOfTotalNumberOfShares", promoter_ctx)
    public_shares = _shp_fact_for_context(xml, "NumberOfFullyPaidUpEquityShares", public_ctx)
    public_holding_pct_direct = _shp_fact_for_context(
        xml, "ShareholdingAsAPercentageOfTotalNumberOfShares", public_ctx)

    if total_promoter is None and public_shares is None:
        return None  # nothing usable was tagged in the uploaded filing

    total_shares = (total_promoter or 0) + (public_shares or 0) if (total_promoter or public_shares) else None

    return {
        "promoter_holding_pct": round(promoter_holding_pct_direct * 100, 2) if promoter_holding_pct_direct is not None
            else (round(total_promoter / total_shares * 100, 2) if total_promoter and total_shares else None),
        "promoter_pledge_pct": round(promoter_pledge_pct_direct * 100, 2) if promoter_pledge_pct_direct is not None
            else (round(pledged / total_promoter * 100, 2) if pledged is not None and total_promoter else (0.0 if total_promoter else None)),
        "num_shares_pledged": pledged,
        "total_promoter_holding": total_promoter,
        "total_shares": total_shares,
        "institutional_holding_pct": None,  # not separately tagged in the in-bse-shp taxonomy at this level
        # Free Float % proxy (per existing, already-documented simplification):
        # Public shareholding % stands in for free float - no separate
        # locked-in-shares tag exists in this taxonomy to subtract.
        "public_holding_pct": round(public_holding_pct_direct * 100, 2) if public_holding_pct_direct is not None
            else (round(public_shares / total_shares * 100, 2) if public_shares and total_shares else None),
        "as_of_quarter": "as per uploaded Shareholding Pattern filing",
        "pledge_status": "ok" if pledged is not None else "zero",
    }


def _manual_override_filing(symbol):
    """Returns a synthetic single-filing dict (matching fetch_filings()'s
    normal shape) built from the uploaded XBRL's own end-date facts, or None
    if nothing was uploaded for this symbol. Never fabricates a date - reads
    it straight out of the filing's own contexts.

    The reporting period's END date is derived via `_annual_context()` (the
    SAME duration-context selector every other ratio in this file already
    relies on): the duration context whose RevenueFromOperations value is
    LARGEST is the full financial year (a quarter's revenue is always
    smaller). Taking max() over EVERY duration-context date in the filing
    (the previous approach) could pick up an unrelated later date some
    non-financial-period duration context happens to carry (e.g. a board-
    meeting/filing-date context), landing on a bogus reporting period."""
    sym = symbol.strip().upper().replace(".NS", "")
    p = _manual_xbrl_path(sym)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            xml = fh.read()
        contexts, facts = _parse_xbrl(xml)
        annual_cid = _annual_context(contexts, facts, probe_tag="RevenueFromOperations")
        if annual_cid is None:
            # Revenue tag absent/unusable - fall back to the largest duration
            # context (previous behaviour) rather than failing outright.
            durations = [c["date"] for c in contexts.values() if c["type"] == "duration" and not c["dim"]]
            to_date = max(durations) if durations else None
            print(f"[nse_xbrl] manual XBRL for {sym}: no RevenueFromOperations context found - "
                  f"fell back to max(duration dates) = {to_date}")
        else:
            to_date = contexts[annual_cid]["date"]
            start_date = None
            m = re.search(rf'<xbrli:context id="{re.escape(annual_cid)}">.*?<xbrli:startDate>([^<]+)</xbrli:startDate>', xml, re.S)
            if m:
                start_date = m.group(1).strip()
            print(f"[nse_xbrl] manual XBRL for {sym}: selected annual context '{annual_cid}' "
                  f"(start={start_date}, end={to_date}, consolidated=Non-Consolidated) as FY{to_date}")
        if not to_date:
            return None
        return {
            "to_date": to_date, "consolidated": "Non-Consolidated", "audited": "Audited",
            "relating_to": None, "taxonomy": "INDAS", "xbrl": f"manual-upload-xbrl://{sym}",
        }
    except Exception as e:
        print(f"[nse_xbrl] manual XBRL override unreadable for {sym}: {e}")
        return None

_RESULTS_API = ("https://www.nseindia.com/api/corporates-financial-results"
                "?index=equities&symbol={sym}&period={period}")
_NS = "in-bse-fin"  # every NSE Ind-AS / Banking result uses this fact namespace

# Companies whose business model has no inventory - Inventory Turnover is N/A by
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


def _mirror_to_db_if_ratio_key(key, payload):
    """If `key` matches one of this file's own ratio cache-key patterns
    (`<prefix>_<SYMBOL>_latest`) AND has enough shape to be worth storing
    (a real fiscal year via `selected_period`), write it into Supabase too.
    Never raises - see `write_db_ratio`'s own docstring for why."""
    if not isinstance(payload, dict) or not payload.get("selected_period"):
        return
    if not key.endswith("_latest"):
        return  # only "latest year" results are cached this way - an
                 # explicit historical-year request keys as "..._31-Mar-2023"
                 # and deliberately isn't mirrored (DB only ever holds "latest")
    for prefix, ratio_no in _RATIO_CACHE_PREFIXES:
        marker = f"{prefix}_"
        if key.startswith(marker):
            symbol = key[len(marker):-len("_latest")]
            if symbol:
                # Best-effort read of the ACTUAL basis this payload was
                # computed on, from the "FYxx (consolidated)"/"(standalone)"
                # tag several `fetch_X_from_annual_report` wrappers already
                # embed in `period` (e.g. annual_report_financials.py:8018)
                # - avoids re-hardcoding True here now that the underlying
                # basis is resolved per-company rather than assumed (see
                # `_resolved_consolidated`). Defaults to True (unchanged
                # prior behaviour) when the payload carries no such tag.
                period_text = str(payload.get("period") or "").lower()
                consolidated = "standalone" not in period_text
                write_db_ratio(symbol, ratio_no, payload, consolidated=consolidated)
            return


def _write_cache(key, payload):
    try:
        _mirror_to_db_if_ratio_key(key, payload)
    except Exception:
        pass
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
    manual = _manual_override_filing(sym)
    if manual is not None:
        return [manual]
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        # Manual document-analysis workflow: no uploaded XBRL for this
        # symbol - never reach the live NSE results API to fill the gap.
        return []
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
    dates - instead pick the duration context whose probe value (revenue) is the
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
    if xbrl_url.startswith("manual-upload-xbrl://"):
        sym = xbrl_url[len("manual-upload-xbrl://"):]
        p = _manual_xbrl_path(sym)
        if not os.path.exists(p):
            return None, None
        with open(p, "r", encoding="utf-8") as fh:
            return _parse_xbrl(fh.read())
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
        return to_date or "-"


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
        return None, "No Cost-of-materials / Purchases lines in the filing - not a goods business."
    # Numerator is Net Sales (Revenue from Operations) - the Annual Report's own
    # Inventory Turnover definition. COGS above is kept only as the goods-
    # business gate and a reference figure.
    rev_v = _fact_in_context(facts_c, "RevenueFromOperations", acid) if acid else None
    sales_cr = _to_cr(rev_v) if rev_v is not None else None
    if not sales_cr or sales_cr <= 0:
        return None, "Revenue from Operations not found in the annual XBRL filing - Net Sales is the Inventory Turnover numerator."

    # Denominator: average of the two consecutive year-end Inventories.
    inv_cur = _latest_instant_value(ctx_c, facts_c, "Inventories")
    inv_prev = _latest_instant_value(ctx_p, facts_p, "Inventories")
    if not inv_cur or not inv_prev or not inv_cur[1] or not inv_prev[1]:
        return None, "Inventory line not found (or zero) in one of the two annual balance sheets - not a goods business."
    inv_cur_cr, inv_prev_cr = _to_cr(inv_cur[1]), _to_cr(inv_prev[1])

    # ACCURACY FIX: NSE's annual XBRL only tags the CURRENT year-end balance
    # sheet - never a prior-year comparative. So the "prior year" figure above
    # comes from a DIFFERENT filing (that year's own annual XBRL), which is
    # wrong whenever the company restates prior-year comparatives (e.g. after a
    # merger/amalgamation - confirmed for Tata Steel FY24, which absorbed
    # Neelachal Ispat Nigam Ltd). The company's OWN current-year filing shows
    # the correctly RESTATED comparative; extract it (deterministically, from
    # PDF word positions - no LLM) and use it in place of the separate-filing
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
    ratio_raw = (sales_cr / avg_inv) if avg_inv else None
    ratio = round(ratio_raw, 2) if ratio_raw is not None else None

    note = ("Consolidated, audited - Cost of Goods Sold from NSE XBRL; prior-year "
            "Inventory is the company's own RESTATED comparative (verified against "
            "the filing), so both years are on the same reporting basis."
            if restated_note else
            "Consolidated, audited - computed from the company's own NSE XBRL result filings.")

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
        "value": ratio, "value_raw": ratio_raw, "unit": "x",
        "confidence": confidence,
        "estimated": False,
        "period": f"{_fy_label(cur['to_date'])} (consolidated)",
        "numerator": {"label": "Net Sales (Revenue from Operations)", "value_cr": round(sales_cr, 2),
                      "reference_cogs_cr": round(cogs, 2), "components": components},
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
    (None, reason) - never raises."""
    try:
        from tools.annual_report_financials import fetch_inventory_turnover_from_annual_report
        if target_year in ar_years:
            ar = fetch_inventory_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
        return None, "Not applicable - banking-taxonomy filing has no Inventory / Cost-of-materials lines."
    return _compute_pair(annuals[idx], annuals[idx + 1], sym=sym, name=name)


def fetch_inventory_turnover(symbol, name=None, to_date=None):
    """
    Inventory Turnover = Net Sales / Average Inventory (the Annual Report's own definition). PRIMARY source is the
    company's own Annual Report (per the Source Hierarchy - ranks above the
    quarterly/annual Reg-33 result filing): both years' figures sit in the SAME
    document, on the same reporting basis, and the statements extract cleanly
    (no jumbled-text reconstruction needed). Falls back to the NSE XBRL Reg-33
    filing (proven, but needs the restated-comparative patch - see
    bse_restated_inventory.py) only if the Annual Report path fails for that year.

    `to_date` selects which year-end to compute (e.g. '31-Mar-2024'); when it's
    explicit we compute exactly that year (N/A if it genuinely isn't published
    yet). When it's None (default load) we walk newest-to-oldest and return the
    FIRST year that actually computes - e.g. skip FY26 straight to FY25 if
    FY26's filing isn't out yet, rather than showing a blank "latest year".
    Always returns `available_periods` for the UI year-picker. Returns
    {'applicable': False} for lenders/no-inventory businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" - wraps `fetch_inventory_turnover_from_annual_report` (bumped
    # "_v2") which wraps `_get_extracted_financials` (bumped v19->v20 for
    # the missing "Changes in inventories" COGS component fix) - same
    # nested-cache-chain lesson as the EPS caches.
    ckey = f"invturn_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Inventory Turnover"}
    if to_date is None:
        db_row = try_db_ratio(sym, 1)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business with no inventory."}
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
    # business" the company is structurally a services/financial business -
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
# Receivables Turnover - Revenue from Operations ÷ Average Trade Receivables.
# Sourced from the Annual Report only (no NSE XBRL Reg-33 fallback yet - the
# Annual Report is the spec's #1-ranked source anyway, and it's already what
# Inventory Turnover reuses across ratios via the shared cached extraction).
# --------------------------------------------------------------------------- #
def fetch_receivables_turnover(symbol, name=None, to_date=None):
    """
    Receivables Turnover = Revenue from Operations ÷ Average Trade Receivables
    (Revenue from Operations used as a proxy for Net Credit Sales - Indian
    Annual Reports don't split cash vs. credit sales). Same year-selection
    behaviour as `fetch_inventory_turnover`: explicit `to_date` computes
    exactly that year; `to_date=None` walks newest-to-oldest and returns the
    first year that actually computes. Returns {'applicable': False} for
    lenders/financial businesses (receivables concept differs - loans/advances
    instead) - never a fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"recvturn_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Receivables Turnover"}
    if to_date is None:
        db_row = try_db_ratio(sym, 3)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(receivables concept differs - loans/advances instead)."}
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
        r = fetch_receivables_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        # `r` is spread regardless of applicability - an N/A result can still
        # carry real partial figures worth showing, not just a reason string.
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    # No year requested -> walk newest-to-oldest (capped, same rationale as
    # Inventory Turnover's cascade), return the first year that computes.
    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_receivables_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Payables Turnover - Purchases (a+b) ÷ Average Trade Payables. Sourced from
# the Annual Report only, same rationale as Receivables Turnover.
# --------------------------------------------------------------------------- #
def fetch_payables_turnover(symbol, name=None, to_date=None):
    """
    Payables Turnover = Purchases ÷ Average Trade Payables (Purchases = Cost
    of materials consumed + Purchases of stock-in-trade, falling back to
    COGS minus the inventory movement only if that split isn't available).
    Same year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"payturn_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Payables Turnover"}
    if to_date is None:
        db_row = try_db_ratio(sym, 5)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business with no trade payables."}
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
        r = fetch_payables_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        # `r` is spread regardless of applicability - an N/A result can still
        # carry real partial figures worth showing, not just a reason string.
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_payables_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Asset Turnover - Revenue from Operations ÷ Average Total Assets. Sourced
# from the Annual Report only, same rationale as Receivables/Payables Turnover.
# --------------------------------------------------------------------------- #
def fetch_asset_turnover(symbol, name=None, to_date=None):
    """
    Asset Turnover = Revenue from Operations ÷ Average Total Assets. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"assetturn_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Asset Turnover"}
    if to_date is None:
        db_row = try_db_ratio(sym, 7)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(asset base is fundamentally different - loans/investments, not operating assets)."}
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
        r = fetch_asset_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        # `r` is spread regardless of applicability - an N/A result can still
        # carry real partial figures worth showing, not just a reason string.
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_asset_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Fixed Asset Turnover (Sr No 30) - Revenue from Operations ÷ Average Net
# Fixed Assets. Sourced from the Annual Report only, same rationale as the
# other turnover ratios.
# --------------------------------------------------------------------------- #
def fetch_fixed_asset_turnover(symbol, name=None, to_date=None):
    """
    Fixed Asset Turnover = Revenue from Operations ÷ Average Net Fixed
    Assets. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"fixedassetturn_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Fixed Asset Turnover"}
    if to_date is None:
        db_row = try_db_ratio(sym, 30)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(minimal fixed assets; asset base is loans/investments, not PP&E)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_fixed_asset_turnover_from_annual_report)
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
        r = fetch_fixed_asset_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_fixed_asset_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Working Capital Turnover - Revenue from Operations ÷ Average Working
# Capital (Total Current Assets − Total Current Liabilities). Sourced from
# the Annual Report only, same rationale as the other turnover ratios.
# --------------------------------------------------------------------------- #
def fetch_working_capital_turnover(symbol, name=None, to_date=None):
    """
    Working Capital Turnover = Revenue from Operations ÷ Average Working
    Capital. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses, and also
    when Average Working Capital is zero/negative (per spec - never silently
    reports a sign-inverted or meaningless ratio). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"wcturn_v3_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Working Capital Turnover"}
    if to_date is None:
        db_row = try_db_ratio(sym, 8)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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

    # Note: `r` is spread in BOTH the applicable and N/A cases below - an N/A
    # result (e.g. negative Average Working Capital) still carries real
    # numerator/denominator figures worth showing, not just a reason string,
    # so those fields must survive into the final response either way.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_working_capital_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_working_capital_turnover_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Days Working Capital (Sr No 31) = (Average Working Capital ÷ Revenue from
# Operations) × 365 - the days-based expression of Working Capital Turnover
# (Sr No 8/26). Pure arithmetic reuse of the SAME two figures - its own
# small function (not a client-side derivation of Working Capital Turnover's
# endpoint) since that ratio's own N/A branch fires on Average Working
# Capital ≤ 0, which per spec is a VALID, often-favourable result here
# (supplier-funded working capital), never withheld.
# --------------------------------------------------------------------------- #
def fetch_days_working_capital(symbol, name=None, to_date=None):
    """
    Days Working Capital = (Average Working Capital ÷ Revenue from
    Operations) × 365. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses (same Current Assets/Liabilities concept
    mismatch as Working Capital Turnover), and when Revenue is zero/missing
    - but, unlike Working Capital Turnover, NEVER when Average Working
    Capital is negative (a real, valid signal, not withheld here). Cached;
    never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"dayswc_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Days Working Capital"}
    if to_date is None:
        db_row = try_db_ratio(sym, 31)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(current assets/liabilities concept differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_days_working_capital_from_annual_report)
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
        r = fetch_days_working_capital_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_days_working_capital_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Receivables-to-Payables Ratio (Sr No 32) = Trade Receivables ÷ Trade
# Payables, BOTH closing balance. Pure reuse of the SAME Trade Receivables/
# Trade Payables fields already validated for Receivables Turnover (Sr No 3)/
# Payables Turnover (Sr No 5). Sourced from the Annual Report only, same
# rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_receivables_to_payables_ratio(symbol, name=None, to_date=None):
    """
    Receivables-to-Payables Ratio = Trade Receivables ÷ Trade Payables
    (closing balance, current year only). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, and when Trade Payables is zero (undefined
    division) - but a ratio below 1x is a real, valid result, never
    withheld. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"rtop_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Receivables-to-Payables Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 32)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(no conventional Trade Receivables/Trade Payables cycle)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_receivables_to_payables_ratio_from_annual_report)
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
        r = fetch_receivables_to_payables_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_receivables_to_payables_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Net Debt/EBITDA (Sr No 33) = (Total Debt − Cash and Cash Equivalents) ÷
# EBITDA. Total Debt reuses Sr No 20's SHARED a+b+c protocol
# (`_compute_total_debt`); EBITDA is its OWN independent calculation (Sr No
# 93 - EBITDA-basis, NEVER Sr No 15's EBIT-basis Operating Profit Margin).
# Sourced from the Annual Report only, same rationale as the other ratios.
# --------------------------------------------------------------------------- #
def fetch_net_debt_to_ebitda(symbol, name=None, to_date=None, lease_basis="basis1"):
    """
    Net Debt/EBITDA = (Total Debt − Cash and Cash Equivalents) ÷ EBITDA. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses, when EBITDA is
    zero/negative, and when Net Debt is negative (a genuine "Net Cash"
    position, flagged via `net_cash: True` rather than reported as a
    spuriously low leverage multiple). `lease_basis` defaults to "basis1"
    (Lease Liabilities included in Total Debt, matching Sr No 20/21/29's own
    default) - pass "basis2" for the traditional ex-lease view. Cached;
    never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key: without it, a symbol with both a manually-uploaded
    # document and a live-fetchable one would share this cache key across
    # the manual-upload and automatic pipelines, leaking the manual-only
    # Direct Expenses EBITDA fix into the automatic pipeline's served
    # result, or vice versa.
    from tools.manual_mode import is_manual_mode
    ckey = (f"ndebitda_v3_{sym}_{to_date or 'latest'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Net Debt/EBITDA"}
    if to_date is None:
        db_row = try_db_ratio(sym, 33)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(operating-cost structure and debt concept differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_net_debt_to_ebitda_from_annual_report)
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
        r = fetch_net_debt_to_ebitda_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_net_debt_to_ebitda_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        # `applicable=False` here means two DIFFERENT things: a genuine
        # extraction failure (worth probing an older year for), or a real
        # "Net Cash" position (`net_cash: True` - Cash exceeds Total Debt,
        # so the ratio is correctly undefined, not a leverage multiple).
        # The latter is a definitive, correct answer for that year, not a
        # failure - treating it the same as a failure silently discarded
        # the CURRENT year's genuine Net Cash finding and fell back to an
        # OLDER year's real (and by now stale/less relevant) multiple
        # instead (confirmed on HUL: FY26 Net Cash was skipped in favour of
        # FY25's 0.45x). Both are accepted as a final result here.
        if r.get("applicable") or r.get("net_cash"):
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
# Debt Service Coverage Ratio (DSCR, Sr No 34) = EBITDA (Net Operating Income
# proxy, Sr No 93) ÷ Total Debt Service (Finance Costs + Principal Repayment
# of Borrowings, from the Cash Flow Statement's Financing Activities
# section). Sourced from the Annual Report only, same rationale as the
# other ratios above.
# --------------------------------------------------------------------------- #
def fetch_debt_service_coverage_ratio(symbol, name=None, to_date=None, lease_basis="basis1"):
    """
    Debt Service Coverage Ratio = EBITDA ÷ (Finance Costs + Principal
    Repayment of Borrowings [+ Lease Liabilities principal repayment under
    Basis 2]). Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses, and when
    Total Debt Service is zero (a genuinely debt-free company - per spec,
    not calculated rather than divided by zero). `lease_basis` defaults to
    "basis1" (lease principal repayment EXCLUDED from Total Debt Service,
    per Sr No 34's own spec - note this is the opposite direction from Sr
    No 20/33's Basis 1). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_service_coverage_ratio_
    # from_annual_report's own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"dscr_v5_{sym}_{to_date or 'latest'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Debt Service Coverage Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 34)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(operating-cost structure and debt-service concept differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_debt_service_coverage_ratio_from_annual_report)
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
        r = fetch_debt_service_coverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_debt_service_coverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
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
# Cash Flow Coverage Ratio (Sr No 35) = Net Cash Flow from Operating
# Activities ÷ Total Debt (Sr No 20's SHARED a+b+c protocol). A cash-based
# solvency check, more resistant to manipulation than EBIT/EBITDA-based
# leverage ratios since it uses real Cash Flow Statement movements. Sourced
# from the Annual Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_cash_flow_coverage_ratio(symbol, name=None, to_date=None, lease_basis="basis1"):
    """
    Cash Flow Coverage Ratio = Net Cash Flow from Operating Activities ÷
    Total Debt. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses, and when
    Total Debt is zero (a genuinely debt-free company - the ratio wouldn't
    be meaningful). `lease_basis` defaults to "basis1" (Lease Liabilities
    included in Total Debt, matching Sr No 20/21/29/33's own default) - pass
    "basis2" for the traditional ex-lease view. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_cash_flow_coverage_ratio_from_
    # annual_report's own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"cfcr_v5_{sym}_{to_date or 'latest'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Cash Flow Coverage Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 35)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(cash flow structure and debt concept differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_cash_flow_coverage_ratio_from_annual_report)
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
        r = fetch_cash_flow_coverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_cash_flow_coverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
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
# Free Cash Flow (FCF, Sr No 36) = Net Cash Flow from Operating Activities −
# net Capital Expenditure (Purchase of PP&E + Intangibles, net of disposal
# proceeds), all from the Cash Flow Statement. Sourced from the Annual
# Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_free_cash_flow(symbol, name=None, to_date=None):
    """
    Free Cash Flow = Net Cash Flow from Operating Activities − net Capital
    Expenditure. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses. A
    negative FCF is a real, valid result (e.g. a capex/growth investment
    phase) - never withheld. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"fcf_v4_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Free Cash Flow"}
    if to_date is None:
        db_row = try_db_ratio(sym, 36)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(cash flow/capex structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_free_cash_flow_from_annual_report)
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
        r = fetch_free_cash_flow_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_free_cash_flow_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# FCF Margin (Sr No 38) = Free Cash Flow (Sr No 36) ÷ Revenue from Operations
# (Sr No 3) - a cash-based counterpart to Net Profit Margin. Sourced from
# the Annual Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_fcf_margin(symbol, name=None, to_date=None):
    """
    FCF Margin = Free Cash Flow ÷ Revenue from Operations. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses, and when Revenue
    is zero/missing. A negative margin is a real, valid result (e.g. a
    growth/capex investment phase) - never withheld. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"fcfmargin_v4_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "FCF Margin"}
    if to_date is None:
        db_row = try_db_ratio(sym, 38)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(cash flow/capex structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_fcf_margin_from_annual_report)
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
        r = fetch_fcf_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_fcf_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Operating Cash Flow Ratio (Sr No 39) = Net Cash Flow from Operating
# Activities ÷ Total Current Liabilities (closing, reuse Sr No 10's
# denominator) - a stricter, cash-based liquidity test than the Current
# Ratio. Sourced from the Annual Report only, same rationale as the other
# ratios above.
# --------------------------------------------------------------------------- #
def fetch_operating_cash_flow_ratio(symbol, name=None, to_date=None):
    """
    Operating Cash Flow Ratio = Net Cash Flow from Operating Activities ÷
    Total Current Liabilities (closing balance, current year only). Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses, and when Total
    Current Liabilities is zero. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ocfratio_v4_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Operating Cash Flow Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 39)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(current liabilities/cash flow concept differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_operating_cash_flow_ratio_from_annual_report)
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
        r = fetch_operating_cash_flow_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_operating_cash_flow_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Capex Intensity (Sr No 40) = Capital Expenditure, net (Sr No 36's
# denominator component) ÷ Revenue from Operations (Sr No 3). Sourced from
# the Annual Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_capex_intensity(symbol, name=None, to_date=None):
    """
    Capex Intensity = Capital Expenditure (net) ÷ Revenue from Operations.
    Same year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses, and when Revenue
    is zero/missing. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_capex_intensity_from_annual_
    # report's own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"capexint_v6_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Capex Intensity"}
    if to_date is None:
        db_row = try_db_ratio(sym, 40)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(cash flow/capex structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_capex_intensity_from_annual_report)
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
        r = fetch_capex_intensity_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_capex_intensity_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# OCF/Net Profit (Sr No 41) = Net Cash Flow from Operating Activities ÷ Net
# Profit (owners-attributable, reuses Sr No 16's `pat` convention). Sourced
# from the Annual Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_ocf_to_net_profit(symbol, name=None, to_date=None):
    """
    OCF/Net Profit = Net Cash Flow from Operating Activities ÷ Net Profit
    (owners-attributable). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, and when Net Profit is zero/negative.
    Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"ocfnp_v5_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "OCF/Net Profit"}
    if to_date is None:
        db_row = try_db_ratio(sym, 41)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(cash flow/profit structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_ocf_to_net_profit_from_annual_report)
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
        r = fetch_ocf_to_net_profit_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_ocf_to_net_profit_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Return on Invested Capital (ROIC, Sr No 42) = NOPAT ÷ Invested Capital.
# Sourced from the Annual Report only, same rationale as the other ratios
# above.
# --------------------------------------------------------------------------- #
def fetch_roic(symbol, name=None, to_date=None, lease_basis="basis1"):
    """
    ROIC = NOPAT (EBIT taxed at the effective rate) ÷ Invested Capital (Total
    Debt + Total Equity − Cash, closing balance). Same year-selection
    behaviour as `fetch_inventory_turnover`. Returns {'applicable': False}
    for lenders/financial businesses, when Profit Before Tax is zero/
    negative, or when Invested Capital is zero/negative. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v3" - wraps `fetch_roic_from_annual_report` (bumped "_v3") which
    # wraps `_get_extracted_financials` (v24, tax_expense fix).
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"roic_v3_{sym}_{to_date or 'latest'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Return on Invested Capital (ROIC)"}
    if to_date is None:
        db_row = try_db_ratio(sym, 42)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(capital structure/return metrics differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_roic_from_annual_report)
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
        r = fetch_roic_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_roic_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
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
# Effective Tax Rate (Sr No 43) = Total Tax Expense ÷ Profit Before Tax.
# Sourced from the Annual Report only, same rationale as the other ratios
# above.
# --------------------------------------------------------------------------- #
def fetch_effective_tax_rate(symbol, name=None, to_date=None):
    """
    Effective Tax Rate = Total Tax Expense (Current + Deferred Tax) ÷ Profit
    Before Tax. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses, and
    when Profit Before Tax is zero/negative. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" - wraps `fetch_effective_tax_rate_from_annual_report` (bumped
    # "_v2") which wraps `_get_extracted_financials` (v24, tax_expense fix).
    ckey = f"etr_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Effective Tax Rate"}
    if to_date is None:
        db_row = try_db_ratio(sym, 43)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(tax structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_effective_tax_rate_from_annual_report)
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
        r = fetch_effective_tax_rate_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_effective_tax_rate_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Contribution Margin (Sr No 44) = (Revenue − Variable Costs) ÷ Revenue.
# KNOWN APPROXIMATION (see annual_report_financials.py's own docstring for
# the full scope decision) - "Variable Costs" here is only the raw-material
# COGS components, never a true MD&A-sourced fixed/variable split.
# --------------------------------------------------------------------------- #
def fetch_contribution_margin(symbol, name=None, to_date=None):
    """
    Contribution Margin = (Revenue − Variable Costs, PROXY) ÷ Revenue. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses, when Revenue is
    zero, or when the company has no goods-cost lines to approximate
    Variable Costs from (genuine services business). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"cm_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Contribution Margin"}
    if to_date is None:
        db_row = try_db_ratio(sym, 44)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(cost structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_contribution_margin_from_annual_report)
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
        r = fetch_contribution_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_contribution_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# EPS Growth Rate (Sr No 45) = (Current Year Basic EPS ÷ Prior Year Basic
# EPS) − 1. Sourced from the Annual Report only, same rationale as the
# other ratios above. UNLIKE most ratios in this file, per spec this is
# applicable to Banks/NBFC/Insurance too - no lender/financial exclusion.
# --------------------------------------------------------------------------- #
def fetch_eps_growth(symbol, name=None, to_date=None):
    """
    EPS Growth Rate = (Current Year Basic EPS ÷ Prior Year Basic EPS) − 1.
    Same year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} when Prior Year EPS is zero/negative (Not
    Meaningful). Applicable to every sector including Banks/NBFC/Insurance
    - no lender exclusion, unlike most ratios in this file. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v4" - a THIRD, outermost cache layer discovered in the same chain:
    # this function's own cache wraps `fetch_eps_growth_from_annual_report`,
    # whose cache (in tools/annual_report_financials.py, independently
    # bumped "_v2"->"_v3") wraps `_get_extracted_financials` (independently
    # bumped "v18"->"v19") - THREE nested caches, each of which must be
    # bumped whenever the innermost extraction logic changes, not just the
    # one whose own code literally changed. Confirmed real on ANURAS: after
    # fixing the v18->v19 and ar_epsgrowth v2->v3 layers, THIS outermost
    # "_v3" cache (written earlier in the same investigation, before those
    # inner fixes landed) was still serving the stale -38.93%/6.62/10.84
    # result. Generic lesson for this whole cache chain: a wrapper cache's
    # version must move in lockstep with every cache/function it calls
    # through to, not just its own diff.
    ckey = f"epsgrowth_v4_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "EPS Growth Rate"}
    if to_date is None:
        db_row = try_db_ratio(sym, 45)
        if db_row is not None:
            return {**base, **db_row}

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_eps_growth_from_annual_report)
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
        # Consolidated-first, matching `fetch_eps`'s policy (Sr No 24) and
        # the project-wide Consolidation Priority rule - EPS Growth must be
        # computed on the SAME basis as EPS itself, never Consolidated
        # current-year vs Standalone prior-year or vice versa. The existing
        # consolidated->standalone fallback inside `_get_extracted_financials_impl`
        # already handles a filer with no Consolidated statement at all.
        r = fetch_eps_growth_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        # Consolidated-first, matching `fetch_eps`'s policy (Sr No 24) and
        # the project-wide Consolidation Priority rule - EPS Growth must be
        # computed on the SAME basis as EPS itself, never Consolidated
        # current-year vs Standalone prior-year or vice versa. The existing
        # consolidated->standalone fallback inside `_get_extracted_financials_impl`
        # already handles a filer with no Consolidated statement at all.
        r = fetch_eps_growth_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Dividend Payout Ratio (Sr No 47) = Total Dividends Declared ÷ Net Profit.
# Sourced from the Annual Report only, same rationale as the other ratios
# above. Per spec, applicable to Banks/NBFC/Insurance too - no lender
# exclusion.
# --------------------------------------------------------------------------- #
def fetch_dividend_payout_ratio(symbol, name=None, to_date=None):
    """
    Dividend Payout Ratio = Total Dividends Declared (Dividend per Share ×
    Shares Outstanding) ÷ Net Profit. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} when Net
    Profit is zero/negative. Applicable to every sector including Banks/
    NBFC/Insurance - no lender exclusion, unlike most ratios in this file.
    Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"payout_v3_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Dividend Payout Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 47)
        if db_row is not None:
            return {**base, **db_row}

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_dividend_payout_ratio_from_annual_report)
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
        r = fetch_dividend_payout_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_dividend_payout_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Net Cash Flow from Operating Activities (standalone) - Price/Cash Flow's
# (Sr No 53) denominator, GROSS before capex. Sourced from the Annual
# Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_operating_cash_flow(symbol, name=None, to_date=None):
    """
    Net Cash Flow from Operating Activities, GROSS (before capex, never
    Free Cash Flow). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} when
    Operating Cash Flow is zero/negative. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ocf_only_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Net Cash Flow from Operating Activities"}
    if to_date is None:
        db_row = try_db_ratio(sym, 53)
        if db_row is not None:
            return {**base, **db_row}

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_operating_cash_flow_from_annual_report)
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
        r = fetch_operating_cash_flow_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_operating_cash_flow_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Altman Z-Score (Sr No 55) statement-side components - Market Cap is
# combined client-side (needs a live price). Sourced from the Annual
# Report only, same rationale as the other ratios above. Per spec, N/A for
# Banks/NBFC/Insurance - the standard lender exclusion applies here.
# --------------------------------------------------------------------------- #
def fetch_altman_z_score_components(symbol, name=None, to_date=None):
    """
    Altman Z-Score's five statement-side components (WC, TA, Retained
    Earnings, EBIT, Total Liabilities, Sales - Market Cap combined
    client-side). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for lenders/
    financial businesses, or when Total Assets/Total Liabilities is
    zero/negative. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"zscore_comp_v4_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Altman Z-Score"}
    if to_date is None:
        db_row = try_db_ratio(sym, 55)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business (balance sheet structure "
                         "differs fundamentally; use a sector-specific distress model instead)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_altman_z_score_components_from_annual_report)
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
        r = fetch_altman_z_score_components_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        if r.get("applicable"):
            r = _combine_altman_z_score(sym, r)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_altman_z_score_components_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        if r.get("applicable"):
            r = _combine_altman_z_score(sym, r)
            out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
            _write_cache(ckey, out)
            return out
        if first_reason is None:
            first_reason = r.get("reason")
    out = {**base, "applicable": False, "reason": first_reason or "Not applicable for this company.",
           "selected_period": f"31-Mar-{ar_years[0]}", "available_periods": available}
    _write_cache(ckey, out)
    return out


def _combine_altman_z_score(sym, statement_result):
    """Combines `fetch_altman_z_score_components_from_annual_report`'s five
    statement-side components with the sixth, market-derived one (Market
    Capitalisation, for the MktCap/TL term) into the final registry formula:

        Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA)

    Previously this combination step was never performed anywhere in the
    code path `run_fundamental_analysis` actually calls - the docstring on
    the statement-side function said Market Cap gets "combined client-side",
    but the frontend (frontend/src/views/DocumentAnalysis.jsx) only ever
    renders `r.inputs`/`r.value`/`r.status` generically; it never runs an
    Altman-specific calculation. The net effect: Sr No 55 always showed
    NOT_DISCLOSED regardless of whether every input was actually available
    (confirmed real on ANURAS: all 5 statement components plus a working
    live-price fetch were present, yet the ratio never computed a value).
    Completes it here instead, symmetric with how Strategy-C ratios
    (P/E, P/B, ...) already combine Annual-Report facts with live price -
    same "market_price" input-lineage convention (see `_row_from_nse_xbrl_out`'s
    handling of `numerator`/`denominator`, mirrored here via `numerator`).
    Never fabricates: if the live price or shares-outstanding fetch fails,
    returns the statement-side result UNCHANGED (still `applicable: True`
    but with no top-level "value" - i.e. genuinely NOT_DISCLOSED, since a
    live price genuinely isn't available, not because this code gave up)."""
    comps = statement_result.get("components") or {}
    ta = comps.get("total_assets_cr")
    tl = comps.get("total_liabilities_cr")
    wc = comps.get("working_capital_cr")
    re_ = comps.get("retained_earnings_cr")
    ebit = comps.get("ebit_cr")
    sales = comps.get("sales_cr")
    if not ta or not tl or ta <= 0 or tl <= 0 or None in (wc, re_, ebit, sales):
        return statement_result

    try:
        from tools.market_price import get_live_price
        bse_code = None
        try:
            from tools.supabase_client import get_client as _get_sb
            _rows = _get_sb().table("companies").select("bse_code").eq("symbol", sym).limit(1).execute().data
            bse_code = (_rows[0].get("bse_code") if _rows else None)
        except Exception:
            pass
        price = get_live_price(sym, bse_code=bse_code)
    except Exception:
        price = None
    shares_hit = fetch_shares_outstanding(sym)
    shares = shares_hit.get("value") if shares_hit else None
    if not price or not shares:
        return statement_result

    market_cap_cr = price["ltp"] * shares / 1e7  # shares x price (Rs) -> Rs Cr
    z = (1.2 * (wc / ta) + 1.4 * (re_ / ta) + 3.3 * (ebit / ta)
         + 0.6 * (market_cap_cr / tl) + 1.0 * (sales / ta))

    return {
        **statement_result,
        "value": round(z, 2), "unit": "score",
        "numerator": {
            "label": "Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA)",
            "value_cr": round(z, 2),
            "components": {
                "Working Capital": wc, "Total Assets": ta, "Retained Earnings": re_,
                "EBIT": ebit, "Total Liabilities": tl, "Sales": sales,
                "Market Capitalisation": round(market_cap_cr, 2),
            },
        },
        "market_price": {"name": "market_price", "value": round(price["ltp"], 2), "unit": "₹",
                          "source": f"Live quote ({price.get('source') or 'unknown source'})"},
    }


# --------------------------------------------------------------------------- #
# Piotroski F-Score (Sr No 56) - sum of nine binary year-over-year
# fundamental-strength tests. Sourced from the Annual Report only, same
# rationale as the other ratios above. Per spec, N/A for Banks/NBFC/
# Insurance - several component tests (Current Ratio, Gross Margin) don't
# apply to financial institutions.
# --------------------------------------------------------------------------- #
def fetch_piotroski_f_score(symbol, name=None, to_date=None):
    """
    Piotroski F-Score = sum of nine binary (1/0) year-over-year
    fundamental-strength tests (0-9 scale). Same year-selection behaviour
    as `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, or when two consecutive years of PAT/
    Total Assets/Operating Cash Flow aren't available. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"fscore_v3_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Piotroski F-Score"}
    if to_date is None:
        db_row = try_db_ratio(sym, 56)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business (several component tests, e.g. "
                         "Current Ratio and Gross Margin, don't apply to financial institutions)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_piotroski_f_score_from_annual_report)
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
        r = fetch_piotroski_f_score_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_piotroski_f_score_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Beneish M-Score (Sr No 57) - fixed-weight linear combination of eight
# year-over-year index variables. Sourced from the Annual Report only,
# same rationale as the other ratios above. Per spec, N/A for Banks/NBFC/
# Insurance - the model was calibrated on non-financial companies.
# --------------------------------------------------------------------------- #
def fetch_beneish_m_score(symbol, name=None, to_date=None):
    """
    Beneish M-Score = an 8-variable earnings-manipulation detection
    composite. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses, or
    when two consecutive years of complete data aren't available for any
    of the eight required variables. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"mscore_v3_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Beneish M-Score"}
    if to_date is None:
        db_row = try_db_ratio(sym, 57)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business (the model was calibrated on "
                         "non-financial companies)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_beneish_m_score_from_annual_report)
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
        r = fetch_beneish_m_score_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_beneish_m_score_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Net Interest Margin (Sr No 58) = (Interest Income − Interest Expense) ÷
# Average Interest-Earning Assets. The FIRST ratio in this suite that is
# applicable ONLY to Banks/NBFC (the inverse of every prior ratio's
# lender exclusion) - sourced from a Bank/NBFC's own RBI-format Annual
# Report via the new `_extract_bank_from_pdf` parser.
# --------------------------------------------------------------------------- #
def fetch_net_interest_margin(symbol, name=None, to_date=None):
    """
    Net Interest Margin = (Interest Income − Interest Expense) ÷ Average
    Interest-Earning Assets. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    non-financial companies - this ratio applies ONLY to Banks/NBFCs, the
    inverse of the standard lender exclusion. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"nim_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Net Interest Margin"}
    if to_date is None:
        db_row = try_db_ratio(sym, 58)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if not any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - Net Interest Margin is specific to lending institutions (Banks/"
                         "NBFCs); this company's balance sheet structure doesn't fit the interest-spread "
                         "model."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_net_interest_margin_from_annual_report)
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
        r = fetch_net_interest_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_net_interest_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# CASA Ratio (Sr No 59) = (Demand Deposits + Savings Bank Deposits) ÷
# Total Deposits. Applicable to BANKS ONLY, narrower than Net Interest
# Margin's Bank+NBFC scope - per spec, NBFCs typically don't take retail
# deposits, so this ratio isn't meaningful for them even though NIM is.
# --------------------------------------------------------------------------- #
def fetch_casa_ratio(symbol, name=None, to_date=None):
    """
    CASA Ratio = (Demand Deposits + Savings Bank Deposits) ÷ Total
    Deposits. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for non-bank companies (including
    NBFCs, unlike Net Interest Margin's broader Bank+NBFC scope) - or
    when Total Deposits is zero. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"casa_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "CASA Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 59)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if "bank" not in nm:
        out = {**base, "applicable": False,
               "reason": "Not applicable - CASA Ratio applies specifically to Banks with a retail deposit "
                         "franchise; this company doesn't take retail deposits (e.g. an NBFC or a "
                         "non-financial business)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_casa_ratio_from_annual_report)
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
        r = fetch_casa_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_casa_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Gross NPA % (Sr No 60) = Gross Non-Performing Assets ÷ Gross Advances.
# Applicable to Banks/NBFC, same scope as Net Interest Margin (Sr No 58) -
# broader than CASA Ratio's Banks-only scope, since NBFCs have loan books
# and asset-quality risk too, even without a retail deposit franchise.
# --------------------------------------------------------------------------- #
def fetch_gross_npa_pct(symbol, name=None, to_date=None):
    """
    Gross NPA % = Gross Non-Performing Assets ÷ Gross Advances. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for non-financial companies (this ratio applies
    ONLY to Banks/NBFCs), or when Gross Advances is zero. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"gnpa_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Gross NPA %"}
    if to_date is None:
        db_row = try_db_ratio(sym, 60)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if not any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - Gross NPA % is specific to lending institutions (Banks/NBFCs) with "
                         "a loan book; this company's balance sheet structure doesn't fit the asset-quality "
                         "model."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_gross_npa_pct_from_annual_report)
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
        r = fetch_gross_npa_pct_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_gross_npa_pct_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Net NPA % (Sr No 61) = Net Non-Performing Assets ÷ Net Advances. Same
# Bank/NBFC applicability scope as Gross NPA % (Sr No 60).
# --------------------------------------------------------------------------- #
def fetch_net_npa_pct(symbol, name=None, to_date=None):
    """
    Net NPA % = Net Non-Performing Assets ÷ Net Advances. Same year-
    selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for non-financial companies (this ratio applies
    ONLY to Banks/NBFCs), or when Net Advances is zero. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"nnpa_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Net NPA %"}
    if to_date is None:
        db_row = try_db_ratio(sym, 61)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if not any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - Net NPA % is specific to lending institutions (Banks/NBFCs) with a "
                         "loan book; this company's balance sheet structure doesn't fit the asset-quality "
                         "model."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_net_npa_pct_from_annual_report)
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
        r = fetch_net_npa_pct_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_net_npa_pct_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Capital Adequacy Ratio / CRAR (Sr No 63) = (Tier I + Tier II Capital) ÷
# Risk-Weighted Assets. Same Bank+NBFC applicability scope as Net Interest
# Margin/Gross NPA %.
# --------------------------------------------------------------------------- #
def fetch_capital_adequacy_ratio(symbol, name=None, to_date=None):
    """
    Capital Adequacy Ratio / CRAR = (Tier I + Tier II Capital) ÷ Risk-
    Weighted Assets (falls back to a directly-disclosed CRAR % when the
    individual capital tiers/RWA aren't separately found). Same year-
    selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for non-financial companies. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"crar_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Capital Adequacy Ratio (CRAR)"}
    if to_date is None:
        db_row = try_db_ratio(sym, 63)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if not any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - Capital Adequacy Ratio is specific to lending institutions (Banks/"
                         "NBFCs) subject to Basel III capital norms."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_capital_adequacy_ratio_from_annual_report)
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
        r = fetch_capital_adequacy_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_capital_adequacy_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Cost-to-Income Ratio (Sr No 65) = Operating Expenses ÷ (Net Interest
# Income + Other Income). Same Bank+NBFC applicability scope as Net
# Interest Margin/Gross NPA %.
# --------------------------------------------------------------------------- #
def fetch_cost_to_income_ratio(symbol, name=None, to_date=None):
    """
    Cost-to-Income Ratio = Operating Expenses (Employee Cost + Other
    Operating Expenses) ÷ (Net Interest Income + Other Income). Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for non-financial companies, or when the income
    base is zero/negative. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"cir_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Cost-to-Income Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 65)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if not any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - Cost-to-Income Ratio is specific to lending institutions (Banks/"
                         "NBFCs); use Operating Profit Margin for non-financial companies instead."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_cost_to_income_ratio_from_annual_report)
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
        r = fetch_cost_to_income_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_cost_to_income_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Beta (Sr No 66) = Covariance(Stock Returns, Market Returns) / Variance
# (Market Returns) - the FIRST ratio in this suite not derived from
# financial statements at all. Purely a market-data/statistical
# computation over historical price series (weekly closes, ~2-year
# lookback per spec's own guidance for less-liquid Indian mid/small-caps),
# no Annual Report/fiscal-year concept applies here at all, unlike every
# other ratio in this file. Benchmark index: Nifty 50 (^NSEI on
# yfinance - this codebase's existing convention for historical closes,
# already used in agent/stock_agent.py's `_next_month_price` and
# tools/angel_scraper.py's P/E-band builder, just never for an INDEX
# ticker before).
# --------------------------------------------------------------------------- #
def fetch_beta(symbol, name=None, to_date=None):
    """
    Beta = Cov(stock weekly returns, Nifty 50 weekly returns) / Var(Nifty
    50 weekly returns), over a trailing 2-year window. `to_date` is
    accepted for signature consistency with every other `fetch_X` in this
    file but IGNORED - Beta always uses the current trailing window, since
    it has no fiscal-year/Annual-Report concept to select a period from
    (there is no "available_periods" list for this ratio).

    Per spec, N/A / flagged unreliable if fewer than ~1 year of aligned
    weekly returns are available (newly-listed/IPO stock, or a data
    fetch failure). Confidence: 1.0 for a full ~2-year window (~100+
    weekly points), 0.8 for a shorter window (~26-99 points, higher
    standard error per spec's own tiering), 0.4 for a very thin window
    (still >= the ~1-year N/A floor, but close to it).

    Cached 7 days (Beta is a slow-moving statistic - no need to recompute
    on every request). Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"beta_{sym}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Beta"}
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        # Beta requires a multi-year historical price series - never
        # derivable from an uploaded Annual Report/XBRL, nor from a single
        # Angel One live price. Never fabricated; never a live yfinance
        # call in this workflow.
        return {**base, "applicable": False, "status": "insufficient_data",
                "reason": "Beta requires a multi-year historical price series, which is not derivable "
                          "from an uploaded Annual Report/XBRL or a single live market price."}
    db_row = try_db_ratio(sym, 66)
    if db_row is not None:
        return {**base, **db_row}

    try:
        from tools.yf_cache import cached_history
        stock_hist = cached_history(f"{sym}.NS", period="2y", interval="1wk")
        index_hist = cached_history("^NSEI", period="2y", interval="1wk")
    except Exception as e:
        print(f"[nse_xbrl] Beta history fetch failed for {sym}: {e}")
        return {**base, "applicable": False,
                "reason": "Could not fetch historical price data right now - please try again in a moment."}

    if stock_hist is None or stock_hist.empty or index_hist is None or index_hist.empty:
        out = {**base, "applicable": False,
               "reason": "No historical price data available - likely a newly-listed stock with "
                         "insufficient trading history."}
        _write_cache(ckey, out)
        return out

    try:
        import pandas as pd
        # Inner-join on trading week (yfinance's own DatetimeIndex, timezone-
        # normalised) so both series cover EXACTLY the same dates - a
        # misalignment here would silently distort the regression, per
        # spec's own warning.
        stock_close = stock_hist["Close"].copy()
        index_close = index_hist["Close"].copy()
        stock_close.index = stock_close.index.tz_localize(None)
        index_close.index = index_close.index.tz_localize(None)
        aligned = pd.concat([stock_close, index_close], axis=1, join="inner")
        aligned.columns = ["stock", "index"]
        returns = aligned.pct_change().dropna()
    except Exception as e:
        print(f"[nse_xbrl] Beta alignment/return calc failed for {sym}: {e}")
        return {**base, "applicable": False,
                "reason": "Something went wrong computing this ratio - please try again."}

    n_points = len(returns)
    # Per spec, N/A if fewer than ~1 year of trading history - at weekly
    # frequency that's roughly 52 aligned return points.
    if n_points < 52:
        out = {**base, "applicable": False,
               "reason": f"Only {n_points} weeks of aligned trading history found - fewer than the "
                         "~1-year minimum needed for a reliable Beta (newly-listed stock or an extremely "
                         "illiquid one)."}
        _write_cache(ckey, out)
        return out

    import numpy as np
    stock_returns = returns["stock"].to_numpy()
    index_returns = returns["index"].to_numpy()
    cov = np.cov(stock_returns, index_returns, ddof=1)[0][1]
    var = np.var(index_returns, ddof=1)
    if var == 0:
        out = {**base, "applicable": False, "reason": "Benchmark index return variance is zero over this "
                                                        "window - Beta is undefined."}
        _write_cache(ckey, out)
        return out

    beta = round(cov / var, 2)
    confidence = 1.0 if n_points >= 100 else (0.8 if n_points >= 52 else 0.4)

    start_date = returns.index.min().strftime("%d-%b-%Y")
    end_date = returns.index.max().strftime("%d-%b-%Y")

    out = {
        **base,
        "applicable": True,
        "value": beta, "unit": "",
        "confidence": confidence,
        "estimated": confidence < 1.0,
        "period": f"Weekly returns, {start_date} to {end_date} ({n_points} points)",
        "numerator": {"label": "Covariance(Stock Returns, Nifty 50 Returns)", "value_cr": round(cov, 6)},
        "denominator": {"label": "Variance(Nifty 50 Returns)", "value_cr": round(var, 6)},
        "sources": [{"url": "https://finance.yahoo.com/quote/" + sym + ".NS/history",
                     "label": f"{sym}.NS Historical Prices ↗"},
                    {"url": "https://finance.yahoo.com/quote/%5ENSEI/history",
                     "label": "Nifty 50 (^NSEI) Historical Prices ↗"}],
        "note": "Purely a market-data/statistical computation - NOT derived from financial statements, "
                "unaffected by Consolidated/Standalone reporting. Computed via weekly closing-price returns "
                "over a trailing 2-year window against the Nifty 50 (^NSEI) benchmark. A backward-looking "
                "historical measure, not a forecast - it can shift materially going forward. Cross-check "
                "against the qualitative risk profile of the sector (e.g. a debt-free FMCG company showing "
                "Beta > 1.5 warrants a data-quality check).",
    }
    _write_cache(ckey, out)
    return out


# --------------------------------------------------------------------------- #
# Promoter Pledge % (Sr No 67) = Pledged Promoter Shares ÷ Total Promoter
# Shareholding. Sourced from the quarterly SEBI Shareholding Pattern
# disclosure (BSE/NSE), NOT the Annual Report's financial statements --
# reuses `tools/shareholding_scraper.py`'s existing `fetch_shareholding()`
# (already built for the F-11 promoter-pledge feature elsewhere in this
# app) rather than re-scraping NSE's corporate-pledgedata endpoint from
# scratch. No fiscal-year concept applies here either (like Beta,
# Sr No 66) -- this is always "as of the most recent quarterly filing".
# --------------------------------------------------------------------------- #
def fetch_promoter_pledge_pct(symbol, name=None, to_date=None):
    """
    Promoter Pledge % = Number of Promoter Shares Pledged / Total Number
    of Promoter Shares Held, from the most recent SEBI Shareholding
    Pattern filing. `to_date` is accepted for signature consistency but
    IGNORED -- always the latest quarter, per spec's own "do not use a
    stale figure" instruction.

    Per spec, this is a FLAG (not a mathematical N/A) when Total Promoter
    Shareholding = 0 -- a professionally-managed company with no promoter/
    founder holding, where pledge simply doesn't apply to the ownership
    structure, distinct from a genuine data-fetch failure.

    Confidence: 1.0 when NSE's own pledge endpoint returned a real,
    explicit disclosure ("ok"); 0.95 when NSE explicitly listed no pledge
    for this scrip (NSE only lists pledged scrips at all, so absence is a
    real, high-confidence 0%, not a guess); 0.6 when NSE's endpoint
    couldn't be reached at all and a 0% is merely ASSUMED, per
    `shareholding_scraper.py`'s own `pledge_status` flag -- flagged
    explicitly as "Assumed" in that case, never silently presented at the
    same confidence as a confirmed 0%.

    Cached via `shareholding_scraper.py`'s own 12-hour pledge-data cache
    (pledge updates quarterly, so this is deliberately a short TTL relative
    to the Annual-Report ratios' 90-day cache). Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    base = {"symbol": sym, "ratio_name": "Promoter Pledge %"}

    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        sh = _shareholding_from_manual_upload(sym)
        if sh is None:
            return {**base, "applicable": False, "status": "not_disclosed",
                    "reason": "Shareholding Pattern filing not uploaded (or didn't contain a usable "
                              "Promoter Pledge disclosure) - upload it to compute this ratio."}
    else:
        try:
            from tools.shareholding_scraper import fetch_shareholding
            sh = fetch_shareholding(sym, name)
        except Exception as e:
            print(f"[nse_xbrl] Promoter Pledge % fetch failed for {sym}: {e}")
            return {**base, "applicable": False,
                    "reason": "Could not fetch the Shareholding Pattern filing right now - please try again."}

    promoter_holding_pct = sh.get("promoter_holding_pct")
    if promoter_holding_pct is None or promoter_holding_pct == 0:
        return {**base, "applicable": False,
                "reason": "No promoter/founder shareholding on record - this appears to be a "
                          "professionally-managed company with no promoter group, so Promoter Pledge % "
                          "doesn't apply to its ownership structure."}

    pledge_pct = sh.get("promoter_pledge_pct")
    if pledge_pct is None:
        return {**base, "applicable": False,
                "reason": "Could not find a Promoter Pledge disclosure in the Shareholding Pattern filing."}

    pledge_status = sh.get("pledge_status")
    confidence = 1.0 if pledge_status == "ok" else (0.95 if pledge_status == "zero" else 0.6)
    num_shares_pledged = sh.get("num_shares_pledged")
    total_promoter_shares = sh.get("total_promoter_holding")
    # Per spec, Promoter Pledge % = Pledged Promoter Shares / Total PROMOTER
    # Shares -- but NSE's own `percSharesPledged` field (what `pledge_pct`
    # holds) is actually pledged shares as a percent of the company's
    # TOTAL ISSUED shares, a different, smaller denominator (confirmed on
    # Gopal Snacks: NSE's raw field gives 11.66%, using num_shares_pledged /
    # total_issued_shares; recomputing against the actual Total Promoter
    # Shareholding count gives the spec-correct 14.32% -- materially
    # different since promoter holding is always < 100% of the company).
    # Recompute locally whenever both raw share counts are available
    # (matches the numerator/denominator now shown in the breakdown);
    # only fall back to NSE's own pre-computed percentage when the raw
    # counts aren't both present (e.g. a "zero" pledge status with no
    # promoter-holding count returned).
    if num_shares_pledged is not None and total_promoter_shares:
        pledge_pct = round((num_shares_pledged / total_promoter_shares) * 100, 2)

    out = {
        **base,
        "applicable": True,
        "value": round(pledge_pct, 2), "unit": "%",
        "confidence": confidence,
        "estimated": confidence < 1.0,
        "assumed_zero": pledge_status == "assumed_zero",
        "period": sh.get("as_of_quarter") or "most recent quarter",
        "numerator": {"label": "Pledged Promoter Shares", "value_cr": num_shares_pledged},
        "denominator": {"label": "Total Promoter Shareholding (shares)",
                         "value_cr": total_promoter_shares},
        "sources": [{"url": "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data",
                     "label": "NSE Shareholding Pattern ↗"}],
        "note": ("From the most recent SEBI Shareholding Pattern filing (BSE/NSE), a governance/risk "
                 "disclosure, not an accounting figure from the Annual Report. Pledged shares can be "
                 "forcibly sold by lenders if the share price falls sharply and margin/collateral calls are "
                 "triggered - a rising trend over consecutive quarters, especially alongside a declining "
                 "share price, is a compounding governance-risk signal worth flagging explicitly."
                 if pledge_status != "assumed_zero" else
                 "NSE's pledge endpoint could not be reached for a live check this time, so 0% is ASSUMED "
                 "(NSE only lists scrips with an actual pledge on record, so absence usually does mean "
                 "zero) rather than confirmed - flagged with reduced confidence."),
    }
    return out


# --------------------------------------------------------------------------- #
# Free Float % (Sr No 68) = (Total Shares − Promoter Holding − Locked-in
# Shares) ÷ Total Shares. Sourced from the SAME SEBI Shareholding Pattern
# disclosure as Promoter Pledge % (Sr No 67) -- reuses
# `shareholding_scraper.fetch_shareholding()` again, no separate fetch.
# No fiscal-year concept applies (like Sr No 66/67) -- always the latest
# quarter.
# --------------------------------------------------------------------------- #
def fetch_free_float_pct(symbol, name=None, to_date=None):
    """
    Free Float % = (Total Shares − Promoter Holding − Locked-in Shares) ÷
    Total Shares. `to_date` accepted for signature consistency but
    IGNORED -- always the latest quarter.

    KNOWN, DISCLOSED SIMPLIFICATION (matches spec's own 0.8-confidence
    fallback tier): this codebase's Shareholding Pattern data
    (`shareholding_scraper.py`) exposes Promoter/Institutional/Public
    percentages, but no SEPARATE "locked-in/non-tradeable shares"
    category (e.g. employee-trust lock-ins, government holdings, shares
    under litigation) beyond the Promoter/FII/DII/Public split already
    available. Free Float here is therefore computed as
    `100% - Promoter Holding %` -- per spec's own explicit warning, this
    is a PROXY, not the more granular figure a dedicated index-methodology
    document would give, and is flagged at confidence 0.8 rather than 1.0
    accordingly, never presented as a precise index-eligibility figure.

    Per spec, flag (not error) if Total Shares Outstanding is unknown
    (i.e. Promoter Holding % itself couldn't be sourced) -- same
    professionally-managed-company edge case as Sr No 67, though for Free
    Float that case actually means ~100% free float (no promoter lock-in
    at all), not N/A -- handled explicitly below, distinct from Sr No 67's
    own "not applicable" branch for that same input.

    Cached via `shareholding_scraper.py`'s own pledge/shareholding cache.
    Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    base = {"symbol": sym, "ratio_name": "Free Float %"}

    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        sh = _shareholding_from_manual_upload(sym)
        if sh is None:
            return {**base, "applicable": False, "status": "not_disclosed",
                    "reason": "Shareholding Pattern filing not uploaded (or didn't contain a usable "
                              "shareholding breakdown) - upload it to compute this ratio."}
    else:
        try:
            from tools.shareholding_scraper import fetch_shareholding
            sh = fetch_shareholding(sym, name)
        except Exception as e:
            print(f"[nse_xbrl] Free Float % fetch failed for {sym}: {e}")
            return {**base, "applicable": False,
                    "reason": "Could not fetch the Shareholding Pattern filing right now - please try again."}

    promoter_holding_pct = sh.get("promoter_holding_pct")
    institutional_pct = sh.get("institutional_holding_pct")
    public_pct = sh.get("public_holding_pct")

    if promoter_holding_pct is None:
        # No promoter shareholding on record at all -- per spec, Free Float
        # is genuinely ~100% for a professionally-managed company with no
        # promoter group (distinct from Sr No 67's "not applicable" for
        # this same input -- pledge genuinely doesn't apply there, but
        # Free Float is a real, computable 100% here).
        out = {
            **base,
            "applicable": True,
            "value": 100.0, "unit": "%",
            "confidence": 0.8,
            "estimated": True,
            "period": sh.get("as_of_quarter") or "most recent quarter",
            "numerator": {"label": "Total Shares − Promoter Holding (0%, none on record)",
                          "value_cr": 100.0},
            "denominator": {"label": "Total Shares Outstanding", "value_cr": 100.0},
            "sources": [{"url": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}",
                         "label": "NSE Shareholding Pattern ↗"}],
            "note": "No promoter/founder shareholding was found on record -- this appears to be a "
                    "professionally-managed company with no promoter group, so Free Float is effectively "
                    "the full share count. Computed as 100% − Promoter Holding % (a proxy for the full "
                    "Free Float definition, which would also net out any separately-disclosed locked-in "
                    "categories not captured here), hence the reduced confidence.",
        }
        return out

    free_float_pct = round(max(100.0 - promoter_holding_pct, 0.0), 2)

    out = {
        **base,
        "applicable": True,
        "value": free_float_pct, "unit": "%",
        "confidence": 0.8,
        "estimated": True,
        "period": sh.get("as_of_quarter") or "most recent quarter",
        "numerator": {
            "label": "Total Shares − Promoter Holding (proxy for Free Float)",
            "value_cr": free_float_pct,
            "components": {
                "Institutional Holding (FII + DII)": institutional_pct,
                "Public Holding": public_pct,
            },
        },
        "denominator": {"label": "Total Shares Outstanding", "value_cr": 100.0},
        "sources": [{"url": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}",
                     "label": "NSE Shareholding Pattern ↗"}],
        "note": "From the most recent SEBI Shareholding Pattern filing (BSE/NSE) - computed as 100% − "
                "Promoter Holding %, a PROXY for the full Free Float definition (Total Shares − Promoter "
                "Holding − Locked-in/Non-Tradeable Shares), since this codebase's data does not separately "
                "disclose locked-in categories (employee-trust lock-ins, government holdings, litigation-"
                "held shares) beyond the Promoter/Institutional/Public split - hence the reduced confidence. "
                "Determines both trading liquidity and index eligibility/weighting (major indices use "
                "free-float market capitalisation, not total market capitalisation).",
    }
    return out


# --------------------------------------------------------------------------- #
# Current Ratio - Total Current Assets ÷ Total Current Liabilities, closing
# balance only (point-in-time, not averaged). Sourced from the Annual Report
# only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_current_ratio(symbol, name=None, to_date=None):
    """
    Current Ratio = Total Current Assets ÷ Total Current Liabilities (closing
    balance, current year only). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses - never a fabricated number. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_current_ratio_from_annual_report's
    # own cache key: `_doc_tag_for_cache` keys off on-disk document
    # existence alone, not calling mode, so without this suffix a symbol
    # with both a manually-uploaded document and a live-fetchable one would
    # share this cache key across the manual-upload and automatic
    # pipelines. Never let that cross-contaminate.
    from tools.manual_mode import is_manual_mode
    ckey = (f"currentratio_v4_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Current Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 10)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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
        r = fetch_current_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_current_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Quick Ratio - (Total Current Assets − Inventories) ÷ Total Current
# Liabilities, closing balance only (point-in-time, not averaged). Sourced
# from the Annual Report only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_quick_ratio(symbol, name=None, to_date=None):
    """
    Quick Ratio = (Total Current Assets − Inventories) ÷ Total Current
    Liabilities (closing balance, current year only). Same year-selection
    behaviour as `fetch_inventory_turnover`. Returns {'applicable': False}
    for lenders/financial businesses - never a fabricated number. Cached;
    never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" - wraps `fetch_quick_ratio_from_annual_report` (bumped "_v3" for
    # the new `line_items` breakdown) and must move with it.
    ckey = f"quickratio_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Quick Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 11)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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
        r = fetch_quick_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_quick_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Cash Ratio - Cash and Cash Equivalents ÷ Total Current Liabilities, closing
# balance only (point-in-time, not averaged). Sourced from the Annual Report
# only, same rationale as the other ratios above.
# --------------------------------------------------------------------------- #
def fetch_cash_ratio(symbol, name=None, to_date=None):
    """
    Cash Ratio = Cash and Cash Equivalents ÷ Total Current Liabilities
    (closing balance, current year only). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses - never a fabricated number. Cached; never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_cash_ratio_from_annual_report's
    # own cache key: `_doc_tag_for_cache` keys off on-disk document
    # existence alone, not calling mode, so without this suffix a symbol
    # with both a manually-uploaded document and a live-fetchable one would
    # share this cache key across the manual-upload and automatic
    # pipelines, leaking the manual-only 3-column Balance Sheet fix into
    # the automatic pipeline's served result (or vice versa).
    from tools.manual_mode import is_manual_mode
    ckey = (f"cashratio_v5_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Cash Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 12)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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
        r = fetch_cash_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_cash_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Gross Profit Margin - (Revenue − COGS) ÷ Revenue, reusing the same COGS
# components validated for Inventory Turnover. Sourced from the Annual Report
# only, same rationale as Asset/Working Capital Turnover.
# --------------------------------------------------------------------------- #
def fetch_gross_profit_margin(symbol, name=None, to_date=None):
    """
    Gross Profit Margin = (Revenue from Operations − COGS) ÷ Revenue from
    Operations. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" - same nested-cache-chain reasoning as `fetch_inventory_turnover`'s
    # "_v2" bump: wraps `fetch_gross_profit_margin_from_annual_report`
    # (bumped "_v2") which wraps `_get_extracted_financials` (v19->v20).
    ckey = f"gpm_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Gross Profit Margin"}
    if to_date is None:
        db_row = try_db_ratio(sym, 14)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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
        r = fetch_gross_profit_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_gross_profit_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Operating Profit Margin (EBIT Basis) - (Revenue − COGS − Employee Benefit
# Expense − Other Expenses − Depreciation & Amortisation) ÷ Revenue. Sourced
# from the Annual Report only, same rationale as Gross Profit Margin.
# --------------------------------------------------------------------------- #
def fetch_operating_profit_margin(symbol, name=None, to_date=None):
    """
    Operating Profit Margin (EBIT Basis) = (Revenue − COGS − Employee
    Benefit Expense − Other Expenses − Depreciation & Amortisation) ÷
    Revenue. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"opm_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Operating Profit Margin (EBIT Basis)"}
    if to_date is None:
        db_row = try_db_ratio(sym, 15)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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
        r = fetch_operating_profit_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_operating_profit_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Income Statement Flow - Revenue -> Cost of Revenue/Gross Profit -> Operating
# Expenses/Operating Profit -> PBT bridge -> Tax/Net Profit, for the Overview
# page Sankey. Applicable to ALL industries (does NOT gate on _NON_INVENTORY)
# since the AR-level builder itself degrades the flow's depth to whatever the
# statement discloses - a bank/NBFC naturally comes back with no Cost of
# Revenue split rather than a fabricated one.
# --------------------------------------------------------------------------- #
def fetch_income_statement_flow(symbol, name=None, to_date=None):
    """
    Nodes/links for the Revenue -> Profit & Cost Sankey, built only from the
    company's own Annual Report P&L (see
    `fetch_income_statement_flow_from_annual_report` for the tiering rules).
    Same year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} when even the shallowest Revenue -> PBT -> Net
    Profit flow can't be built from the P&L page. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"incflow_v10_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym}
    # No Supabase precompute table for this one yet (ratio_no is int-keyed) -
    # relies solely on the 90-day file cache in `_get_extracted_financials`.
    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_income_statement_flow_from_annual_report)
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
        r = fetch_income_statement_flow_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_income_statement_flow_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Net Profit Margin - Profit After Tax (owners-attributable) ÷ Revenue.
# Sourced from the Annual Report only, same rationale as Gross/Operating
# Profit Margin. Applicable to ALL industries per spec (only banks/NBFC/
# insurance excluded) - unlike the COGS-based margins, this ratio doesn't
# require a goods-based cost structure, so it does NOT gate on _NON_INVENTORY
# the same way; it's still excluded for lenders per spec's own industry list.
# --------------------------------------------------------------------------- #
def fetch_net_profit_margin(symbol, name=None, to_date=None):
    """
    Net Profit Margin = Profit After Tax (owners-attributable) ÷ Revenue from
    Operations. Same year-selection behaviour as `fetch_inventory_turnover`.
    Returns {'applicable': False} for lenders/financial businesses - never a
    fabricated number. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" - wraps `fetch_net_profit_margin_from_annual_report` (bumped
    # "_v2") which wraps `_get_extracted_financials` (v23 - "pat" alias fix).
    ckey = f"npm_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Net Profit Margin"}
    if to_date is None:
        db_row = try_db_ratio(sym, 16)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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
        r = fetch_net_profit_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_reason = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_net_profit_margin_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Return on Equity (ROE) - Profit After Tax (owners-attributable) ÷ Average
# Total Equity (owners-attributable). Sourced from the Annual Report only,
# same rationale as Net Profit Margin.
# --------------------------------------------------------------------------- #
def fetch_return_on_equity(symbol, name=None, to_date=None):
    """
    Return on Equity = Profit After Tax (owners-attributable) ÷ Average Total
    Equity (owners-attributable). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses and for negative-equity companies (per
    spec - never a spurious positive ratio). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v4" - wraps `fetch_return_on_equity_from_annual_report` (bumped
    # "_v4") which wraps `_get_extracted_financials` (v23).
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_return_on_equity_from_annual_
    # report's own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"roe_v4_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Return on Equity"}
    if to_date is None:
        db_row = try_db_ratio(sym, 18)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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

    # `r` is spread in BOTH the applicable and N/A cases - negative equity is
    # a real, worth-showing finding (like negative Working Capital), not just
    # a bare reason string.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_return_on_equity_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_return_on_equity_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Return on Capital Employed (ROCE) - EBIT (Profit Before Tax + Finance
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
    # "_v4" - wraps `fetch_return_on_capital_employed_from_annual_report`
    # (bumped "_v4") which wraps `_get_extracted_financials` (v24).
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key: without it, a symbol with both a manually-uploaded
    # document and a live-fetchable one would share this cache key across
    # the manual-upload and automatic pipelines.
    from tools.manual_mode import is_manual_mode
    ckey = (f"roce_v4_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Return on Capital Employed"}
    if to_date is None:
        db_row = try_db_ratio(sym, 19)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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

    # `r` is spread in BOTH the applicable and N/A cases - a negative Capital
    # Employed is a real, worth-showing finding, not just a reason string.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_return_on_capital_employed_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_return_on_capital_employed_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Debt-to-Equity Ratio - Total Debt (Long-term + Short-term Borrowings +
# Current Maturities) ÷ Total Equity (owners-attributable), both CLOSING
# balance. Sourced from the Annual Report only, same rationale as Current
# Ratio (point-in-time, no averaging).
# --------------------------------------------------------------------------- #
def fetch_debt_to_equity(symbol, name=None, to_date=None, lease_basis="basis1"):
    """
    Debt-to-Equity = Total Debt ÷ Total Equity (owners-attributable), both
    closing balance. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, and for negative/zero-equity companies
    (per spec - never a spurious ratio). `lease_basis` defaults to "basis1"
    (Lease Liabilities included in Total Debt, per Sr No 20/33's own
    default) - pass "basis2" for the traditional ex-lease view; this is the
    single global per-company toggle every Total-Debt-based ratio shares.
    Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" - wraps `fetch_debt_to_equity_from_annual_report` (bumped "_v2")
    # which wraps `_get_extracted_financials` (v22 - equity_full NCI fix).
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key: without it, a symbol with both a manually-uploaded
    # document and a live-fetchable one would share this cache key across
    # the manual-upload and automatic pipelines, leaking the manual-only
    # owners-attributable-equity denominator into the automatic pipeline's
    # served result, or vice versa.
    from tools.manual_mode import is_manual_mode
    ckey = (f"de_v3_{sym}_{to_date or 'latest'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Debt-to-Equity"}
    if to_date is None and lease_basis == "basis1":
        db_row = try_db_ratio(sym, 20)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
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

    # `r` is spread in BOTH the applicable and N/A cases - negative equity is
    # a real, worth-showing finding, not just a reason string.
    if to_date:
        target_year = _yr_from_to_date(to_date) or ar_years[0]
        r = fetch_debt_to_equity_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_debt_to_equity_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
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
# Debt Ratio (Sr No 21) - Total Debt ÷ Total Assets, both CLOSING balance.
# Reuses Debt-to-Equity's Total Debt numerator and Asset Turnover's Total
# Assets field (closing only, not averaged). Sourced from the Annual Report
# only, same rationale as Debt-to-Equity.
# --------------------------------------------------------------------------- #
def fetch_debt_ratio(symbol, name=None, to_date=None, lease_basis="basis1"):
    """
    Debt Ratio = Total Debt ÷ Total Assets, both closing balance. Same
    year-selection behaviour as `fetch_inventory_turnover`. Returns
    {'applicable': False} for lenders/financial businesses (capital
    structure rules differ fundamentally there). `lease_basis` defaults to
    "basis1" (Lease Liabilities included) - pass "basis2" for the ex-lease
    view; the same single global per-company toggle as Debt-to-Equity.
    Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"debtratio_v3_{sym}_{to_date or 'latest'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Debt Ratio"}
    if to_date is None and lease_basis == "basis1":
        db_row = try_db_ratio(sym, 21)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(capital structure and leverage rules differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_debt_ratio_from_annual_report)
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
        r = fetch_debt_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_debt_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
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
# Interest Coverage Ratio (Sr No 22) - EBIT ÷ Interest Expense (Finance
# Costs), current year only. Reuses ROCE's EBIT numerator. Sourced from the
# Annual Report only, same rationale as Debt Ratio/Debt-to-Equity.
# --------------------------------------------------------------------------- #
def fetch_interest_coverage_ratio(symbol, name=None, to_date=None):
    """
    Interest Coverage Ratio = EBIT ÷ Interest Expense (Finance Costs), current
    year only - no averaging. Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses, and {'applicable': False, 'not_meaningful':
    True} (not a computation failure) when Finance Costs is nil - a
    genuinely debt-free/interest-free company, never a divide-by-zero or
    fabricated infinite ratio. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"intcov_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Interest Coverage Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 22)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(interest is core to its business model, not a financing cost to cover)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_interest_coverage_ratio_from_annual_report)
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
        r = fetch_interest_coverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_interest_coverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        # Same fix as Net Debt/EBITDA's probe loop just above: `not_meaningful:
        # True` (genuinely nil Finance Costs - a debt-free/interest-free
        # year) is a definitive, correct answer, not an extraction failure -
        # treating it as one silently discarded the current year's real
        # "debt-free" finding in favour of an older year's real multiple.
        if r.get("applicable") or r.get("not_meaningful"):
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
# Financial Leverage Ratio (Sr No 23) - Average Total Assets ÷ Average
# Shareholders' Equity, the "leverage" leg of the DuPont ROE decomposition.
# Reuses Asset Turnover's Average Total Assets and ROE's Average Total
# Equity. Sourced from the Annual Report only, same rationale as ROE.
# --------------------------------------------------------------------------- #
def fetch_financial_leverage_ratio(symbol, name=None, to_date=None):
    """
    Financial Leverage Ratio = Average Total Assets ÷ Average Shareholders'
    Equity (owners-attributable). Same year-selection behaviour as
    `fetch_inventory_turnover`. Returns {'applicable': False} for
    lenders/financial businesses and negative-equity companies (per spec -
    same restriction as ROE). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v3" - wraps `fetch_financial_leverage_ratio_from_annual_report`
    # (bumped "_v3") which wraps `_get_extracted_financials` (v20->v21) -
    # same nested-cache-chain lesson as the EPS/GPM cache fixes.
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"finlev_v3_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Financial Leverage Ratio"}
    if to_date is None:
        db_row = try_db_ratio(sym, 23)
        if db_row is not None:
            return {**base, **db_row}

    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(capital structure and capital adequacy rules differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_financial_leverage_ratio_from_annual_report)
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
        r = fetch_financial_leverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_financial_leverage_ratio_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Basic EPS (Sr No 24 denominator) - the Annual-Report half of Price-to-
# Earnings. UNLIKE every other ratio here, this is NOT excluded for Banks/
# NBFC (per spec's applicable_industries list - EPS/P-E are meaningful for
# them too; only unlisted Insurance subsidiaries are excluded, which is
# already naturally handled by "no live price available").
# --------------------------------------------------------------------------- #
def fetch_eps(symbol, name=None, to_date=None):
    """
    Basic Earnings per Share, current year only. Same year-selection
    behaviour as `fetch_inventory_turnover`, but with NO lender/financial-
    business exclusion (EPS applies to Banks/NBFC too). Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v4" - same nested-cache-chain reasoning as `fetch_eps_growth`'s
    # "_v4" bump: this cache wraps `fetch_eps_from_annual_report` (bumped
    # "_v2"->"_v3") which wraps `_get_extracted_financials` (bumped
    # "v18"->"v19") - this outermost layer must move with both.
    ckey = f"eps_v4_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Basic EPS"}
    if to_date is None:
        db_row = try_db_ratio(sym, 24)
        if db_row is not None:
            return {**base, **db_row}


    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_eps_from_annual_report)
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
        # Consolidated-first, Standalone-fallback - matches the project-wide
        # Consolidation Priority rule every other ratio in this suite already
        # follows (Net Profit Margin/ROE/ROCE/BVPS/Dividend Payout all read
        # Consolidated PAT/equity first). A prior version of this function
        # used Standalone-only for EPS specifically; that broke consistency
        # with the rest of the framework and wasn't backed by the project's
        # own Excel/framework spec (which doesn't document a Standalone-only
        # EPS rule at all), so it was reverted. `_get_extracted_financials_impl`'s
        # existing consolidated->standalone fallback still applies for a
        # filer with no separate Consolidated statement at all.
        r = fetch_eps_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        # Consolidated-first, Standalone-fallback - see the comment on the
        # `to_date` branch above for the full reasoning.
        r = fetch_eps_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Book Value per Share (Sr No 25 denominator) - the Annual-Report half of
# Price-to-Book. Like EPS, NO Bank/NBFC/Insurance exclusion (per spec's own
# applicable_industries list - P/B applies to all of them, including banks,
# where it's especially relevant).
# --------------------------------------------------------------------------- #
def fetch_book_value_per_share(symbol, name=None, to_date=None, consolidated=True):
    """
    Book Value per Share = Total Equity (owners-attributable, closing) ÷
    Equity Shares Outstanding (closing). Same year-selection behaviour as
    `fetch_inventory_turnover`, but with NO lender/financial-business
    exclusion. Returns {'applicable': False} for negative-equity companies
    (per spec). `consolidated` defaults to True (Sr No 25's own card, paired
    with a consolidated-basis Market Cap for P/B) - pass `consolidated=False`
    for Sr No 46's dedicated "Book Value per Share (Standalone)" card, which
    used to silently ALWAYS fetch consolidated data regardless of its own
    name (there was no way to request standalone at all) - confirmed
    wrong on companies with a material owners-vs-consolidated equity gap.
    The Supabase fast-path (`try_db_ratio`) only ever stores the
    consolidated figure, so it's skipped entirely for a standalone request.
    Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v3" - wraps `fetch_book_value_per_share_from_annual_report` (bumped
    # "_v3") which wraps `_get_extracted_financials` (v22).
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"bvps_v4_{sym}_{to_date or 'latest'}_{'C' if consolidated else 'S'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Book Value per Share"}
    if to_date is None and consolidated:
        db_row = try_db_ratio(sym, 25)
        if db_row is not None:
            return {**base, **db_row}


    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_book_value_per_share_from_annual_report)
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
        r = fetch_book_value_per_share_from_annual_report(sym, name, target_year, consolidated=consolidated)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_book_value_per_share_from_annual_report(sym, name, target_year, consolidated=consolidated)
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
# Equity Shares Outstanding + Revenue from Operations (Sr No 26 building
# blocks) - Market Cap ÷ Revenue (Price-to-Sales). Both are simple single-
# field reuses (shares_outstanding from Sr No 25, revenue from Sr No 3) kept
# as their own endpoints so P/S stays computable independent of Book Value
# per Share's (negative-equity) or Receivables Turnover's (missing
# receivables) own applicability. NO Bank/NBFC exclusion (per spec's own
# applicable_industries list - only Insurance is excluded, for P/S).
# --------------------------------------------------------------------------- #
def fetch_shares_outstanding(symbol, name=None, to_date=None):
    """Equity Shares Outstanding (closing), current year only. Same year-
    selection behaviour as `fetch_inventory_turnover`, no lender/financial
    exclusion. Cached; never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"sharesout_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Equity Shares Outstanding"}
    if to_date is None:
        db_row = try_db_ratio(sym, 100)
        if db_row is not None:
            return {**base, **db_row}


    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_shares_outstanding_from_annual_report)
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
        r = fetch_shares_outstanding_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_shares_outstanding_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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


def fetch_revenue_from_operations(symbol, name=None, to_date=None):
    """Revenue from Operations, current year only. Same year-selection
    behaviour as `fetch_inventory_turnover`, no lender/financial exclusion.
    Cached; never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"revenueops_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Revenue from Operations"}
    if to_date is None:
        db_row = try_db_ratio(sym, 26)
        if db_row is not None:
            return {**base, **db_row}


    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_revenue_from_operations_from_annual_report)
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
        r = fetch_revenue_from_operations_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_revenue_from_operations_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# Dividend per Share (Sr No 27 numerator) - always standalone-sourced (see
# fetch_dividend_per_share_from_annual_report's docstring). NO Bank/NBFC
# exclusion (per spec's own applicable_industries list - only Insurance is
# excluded, for Dividend Yield).
# --------------------------------------------------------------------------- #
def fetch_dividend_per_share(symbol, name=None, to_date=None):
    """
    Total Dividend per Equity Share declared during the year (always
    standalone). Same year-selection behaviour as `fetch_inventory_turnover`,
    no lender/financial exclusion. Never returns a plain N/A for "no
    dividend" - that's a real 0% per spec, at reduced confidence when
    unconfirmed. Cached; never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    # "_manual" suffix - see the matching comment on
    # tools.annual_report_financials.fetch_debt_ratio_from_annual_report's
    # own cache key.
    from tools.manual_mode import is_manual_mode
    ckey = (f"dps_v4_{sym}_{to_date or 'latest'}"
            f"{'_manual' if is_manual_mode() else ''}_{_doc_tag_for_cache(sym, to_date)}")
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Dividend per Share"}
    if to_date is None:
        db_row = try_db_ratio(sym, 27)
        if db_row is not None:
            return {**base, **db_row}


    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_dividend_per_share_from_annual_report)
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
        r = fetch_dividend_per_share_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_dividend_per_share_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
# EV/EBITDA (Sr No 29) building blocks - EBITDA (its OWN independent
# calculation, `fetch_ebitda_from_annual_report`/Sr No 93 in the master
# field registry - it no longer reuses Sr No 15's Operating Profit Margin
# numerator, since Sr No 15 was redefined to EBIT-basis (deducts
# Depreciation & Amortisation) while EBITDA must stay EBITDA-basis; see that
# function's docstring), Total Debt (reuses Sr No 20's full a+b+c protocol -
# `_compute_total_debt`, NOT the old simplified Borrowings-only figure),
# Cash and Cash Equivalents (reuses Sr No 12's numerator). Each its own
# function so Enterprise Value stays computable independent of OPM's/
# Debt-to-Equity's/Cash Ratio's own unrelated applicability gates. Standard
# Bank/NBFC exclusion applies (per spec's own applicable_industries list -
# same as every non-market-multiple ratio; only Insurance additionally
# excluded).
# --------------------------------------------------------------------------- #
def fetch_ebitda(symbol, name=None, to_date=None):
    """EBITDA (Revenue − COGS − Employee Costs − Other Expenses), current
    year only. Same year-selection behaviour as `fetch_inventory_turnover`.
    Cached; never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ebitda_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "EBITDA"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(operating-cost structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import list_annual_report_years, fetch_ebitda_from_annual_report
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
        r = fetch_ebitda_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_ebitda_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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


def fetch_total_debt(symbol, name=None, to_date=None, lease_basis="basis1"):
    """Total Debt (closing), same components as Debt-to-Equity/Debt Ratio's
    numerator. Same year-selection behaviour as `fetch_inventory_turnover`.
    `lease_basis` defaults to "basis1" (Lease Liabilities included) - pass
    "basis2" for the ex-lease view; the same single global per-company
    toggle as Debt-to-Equity/Debt Ratio. Cached; never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"totaldebt_v2_{sym}_{to_date or 'latest'}_{lease_basis}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Total Debt"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(capital structure rules differ fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import list_annual_report_years, fetch_total_debt_from_annual_report
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
        r = fetch_total_debt_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_total_debt_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year), lease_basis=lease_basis)
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


def fetch_cash_and_equivalents(symbol, name=None, to_date=None):
    """Cash and Cash Equivalents (closing), identical field to Cash Ratio's
    numerator. Same year-selection behaviour as `fetch_inventory_turnover`.
    Cached; never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"cashonly_v2_{sym}_{to_date or 'latest'}_{_doc_tag_for_cache(sym, to_date)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    base = {"symbol": sym, "ratio_name": "Cash and Cash Equivalents"}
    nm = (name or sym).lower()
    if any(w in nm for w in _NON_INVENTORY):
        out = {**base, "applicable": False,
               "reason": "Not applicable - this is a lender/financial business "
                         "(balance sheet structure differs fundamentally)."}
        _write_cache(ckey, out)
        return out

    try:
        from tools.annual_report_financials import (
            list_annual_report_years, fetch_cash_and_equivalents_from_annual_report)
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
        r = fetch_cash_and_equivalents_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
        out = {**base, "selected_period": f"31-Mar-{target_year}", "available_periods": available, **r}
        _write_cache(ckey, out)
        return out

    MAX_PROBE_YEARS = 4
    first_result = None
    for target_year in ar_years[:MAX_PROBE_YEARS]:
        r = fetch_cash_and_equivalents_from_annual_report(sym, name, target_year, consolidated=_resolved_consolidated(sym, name, target_year))
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
