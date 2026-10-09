"""
Multi-company ratio regression probe (NOT a pytest module - run it by hand):

    python tests/ratio_regression_probe.py --root <repo root to test> --out <results.json> [--symbols A:2025,B:2026 ...]

Runs the REAL extraction on the locally cached Annual Report PDFs (cache/ar_pdfs, no network, no cache writes,
no DB writes) in the automatic-pipeline mode, calls every `fetch_*_from_annual_report` ratio/fact function the
dashboard endpoints use, and - when the tested tree contains `tools.ratio_contract` - also computes the full
contract set with a fixed test price. Point `--root` at a `git worktree` of an older commit to get a
before/after comparison from the SAME harness.

The result JSON is {"SYMBOL:FY": {"fetch": {fn: {...}}, "contract": {...}, "facts": {...}, "error": ...}}.
"""
import argparse
import concurrent.futures
import json
import os
import sys
import time
import traceback
import warnings

DATA_ROOT = os.environ.get("NAVRIST_AR_PDF_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "ar_pdfs")

# the same universe the remediation was regression-tested on (category -> symbol:FY)
UNIVERSE = {
    "manufacturing": ["ASIANPAINT:2025", "AARTIIND:2025", "MARUTI:2025", "TATASTEEL:2025", "ULTRACEMCO:2025", "POLYCAB:2025"],
    "IT services": ["TCS:2025", "INFY:2025", "HCLTECH:2025"],
    "bank": ["HDFCBANK:2025", "ICICIBANK:2025", "SBIN:2025", "KOTAKBANK:2025"],
    "NBFC / HFC": ["POONAWALLA:2025", "PNBHOUSING:2025"],
    "holding / investment company": ["THEINVEST:2025", "RELIANCE:2025", "LT:2025"],
    "large leases": ["BATAINDIA:2025", "ETERNAL:2025", "TITAN:2025", "JUBLFOOD:2026"],
    "NCI / dividend payer": ["HINDUNILVR:2025", "ITC:2025", "ANURAS:2025", "ANURAS:2026"],
    "no dividend / loss / negative FCF": ["ZEEL:2025", "SUZLON:2025", "NAZARA:2025", "CAMPUS:2025"],
    "small / standalone / sparse disclosure": ["ELECTHERM:2025", "XELPMOC:2025", "PARACABLES:2025", "GANESHCP:2025", "APEX:2025"],
}

FETCH_FUNCS = [
    "inventory_turnover", "receivables_turnover", "payables_turnover", "asset_turnover", "working_capital_turnover",
    "current_ratio", "quick_ratio", "cash_ratio", "gross_profit_margin", "operating_profit_margin", "net_profit_margin",
    "return_on_equity", "return_on_capital_employed", "debt_to_equity", "debt_ratio", "interest_coverage_ratio",
    "financial_leverage_ratio", "fixed_asset_turnover", "days_working_capital", "receivables_to_payables_ratio",
    "net_debt_to_ebitda", "debt_service_coverage_ratio", "cash_flow_coverage_ratio", "free_cash_flow", "fcf_margin",
    "operating_cash_flow_ratio", "capex_intensity", "ocf_to_net_profit", "roic", "effective_tax_rate",
    "contribution_margin", "eps_growth", "book_value_per_share", "dividend_payout_ratio", "altman_z_score_components",
    "piotroski_f_score", "beneish_m_score", "eps", "shares_outstanding", "revenue_from_operations", "dividend_per_share",
    "ebitda", "total_debt", "cash_and_equivalents",
    # bank-specific (unchanged formulas; run to prove the shared extraction change did not regress them)
    "net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct", "capital_adequacy_ratio", "cost_to_income_ratio",
]


def _setup(root):
    warnings.filterwarnings("ignore")
    sys.path.insert(0, root)
    import tools.annual_report_financials as ar

    class _Resp:
        def __init__(self, b):
            self.content = b

    def fake_get(url, *a, **k):
        sym, fy = url.rsplit("/", 1)[1].rsplit("_", 1)
        with open(os.path.join(DATA_ROOT, f"{sym}_{fy}.pdf"), "rb") as fh:
            return _Resp(fh.read())

    orig_impl = ar._get_extracted_financials_impl
    memo = {}

    def impl(symbol, name, fy, consolidated=True):
        k = (symbol.upper(), fy, consolidated)
        if k not in memo:
            memo[k] = orig_impl(symbol, name, fy, consolidated)
        return memo[k]

    ar._get_extracted_financials_impl = impl
    ar._find_annual_report_pdf = lambda sym, name, fy: f"file://local/{sym}_{fy}"
    ar._sess = lambda: type("S", (), {"get": staticmethod(fake_get)})()
    ar._read_cache = lambda k: None
    ar._write_cache = lambda k, v: None
    return ar


def _slim(out):
    if not isinstance(out, dict):
        return {"raw": str(out)[:200]}
    keep = ("applicable", "status", "value", "value_raw", "unit", "confidence", "estimated", "reason", "period")
    d = {k: out.get(k) for k in keep if k in out}
    if isinstance(d.get("reason"), str):
        d["reason"] = d["reason"][:160]
    n, dd = out.get("numerator") or {}, out.get("denominator") or {}
    d["num"], d["den"] = n.get("value_cr"), dd.get("value_cr")
    d["warnings"] = len(out.get("warnings") or [])
    return d


def run_one(args):
    root, sym, fy = args
    t0 = time.time()
    res = {"fetch": {}, "contract": {}, "facts": {}, "error": None}
    try:
        ar = _setup(root)
        for name in FETCH_FUNCS:
            fn = getattr(ar, f"fetch_{name}_from_annual_report", None)
            if fn is None:
                continue
            try:
                res["fetch"][name] = _slim(fn(sym, sym, fy, True))
            except Exception as e:
                res["fetch"][name] = {"exception": f"{type(e).__name__}: {e}"}
        try:
            from tools import ratio_contract as rc
            from tools.fundamental_fact_store import get_canonical_facts
            fs = get_canonical_facts(sym, sym, fy)
            res["facts"] = {k: {"v": f.value, "p": f.prior_value, "status": f.status, "est": f.estimated, "tag": f.source_tag}
                            for k, f in fs.facts.items() if hasattr(f, "value")}
            res["basis"] = fs.selection.selected_basis
            res["acquisition"] = (fs.extras or {}).get("acquisition")
            market = {"price": 100.0, "source": "regression-test"}
            for k, r in rc.compute_all(fs, market).items():
                res["contract"][k] = {"value_raw": r.get("value_raw"), "status": r.get("status"), "conf": r.get("confidence"),
                                       "reason": (r.get("reason") or "")[:140], "warn": len(r.get("warnings") or [])}
        except ImportError:
            pass
    except Exception:
        res["error"] = traceback.format_exc()[-1500:]
    res["seconds"] = round(time.time() - t0, 1)
    return f"{sym}:{fy}", res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    syms = a.symbols or [s for v in UNIVERSE.values() for s in v]
    jobs = []
    for s in syms:
        sym, fy = s.split(":")
        if os.path.exists(os.path.join(DATA_ROOT, f"{sym}_{fy}.pdf")):
            jobs.append((a.root, sym, int(fy)))
        else:
            print("skip (no cached PDF):", s)
    out = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as ex:
        for key, res in ex.map(run_one, jobs):
            out[key] = res
            print(f"{key:18s} {res['seconds']:6.1f}s  fetch={len(res['fetch'])} contract={len(res['contract'])} "
                  f"{'ERROR' if res['error'] else 'ok'}", flush=True)
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(out, fh, default=str)
    print("done ->", a.out)


if __name__ == "__main__":
    main()
