"""
Precompute worker — the fix for the 3-4 minute "Reading audited filings..."
wait. Runs every Annual-Report-sourced ratio's `fetch_X` wrapper (from
tools/nse_xbrl.py) ONCE per company and writes the result into Supabase's
`ratio_values` table. After this has run, reads become a single fast SQL
SELECT instead of a live PDF download+parse.

Only ratios genuinely sourced from the Annual Report are stored here.
Market-price-dependent ratios (P/E, P/B, P/S, Dividend Yield, Earnings
Yield, EV/EBITDA — Sr No 24-29) are NOT stored as final multiples, because
market price changes continuously and "precomputing" it would go stale
immediately. Instead, their Annual-Report HALF is stored (EPS, Book Value
per Share, Revenue, Dividend per Share, Shares Outstanding — the slow part)
and combined with a fast live-quote fetch at request time. Similarly, the
pure client-side arithmetic ratios (DOH/DSO/DPO/CCC/Working Capital/ROA —
Sr No 2/4/6/9/13/17) aren't stored separately; they're cheap derivations
from the stored building blocks and stay computed at read time.

ratio_no mapping used in `ratio_values`:
  1,3,5,7,8,10,11,12,14,15,16,18,19,20,21,22,23  -> direct spec Sr Nos
  24 -> Basic EPS (Sr No 24's Annual-Report half)
  25 -> Book Value per Share (Sr No 25's Annual-Report half)
  26 -> Revenue from Operations (Sr No 26's Annual-Report half)
  27 -> Dividend per Share (Sr No 27's Annual-Report half)
  100 -> Equity Shares Outstanding (auxiliary — feeds Market Cap for 26/29,
         not a numbered spec ratio itself, kept in this table for locality)
Sr No 2,4,6,9,13,17,28,29 are intentionally NOT stored (derived at read
time from the rows above + a live quote).

Resumable via `refresh_jobs`: each (symbol, ratio_no) is marked done/error,
so a full-registry run can be safely stopped and restarted without
recomputing everything.
"""

import sys
import time
import traceback

sys.path.insert(0, ".")

from tools.supabase_client import get_client
from tools import nse_xbrl as x

# (ratio_no, wrapper_function) — every one of these takes (symbol, name) and
# returns the same {"applicable", "value", "unit", "confidence", "numerator",
# "denominator", "sources", "reason", "note", "period", "selected_period"}
# shape already used throughout the frontend.
RATIO_FETCHERS = [
    (1, x.fetch_inventory_turnover),
    (3, x.fetch_receivables_turnover),
    (5, x.fetch_payables_turnover),
    (7, x.fetch_asset_turnover),
    (8, x.fetch_working_capital_turnover),
    (10, x.fetch_current_ratio),
    (11, x.fetch_quick_ratio),
    (12, x.fetch_cash_ratio),
    (14, x.fetch_gross_profit_margin),
    (15, x.fetch_operating_profit_margin),
    (16, x.fetch_net_profit_margin),
    (18, x.fetch_return_on_equity),
    (19, x.fetch_return_on_capital_employed),
    (20, x.fetch_debt_to_equity),
    (21, x.fetch_debt_ratio),
    (22, x.fetch_interest_coverage_ratio),
    (23, x.fetch_financial_leverage_ratio),
    (24, x.fetch_eps),
    (25, x.fetch_book_value_per_share),
    (26, x.fetch_revenue_from_operations),
    (27, x.fetch_dividend_per_share),
    (100, x.fetch_shares_outstanding),
    # Ratios that tools/nse_xbrl.py already checks the DB for (try_db_ratio)
    # but were missing from this list, so they only ever got fast AFTER
    # someone happened to view them live once. Adding them here makes the
    # bulk precompute cover them proactively instead of relying on
    # opportunistic first-hit caching.
    (30, x.fetch_fixed_asset_turnover),
    (31, x.fetch_days_working_capital),
    (32, x.fetch_receivables_to_payables_ratio),
    (33, x.fetch_net_debt_to_ebitda),
    (34, x.fetch_debt_service_coverage_ratio),
    (35, x.fetch_cash_flow_coverage_ratio),
    (36, x.fetch_free_cash_flow),
    (38, x.fetch_fcf_margin),
    (39, x.fetch_operating_cash_flow_ratio),
    (40, x.fetch_capex_intensity),
    (41, x.fetch_ocf_to_net_profit),
    (42, x.fetch_roic),
    (43, x.fetch_effective_tax_rate),
    (44, x.fetch_contribution_margin),
    (45, x.fetch_eps_growth),
    (47, x.fetch_dividend_payout_ratio),
    (53, x.fetch_operating_cash_flow),
    (55, x.fetch_altman_z_score_components),
    (56, x.fetch_piotroski_f_score),
    (57, x.fetch_beneish_m_score),
    (58, x.fetch_net_interest_margin),
    (59, x.fetch_casa_ratio),
    (60, x.fetch_gross_npa_pct),
    (61, x.fetch_net_npa_pct),
    (63, x.fetch_capital_adequacy_ratio),
    (65, x.fetch_cost_to_income_ratio),
    (66, x.fetch_beta),
]


def _extract_fiscal_year(result):
    """selected_period is '31-Mar-2025' -> fiscal_year 2025. Falls back to
    the current year if genuinely absent (e.g. a hard N/A with no periods
    at all) so the row still has a valid, non-null primary key."""
    sp = result.get("selected_period") or ""
    try:
        return int(sp.split("-")[-1])
    except Exception:
        import datetime
        return datetime.date.today().year


def upsert_company(sb, symbol, name):
    sb.table("companies").upsert({"symbol": symbol, "name": name}).execute()


def compute_one(sb, symbol, name, ratio_no, fetcher):
    """Runs one ratio's fetch for one company, upserts into ratio_values,
    marks the refresh_jobs row done/error. Never raises — errors are
    recorded, not propagated, so one bad company/ratio (or a dropped
    connection, e.g. from the machine sleeping mid-request) can't kill the
    run. The fallback error-write is itself guarded, since a network blip
    can just as easily kill that write as the original fetch."""
    try:
        r = fetcher(symbol, name)
        fiscal_year = _extract_fiscal_year(r)
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
            "period_label": r.get("period") or r.get("selected_period"),
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
            print(f"[precompute] could not even record the error for {symbol} ratio_no={ratio_no}: {e2}")
        return False


def _load_done_set(sb):
    """Paginated fetch of every 'done' (symbol, ratio_no) pair. A single
    .execute() call caps out at Supabase's default page size (~1000 rows) —
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
    """All 22 ratios for one company, sequentially (the first fetch warms
    that company's shared Annual-Report PDF cache in annual_report_financials
    ._get_extracted_financials, so the rest of this company's ratios hit disk
    cache — that locality is why this stays a single function instead of also
    fanning ratio_no out across threads)."""
    try:
        upsert_company(sb, symbol, name)
    except Exception as e:
        print(f"[precompute] company upsert failed for {symbol}: {e}")
        return 0, 0

    ok_count, err_count = 0, 0
    for ratio_no, fetcher in RATIO_FETCHERS:
        if (symbol, ratio_no) in done_set:
            continue
        try:
            ok = compute_one(sb, symbol, name, ratio_no, fetcher)
        except Exception as e:
            print(f"[precompute] unexpected failure on {symbol} ratio_no={ratio_no}, skipping: {e}")
            ok = False
        print(f"[precompute] {symbol} ratio_no={ratio_no} -> {'ok' if ok else 'ERROR'}")
        if ok:
            ok_count += 1
        else:
            err_count += 1
    return ok_count, err_count


def run(companies, sleep_between=0.0, skip_done=True, workers=1):
    """companies: list of {"symbol": ..., "name": ...}. Resumable — rows
    already marked 'done' in refresh_jobs are skipped unless skip_done=False.

    Designed to survive the machine sleeping mid-run: a dropped connection
    (DNS/socket errors from Windows suspending network mid-request) is
    caught per-company rather than being allowed to kill the whole process,
    with a short backoff so a burst of "just woke up, network's not back
    yet" failures doesn't spam thousands of instant errors before the
    connection actually recovers.

    workers > 1 processes multiple COMPANIES concurrently (each company's 22
    ratios still run sequentially within its own thread, so the shared
    per-company PDF cache still gets warmed once and reused). This is
    I/O-bound work (PDF download + Supabase writes), so threads — not
    processes — give the speedup without extra memory overhead. Keep this
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
            print(f"[precompute] ({done_companies}/{total_companies} companies) {symbol} done — {ok_count} ok, {err_count} errors")
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
            print(f"[precompute] ({done_companies}/{total_companies} companies) {symbol} done — {ok_count} ok, {err_count} errors")

            if ok_count > 0:
                consecutive_failures = 0
            elif err_count > 0:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    backoff = min(30, 2 * consecutive_failures)
                    print(f"[precompute] {consecutive_failures} companies in a row with zero successes (likely network down) — pausing {backoff}s")
                    time.sleep(backoff)


if __name__ == "__main__":
    # Small smoke-test batch by default — pass company symbols on the CLI to
    # run a custom batch, e.g.:
    #   python tools/precompute_worker.py MARUTI DMART TATASTEEL
    import json
    test_companies = [
        {"symbol": "MARUTI", "name": "Maruti Suzuki India Limited"},
        {"symbol": "DMART", "name": "Avenue Supermarts Limited"},
        {"symbol": "TATASTEEL", "name": "Tata Steel Limited"},
    ]
    if len(sys.argv) > 1:
        test_companies = [{"symbol": s.upper(), "name": s.upper()} for s in sys.argv[1:]]
    run(test_companies)
