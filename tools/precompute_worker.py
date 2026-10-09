"""
Precompute worker - the fix for the 3-4 minute "Reading audited filings..."
wait. Runs the UNIVERSAL calculation engine for every applicable ratio in
`tools.fundamental_ratio_registry.RATIOS`, ONCE per company, and writes each
result into Supabase's `ratio_values` table. After this has run, reads
become a single fast SQL SELECT instead of a live PDF download+parse.

Production path (spec §14/§25):

    company identity -> fiscal year -> statement selection
    -> canonical FactSet (one extraction per company)
    -> tools.ratio_calculation_engine.calculate_ratio, per registry entry
    -> tools.db_ratio_reader.write_db_ratio (records the ACTUAL basis +
       extraction_version used, never a hardcoded assumption)

This worker no longer calls `tools.nse_xbrl.fetch_X` wrappers directly or
computes anything independently - every value written here came from the
same engine the generic `/api/v1/ratio/{ratio_key}` endpoint uses, so a
precomputed row and a live request for the same (symbol, ratio, FY, basis)
can never disagree.

Market-price-dependent ratios (P/E, P/B, ...) and the few genuinely
non-AR ratios (Beta, Promoter Pledge %, Free Float %) ARE still computed and
written here (the engine handles them), but their live-price/market-data
component means the STORED figure can go stale as soon as price moves - the
`period_label`/computed_at timestamp make that visible; the frontend's own
live-quote layer is unaffected by this (it doesn't read `ratio_values` for
those in the first place, only market_price.py).

Resumable via `refresh_jobs`: each (symbol, sr_no) is marked done/error, so
a full-registry run can be safely stopped and restarted without recomputing
everything.
"""

import sys
import time

sys.path.insert(0, ".")

from tools.supabase_client import get_client
from tools.fundamental_ratio_registry import RATIOS
from tools.ratio_calculation_engine import calculate_ratio
from tools.fundamental_fact_store import clear_run_cache, EXTRACTION_VERSION
from tools.db_ratio_reader import write_db_ratio


def _resolve_fiscal_year(symbol, name):
    """Resolves the latest fiscal year with a filed Annual Report ONCE per
    company - every ratio for this company shares this same year, instead
    of each ratio independently re-discovering it (spec §4)."""
    try:
        from tools.annual_report_financials import list_annual_report_years
        years = list_annual_report_years(symbol, name) or []
        return max(years) if years else None
    except Exception as e:
        print(f"[precompute] could not resolve fiscal year for {symbol}: {e}")
        return None


def upsert_company(sb, symbol, name):
    sb.table("companies").upsert({"symbol": symbol, "name": name}).execute()


def compute_one(sb, symbol, name, fiscal_year, spec):
    """Runs the universal engine for one ratio, one company, writes the
    result + marks the refresh_jobs row done/error. Never raises."""
    ratio_key, sr_no = spec["ratio_key"], spec["sr_no"]
    try:
        result = calculate_ratio(ratio_key, symbol, name, fiscal_year)
        out = {
            "selected_period": f"31-Mar-{result.get('financial_year') or fiscal_year}",
            "applicable": bool(result.get("applicable")),
            "value": result.get("value"),
            "unit": result.get("unit"),
            "period": f"FY{result.get('financial_year') or fiscal_year}",
            "reason": result.get("reason") or result.get("missing_dependency"),
            "note": result.get("calculation_trace"),
            "sources": result.get("source_documents"),
        }
        consolidated = result.get("statement_basis") == "CONSOLIDATED"
        # ONE version for writer and readers: nse_xbrl's `try_db_ratio` filters on the extraction-LOGIC version
        # (`_current_extraction_version`), so rows must be stamped with that same number - stamping them with the
        # fact store's own counter meant a written row could never match, nor ever be invalidated by a logic bump.
        from tools.annual_report_financials import _EXTRACTION_LOGIC_VERSION
        write_db_ratio(symbol, sr_no, out, consolidated=consolidated, extraction_version=int(_EXTRACTION_LOGIC_VERSION))
        sb.table("refresh_jobs").upsert({
            "symbol": symbol, "ratio_no": sr_no,
            "status": "done", "last_run_at": "now()", "last_error": None,
        }).execute()
        return True
    except Exception as e:
        try:
            sb.table("refresh_jobs").upsert({
                "symbol": symbol, "ratio_no": sr_no,
                "status": "error", "last_run_at": "now()", "last_error": str(e)[:500],
            }).execute()
        except Exception as e2:
            print(f"[precompute] could not even record the error for {symbol} ratio_no={sr_no}: {e2}")
        return False


def _load_done_set(sb):
    """Paginated fetch of every 'done' (symbol, ratio_no) pair. A single
    .execute() call caps out at Supabase's default page size (~1000 rows) -
    with tens of thousands of done rows that silently truncated done_set,
    causing run() to re-download/re-parse companies that were already
    finished. range() pages through the full table instead."""
    done_set = set()
    start = 0
    page_size = 1000
    while True:
        resp = (sb.table("refresh_jobs").select("symbol,ratio_no")
                .eq("status", "done").range(start, start + page_size - 1).execute())
        batch = resp.data or []
        done_set.update((row["symbol"], row["ratio_no"]) for row in batch)
        if len(batch) < page_size:
            break
        start += page_size
    return done_set


def _run_one_company(sb, symbol, name, done_set):
    """Every registry ratio for one company, sequentially. Resolves the
    fiscal year ONCE (not per ratio), then relies on
    `tools.fundamental_fact_store`'s own per-(symbol, fiscal_year) run-cache
    (cleared at the end of this function) so the underlying Annual Report is
    extracted once for the whole company, not once per ratio - this is why
    ratios still run sequentially within one company rather than also
    fanning ratio_no out across threads."""
    try:
        upsert_company(sb, symbol, name)
    except Exception as e:
        print(f"[precompute] company upsert failed for {symbol}: {e}")
        return 0, 0

    fiscal_year = _resolve_fiscal_year(symbol, name)
    if fiscal_year is None:
        print(f"[precompute] {symbol}: no Annual Report filings found, skipping")
        return 0, 0

    ok_count, err_count = 0, 0
    try:
        for spec in RATIOS:
            sr_no = spec["sr_no"]
            if (symbol, sr_no) in done_set:
                continue
            ok = compute_one(sb, symbol, name, fiscal_year, spec)
            print(f"[precompute] {symbol} sr_no={sr_no} ({spec['ratio_key']}) -> {'ok' if ok else 'ERROR'}")
            if ok:
                ok_count += 1
            else:
                err_count += 1
    finally:
        # This company's canonical FactSet must never be reused for the
        # NEXT company in the loop (spec's no-cross-company-contamination
        # rule) - cleared unconditionally, even on an unexpected failure.
        clear_run_cache()
    return ok_count, err_count


def run(companies, sleep_between=0.0, skip_done=True, workers=1):
    """companies: list of {"symbol": ..., "name": ...}. Resumable - rows
    already marked 'done' in refresh_jobs are skipped unless skip_done=False.

    Designed to survive the machine sleeping mid-run: a dropped connection
    (DNS/socket errors from Windows suspending network mid-request) is
    caught per-company rather than being allowed to kill the whole process,
    with a short backoff so a burst of "just woke up, network's not back
    yet" failures doesn't spam thousands of instant errors before the
    connection actually recovers.

    workers > 1 processes multiple COMPANIES concurrently (each company's
    ratios still run sequentially within its own thread, so the shared
    per-company FactSet cache still gets warmed once and reused). This is
    I/O-bound work (PDF download + Supabase writes), so threads - not
    processes - give the speedup without extra memory overhead. Keep this
    modest (3-5): NSE/BSE will rate-limit or block a client that opens too
    many concurrent connections, which would make the run slower overall,
    not faster."""
    sb = get_client()

    done_set = set()
    if skip_done:
        try:
            done_set = _load_done_set(sb)
            print(f"[precompute] loaded {len(done_set)} already-done pairs, will skip them")
        except Exception as e:
            print(f"[precompute] could not load existing refresh_jobs, starting fresh: {e}")

    total_companies = len(companies)

    if workers <= 1:
        done_companies = 0
        for c in companies:
            symbol, name = c["symbol"], c.get("name", c["symbol"])
            ok_count, err_count = _run_one_company(sb, symbol, name, done_set)
            done_companies += 1
            print(f"[precompute] ({done_companies}/{total_companies} companies) {symbol} done - {ok_count} ok, {err_count} errors")
            if sleep_between:
                time.sleep(sleep_between)
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    done_companies = 0
    consecutive_failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_one_company, sb, c["symbol"], c.get("name", c["symbol"]), done_set): c
            for c in companies
        }
        for fut in as_completed(futures):
            c = futures[fut]
            symbol = c["symbol"]
            try:
                ok_count, err_count = fut.result()
            except Exception as e:
                print(f"[precompute] company thread crashed for {symbol}: {e}")
                ok_count, err_count = 0, 1
            done_companies += 1
            print(f"[precompute] ({done_companies}/{total_companies} companies) {symbol} done - {ok_count} ok, {err_count} errors")

            if ok_count > 0:
                consecutive_failures = 0
            elif err_count > 0:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    backoff = min(30, 2 * consecutive_failures)
                    print(f"[precompute] {consecutive_failures} companies in a row with zero successes (likely network down) - pausing {backoff}s")
                    time.sleep(backoff)


def _make_legacy_fetcher(ratio_key):
    """Compatibility shim (spec §15's "legacy API -> universal engine, not
    an independent calculation"): several other tools
    (`tools/coverage_report.py`, `tools/refresh_ratios.py`) still call
    `precompute_worker.RATIO_FETCHERS`'s `fetcher(symbol, name[, to_date])`
    directly. Rather than duplicate their (real, still-needed) resumable/
    forced-refresh orchestration logic, this wraps the SAME universal
    `calculate_ratio` engine behind the old call signature, returning the
    same dict shape the old `nse_xbrl.fetch_X` wrappers did - no
    independent calculation lives in this wrapper. `to_date`, if given, is
    honored as an explicit fiscal year request (unlike the old fetchers,
    the new engine has no Supabase fast-path to bypass, so there is no
    staleness bug to route around here - every call genuinely recomputes)."""
    def _fetch(symbol, name=None, to_date=None):
        fiscal_year = None
        if to_date:
            try:
                fiscal_year = int(str(to_date).split("-")[-1])
            except Exception:
                fiscal_year = None
        if fiscal_year is None:
            fiscal_year = _resolve_fiscal_year(symbol, name)
        if fiscal_year is None:
            return {"applicable": False, "reason": "No Annual Report filings found for this company."}
        r = calculate_ratio(ratio_key, symbol, name, fiscal_year)
        return {
            "applicable": r.get("applicable"), "value": r.get("value"), "unit": r.get("unit"),
            "confidence": None, "period": r.get("statement_basis"),
            "selected_period": f"31-Mar-{r.get('financial_year') or fiscal_year}",
            "numerator": None, "denominator": None, "sources": r.get("source_documents"),
            "reason": r.get("reason") or r.get("missing_dependency"), "note": r.get("calculation_trace"),
            "consolidated": r.get("statement_basis") == "CONSOLIDATED",
        }
    _fetch.__name__ = f"fetch_{ratio_key}"
    return _fetch


# Backward-compatible view over the registry for tools that still address
# ratios by (sr_no, callable) - e.g. tools/coverage_report.py,
# tools/refresh_ratios.py. Every callable here delegates to the SAME
# universal engine `_run_one_company` above uses; nothing here re-derives a
# financial fact independently.
RATIO_FETCHERS = [(spec["sr_no"], _make_legacy_fetcher(spec["ratio_key"])) for spec in RATIOS]


if __name__ == "__main__":
    # Small smoke-test batch by default - pass company symbols on the CLI to
    # run a custom batch, e.g.:
    #   python tools/precompute_worker.py MARUTI DMART TATASTEEL
    test_companies = [
        {"symbol": "MARUTI", "name": "Maruti Suzuki India Limited"},
        {"symbol": "DMART", "name": "Avenue Supermarts Limited"},
        {"symbol": "TATASTEEL", "name": "Tata Steel Limited"},
    ]
    if len(sys.argv) > 1:
        test_companies = [{"symbol": s.upper(), "name": s.upper()} for s in sys.argv[1:]]
    run(test_companies)
