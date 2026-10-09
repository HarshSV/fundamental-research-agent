"""Universe integrity scan: runs the REAL extraction (automatic pipeline, cached PDFs, no network/DB) over every cached annual
report and checks the accounting identities that must hold in ANY filing. A violation is an extraction/perimeter defect
candidate - it is how defects such as 'whole-entity profit used as owners' profit' or 'NCI read as the total-equity
subtotal' are found without knowing the company.

    python tests/universe_scan.py --out universe_scan.json [--workers 4] [SYM:FY ...]

Checks (each only when its inputs exist):
  eps_pat      owners' profit  ~ Basic EPS x shares (+/-12%)            -> perimeter / share-count / EPS-basis defect
  bs_identity  Total liabilities + Total equity (incl. NCI) ~ Total assets (+/-1.5%) -> equity / NCI / liabilities defect
  nci_bounds   0 <= NCI <= Total equity incl. NCI
  pat_vs_total owners' profit <= whole-entity profit (when both)
  debt_bounds  0 <= Total debt <= Total assets
  ebitda_sane  EBITDA = EBIT + depreciation
  wc_identity  Working capital = Total current assets - Total current liabilities
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import traceback
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratio_regression_probe as P


def latest_jobs():
    best = {}
    for f in os.listdir(P.DATA_ROOT):
        m = re.fullmatch(r"([A-Z0-9]+)_(\d{4})\.pdf", f)
        if m and m.group(1) != "SYNTHCO":
            best[m.group(1)] = max(best.get(m.group(1), 0), int(m.group(2)))
    return sorted(best.items())


def check(sym, fy):
    P._setup(".")
    from tools.fundamental_fact_store import get_canonical_facts
    fs = get_canonical_facts(sym, sym, fy)
    out = {"sym": sym, "fy": fy, "basis": fs.selection.selected_basis, "viol": [], "n_facts": 0}
    if fs.facts.get("_error"):
        out["error"] = fs.facts["_error"][:120]
        return out
    g = lambda k: (fs.get(k).value if fs.get(k) is not None else None)
    gp = lambda k: (fs.get(k).prior_value if fs.get(k) is not None else None)
    out["n_facts"] = sum(1 for f in fs.facts.values() if hasattr(f, "value") and f.value is not None)
    pat, eps, sh = g("pat"), g("eps"), g("shares_outstanding")
    if pat and eps and sh:
        implied = eps * sh / 1e7
        if abs(implied - pat) > 0.12 * abs(pat):
            out["viol"].append(("eps_pat", f"owners PAT {pat:,.0f} vs EPS x shares {implied:,.0f}"))
    ta, tl, ef, eq, nci = g("total_assets"), g("total_liabilities"), g("equity_full"), g("equity"), g("nci")
    if ta and tl and ef is not None and abs(tl + ef - ta) > 0.015 * ta:
        out["viol"].append(("bs_identity", f"TL {tl:,.0f} + equity {ef:,.0f} != TA {ta:,.0f}"))
    if nci is not None and ef is not None and (nci < -0.5 or nci > ef + 0.5):
        out["viol"].append(("nci_bounds", f"NCI {nci:,.0f} vs total equity {ef:,.0f}"))
    pt = g("pat_total")
    if pat is not None and pt is not None and pat > pt + max(1.0, 0.002 * abs(pt)) and pt > 0:
        out["viol"].append(("pat_vs_total", f"owners {pat:,.0f} > whole-entity {pt:,.0f}"))
    td = g("total_debt")
    if td is not None and ta and (td < -0.5 or td > ta):
        out["viol"].append(("debt_bounds", f"debt {td:,.0f} vs assets {ta:,.0f}"))
    eb, ebit, dep = g("ebitda"), g("ebit"), g("depreciation")
    if eb is not None and ebit is not None and dep is not None and abs(eb - (ebit + dep)) > 0.01:
        out["viol"].append(("ebitda_sane", f"{eb:,.2f} != {ebit:,.2f} + {dep:,.2f}"))
    wc, ca, cl = g("working_capital"), g("total_current_assets"), g("total_current_liabilities")
    if wc is not None and ca is not None and cl is not None and abs(wc - (ca - cl)) > 0.01:
        out["viol"].append(("wc_identity", f"{wc:,.2f} != {ca:,.2f} - {cl:,.2f}"))
    # a violation is SAFE when every fact involved is already flagged (needs_review/estimated) - the status layer then stops any
    # dependent ratio from being 'verified'; it is UNSAFE when an involved fact still says VERIFIED
    involved = {"eps_pat": ("pat", "eps", "shares_outstanding"), "bs_identity": ("total_assets", "total_liabilities", "equity_full"),
                "nci_bounds": ("nci", "equity_full"), "pat_vs_total": ("pat", "pat_total"), "debt_bounds": ("total_debt",),
                "ebitda_sane": ("ebitda",), "wc_identity": ("working_capital",)}
    out["unflagged"] = [k for k, _ in out["viol"]
                        if any(fs.get(f) is not None and fs.get(f).value is not None and fs.get(f).status == "VERIFIED"
                               and not fs.get(f).estimated for f in involved[k])]
    out["facts"] = {k: g(k) for k in ("revenue", "pat", "pat_total", "eps", "shares_outstanding", "equity", "nci", "total_assets",
                                      "total_debt", "operating_cash_flow", "dps")}
    return out


def run(job):
    sym, fy = job
    t0 = time.time()
    try:
        r = check(sym, fy)
    except Exception:
        r = {"sym": sym, "fy": fy, "error": traceback.format_exc()[-300:], "viol": []}
    r["sec"] = round(time.time() - t0, 1)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="universe_scan.json")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("symbols", nargs="*")
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    jobs = [(s.split(":")[0], int(s.split(":")[1])) for s in a.symbols] if a.symbols else latest_jobs()
    res = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(run, jobs):
            res.append(r)
            tag = ("ERR " + r["error"][:60] if r.get("error") else ("OK" if not r["viol"] else
                   ("FLAGGED " if not r.get("unflagged") else "UNFLAGGED " + ",".join(r["unflagged"]) + " | ") + "; ".join(v[0] for v in r["viol"])))
            print(f"{r['sym']}:{r['fy']} {tag}", flush=True)
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    bad = [r for r in res if r.get("viol")]
    print(f"\n{len(res)} filings, {len([r for r in res if r.get('error')])} unreadable, {len(bad)} with violations, "
          f"{len([r for r in bad if r.get('unflagged')])} with a violation NOT yet flagged by the status layer")
    kinds = {}
    for r in bad:
        for k, _ in r["viol"]:
            kinds[k] = kinds.get(k, 0) + 1
    print("violation kinds:", kinds)


if __name__ == "__main__":
    main()
