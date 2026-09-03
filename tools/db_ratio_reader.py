"""
Fast-path reader for `ratio_values` - the piece that actually removes the
3-4 minute "Reading audited filings..." wait, for any company the
precompute worker has already reached. Every nse_xbrl `fetch_X` wrapper
checks this FIRST (only for the "latest year" case - a specific historical
year request always goes live, since the DB only stores what the
precompute worker has computed so far); if there's no row yet, falls
through to the existing live PDF-parsing path unchanged - no regression
for not-yet-precomputed companies, just no speedup either until the
background run reaches them.
"""

import os
import json
import time

from tools.supabase_client import get_client

_FRESHNESS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "cache", "db_ratio_freshness")
_FRESHNESS_TTL = 12 * 3600  # short - just enough to keep the fast path fast


def _latest_ar_year_cached(symbol):
    """Cheap, short-TTL-cached lookup of the newest fiscal year an Annual
    Report exists for - used only to detect a STALE Supabase "latest" row
    (see `try_db_ratio` below), not for the ratio computation itself.

    Confirmed on Gopal Snacks (a recently-listed company): the precompute
    worker wrote its FY24 Receivables Turnover row before FY25's Annual
    Report was published, and with no freshness check `try_db_ratio` kept
    serving that FY24 row forever afterwards - the exact "shows FY24 even
    though FY25 is publicly available" bug QA flagged, and a general risk
    for ANY company whose precompute run predates its latest filing, not
    just this one. A short TTL (12h, separate from the 7-day TTL other BSE
    lookups in this codebase use) keeps this near-free on repeat requests
    while still catching a newly-published Annual Report within the same
    day, rather than waiting on the background precompute job's queue
    position. Never raises."""
    path = os.path.join(_FRESHNESS_CACHE_DIR, f"{symbol}.json")
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) <= _FRESHNESS_TTL:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("year")
    except Exception:
        pass
    year = None
    try:
        from tools.annual_report_financials import list_annual_report_years
        years = list_annual_report_years(symbol, None) or []
        year = max(years) if years else None
    except Exception:
        pass
    try:
        os.makedirs(_FRESHNESS_CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"year": year}, fh)
    except Exception:
        pass
    return year


def write_db_ratio(symbol, ratio_no, out, consolidated=True, extraction_version=None):
    """The write-back half of the fast-path: called whenever a LIVE
    computation (DB miss -> full PDF parse) produces a "latest year" result,
    so the NEXT search for this (symbol, ratio) - by anyone - is instant
    from then on, without waiting for the background precompute to reach it.
    Turns "only the background job populates Supabase" into "every request
    that ever computes something for real also banks it" - the concrete fix
    for a company like AAKASH being slow purely because of queue position.

    `out` is whatever shape a `fetch_X` wrapper returns (same dict the
    frontend/HTTP layer already consumes) - only persists when there's an
    actual fiscal year to key on (`selected_period`); silently no-ops
    otherwise (e.g. a "no filings found at all" N/A has nothing to store).
    Never raises - a DB write failure must never break the live response
    the user is already waiting on.

    `consolidated` must reflect the ACTUAL basis this result was computed
    on (e.g. `tools.statement_selector.select_statement_basis(...).
    selected_basis == "CONSOLIDATED"`), not just assumed True - a company
    whose Annual Report has no consolidated statements and was genuinely
    computed on a standalone basis must not have that fact silently
    overwritten to `consolidated=True` in the cache, or a later
    basis-specific read would serve the wrong figure as if it were
    consolidated.

    `extraction_version`, when given, should be
    `tools.fundamental_fact_store.EXTRACTION_VERSION` (or the calculation
    engine's own version once it has one) - persisted so a later logic
    change can make every row written under an OLDER version a transparent
    cache miss (see `try_db_ratio`). Left `None` for callers that don't
    resolve a version yet (the column is added by
    `db/002_extraction_version.sql`, additive/idempotent, and simply
    omitted from the write until that migration has been applied - never
    raises if the column doesn't exist yet, per this function's normal
    never-raises contract).

    Skipped entirely in tools/manual_mode.py's manual document-analysis
    workflow - that workflow's results (fiscal year, consolidation basis,
    even the underlying document) can legitimately differ from what the
    automatic pipeline would compute for the same symbol, and must never
    cross-pollute this shared ratio_values cache the automatic pipeline
    reads from."""
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        return
    try:
        sp = out.get("selected_period") or ""
        fiscal_year = int(sp.split("-")[-1])
    except Exception:
        return
    try:
        sb = get_client()
        # `ratio_values.symbol` has a FK into `companies` - every symbol in
        # the registry was already seeded there (even ones with no resolved
        # filings), so this normally just works. Deliberately does NOT
        # upsert `companies` here (would require guessing a `name`, and
        # could clobber the REAL name seed_company_registry already stored
        # with a placeholder) - a symbol genuinely missing from `companies`
        # (outside the known registry) will just fail this insert silently,
        # which is an acceptable degradation: the live answer the user is
        # waiting on was already returned regardless.
        row = {
            "symbol": symbol,
            "ratio_no": ratio_no,
            "fiscal_year": fiscal_year,
            "consolidated": bool(consolidated),
            "applicable": bool(out.get("applicable")),
            "value": out.get("value"),
            "unit": out.get("unit"),
            "confidence": out.get("confidence"),
            "estimated": bool(out.get("estimated", False)),
            "period_label": out.get("period") or sp,
            "numerator": out.get("numerator"),
            "denominator": out.get("denominator"),
            "sources": out.get("sources"),
            "reason": out.get("reason"),
            "note": out.get("note"),
        }
        if extraction_version is not None:
            row["extraction_version"] = extraction_version
        sb.table("ratio_values").upsert(row).execute()
    except Exception as e:
        print(f"[db_ratio_reader] write-back failed for {symbol} ratio_no={ratio_no}: {e}")


def try_db_ratio(symbol, ratio_no, consolidated=None, extraction_version=None):
    """Returns a dict shaped like the existing fetch_X wrappers' output
    (applicable/value/unit/confidence/...), or None if this (symbol,
    ratio_no) hasn't been precomputed yet. Never raises - any DB error
    just falls through to the live path, same as a cache miss.

    `consolidated`, when given (True/False), restricts the lookup to a row
    computed on that exact basis - so a request that resolved to STANDALONE
    (via tools.statement_selector) never gets served a CONSOLIDATED-basis
    cached row, or vice versa. Left `None` (default) for existing callers
    that don't yet resolve a basis explicitly, preserving prior behaviour.

    `extraction_version`, when given, restricts the lookup to a row written
    under that exact version (see `write_db_ratio`) - so a row computed
    under OLDER extraction/calculation logic is treated as a cache miss
    rather than served stale, once a caller starts passing the current
    `tools.fundamental_fact_store.EXTRACTION_VERSION`. Left `None` (default)
    for callers that don't version their requests yet - unchanged prior
    behaviour, and safe even before `db/002_extraction_version.sql` has
    been applied (the column is only referenced when this argument is given).

    Always returns None in tools/manual_mode.py's manual document-analysis
    workflow - a value the automatic pipeline computed earlier (possibly
    from a different fiscal year, consolidation basis, or document
    entirely) must never be silently served in place of actually computing
    it from the documents this run's user uploaded."""
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        return None
    try:
        sb = get_client()
        q = sb.table("ratio_values").select("*").eq("symbol", symbol).eq("ratio_no", ratio_no)
        if consolidated is not None:
            q = q.eq("consolidated", bool(consolidated))
        if extraction_version is not None:
            q = q.eq("extraction_version", extraction_version)
        r = q.order("fiscal_year", desc=True).limit(1).execute()
        if not r.data:
            return None
        row = r.data[0]
        # Stale-"latest" guard: if a newer Annual Report has since been
        # published, this row is out of date - fall through to the live
        # path instead of serving an outdated year. The live call also
        # writes back through `write_db_ratio`, so this self-heals: the
        # NEXT request for this (symbol, ratio) is fast again, precompute
        # worker or not.
        latest_year = _latest_ar_year_cached(symbol)
        if latest_year is not None and latest_year > row["fiscal_year"]:
            return None
        return {
            "applicable": row["applicable"],
            "value": row["value"],
            "unit": row["unit"],
            "confidence": row["confidence"],
            "estimated": row["estimated"],
            "period": row["period_label"],
            "selected_period": f"31-Mar-{row['fiscal_year']}",
            # available_periods isn't stored in ratio_values (it's a
            # BSE-filing-list lookup, not a ratio value) - the period
            # picker just won't offer alternate years for a DB-served
            # result until a future pass adds it. Not a correctness issue,
            # just a smaller dropdown; every ratio-year figure itself is
            # exact from the precompute run.
            "available_periods": None,
            "numerator": row["numerator"],
            "denominator": row["denominator"],
            "sources": row["sources"],
            "reason": row["reason"],
            "note": row["note"],
        }
    except Exception:
        return None
