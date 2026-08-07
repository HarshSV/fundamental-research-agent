"""
Refresh mechanism — force specific (symbol, ratio_no) pairs to recompute
and overwrite Supabase's `ratio_values` table, for use whenever an
extractor bug fix needs to reach companies that were already precomputed
BEFORE the fix landed.

Why this has to exist as its own tool, not just "run precompute again":
`tools/precompute_worker.py`'s `run()` skips any (symbol, ratio_no) pair
already marked "done" in `refresh_jobs` — that's the whole point of it
being resumable, but it means a code fix never reaches an already-done
pair on its own. `tools/_refix_tcl_cash_ratios.py` was a prior one-off,
hardcoded attempt at exactly this problem (a 2026-07-31 regression); this
generalizes that pattern into a reusable tool instead of writing a new
bespoke script for every future extraction fix.

There's a second, more subtle bug this tool specifically has to avoid
repeating: bypassing the `refresh_jobs` "done" skip is not enough on its
own. Every `tools/nse_xbrl.py` fetch_X wrapper ALSO checks Supabase itself
(`try_db_ratio`) before doing any live computation, whenever `to_date` is
None — and it returns the EXISTING row immediately if one is present,
correct or not. `precompute_worker.compute_one` calls `fetcher(symbol,
name)` with no `to_date`, so re-running it against a pair that already has
a (wrong) row just reads that same wrong row back out of Supabase and
writes it right back — a silent no-op refresh. Confirmed by hand on ITC's
Current/Quick/Cash/Operating-Cash-Flow ratios (2026-08-07): calling the
plain wrapper repeated the same -14.03 Quick Ratio every time, and only
passing an explicit `to_date` for the latest Annual Report year (which
`try_db_ratio` is never consulted for) actually forced the live PDF path
and produced the corrected value.

Usage:
    # Refresh specific ratios for specific companies (fast, for
    # verifying a fix against the exact stock(s) that surfaced it):
    python -m tools.refresh_ratios --ratios 10,11,12,39 --symbols ITC,RELIANCE

    # Refresh specific ratios across the FULL `companies` registry (slow —
    # one PDF download+parse per company; same-company ratios reuse that
    # company's already-warmed PDF cache, so batching several affected
    # ratio_nos together in one run is much cheaper than separate runs):
    python -m tools.refresh_ratios --ratios 10,11,12,39 --all

    # From Python, e.g. immediately after landing an extraction fix:
    from tools.refresh_ratios import refresh
    refresh(ratio_nos=[10, 11, 12, 39], symbols=["ITC"])
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from tools.supabase_client import get_client
from tools.precompute_worker import upsert_company, RATIO_FETCHERS

PAGE_SIZE = 1000


def _load_all_companies(sb):
    """Paginated fetch of every (symbol, name) in the `companies` table —
    same pagination pattern as coverage_report.py's fetch_all, needed
    because a single .execute() call caps out around Supabase's default
    page size."""
    rows = []
    start = 0
    while True:
        resp = sb.table("companies").select("symbol,name").range(start, start + PAGE_SIZE - 1).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def compute_one_forced(sb, symbol, name, ratio_no, fetcher):
    """Like precompute_worker.compute_one, but actually bypasses the
    Supabase fast-path read instead of tripping over it. Looks up the
    latest Annual Report fiscal year once and calls the fetcher with that
    year as an EXPLICIT to_date — every nse_xbrl fetch_X wrapper only
    consults try_db_ratio when to_date is None, so this is the one thing
    that reliably forces the live PDF-parsing path regardless of what's
    already sitting in `ratio_values`. Never raises — records an error in
    `refresh_jobs` and returns False instead, same convention as
    compute_one. Returns True/False (success)."""
    try:
        from tools.annual_report_financials import list_annual_report_years
        years = list_annual_report_years(symbol, name) or []
    except Exception as e:
        print(f"[refresh_ratios] AR year lookup failed for {symbol}: {e}")
        years = []
    if not years:
        print(f"[refresh_ratios] {symbol}: no Annual Report years found, skipping ratio_no={ratio_no}")
        return False
    latest_year = years[0]
    to_date = f"31-Mar-{latest_year}"

    try:
        try:
            r = fetcher(symbol, name, to_date=to_date)
        except TypeError:
            # A handful of fetchers don't take a to_date at all (e.g. a pure
            # point-in-time figure with no historical-year concept) — fall
            # back to the plain call for those rather than crashing the run.
            r = fetcher(symbol, name)
        fiscal_year = None
        sp = r.get("selected_period") or ""
        try:
            fiscal_year = int(sp.split("-")[-1])
        except Exception:
            fiscal_year = latest_year
        row = {
            "symbol": symbol,
            "ratio_no": ratio_no,
            "fiscal_year": fiscal_year,
            "consolidated": True,
            "applicable": bool(r.get("applicable")),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "confidence": r.get("confidence"),
            "estimated": bool(r.get("estimated", False)),
            "period_label": r.get("period") or sp,
            "numerator": r.get("numerator"),
            "denominator": r.get("denominator"),
            "sources": r.get("sources"),
            "reason": r.get("reason"),
            "note": r.get("note"),
        }
        sb.table("ratio_values").upsert(row).execute()
        sb.table("refresh_jobs").upsert({
            "symbol": symbol, "ratio_no": ratio_no,
            "status": "done", "last_run_at": "now()", "last_error": None,
        }).execute()
        return True
    except Exception as e:
        try:
            sb.table("refresh_jobs").upsert({
                "symbol": symbol, "ratio_no": ratio_no,
                "status": "error", "last_run_at": "now()", "last_error": str(e)[:500],
            }).execute()
        except Exception as e2:
            print(f"[refresh_ratios] could not even record the error for {symbol} ratio_no={ratio_no}: {e2}")
        return False


def refresh(ratio_nos, symbols=None, sleep_between=0.0):
    """Force-recomputes every (symbol, ratio_no) pair for the given
    ratio_nos — across the given symbols, or the FULL `companies` registry
    when symbols is None — and overwrites `ratio_values` regardless of
    whether a row already exists there or what `refresh_jobs` says about
    it. This is the operation you want right after fixing an extractor
    bug: the pairs most likely to be wrong are exactly the ones already
    marked "done" from before the fix.

    ratio_nos: iterable of ints (must exist in precompute_worker.RATIO_FETCHERS).
    symbols: iterable of symbol strings, or None for every company in Supabase.
    Returns (ok_count, err_count).
    """
    ratio_nos = set(ratio_nos)
    targets = [(rn, fn) for rn, fn in RATIO_FETCHERS if rn in ratio_nos]
    missing = ratio_nos - {rn for rn, _ in targets}
    if missing:
        print(f"[refresh_ratios] WARNING: ratio_no(s) {sorted(missing)} not found in "
              f"precompute_worker.RATIO_FETCHERS — skipped (check the Sr No is one that's "
              f"actually precomputed, not a client-side-derived one)")
    if not targets:
        print("[refresh_ratios] nothing to do — no valid ratio_nos given")
        return 0, 0

    sb = get_client()
    if symbols:
        wanted = [s.strip().upper() for s in symbols if s.strip()]
        rows = sb.table("companies").select("symbol,name").in_("symbol", wanted).execute().data or []
        by_symbol = {r["symbol"]: r.get("name") or r["symbol"] for r in rows}
        companies = [{"symbol": s, "name": by_symbol.get(s, s)} for s in wanted]
    else:
        companies = _load_all_companies(sb)

    print(f"[refresh_ratios] refreshing ratio_no {sorted(rn for rn, _ in targets)} "
          f"x {len(companies)} company(ies) = {len(targets) * len(companies)} pairs "
          f"(bypassing both refresh_jobs and the Supabase fast-path read)")

    ok_count = err_count = 0
    for i, c in enumerate(companies, 1):
        symbol, name = c["symbol"], c.get("name") or c["symbol"]
        try:
            upsert_company(sb, symbol, name)
        except Exception as e:
            print(f"[refresh_ratios] company upsert failed for {symbol}: {e}")
        for ratio_no, fetcher in targets:
            ok = compute_one_forced(sb, symbol, name, ratio_no, fetcher)
            print(f"[refresh_ratios] {symbol} ratio_no={ratio_no} -> {'ok' if ok else 'ERROR'}")
            if ok:
                ok_count += 1
            else:
                err_count += 1
        print(f"[refresh_ratios] ({i}/{len(companies)} companies) {symbol} done")
        if sleep_between:
            time.sleep(sleep_between)

    print(f"[refresh_ratios] DONE — {ok_count} ok, {err_count} errors")
    return ok_count, err_count


def main():
    p = argparse.ArgumentParser(
        description="Force-refresh precomputed ratio rows in Supabase, bypassing skip_done and the fast-path read.")
    p.add_argument("--ratios", required=True, help="Comma-separated ratio_no list, e.g. 10,11,12,39")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", help="Comma-separated symbols, e.g. ITC,RELIANCE")
    group.add_argument("--all", action="store_true", help="Refresh across every company in the `companies` table")
    p.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between companies (politeness throttle)")
    args = p.parse_args()

    ratio_nos = [int(x) for x in args.ratios.split(",") if x.strip()]
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    refresh(ratio_nos, symbols=symbols, sleep_between=args.sleep)


if __name__ == "__main__":
    main()
