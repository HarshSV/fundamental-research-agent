"""SOURCE-VERIFICATION scan (run by hand): which company-years have actually been checked against evidence, and how.

    python tests/source_verification_scan.py --out docs/source_verification_2026-10.json

For every company-year with a cached Annual Report PDF it records, using the AUTOMATIC pipeline (identical to the manual one, see
tests/test_pipeline_parity.py):
  * LINEAGE   - how many base facts (current AND prior year) are found printed in the report itself (INR million x10 / crore, Indian
                or Western grouping). This proves the extractor read figures that exist in the document, not that they are the right rows.
  * PUBLISHER - revenue, whole-entity profit, effective tax rate and borrowings compared with Screener's annual consolidated figures for
                the SAME fiscal year (fetched during the audit; integers as Screener shows them). A gap is explained, not forced to zero.
Nothing here asserts that every ratio of those companies is correct: see docs/ratio_audit_matrix_2026-10.md for the per-ratio verdicts."""
import argparse
import json
import os
import re
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

# Screener annual consolidated (Rs Cr): (sales, net profit [whole entity], tax %, borrowings). Fetched from screener.in during the audit.
SCREENER = {
    ("TCS", 2025): (255324, 48797, 25, 9392), ("TCS", 2026): (267021, 49454, 24, 11283),
    ("MARUTI", 2025): (152913, 14500, 26, 87),
    ("ITC", 2025): (75323, 35052, 16, 285),
    ("BHARTIARTL", 2025): (172985, 37481, 2, 213642), ("BHARTIARTL", 2026): (210973, 33823, 25, 195412),
    ("HINDUNILVR", 2025): (61328, 10671, 26, 1648),
    ("TITAN", 2025): (60456, 3337, 26, 20777),
    ("BATAINDIA", 2025): (3489, 331, 22, 1446),
    ("INFY", 2025): (162990, 26750, 29, 8227), ("INFY", 2026): (178650, 29474, 26, 9176),
    ("RELIANCE", 2025): (962820, 81309, 24, 374313),
    ("LT", 2025): (255734, 17673, 25, 132409),
    ("ANURAS", 2025): (1437, 160, 19, 1373), ("ANURAS", 2026): (2365, 222, 13, 1867),
}
# why a known gap is not an extraction error
EXPLAIN = {
    ("ITC", 2025): "Screener's net profit 35,052 includes the one-off gain on the hotels demerger (discontinued operations); Navrist uses continuing operations (policy M).",
    ("BHARTIARTL", 2025): "Screener tax 2% reflects a one-off deferred-tax credit in its own tax % row.",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="source_verification.json")
    ap.add_argument("symbols", nargs="*")
    a = ap.parse_args()
    import ratio_regression_probe as P
    import tools.annual_report_financials as ar0
    orig_impl = ar0._get_extracted_financials_impl
    ar = P._setup(".")
    ar._get_extracted_financials_impl = orig_impl
    from tools.fundamental_fact_store import get_canonical_facts, clear_run_cache
    import ratio_audit_matrix as M
    import fitz

    out = {}
    for (sym, fy), ref in SCREENER.items():
        if a.symbols and f"{sym}:{fy}" not in a.symbols:
            continue
        path = os.path.join(P.DATA_ROOT, f"{sym}_{fy}.pdf")
        if not os.path.exists(path):
            continue
        clear_run_cache()
        fs = get_canonical_facts(sym, sym, fy)
        if fs.facts.get("_error"):
            out[f"{sym}:{fy}"] = {"error": "no statements extracted"}
            continue
        doc = fitz.open(path)
        pages = [re.sub(r"\s+", " ", doc[i].get_text()) for i in range(len(doc))]
        lin = M.lineage(fs, pages)
        found = [k for k, v in lin.items() if v.get("found") is True]
        missed = [k for k, v in lin.items() if v.get("found") is False]
        na = [k for k, v in lin.items() if v.get("found") is None]
        g = lambda k: (fs.get(k).value if fs.get(k) is not None else None)         # noqa: E731
        rev, ptot, pat = g("revenue"), g("pat_total"), g("pat")
        tax, pbt, debt = g("tax_expense"), g("pbt"), g("total_debt")
        s_rev, s_np, s_tax, s_debt = ref
        taxp = (tax / pbt * 100) if tax is not None and pbt else None
        ptot_eff = ptot if ptot is not None else pat
        rows = {
            "revenue": (rev, s_rev, rev is not None and abs(rev - s_rev) <= 0.005 * s_rev),
            "net_profit_whole_entity": (ptot_eff, s_np, ptot_eff is not None and abs(ptot_eff - s_np) <= 0.01 * abs(s_np) + 1),
            "tax_pct": (taxp, s_tax, taxp is not None and abs(taxp - s_tax) <= 1.5),
            "debt_vs_borrowings": (debt, s_debt, debt is not None and abs(debt - s_debt) <= 0.10 * s_debt + 5),
        }
        out[f"{sym}:{fy}"] = {
            "basis": fs.selection.selected_basis, "lineage_found": len(found), "lineage_missed": missed, "lineage_not_extracted": na,
            "lineage_by_fact": {k: v.get("found") for k, v in lin.items()},
            "publisher": {k: {"navrist": v[0], "screener": v[1], "agrees": bool(v[2])} for k, v in rows.items()},
            "explained_gap": EXPLAIN.get((sym, fy)),
        }
        print(f"{sym}:{fy} lineage {len(found)}/{len(lin)} missed={missed} na={na} | " +
              " ".join(f"{k}={'OK' if v[2] else 'GAP'}" for k, v in rows.items()), flush=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1, default=str)


if __name__ == "__main__":
    main()
