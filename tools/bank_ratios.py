"""Ratios 58-65 (NIM, CASA, Gross NPA, Net NPA, PCR, CRAR, Credit-to-Deposit, Cost-to-Income) - ONE definition each,
computed from `tools.bank_extractor`'s identity-checked reads of the bank's STANDALONE RBI-format statements.

Definitions (global; see docs/ratio_contract.md "Banking ratios"):
  58 NIM            = (Interest Earned - Interest Expended) / average Interest-Earning Assets x 100,
                      Interest-Earning Assets = Cash & balances with RBI + Balances with banks & money at call + Investments
                      + Advances (balance-sheet face; average of closing current and prior year). The bank's own disclosed
                      NIM is shown as a cross-check; a gap > 0.75 pp downgrades the result to needs_review.
  59 CASA           = (Demand + Savings deposits) / Total deposits x 100, Schedule 3, only when D + S + Term = Total = BS Deposits.
  60/61 Gross/Net NPA = the ratio the bank discloses (RBI asset-quality disclosure), never rebuilt from a guessed denominator.
  62 PCR            = the Provision Coverage Ratio the bank discloses (SBI-style 'excluding AUCA' is labelled as such).
  63 CRAR           = the total Capital to Risk-Weighted Assets Ratio the bank discloses.
  64 Credit/Deposit = Advances / Deposits x 100 (balance-sheet face).
  65 Cost-to-Income = Operating Expenses / (Net Interest Income + Other Income) x 100 (P&L face).

A figure that cannot be read AND proven is unknown (not_disclosed / insufficient_data) - never zero, never a nearby row.
"""
import datetime as _dt

_NOTE_BASIS = "Standalone bank statements (RBI format) - the regulated entity; see policy in tools/bank_extractor.py."


def _c(parsed, name):
    v = parsed.get(name)
    return v if isinstance(v, dict) and v.get("cur") is not None else None


def _leg(label, value, page, statement, unit=None, **kw):
    d = {"label": label, "value_cr": round(value, 2), "value_raw": value, "source": "Annual Report", "statement": statement,
         "page": page, **kw}
    if unit is not None:
        d["unit"] = unit
    return d


def _part(label, value, sign, page, statement):
    return {"label": label, "value_raw": value, "sign": sign, "source": "Annual Report", "statement": statement, "page": page}


def _base(parsed, fy, key_label):
    yy = str(fy)[-2:]
    basis = parsed.get("basis") or "standalone"
    return {"applicable": False, "period": f"FY{yy} ({basis})", "statement_basis": basis,
            "perimeter": "bank (standalone)" if parsed.get("format") != "nbfc" else f"NBFC ({basis})", "calculated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "source_url": parsed.get("source_url"), "ratio_name": key_label}


def _fail(base, status, reason):
    return {**base, "status": status, "reason": reason}


def _sources(ar, parsed, fy, *pages):
    try:
        pl = next((p for p in pages if p and p[0] == "pl"), None)
        bs = next((p for p in pages if p and p[0] == "bs"), None)
        return ar._page_sources(parsed.get("source_url"), fy, pl_page=pl[1] if pl else None,
                                bs_page=bs[1] if bs else None) if parsed.get("source_url") else []
    except Exception:
        return []


def _finish(ar, key, base, parsed, fy, value, unit, num, den, formula, pages, status="verified", confidence=1.0,
            warnings=(), note=None):
    from tools.ratio_breakdown import legacy_breakdown
    out = {**base, "applicable": True, "status": status, "value": round(value, 2), "value_raw": value, "unit": unit,
           "confidence": confidence, "estimated": status != "verified", "numerator": num, "denominator": den,
           "warnings": list(warnings), "methodology": note, "note": " ".join([note or "", _NOTE_BASIS]).strip(),
           "sources": _sources(ar, parsed, fy, *pages)}
    try:
        out["breakdown"] = legacy_breakdown(key, out, formula, fy=fy, basis=base.get("statement_basis", "standalone"))
    except Exception as e:
        print(f"[bank_ratios] breakdown for {key} failed: {e}")
        out["breakdown"] = None
    return out


def _disclosed(ar, key, name, label, parsed, fy, base):
    d = (parsed.get("disclosed") or {}).get(name)
    if not d:
        return _fail(base, "not_disclosed",
                     f"The bank's own {label} disclosure could not be found in its regulatory disclosures; it is not "
                     "reconstructed from other rows.")
    num = {"label": f"{label} as disclosed by the bank", "value_raw": d["cur"], "value_cr": d["cur"], "unit": "%",
           "source": "Annual Report (RBI disclosure)", "statement": "Notes to accounts - disclosures", "page": d["page"],
           "note": f"Printed row: \"{d['label']}\""}
    warn = []
    if name == "pcr_pct" and "excluding" in d["label"].lower():
        warn.append("The printed PCR excludes technical write-offs (AUCA); the figure including AUCA is higher.")
    return _finish(ar, key, base, parsed, fy, d["cur"], "%", num, None, f"{label} (as disclosed)", [],
                   warnings=warn, note=f"{label} exactly as the bank discloses it (page {d['page']}) - the regulatory figure, not rebuilt.")


def compute(ar, key, symbol, name, fiscal_year):
    sym = symbol.strip().upper().replace(".NS", "")
    parsed = ar._get_extracted_bank_financials(sym, name, fiscal_year, True)
    label = {"net_interest_margin": "Net Interest Margin", "casa_ratio": "CASA Ratio", "gross_npa_pct": "Gross NPA ratio",
             "net_npa_pct": "Net NPA ratio", "provision_coverage_ratio": "Provision Coverage Ratio",
             "capital_adequacy_ratio": "Capital Adequacy Ratio (CRAR)", "credit_to_deposit_ratio": "Credit-to-Deposit Ratio",
             "cost_to_income_ratio": "Cost-to-Income Ratio"}[key]
    base = _base(parsed, fiscal_year, label)
    if "error" in parsed:
        return {**base, "reason": parsed["error"]}
    if parsed.get("problems") and "deposits" not in parsed and parsed.get("format") != "nbfc":
        return _fail(base, "not_applicable", "Not an RBI-format bank filing (no Deposits/Advances balance sheet found): " +
                     "; ".join(parsed["problems"]))
    ids = parsed.get("identities") or {}
    if parsed.get("format") == "nbfc":
        return _nbfc(ar, key, parsed, fiscal_year, base)

    if key == "capital_adequacy_ratio" and parsed.get("capital_amounts"):
        ca = parsed["capital_amounts"]
        cap, rwa = ca["capital"], ca["rwa"]
        v = cap["cur"] / rwa["cur"] * 100
        warns, status, conf = [], "verified", 1.0
        disc = (parsed.get("disclosed") or {}).get("crar_pct")
        if disc and abs(disc["cur"] - v) > 0.3:
            status, conf = "needs_review", 0.8
            warns.append(f"The computed CRAR {v:.2f}% differs from the printed {disc['cur']:.2f}% (page {disc['page']}).")
        pg = ca["page"]
        return _finish(ar, key, base, parsed, fiscal_year, v, "%",
                       _leg("Total capital funds (Tier 1 + Tier 2)", cap["cur"], pg, "Notes - Basel III capital adequacy"),
                       _leg("Total risk-weighted assets", rwa["cur"], pg, "Notes - Basel III capital adequacy"),
                       "Total Capital ÷ Risk-Weighted Assets × 100", [], status=status, confidence=conf, warnings=warns,
                       note="CRAR = Total capital funds / Total risk-weighted assets (Basel III capital table).")
    if key in ("gross_npa_pct", "net_npa_pct", "provision_coverage_ratio", "capital_adequacy_ratio"):
        nm = {"gross_npa_pct": "gross_npa_pct", "net_npa_pct": "net_npa_pct", "provision_coverage_ratio": "pcr_pct",
              "capital_adequacy_ratio": "crar_pct"}[key]
        return _disclosed(ar, key, nm, label, parsed, fiscal_year, base)

    if key == "credit_to_deposit_ratio":
        adv, dep = _c(parsed, "advances"), _c(parsed, "deposits")
        if not adv or not dep or not dep["cur"]:
            return _fail(base, "not_disclosed", "Advances / Deposits rows were not found on the standalone balance sheet.")
        if not ids.get("balance_sheet_total", False):
            return _fail(base, "insufficient_data", "The balance sheet's Total liabilities and Total assets rows do not agree - the page read is not trusted.")
        v = adv["cur"] / dep["cur"] * 100
        return _finish(ar, key, base, parsed, fiscal_year, v, "%",
                       _leg("Advances (net, balance sheet)", adv["cur"], adv["page"], "Balance Sheet"),
                       _leg("Deposits", dep["cur"], dep["page"], "Balance Sheet"), "Advances ÷ Deposits × 100", [("bs", adv["page"])],
                       note="Credit-to-Deposit = Advances / Deposits (balance-sheet face).")

    if key == "cost_to_income_ratio":
        ie, ix, oi, ox = (_c(parsed, k) for k in ("interest_earned", "interest_expended", "other_income", "operating_expenses"))
        if not (ie and ix and oi and ox):
            return _fail(base, "not_disclosed", "Interest Earned / Interest Expended / Other Income / Operating Expenses rows were not all found on the standalone P&L.")
        nii = ie["cur"] - ix["cur"]
        den = nii + oi["cur"]
        if den <= 0:
            return _fail(base, "not_meaningful", "Net Interest Income + Other Income is not positive.")
        v = ox["cur"] / den * 100
        pg = ie["page"]
        return _finish(ar, key, base, parsed, fiscal_year, v, "%",
                       _leg("Operating Expenses", ox["cur"], ox["page"], "Profit and Loss Account"),
                       {"label": "Net Interest Income + Other Income", "value_cr": round(den, 2), "value_raw": den,
                        "source": "Annual Report", "statement": "Profit and Loss Account", "page": pg,
                        "parts": [_part("Interest Earned", ie["cur"], 1, pg, "Profit and Loss Account"),
                                  _part("Interest Expended", ix["cur"], -1, pg, "Profit and Loss Account"),
                                  _part("Other Income", oi["cur"], 1, pg, "Profit and Loss Account")]},
                       "Operating Expenses ÷ (Net Interest Income + Other Income) × 100", [("pl", pg)],
                       note="Cost-to-Income = Operating Expenses / (Net Interest Income + Other Income); Net Interest Income = Interest Earned - Interest Expended.")

    if key == "casa_ratio":
        d, s_, t = _c(parsed, "demand_deposits"), _c(parsed, "savings_deposits"), _c(parsed, "schedule3_total")
        if not (d and s_ and t):
            return _fail(base, "insufficient_data", "Schedule 3 Demand / Savings / Total deposits could not all be read; a missing component is not assumed to be zero.")
        if not (ids.get("schedule3_components_sum_to_total") and ids.get("schedule3_total_equals_balance_sheet")):
            return _fail(base, "insufficient_data", "Schedule 3 does not add up (Demand + Savings + Term = Total = Balance-sheet Deposits) - the page read is not trusted.")
        v = (d["cur"] + s_["cur"]) / t["cur"] * 100
        pg = d["page"]
        return _finish(ar, key, base, parsed, fiscal_year, v, "%",
                       {"label": "CASA (Demand + Savings Bank Deposits)", "value_cr": round(d["cur"] + s_["cur"], 2),
                        "value_raw": d["cur"] + s_["cur"], "source": "Annual Report", "statement": "Schedule 3 - Deposits", "page": pg,
                        "parts": [_part("Demand deposits (from banks + from others)", d["cur"], 1, pg, "Schedule 3 - Deposits"),
                                  _part("Savings bank deposits", s_["cur"], 1, pg, "Schedule 3 - Deposits")]},
                       _leg("Total deposits", t["cur"], t["page"], "Schedule 3 - Deposits"),
                       "(Demand Deposits + Savings Bank Deposits) ÷ Total Deposits × 100", [("bs", parsed.get("deposits", {}).get("page"))],
                       note="CASA = (Demand + Savings deposits) / Total deposits (Schedule 3, proven to equal the balance sheet).")

    if key == "net_interest_margin":
        need = ("interest_earned", "interest_expended", "cash_rbi", "balances_banks", "investments", "advances")
        g = {k: _c(parsed, k) for k in need}
        if any(v is None or v.get("prior") is None for v in g.values()):
            miss = [k for k, v in g.items() if v is None or v.get("prior") is None]
            return _fail(base, "not_disclosed", "Rows needed for NIM were not found on the standalone statements: " + ", ".join(miss))
        if not ids.get("balance_sheet_total", False):
            return _fail(base, "insufficient_data", "The balance sheet's Total liabilities and Total assets rows do not agree - the page read is not trusted.")
        ie, ix = g["interest_earned"], g["interest_expended"]
        nii = ie["cur"] - ix["cur"]
        names = (("cash_rbi", "Cash & balances with RBI"), ("balances_banks", "Balances with banks & money at call"),
                 ("investments", "Investments"), ("advances", "Advances"))
        bs = g["advances"]["page"]
        yy = str(fiscal_year)

        def ea_leg(which, tag):
            tot = sum(g[k][which] for k, _ in names)
            return {"label": f"Interest-earning assets {tag}", "value_cr": round(tot, 2), "value_raw": tot, "source": "Annual Report",
                    "statement": "Balance Sheet", "page": bs,
                    "parts": [_part(f"{lab} {tag}", g[k][which], 1, bs, "Balance Sheet") for k, lab in names]}
        cur_leg, pri_leg = ea_leg("cur", f"FY{yy}"), ea_leg("prior", f"FY{int(yy) - 1}")
        avg = (cur_leg["value_raw"] + pri_leg["value_raw"]) / 2.0
        if avg <= 0:
            return _fail(base, "not_meaningful", "Average interest-earning assets is not positive.")
        v = nii / avg * 100
        warns, status, conf = [], "verified", 1.0
        disc = (parsed.get("disclosed") or {}).get("nim_pct")
        if disc:
            gap = abs(v - disc["cur"])
            note_c = f"The bank's own disclosed NIM is {disc['cur']:.2f}% (page {disc['page']}); the bank averages only the genuinely interest-bearing part of these assets."
            if gap > 0.75:
                status, conf = "needs_review", 0.8
                warns.append(note_c + f" The computed {v:.2f}% differs by {gap:.2f} pp.")
            else:
                warns.append(note_c)
        pl = ie["page"]
        num = {"label": "Net Interest Income (Interest Earned − Interest Expended)", "value_cr": round(nii, 2), "value_raw": nii,
               "source": "Annual Report", "statement": "Profit and Loss Account", "page": pl,
               "parts": [_part("Interest Earned", ie["cur"], 1, pl, "Profit and Loss Account"),
                         _part("Interest Expended", ix["cur"], -1, pl, "Profit and Loss Account")]}
        den = {"label": "Average Interest-Earning Assets", "value_cr": round(avg, 2), "value_raw": avg, "source": "Annual Report",
               "statement": "Balance Sheet", "page": bs,
               "expr": [cur_leg, "+", pri_leg, "÷", {"const": 2.0, "text": "2"}]}
        return _finish(ar, key, base, parsed, fiscal_year, v, "%", num, den,
                       "Net Interest Income ÷ Average Interest-Earning Assets × 100", [("pl", pl), ("bs", bs)],
                       status=status, confidence=conf, warnings=warns,
                       note="NIM = Net Interest Income / average (Cash & RBI balances + Balances with banks + Investments + Advances).")
    return {**base, "reason": f"No bank definition for {key}."}


def _nbfc(ar, key, parsed, fy, base):
    """NBFC / HFC (Ind AS) versions of the same ratios. CASA and Credit-to-Deposit are bank-only; the asset-quality / capital
    ratios use the same disclosed-figure rule; NIM and Cost-to-Income are computed from the statements' own rows."""
    label = base["ratio_name"]
    st = "Statement of Profit and Loss"
    if key in ("casa_ratio", "credit_to_deposit_ratio"):
        return _fail(base, "not_applicable", f"{label} is a deposit-taking bank ratio (CASA / bank balance sheet); it does not apply to an NBFC.")
    if key in ("gross_npa_pct", "net_npa_pct", "provision_coverage_ratio", "capital_adequacy_ratio"):
        if key == "capital_adequacy_ratio" and parsed.get("capital_amounts"):
            ca = parsed["capital_amounts"]
            v = ca["capital"]["cur"] / ca["rwa"]["cur"] * 100
            return _finish(ar, key, base, parsed, fy, v, "%", _leg("Total capital funds", ca["capital"]["cur"], ca["page"], "Notes - capital adequacy"),
                           _leg("Total risk-weighted assets", ca["rwa"]["cur"], ca["page"], "Notes - capital adequacy"),
                           "Total Capital ÷ Risk-Weighted Assets × 100", [], note="CRAR = Total capital funds / Total risk-weighted assets.")
        nm = {"gross_npa_pct": "gross_npa_pct", "net_npa_pct": "net_npa_pct", "provision_coverage_ratio": "pcr_pct",
              "capital_adequacy_ratio": "crar_pct"}[key]
        return _disclosed(ar, key, nm, label, parsed, fy, base)
    g = lambda k: parsed.get(k) if isinstance(parsed.get(k), dict) else None
    if key == "net_interest_margin":
        ii, fc, ln, inv = g("interest_income"), g("finance_costs"), g("loans"), g("investments")
        if not (ii and fc and ln and inv):
            return _fail(base, "not_disclosed", "Interest income / Finance costs / Loans / Investments rows were not all found.")
        nii = ii["cur"] - fc["cur"]
        yy = str(fy)
        names = (("loans", "Loans"), ("investments", "Investments"))

        def ea(which, tag):
            tot = ln[which] + inv[which]
            return {"label": f"Interest-earning assets {tag}", "value_cr": round(tot, 2), "value_raw": tot, "source": "Annual Report",
                    "statement": "Balance Sheet", "page": ln["page"],
                    "parts": [_part(f"Loans {tag}", ln[which], 1, ln["page"], "Balance Sheet"),
                              _part(f"Investments {tag}", inv[which], 1, inv["page"], "Balance Sheet")]}
        cur_l, pri_l = ea("cur", f"FY{yy}"), ea("prior", f"FY{int(yy) - 1}")
        avg = (cur_l["value_raw"] + pri_l["value_raw"]) / 2.0
        num = {"label": "Net Interest Income (Interest income − Finance costs)", "value_cr": round(nii, 2), "value_raw": nii,
               "source": "Annual Report", "statement": st, "page": ii["page"],
               "parts": [_part("Interest income", ii["cur"], 1, ii["page"], st), _part("Finance costs", fc["cur"], -1, fc["page"], st)]}
        den = {"label": "Average Interest-Earning Assets (Loans + Investments)", "value_cr": round(avg, 2), "value_raw": avg,
               "source": "Annual Report", "statement": "Balance Sheet", "page": ln["page"],
               "expr": [cur_l, "+", pri_l, "÷", {"const": 2.0, "text": "2"}]}
        return _finish(ar, key, base, parsed, fy, nii / avg * 100, "%", num, den,
                       "Net Interest Income ÷ Average Interest-Earning Assets × 100", [],
                       note="NBFC NIM = (Interest income - Finance costs) / average (Loans + Investments).")
    if key == "cost_to_income_ratio":
        em, dp, ox, ti, fc = g("employee_cost"), g("depreciation"), g("other_expenses"), g("total_income"), g("finance_costs")
        if not (em and dp and ox and ti and fc):
            return _fail(base, "not_disclosed", "Employee benefits / Depreciation / Other expenses / Total income / Finance costs rows were not all found.")
        opex = em["cur"] + dp["cur"] + ox["cur"]
        net_inc = ti["cur"] - fc["cur"]
        if net_inc <= 0:
            return _fail(base, "not_meaningful", "Total income less finance costs is not positive.")
        pg = ti["page"]
        num = {"label": "Operating expenses (Employee benefits + Depreciation + Other expenses)", "value_cr": round(opex, 2), "value_raw": opex,
               "source": "Annual Report", "statement": st, "page": pg,
               "parts": [_part("Employee benefits expenses", em["cur"], 1, pg, st), _part("Depreciation & amortisation", dp["cur"], 1, pg, st),
                         _part("Other expenses", ox["cur"], 1, pg, st)]}
        den = {"label": "Net total income (Total income − Finance costs)", "value_cr": round(net_inc, 2), "value_raw": net_inc,
               "source": "Annual Report", "statement": st, "page": pg,
               "parts": [_part("Total income", ti["cur"], 1, pg, st), _part("Finance costs", fc["cur"], -1, pg, st)]}
        return _finish(ar, key, base, parsed, fy, opex / net_inc * 100, "%", num, den,
                       "Operating Expenses ÷ (Total Income − Finance Costs) × 100", [],
                       note="NBFC Cost-to-Income = (Employee + Depreciation + Other expenses) / (Total income - Finance costs); impairment charges are credit cost, not operating cost.")
    return _fail(base, "not_disclosed", f"No NBFC definition for {key}.")
