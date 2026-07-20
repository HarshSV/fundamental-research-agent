"""
Fast-path reader for `ratio_values` — the piece that actually removes the
3-4 minute "Reading audited filings..." wait, for any company the
precompute worker has already reached. Every nse_xbrl `fetch_X` wrapper
checks this FIRST (only for the "latest year" case — a specific historical
year request always goes live, since the DB only stores what the
precompute worker has computed so far); if there's no row yet, falls
through to the existing live PDF-parsing path unchanged — no regression
for not-yet-precomputed companies, just no speedup either until the
background run reaches them.
"""

from tools.supabase_client import get_client


def write_db_ratio(symbol, ratio_no, out):
    """The write-back half of the fast-path: called whenever a LIVE
    computation (DB miss -> full PDF parse) produces a "latest year" result,
    so the NEXT search for this (symbol, ratio) — by anyone — is instant
    from then on, without waiting for the background precompute to reach it.
    Turns "only the background job populates Supabase" into "every request
    that ever computes something for real also banks it" — the concrete fix
    for a company like AAKASH being slow purely because of queue position.

    `out` is whatever shape a `fetch_X` wrapper returns (same dict the
    frontend/HTTP layer already consumes) — only persists when there's an
    actual fiscal year to key on (`selected_period`); silently no-ops
    otherwise (e.g. a "no filings found at all" N/A has nothing to store).
    Never raises — a DB write failure must never break the live response
    the user is already waiting on."""
    try:
        sp = out.get("selected_period") or ""
        fiscal_year = int(sp.split("-")[-1])
    except Exception:
        return
    try:
        sb = get_client()
        # `ratio_values.symbol` has a FK into `companies` — every symbol in
        # the registry was already seeded there (even ones with no resolved
        # filings), so this normally just works. Deliberately does NOT
        # upsert `companies` here (would require guessing a `name`, and
        # could clobber the REAL name seed_company_registry already stored
        # with a placeholder) — a symbol genuinely missing from `companies`
        # (outside the known registry) will just fail this insert silently,
        # which is an acceptable degradation: the live answer the user is
        # waiting on was already returned regardless.
        sb.table("ratio_values").upsert({
            "symbol": symbol,
            "ratio_no": ratio_no,
            "fiscal_year": fiscal_year,
            "consolidated": True,
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
        }).execute()
    except Exception as e:
        print(f"[db_ratio_reader] write-back failed for {symbol} ratio_no={ratio_no}: {e}")


def try_db_ratio(symbol, ratio_no):
    """Returns a dict shaped like the existing fetch_X wrappers' output
    (applicable/value/unit/confidence/...), or None if this (symbol,
    ratio_no) hasn't been precomputed yet. Never raises — any DB error
    just falls through to the live path, same as a cache miss."""
    try:
        sb = get_client()
        r = (sb.table("ratio_values").select("*")
             .eq("symbol", symbol).eq("ratio_no", ratio_no)
             .order("fiscal_year", desc=True).limit(1).execute())
        if not r.data:
            return None
        row = r.data[0]
        return {
            "applicable": row["applicable"],
            "value": row["value"],
            "unit": row["unit"],
            "confidence": row["confidence"],
            "estimated": row["estimated"],
            "period": row["period_label"],
            "selected_period": f"31-Mar-{row['fiscal_year']}",
            # available_periods isn't stored in ratio_values (it's a
            # BSE-filing-list lookup, not a ratio value) — the period
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
