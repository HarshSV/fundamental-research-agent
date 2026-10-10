"""
THE ratio calculation contract - one canonical definition and one computation
for every Annual-Report-sourced ratio (Sr No 1-57) plus the market and
shareholding ratios (24-29, 37, 50-54, 66-68).

Before this module the same ratio was implemented up to three times
(`document_analysis_engine`, the `nse_xbrl` endpoints, the canonical
`ratio_calculation_engine`) and the copies disagreed. Now:

    FactSet  (tools.fundamental_fact_store - normalized, provenance-bearing)
        -> compute_ratio(key, facts, market, deps)   <- the ONLY formula code
        -> result dict {value_raw, value, status, confidence, estimated,
                        numerator, denominator, inputs, warnings,
                        formula_version, methodology, perimeter, ...}

and every engine/endpoint is an adapter over that result:
    * `annual_report_financials.fetch_*_from_annual_report`   (legacy shape)
    * `document_analysis_engine` Strategy A/B/C rows
    * `ratio_calculation_engine.calculate_ratio`              (canonical API)

RULES THE CONTRACT ENFORCES
  1. Unknown is never zero. A missing input yields `not_disclosed` /
     `insufficient_data` with a reason - never a computed 0.
  2. Ratios consume UNROUNDED values (`value_raw`); `value` is display only.
  3. Status propagates: a derived ratio is never "better" than its parents
     (needs_review/estimated -> needs_review; unavailable -> unavailable).
  4. A mathematically valid but economically meaningless result (negative
     FCF multiple, negative growth in PEG, ...) keeps its number but is
     `not_meaningful`, never `verified`.
  5. Perimeters are explicit (SPEC[...]["perimeter"]): owners vs whole entity.
  6. Acquisition-distorted ratios (year-end balance sheet fully consolidated,
     P&L only part-year) are flagged needs_review - never adjusted.

Bump FORMULA_VERSION whenever ANY definition below changes: it is stamped on
every stored row and part of every cache key, so old results can never be
silently served as current.
"""

import math

FORMULA_VERSION = "2026.10.17"

# --------------------------------------------------------------------------------------------
# Policy switches (each one a documented Navrist methodology decision)
# --------------------------------------------------------------------------------------------
# Whose profit goes in NPM / ROA on a consolidated statement. "owners" is the user-approved
# policy (2026-10-07): shareholder-attributable profit. Both are labelled with their perimeter;
# flip a value to "whole_entity" to use total PAT (incl. NCI) without touching any formula.
PERIMETER_POLICY = {"npm": "owners", "roa": "owners"}

# Ratios whose numerator (a flow) and denominator (a balance) are not comparable in a year in
# which a material subsidiary was consolidated part-way through.
ACQUISITION_SENSITIVE = {
    "inventory_turnover", "days_inventory_outstanding", "receivables_turnover", "days_sales_outstanding",
    "payables_turnover", "days_payables_outstanding", "asset_turnover", "working_capital_turnover",
    "cash_conversion_cycle", "roa", "roce", "financial_leverage_ratio", "fixed_asset_turnover",
    "days_working_capital", "net_debt_to_ebitda", "ocf_ratio", "roic",
}

STATUS_RANK = {"verified": 0, "needs_review": 1, "not_meaningful": 2,
               "insufficient_data": 3, "not_disclosed": 4, "not_applicable": 5}
UNAVAILABLE = {"insufficient_data", "not_disclosed", "not_applicable"}
LEGACY_UNIT = {"INR_CRORE": "₹ Cr", "INR_PER_SHARE": "₹", "RATIO": "x", "ABSOLUTE_SHARES": "shares"}

# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
# EQUITY-BASIS POLICY (2026.10.10) - which "equity" each ratio uses, declared once and enforced by tests
# --------------------------------------------------------------------------------------------
# Three equity concepts exist on a consolidated balance sheet; they are NEVER interchangeable:
#   total_equity_incl_nci   `equity_full` = owners' equity + non-controlling interest. The funding base of the WHOLE consolidated
#                           entity: it pairs with whole-entity debt / assets / invested capital (100%-consolidated).
#   owners_equity           `equity` = equity attributable to owners of the parent (share capital + other equity). It pairs with
#                           owners' profit, owners' EPS, shares outstanding and market capitalisation (all owners-only claims).
#   shareholders_equity     the single figure of a STANDALONE statement or of a consolidated group with no NCI: there
#                           owners' equity == total equity, so both bases coincide (`equity_full` falls back to `equity`).
# Rule: a numerator and denominator must sit on the same perimeter. Entity-level leverage/capital ratios use total equity incl. NCI;
# per-share, return-to-owners and market-value ratios use owners' equity. ROA (owners' profit / whole assets) is the one deliberate
# mixed ratio (PERIMETER_POLICY) and uses no equity. Ratios not listed read no equity fact.
EQUITY_BASIS = {
    "debt_to_equity":           "total_equity_incl_nci",   # whole-entity debt / whole-entity equity (closing)
    "financial_leverage_ratio": "total_equity_incl_nci",   # avg total assets / avg total equity incl. NCI
    "roic":                     "total_equity_incl_nci",   # NOPAT / (debt + equity incl. NCI - cash)
    "roe":                      "owners_equity",           # owners' PAT / avg owners' equity
    "bvps":                     "owners_equity",           # owners' equity / shares
    "pb_ratio":                 "owners_equity",           # price / BVPS
    "graham_number":            "owners_equity",           # EPS(owners) x BVPS(owners)
    "sustainable_growth_rate":  "owners_equity",           # ROE(owners) x retention
}
# Equity-related inputs that appear in ratios WITHOUT being the equity fact itself (documented, tested not to read equity):
EQUITY_NOTES = {
    "roa": "owners' PAT / average total assets - no equity input (deliberate perimeter mix, see PERIMETER_POLICY)",
    "altman_z_score": "Market Cap (owners' market value of equity) / Total Liabilities (= Total Assets - total equity incl. NCI); "
                      "Retained Earnings is the owners' Other Equity proxy (always needs_review); no direct equity fact is read",
    "piotroski_f_score": "no test uses an equity figure (ROA, CFO, dROA, accruals, d(debt/assets), d(current ratio), shares, "
                         "d(gross margin), d(asset turnover))",
}

# --------------------------------------------------------------------------------------------
# SPEC - the written definition of every ratio (also shown to users as the methodology)
# --------------------------------------------------------------------------------------------
SPEC = {
    "inventory_turnover": dict(perimeter="whole_entity", basis="average inventory", definition=
        "Cost of Goods Sold ÷ Average Inventory (opening + closing) ÷ 2. COGS = Cost of materials consumed + Purchases of "
        "stock-in-trade + Changes in inventories of finished goods, WIP and stock-in-trade (the P&L's own cost lines). "
        "Formal correction 2026.10.7: the earlier Net-Sales numerator (Annual Report's own definition) was retired."),
    "days_inventory_outstanding": dict(perimeter="whole_entity", basis="derived", definition="365 ÷ Inventory Turnover (unrounded)."),
    "receivables_turnover": dict(perimeter="whole_entity", basis="average receivables", definition=
        "Revenue from Operations ÷ Average Trade Receivables (net credit sales are not disclosed - revenue is a proxy, so "
        "the result is always needs_review)."),
    "days_sales_outstanding": dict(perimeter="whole_entity", basis="derived", definition="365 ÷ Receivables Turnover (unrounded)."),
    "payables_turnover": dict(perimeter="whole_entity", basis="average payables", definition=
        "Net Purchases ÷ Average Trade Payables. Purchases = the Cost of Materials Consumed note's 'Purchases during the "
        "year' (+ Purchases of stock-in-trade); when the note line is absent Cost of Materials Consumed is a flagged proxy."),
    "days_payables_outstanding": dict(perimeter="whole_entity", basis="derived", definition="365 ÷ Payables Turnover (unrounded)."),
    "asset_turnover": dict(perimeter="whole_entity", basis="average assets", definition="Net Sales ÷ Average Total Assets."),
    "working_capital_turnover": dict(perimeter="whole_entity", basis="average working capital", definition=
        "Net Sales ÷ Average Working Capital, Working Capital = Current Assets − Current Liabilities, average = (opening + closing) "
        "÷ 2 (authoritative 68-ratio specification; same average basis as Sr 31). Closing WC is used only when the prior year is "
        "unavailable, and the result is then flagged. Corrected in 2026.10.8 - the earlier closing-WC alignment is retired."),
    "cash_conversion_cycle": dict(perimeter="whole_entity", basis="derived", definition="DSO + DOH - DPO (unrounded parents)."),
    "current_ratio": dict(perimeter="whole_entity", basis="closing", definition="Total Current Assets ÷ Total Current Liabilities."),
    "quick_ratio": dict(perimeter="whole_entity", basis="closing", definition="(Total Current Assets - Inventories) ÷ Total Current Liabilities."),
    "cash_ratio": dict(perimeter="whole_entity", basis="closing", definition=
        "(Cash & Cash Equivalents + unrestricted Other Bank Balances) ÷ Total Current Liabilities. Other Bank Balances count "
        "when the note shows they are unrestricted: restricted lines (unclaimed dividend, earmarked, margin money, lien-marked deposits) "
        "are excluded; a line of unstated nature is included but needs_review; an undisclosed split keeps the line, needs_review, with "
        "an explicit limitation. Separate from the Cash (cash & equivalents only) used by Net debt / EV / EV multiples."),
    "working_capital": dict(perimeter="whole_entity", basis="closing", definition="Total Current Assets - Total Current Liabilities."),
    "gross_profit_margin": dict(perimeter="whole_entity", basis="flow", definition=
        "(Revenue - COGS) ÷ Revenue; COGS = Cost of materials consumed + Purchases of stock-in-trade + Changes in inventories."),
    "operating_profit_margin": dict(perimeter="whole_entity", basis="flow", definition=
        "EBIT ÷ Revenue; EBIT = Profit Before Tax + Finance Costs (Other Income included - same EBIT everywhere)."),
    "net_profit_margin": dict(perimeter="owners (policy)", basis="flow", definition=
        "Owners'-attributable Profit After Tax ÷ Revenue from Operations (PERIMETER_POLICY['npm'])."),
    "roa": dict(perimeter="owners (policy)", basis="average assets", definition=
        "Owners'-attributable Profit After Tax ÷ Average Total Assets (PERIMETER_POLICY['roa'])."),
    "roe": dict(perimeter="owners", basis="average equity", definition=
        "Owners'-attributable PAT ÷ Average Owners' Equity (EQUITY_BASIS = owners_equity; never calculated on negative equity)."),
    "roce": dict(perimeter="whole_entity", basis="average capital employed", definition=
        "EBIT ÷ Average Capital Employed; Capital Employed = Total Assets - Total Current Liabilities."),
    "debt_to_equity": dict(perimeter="whole_entity", basis="closing", definition=
        "Total Debt ÷ Total Equity incl. NCI (whole-entity debt over whole-entity equity; EQUITY_BASIS = total_equity_incl_nci)."),
    "debt_ratio": dict(perimeter="whole_entity", basis="closing", definition="Total Debt ÷ Total Assets."),
    "interest_coverage_ratio": dict(perimeter="whole_entity", basis="flow", definition="EBIT ÷ Finance Costs (gross)."),
    "financial_leverage_ratio": dict(perimeter="whole_entity", basis="average", definition=
        "Average Total Assets ÷ Average Total Equity incl. NCI."),
    "pe_ratio": dict(perimeter="owners", basis="price / FY EPS", definition="Market Price ÷ Basic EPS attributable to owners."),
    "pb_ratio": dict(perimeter="owners", basis="price / closing BVPS", definition="Market Price ÷ BVPS (the single BVPS of Sr 46)."),
    "ps_ratio": dict(perimeter="whole_entity", basis="mcap / FY revenue", definition="Market Cap ÷ Revenue from Operations."),
    "dividend_yield": dict(perimeter="owners", basis="price / FY DPS", definition=
        "DPS ÷ Market Price; DPS = interim/special dividend declared during the FY + final dividend recommended for the FY."),
    "earnings_yield": dict(perimeter="owners", basis="derived", definition="Basic EPS (owners) ÷ Market Price (unrounded)."),
    "ev_to_ebitda": dict(perimeter="whole_entity", basis="closing debt/cash", definition=
        "(Market Cap + Total Debt - Cash & Cash Equivalents) ÷ EBITDA (EBIT + D&A) - the authoritative specification, and the ONE "
        "Enterprise Value definition used by Sr 29, 51 and 52. Non-controlling interest is NOT added (corrected 2026.10.8); a "
        "separately labelled 'EV incl. NCI' reference figure is carried alongside for consolidated entities with NCI but never "
        "feeds a ratio."),
    "fixed_asset_turnover": dict(perimeter="whole_entity", basis="average net fixed assets", definition=
        "Net Sales ÷ Average Net Fixed Assets; Net Fixed Assets = PPE + Right-of-use assets + Capital WIP + Intangibles "
        "(goodwill excluded)."),
    "days_working_capital": dict(perimeter="whole_entity", basis="average working capital", definition=
        "(Average Working Capital ÷ Revenue) × 365 (authoritative spec; closing WC only when the prior year is missing)."),
    "receivables_to_payables": dict(perimeter="whole_entity", basis="closing", definition="Trade Receivables ÷ Trade Payables."),
    "net_debt_to_ebitda": dict(perimeter="whole_entity", basis="closing debt/cash", definition=
        "(Total Debt - Cash & Cash Equivalents) ÷ EBITDA."),
    "dscr": dict(perimeter="whole_entity", basis="flow", definition=
        "Net Operating Income (= EBITDA, flagged proxy) ÷ (gross principal repayments + interest due [Finance Costs]). "
        "Unavailable when gross principal repayments are not disclosed - never rebuilt from net financing flows."),
    "cash_flow_coverage_ratio": dict(perimeter="whole_entity", basis="flow / closing debt", definition="Operating Cash Flow ÷ Total Debt."),
    "free_cash_flow": dict(perimeter="whole_entity", basis="flow", definition="Operating Cash Flow - gross Capex (no disposal proceeds netted)."),
    "fcf_yield": dict(perimeter="whole_entity", basis="flow / mcap", definition="Free Cash Flow ÷ Market Cap."),
    "fcf_margin": dict(perimeter="whole_entity", basis="flow", definition="Free Cash Flow ÷ Revenue."),
    "ocf_ratio": dict(perimeter="whole_entity", basis="flow / closing", definition="Operating Cash Flow ÷ Total Current Liabilities."),
    "capex_intensity": dict(perimeter="whole_entity", basis="flow", definition="Gross Capex ÷ Revenue."),
    "ocf_to_net_profit": dict(perimeter="whole_entity", basis="flow", definition=
        "Operating Cash Flow ÷ Net Profit, both whole-entity (total PAT incl. NCI)."),
    "roic": dict(perimeter="whole_entity", basis="closing invested capital", definition=
        "NOPAT ÷ Invested Capital; NOPAT = EBIT × (1 - effective tax rate); Invested Capital = Total Debt + Total Equity "
        "(incl. NCI) - Cash & Cash Equivalents (closing, per spec)."),
    "effective_tax_rate": dict(perimeter="whole_entity", basis="flow", definition="Total Tax Expense ÷ Profit Before Tax."),
    "contribution_margin": dict(perimeter="whole_entity", basis="flow (PROXY)", definition=
        "(Revenue - Variable Costs) ÷ Revenue. Variable costs are NOT disclosed: reconstructed from goods cost + Direct "
        "Expenses / volume-linked Other-Expenses note items. Always a flagged proxy (needs_review); unavailable when only "
        "goods cost could be identified."),
    "eps_growth_rate": dict(perimeter="owners", basis="YoY", definition="(Current Basic EPS (owners) ÷ Prior Basic EPS (owners)) - 1."),
    "bvps": dict(perimeter="owners", basis="closing", definition="Owners' Equity ÷ Equity Shares Outstanding (closing). The ONE BVPS."),
    "dividend_payout_ratio": dict(perimeter="owners (cash dividends: whole entity)", basis="flow", definition=
        "Dividends PAID (cash flow statement) ÷ owners' Net Profit. Declared DPS × shares only as a flagged estimate when "
        "no paid line exists; unavailable (never 0) when neither exists."),
    "retention_ratio": dict(perimeter="owners", basis="derived", definition="100% - Dividend Payout (only when payout is available)."),
    "sustainable_growth_rate": dict(perimeter="owners", basis="derived", definition="ROE × Retention (both must be available)."),
    "peg_ratio": dict(perimeter="owners", basis="derived", definition="P/E ÷ EPS growth (%) (not meaningful when growth ≤ 0)."),
    "ev_to_sales": dict(perimeter="whole_entity", basis="derived", definition=
        "Enterprise Value (Market Cap + Debt + NCI - Cash) ÷ Revenue."),
    "ev_to_fcf": dict(perimeter="whole_entity", basis="derived", definition=
        "Enterprise Value (Market Cap + Debt + NCI - Cash) ÷ Free Cash Flow (not meaningful when FCF ≤ 0)."),
    "price_to_cash_flow": dict(perimeter="whole_entity", basis="mcap / flow", definition="Market Cap ÷ Operating Cash Flow."),
    "graham_number": dict(perimeter="owners", basis="derived", definition="√(22.5 × EPS (owners) × BVPS)."),
    "altman_z_score": dict(perimeter="whole_entity", basis="closing", definition=
        "1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MktCap/Total Liabilities + 1.0·Sales/TA; Total Liabilities as reported "
        "(NCI is never booked as a liability); RE = Other Equity proxy (needs_review)."),
    "piotroski_f_score": dict(perimeter="whole_entity", basis="two-year", definition=
        "Nine binary tests; a score is reported only when all nine can be evaluated, otherwise insufficient_data."),
    "beneish_m_score": dict(perimeter="whole_entity", basis="two-year", definition=
        "8-variable M-Score; SGAI uses Other Expenses as the SG&A proxy (needs_review)."),
}

ALL_KEYS_ORDER = None  # filled lazily from the registry


def _registry():
    from tools.fundamental_ratio_registry import BY_RATIO_KEY, BY_SR_NO
    return BY_RATIO_KEY, BY_SR_NO


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------
def _fstatus(f):
    if f is None or f.value is None:
        return "not_disclosed"
    if f.status == "NEEDS_REVIEW" or f.estimated:
        return "needs_review"
    return "verified"


def _prov(f):
    return {"fact": f.fact_key, "value": f.value, "prior_value": f.prior_value, "unit": f.unit, "period": f.period,
            "statement_basis": f.statement_basis, "perimeter": f.perimeter, "source": f.source_document,
            "source_page": f.source_page, "source_tag": f.source_tag, "extraction_method": f.extraction_method,
            "status": f.status, "confidence": f.confidence, "estimated": f.estimated,
            "raw_label": f.raw_label, "warnings": list(f.warnings)}


def _rd(x, n=2):
    return None if x is None else round(x, n)


def _res(key, *, value_raw=None, unit="x", status="verified", confidence=1.0, estimated=False, num=None,
         den=None, facts=(), warnings=(), reason=None, extra=None, line_items=None):
    reg, _ = _registry()
    spec = reg.get(key) or {}
    sp = SPEC.get(key, {})
    facts = [f for f in facts if f is not None]
    est = bool(estimated or status == "needs_review" or any(f.estimated for f in facts))
    out = {
        "ratio_key": key, "sr_no": spec.get("sr_no"), "label": spec.get("label"), "formula": spec.get("formula"),
        "formula_version": FORMULA_VERSION, "methodology": sp.get("definition"), "perimeter": sp.get("perimeter"),
        "period_basis": sp.get("basis"), "unit": unit, "value_raw": value_raw,
        "value": _rd(value_raw), "status": status, "confidence": confidence, "estimated": est,
        "numerator": num, "denominator": den, "warnings": list(dict.fromkeys(warnings)), "reason": reason,
        "inputs": [_prov(f) for f in facts],
    }
    if line_items:
        out["line_items"] = line_items
    if extra:
        out.update(extra)
    return out


def _unavailable(key, facts_needed, fs, reason=None, unit="x", status=None, extra=None):
    """Result for a ratio whose inputs are missing. Never a number."""
    missing = [f for f in facts_needed if f is None or getattr(f, "value", None) is None]
    st = status
    if st is None:
        st = "insufficient_data" if any(m is not None and m.status == "INSUFFICIENT_DATA" for m in missing) \
            else "not_disclosed"
    why = reason
    if why is None:
        w = [x for m in missing if m is not None for x in m.warnings]
        names = ", ".join(sorted({(m.fact_key if m is not None else "?") for m in missing}))
        why = (w[0] if w else f"Required input(s) not found in the filing: {names}.")
    return _res(key, unit=unit, status=st, confidence=0.0, estimated=False, reason=why,
                facts=[f for f in facts_needed if f is not None], extra=extra)


def _merge(base_status, base_conf, base_est, facts, warnings=()):
    """Folds the facts' own uncertainty into a result's status/confidence."""
    st, conf, est, warns = base_status, base_conf, base_est, list(warnings)
    for f in facts:
        if f is None:
            continue
        if _fstatus(f) == "needs_review":
            if STATUS_RANK[st] < STATUS_RANK["needs_review"]:
                st = "needs_review"
            est = True
        if f.confidence is not None:
            conf = min(conf, f.confidence)
        warns.extend(f.warnings)
    return st, conf, est, warns


def _acq_guard(key, fs, res):
    acq = (fs.extras or {}).get("acquisition") or {}
    if key in ACQUISITION_SENSITIVE and acq.get("flag") and res.get("value_raw") is not None \
            and res["status"] in ("verified", "needs_review"):
        res["warnings"].append(
            "Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the "
            "P&L carries only its part-year contribution, so flows and balances are not on a comparable footing ("
            + "; ".join(acq.get("reasons") or []) + ").")
        res["status"] = "needs_review"
        res["estimated"] = True
        res["confidence"] = min(res.get("confidence") or 1.0, 0.8)
        res["acquisition_flag"] = True
    return res


_BY_YEAR_KEYS = {"inventory": "inventory_by_year", "receivables": "receivables_by_year",
                 "payables": "payables_by_year", "total_assets": "total_assets_by_year",
                 "equity": "equity_by_year", "equity_full": "equity_by_year",
                 "net_fixed_assets": "net_fixed_assets_by_year", "capital_employed": "capital_employed_by_year",
                 "working_capital": "working_capital_by_year"}


def _leg(fs, fact, mode, label, comps=None, closing_label=None):
    """-> (value, descriptor_dict, estimated_flag, fact). mode: cur | avg."""
    f = fs.get(fact)
    if f is None or f.value is None:
        return None, None, False, f
    fy = fs.fiscal_year
    d = {"label": label, "value_cr": None}
    est = False
    v = f.value
    by_year = {f"FY{fy}": round(f.value, 2)}
    if f.prior_value is not None:
        by_year[f"FY{fy - 1}"] = round(f.prior_value, 2)
    if mode == "avg":
        if f.prior_value is not None:
            v = (f.value + f.prior_value) / 2.0
        else:
            est = True
            d["label"] = (closing_label or f"Closing {label.split(' (')[0]} (opening/prior-year unavailable)")
    d["value_cr"] = round(v, 2)
    d["value_raw"] = v                       # unrounded value actually divided (breakdown provenance)
    d["fact"] = fact
    d["averaged"] = bool(mode == "avg" and f.prior_value is not None)
    if fact in _BY_YEAR_KEYS:
        d[_BY_YEAR_KEYS[fact]] = by_year
    if comps:
        d["components"] = comps
    return v, d, est, f


def _legd(label, raw, fact=None, parts=None, **kw):
    """Hand-built leg descriptor carrying the UNROUNDED value (`value_raw`) the arithmetic used, the fact it was
    read from and - for composite values - its signed `parts` (so the calculation breakdown can show every number)."""
    d = {"label": label, "value_cr": round(raw, 2), "value_raw": raw}
    if fact:
        d["fact"] = fact
    if parts:
        d["parts"] = parts
    d.update(kw)
    return d


def _part(label, raw, sign=1, fact=None, **kw):
    return {"label": label, "value_raw": raw, "sign": sign, **({"fact": fact} if fact else {}), **kw}


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _two_leg(fs, key, unit, num_fact, num_mode, num_label, den_fact, den_mode, den_label, mult=1.0,
             den_positive=False, reason_nonpositive=None, num_comps=None, den_comps=None, extra=None,
             base_conf=1.0, base_status="verified", warnings=(), den_closing_label=None, num_closing_label=None,
             allow_negative_den=False):
    nv, nd, ne, nf = _leg(fs, num_fact, num_mode, num_label, num_comps, num_closing_label)
    dv, dd, de, df = _leg(fs, den_fact, den_mode, den_label, den_comps, den_closing_label)
    if nv is None or dv is None:
        return _unavailable(key, [nf, df], fs, unit=unit)
    if dv == 0:
        return _res(key, unit=unit, status="insufficient_data", confidence=0.0,
                    reason=f"{den_label} is zero - the ratio would be undefined.", num=nd, den=dd, facts=[nf, df])
    if den_positive and dv < 0:
        return _res(key, unit=unit, status="not_meaningful", confidence=0.0,
                    reason=reason_nonpositive or f"{den_label} is negative - the ratio would be meaningless/sign-inverted.",
                    num=nd, den=dd, facts=[nf, df])
    raw = nv / dv * mult
    conf, est = base_conf, ne or de
    if est:
        conf = min(conf, 0.8)
    st, conf, est, warns = _merge(base_status, conf, est, [nf, df], warnings)
    if est and st == "verified":
        st = "needs_review"
    return _res(key, value_raw=raw, unit=unit, status=st, confidence=conf, estimated=est, num=nd, den=dd,
                facts=[nf, df], warnings=warns, extra=extra)


def _eq_full_label(f):
    return "Total Equity incl. Non-Controlling Interests" if f is not None else "Total Equity"


# --------------------------------------------------------------------------------------------
# market helpers
# --------------------------------------------------------------------------------------------
def live_market(symbol, bse_code=None):
    """Current price, kept strictly separate from every statement fact. None if unavailable."""
    try:
        from tools.market_price import get_live_price
        px = get_live_price(symbol, bse_code=bse_code) if bse_code else get_live_price(symbol)
    except Exception:
        px = None
    if not px or px.get("ltp") is None:
        return None
    import datetime as _dt
    return {"price": float(px["ltp"]), "source": px.get("source") or "unknown", "as_of": "live quote",
            "quoted_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "prev_close": px.get("close")}


def _mcap(fs, market):
    sh = fs.get("shares_outstanding")
    if market is None or sh is None or not sh.value:
        return None
    return market["price"] * sh.value / 1e7          # -> INR crore


def _market_input(market):
    return {"label": "Market price", "value_cr": round(market["price"], 2), "value_raw": market["price"], "unit": "₹",
            "source": (f"Latest quote ({market.get('source')})" + (f" fetched {market['quoted_at']}" if market.get("quoted_at") else "")
                       + " - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures"),
            "kind": "market"}


def _const(v, text):
    """A literal constant inside an `expr` leg (e.g. the crore divisor)."""
    return {"const": v, "text": text}


_CRORE = _const(1e7, "1,00,00,000 (₹ → ₹ crore)")


def _mcap_leg(fs, market, mc):
    sh = fs.get("shares_outstanding")
    return _legd("Market Capitalisation (price × shares outstanding)", mc,
                 expr=[_market_input(market), "×", _legd("Equity Shares Outstanding", sh.value, "shares_outstanding", unit="shares"),
                       "÷", _CRORE])


def _ev_leg(fs, market, ev):
    mc, debt, cash = _mcap(fs, market), fs.get("total_debt"), fs.get("cash")
    parts = [{"leg": _mcap_leg(fs, market, mc), "sign": 1, "label": "Market Capitalisation", "value_raw": mc},
             _part("Total Debt", debt.value, 1, "total_debt"),
             _part("Cash and Cash Equivalents", cash.value, -1, "cash")]
    return _legd("Enterprise Value (Market Cap + Total Debt − Cash & Cash Equivalents)", ev, parts=parts)


def _no_market(key, unit="x"):
    return _res(key, unit=unit, status="insufficient_data", confidence=0.0,
                reason="A live market price is required and could not be obtained.")


def _nci_reference(fs):
    """Non-controlling interest at book value, for the SEPARATE reference figure 'EV incl. NCI' only (see `_ev_incl_nci_reference`).
    It is never part of the Navrist EV metric: the authoritative specification defines EV = Market Cap + Debt - Cash. Returns
    None when the NCI of a consolidated entity cannot be read (the reference is then simply not offered - nothing is assumed)."""
    nci = fs.get("nci")
    if fs.selection.selected_basis != "CONSOLIDATED":
        return 0.0
    if nci is None or nci.value is None:
        return None
    return nci.value


def _enterprise_value(fs, market):
    """Navrist EV (Sr 29 / 51 / 52, ONE definition): Market Cap + Total Debt - Cash & Cash Equivalents (authoritative spec)."""
    mc = _mcap(fs, market)
    debt, cash = fs.get("total_debt"), fs.get("cash")
    base_facts = [debt, cash, fs.get("shares_outstanding")]
    if mc is None or debt is None or debt.value is None or cash is None or cash.value is None:
        return None, base_facts
    return mc + debt.value - cash.value, base_facts


def _ev_incl_nci_reference(fs, ev):
    """A SEPARATE, clearly labelled 'consolidated enterprise value' (EV + book NCI) offered as reference data next to the metric.
    It never feeds a ratio, a status or a warning; None when NCI is unreadable or nil."""
    nci = _nci_reference(fs)
    if ev is None or not nci:
        return None
    return {"label": "Reference only - EV incl. Non-Controlling Interest (book); NOT the Navrist EV", "ev_incl_nci_cr": ev + nci,
            "nci_cr": nci}


def _ev_nci_warns(fs):
    return []


# --------------------------------------------------------------------------------------------
# the formulas
# --------------------------------------------------------------------------------------------
def _sl(fs):
    """Label of the sales leg: 'Net Sales ...' when excise duty was deducted, otherwise the reported 'Revenue from Operations'."""
    f = fs.get("net_sales")
    return ("Net Sales (Revenue from Operations − Excise Duty)" if f is not None and f.source_tag == "revenue-excise_duty"
            else "Revenue from Operations")


def _r_inventory_turnover(fs, market, deps):
    key = "inventory_turnover"
    comps = (fs.extras or {}).get("components") or {}
    cogs = fs.get("cogs")
    if not comps:
        return _res(key, status="not_disclosed", confidence=0.0,
                    reason="No Cost of Goods Sold line items (Cost of materials consumed / Purchases of stock-in-trade / "
                           "Changes in inventories) were found - either not a goods business or not extracted; nothing is assumed.")
    inv = fs.get("inventory")
    if inv is None or inv.value is None:
        return _unavailable(key, [inv], fs, reason="Could not find 'Inventories' row on the Balance Sheet page.")
    if inv.value <= 0:
        return _res(key, status="insufficient_data", confidence=0.0, reason="Inventory value is zero or missing.", facts=[inv])
    if cogs is None or cogs.value is None:
        return _unavailable(key, [cogs], fs, reason="Cost of Goods Sold could not be built from the P&L expense lines.")
    if cogs.value <= 0:
        return _res(key, status="insufficient_data", confidence=0.0, facts=[cogs],
                    reason="Cost of Goods Sold (materials consumed + purchases of stock-in-trade + changes in inventories) is zero or "
                           "negative, so inventory turnover cannot be computed from it.")
    extra = {}
    r = _two_leg(fs, key, "x", "cogs", "cur", "Cost of Goods Sold", "inventory", "avg",
                 "Average Inventory (opening + closing) ÷ 2", base_conf=0.95 if len(comps) < 3 else 1.0, extra=extra)
    if r.get("numerator"):
        r["numerator"]["components"] = {k: round(v[0], 2) for k, v in comps.items()}
        r["numerator"]["label"] = "Cost of Goods Sold (sum of the P&L cost lines below)"
    return r


def _r_receivables_turnover(fs, market, deps):
    r = _two_leg(fs, "receivables_turnover", "x", "net_sales", "cur", _sl(fs), "receivables", "avg",
                 "Average Trade Receivables (opening + closing) ÷ 2", base_conf=0.8, base_status="needs_review",
                 warnings=("Net credit sales are not disclosed; Revenue from Operations is used as the proxy.",))
    if r["value_raw"] is not None:
        r["estimated"] = True
        r["confidence"] = min(r["confidence"], 0.8) if (r.get("denominator") or {}).get("receivables_by_year", {}).get(
            f"FY{fs.fiscal_year - 1}") is not None else 0.4
    return r


def _r_payables_turnover(fs, market, deps):
    key = "payables_turnover"
    pur = fs.get("purchases")
    if pur is None or pur.value is None:
        return _unavailable(key, [pur], fs, reason="Neither Purchases (a+b) nor the COGS/Inventory fallback data was available.")
    pay = fs.get("payables")
    if pay is None or pay.value is None:
        return _unavailable(key, [pay], fs, reason="Could not find 'Trade payables' row on the Balance Sheet page.")
    if pur.value <= 0:
        return _res(key, status="insufficient_data", confidence=0.0, reason="Purchases is zero or missing.", facts=[pur])
    if pay.value <= 0:
        return _res(key, status="insufficient_data", confidence=0.0, reason="Trade payables value is zero or missing.", facts=[pay])
    tag = pur.source_tag or ""
    if "proxy" in tag:
        lab = "Purchases (a: Cost of materials consumed - PROXY, the note's purchases line was not found)"
    elif "purchases_during_the_year" in tag and "stock_in_trade" in tag:
        lab = "Purchases (a: Purchases during the year (Cost of Materials Consumed note) + b: Purchases of stock-in-trade)"
    elif "purchases_during_the_year" in tag:
        lab = "Purchases (a: Purchases during the year (Cost of Materials Consumed note); no Purchases of stock-in-trade disclosed)"
    elif "stock_in_trade" in tag:
        lab = "Purchases (b: Purchases of stock-in-trade - a pure trading business, no Cost of materials consumed)"
    else:
        lab = "Purchases (fallback: COGS − (Opening Inventories − Closing Inventories))"
    comps = (fs.extras or {}).get("components") or {}
    r = _two_leg(fs, key, "x", "purchases", "cur", lab, "payables", "avg", "Average Trade Payables (opening + closing) ÷ 2")
    if r["value_raw"] is not None and "a: Purchases during the year" in lab and len(comps) and not (
            "Purchases of stock-in-trade" in comps):
        r["confidence"] = min(r["confidence"], 0.95)
    return r


def _r_asset_turnover(fs, market, deps):
    return _two_leg(fs, "asset_turnover", "x", "net_sales", "cur", _sl(fs), "total_assets", "avg",
                    "Average Total Assets (opening + closing) ÷ 2", den_positive=True)


def _r_working_capital_turnover(fs, market, deps):
    r = _two_leg(fs, "working_capital_turnover", "x", "net_sales", "cur", _sl(fs), "working_capital",
                 "avg", "Average Working Capital (opening + closing) ÷ 2, Working Capital = Current Assets − Current Liabilities",
                 den_positive=True,
                 den_closing_label="Closing Working Capital (opening/prior-year unavailable)",
                 reason_nonpositive="Average Working Capital is negative - the ratio would be meaningless/sign-inverted, so it is "
                                    "withheld rather than reported.")
    return r


def _r_current_ratio(fs, market, deps):
    return _two_leg(fs, "current_ratio", "x", "total_current_assets", "cur", "Total Current Assets (closing)",
                    "total_current_liabilities", "cur", "Total Current Liabilities (closing)")


def _r_quick_ratio(fs, market, deps):
    key = "quick_ratio"
    tca, tcl, inv = fs.get("total_current_assets"), fs.get("total_current_liabilities"), fs.get("inventory")
    if tca is None or tca.value is None or tcl is None or tcl.value is None:
        return _unavailable(key, [tca, tcl], fs)
    comps = (fs.extras or {}).get("components") or {}
    warns = []
    if inv is None or inv.value is None:
        if comps:
            return _unavailable(key, [inv], fs, reason="A goods business (it reports Cost of Goods Sold) but its 'Inventories' "
                                                         "row could not be found - not assumed to be zero.")
        inv_v = 0.0
        warns.append("No Inventories line and no Cost of Goods Sold lines: treated as a business with no inventory.")
    else:
        inv_v = inv.value
    if tcl.value == 0:
        return _res(key, status="insufficient_data", confidence=0.0, reason="Total Current Liabilities is zero.", facts=[tca, tcl, inv])
    qa = tca.value - inv_v
    st, conf, est, w = _merge("verified", 1.0, False, [tca, tcl, inv], warns)
    return _res(key, value_raw=qa / tcl.value, status=st, confidence=conf, estimated=est, facts=[tca, tcl, inv], warnings=w,
                num=_legd("Total Current Assets − Inventories (closing)", qa,
                          parts=[_part("Total Current Assets", tca.value, 1, "total_current_assets"),
                                 _part("Inventories", inv_v, -1, "inventory" if inv is not None and inv.value is not None else None,
                                       **({} if inv is not None and inv.value is not None else {"note": "No Inventories line and no goods-cost lines: treated as no inventory."}))],
                          components={"Total Current Assets": round(tca.value, 2), "less: Inventories": round(inv_v, 2)}),
                den=_legd("Total Current Liabilities (closing)", tcl.value, "total_current_liabilities"),
                line_items=[{"label": "Current Assets", "value_cr": round(tca.value, 2)},
                            {"label": "Inventory", "value_cr": round(inv_v, 2)},
                            {"label": "Current Liabilities", "value_cr": round(tcl.value, 2)}])


def _r_cash_ratio(fs, market, deps):
    key = "cash_ratio"
    cash, tcl, obb = fs.get("cash"), fs.get("total_current_liabilities"), fs.get("other_bank_balances")
    if cash is None or cash.value is None:
        return _unavailable(key, [cash], fs, reason="Could not find 'Cash and Cash Equivalents' row on the Balance Sheet page.")
    if tcl is None or tcl.value is None:
        return _unavailable(key, [tcl], fs, reason="Could not find 'Total Current Liabilities' row on the Balance Sheet page.")
    if tcl.value == 0:
        return _res(key, status="insufficient_data", confidence=0.0, reason="Total Current Liabilities is zero.", facts=[cash, tcl])
    breakup = (fs.extras or {}).get("other_bank_balances_breakup")
    unrestricted = breakup.get("unrestricted_cur") if breakup else None
    obb_cur = round(obb.value, 2) if obb is not None and obb.value is not None else None
    # Cash and bank balances: cash & cash equivalents plus current "other bank balances" (deposits < 12 months). When the notes give a
    # restricted/unrestricted split only the unrestricted part counts; otherwise the whole current line is used (it is a current
    # liquid asset) and the caveat is carried as a warning rather than silently dropping it.
    if unrestricted is not None:
        obb_used = unrestricted
    else:
        obb_used = obb.value if obb is not None and obb.value is not None else 0.0
    numerator = cash.value + obb_used
    include_all = unrestricted is None and obb_cur is not None and abs(obb_cur) >= 0.005
    unclassified = (breakup or {}).get("unclassified_cur") if unrestricted is not None else None
    excluded = (breakup or {}).get("netoff_cur") if unrestricted is not None else None
    label = ("Cash and Cash Equivalents + Unrestricted Other Bank Balances (closing)" if unrestricted is not None
             else "Cash and Cash Equivalents + Other Bank Balances (closing)" if include_all
             else "Cash and Cash Equivalents (closing)")
    cw = []
    if include_all:
        cw.append("LIMITATION: the source does not separate restricted/lien-marked from free balances, so the whole current "
                  "'Other bank balances' line is included - the ratio may be overstated by any restricted portion.")
    if unrestricted is not None and excluded:
        cw.append(f"Restricted / lien-marked balances of {excluded:,.2f} Cr were excluded from the numerator.")
    if unclassified:
        cw.append(f"{unclassified:,.2f} Cr of other bank balances sits on a line whose nature the note does not state "
                  "(e.g. 'Deposit account'); no restriction is disclosed so it is included, but it is not confirmed as free cash.")
    needs = include_all or bool(unclassified)
    st, conf, est, w = _merge("needs_review" if needs else "verified", 0.8 if needs else 1.0, needs, [cash, tcl], cw)
    return _res(key, value_raw=numerator / tcl.value, status=st, confidence=conf, estimated=est, facts=[cash, tcl, obb],
                warnings=w, num=_legd(label, numerator, "cash" if not (unrestricted is not None or include_all) else None,
                                      parts=([_part("Cash and Cash Equivalents", cash.value, 1, "cash"),
                                              _part("Other Bank Balances" if include_all else "Unrestricted Other Bank Balances (Notes breakup)",
                                                    obb_used, 1, "other_bank_balances")]
                                             if (unrestricted is not None or include_all) else None)),
                den=_legd("Total Current Liabilities (closing)", tcl.value, "total_current_liabilities"),
                extra={"other_bank_balances_cr": obb_cur, "other_bank_balances_breakup": breakup,
                       "obb_classification": (breakup or {}).get("components")})


def _r_working_capital(fs, market, deps):
    wc = fs.get("working_capital")
    if wc is None or wc.value is None:
        return _unavailable("working_capital", [fs.get("total_current_assets"), fs.get("total_current_liabilities")], fs, unit="₹ Cr")
    tca, tcl = fs.get("total_current_assets"), fs.get("total_current_liabilities")
    st, conf, est, w = _merge("verified", 1.0, False, [wc, tca, tcl])
    return _res("working_capital", value_raw=wc.value, unit="₹ Cr", status=st, confidence=conf, estimated=est,
                facts=[tca, tcl], warnings=w,
                num=_legd("Total Current Assets (closing)", tca.value, "total_current_assets"),
                den=_legd("Total Current Liabilities (closing)", tcl.value, "total_current_liabilities"))


def _r_gross_profit_margin(fs, market, deps):
    key = "gross_profit_margin"
    comps = (fs.extras or {}).get("components") or {}
    rev, cogs = fs.get("net_sales"), fs.get("cogs")
    if not comps or cogs is None or cogs.value is None:
        return _res(key, unit="%", status="not_disclosed", confidence=0.0,
                    reason="No Cost of Goods Sold line items were found - either not a goods business or not extracted; "
                           "nothing is assumed.")
    if rev is None or rev.value is None:
        return _unavailable(key, [rev], fs, unit="%", reason="Could not find 'Revenue from operations' row on the P&L page.")
    if rev.value <= 0:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, reason="Revenue from operations is zero or negative.", facts=[rev])
    gp = rev.value - cogs.value
    comp_out = {_sl(fs): round(rev.value, 2)}
    for k, v in comps.items():
        comp_out[f"less: {k}"] = round(v[0], 2)
    st, conf, est, w = _merge("verified", 0.95 if len(comps) < 3 else 1.0, False, [rev, cogs])
    return _res(key, value_raw=gp / rev.value * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[rev, cogs],
                warnings=w, num=_legd("Gross Profit (Revenue − COGS)", gp, components=comp_out,
                                      parts=[_part(_sl(fs), rev.value, 1, "net_sales")] +
                                            [_part(k, v[0], -1, statement="Statement of Profit and Loss (expense note)") for k, v in comps.items()]),
                den=_legd(_sl(fs), rev.value, "net_sales"))


def _ebit_num(fs, ebit):
    pbt, fc = fs.get("pbt"), fs.get("finance_costs")
    comps = None
    parts = None
    if pbt is not None and pbt.value is not None and fc is not None and fc.value is not None and ebit.source_tag == "pbt+finance_costs":
        comps = {"Profit Before Tax": round(pbt.value, 2), "add back: Finance Costs": round(fc.value, 2)}
        parts = [_part("Profit Before Tax", pbt.value, 1, "pbt"), _part("Finance Costs (added back)", fc.value, 1, "finance_costs")]
    elif ebit.source_tag == "revenue-total_expenses+finance_costs":
        rev, te = fs.get("revenue"), fs.get("total_expenses")
        if all(x is not None and x.value is not None for x in (rev, te, fc)):
            parts = [_part("Revenue from Operations", rev.value, 1, "revenue"), _part("Total Expenses", te.value, -1, "total_expenses"),
                     _part("Finance Costs (added back)", fc.value, 1, "finance_costs")]
    return _legd("Operating Profit (Profit Before Tax + Finance Costs)", ebit.value, "ebit", parts=parts,
                 **({"components": comps} if comps else {}))


def _r_operating_profit_margin(fs, market, deps):
    key = "operating_profit_margin"
    rev, ebit = fs.get("net_sales"), fs.get("ebit")
    if rev is None or rev.value is None:
        return _unavailable(key, [rev], fs, unit="%", reason="Could not find 'Revenue from operations' row on the P&L page.")
    if ebit is None or ebit.value is None:
        return _unavailable(key, [ebit], fs, unit="%")
    if rev.value <= 0:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, reason="Revenue from operations is zero or negative.", facts=[rev])
    st, conf, est, w = _merge("verified", 1.0, False, [rev, ebit])
    return _res(key, value_raw=ebit.value / rev.value * 100, unit="%", status=st, confidence=conf, estimated=est,
                facts=[rev, ebit], warnings=w, num=_ebit_num(fs, ebit),
                den=_legd(_sl(fs), rev.value, "net_sales"),
                extra={"formula": "(Profit Before Tax + Finance Costs) / Revenue from Operations x 100"})


def _pat_fact(fs, policy_key):
    pol = PERIMETER_POLICY.get(policy_key, "owners")
    return (fs.get("pat_total") if pol == "whole_entity" else fs.get("pat")), pol


def _r_net_profit_margin(fs, market, deps):
    pat, pol = _pat_fact(fs, "npm")
    label = ("Profit for the Year Attributable to Owners of the Company" if pol == "owners"
             else "Profit for the Year (whole entity, incl. NCI)")
    r = _two_leg(fs, "net_profit_margin", "%", "pat" if pol == "owners" else "pat_total", "cur", label,
                 "net_sales", "cur", _sl(fs), mult=100.0, den_positive=True,
                 reason_nonpositive="Revenue from operations is zero or negative.")
    if r.get("value_raw") is not None and pol == "owners" and (fs.extras or {}).get("nci_material"):
        r["warnings"].append("Perimeter: owners' profit over 100%-consolidated revenue (NCI share of profit excluded).")
    return r


def _r_roa(fs, market, deps):
    pat, pol = _pat_fact(fs, "roa")
    fact = "pat" if pol == "owners" else "pat_total"
    label = "Profit After Tax (owners-attributable)" if pol == "owners" else "Profit After Tax (whole entity, incl. NCI)"
    r = _two_leg(fs, "roa", "%", fact, "cur", label, "total_assets", "avg", "Average Total Assets (opening + closing) ÷ 2",
                 mult=100.0, den_positive=True)
    if r.get("value_raw") is not None and pol == "owners" and (fs.extras or {}).get("nci_material"):
        r["warnings"].append("Perimeter: owners' profit over whole-entity assets (assets include NCI-funded assets).")
    return r


def _r_roe(fs, market, deps):
    key = "roe"
    pat, eq = fs.get("pat"), fs.get("equity")
    if pat is None or pat.value is None:
        return _unavailable(key, [pat], fs, unit="%", reason="Could not find a 'Profit for the year'/'Profit after tax' row on the P&L page.")
    if eq is None or eq.value is None:
        return _unavailable(key, [eq], fs, unit="%", reason="Could not find a 'Total Equity'/'Shareholders' Funds' row on the Balance Sheet page.")
    if eq.value <= 0 or (eq.prior_value is not None and eq.prior_value <= 0):
        return _res(key, unit="%", status="not_meaningful", confidence=0.0, facts=[pat, eq],
                    reason="Shareholders' Equity is negative (or zero) - ROE would be meaningless (negative ÷ negative gives a spurious positive).",
                    num={"label": "Profit After Tax (owners-attributable)", "value_cr": round(pat.value, 2)},
                    den={"label": "Total Equity", "value_cr": round(eq.value, 2)})
    lab = "Average Total Equity (opening + closing) ÷ 2 - Total Equity Attributable to Owners of the Company"
    return _two_leg(fs, key, "%", "pat", "cur", "Profit After Tax (owners-attributable)", "equity", "avg", lab, mult=100.0,
                    den_closing_label="Closing Total Equity - Total Equity Attributable to Owners of the Company (opening/prior-year unavailable)")


def _r_roce(fs, market, deps):
    key = "roce"
    ebit = fs.get("ebit")
    if ebit is None or ebit.value is None:
        return _unavailable(key, [ebit], fs, unit="%")
    ce = fs.get("capital_employed")
    r = _two_leg(fs, key, "%", "ebit", "cur", "EBIT (Sr No 15)", "capital_employed", "avg",
                 "Average Capital Employed (opening + closing) ÷ 2", mult=100.0, den_positive=True,
                 reason_nonpositive="Average Capital Employed is negative - the ratio would be meaningless.")
    if r.get("numerator"):
        r["numerator"] = _ebit_num(fs, ebit) | {"label": "EBIT (Sr No 15)"}
    r["shared_dependencies"] = {"ebit_source": "Sr No 15", "ebit_value_cr": round(ebit.value, 2), "ebit_consistent": True}
    return r


def _debt_comps(fs):
    return (fs.extras or {}).get("debt_components")


def _r_debt_to_equity(fs, market, deps):
    key = "debt_to_equity"
    debt, eqf = fs.get("total_debt"), fs.get("equity_full")
    if debt is None or debt.value is None:
        return _unavailable(key, [debt], fs, reason=(fs.extras or {}).get("debt_reason"))
    if eqf is None or eqf.value is None:
        return _unavailable(key, [eqf], fs, reason="Could not find a 'Total Equity' row on the Balance Sheet page.")
    if eqf.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[debt, eqf],
                    reason="Total Equity is negative or zero - the ratio would be meaningless.")
    st, conf, est, w = _merge("verified", 1.0, False, [debt, eqf])
    return _res(key, value_raw=debt.value / eqf.value, status=st, confidence=conf, estimated=est, facts=[debt, eqf], warnings=w,
                num=_legd("Total Debt (closing)", debt.value, "total_debt", components=_debt_comps(fs)),
                den=_legd(f"{_eq_full_label(eqf)} (closing)", eqf.value, "equity_full"))


def _r_debt_ratio(fs, market, deps):
    key = "debt_ratio"
    debt, ta = fs.get("total_debt"), fs.get("total_assets")
    if debt is None or debt.value is None:
        return _unavailable(key, [debt], fs, reason=(fs.extras or {}).get("debt_reason"))
    if ta is None or ta.value is None:
        return _unavailable(key, [ta], fs, reason="Could not find 'Total Assets' row on the Balance Sheet page.")
    if ta.value <= 0:
        return _res(key, status="insufficient_data", confidence=0.0, reason="Total Assets value is zero or missing.", facts=[ta])
    st, conf, est, w = _merge("verified", 1.0, False, [debt, ta])
    return _res(key, value_raw=debt.value / ta.value, status=st, confidence=conf, estimated=est, facts=[debt, ta], warnings=w,
                num=_legd("Total Debt (closing) - identical to Debt-to-Equity's numerator", debt.value, "total_debt",
                          components=_debt_comps(fs)),
                den=_legd("Total Assets (closing balance, not averaged)", ta.value, "total_assets"))


def _r_interest_coverage(fs, market, deps):
    key = "interest_coverage_ratio"
    ebit, fc = fs.get("ebit"), fs.get("finance_costs")
    if ebit is None or ebit.value is None:
        return _unavailable(key, [ebit], fs)
    if fc is None or fc.value is None:
        return _unavailable(key, [fc], fs, reason="Could not find a 'Finance Costs' row on the P&L page.")
    if fc.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[ebit, fc],
                    reason="Finance costs are zero - interest coverage is not meaningful for a company with no interest burden.")
    st, conf, est, w = _merge("verified", 1.0, False, [ebit, fc])
    num = _ebit_num(fs, ebit)
    num["label"] = "EBIT (Profit Before Tax + Finance Costs)"
    return _res(key, value_raw=ebit.value / fc.value, status=st, confidence=conf, estimated=est, facts=[ebit, fc], warnings=w,
                num=num, den=_legd("Interest Expense (Finance Costs, gross - not netted against Interest Income)", fc.value,
                                   "finance_costs"))


def _r_financial_leverage(fs, market, deps):
    return _two_leg(fs, "financial_leverage_ratio", "x", "total_assets", "avg", "Average Total Assets (opening + closing) ÷ 2",
                    "equity_full", "avg", "Average Total Equity incl. Non-Controlling Interests", den_positive=True,
                    reason_nonpositive="Total Equity is negative - financial leverage would be meaningless.")


def _r_pe(fs, market, deps):
    key = "pe_ratio"
    eps = fs.get("eps")
    if market is None:
        return _no_market(key)
    if eps is None or eps.value is None:
        return _unavailable(key, [eps], fs)
    if eps.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[eps],
                    reason="Basic EPS is zero or negative - P/E is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [eps])
    return _res(key, value_raw=market["price"] / eps.value, status=st, confidence=conf, estimated=est, facts=[eps], warnings=w,
                num=_market_input(market), den=_legd("Basic EPS attributable to owners (FY)", eps.value, "eps", unit="₹"))


def _r_pb(fs, market, deps):
    key = "pb_ratio"
    bv = fs.get("bvps")
    if market is None:
        return _no_market(key)
    if bv is None or bv.value is None:
        return _unavailable(key, [bv], fs)
    if bv.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[bv], reason="Book value per share is zero or negative.")
    st, conf, est, w = _merge("verified", 1.0, False, [bv])
    return _res(key, value_raw=market["price"] / bv.value, status=st, confidence=conf, estimated=est, facts=[bv], warnings=w,
                num=_market_input(market), den=_legd("Book Value per Share (Sr 46)", bv.value, "bvps", unit="₹"))


def _r_ps(fs, market, deps):
    key = "ps_ratio"
    rev = fs.get("net_sales")
    if market is None:
        return _no_market(key)
    mc = _mcap(fs, market)
    if mc is None or rev is None or rev.value in (None, 0):
        return _unavailable(key, [fs.get("shares_outstanding"), rev], fs)
    st, conf, est, w = _merge("verified", 1.0, False, [rev, fs.get("shares_outstanding")])
    return _res(key, value_raw=mc / rev.value, status=st, confidence=conf, estimated=est,
                facts=[rev, fs.get("shares_outstanding")], warnings=w,
                num=_mcap_leg(fs, market, mc), den=_legd(_sl(fs), rev.value, "net_sales"))


def _r_dividend_yield(fs, market, deps):
    key = "dividend_yield"
    dps = fs.get("dps")
    if market is None:
        return _no_market(key, "%")
    if dps is None or dps.value is None:
        return _unavailable(key, [dps], fs, unit="%")
    st, conf, est, w = _merge("verified", 1.0, False, [dps])
    return _res(key, value_raw=dps.value / market["price"] * 100, unit="%", status=st, confidence=conf, estimated=est,
                facts=[dps], warnings=w, num=_legd("Dividend per Share (declared for the FY)", dps.value, "dps", unit="₹"),
                den=_market_input(market), extra={"dps_basis": dps.raw_label or dps.source_tag})


def _r_ev_to_ebitda(fs, market, deps):
    key = "ev_to_ebitda"
    if market is None:
        return _no_market(key)
    ev, ef = _enterprise_value(fs, market)
    ebitda = fs.get("ebitda")
    if ev is None:
        return _unavailable(key, ef, fs)
    if ebitda is None or ebitda.value is None:
        return _unavailable(key, [ebitda], fs)
    mc = _mcap(fs, market)
    warns = _ev_nci_warns(fs)
    if ebitda.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=ef + [ebitda], warnings=warns,
                    reason="EBITDA is zero or negative - the multiple is not meaningful.")
    st, conf, est, w = _merge("needs_review" if warns else "verified", 0.85 if warns else 1.0, bool(warns), ef + [ebitda], warns)
    return _res(key, value_raw=ev / ebitda.value, status=st, confidence=conf, estimated=est, facts=ef + [ebitda], warnings=w,
                num=_legd("Enterprise Value (Market Cap + Total Debt − Cash & Cash Equivalents)", ev,
                          parts=_ev_leg(fs, market, ev)["parts"],
                          components={"Market Capitalisation": round(mc, 2), "Total Debt": round(fs.get("total_debt").value, 2),
                                      "less: Cash and Cash Equivalents": round(fs.get("cash").value, 2)}),
                den=_legd("EBITDA (EBIT + Depreciation & Amortisation)", ebitda.value, "ebitda"),
                extra={"ev_cr": ev, "market_price": _market_input(market), "reference_ev_incl_nci": _ev_incl_nci_reference(fs, ev)})


def _r_fixed_asset_turnover(fs, market, deps):
    r = _two_leg(fs, "fixed_asset_turnover", "x", "net_sales", "cur", _sl(fs), "net_fixed_assets", "avg",
                 "Average Net Fixed Assets (opening + closing) ÷ 2", den_positive=True)
    comps = (fs.extras or {}).get("nfa_components")
    if comps and r.get("denominator"):
        r["denominator"]["components"] = {k: round(v, 2) for k, v in comps.items() if v is not None}
    return r


def _r_days_working_capital(fs, market, deps):
    wc = fs.get("working_capital")
    if wc is None or wc.value is None:
        return _unavailable("days_working_capital", [wc], fs, unit="days")
    r = _two_leg(fs, "days_working_capital", "days", "working_capital", "avg", "Average Working Capital (opening + closing) ÷ 2",
                 "net_sales", "cur", _sl(fs), mult=365.0, den_positive=True,
                 reason_nonpositive="Revenue from operations is zero or negative.",
                 num_closing_label="Closing Working Capital (opening/prior-year unavailable)")
    return r


def _r_receivables_to_payables(fs, market, deps):
    key = "receivables_to_payables"
    r = _two_leg(fs, key, "x", "receivables", "cur", "Trade Receivables (closing)", "payables", "cur", "Trade Payables (closing)")
    return r


def _r_net_debt_to_ebitda(fs, market, deps):
    key = "net_debt_to_ebitda"
    nd, ebitda, debt, cash = fs.get("net_debt"), fs.get("ebitda"), fs.get("total_debt"), fs.get("cash")
    if nd is None or nd.value is None:
        return _unavailable(key, [debt, cash], fs, reason=(fs.extras or {}).get("debt_reason"))
    if ebitda is None or ebitda.value is None:
        return _unavailable(key, [ebitda], fs)
    comps = dict(_debt_comps(fs) or {})
    comps["less: Cash and Cash Equivalents"] = round(cash.value, 2)
    num = _legd("Net Debt (Total Debt − Cash and Cash Equivalents)", nd.value, "net_debt", components=comps)
    den = _legd("EBITDA (EBIT + Depreciation & Amortisation)", ebitda.value, "ebitda")
    if ebitda.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[debt, cash, ebitda], num=num, den=den,
                    reason="EBITDA is zero or negative - leverage multiple is not meaningful.")
    if nd.value <= 0:
        return _res(key, status="not_applicable", confidence=1.0, facts=[debt, cash, ebitda], num=num, den=den,
                    reason="Net cash position (cash exceeds total debt) - Net Debt/EBITDA is not a leverage ratio here.",
                    extra={"net_cash": True})
    st, conf, est, w = _merge("verified", 1.0, False, [debt, cash, ebitda])
    return _res(key, value_raw=nd.value / ebitda.value, status=st, confidence=conf, estimated=est, facts=[debt, cash, ebitda],
                warnings=w, num=num, den=den,
                extra={"shared_dependencies": {"ebitda_value_cr": round(ebitda.value, 2), "ebitda_consistent": True,
                                               "total_debt_value_cr": round(debt.value, 2), "total_debt_consistent": True,
                                               "cash_value_cr": round(cash.value, 2), "cash_consistent": True}})


def _r_dscr(fs, market, deps):
    key = "dscr"
    ebitda, rep, fc = fs.get("ebitda"), fs.get("borrowings_repayment"), fs.get("finance_costs")
    if ebitda is None or ebitda.value is None:
        return _unavailable(key, [ebitda], fs)
    if rep is None or rep.value is None:
        return _res(key, status="insufficient_data", confidence=0.0, facts=[ebitda, fc],
                    reason="Gross principal repayments of borrowings are not disclosed as a separate line (only net "
                           "financing flows are) - DSCR is not rebuilt from net flows.")
    if fc is None or fc.value is None:
        return _unavailable(key, [fc], fs)
    principal = abs(rep.value)
    dparts = [_part("Repayment of borrowings (gross principal)", principal, 1, statement="Cash Flow Statement")]
    comps = {"Repayment of borrowings (gross principal)": round(principal, 2)}
    lr = fs.get("lease_repayment")
    if (fs.extras or {}).get("lease_status") == "found" and lr is not None and lr.value is not None:
        principal += abs(lr.value)
        comps["Repayment of lease liabilities (principal)"] = round(abs(lr.value), 2)
        dparts.append(_part("Repayment of lease liabilities (principal)", abs(lr.value), 1, statement="Cash Flow Statement"))
    comps["Interest due (Finance Costs)"] = round(fc.value, 2)
    dparts.append(_part("Interest due (Finance Costs)", fc.value, 1, "finance_costs"))
    denom = principal + fc.value
    if denom <= 0:
        return _res(key, status="insufficient_data", confidence=0.0, facts=[ebitda, rep, fc], reason="Debt service is zero.")
    st, conf, est, w = _merge("needs_review", 0.8, True, [ebitda, rep, fc],
                              ["Net Operating Income is not a disclosed line: EBITDA is used as the proxy (flagged)."])
    return _res(key, value_raw=ebitda.value / denom, status=st, confidence=conf, estimated=True, facts=[ebitda, rep, fc], warnings=w,
                num=_legd("Net Operating Income (proxy: EBITDA)", ebitda.value, "ebitda"),
                den=_legd("Principal Repayment + Interest Due", denom, parts=dparts, components=comps))


def _r_cash_flow_coverage(fs, market, deps):
    key = "cash_flow_coverage_ratio"
    ocf, debt = fs.get("operating_cash_flow"), fs.get("total_debt")
    if ocf is None or ocf.value is None:
        return _unavailable(key, [ocf], fs, reason="Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow Statement.")
    if debt is None or debt.value is None:
        return _unavailable(key, [debt], fs, reason=(fs.extras or {}).get("debt_reason"))
    if debt.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[ocf, debt], reason="Total Debt is zero - coverage is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [ocf, debt])
    return _res(key, value_raw=ocf.value / debt.value, status=st, confidence=conf, estimated=est, facts=[ocf, debt], warnings=w,
                num=_legd("Net Cash Flow from Operating Activities", ocf.value, "operating_cash_flow"),
                den=_legd("Total Debt (closing)", debt.value, "total_debt", components=_debt_comps(fs)))


def _fcf_comps(fs):
    ocf, capex = fs.get("operating_cash_flow"), fs.get("capex")
    return {"Net Cash Flow from Operating Activities": round(ocf.value, 2),
            "less: Capital Expenditure (gross)": round(capex.value, 2)}


def _r_fcf(fs, market, deps):
    key = "free_cash_flow"
    fcf, ocf, capex = fs.get("fcf"), fs.get("operating_cash_flow"), fs.get("capex")
    if fcf is None or fcf.value is None:
        return _unavailable(key, [ocf, capex], fs, unit="₹ Cr")
    st, conf, est, w = _merge("verified", 1.0, False, [ocf, capex])
    return _res(key, value_raw=fcf.value, unit="₹ Cr", status=st, confidence=conf, estimated=est, facts=[ocf, capex], warnings=w,
                num=_legd("Free Cash Flow (Operating Cash Flow − Gross Capex)", fcf.value, "fcf", components=_fcf_comps(fs)))


def _r_fcf_yield(fs, market, deps):
    key = "fcf_yield"
    fcf = fs.get("fcf")
    if market is None:
        return _no_market(key, "%")
    mc = _mcap(fs, market)
    if mc is None or fcf is None or fcf.value is None:
        return _unavailable(key, [fcf, fs.get("shares_outstanding")], fs, unit="%")
    st, conf, est, w = _merge("verified", 1.0, False, [fcf, fs.get("shares_outstanding"), fs.get("operating_cash_flow"), fs.get("capex")])
    return _res(key, value_raw=fcf.value / mc * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[fcf, fs.get("shares_outstanding")],
                warnings=w, num=_legd("Free Cash Flow", fcf.value, "fcf", components=_fcf_comps(fs)),
                den=_mcap_leg(fs, market, mc))


def _r_fcf_margin(fs, market, deps):
    key = "fcf_margin"
    fcf, rev = fs.get("fcf"), fs.get("net_sales")
    if fcf is None or fcf.value is None:
        return _unavailable(key, [fs.get("operating_cash_flow"), fs.get("capex")], fs, unit="%")
    if rev is None or rev.value is None:
        return _unavailable(key, [rev], fs, unit="%")
    if rev.value <= 0:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, reason="Revenue from operations is zero or negative.", facts=[rev])
    st, conf, est, w = _merge("verified", 1.0, False, [fcf, rev, fs.get("operating_cash_flow"), fs.get("capex")])
    return _res(key, value_raw=fcf.value / rev.value * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[fcf, rev], warnings=w,
                num=_legd("Free Cash Flow (Operating Cash Flow − Gross Capex)", fcf.value, "fcf", components=_fcf_comps(fs)),
                den=_legd(_sl(fs), rev.value, "net_sales"))


def _r_ocf_ratio(fs, market, deps):
    return _two_leg(fs, "ocf_ratio", "x", "operating_cash_flow", "cur", "Net Cash Flow from Operating Activities",
                    "total_current_liabilities", "cur", "Total Current Liabilities (closing)", den_positive=True)


def _r_capex_intensity(fs, market, deps):
    key = "capex_intensity"
    capex, rev = fs.get("capex"), fs.get("net_sales")
    if capex is None or capex.value is None:
        return _unavailable(key, [capex], fs, unit="%")
    if rev is None or rev.value is None:
        return _unavailable(key, [rev], fs, unit="%")
    if rev.value <= 0:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, reason="Revenue from operations is zero or negative.", facts=[rev])
    st, conf, est, w = _merge("verified", 1.0, False, [capex, rev])
    ppe, intg = fs.get("capex_ppe_purchase"), fs.get("capex_intangible_purchase")
    comps = {"Purchase of Property, Plant and Equipment": round(abs(ppe.value), 2)} if ppe is not None and ppe.value is not None else {}
    if intg is not None and intg.value is not None:
        comps["Purchase of Intangible Assets"] = round(abs(intg.value), 2)
    return _res(key, value_raw=capex.value / rev.value * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[capex, rev], warnings=w,
                num=_legd("Capital Expenditure (gross)", capex.value, "capex", components=comps),
                den=_legd(_sl(fs), rev.value, "net_sales"))


def _r_ocf_to_net_profit(fs, market, deps):
    key = "ocf_to_net_profit"
    ocf, pt = fs.get("operating_cash_flow"), fs.get("pat_total")
    if ocf is None or ocf.value is None:
        return _unavailable(key, [ocf], fs)
    if pt is None or pt.value is None:
        return _unavailable(key, [pt], fs, reason="Whole-entity Net Profit (incl. NCI) was not found - OCF is a whole-entity flow, "
                                                  "so it is not divided by owners-only profit.")
    if pt.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[ocf, pt], reason="Net Profit is zero or negative - the ratio is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [ocf, pt])
    return _res(key, value_raw=ocf.value / pt.value, status=st, confidence=conf, estimated=est, facts=[ocf, pt], warnings=w,
                num=_legd("Net Cash Flow from Operating Activities", ocf.value, "operating_cash_flow"),
                den=_legd("Profit for the Year (whole entity, incl. NCI)", pt.value, "pat_total"))


def _r_roic(fs, market, deps):
    key = "roic"
    nopat, ic, ebit, tr = fs.get("nopat"), fs.get("invested_capital"), fs.get("ebit"), fs.get("tax_rate")
    if nopat is None or nopat.value is None:
        return _unavailable(key, [ebit, tr], fs, unit="%")
    if ic is None or ic.value is None:
        return _unavailable(key, [ic], fs, unit="%", reason=(fs.extras or {}).get("debt_reason"))
    if ic.value <= 0:
        return _res(key, unit="%", status="not_meaningful", confidence=0.0, facts=[nopat, ic], reason="Invested Capital is zero or negative.")
    warns = []
    if tr is not None and tr.value is not None and (tr.value < 0 or tr.value > 0.6):
        warns.append(f"Effective tax rate {tr.value:.1%} is outside 0-60%; NOPAT is flagged for review.")
    st, conf, est, w = _merge("needs_review" if warns else "verified", 0.8 if warns else 1.0, bool(warns), [nopat, ic], warns)
    comps = (fs.extras or {}).get("debt_components") or {}
    debt, eqf, cash = fs.get("total_debt"), fs.get("equity_full"), fs.get("cash")
    return _res(key, value_raw=nopat.value / ic.value * 100, unit="%", status=st, confidence=conf, estimated=est,
                facts=[nopat, ic, ebit], warnings=w,
                num=_legd("NOPAT (EBIT x (1 - Effective Tax Rate))", nopat.value, "nopat",
                          components={"EBIT (Sr No 15)": round(ebit.value, 2), "Effective Tax Rate": round(tr.value * 100, 2)}),
                den=_legd("Invested Capital (closing) = Total Debt + Total Equity (incl. NCI) - Cash", ic.value, "invested_capital",
                          components={"Total Debt": round(debt.value, 2), "Total Equity (incl. Non-Controlling Interests)": round(eqf.value, 2),
                                      "less: Cash and Cash Equivalents": round(cash.value, 2)}),
                extra={"averaging": "closing-only"})


def _r_effective_tax_rate(fs, market, deps):
    key = "effective_tax_rate"
    tax, pbt = fs.get("tax_expense"), fs.get("pbt")
    if tax is None or tax.value is None:
        return _unavailable(key, [tax], fs, unit="%")
    if pbt is None or pbt.value is None:
        return _unavailable(key, [pbt], fs, unit="%")
    if pbt.value <= 0:
        return _res(key, unit="%", status="not_meaningful", confidence=0.0, facts=[tax, pbt],
                    reason="Profit Before Tax is zero or negative - an effective tax rate is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [tax, pbt])
    return _res(key, value_raw=tax.value / pbt.value * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[tax, pbt], warnings=w,
                num=_legd("Total Tax Expense (Current + Deferred Tax)", tax.value, "tax_expense"),
                den=_legd("Profit Before Tax", pbt.value, "pbt"))


def _r_contribution_margin(fs, market, deps):
    key = "contribution_margin"
    rev = fs.get("net_sales")
    if rev is None or rev.value is None:
        return _unavailable(key, [rev], fs, unit="%")
    if rev.value <= 0:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, reason="Revenue from operations is zero or negative.", facts=[rev])
    comps = (fs.extras or {}).get("components") or {}
    direct = (fs.extras or {}).get("direct_expenses")
    note = (fs.extras or {}).get("variable_opex_note")
    items = (note or {}).get("items") or {}
    has_direct, has_note = direct is not None, bool(items)
    if not has_direct and not has_note:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, facts=[rev],
                    reason="Variable costs could not be identified: no Direct Expenses line and no volume-linked Other-Expenses note "
                           "item (freight, power & fuel, packing, commissions) was found. Goods cost alone is not the variable cost of a "
                           "business, so no contribution margin is manufactured.")
    var, parts = 0.0, {}                      # `var` stays UNROUNDED - only the displayed components are rounded
    cparts = [_part(_sl(fs), rev.value, 1, "net_sales")]
    for lab in ("Cost of materials consumed", "Purchases of stock-in-trade", "Changes in inventories"):
        if lab in comps:
            parts[lab] = round(comps[lab][0], 2)
            var += comps[lab][0]
            cparts.append(_part(lab, comps[lab][0], -1, statement="Statement of Profit and Loss (expense note)"))
    if has_direct:
        parts["Direct Expenses"] = round(direct[0], 2)
        var += direct[0]
        cparts.append(_part("Direct Expenses", direct[0], -1, statement="Statement of Profit and Loss"))
    else:
        for lab, (cur, _p) in items.items():
            parts[lab] = round(cur, 2)
            var += cur
            cparts.append(_part(lab, cur, -1, statement="Notes to the financial statements (other expenses)"))
    contrib = rev.value - var
    st, conf, est, w = _merge("needs_review", 0.6, True, [rev],
                              ["PROXY: Ind AS filings do not disclose variable costs; reconstructed from goods cost + Direct "
                               "Expenses / volume-linked note items. Rent, professional fees, employee cost, depreciation and "
                               "finance costs are never treated as variable."])
    return _res(key, value_raw=contrib / rev.value * 100, unit="%", status=st, confidence=conf, estimated=True, facts=[rev], warnings=w,
                num=_legd("Contribution (Revenue - Total Variable Costs) [PROXY]", contrib, parts=cparts, parts_tol=0.011,
                          components={"Revenue from Operations": round(rev.value, 2), "less: Total Variable Costs": round(var, 2),
                                      **{f"  {k}": v for k, v in parts.items()}}),
                den=_legd(_sl(fs), rev.value, "net_sales"),
                extra={"approximation": True, "formula": "(Revenue from Operations - Total Variable Costs) / Revenue from Operations x 100",
                       "variable_cost_extraction_status": "direct_expenses_only" if has_direct else "note_matched"})


def _r_eps_growth(fs, market, deps):
    key = "eps_growth_rate"
    eps = fs.get("eps")
    if eps is None or eps.value is None:
        return _unavailable(key, [eps], fs, unit="%")
    if eps.prior_value is None:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0, facts=[eps], reason="Prior-year EPS was not found.")
    if eps.prior_value <= 0:
        return _res(key, unit="%", status="not_meaningful", confidence=0.0, facts=[eps],
                    reason="Prior-year EPS is zero or negative - a growth rate is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [eps])
    return _res(key, value_raw=(eps.value / eps.prior_value - 1) * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[eps],
                warnings=w, num=_legd("Basic EPS (current year, owners)", eps.value, "eps", unit="₹"),
                den=_legd("Basic EPS (prior year, owners)", eps.prior_value, "eps", which="prior", unit="₹"))


def _r_bvps(fs, market, deps):
    key = "bvps"
    bv, eq, sh = fs.get("bvps"), fs.get("equity"), fs.get("shares_outstanding")
    if bv is None or bv.value is None:
        return _unavailable(key, [eq, sh], fs, unit="₹")
    st, conf, est, w = _merge("verified", 1.0, False, [eq, sh])
    return _res(key, value_raw=bv.value, unit="₹", status=st, confidence=conf, estimated=est, facts=[eq, sh], warnings=w,
                num=_legd("Total Equity Attributable to Owners of the Company (closing)", eq.value, "equity"),
                den=_legd("Equity Shares Outstanding (closing)", sh.value, "shares_outstanding", unit="shares"))


def _r_dividend_payout(fs, market, deps):
    key = "dividend_payout_ratio"
    paid, pat, dps, sh = fs.get("dividends_paid"), fs.get("pat"), fs.get("dps"), fs.get("shares_outstanding")
    if pat is None or pat.value is None:
        return _unavailable(key, [pat], fs, unit="%", reason="Could not find a 'Profit for the year'/'Profit after tax' row on the P&L page.")
    if pat.value <= 0:
        return _res(key, unit="%", status="not_meaningful", confidence=0.0, facts=[pat],
                    reason="Net Profit is zero or negative - Dividend Payout is not meaningful.")
    if paid is not None and paid.value is not None:
        owners_side = paid.perimeter == "owners" or not (fs.extras or {}).get("nci_material")
        basis = ("Dividends paid to the Company's shareholders during the year" if owners_side else
                 "Dividends paid during the year (cash flow statement, whole entity incl. minorities' share)")
        st, conf, est, w = _merge("verified", 1.0, False, [paid, pat])
        comp = (fs.extras or {}).get("dividend_components")
        extra = {"dividend_found": True, "dividend_basis": "paid", "dividend_components": comp}
        if dps is not None and isinstance(dps.value, (int, float)) and dps.value and sh is not None and sh.value:       # reference only: the dividend declared FOR the year
            extra["reference_declared_for_year_payout_pct"] = dps.value * sh.value / 1e7 / pat.value * 100
        return _res(key, value_raw=paid.value / pat.value * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[paid, pat],
                    warnings=w, num=_legd(basis, paid.value, "dividends_paid"),
                    den=_legd("Profit for the Year Attributable to Owners of the Company", pat.value, "pat"),
                    extra=extra)
    if dps is not None and dps.value is not None and dps.value > 0 and sh is not None and sh.value:
        declared = dps.value * sh.value / 1e7
        st, conf, est, w = _merge("needs_review", 0.6, True, [dps, pat],
                                  ["No 'Dividend paid' cash-flow line was found: payout is ESTIMATED from declared DPS × shares outstanding."])
        return _res(key, value_raw=declared / pat.value * 100, unit="%", status=st, confidence=conf, estimated=True, facts=[dps, sh, pat],
                    warnings=w, num=_legd("Dividends declared (DPS × shares outstanding) - ESTIMATE", declared,
                                          expr=[_legd("Dividend per Share (declared for the FY)", dps.value, "dps", unit="₹"), "×",
                                                _legd("Equity Shares Outstanding", sh.value, "shares_outstanding", unit="shares"), "÷", _CRORE]),
                    den=_legd("Profit for the Year Attributable to Owners of the Company", pat.value, "pat"),
                    extra={"dividend_found": True, "dividend_basis": "declared_estimate"})
    return _unavailable(key, [paid], fs, unit="%",
                        reason="Dividends paid could not be determined: no 'Dividend paid' cash-flow line and no dividend-per-share "
                               "disclosure was found. This is UNKNOWN, not a 0% payout.",
                        extra={"dividend_found": False})


def _r_altman(fs, market, deps):
    key = "altman_z_score"
    if market is None:
        return _no_market(key, "score")
    wc, ta, re_, ebit, tl, rev = (fs.get(k) for k in ("working_capital", "total_assets", "retained_earnings", "ebit", "total_liabilities", "revenue"))
    req = [wc, ta, re_, ebit, tl, rev]
    if any(f is None or f.value is None for f in req):
        return _unavailable(key, req, fs, unit="score")
    mc = _mcap(fs, market)
    if mc is None:
        return _unavailable(key, [fs.get("shares_outstanding")], fs, unit="score")
    if ta.value <= 0 or tl.value <= 0:
        return _res(key, unit="score", status="insufficient_data", confidence=0.0, facts=req, reason="Total assets/liabilities not positive.")
    z = (1.2 * wc.value / ta.value + 1.4 * re_.value / ta.value + 3.3 * ebit.value / ta.value
         + 0.6 * mc / tl.value + 1.0 * rev.value / ta.value)
    st, conf, est, w = _merge("verified", 1.0, False, req)
    comps = {"Working Capital": round(wc.value, 2), "Total Assets": round(ta.value, 3), "Retained Earnings": round(re_.value, 2),
             "EBIT": round(ebit.value, 2), "Total Liabilities": round(tl.value, 2), "Sales": round(rev.value, 2),
             "Market Capitalisation": round(mc, 1)}
    return _res(key, value_raw=z, unit="score", status=st, confidence=conf, estimated=est, facts=req, warnings=w,
                num={"label": "Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA)",
                     "value_cr": round(z, 2), "components": comps},
                extra={"components": {"total_assets_cr": ta.value, "working_capital_cr": wc.value, "retained_earnings_cr": re_.value,
                                      "retained_earnings_basis": "other_equity_proxy", "ebit_cr": ebit.value,
                                      "total_liabilities_cr": tl.value, "sales_cr": rev.value},
                       "market_price": {"name": "market_price", "value": market["price"], "unit": "₹",
                                        "source": f"Live quote ({market.get('source')})"}})


def _r_piotroski(fs, market, deps):
    key = "piotroski_f_score"
    pat_o, pat_t = fs.get("pat"), fs.get("pat_total")
    ta, ocf, tca, tcl = fs.get("total_assets"), fs.get("operating_cash_flow"), fs.get("total_current_assets"), fs.get("total_current_liabilities")
    gp, rev, sh = fs.get("gross_profit"), fs.get("revenue"), fs.get("shares_outstanding")
    lt, debt = fs.get("lt_borrowings"), fs.get("total_debt")
    roa_pat, _ = _pat_fact(fs, "roa")
    tests = []
    used = [roa_pat, pat_t, ta, ocf, tca, tcl, gp, rev, sh]      # leverage fact (lt OR total debt) is added below

    def add(name, cat, ok, passed=None, detail="", spec=None):
        tests.append({"name": name, "category": cat, "applicable": ok, "passed": passed if ok else None, "detail": detail,
                      **({"spec": spec} if (spec and ok) else {})})

    def two(f):
        return f is not None and f.value is not None and f.prior_value is not None

    if two(roa_pat) and two(ta) and ta.value and ta.prior_value:
        r0, r1 = roa_pat.value / ta.value, roa_pat.prior_value / ta.prior_value
        _rs = {"type": "ratio", "num": roa_pat.fact_key, "den": "total_assets", "cur": r0, "prior": r1, "unit": "frac%",
               "label": "ROA = PAT ÷ closing Total Assets"}
        add("ROA > 0", "Profitability", True, r0 > 0, f"ROA {r0:.2%} (PAT / closing Total Assets)", {**_rs, "op": ">", "vs": "zero"})
        add("ROA improved YoY", "Profitability", True, r0 > r1, f"{r0:.2%} vs {r1:.2%} prior year", {**_rs, "op": ">", "vs": "prior"})
    else:
        add("ROA > 0", "Profitability", False, detail="Current/prior PAT or Total Assets not found.")
        add("ROA improved YoY", "Profitability", False, detail="Current/prior PAT or Total Assets not found.")
    if ocf is not None and ocf.value is not None:
        add("Operating Cash Flow > 0", "Profitability", True, ocf.value > 0, f"OCF Rs.{ocf.value:,.2f} Cr",
            {"type": "facts", "lhs": "operating_cash_flow", "rhs": None, "op": ">"})
    else:
        add("Operating Cash Flow > 0", "Profitability", False, detail="Operating cash flow not found.")
    if ocf is not None and ocf.value is not None and pat_t is not None and pat_t.value is not None:
        add("OCF > Net Profit (accrual quality)", "Profitability", True, ocf.value > pat_t.value,
            f"OCF Rs.{ocf.value:,.2f} Cr vs whole-entity PAT Rs.{pat_t.value:,.2f} Cr",
            {"type": "facts", "lhs": "operating_cash_flow", "rhs": "pat_total", "op": ">"})
    else:
        add("OCF > Net Profit (accrual quality)", "Profitability", False, detail="OCF or whole-entity PAT not found.")
    if two(lt) and two(ta) and ta.value and ta.prior_value:
        l0, l1 = lt.value / ta.value, lt.prior_value / ta.prior_value
        add("Leverage decreased (LT Debt/TA)", "Leverage/Liquidity", True, l0 < l1, f"LT borrowings/TA {l0:.3f} vs {l1:.3f}",
            {"type": "ratio", "num": "lt_borrowings", "den": "total_assets", "cur": l0, "prior": l1, "unit": "frac", "op": "<",
             "vs": "prior", "label": "Leverage = Long-term borrowings ÷ closing Total Assets"})
        used.append(lt)
    elif two(debt) and two(ta) and ta.value and ta.prior_value:
        l0, l1 = debt.value / ta.value, debt.prior_value / ta.prior_value
        add("Leverage decreased (Total Debt/TA)", "Leverage/Liquidity", True, l0 < l1,
            f"Total debt/TA {l0:.3f} vs {l1:.3f} (long-term borrowings alone were not separable)",
            {"type": "ratio", "num": "total_debt", "den": "total_assets", "cur": l0, "prior": l1, "unit": "frac", "op": "<",
             "vs": "prior", "label": "Leverage = Total Debt ÷ closing Total Assets"})
        used.append(debt)
    else:
        add("Leverage decreased (LT Debt/TA)", "Leverage/Liquidity", False, detail="Debt for both years not found.")
    if two(tca) and two(tcl) and tcl.value and tcl.prior_value:
        c0, c1 = tca.value / tcl.value, tca.prior_value / tcl.prior_value
        add("Current Ratio improved YoY", "Leverage/Liquidity", True, c0 > c1, f"{c0:.2f}x vs {c1:.2f}x prior year",
            {"type": "ratio", "num": "total_current_assets", "den": "total_current_liabilities", "cur": c0, "prior": c1, "unit": "x",
             "op": ">", "vs": "prior", "label": "Current Ratio = Total Current Assets ÷ Total Current Liabilities"})
    else:
        add("Current Ratio improved YoY", "Leverage/Liquidity", False, detail="Current assets/liabilities for both years not found.")
    if two(sh):
        add("No dilution (shares not increased)", "Leverage/Liquidity", True, sh.value <= sh.prior_value * 1.001,
            f"{sh.value:,.0f} vs {sh.prior_value:,.0f} shares",
            {"type": "dilution", "cur": sh.value, "prior": sh.prior_value, "limit": sh.prior_value * 1.001})
    else:
        add("No dilution (shares not increased)", "Leverage/Liquidity", False, detail="Equity shares outstanding for both years not found.")
    if two(gp) and two(rev) and rev.value and rev.prior_value:
        g0, g1 = gp.value / rev.value, gp.prior_value / rev.prior_value
        add("Gross Margin improved YoY", "Operating Efficiency", True, g0 > g1, f"{g0:.2%} vs {g1:.2%}",
            {"type": "ratio", "num": "gross_profit", "den": "revenue", "cur": g0, "prior": g1, "unit": "frac%", "op": ">",
             "vs": "prior", "label": "Gross Margin = Gross Profit ÷ Revenue"})
    else:
        add("Gross Margin improved YoY", "Operating Efficiency", False, detail="Gross profit for both years not found.")
    if two(rev) and two(ta) and ta.value and ta.prior_value:
        a0, a1 = rev.value / ta.value, rev.prior_value / ta.prior_value
        add("Asset Turnover improved YoY", "Operating Efficiency", True, a0 > a1, f"{a0:.3f} vs {a1:.3f}",
            {"type": "ratio", "num": "revenue", "den": "total_assets", "cur": a0, "prior": a1, "unit": "x", "op": ">", "vs": "prior",
             "label": "Asset Turnover = Revenue ÷ closing Total Assets"})
    else:
        add("Asset Turnover improved YoY", "Operating Efficiency", False, detail="Revenue/Total Assets for both years not found.")
    evaluated = [t for t in tests if t["applicable"]]
    score = sum(1 for t in evaluated if t["passed"])
    extra = {"tests": tests, "max_score": 9, "tests_evaluated": len(evaluated), "partial_score": score}
    if len(evaluated) < 9:
        skipped = [t["name"] for t in tests if not t["applicable"]]
        return _res(key, unit="", status="insufficient_data", confidence=0.0, facts=[f for f in used if f is not None],
                    reason=f"Only {len(evaluated)} of 9 Piotroski tests could be evaluated (missing: {', '.join(skipped)}); a partial "
                           f"score ({score}/{len(evaluated)}) is not reported as a 9-point score.", extra=extra)
    st, conf, est, w = _merge("verified", 1.0, False, [f for f in used if f is not None])
    return _res(key, value_raw=float(score), unit="", status=st, confidence=conf, estimated=est, facts=[f for f in used if f is not None],
                warnings=w, extra=extra)


def _r_beneish(fs, market, deps):
    key = "beneish_m_score"
    recv, rev, gp, tca, ppe, ta = (fs.get(k) for k in ("receivables", "revenue", "gross_profit", "total_current_assets", "ppe", "total_assets"))
    dep, oe, pt, ocf = fs.get("depreciation"), fs.get("other_expenses"), fs.get("pat_total"), fs.get("operating_cash_flow")
    tcl, debt, lt = fs.get("total_current_liabilities"), fs.get("total_debt"), fs.get("lt_borrowings")
    need2 = [recv, rev, gp, tca, ppe, ta, dep, oe, tcl]
    if any(f is None or f.value is None or f.prior_value is None for f in need2) or pt is None or pt.value is None \
            or ocf is None or ocf.value is None:
        miss = [f.fact_key for f in need2 + [pt, ocf] if f is not None and (f.value is None or (f not in (pt, ocf) and f.prior_value is None))]
        return _res(key, unit="", status="insufficient_data", confidence=0.0, facts=[f for f in need2 + [pt, ocf] if f is not None],
                    reason="Beneish needs two years of receivables, revenue, gross profit, current assets, PPE, total assets, "
                           "depreciation, other expenses and current liabilities plus current-year profit and OCF "
                           f"(missing/incomplete: {', '.join(sorted(set(miss))) or 'n/a'}).")
    ldebt = debt if (debt is not None and debt.value is not None and debt.prior_value is not None) else lt
    if ldebt is None or ldebt.value is None or ldebt.prior_value is None:
        return _res(key, unit="", status="insufficient_data", confidence=0.0, facts=need2,
                    reason="Beneish LVGI needs debt for both years; it was not available.")
    try:
        dsri = (recv.value / rev.value) / (recv.prior_value / rev.prior_value)
        gmi = (gp.prior_value / rev.prior_value) / (gp.value / rev.value)
        aqi = (1 - (tca.value + ppe.value) / ta.value) / (1 - (tca.prior_value + ppe.prior_value) / ta.prior_value)
        sgi = rev.value / rev.prior_value
        depi = (dep.prior_value / (ppe.prior_value + dep.prior_value)) / (dep.value / (ppe.value + dep.value))
        sgai = (oe.value / rev.value) / (oe.prior_value / rev.prior_value)
        tata = (pt.value - ocf.value) / ta.value
        lvgi = ((ldebt.value + tcl.value) / ta.value) / ((ldebt.prior_value + tcl.prior_value) / ta.prior_value)
    except ZeroDivisionError:
        return _res(key, unit="", status="insufficient_data", confidence=0.0, facts=need2, reason="A Beneish index divided by zero.")
    m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai
         + 4.679 * tata - 0.327 * lvgi)
    st, conf, est, w = _merge("needs_review", 0.85, True, need2 + [pt, ocf, ldebt],
                              ["SG&A is proxied by Other Expenses (Ind AS has no distinct SG&A line) - SGAI is an approximation."])
    return _res(key, value_raw=m, unit="", status=st, confidence=conf, estimated=True, facts=need2 + [pt, ocf, ldebt], warnings=w,
                extra={"variables": {"DSRI": round(dsri, 3), "GMI": round(gmi, 3), "AQI": round(aqi, 3), "SGI": round(sgi, 3),
                                     "DEPI": round(depi, 3), "SGAI": round(sgai, 3), "TATA": round(tata, 3), "LVGI": round(lvgi, 3)},
                       "variables_raw": {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi, "DEPI": depi, "SGAI": sgai, "TATA": tata,
                                         "LVGI": lvgi},
                       "leverage_fact": ldebt.fact_key})


# --------------------------------------------------------------------------------------------
# derived ratios (Strategy B) - consume parents' UNROUNDED values and inherit their status
# --------------------------------------------------------------------------------------------
def _inherit(key, parents, own_status="verified", own_conf=1.0, warnings=()):
    """(status, confidence, estimated, warnings, blocking_parent) from the parents' results."""
    st, conf, est, warns = own_status, own_conf, False, list(warnings)
    blocking = None
    for p in parents:
        if p is None:
            return "insufficient_data", 0.0, False, warns, "missing"
        ps = p.get("status", "verified")
        if ps in UNAVAILABLE or p.get("value_raw") is None:
            return ps if ps in UNAVAILABLE else "insufficient_data", 0.0, False, warns, p
        if STATUS_RANK[ps] > STATUS_RANK[st] and ps in ("needs_review", "not_meaningful"):
            st = ps
        conf = min(conf, p.get("confidence") if p.get("confidence") is not None else 1.0)
        est = est or bool(p.get("estimated"))
        warns.extend(p.get("warnings") or [])
    return st, conf, est, warns, blocking


def _derived_unavailable(key, blocking, unit="x"):
    why = "A required parent ratio is unavailable"
    if isinstance(blocking, dict):
        why = f"{blocking.get('label') or blocking.get('ratio_key')} is {blocking.get('status')}: {blocking.get('reason') or 'no value'}"
    st = blocking.get("status") if isinstance(blocking, dict) and blocking.get("status") in UNAVAILABLE else "insufficient_data"
    return _res(key, unit=unit, status=st, confidence=0.0, reason=why)


def _days_from(key, parent_key, deps, mult=365.0):
    p = deps.get(parent_key)
    st, conf, est, w, blocking = _inherit(key, [p])
    if blocking is not None:
        return _derived_unavailable(key, blocking, "days")
    if not p["value_raw"]:
        return _res(key, unit="days", status="insufficient_data", confidence=0.0, reason=f"{p['label']} is zero.")
    return _res(key, value_raw=mult / p["value_raw"], unit="days", status=st, confidence=conf, estimated=est, warnings=w,
                extra={"derived_from": [{"ratio_key": parent_key, "label": p["label"], "value_raw": p["value_raw"], "status": p["status"]}]})


def _r_ccc(fs, market, deps):
    key = "cash_conversion_cycle"
    dso, doh, dpo = deps.get("days_sales_outstanding"), deps.get("days_inventory_outstanding"), deps.get("days_payables_outstanding")
    st, conf, est, w, blocking = _inherit(key, [dso, doh, dpo])
    if blocking is not None:
        return _derived_unavailable(key, blocking, "days")
    return _res(key, value_raw=dso["value_raw"] + doh["value_raw"] - dpo["value_raw"], unit="days", status=st, confidence=conf,
                estimated=est, warnings=w, extra={"derived_from": [
                    {"ratio_key": k, "label": p["label"], "value_raw": p["value_raw"], "status": p["status"]}
                    for k, p in (("days_sales_outstanding", dso), ("days_inventory_outstanding", doh), ("days_payables_outstanding", dpo))]})


def _r_retention(fs, market, deps):
    key = "retention_ratio"
    p = deps.get("dividend_payout_ratio")
    st, conf, est, w, blocking = _inherit(key, [p])
    if blocking is not None:
        return _derived_unavailable(key, blocking, "%")
    return _res(key, value_raw=100.0 - p["value_raw"], unit="%", status=st, confidence=conf, estimated=est, warnings=w,
                extra={"derived_from": [{"ratio_key": "dividend_payout_ratio", "label": p["label"], "value_raw": p["value_raw"], "status": p["status"]}]})


def _r_sgr(fs, market, deps):
    key = "sustainable_growth_rate"
    roe, ret = deps.get("roe"), deps.get("retention_ratio")
    st, conf, est, w, blocking = _inherit(key, [roe, ret])
    if blocking is not None:
        return _derived_unavailable(key, blocking, "%")
    return _res(key, value_raw=roe["value_raw"] * ret["value_raw"] / 100.0, unit="%", status=st, confidence=conf, estimated=est, warnings=w,
                extra={"derived_from": [{"ratio_key": k, "label": p["label"], "value_raw": p["value_raw"], "status": p["status"]}
                                        for k, p in (("roe", roe), ("retention_ratio", ret))]})


def _r_earnings_yield(fs, market, deps):
    key = "earnings_yield"
    eps = fs.get("eps")
    if market is None:
        return _no_market(key, "%")
    if eps is None or eps.value is None:
        return _unavailable(key, [eps], fs, unit="%")
    st, conf, est, w = _merge("verified", 1.0, False, [eps])
    return _res(key, value_raw=eps.value / market["price"] * 100, unit="%", status=st, confidence=conf, estimated=est, facts=[eps], warnings=w,
                num=_legd("Basic EPS attributable to owners (FY)", eps.value, "eps", unit="₹"), den=_market_input(market))


def _r_peg(fs, market, deps):
    key = "peg_ratio"
    eps, g = fs.get("eps"), deps.get("eps_growth_rate")
    if market is None:
        return _no_market(key)
    if eps is None or eps.value is None:
        return _unavailable(key, [eps], fs)
    st, conf, est, w, blocking = _inherit(key, [g])
    if blocking is not None:
        return _derived_unavailable(key, blocking)
    if eps.value <= 0:
        return _res(key, status="not_meaningful", confidence=0.0, facts=[eps], reason="EPS is zero or negative - PEG is not meaningful.")
    pe = market["price"] / eps.value
    if g["value_raw"] <= 0:
        return _res(key, value_raw=pe / g["value_raw"] if g["value_raw"] else None, status="not_meaningful", confidence=0.0, facts=[eps],
                    reason="EPS growth is zero or negative - PEG is not meaningful.",
                    num=_legd("P/E (Market Price ÷ owners' EPS)", pe, expr=[_market_input(market), "÷", _legd("Basic EPS (owners)", eps.value, "eps", unit="₹")],
                              unit="x"),
                    den=_legd("EPS Growth Rate (%)", g["value_raw"], kind="parent", parent_key="eps_growth_rate", unit="%"))
    st2, conf2, est2, w2 = _merge(st, conf, est, [eps], w)
    return _res(key, value_raw=pe / g["value_raw"], status=st2, confidence=conf2, estimated=est2, facts=[eps], warnings=w2,
                num=_legd("P/E (Market Price ÷ owners' EPS)", pe, expr=[_market_input(market), "÷", _legd("Basic EPS (owners)", eps.value, "eps", unit="₹")],
                          unit="x"),
                den=_legd("EPS Growth Rate (%)", g["value_raw"], kind="parent", parent_key="eps_growth_rate", unit="%"),
                extra={"derived_from": [{"ratio_key": "eps_growth_rate", "label": g["label"], "value_raw": g["value_raw"], "status": g["status"]}]})


def _r_ev_to_sales(fs, market, deps):
    key = "ev_to_sales"
    if market is None:
        return _no_market(key)
    ev, ef = _enterprise_value(fs, market)
    rev = fs.get("net_sales")
    if ev is None:
        return _unavailable(key, ef, fs)
    if rev is None or rev.value in (None, 0):
        return _unavailable(key, [rev], fs)
    warns = _ev_nci_warns(fs)
    st, conf, est, w = _merge("needs_review" if warns else "verified", 0.85 if warns else 1.0, bool(warns), ef + [rev], warns)
    return _res(key, value_raw=ev / rev.value, status=st, confidence=conf, estimated=est, facts=ef + [rev], warnings=w,
                num=_ev_leg(fs, market, ev), den=_legd(_sl(fs), rev.value, "net_sales"))


def _r_ev_to_fcf(fs, market, deps):
    key = "ev_to_fcf"
    if market is None:
        return _no_market(key)
    ev, ef = _enterprise_value(fs, market)
    p = deps.get("free_cash_flow")
    if ev is None:
        return _unavailable(key, ef, fs)
    st, conf, est, w, blocking = _inherit(key, [p])
    if blocking is not None:
        return _derived_unavailable(key, blocking)
    fcf = p["value_raw"]
    num = _ev_leg(fs, market, ev)
    den = _legd("Free Cash Flow", fcf, kind="parent", parent_key="free_cash_flow", unit="₹ Cr")
    if fcf == 0:
        return _res(key, status="insufficient_data", confidence=0.0, num=num, den=den, reason="Free Cash Flow is zero.")
    if fcf < 0:
        return _res(key, value_raw=ev / fcf, status="not_meaningful", confidence=0.0, num=num, den=den, facts=ef,
                    warnings=["Free Cash Flow is negative: the multiple exists mathematically but is not economically meaningful."],
                    reason="Negative Free Cash Flow - EV/FCF is not meaningful.")
    nw = _ev_nci_warns(fs)
    st2, conf2, est2, w2 = _merge("needs_review" if (nw and st == "verified") else st, min(conf, 0.85) if nw else conf,
                                  est or bool(nw), ef, list(w) + nw)
    return _res(key, value_raw=ev / fcf, status=st2, confidence=conf2, estimated=est2, facts=ef, warnings=w2, num=num, den=den)


def _r_ptocf(fs, market, deps):
    key = "price_to_cash_flow"
    ocf = fs.get("operating_cash_flow")
    if market is None:
        return _no_market(key)
    mc = _mcap(fs, market)
    if mc is None or ocf is None or ocf.value is None:
        return _unavailable(key, [ocf, fs.get("shares_outstanding")], fs)
    if ocf.value <= 0:
        return _res(key, value_raw=mc / ocf.value if ocf.value else None, status="not_meaningful", confidence=0.0, facts=[ocf],
                    reason="Operating cash flow is zero or negative - the multiple is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [ocf, fs.get("shares_outstanding")])
    return _res(key, value_raw=mc / ocf.value, status=st, confidence=conf, estimated=est, facts=[ocf, fs.get("shares_outstanding")], warnings=w,
                num=_mcap_leg(fs, market, mc),
                den=_legd("Net Cash Flow from Operating Activities", ocf.value, "operating_cash_flow"))


def _r_graham(fs, market, deps):
    key = "graham_number"
    eps, bv = fs.get("eps"), fs.get("bvps")
    if eps is None or eps.value is None or bv is None or bv.value is None:
        return _unavailable(key, [eps, bv], fs, unit="₹")
    if eps.value <= 0 or bv.value <= 0:
        return _res(key, unit="₹", status="not_meaningful", confidence=0.0, facts=[eps, bv],
                    reason="EPS or book value per share is zero/negative - the Graham Number is not meaningful.")
    st, conf, est, w = _merge("verified", 1.0, False, [eps, bv])
    return _res(key, value_raw=math.sqrt(22.5 * eps.value * bv.value), unit="₹", status=st, confidence=conf, estimated=est, facts=[eps, bv],
                warnings=w, num=_legd("22.5 × EPS (owners) × BVPS", 22.5 * eps.value * bv.value, unit="",
                                      expr=[_const(22.5, "22.5"), "×", _legd("Basic EPS (owners)", eps.value, "eps", unit="₹"), "×",
                                            _legd("Book Value per Share", bv.value, "bvps", unit="₹")]))


_DERIVED = {
    "days_inventory_outstanding": lambda fs, m, d: _days_from("days_inventory_outstanding", "inventory_turnover", d),
    "days_sales_outstanding": lambda fs, m, d: _days_from("days_sales_outstanding", "receivables_turnover", d),
    "days_payables_outstanding": lambda fs, m, d: _days_from("days_payables_outstanding", "payables_turnover", d),
    "cash_conversion_cycle": _r_ccc, "retention_ratio": _r_retention, "sustainable_growth_rate": _r_sgr,
    "earnings_yield": _r_earnings_yield, "peg_ratio": _r_peg, "ev_to_sales": _r_ev_to_sales, "ev_to_fcf": _r_ev_to_fcf,
    "graham_number": _r_graham,
}

_DIRECT = {
    "inventory_turnover": _r_inventory_turnover, "receivables_turnover": _r_receivables_turnover,
    "payables_turnover": _r_payables_turnover, "asset_turnover": _r_asset_turnover,
    "working_capital_turnover": _r_working_capital_turnover, "current_ratio": _r_current_ratio, "quick_ratio": _r_quick_ratio,
    "cash_ratio": _r_cash_ratio, "working_capital": _r_working_capital, "gross_profit_margin": _r_gross_profit_margin,
    "operating_profit_margin": _r_operating_profit_margin, "net_profit_margin": _r_net_profit_margin, "roa": _r_roa,
    "roe": _r_roe, "roce": _r_roce, "debt_to_equity": _r_debt_to_equity, "debt_ratio": _r_debt_ratio,
    "interest_coverage_ratio": _r_interest_coverage, "financial_leverage_ratio": _r_financial_leverage,
    "pe_ratio": _r_pe, "pb_ratio": _r_pb, "ps_ratio": _r_ps, "dividend_yield": _r_dividend_yield,
    "ev_to_ebitda": _r_ev_to_ebitda, "fixed_asset_turnover": _r_fixed_asset_turnover,
    "days_working_capital": _r_days_working_capital, "receivables_to_payables": _r_receivables_to_payables,
    "net_debt_to_ebitda": _r_net_debt_to_ebitda, "dscr": _r_dscr, "cash_flow_coverage_ratio": _r_cash_flow_coverage,
    "free_cash_flow": _r_fcf, "fcf_yield": _r_fcf_yield, "fcf_margin": _r_fcf_margin, "ocf_ratio": _r_ocf_ratio,
    "capex_intensity": _r_capex_intensity, "ocf_to_net_profit": _r_ocf_to_net_profit, "roic": _r_roic,
    "effective_tax_rate": _r_effective_tax_rate, "contribution_margin": _r_contribution_margin,
    "eps_growth_rate": _r_eps_growth, "bvps": _r_bvps, "dividend_payout_ratio": _r_dividend_payout,
    "price_to_cash_flow": _r_ptocf, "altman_z_score": _r_altman, "piotroski_f_score": _r_piotroski,
    "beneish_m_score": _r_beneish, "roe_": None,
}
_DIRECT.pop("roe_", None)

# which ratios each derived ratio needs computed first (status/value inheritance)
PARENTS = {
    "days_inventory_outstanding": ["inventory_turnover"], "days_sales_outstanding": ["receivables_turnover"],
    "days_payables_outstanding": ["payables_turnover"],
    "cash_conversion_cycle": ["days_sales_outstanding", "days_inventory_outstanding", "days_payables_outstanding"],
    "retention_ratio": ["dividend_payout_ratio"], "sustainable_growth_rate": ["roe", "retention_ratio"],
    "peg_ratio": ["eps_growth_rate"], "ev_to_fcf": ["free_cash_flow"],
    "earnings_yield": [], "ev_to_sales": [], "graham_number": [],
}

COMPUTABLE = set(_DIRECT) | set(_DERIVED)
MARKET_KEYS = {"pe_ratio", "pb_ratio", "ps_ratio", "dividend_yield", "earnings_yield", "ev_to_ebitda", "ev_to_sales",
               "ev_to_fcf", "fcf_yield", "price_to_cash_flow", "peg_ratio", "altman_z_score"}


def fiscal_year_label(fy):
    """Fiscal year 2026 (ends 31-Mar-2026) -> 'FY2025-26'. None when the year is unknown."""
    try:
        fy = int(fy)
    except (TypeError, ValueError):
        return None
    return f"FY{fy - 1}-{str(fy)[-2:]}"


def reporting_context(key, fs, market=None):
    """Period policy of a displayed ratio (display metadata only - no arithmetic): every contract ratio is built from the selected fiscal
    year's ANNUAL statements, never from quarterly or trailing-twelve-month (TTM) figures. Market-priced ratios say which price they use."""
    sel = getattr(fs, "selection", None)
    basis = getattr(sel, "selected_basis", None)
    ctx = {
        "period_type": "annual", "ttm": False,
        "fiscal_year": getattr(fs, "fiscal_year", None), "fiscal_year_label": fiscal_year_label(getattr(fs, "fiscal_year", None)),
        "statement_basis": basis.lower() if isinstance(basis, str) else None,
        "balance_convention": "closing balance of the fiscal year; averages use the prior-year closing balance as opening (unavailable when it is missing)",
        "screener_comparable": "annual (non-TTM) statements - compare with Screener's annual column, not its TTM column",
    }
    fb = (getattr(fs, "extras", None) or {}).get("basis_fallback")
    if fb:
        ctx["basis_requested"] = fs.extras.get("basis_requested")
        ctx["basis_note"] = fb
    if key in MARKET_KEYS:
        q = (market or {}) if isinstance(market, dict) else {}
        ctx["price"] = {"kind": "latest_quote", "quoted_at": q.get("quoted_at"),
                        "note": "latest market price over fiscal-year per-share figures; not the fiscal-year-end price"}
    return ctx


def compute_ratio(key, fs, market=None, deps=None):
    """The ONLY place a ratio's arithmetic lives. `deps` = already-computed
    parent results (see PARENTS) for derived ratios."""
    deps = deps or {}
    fn = _DERIVED.get(key) or _DIRECT.get(key)
    if fn is None:
        raise KeyError(f"'{key}' has no contract formula (banking/shareholding/beta delegate to their providers).")
    try:
        res = fn(fs, market, deps)
    except (TypeError, AttributeError, ZeroDivisionError, ValueError, OverflowError) as e:
        # an input the formula needs is absent / inconsistent in a way no earlier guard anticipated: the ratio is WITHHELD with a reason
        # (never a crash, never a guessed number); the cause is logged so the gap can be closed properly.
        print(f"[ratio_contract] {key}: formula could not be evaluated ({type(e).__name__}: {e}) - withheld")
        res = _res(key, status="insufficient_data", confidence=0.0,
                   reason="A required input is missing or inconsistent, so the ratio cannot be evaluated.")
    res = _acq_guard(key, fs, res)
    res["reporting"] = reporting_context(key, fs, market)
    if key in EQUITY_BASIS:
        res["equity_basis"] = EQUITY_BASIS[key]
    elif key in EQUITY_NOTES:
        res["equity_basis"] = "none"
    # calculation breakdown: built from THIS result's own legs/parents (display metadata only - no arithmetic)
    try:
        from tools.ratio_breakdown import build_breakdown
        res["breakdown"] = build_breakdown(key, res, fs, deps)
    except Exception as e:
        print(f"[ratio_contract] breakdown for {key} failed: {type(e).__name__}: {e}")
        res["breakdown"] = None
    return res


def compute_with_parents(key, fs, market=None, cache=None):
    """compute_ratio + automatic (recursive) parent resolution, sharing `cache`."""
    cache = cache if cache is not None else {}

    def get(k):
        if k not in cache:
            deps = {p: get(p) for p in PARENTS.get(k, [])}
            cache[k] = compute_ratio(k, fs, market, deps)
        return cache[k]

    return get(key)


def compute_all(fs, market=None, keys=None):
    cache = {}
    for k in (keys or sorted(COMPUTABLE)):
        compute_with_parents(k, fs, market, cache)
    return cache


# --------------------------------------------------------------------------------------------
# shareholding / beta policies (one definition shared by every engine)
# --------------------------------------------------------------------------------------------
BETA_POLICY = {"benchmark": "^NSEI", "interval": "1wk", "period": "2y", "min_observations": 52,
               "estimator": "sample covariance / sample variance (ddof=1) of weekly returns, inner-joined on dates"}


def beta_result(info, symbol=None):
    """Beta (Sr 66) from `tools.market_history.weekly_beta`'s dict. One policy for every engine."""
    key = "beta"
    if not info or info.get("beta") is None:
        return _res(key, unit="", status="insufficient_data", confidence=0.0,
                    reason=(info or {}).get("reason") or "Historical price data is unavailable.")
    n = info["n"]
    conf = 1.0 if n >= 100 else 0.8
    st = "verified" if conf >= 1.0 else "needs_review"
    warns = [] if conf >= 1.0 else [f"Only {n} weekly observations (full confidence needs 100+)."]
    return _res(key, value_raw=info["beta"], unit="", status=st, confidence=conf, estimated=conf < 1.0, warnings=warns,
                num=_legd("Covariance(Stock Returns, Nifty 50 Returns)", info["cov"], unit="", dp=6, source="Yahoo Finance weekly prices"),
                den=_legd("Variance(Nifty 50 Returns)", info["var"], unit="", dp=6, source="Yahoo Finance weekly prices (^NSEI)"),
                extra={"period": f"Weekly returns, {info.get('start')} to {info.get('end')} ({n} points)",
                       "benchmark": BETA_POLICY["benchmark"], "observations": n})


# Plausibility bounds for the bank/NBFC-specific ratios (Sr 58-65, in %). The bank statements are extracted by a
# dedicated module; a value outside these bounds is an extraction error (e.g. a rupee-crore amount read as a
# percentage), never a real ratio - it is withheld rather than shown as applicable.
BANK_BOUNDS = {
    "net_interest_margin": (-5.0, 20.0), "casa_ratio": (0.0, 100.0), "gross_npa_pct": (0.0, 60.0),
    "net_npa_pct": (0.0, 60.0), "provision_coverage_ratio": (0.0, 200.0), "capital_adequacy_ratio": (0.0, 60.0),
    "credit_to_deposit_ratio": (0.0, 200.0), "cost_to_income_ratio": (0.0, 300.0),
}


def guard_bank(key, out):
    """Withholds an implausible bank ratio (see BANK_BOUNDS). Returns `out` unchanged when it is fine/unavailable."""
    b = BANK_BOUNDS.get(key)
    if not b or not isinstance(out, dict) or not out.get("applicable"):
        return out
    v = out.get("value")
    if v is None or b[0] <= v <= b[1]:
        return out
    return {**out, "applicable": False, "status": "insufficient_data", "mathematical_value": v, "value": None,
            "value_raw": None, "reason": f"The extracted value {v:,.2f}% is outside the plausible range "
            f"[{b[0]:g}%, {b[1]:g}%] for this bank ratio - the banking-statement extraction is suspect, so it is withheld "
            "rather than shown."}


def bank_guard(key):
    """Decorator applying `guard_bank` to a bank-ratio fetcher."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            return guard_bank(key, fn(*a, **k))
        return inner
    return deco


def pledge_result(sh):
    """Promoter Pledge % from a shareholding dict (tools.shareholding_scraper / manual upload)."""
    key = "promoter_pledge_pct"
    if sh is None:
        return _res(key, unit="%", status="not_disclosed", confidence=0.0,
                    reason="Shareholding Pattern data is unavailable.")
    promoter = sh.get("promoter_holding_pct")
    if promoter is None:
        return _res(key, unit="%", status="not_disclosed", confidence=0.0,
                    reason="Promoter holding could not be read from the Shareholding Pattern - pledge cannot be determined.")
    if promoter == 0:
        return _res(key, unit="%", status="not_applicable", confidence=1.0,
                    reason="No promoter/founder shareholding on record - Promoter Pledge % does not apply.")
    status = sh.get("pledge_status")
    pledged, total = sh.get("num_shares_pledged"), sh.get("total_promoter_holding")
    pct = sh.get("promoter_pledge_pct")
    if pledged is not None and total:
        pct = pledged / total * 100.0
    if status == "assumed_zero" or pct is None:
        return _res(key, unit="%", status="insufficient_data", confidence=0.0,
                    reason="The pledge disclosure could not be retrieved - a 0% pledge is NOT assumed.")
    if status != "ok" and pledged is None:
        # NO pledged-share count was disclosed: the 0% is INFERRED from the absence of a record in NSE's pledge dataset.
        # That is evidence, not a disclosure - it is reported as such (needs_review), never as a verified figure.
        return _res(key, value_raw=pct, unit="%", status="needs_review", confidence=0.7, estimated=True,
                    warnings=["INFERRED: NSE's pledge dataset lists only scrips with a pledge on record and this company has "
                              "none, so 0% is inferred from the absence of a record - no pledged-share count was disclosed."],
                    extra={"inferred_zero": True})
    if pct < 0 or pct > 100.0 + 1e-9 or (pledged is not None and total and pledged > total * (1 + 1e-9)):
        # internally impossible (found on real data: pledged 25.4 crore shares against 31 lakh promoter shares = 8,174%) -
        # the figure is withheld, never shown as a percentage of anything
        return _res(key, unit="%", status="insufficient_data", confidence=0.0,
                    reason=f"The pledge data is internally inconsistent (pledged {pledged:,.0f} shares vs total promoter shares "
                           f"{(total or 0):,.0f} = {pct:,.2f}%) - a pledge percentage must lie between 0% and 100%, so no value is reported."
                    if pledged is not None else "The pledge percentage is outside 0-100% - no value is reported.")
    if sh.get("source") == "uploaded_filing" and pledged is not None and total:
        # the pledged-share count is read from the shareholding-pattern filing ITSELF (primary source) and, where the filing also
        # tags the pledged percentage, the two must agree
        direct = sh.get("promoter_pledge_pct_filing", sh.get("promoter_pledge_pct"))
        if direct is not None and abs(direct - pct) > 0.05:
            return _res(key, value_raw=pct, unit="%", status="needs_review", confidence=0.7, estimated=True,
                        warnings=[f"The filing's own pledged percentage ({direct:.2f}%) disagrees with pledged/total shares ({pct:.2f}%)."])
        return _res(key, value_raw=pct, unit="%", status="verified", confidence=1.0,
                    num=_legd("Pledged Promoter Shares", pledged, unit="shares", source="Shareholding Pattern (uploaded filing)"),
                    den=_legd("Total Promoter Shareholding (shares)", total, unit="shares", source="Shareholding Pattern (uploaded filing)"))
    # The pledged-share count comes from NSE's pledge-data endpoint (a secondary aggregator), not from the shareholding-pattern
    # filing itself and it is not cross-checked against it: a figure that cannot be verified at the primary source is
    # `needs_review`, never `verified`.
    w = ["Source is NSE's pledge-data endpoint (secondary); the pledged-share count was not cross-checked against the "
         "shareholding-pattern filing itself, so it is not marked verified."]
    if status != "ok":
        w.append("NSE lists only scrips with a pledge on record; its absence is the evidence for 0%.")
    return _res(key, value_raw=pct, unit="%", status="needs_review", confidence=0.85, estimated=True, warnings=w,
                num=_legd("Pledged Promoter Shares", pledged, unit="shares", source="Shareholding Pattern (NSE)") if pledged is not None else None,
                den=_legd("Total Promoter Shareholding (shares)", total, unit="shares", source="Shareholding Pattern (NSE)") if total else None)


def free_float_result(sh):
    """Free Float % = 100 - promoter & promoter-group % - locked-in % (when disclosed).
    Without a locked-in disclosure it is a labelled PROXY (needs_review), never exact."""
    key = "free_float_pct"
    if sh is None or sh.get("promoter_holding_pct") is None:
        return _res(key, unit="%", status="not_disclosed", confidence=0.0,
                    reason="Promoter holding is not available from the Shareholding Pattern - free float cannot be derived "
                           "(it is not assumed to be 100%).")
    promoter = float(sh["promoter_holding_pct"])
    locked = sh.get("locked_in_pct")
    if locked is not None:
        ff = max(100.0 - promoter - float(locked), 0.0)
        return _res(key, value_raw=ff, unit="%", status="verified", confidence=0.95,
                    num=_legd("Free Float % = Total Shares − Promoter Holding − Locked-in Shares", ff, unit="%", parts=[
                        _part("Total shares (100%)", 100.0, 1, source="Shareholding Pattern"),
                        _part("Promoter & promoter-group holding", promoter, -1, source="Shareholding Pattern"),
                        _part("Locked-in shares", float(locked), -1, source="Shareholding Pattern")]))
    ff = max(100.0 - promoter, 0.0)
    return _res(key, value_raw=ff, unit="%", status="needs_review", confidence=0.8, estimated=True,
                warnings=["Locked-in / non-tradable shares are not disclosed in the shareholding data: this is the non-promoter "
                          "shareholding, a PROXY for free float."],
                num=_legd("Free Float % (proxy) = Total Shares − Promoter Holding", ff, unit="%", parts=[
                    _part("Total shares (100%)", 100.0, 1, source="Shareholding Pattern"),
                    _part("Promoter & promoter-group holding", promoter, -1, source="Shareholding Pattern")]))


def _with_breakdown(fn):
    """Provider-backed ratios (Beta, Promoter Pledge, Free Float) have no FactSet; their breakdown is built from the
    result's own legs the same way."""
    import functools

    @functools.wraps(fn)
    def inner(*a, **k):
        res = fn(*a, **k)
        try:
            from tools.ratio_breakdown import build_breakdown
            res["breakdown"] = build_breakdown(res["ratio_key"], res, None, None)
        except Exception as e:
            print(f"[ratio_contract] breakdown for {res.get('ratio_key')} failed: {type(e).__name__}: {e}")
            res["breakdown"] = None
        return res
    return inner


beta_result = _with_breakdown(beta_result)
pledge_result = _with_breakdown(pledge_result)
free_float_result = _with_breakdown(free_float_result)
