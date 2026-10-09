"""Final global validation: runs the REAL 68-ratio orchestrator (`document_analysis_engine.run_fundamental_analysis`) over
real cached Annual Reports (no DB writes, no network except what the shareholding/beta providers need) and records, for
every ratio of every company: calculated?, value, status, formula version, basis, provenance, reason - then checks the
cross-company invariants.

    python tests/final_validation.py --out final_validation.json [SYM:FY:SECTOR ...]

The market price is a fixed test value (100.0) so runs are comparable; Beta / Promoter Pledge / Free Float use the live
providers (they have no filing to read) unless --offline is given.
"""
import argparse
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratio_regression_probe as P

# category -> (symbol, fiscal year, NSE sector label used by the pipeline's applicability gate)
UNIVERSE = [
    ("manufacturing", "ASIANPAINT", 2025, "Paints"),
    ("IT services", "TCS", 2025, "IT - Software"),
    ("bank", "HDFCBANK", 2025, "Banks"),
    ("bank", "ICICIBANK", 2025, "Banks"),
    ("bank", "KOTAKBANK", 2025, "Banks"),
    ("bank", "SBIN", 2025, "Banks"),
    ("NBFC", "POONAWALLA", 2025, "NBFC"),
    ("NBFC / HFC (deposit-taking)", "PNBHOUSING", 2025, "NBFC"),
    ("NCI + dividend payer", "HINDUNILVR", 2025, "FMCG"),
    ("leases", "BATAINDIA", 2025, "Footwear"),
    ("leases", "TITAN", 2025, "Consumer Durables"),
    ("negative FCF / no dividend", "ZEEL", 2025, "Media"),
    ("dividend payer", "ITC", 2025, "FMCG"),
    ("no dividend / loss", "NAZARA", 2025, "Media"),
    ("missing disclosures / small", "ELECTHERM", 2025, "Electricals"),
    ("holding / consolidated+standalone", "RELIANCE", 2025, "Oil & Gas"),
    ("conglomerate", "LT", 2025, "Construction"),
]


NAMES = {"ASIANPAINT": "Asian Paints Limited", "TCS": "Tata Consultancy Services Limited", "HDFCBANK": "HDFC Bank Limited",
         "ICICIBANK": "ICICI Bank Limited", "KOTAKBANK": "Kotak Mahindra Bank Limited", "SBIN": "State Bank of India",
         "POONAWALLA": "Poonawalla Fincorp Limited", "PNBHOUSING": "PNB Housing Finance Limited",
         "HINDUNILVR": "Hindustan Unilever Limited", "BATAINDIA": "Bata India Limited", "TITAN": "Titan Company Limited",
         "ZEEL": "Zee Entertainment Enterprises Limited", "ITC": "ITC Limited", "NAZARA": "Nazara Technologies Limited",
         "ELECTHERM": "Electrotherm (India) Limited", "RELIANCE": "Reliance Industries Limited", "LT": "Larsen & Toubro Limited"}


def ensure_text_cache(sym, fy):
    """The manual/uploaded-document pipeline reads page text from cache/ar_text (written when a document is uploaded). Build
    that cache from the real cached PDF - exactly what ar_document_cache.get_ar_pages does for a downloaded filing."""
    import re
    import fitz
    import tools.ar_document_cache as adc
    from tools.annual_report_financials import _page_text
    if adc._read_text_cache(sym, fy) is not None:
        return
    path = os.path.join(P.DATA_ROOT, f"{sym}_{fy}.pdf")
    doc = fitz.open(path)
    pages = []
    for page in doc:
        try:
            t = _page_text(page)
        except Exception:
            t = ""
        t = re.sub(r"\s+", " ", t)
        pages.append("".join(ch for ch in t if ch >= " "))
    doc.close()
    adc._write_text_cache(sym, fy, pages, f"manual-upload://{sym}_{fy}")


def run_company(sym, fy, sector, offline=False):
    ensure_text_cache(sym, fy)
    import tools.ar_document_cache as adc
    import tools.document_analysis_engine as dae
    import tools.market_price as mp
    import tools.nse_sector_map as ns
    import tools.supabase_client as sc

    captured = {}

    class Q:
        def __init__(s, n):
            s.n = n

        def select(s, *a, **k):
            return s

        def eq(s, *a, **k):
            return s

        def limit(s, *a, **k):
            return s

        def upsert(s, rows, **k):
            captured.setdefault(s.n, []).extend(rows)
            return s

        def execute(s):
            class R:
                data = []
            return R()

    class SB:
        def table(s, n):
            return Q(n)

    sc.get_client = lambda: SB()
    mp.get_live_price = lambda *a, **k: {"ltp": 100.0, "source": "regression-test"}
    ns.get_nse_sector = lambda s: sector
    dae.get_nse_sector = ns.get_nse_sector
    orig = adc.get_ar_pages
    adc.get_ar_pages = lambda s, n, fiscal_year=None, y=None: orig(s, n, fiscal_year or y or fy)
    # the pipeline walks "the newest cached year"; pin it to the filing under test so every ratio uses the SAME document
    adc.manual_cached_years = lambda symbol: [fy]
    if offline:
        import tools.nse_xbrl as nx
        for fn in ("fetch_beta", "fetch_promoter_pledge_pct", "fetch_free_float_pct"):
            setattr(nx, fn, lambda *a, **k: {"applicable": False, "status": "insufficient_data", "reason": "offline run"})
    summary = dae.run_fundamental_analysis(sym, NAMES.get(sym, sym))
    return captured.get("fundamental_analysis_results", []), summary


def row_view(r, reg):
    md = next((i for i in r["inputs"] if i.get("name") == "_metadata"), {})
    bd = md.get("breakdown") or {}
    spec = reg[r["ratio_key"]]
    return {"sr_no": spec["sr_no"], "ratio_key": r["ratio_key"], "label": r["label"], "value": r["value"], "unit": r["unit"],
            "status": md.get("status_detail") or r["status"], "formula_version": md.get("formula_version"),
            "basis": md.get("statement_basis") or (bd.get("basis")), "period": bd.get("period"),
            "calculated": r["value"] is not None, "reason": (md.get("reason") or "")[:200],
            "has_breakdown": bool(bd), "reconciles": bd.get("reconciles"),
            "n_inputs": len(bd.get("inputs") or []), "source": bd.get("source"),
            "warnings": len(md.get("warnings") or []), "depends_on": spec.get("depends_on", [])}


def invariants(rows, sector):
    from tools.ratio_contract import FORMULA_VERSION
    bad = []
    by_key = {r["ratio_key"]: r for r in rows}
    rank = {"verified": 0, "needs_review": 1, "not_meaningful": 2, "insufficient_data": 3, "not_disclosed": 4, "not_applicable": 5}
    for r in rows:
        k, v, st = r["ratio_key"], r["value"], r["status"]
        if len(rows) != 68:
            bad.append(("-", f"{len(rows)} rows instead of 68"))
            break
        if v is not None and st in ("insufficient_data", "not_disclosed", "not_applicable"):
            bad.append((k, f"value {v} with unavailable status {st}"))
        if v is None and st in ("verified", "needs_review"):
            bad.append((k, f"{st} without a value"))
        if r["formula_version"] != FORMULA_VERSION:
            bad.append((k, f"formula_version {r['formula_version']}"))
        if v is not None and st in ("verified", "needs_review"):
            if not r["has_breakdown"]:
                bad.append((k, "numeric result without a breakdown"))
            elif r["reconciles"] is False or (r["reconciles"] is None and r["sr_no"] != 67):    # 67: inferred 0% has no calculation
                bad.append((k, f"breakdown reconciles={r['reconciles']}"))
        for d in r["depends_on"]:                                   # a derived ratio is never better than its parents
            dr = by_key.get(next((x["ratio_key"] for x in rows if x["sr_no"] == d), None))
            if dr and st == "verified" and rank.get(dr["status"], 0) > 1 and dr["status"] != "not_meaningful":
                bad.append((k, f"verified although parent Sr {d} is {dr['status']}"))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="final_validation.json")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("symbols", nargs="*")
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    P._setup(".")
    from tools.fundamental_ratio_registry import BY_RATIO_KEY
    jobs = UNIVERSE
    if a.symbols:
        jobs = []
        for s in a.symbols:
            sym, fy, *sec = s.split(":")
            known = next((u for u in UNIVERSE if u[1] == sym), None)
            jobs.append((known[0] if known else "custom", sym, int(fy), sec[0] if sec else (known[3] if known else "Other")))
    out = {}
    for cat, sym, fy, sector in jobs:
        try:
            rows, summary = run_company(sym, fy, sector, a.offline)
            views = [row_view(r, BY_RATIO_KEY) for r in rows]
            views.sort(key=lambda r: r["sr_no"])
            out[f"{sym}:{fy}"] = {"category": cat, "sector": sector, "summary": summary, "rows": views,
                                  "violations": invariants(views, sector)}
            print(f"{sym}:{fy} [{cat}] {summary} violations={len(out[f'{sym}:{fy}']['violations'])}")
            for v in out[f"{sym}:{fy}"]["violations"]:
                print("     !!", *v)
        except Exception as e:
            import traceback
            out[f"{sym}:{fy}"] = {"category": cat, "error": traceback.format_exc()[-600:]}
            print(f"{sym}:{fy} [{cat}] ERROR {type(e).__name__}: {e}")
    json.dump(out, open(a.out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
