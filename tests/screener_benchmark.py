"""Generates docs/screener_benchmark_2026-10.{md,json}: Navrist vs Screener (annual, consolidated, same fiscal year) for the four statement-level
figures that tests/source_verification_scan.py compares (revenue, whole-entity profit, effective tax rate, borrowings), one row per company-year
and metric, with the classified reason for every difference.  Built only from docs/source_verification_2026-10.json plus the cause table below;
`tests/test_screener_benchmark_artefact.py` fails when the committed files are stale.

    python tests/screener_benchmark.py --out-dir docs

Scope (stated in the output): this is a statement-level benchmark.  Ratio-level (all 68) Screener comparison on identical inputs exists only for
ANURAS FY2026 (docs/anuras_fy2026_audit.md).  Screener was not assumed to be right: where it differs, the difference is traced to a definition."""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

METRICS = {
    "revenue": ("Revenue from operations (Rs Cr)", "Revenue from operations as printed in the statement of profit and loss",
                "Screener 'Sales' (annual, consolidated; whole crore)"),
    "net_profit_whole_entity": ("Net profit, whole entity (Rs Cr)", "Profit for the year (owners + NCI), continuing operations (policy M)",
                                "Screener 'Net Profit' (annual, consolidated)"),
    "tax_pct": ("Effective tax rate (%)", "Tax expense / profit before tax as printed", "Screener 'Tax %' row (its own PBT, whole percent)"),
    "debt_vs_borrowings": ("Total debt vs Screener Borrowings (Rs Cr)", "Borrowings + lease liabilities + debt-like other financial liabilities",
                           "Screener 'Borrowings' (balance-sheet borrowings only)"),
}
VALID, EXTRACT, REVIEW = ("Valid methodology difference", "Source extraction issue", "Needs review / insufficient evidence")
# (company-year, metric) -> (class, root cause, decision)
CAUSE = {
    ("ITC:2025", "revenue"): (VALID, "Screener nets excise duty: 81,612.78 - 6,289.44 = 75,323.34 (Screener 75,323).",
                              "Keep Revenue from operations as printed; label the difference."),
    ("ITC:2025", "net_profit_whole_entity"): (VALID, "Screener 35,052 includes the INR 15,016 Cr discontinued-operations (hotels demerger) gain; Navrist uses continuing "
                                              "operations so profit and EPS share one perimeter (policy M).", "Keep policy M; label the difference."),
    ("ITC:2025", "tax_pct"): (REVIEW, "Screener's tax % is computed on its own PBT (after exceptional items); Navrist uses tax / PBT as printed.",
                              "Left as is; PBT-before/after-exceptional definition not settled."),
    ("BHARTIARTL:2025", "tax_pct"): (REVIEW, "One-off deferred-tax and exceptional items: Screener's own PBT differs from the printed PBT.", "Needs review."),
    ("BHARTIARTL:2026", "tax_pct"): (REVIEW, "As FY2025 (exceptional items shift Screener's PBT).", "Needs review."),
    ("HINDUNILVR:2025", "revenue"): (VALID, "Screener 'Sales' 61,328 excludes other operating revenue (63,121 - 1,793).",
                                     "Keep Revenue from operations as printed; label the difference."),
    ("TITAN:2025", "debt_vs_borrowings"): (VALID, "12,967 + 'Gold on loan' 7,810 = Screener 20,777 exactly. Gold on loan is an interest-bearing metal loan that "
                                            "Navrist does not count as debt.", "OPEN DECISION: not changed without a policy ruling; difference is reproducible."),
    ("RELIANCE:2025", "revenue"): (VALID, "Screener nets excise duty (980,136 - 15,443 = 964,693) and further small deductions; Screener shows 962,820.",
                                   "Keep Revenue from operations as printed; label the difference."),
    ("RELIANCE:2025", "debt_vs_borrowings"): (VALID, "Navrist adds lease liabilities (109,313) that Screener's borrowings exclude: 347,530 + 109,313 = 456,843 "
                                              "(Screener 374,313 also differs by other items).", "Keep leases in Total Debt (decision documented in docs/ratio_contract.md)."),
    ("LT:2025", "debt_vs_borrowings"): (EXTRACT, "Conglomerate with a financial-services balance sheet: borrowings of the financing business sit outside the "
                                        "lines the reader takes (96,214 vs 132,409). Flagged by the identity checks.", "Unresolved - debt-dependent ratios for L&T are not source-verified."),
}


def build():
    sv = json.load(open(os.path.join(ROOT, "docs", "source_verification_2026-10.json"), encoding="utf-8"))
    rows = []
    for cy, v in sorted(sv.items()):
        if v.get("error"):
            continue
        for m, (label, nav_formula, ref_formula) in METRICS.items():
            p = v["publisher"][m]
            nav, ref = p["navrist"], p["screener"]
            diff = None if nav is None or ref is None else round(nav - ref, 4)
            pct = None if diff is None or not ref else round(diff / ref * 100, 3)
            if p["agrees"]:
                cls, cause, decision = ("Matches under the same definition", "-", "No action")
            else:
                cls, cause, decision = CAUSE[(cy, m)]
            rows.append({"company_year": cy, "metric": label, "basis": v["basis"], "period_class": "annual (non-TTM)", "navrist": nav,
                         "screener": ref, "abs_diff": diff, "pct_diff": pct, "navrist_formula": nav_formula, "reference_formula": ref_formula,
                         "classification": cls, "root_cause": cause, "source_evidence": "docs/source_verification_2026-10.json (filing lineage + publisher)",
                         "decision": decision})
    return rows


def render(rows):
    L = ["# Navrist vs Screener - annual, non-TTM, consolidated benchmark (2026-10)", "",
         "Generated by `tests/screener_benchmark.py` from `docs/source_verification_2026-10.json`. **Scope: four statement-level figures per company-year "
         "(revenue, whole-entity profit, effective tax rate, borrowings) for 15 company-years.** A full 68-ratio comparison on identical inputs exists only "
         "for ANURAS FY2026 (`docs/anuras_fy2026_audit.md`). Screener's TTM column is never used; Screener is not assumed correct.", "",
         "**Tolerance:** Screener prints whole crore / whole percent, so a figure agrees when it equals Screener's after that rounding "
         "(the flag computed by the verification scan).", "",
         "| Company-year | Metric | Basis | Period | Navrist | Screener | Abs diff | % diff | Navrist formula | Screener formula | Classification | Root cause | Decision |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['company_year']} | {r['metric']} | {r['basis']} | {r['period_class']} | {r['navrist']} | {r['screener']} | {r['abs_diff']} | "
                 f"{r['pct_diff']} | {r['navrist_formula']} | {r['reference_formula']} | {r['classification']} | {r['root_cause']} | {r['decision']} |")
    n = len(rows)
    ok = sum(1 for r in rows if r["classification"].startswith("Matches"))
    L += ["", f"**{ok} of {n} comparisons match; {n - ok} differ and each is classified above.**"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "docs"))
    a = ap.parse_args()
    rows = build()
    json.dump({"rows": rows}, open(os.path.join(a.out_dir, "screener_benchmark_2026-10.json"), "w", encoding="utf-8"), indent=1)
    open(os.path.join(a.out_dir, "screener_benchmark_2026-10.md"), "w", encoding="utf-8").write(render(rows))
    print("wrote", len(rows), "rows")
