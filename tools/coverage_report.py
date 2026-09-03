"""
Coverage report - answers "across all NSE companies, which (symbol, ratio)
pairs are missing, errored, or never attempted?" in one run.

Pulls companies, refresh_jobs, and ratio_values from Supabase into memory
and diffs them against the full expected symbol x ratio_no matrix (mirrors
the RATIO_FETCHERS list in tools/precompute_worker.py).

Usage:
    python tools/coverage_report.py            # console summary
    python tools/coverage_report.py --csv out.csv   # also write per-gap CSV
"""

import argparse
import csv
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from tools.supabase_client import get_client
from tools.precompute_worker import RATIO_FETCHERS

RATIO_NOS = [r for r, _ in RATIO_FETCHERS]
RATIO_NAMES = {r: fn.__name__.replace("fetch_", "") for r, fn in RATIO_FETCHERS}

PAGE_SIZE = 1000


def fetch_all(sb, table, columns):
    rows = []
    start = 0
    while True:
        resp = sb.table(table).select(columns).range(start, start + PAGE_SIZE - 1).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="write full gap list to this CSV path")
    args = ap.parse_args()

    sb = get_client()

    print("[coverage] loading companies...")
    companies = fetch_all(sb, "companies", "symbol,name,registry_status,registry_error")
    print(f"[coverage] {len(companies)} companies")

    print("[coverage] loading refresh_jobs...")
    jobs = fetch_all(sb, "refresh_jobs", "symbol,ratio_no,status,last_error")
    print(f"[coverage] {len(jobs)} refresh_jobs rows")

    print("[coverage] loading ratio_values...")
    values = fetch_all(sb, "ratio_values", "symbol,ratio_no,applicable,value,confidence,estimated")
    print(f"[coverage] {len(values)} ratio_values rows")

    job_status = {(j["symbol"], j["ratio_no"]): j for j in jobs}
    value_rows = defaultdict(list)
    for v in values:
        value_rows[(v["symbol"], v["ratio_no"])].append(v)

    unresolved_companies = [c for c in companies if c.get("registry_status") != "resolved"]
    resolved_symbols = [c["symbol"] for c in companies if c.get("registry_status") == "resolved"]

    never_attempted = []
    errored = []
    applicable_no_value = []
    per_ratio_error_count = defaultdict(int)
    per_ratio_never_count = defaultdict(int)
    per_ratio_ok_count = defaultdict(int)

    for symbol in resolved_symbols:
        for ratio_no in RATIO_NOS:
            key = (symbol, ratio_no)
            job = job_status.get(key)
            if job is None:
                never_attempted.append((symbol, ratio_no))
                per_ratio_never_count[ratio_no] += 1
                continue
            if job["status"] == "error":
                errored.append((symbol, ratio_no, job.get("last_error") or ""))
                per_ratio_error_count[ratio_no] += 1
                continue
            if job["status"] == "done":
                per_ratio_ok_count[ratio_no] += 1
                for v in value_rows.get(key, []):
                    if v.get("applicable") and v.get("value") is None:
                        applicable_no_value.append((symbol, ratio_no))

    total_pairs = len(resolved_symbols) * len(RATIO_NOS)
    fully_ok_companies = 0
    for symbol in resolved_symbols:
        if all(job_status.get((symbol, r), {}).get("status") == "done" for r in RATIO_NOS):
            fully_ok_companies += 1

    print("\n===== COVERAGE SUMMARY =====")
    print(f"Total companies in registry: {len(companies)}")
    print(f"  resolved (has AR/filing found): {len(resolved_symbols)}")
    print(f"  unresolved (registry_status != 'resolved'): {len(unresolved_companies)}")
    print(f"\nExpected (symbol x ratio) pairs among resolved companies: {total_pairs}")
    print(f"  done: {total_pairs - len(never_attempted) - len(errored)}")
    print(f"  errored: {len(errored)}")
    print(f"  never attempted (no refresh_jobs row): {len(never_attempted)}")
    print(f"  applicable=true but value is null (edge case): {len(applicable_no_value)}")
    print(f"\nCompanies with ALL {len(RATIO_NOS)} ratios done: {fully_ok_companies} / {len(resolved_symbols)}")

    print("\n--- Per-ratio breakdown ---")
    print(f"{'ratio_no':>8}  {'name':<28} {'done':>6} {'error':>6} {'never':>6}")
    for r in RATIO_NOS:
        print(f"{r:>8}  {RATIO_NAMES[r]:<28} {per_ratio_ok_count[r]:>6} {per_ratio_error_count[r]:>6} {per_ratio_never_count[r]:>6}")

    if unresolved_companies:
        print(f"\n--- Unresolved companies (first 20 of {len(unresolved_companies)}) ---")
        for c in unresolved_companies[:20]:
            print(f"  {c['symbol']:<15} {c.get('registry_status'):<15} {c.get('registry_error') or ''}")

    if errored:
        print(f"\n--- Sample errors (first 20 of {len(errored)}) ---")
        for symbol, ratio_no, err in errored[:20]:
            print(f"  {symbol:<15} ratio_no={ratio_no:<4} {RATIO_NAMES.get(ratio_no, ''):<28} {err[:100]}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["gap_type", "symbol", "ratio_no", "ratio_name", "detail"])
            for c in unresolved_companies:
                w.writerow(["unresolved_company", c["symbol"], "", "", f"{c.get('registry_status')}: {c.get('registry_error') or ''}"])
            for symbol, ratio_no in never_attempted:
                w.writerow(["never_attempted", symbol, ratio_no, RATIO_NAMES.get(ratio_no, ""), ""])
            for symbol, ratio_no, err in errored:
                w.writerow(["error", symbol, ratio_no, RATIO_NAMES.get(ratio_no, ""), err])
            for symbol, ratio_no in applicable_no_value:
                w.writerow(["applicable_no_value", symbol, ratio_no, RATIO_NAMES.get(ratio_no, ""), ""])
        print(f"\n[coverage] full gap list written to {args.csv}")


if __name__ == "__main__":
    main()
