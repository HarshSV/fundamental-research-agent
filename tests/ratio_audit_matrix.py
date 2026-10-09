"""68-ratio AUDIT MATRIX generator (NOT a pytest module - run by hand):

    python tests/ratio_audit_matrix.py [--out-dir docs]

For ANURAS FY2026 (consolidated, the real cached Annual Report, manual-upload pipeline, fixed test price) it audits all 68 ratios:

  1. authoritative formula         - tools/fundamental_ratio_registry.RATIOS
  2. implementation formula        - tools/ratio_contract.SPEC + the result's own breakdown formula / expression
  3. numerator source / inputs     - the result's breakdown inputs (fact, page, statement, method, period, basis)
  4. independent recomputation     - every non-bank ratio is recomputed HERE from the raw normalised facts with a separate,
                                     hand-written implementation of the authoritative formula and compared (relative 1e-6)
  5. input lineage                 - every base fact (current + prior year) is searched for, in the AR's own printed figures,
                                     after unit conversion (rupees million x 10); derived facts are re-derived from their parts
  6. missing-input behaviour       - for each input a ratio reads, the input is blanked on a synthetic filing: the ratio must be
                                     withheld, unchanged, or fall back with a flag - never silently change value as 'verified'
  7. dependency chain              - PARENTS + facts actually read (spy)
  8. regression-test coverage      - AST scan of tests/ (specific tests naming the ratio + generic all-ratio loops)
  9. trusted-source comparison     - Screener annual consolidated figures (fetched for ANURAS) where a comparable one exists,
                                     plus the cross-company final-validation run when present
 10. verdict PASS / NEEDS REVIEW / FAIL

It writes <out-dir>/ratio_audit_matrix_2026-10.md and .json.
"""
import argparse
import ast
import dataclasses
import glob
import json
import math
import os
import re
import sys
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")

PRICE = 1165.0
SYMBOL, FY = "ANURAS", 2026

# Screener (screener.in/company/ANURAS/consolidated, annual columns, fetched during the audit): value as shown, comparable basis note
SCREENER = {
    "revenue": 2365.0, "pat_total": 222.0, "borrowings": 1867.0, "eps": 14.94, "tax_pct": 13.0, "roe_pct": 5.55, "payout_pct": 10.0,
    "dio": 490.0, "dso": 148.0, "dpo": 261.0, "ccc": 377.0, "wc_days": 108.0, "roce_pct": 7.0, "opm_pct": 22.0, "pe": 72.1,
}


# ------------------------------------------------------------------------------------------------ helpers
def load_facts():
    from tools.manual_mode import manual_mode
    manual_mode().__enter__()
    from tools.fundamental_fact_store import get_canonical_facts
    return get_canonical_facts(SYMBOL, SYMBOL, FY)


def fv(fs, k):
    f = fs.get(k)
    return (None, None) if f is None else (f.value, f.prior_value)


def avg(fs, k):
    c, p = fv(fs, k)
    return None if c is None or p is None else (c + p) / 2.0


# ------------------------------------------------------------------------------------------------ independent oracle
def oracle(fs, market):
    """Separate, hand-written implementation of the AUTHORITATIVE formulas (registry text) from raw normalised facts."""
    g = lambda k: fv(fs, k)[0]            # noqa: E731
    gp = lambda k: fv(fs, k)[1]           # noqa: E731
    price = market["price"]
    shares = g("shares_outstanding")
    mcap = price * shares / 1e7
    rev, cogs = g("revenue"), g("cogs")
    ebit, ebitda = g("ebit"), g("ebitda")
    debt, cash = g("total_debt"), g("cash")
    o = {}
    o["inventory_turnover"] = cogs / avg(fs, "inventory")
    o["days_inventory_outstanding"] = 365.0 / o["inventory_turnover"]
    o["receivables_turnover"] = rev / avg(fs, "receivables")
    o["days_sales_outstanding"] = 365.0 / o["receivables_turnover"]
    o["payables_turnover"] = g("purchases") / avg(fs, "payables")
    o["days_payables_outstanding"] = 365.0 / o["payables_turnover"]
    o["asset_turnover"] = rev / avg(fs, "total_assets")
    wc_c, wc_p = g("total_current_assets") - g("total_current_liabilities"), gp("total_current_assets") - gp("total_current_liabilities")
    o["working_capital_turnover"] = rev / ((wc_c + wc_p) / 2.0)
    o["cash_conversion_cycle"] = o["days_sales_outstanding"] + o["days_inventory_outstanding"] - o["days_payables_outstanding"]
    o["current_ratio"] = g("total_current_assets") / g("total_current_liabilities")
    o["quick_ratio"] = (g("total_current_assets") - g("inventory")) / g("total_current_liabilities")
    bk = (fs.extras or {}).get("other_bank_balances_breakup") or {}
    o["cash_ratio"] = (cash + bk.get("unrestricted_cur", g("other_bank_balances") or 0.0)) / g("total_current_liabilities")
    o["working_capital"] = wc_c
    o["gross_profit_margin"] = (rev - cogs) / rev * 100
    o["operating_profit_margin"] = (g("pbt") + g("finance_costs")) / rev * 100
    o["net_profit_margin"] = g("pat") / rev * 100
    o["roa"] = g("pat") / avg(fs, "total_assets") * 100
    o["roe"] = g("pat") / avg(fs, "equity") * 100
    ce = lambda s: s("total_assets") - s("total_current_liabilities")        # noqa: E731
    o["roce"] = (g("pbt") + g("finance_costs")) / ((ce(g) + ce(gp)) / 2.0) * 100
    o["debt_to_equity"] = debt / (g("equity") + g("nci"))
    o["debt_ratio"] = debt / g("total_assets")
    o["interest_coverage_ratio"] = (g("pbt") + g("finance_costs")) / g("finance_costs")
    o["financial_leverage_ratio"] = avg(fs, "total_assets") / ((g("equity") + g("nci") + gp("equity") + gp("nci")) / 2.0)
    o["pe_ratio"] = price / g("eps")
    bvps = g("equity") * 1e7 / shares
    o["pb_ratio"] = price / bvps
    o["ps_ratio"] = mcap / rev
    o["dividend_yield"] = g("dps") / price * 100
    o["earnings_yield"] = g("eps") / price * 100
    o["ev_to_ebitda"] = (mcap + debt - cash) / (g("pbt") + g("finance_costs") + g("depreciation"))
    nfa = lambda s: s("ppe") + s("rou_assets") + s("cwip") + s("intangibles")      # noqa: E731
    o["fixed_asset_turnover"] = rev / ((nfa(g) + nfa(gp)) / 2.0)
    o["days_working_capital"] = (wc_c + wc_p) / 2.0 / rev * 365.0
    o["receivables_to_payables"] = g("receivables") / g("payables")
    o["net_debt_to_ebitda"] = (debt - cash) / ebitda
    # 34 DSCR: gross principal repayments are not disclosed -> must be withheld (checked separately)
    o["cash_flow_coverage_ratio"] = g("operating_cash_flow") / debt
    capex = abs(g("capex_ppe_purchase")) + (abs(g("capex_intangible_purchase")) if g("capex_intangible_purchase") is not None else 0.0)
    o["free_cash_flow"] = g("operating_cash_flow") - capex
    o["fcf_yield"] = o["free_cash_flow"] / mcap * 100
    o["fcf_margin"] = o["free_cash_flow"] / rev * 100
    o["ocf_ratio"] = g("operating_cash_flow") / g("total_current_liabilities")
    o["capex_intensity"] = capex / rev * 100
    o["ocf_to_net_profit"] = g("operating_cash_flow") / g("pat_total")
    tax_rate = g("tax_expense") / g("pbt")
    o["roic"] = ebit * (1 - tax_rate) / (debt + g("equity") + g("nci") - cash) * 100
    o["effective_tax_rate"] = tax_rate * 100
    comps = (fs.extras or {}).get("components") or {}
    items = ((fs.extras or {}).get("variable_opex_note") or {}).get("items") or {}
    direct = (fs.extras or {}).get("direct_expenses")
    var = sum(v[0] for v in comps.values()) + (direct[0] if direct else sum(v[0] for v in items.values()))
    o["contribution_margin"] = (rev - var) / rev * 100
    o["eps_growth_rate"] = (g("eps") / gp("eps") - 1) * 100
    o["bvps"] = bvps
    paid = (fs.extras or {}).get("dividend_components", {}).get("owners_cr")
    o["dividend_payout_ratio"] = (paid if paid is not None else g("dividends_paid")) / g("pat") * 100
    o["retention_ratio"] = 100 - o["dividend_payout_ratio"]
    o["sustainable_growth_rate"] = o["roe"] * o["retention_ratio"] / 100
    o["peg_ratio"] = o["pe_ratio"] / o["eps_growth_rate"]
    ev = mcap + debt - cash
    o["ev_to_sales"] = ev / rev
    o["ev_to_fcf"] = ev / o["free_cash_flow"]            # negative FCF -> contract reports not_meaningful (value kept for display)
    o["price_to_cash_flow"] = mcap / g("operating_cash_flow")
    o["graham_number"] = math.sqrt(22.5 * g("eps") * bvps)
    tl = g("total_assets") - (g("equity") + g("nci"))
    o["altman_z_score"] = (1.2 * wc_c / g("total_assets") + 1.4 * g("retained_earnings") / g("total_assets")
                           + 3.3 * ebit / g("total_assets") + 0.6 * mcap / tl + 1.0 * rev / g("total_assets"))
    ta_c, ta_p = fv(fs, "total_assets")
    gpf = lambda s: (s("revenue") - s("cogs")) / s("revenue")          # noqa: E731
    tests = [
        g("pat") / ta_c > 0,
        g("pat") / ta_c > gp("pat") / ta_p,
        g("operating_cash_flow") > 0,
        g("operating_cash_flow") > g("pat_total"),
        debt / ta_c < fv(fs, "total_debt")[1] / ta_p,
        g("total_current_assets") / g("total_current_liabilities") > gp("total_current_assets") / gp("total_current_liabilities"),
        shares <= gp("shares_outstanding") * 1.001,
        gpf(g) > gpf(gp),
        rev / ta_c > gp("revenue") / ta_p,
    ]
    o["piotroski_f_score"] = float(sum(bool(t) for t in tests))
    gpm = lambda s: (s("revenue") - s("cogs")) / s("revenue")          # noqa: E731
    dsri = (g("receivables") / rev) / (gp("receivables") / gp("revenue"))
    gmi = gpm(gp) / gpm(g)
    aqi = (1 - (g("total_current_assets") + g("ppe")) / ta_c) / (1 - (gp("total_current_assets") + gp("ppe")) / ta_p)
    sgi = rev / gp("revenue")
    depi = (gp("depreciation") / (gp("ppe") + gp("depreciation"))) / (g("depreciation") / (g("ppe") + g("depreciation")))
    sgai = (g("other_expenses") / rev) / (gp("other_expenses") / gp("revenue"))
    tata = (g("pat_total") - g("operating_cash_flow")) / ta_c
    lvgi = ((debt + g("total_current_liabilities")) / ta_c) / ((fv(fs, "total_debt")[1] + gp("total_current_liabilities")) / ta_p)
    o["beneish_m_score"] = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai
                            + 4.679 * tata - 0.327 * lvgi)
    return o


# ------------------------------------------------------------------------------------------------ lineage
BASE_FACTS = ["revenue", "pat", "pat_total", "pbt", "tax_expense", "finance_costs", "depreciation", "inventory", "receivables",
              "payables", "cash", "other_bank_balances", "total_assets", "total_current_assets", "total_current_liabilities",
              "equity", "nci", "operating_cash_flow", "capex_ppe_purchase", "ppe", "rou_assets", "cwip", "intangibles",
              "other_expenses", "employee_benefit_expense", "eps", "shares_outstanding", "retained_earnings"]


def ar_pages():
    import fitz
    path = os.path.join(ROOT, "cache", "ar_pdfs", f"{SYMBOL}_{FY}.pdf")
    doc = fitz.open(path)
    return [re.sub(r"\s+", " ", doc[i].get_text()) for i in range(len(doc))]


def _forms(v, key):
    """Printed forms a figure can take in the AR (rupees crore -> million x10, also crore, lakh x100)."""
    out = set()
    if v is None:
        return out
    if key in ("eps",):
        out |= {f"{v:.2f}"}
    elif key == "shares_outstanding":
        n = int(round(v))
        s = str(n)
        head, tail = (s[:-3], s[-3:]) if len(s) > 3 else ("", s)
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        indian = ",".join(groups + [tail]) if groups else tail
        out |= {f"{n:,}", indian}
    else:
        for m in (10.0, 1.0, 100.0):                                  # INR million / crore / lakh pages
            x = abs(v) * m
            for dp in (2, 1, 0):
                western = f"{x:,.{dp}f}"
                plain = f"{x:.{dp}f}"
                out |= {western, plain, _indian_group(plain)}
    return {s for s in out if len(s) >= 4}


def _indian_group(plain):
    """'1234567.89' -> '12,34,567.89' (lakh/crore grouping)."""
    ip, _, fp = plain.partition(".")
    if len(ip) <= 3:
        return plain
    head, tail = ip[:-3], ip[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail]) + (("." + fp) if fp else "")


def lineage(fs, pages):
    res = {}
    for k in BASE_FACTS:
        f = fs.get(k)
        if f is None or f.value is None:
            res[k] = {"found": None, "note": "fact not extracted"}
            continue
        hits = {}
        for which, v in (("cur", f.value), ("prior", f.prior_value)):
            if v is None:
                continue
            forms = _forms(v, k)
            pg = [i + 1 for i, t in enumerate(pages) if any(re.search(r"(?<![\d.,])" + re.escape(s) + r"(?![\d,]*\d)", t) for s in forms)]
            hits[which] = pg[:6]
        res[k] = {"found": all(bool(h) for h in hits.values()), "pages": hits, "stated_page": f.source_page, "tag": f.source_tag,
                  "value": f.value, "prior": f.prior_value}
    return res


def derived_checks(fs):
    """Derived facts re-derived from their parts."""
    g = lambda k: fv(fs, k)         # noqa: E731
    chk = []

    def eq(name, got, want):
        ok = got is not None and want is not None and abs(got - want) <= 1e-6 * max(1.0, abs(want)) + 0.0051
        chk.append((name, ok, got, want))
    eq("ebit = pbt + finance_costs", g("ebit")[0], g("pbt")[0] + g("finance_costs")[0])
    eq("ebitda = ebit + depreciation", g("ebitda")[0], g("ebit")[0] + g("depreciation")[0])
    eq("working_capital = tca - tcl", g("working_capital")[0], g("total_current_assets")[0] - g("total_current_liabilities")[0])
    eq("capital_employed = ta - tcl", g("capital_employed")[0], g("total_assets")[0] - g("total_current_liabilities")[0])
    eq("net_fixed_assets = ppe+rou+cwip+intangibles", g("net_fixed_assets")[0],
       sum(g(k)[0] for k in ("ppe", "rou_assets", "cwip", "intangibles")))
    eq("equity_full = equity + nci", g("equity_full")[0], g("equity")[0] + g("nci")[0])
    comps = (fs.extras or {}).get("components") or {}
    eq("cogs = sum(P&L cost lines)", g("cogs")[0], sum(v[0] for v in comps.values()))
    eq("gross_profit = revenue - cogs", g("gross_profit")[0], g("revenue")[0] - g("cogs")[0])
    eq("fcf = ocf - capex", g("fcf")[0], g("operating_cash_flow")[0] - g("capex")[0])
    dc = (fs.extras or {}).get("debt_components_raw") or {}
    if dc:
        eq("total_debt = borrowings + leases + qualifying other fin. liabilities", g("total_debt")[0],
           dc["borrowings"] + ((dc.get("leases") or 0.0) if dc.get("leases_included") else 0.0) + (dc.get("ofl") or 0.0))
    tx = _tax_parts(fs)
    if tx:
        eq("tax_expense = current + deferred + earlier-year (P&L face)", g("tax_expense")[0], tx)
    eq("net_debt = total_debt - cash", g("net_debt")[0], g("total_debt")[0] - g("cash")[0])
    eq("total_liabilities = ta - equity_full", g("total_liabilities")[0], g("total_assets")[0] - g("equity_full")[0])
    eq("nopat = ebit*(1-tax/pbt)", g("nopat")[0], g("ebit")[0] * (1 - g("tax_expense")[0] / g("pbt")[0]))
    eq("invested_capital = debt + equity_full - cash", g("invested_capital")[0], g("total_debt")[0] + g("equity_full")[0] - g("cash")[0])
    eq("bvps = equity*1e7/shares", g("bvps")[0], g("equity")[0] * 1e7 / g("shares_outstanding")[0])
    return chk


def _tax_parts(fs):
    """Total tax re-derived from the P&L face lines 'Current tax', 'Deferred tax', '... earlier year(s)' (unit-converted)."""
    pg = fs.get("tax_expense").source_page
    if not pg:
        return None
    t = _PAGES[pg - 1] if _PAGES else ""
    num = r"(\(?[\d,]+\.\d+\)?)"
    vals = []
    for lab in (r"Current tax", r"Deferred tax", r"Short/\(Excess\) Provision of Tax Expenses of earlier year\(s\)"):
        m = re.search(lab + r"\s+" + num, t, re.I)
        if not m:
            continue
        s = m.group(1)
        v = float(s.strip("()").replace(",", ""))
        vals.append(-v if s.startswith("(") else v)
    return sum(vals) / 10.0 if vals else None


_PAGES = []


def shareholding_oracle():
    """Promoter pledge % and free float % recomputed from the uploaded shareholding XBRL (independent regex reader)."""
    p = os.path.join(ROOT, "cache", "shareholding_manual", f"{SYMBOL}.xml")
    if not os.path.exists(p):
        return {}
    x = open(p, encoding="utf-8", errors="ignore").read()

    def fact(tag, ctx):
        m = re.search(r'<in-bse-shp:' + tag + r'\s+contextRef="' + ctx + r'"[^>]*>([^<]*)<', x)
        return float(m.group(1)) if m else None
    pc = "ShareholdingOfPromoterAndPromoterGroup_ContextI"
    pledged, promoter = fact("NumberOfSharesEncumberedUnderPledged", pc), fact("NumberOfFullyPaidUpEquityShares", pc)
    total = fact("NumberOfFullyPaidUpEquityShares", "ShareholdingPattern_ContextI")
    flags = re.findall(r'<in-bse-shp:WhetherTheListedEntityHasAnySharesInLockedIn\w*\s+contextRef="[^"]*"[^>]*>\s*(true|false)', x, re.I)
    out = {}
    if pledged is not None and promoter:
        out["promoter_pledge_pct"] = pledged / promoter * 100
        out["filing_pledge_pct"] = fact("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares", pc)
    if promoter and total:
        locked_none = bool(flags) and all(f.lower() == "false" for f in flags)
        out["free_float_pct"] = (total - promoter) / total * 100 if locked_none else None
    return out


# ------------------------------------------------------------------------------------------------ missing-input probe
def probe_missing(key, market):
    """Blank each fact a ratio reads (synthetic complete filing) and classify the outcome."""
    import tools.ratio_contract as rc
    from tests.test_ratio_remediation import facts, MARKET
    if key not in rc.COMPUTABLE:
        return None
    fs0 = facts()
    read = set()
    cls = type(fs0)
    orig = cls.get

    def spy(self, k, *a, **kw):
        read.add(k)
        return orig(self, k, *a, **kw)
    import tools.ratio_breakdown as rb
    ob = rb.build_breakdown
    cls.get = spy
    rb.build_breakdown = lambda *a, **k: None
    try:
        base = rc.compute_with_parents(key, fs0, MARKET, {})
    finally:
        cls.get = orig
        rb.build_breakdown = ob
    bval = base.get("value_raw")
    out = {"read": sorted(read), "baseline": bval, "withheld": [], "unchanged": [], "fallback_flagged": [], "changed_unflagged": []}
    for k in sorted(read):
        f = fs0.facts.get(k)
        if f is None or not hasattr(f, "value"):
            continue
        nf = dataclasses.replace(f, value=None, prior_value=None, status="NOT_DISCLOSED")
        facts2 = dict(fs0.facts)
        facts2[k] = nf
        fs2 = dataclasses.replace(fs0, facts=facts2)
        r = rc.compute_with_parents(key, fs2, MARKET, {})
        v = r.get("value_raw")
        if v is None:
            out["withheld"].append(k)
        elif bval is not None and abs(v - bval) <= 1e-9 * max(1.0, abs(bval)):
            out["unchanged"].append(k)
        elif r.get("estimated") or r.get("status") not in ("verified",):
            out["fallback_flagged"].append(k)
        else:
            out["changed_unflagged"].append(k)
    return out


# ------------------------------------------------------------------------------------------------ test coverage
def test_coverage():
    specific, generic = {}, {}
    generic_names = []
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        lines = src.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                body = "\n".join(lines[node.lineno - 1:node.end_lineno])
                fname = os.path.basename(path)
                if re.search(r"COMPUTABLE|compute_all|reg\.RATIOS|RATIOS\b|FIRST_18", body):
                    generic_names.append(f"{fname}::{node.name}")
                for m in set(re.findall(r"""["']([a-z][a-z0-9_]{2,})["']""", body)):
                    specific.setdefault(m, []).append(f"{fname}::{node.name}")
                if "ORACLE_RATIO_KEYS" in body:            # table-driven: one sub-test per ratio key 1-57 (see test_ratio_formula_oracle)
                    from tests import test_ratio_formula_oracle as T
                    for m in T.ORACLE_RATIO_KEYS:
                        if m not in T.NOT_COMPARABLE_ON_SYNTHETIC:
                            specific.setdefault(m, []).append(f"{fname}::{node.name}[{m}]")
    return specific, generic_names


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "docs"))
    a = ap.parse_args()
    import tools.fundamental_ratio_registry as reg
    import tools.ratio_contract as rc

    fs = load_facts()
    market = {"price": PRICE, "source": "fixed audit price"}
    res = rc.compute_all(fs, market)
    orch = {}
    p = os.path.join(ROOT, "..", "navrist_tools", "out", "anuras_after.json")
    if os.path.exists(p):
        orch = {r["ratio_key"]: r for r in json.load(open(p, encoding="utf-8"))}
    orc = oracle(fs, market)
    pages = ar_pages()
    _PAGES[:] = pages
    sh_orc = shareholding_oracle()
    orc.update({k: v for k, v in sh_orc.items() if k in ("promoter_pledge_pct", "free_float_pct") and v is not None})
    lin = lineage(fs, pages)
    dchk = derived_checks(fs)
    if lin.get("tax_expense", {}).get("found") is False and any(n.startswith("tax_expense") and ok for n, ok, *_ in dchk):
        lin["tax_expense"]["found"] = True
        lin["tax_expense"]["note"] = "total tax is the sum of the printed P&L lines (current, deferred, earlier-year) - re-derived above"
    spec_tests, generic_tests = test_coverage()
    fv_now = {}
    pf = os.path.join(ROOT, "..", "navrist_tools", "out", "fv_now.json")
    if os.path.exists(pf):
        fv_now = json.load(open(pf, encoding="utf-8"))

    rows = []
    for r in reg.RATIOS:
        key, sr = r["ratio_key"], r["sr_no"]
        out = {"sr_no": sr, "ratio_key": key, "label": r["label"], "category": r["category"], "authoritative_formula": r["formula"],
               "strategy": r["strategy"]}
        spec = rc.SPEC.get(key, {})
        out["implementation_formula"] = spec.get("definition") or "(delegated provider)"
        out["perimeter"] = spec.get("perimeter")
        out["period_basis"] = spec.get("basis")
        out["equity_basis"] = rc.EQUITY_BASIS.get(key) or ("none" if key in rc.EQUITY_NOTES else None)
        c = res.get(key)
        o = orch.get(key)
        if c is not None:
            out["unit"] = c.get("unit")
            out["anuras_value"] = c.get("value_raw")
            out["anuras_status"] = c.get("status")
            bd = c.get("breakdown") or {}
            out["breakdown_formula"] = bd.get("formula")
            out["expression"] = (bd.get("calculation") or {}).get("expression")
            out["reconciles"] = bd.get("reconciles")
            out["inputs"] = [{"fact": i.get("fact"), "name": i.get("name"), "value": i.get("value_raw"), "period": i.get("period"),
                              "basis": i.get("basis"), "page": i.get("page"), "statement": i.get("statement"), "method": i.get("method")}
                             for i in bd.get("inputs") or []]
            out["warnings"] = c.get("warnings") or []
            out["reason"] = c.get("reason")
            out["parents"] = rc.PARENTS.get(key, [])
        elif o is not None:
            out["anuras_value"] = o.get("value")
            out["anuras_status"] = o.get("status")
            out["inputs"] = [{"name": i.get("name"), "value": i.get("value"), "page": i.get("page"), "source": i.get("source")}
                             for i in o.get("inputs") or [] if i.get("name") not in ("_metadata", "financial_year")]
            md = next((i for i in o.get("inputs") or [] if i.get("name") == "_metadata"), {})
            out["reason"] = md.get("reason")
            out["warnings"] = md.get("warnings") or []
        # independent recompute
        if key in orc:
            out["independent_value"] = orc[key]
            v = out.get("anuras_value")
            if v is not None:
                out["delta_rel"] = abs(v - orc[key]) / max(1e-12, abs(orc[key]))
                if c is None and abs(v - orc[key]) <= 0.005 + 1e-12:      # provider rows are stored at 2dp: allow display rounding only
                    out["delta_rel"] = 0.0
        # missing-input probe
        try:
            out["missing_input_probe"] = probe_missing(key, market)
        except Exception as e:                      # pragma: no cover
            out["missing_input_probe"] = {"error": f"{type(e).__name__}: {e}"}
        # tests
        sp = sorted(set(spec_tests.get(key, [])))
        out["tests_specific"] = len(sp)
        out["tests_examples"] = sp[:3]
        out["tests_generic"] = len(generic_tests)
        # cross-company
        cc = []
        for cname, blob in fv_now.items():
            for row in blob.get("rows", []):
                if row["ratio_key"] == key:
                    cc.append((cname, row["status"], row["value"]))
        out["cross_company"] = cc
        rows.append(out)
    # persist raw for the writer
    data = {"rows": rows, "lineage": lin, "derived_checks": [(n, ok, g, w) for n, ok, g, w in dchk], "screener": SCREENER,
            "generic_tests": generic_tests}
    os.makedirs(a.out_dir, exist_ok=True)
    jp = os.path.join(a.out_dir, "ratio_audit_matrix_2026-10.json")
    json.dump(data, open(jp, "w", encoding="utf-8"), indent=1, default=str)
    print("wrote", jp, len(rows), "rows;", sum(1 for n, ok, *_ in dchk if not ok), "derived-fact failures;",
          sum(1 for k, v in lin.items() if v.get("found") is False), "lineage misses")
    from ratio_audit_render import render
    mp = render(data, a.out_dir)
    print("wrote", mp)


if __name__ == "__main__":
    main()
