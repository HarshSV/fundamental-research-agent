"""
Qualitative coverage report - answers "across a sample of NSE companies,
does every A-D qualitative topic actually compute, and what confidence_tag
does each land on?" in one run.

Unlike tools/coverage_report.py (which diffs Supabase's own refresh_jobs/
ratio_values tables against expectation - a DB-side check of what's
ALREADY been computed), this script actively CALLS every top-level A-D
compute_* function for each sampled symbol, live, right now. That's the
only way to answer "does the code actually work for company X" for a
company nobody has ever opened in the app before - a pure DB diff would
just show every untouched company as "never attempted," which doesn't
tell you whether it would succeed if run.

Each compute_* function is deliberately built to "never raise" (every
sub-point catches its own fetch/parse exceptions and degrades to a
NOT_DISCLOSED/SEARCH_INCONCLUSIVE confidence tag) - so a genuine Python
exception escaping here is itself a real, reportable bug, not just an
honest data gap. The CSV distinguishes:
  - error       -> the compute_* call itself raised (a real code bug)
  - ok_tag=X    -> it returned normally with confidence_tag X (could be
                   SINGLE_SOURCE/VERIFIED - real data found - or
                   SEARCH_INCONCLUSIVE/NOT_FOUND - an honest gap, not a bug)

Usage:
    python tools/qualitative_coverage_report.py --sample 100 --csv coverage_qual.csv
    python tools/qualitative_coverage_report.py --symbols RELIANCE,TCS --csv out.csv
"""

import argparse
import csv
import random
import sys
import time
import traceback

sys.path.insert(0, ".")

import tools.qualitative_engine as qe

TOPICS = [
    ("A.1", "business_model_clarity", qe.compute_a1_business_model_clarity),
    ("A.2", "competitive_moat", qe.compute_a2_competitive_moat),
    ("A.3", "revenue_model_quality", qe.compute_a3_revenue_model_quality),
    ("A.4", "product_lifecycle_stage", qe.compute_a4_product_lifecycle_stage),
    ("A.5", "pricing_power", qe.compute_a5_pricing_power),
    ("A.6", "margin_sustainability", qe.compute_a6_margin_sustainability),
    ("B.1", "founder_ceo_track_record", qe.compute_b1_founder_ceo_track_record),
    ("B.2", "management_incentives", qe.compute_b2_management_incentives),
    ("B.3", "management_bench_depth", qe.compute_b3_management_bench_depth),
    ("B.4", "communication_quality", qe.compute_b4_communication_quality),
    ("B.5", "execution_credibility", qe.compute_b5_execution_credibility),
    ("B.6", "culture", qe.compute_b6_culture),
    ("C.1", "promoter_shareholding", qe.compute_c1_promoter_shareholding),
    ("C.2", "promoter_pledging", qe.compute_c2_promoter_pledging),
    ("C.3", "related_party_transactions", qe.compute_c3_related_party_transactions),
    ("C.4", "group_structural_complexity", qe.compute_c4_group_structural_complexity),
    ("C.5", "board_composition", qe.compute_c5_board_composition),
    ("C.6", "auditor_relationships", qe.compute_c6_auditor_relationships),
    ("C.7", "capital_allocation", qe.compute_c7_capital_allocation),
    ("C.8", "minority_shareholder_treatment", qe.compute_c8_minority_shareholder_treatment),
    ("D.1", "insider_selling", qe.compute_d1_insider_activity),
    ("D.2", "insider_buying", qe.compute_d2_insider_buying),
    ("D.3", "secondary_transactions_dilution", qe.compute_d3_secondary_transactions),
    ("D.4", "lockin_releases", qe.compute_d4_lockin_releases),
    ("D.5", "promoter_loans", qe.compute_d5_promoter_loans),
    ("D.6", "pledge_signals", qe.compute_d6_pledge_signals),
]


def fetch_sample_companies(n, symbols_filter=None):
    from tools.supabase_client import get_client
    sb = get_client()
    rows, start, page = [], 0, 1000
    while True:
        resp = sb.table("companies").select("symbol,name").eq("registry_status", "resolved").range(start, start + page - 1).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    if symbols_filter:
        wanted = set(s.strip().upper() for s in symbols_filter)
        rows = [r for r in rows if r["symbol"].upper() in wanted]
        return rows
    random.shuffle(rows)
    return rows[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100, help="number of companies to randomly sample")
    ap.add_argument("--symbols", help="comma-separated explicit symbol list, overrides --sample")
    ap.add_argument("--csv", default="coverage_qualitative.csv", help="output CSV path")
    ap.add_argument("--force", action="store_true", help="bypass the 30-day cache (slower, always live)")
    args = ap.parse_args()

    symbols_filter = args.symbols.split(",") if args.symbols else None
    companies = fetch_sample_companies(args.sample, symbols_filter)
    print(f"[qual-coverage] running {len(TOPICS)} topics x {len(companies)} companies = {len(TOPICS) * len(companies)} calls")

    rows = []
    per_topic_tag_count = {t[0]: {} for t in TOPICS}
    per_topic_error_count = {t[0]: 0 for t in TOPICS}
    t0 = time.time()

    for i, c in enumerate(companies):
        sym, name = c["symbol"], c.get("name")
        for topic_id, topic_key, fn in TOPICS:
            try:
                result = fn(sym, name, force=args.force)
                tag = (result or {}).get("confidence_tag") or "NONE"
                rows.append([sym, name, topic_id, topic_key, "ok", tag, ""])
                per_topic_tag_count[topic_id][tag] = per_topic_tag_count[topic_id].get(tag, 0) + 1
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                rows.append([sym, name, topic_id, topic_key, "error", "", err])
                per_topic_error_count[topic_id] += 1
                print(f"[qual-coverage] ERROR {sym} {topic_id}: {err}")
                traceback.print_exc(limit=2)
        if (i + 1) % 5 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(companies) - i - 1) / rate if rate > 0 else 0
            print(f"[qual-coverage] {i+1}/{len(companies)} companies done ({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "topic_id", "topic_key", "status", "confidence_tag", "error"])
        w.writerows(rows)
    print(f"\n[qual-coverage] wrote {len(rows)} rows to {args.csv}")

    print("\n===== SUMMARY (by topic) =====")
    print(f"{'topic':<6} {'errors':>7}  tags")
    for topic_id, _, _ in TOPICS:
        tags = ", ".join(f"{k}={v}" for k, v in sorted(per_topic_tag_count[topic_id].items()))
        print(f"{topic_id:<6} {per_topic_error_count[topic_id]:>7}  {tags}")

    total_errors = sum(per_topic_error_count.values())
    total_calls = len(TOPICS) * len(companies)
    print(f"\nTotal calls: {total_calls}, total errors: {total_errors} ({100*total_errors/total_calls:.1f}%)")


if __name__ == "__main__":
    main()
