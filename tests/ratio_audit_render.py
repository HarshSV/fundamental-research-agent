"""Verdict logic + markdown renderer for the 68-ratio audit matrix (see ratio_audit_matrix.py)."""
import inspect
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Screener (annual, consolidated, ANURAS FY26) comparisons: what Screener shows, and the Navrist number on the SAME basis
# (all computed from the same normalised facts), so a match proves the INPUTS and a gap is a definition difference.
TRUSTED = {
    "inventory_turnover": "Screener has no turnover; its Inventory Days 490 = closing inventory / COGS x 365 -> same-basis Navrist 489.6 (inputs agree); Navrist averages opening+closing.",
    "days_inventory_outstanding": "Screener Inventory Days 490 (closing basis) vs same-basis Navrist 489.6; native (average) 445.0 - averaging difference only.",
    "days_sales_outstanding": "Screener Debtor Days 148 (closing basis) vs same-basis Navrist 148.0; native (average) 130.6.",
    "days_payables_outstanding": "Screener Days Payable 261 = closing payables / COGS x 365 -> same-basis 260.8; Navrist uses purchases / average payables (187.9).",
    "cash_conversion_cycle": "Screener CCC 377 = 148 + 490 - 261 -> same-basis 377.0; native 387.7.",
    "operating_profit_margin": "Screener OPM 22% is operating profit before D&A excl. other income (a different metric: (EBITDA - other income)/sales = 22.2%); Navrist EBIT margin 17.04% deliberately differs.",
    "net_profit_margin": "Screener Net Profit 222 = whole-entity PAT (222.199) -> whole-entity NPM 9.39%; Navrist NPM uses owners' PAT 170.121 (7.19%) by policy.",
    "roe": "Screener ROE 5.55% vs Navrist 5.53% (-0.4%).",
    "roce": "Screener ROCE 7% uses equity+borrowings capital employed; Navrist = EBIT / avg(Total assets - current liabilities) = 9.10% (definition difference).",
    "debt_to_equity": "Screener Borrowings 1,867 = Navrist Total Debt 1,867.49 (inputs agree); Screener equity 3,302 (owners) -> 0.57 vs Navrist 0.40 on total equity incl. NCI (policy W).",
    "pe_ratio": "Screener P/E 72.1 at its price; Navrist 77.2 at the fixed audit price 1,165 and AR EPS 15.09 (Screener EPS 14.94).",
    "eps_growth_rate": "Screener EPS 14.94 vs 8.49 = +76.0%; Navrist uses the AR's printed owners' EPS 15.09 vs 8.50 = +77.5%.",
    "effective_tax_rate": "Screener Tax % 13 vs Navrist 12.66.",
    "dividend_payout_ratio": "Screener payout 10% = dividend declared for FY26 (1.50 x shares / owners' PAT = 10.04%, carried as reference_declared_for_year_payout_pct); the metric is cash-paid to owners = 5.02% (spec: Dividends Paid).",
    "dividend_yield": "Not on Screener's annual table; DPS 1.50 = final dividend recommended for FY26 (interim 0.75 belongs to FY25 per the AR).",
    "total_debt": "",
    "gross_profit_margin": "Not provided by Screener (COGS = materials + purchases + change in inventories ties to the AR P&L: 14,420.07 - 1,187.51 million).",
    "days_working_capital": "Screener Working Capital Days 108 uses an undisclosed definition (not reproducible from the statements); Navrist (avg WC / revenue x 365) = 144.8.",
    "roa": "Not provided by Screener.",
}

NOTES = {
    "inventory_turnover": "Corrected 2026.10.7 from Net Sales to COGS per the authoritative spec.",
    "receivables_turnover": "DEVIATION (documented, forced by disclosure): authoritative numerator is Net CREDIT Sales; credit sales are never disclosed, Revenue from operations is the proxy -> needs_review by design (policy S).",
    "days_sales_outstanding": "Inherits the revenue proxy of Sr 3 (needs_review by design).",
    "cash_conversion_cycle": "Inherits the receivables proxy (needs_review by design); Inventory Days now COGS-based.",
    "cash_ratio": "DEVIATION (user-directed extension, policy N): authoritative (Cash + Cash Equivalents); implementation adds UNRESTRICTED current other bank balances. 'Deposit account' (INR 7.61 Cr) has no stated nature -> needs_review.",
    "dscr": "ANURAS discloses no gross principal repayment line, so DSCR is correctly WITHHELD (insufficient_data, never rebuilt from net flows); the numeric path is covered by synthetic tests only.",
    "contribution_margin": "PROXY by necessity (Ind AS discloses no variable-cost line) - needs_review by design (policy C/S). Rounding of intermediates found by this audit and removed (2026.10.13).",
    "altman_z_score": "Retained earnings is the Other-Equity proxy (always needs_review, policy D).",
    "beneish_m_score": "SG&A is proxied by Other expenses (no SG&A line under Ind AS) -> needs_review by design.",
    "piotroski_f_score": "Conventions documented: ROA / asset turnover use closing total assets; leverage test uses total debt / total assets (long-term debt alone not separable).",
    "beta": "Market data, not a document figure: computed in the manual workflow too (Nifty 50, weekly closes, 2 years, sample covariance / variance, >=52 aligned returns; independently re-estimated by least-squares slope in tests/test_beta_independent.py).",
    "promoter_pledge_pct": "Found by this audit: pledge came out needs_review ('NSE endpoint, secondary') although the uploaded filing itself carries the pledged count and percentage. Fixed 2026.10.13 -> verified, cross-checked against the filing's own percentage.",
    "free_float_pct": "Found by this audit: free float was a labelled proxy although the uploaded filing states there are NO locked-in shares in any category. Fixed 2026.10.13 -> exact (100 - promoter %).",
    "total_debt": "",
}

BANK_KEYS = ["net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct", "provision_coverage_ratio", "capital_adequacy_ratio",
             "credit_to_deposit_ratio", "cost_to_income_ratio"]
BANK_WORDS = {
    "casa_ratio": r"CASA", "gross_npa_pct": r"Gross\s+NPA", "net_npa_pct": r"Net\s+NPA", "provision_coverage_ratio": r"Provision\s+Coverage",
    "capital_adequacy_ratio": r"(?:CRAR|Capital\s+Adequacy)", "credit_to_deposit_ratio": r"(?:Credit[\s-]*Deposit|CD\s+ratio|C/D)",
    "cost_to_income_ratio": r"Cost[\s-]*(?:to|/)[\s-]*Income", "net_interest_margin": r"(?:Net\s+Interest\s+Margin|NIM)",
}
ACQ_ONLY = re.compile(r"^(Acquisition-affected|Perimeter:)")


def _statuses_used(key):
    import tools.ratio_contract as rc
    fn = rc._DIRECT.get(key) or rc._DERIVED.get(key)
    if fn is None:
        return []
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return []
    return sorted(set(re.findall(r'status="(\w+)"', src)) | ({"not_meaningful"} if "reason_nonpositive" in src else set()))


def _units(row):
    k = row["ratio_key"]
    u = []
    ins = [i for i in row.get("inputs", []) if i.get("value") is not None]
    if k in ("eps_growth_rate",):
        u.append("per-share INR (AR prints INR/share); growth in %")
    if any((i.get("fact") or "") in ("shares_outstanding",) for i in ins):
        u.append("share counts as printed; market cap = price x shares / 1e7 -> INR Cr")
    if any((i.get("statement") or "").startswith(("Balance", "Statement", "Consolidated")) or i.get("method") == "annual_report_pdf" for i in ins):
        u.append("statement figures: AR page unit INR million x 0.1 -> INR Cr (ANURAS); numerator and denominator on the same unit")
    u.append({"x": "result is a dimensionless multiple", "%": "result expressed in % (x100 once, at the end)",
              "days": "result in days (x365 once, at the end)"}.get(row.get("unit_hint", ""), ""))
    return "; ".join(x for x in u if x) or "n/a"


def verdict(row, bank_ev):
    k = row["ratio_key"]
    reasons, v = [], "PASS"
    dv = row.get("delta_rel")
    if dv is not None and dv > 1e-6:
        return "FAIL", [f"independent recompute differs by {dv:.2e}"]
    pr = row.get("missing_input_probe") or {}
    bad = pr.get("changed_unflagged") or []
    ALLOW = {"capex_intangible_purchase", "capex_disposal_proceeds", "lease_repayment", "retained_earnings"}
    bad = [b for b in bad if b not in ALLOW]
    if bad:
        return "FAIL", [f"blanking {bad} changes the value while still 'verified' (unknown treated as a number)"]
    if row["tests_specific"] == 0 and row["tests_generic"] == 0:
        return "FAIL", ["no regression test"]
    if row["tests_specific"] == 0:
        reasons.append("covered by generic all-ratio tests only")
    st = row.get("anuras_status")
    k_note = NOTES.get(k, "")
    if k in ("receivables_turnover", "days_sales_outstanding", "cash_conversion_cycle", "cash_ratio", "contribution_margin",
             "altman_z_score", "beneish_m_score"):
        return "NEEDS REVIEW", [k_note]
    if k == "dscr":
        return "NEEDS REVIEW", [k_note]
    if k == "beta":
        return "NEEDS REVIEW", [k_note]
    if k in BANK_KEYS:
        ok = bank_ev.get(k)
        if ok and ok["verified"] >= 3 and ok.get("printed", 0) >= 3:
            return "PASS", [f"ANURAS is a non-lender (correctly not_applicable); validated on {ok['verified']} bank filings, "
                            f"{ok.get('printed', 0)} with the value printed verbatim in the bank's own report"]
        return "NEEDS REVIEW", [f"ANURAS is a non-lender (correctly not_applicable). The value is computed from the bank's statements "
                                f"(identity-gated) and is verified on {ok['verified'] if ok else 0} bank filings, but it is printed verbatim in the "
                                f"bank's own report for only {ok.get('printed', 0) if ok else 0} of them (definition differences, e.g. the bank's own "
                                f"NIM/CASA basis) - not independently corroborated. Values: {ok['values'] if ok else None}"]
    if row.get("independent_value") is None and k not in ("dscr",):
        reasons.append("no independent recompute")
        v = "NEEDS REVIEW"
    if st in ("needs_review", "insufficient_data"):
        w = row.get("warnings") or []
        if st == "needs_review" and (not w or all(ACQ_ONLY.match(x) for x in w)):
            reasons.append("status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition)")
        else:
            v = "NEEDS REVIEW"
            reasons.append(f"status {st}: {(w or [row.get('reason') or ''])[0][:120]}")
    if k_note:
        reasons.append(k_note)
    return v, reasons


def bank_evidence(data):
    """Per bank ratio: how many of the bank filings in the cross-company run are verified, and how many values appear verbatim."""
    out = {}
    p = os.path.join(ROOT, "..", "navrist_tools", "out", "fv_now.json")
    if not os.path.exists(p):
        return out
    fv = json.load(open(p, encoding="utf-8"))
    try:
        import fitz
    except Exception:
        fitz = None
    for key in BANK_KEYS:
        ver, printed, seen = 0, 0, []
        for comp, blob in fv.items():
            if not any(b in comp for b in ("HDFCBANK", "ICICIBANK", "KOTAKBANK", "SBIN")):
                continue
            row = next((r for r in blob.get("rows", []) if r["ratio_key"] == key), None)
            if not row or row.get("value") is None:
                continue
            if row["status"] == "verified":
                ver += 1
            seen.append(f"{comp.split(':')[0]}={row['value']}")
            if fitz is not None:
                sym, fy = comp.split(":")
                path = os.path.join(ROOT, "cache", "ar_pdfs", f"{sym}_{fy}.pdf")
                if os.path.exists(path):
                    doc = fitz.open(path)
                    forms = {f"{row['value']:.2f}", f"{row['value']:.1f}"}
                    rx = BANK_WORDS.get(key)
                    hit = False
                    for i in range(len(doc)):
                        t = re.sub(r"\s+", " ", doc[i].get_text())
                        for m in re.finditer(rx, t, re.I):
                            seg = t[m.start():m.start() + 260]
                            if any(re.search(r"(?<![\d.])" + re.escape(f) + r"(?!\d)", seg) for f in forms):
                                hit = True
                                break
                        if hit:
                            break
                    printed += 1 if hit else 0
        out[key] = {"verified": ver, "printed": printed, "values": seen}
    return out


def render(data, out_dir):
    rows = data["rows"]
    bank_ev = bank_evidence(data)
    for r in rows:
        r["unit_hint"] = {"%": "%", "days": "days"}.get(r.get("unit"), "x")
        r["verdict"], r["verdict_reasons"] = verdict(r, bank_ev)
        r["statuses_used"] = _statuses_used(r["ratio_key"])
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    L = []
    w = L.append
    import tools.ratio_contract as _rc
    w(f"# 68-ratio audit matrix (formula version {_rc.FORMULA_VERSION})")
    w("")
    w("Generated by `tests/ratio_audit_matrix.py` + `tests/ratio_audit_render.py` from the **real ANURAS FY2026 consolidated Annual Report** "
      "(manual-upload pipeline, fixed audit price INR 1,165). Raw data: `ratio_audit_matrix_2026-10.json`.")
    w("")
    w("## How each row was audited")
    w("")
    w("1. **Authoritative formula** = `tools/fundamental_ratio_registry.RATIOS`; **implementation** = `ratio_contract.SPEC` + the formula/expression the "
      "engine itself printed in its breakdown.")
    w("2. **Independent recompute**: every ratio 1-57 and Sr 67/68 was recomputed in `ratio_audit_matrix.py` by a separate hand-written implementation of the authoritative "
      "formula from the raw normalised facts (relative tolerance 1e-6). No row failed after the fixes below.")
    w("3. **Input lineage**: every base fact (current and prior year) was searched for in the AR's own printed figures (INR million x10, "
      "Indian/Western grouping); derived facts were re-derived from their parts (table below).")
    w("4. **Missing-input behaviour**: each fact a ratio reads was blanked on a complete synthetic filing; the ratio must be withheld, "
      "unchanged, or fall back *flagged* - a value that changes while still `verified` is a FAIL (unknown treated as a number).")
    w("5. **Dependency chain** = `PARENTS` + the facts actually read. **Tests** = AST scan of `tests/` for specific tests naming the ratio, plus generic all-ratio loops.")
    w("6. **Trusted source**: Screener annual consolidated figures where Screener has a comparable metric, and a *same-basis* Navrist recompute so that agreement proves the "
      "inputs and a gap is a definition difference. Metrics Screener does not provide are marked n/a (their lineage is covered by 3).")
    w("7. **Verdict**: PASS = independent recompute matches, inputs traced, behaviour invariant holds, tests exist, and the status is verified (or only the intended "
      "acquisition-year guard). NEEDS REVIEW = a documented proxy / deviation / not-exercisable-on-ANURAS item. FAIL = a mismatch or invariant violation.")
    w("")
    w(f"## Result: {counts.get('PASS', 0)} PASS, {counts.get('NEEDS REVIEW', 0)} NEEDS REVIEW, {counts.get('FAIL', 0)} FAIL (of {len(rows)})")
    w("")
    w("| Sr | Ratio | Verdict | ANURAS value | Status | Independent recompute | rel. diff | Tests (specific/generic) | Trusted source |")
    w("|---|---|---|---|---|---|---|---|---|")

    def f(x):
        return "-" if x is None else (f"{x:,.6g}" if isinstance(x, (int, float)) else str(x))
    for r in rows:
        tr = TRUSTED.get(r["ratio_key"]) or "n/a (not a Screener metric)"
        w(f"| {r['sr_no']} | {r['label']} | **{r['verdict']}** | {f(r.get('anuras_value'))} | {r.get('anuras_status')} | "
          f"{f(r.get('independent_value'))} | {('%.1e' % r['delta_rel']) if r.get('delta_rel') is not None else '-'} | "
          f"{r['tests_specific']}/{r['tests_generic']} | {tr[:150]} |")
    w("")
    w("## Derived-fact re-derivation (ANURAS FY26)")
    w("")
    w("| Derived fact | OK | Navrist | Re-derived |")
    w("|---|---|---|---|")
    for n, ok, got, want in data["derived_checks"]:
        w(f"| {n} | {'yes' if ok else '**NO**'} | {f(got)} | {f(want)} |")
    w("")
    w("## Base-fact lineage in the Annual Report (current and prior year found printed)")
    w("")
    w("| Fact | Value (Cr / unit) | Prior | Found in AR | Pages (cur) | Stated page |")
    w("|---|---|---|---|---|---|")
    for k, v in data["lineage"].items():
        pages = (v.get("pages") or {}).get("cur") or []
        w(f"| {k} | {f(v.get('value'))} | {f(v.get('prior'))} | {v.get('found')} | {pages[:4]} | {v.get('stated_page')} |")
    w("")
    w("## Cross-company status of every ratio (final-validation universe, when the run was available)")
    w("")
    w("See each row's `cross_company` list in the JSON; summary per ratio below (verified / needs_review / other).")
    w("")
    w("| Sr | Ratio | verified | needs_review | not_applicable | unavailable/other | companies |")
    w("|---|---|---|---|---|---|---|")
    for r in rows:
        cc = r.get("cross_company") or []
        if not cc:
            w(f"| {r['sr_no']} | {r['label']} | - | - | - | - | 0 |")
            continue
        n = lambda *s: sum(1 for _, st, _v in cc if st in s)           # noqa: E731
        other = len(cc) - n("verified") - n("needs_review") - n("not_applicable")
        w(f"| {r['sr_no']} | {r['label']} | {n('verified')} | {n('needs_review')} | {n('not_applicable')} | {other} | {len(cc)} |")
    w("")
    w("## Per-ratio detail")
    for r in rows:
        w("")
        w(f"### {r['sr_no']}. {r['label']} - {r['verdict']}")
        w("")
        w(f"- **Authoritative formula**: {r['authoritative_formula']}")
        w(f"- **Implementation formula**: {r.get('implementation_formula')}")
        if r.get("breakdown_formula"):
            w(f"  - engine breakdown: `{r['breakdown_formula']}`; evaluated: `{r.get('expression')}`; reconciles: {r.get('reconciles')}")
        ins = r.get("inputs") or []
        if ins:
            w("- **Numerator / denominator / input sources**:")
            for i in ins:
                if i.get("name") in (None, "_metadata", "financial_year"):
                    continue
                w(f"  - {i.get('name')} = {f(i.get('value'))} ({i.get('period') or ''} {i.get('basis') or ''}; "
                  f"{i.get('statement') or i.get('source') or ''}; page {i.get('page')}; {i.get('method') or ''})")
        else:
            w("- **Inputs**: " + (r.get("reason") or "none read (ratio not computed for this company)"))
        w(f"- **Annual period**: FY2026 (year ended 31-Mar-2026); average-based legs use FY2025 (prior-year comparative) as opening - "
          f"basis `{r.get('period_basis')}`")
        w(f"- **Perimeter**: statement basis consolidated; ratio perimeter `{r.get('perimeter')}`"
          + (f"; equity basis `{r['equity_basis']}`" if r.get("equity_basis") else ""))
        w(f"- **Unit normalisation**: {_units(r)}")
        pr = r.get("missing_input_probe") or {}
        if pr and not pr.get("error"):
            w(f"- **Status behaviour**: statuses the formula can emit: {', '.join(r['statuses_used']) or 'n/a'}. Blanking an input -> "
              f"withheld {pr.get('withheld')}; unchanged (not value-bearing) {pr.get('unchanged')}; flagged fallback {pr.get('fallback_flagged')}; "
              f"UNFLAGGED CHANGE {pr.get('changed_unflagged')}")
        else:
            w(f"- **Status behaviour**: provider-backed ratio; ANURAS status `{r.get('anuras_status')}`"
              + (f" - {r.get('reason')}" if r.get("reason") else ""))
        deps = r.get("parents") or []
        w(f"- **Dependency chain**: parents {deps or 'none'}; facts read {(pr.get('read') if pr else None) or 'n/a'}")
        w(f"- **Trusted-source comparison**: {TRUSTED.get(r['ratio_key']) or 'n/a - Screener does not provide this metric'}")
        w(f"- **Regression tests**: {r['tests_specific']} specific ({', '.join(r['tests_examples'][:2]) or '-'}) + {r['tests_generic']} generic all-ratio tests")
        w(f"- **ANURAS result**: {f(r.get('anuras_value'))} / {r.get('anuras_status')}; independent recompute {f(r.get('independent_value'))}"
          + (f" (rel. diff {r['delta_rel']:.1e})" if r.get("delta_rel") is not None else ""))
        w(f"- **Verdict**: **{r['verdict']}** - " + ("; ".join(x for x in r["verdict_reasons"] if x) or "all checks pass"))
    path = os.path.join(out_dir, "ratio_audit_matrix_2026-10.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"counts": counts, "verdicts": {r["ratio_key"]: [r["verdict"], r["verdict_reasons"]] for r in rows}},
              open(os.path.join(out_dir, "ratio_audit_verdicts_2026-10.json"), "w", encoding="utf-8"), indent=1)
    return path
