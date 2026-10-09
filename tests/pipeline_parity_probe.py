"""Pipeline PARITY probe (run by hand; the pytest guard is tests/test_pipeline_parity.py):

    python tests/pipeline_parity_probe.py [--out parity.json] [SYM:FY ...]

The same company and fiscal period must reach the ratio engine with the SAME facts whichever pipeline asked for them: the manual
document pipeline (tools.manual_mode active, page text from the uploaded-document cache) or the automatic pipeline (no manual mode,
PDF fetched by URL). Both read the same local Annual Report PDF here (network patched to the local file), so ANY difference in a
normalised fact is an extraction-path divergence. The probe extracts both ways with all disk caches off and reports every base fact
whose relative difference exceeds 0.5%.
"""
import argparse
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratio_regression_probe as P          # noqa: E402

DEFAULT = ["ANURAS:2026", "ANURAS:2025", "TCS:2025", "TCS:2026", "MARUTI:2025", "ITC:2025", "HINDUNILVR:2025", "ASIANPAINT:2025",
           "BATAINDIA:2025", "TITAN:2025", "LT:2025", "RELIANCE:2025", "ZEEL:2025", "NAZARA:2025", "ELECTHERM:2025",
           "INFY:2026", "BHARTIARTL:2026", "TATASTEEL:2025", "POLYCAB:2025", "ULTRACEMCO:2025"]
KEYS = ["revenue", "pat", "pat_total", "pbt", "finance_costs", "depreciation", "tax_expense", "eps", "shares_outstanding", "inventory",
        "receivables", "payables", "cash", "total_assets", "total_current_assets", "total_current_liabilities", "equity", "nci",
        "total_debt", "operating_cash_flow", "capex", "dividends_paid", "dps", "cogs"]


def _install_mode_aware_patches(ar):
    """`ratio_regression_probe._setup` memoises the extraction per (symbol, year, basis) and forces a local-file URL - both would hide
    exactly the divergence this probe looks for (the first mode to run would feed the second). Undo the memo and let the manual
    mode keep its real 'manual-upload://' resolution; only the automatic mode is pointed at the local PDF."""
    import tools.manual_mode as mm
    ar._get_extracted_financials_impl = _ORIG["impl"]
    local_find = ar._find_annual_report_pdf

    def find(sym, name, fy):
        if mm.is_manual_mode():
            return _ORIG["find"](sym, name, fy)
        return local_find(sym, name, fy)
    ar._find_annual_report_pdf = find


_ORIG = {}


def facts_for(sym, fy, manual):
    from tools.fundamental_fact_store import get_canonical_facts, clear_run_cache
    clear_run_cache()
    if manual:
        from tools.manual_mode import manual_mode
        with manual_mode():
            fs = get_canonical_facts(sym, sym, fy)
    else:
        fs = get_canonical_facts(sym, sym, fy)
    err = fs.facts.get("_error")
    out = {"_error": err if isinstance(err, str) else (getattr(err, "warnings", None) and err.warnings[0] if err else None),
           "_basis": fs.selection.selected_basis}
    for k in KEYS:
        f = fs.get(k)
        out[k] = None if f is None else f.value
    return out


def compare(a, b, tol=0.005):
    diffs = []
    for k in KEYS:
        x, y = a.get(k), b.get(k)
        if x is None and y is None:
            continue
        if x is None or y is None:
            diffs.append((k, x, y, "missing in one pipeline"))
        elif abs(x - y) > tol * max(abs(x), abs(y), 1e-9) + 0.011:
            diffs.append((k, x, y, f"{abs(x - y) / max(abs(x), abs(y), 1e-9):.1%}"))
    if a.get("_basis") != b.get("_basis"):
        diffs.append(("_basis", a.get("_basis"), b.get("_basis"), "statement basis differs"))
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="parity.json")
    ap.add_argument("symbols", nargs="*")
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import tools.annual_report_financials as ar0
    _ORIG["impl"], _ORIG["find"] = ar0._get_extracted_financials_impl, ar0._find_annual_report_pdf
    ar = P._setup(".")
    _install_mode_aware_patches(ar)
    from final_validation import ensure_text_cache
    res = {}
    for s in (a.symbols or DEFAULT):
        sym, fy = s.split(":")
        fy = int(fy)
        if not os.path.exists(os.path.join(P.DATA_ROOT, f"{sym}_{fy}.pdf")):
            print(f"{s:20} (no local PDF) skipped")
            continue
        try:
            ensure_text_cache(sym, fy)
            man = facts_for(sym, fy, True)
            aut = facts_for(sym, fy, False)
            d = compare(man, aut)
            res[s] = {"manual": man, "automatic": aut, "diffs": d}
            print(f"{s:20} diffs={len(d)} " + "; ".join(f"{k}: manual={x} auto={y}" for k, x, y, _ in d[:6]))
        except Exception as e:
            import traceback
            res[s] = {"error": traceback.format_exc()[-500:]}
            print(f"{s:20} ERROR {type(e).__name__}: {e}")
    json.dump(res, open(a.out, "w", encoding="utf-8"), indent=1, default=str)
    bad = [k for k, v in res.items() if v.get("diffs") or v.get("error")]
    print(f"\n{len(res)} company-years compared; {len(bad)} with divergence: {bad}")


if __name__ == "__main__":
    main()
