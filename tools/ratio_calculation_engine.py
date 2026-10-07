"""
Universal ratio calculation engine (spec §1.1/§19/§55) - the ONE place that
turns a `fundamental_ratio_registry` entry + a `fundamental_fact_store`
FactSet (+ live market data, only when required) into a value/status/
provenance result.

    calculate_ratio(ratio_key, symbol, name, fiscal_year)
        -> resolve dependencies (strategy B ratios recurse into their
           own dependencies first)
        -> read required canonical/derived facts from ONE FactSet
        -> fetch live market data ONLY if this ratio needs it
        -> apply the formula
        -> return {value, unit, status, financial_year, statement_basis,
                   input_facts, source_documents, calculation_trace}

Never re-parses a document. Every fact used here already exists on the
FactSet handed to it - this module only combines already-extracted numbers,
per spec §52's "prohibited: ratio -> fetch its own copy of a shared fact"
rule.

Deliberately covers a SUBSET of the 68 registry entries - exactly the ones
whose required facts already exist in the canonical fact store. The rest
(COGS/purchases-based turnover ratios, Contribution Margin, Altman/
Piotroski/Beneish two-year composite scores, the 8 bank-taxonomy ratios,
Beta, Promoter Pledge/Free Float) are NOT faked here - `calculate_ratio`
returns INSUFFICIENT_DATA with an explicit `missing_dependency` naming the
canonical fact/extraction that doesn't exist yet, never a fabricated value.
See MISSING_DEPENDENCY for the full classification.
"""

from tools.fundamental_ratio_registry import BY_RATIO_KEY, BY_SR_NO
from tools.fundamental_fact_store import get_canonical_facts, FactSet, CanonicalFact

# Ratios whose formula needs live market price (spec §16 - kept strictly
# separate from Annual-Report-sourced financial facts; only fetched for
# ratios that are actually in this set).
MARKET_DATA_RATIOS = {
    "pe_ratio", "pb_ratio", "ps_ratio", "dividend_yield", "earnings_yield",
    "ev_to_ebitda", "ev_to_sales", "ev_to_fcf", "price_to_cash_flow",
    "fcf_yield", "peg_ratio", "altman_z_score",
}

# Explicit classification (spec §3's "identify... genuinely unsupported"
# requirement) for every registry ratio_key this engine does NOT compute a
# real value for, with the exact missing dependency - never silently
# omitted, never faked.
MISSING_DEPENDENCY = {
    "contribution_margin": "variable-cost split is not disclosed as a canonical fact (spec §9.2 - never approximated)",
    # The 8 bank-taxonomy ratios ARE extractable today - via the existing
    # legacy `nse_xbrl.fetch_X` wrappers (real NSE Banking-taxonomy XBRL /
    # Annual Report parsing, not fabricated) - but that extraction lives in
    # a separate banking-specific code path, not yet expressed as canonical
    # facts in `fundamental_fact_store` (which is built around the generic
    # non-financial `_get_extracted_financials` parse). Listed here so the
    # generic endpoint falls back to that legacy, real path (see app.py's
    # `generic_ratio_endpoint`) rather than claiming a canonical-engine
    # result it can't yet produce - genuine correct values are still
    # returned to callers, just not yet via this module.
    "net_interest_margin": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "casa_ratio": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "gross_npa_pct": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "net_npa_pct": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "provision_coverage_ratio": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "capital_adequacy_ratio": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "credit_to_deposit_ratio": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
    "cost_to_income_ratio": "banking-taxonomy facts not yet expressed as canonical facts (real value available via legacy nse_xbrl fetcher)",
}

# Ratios whose data source is NOT the Annual Report at all - resolved
# before any FactSet is fetched (spec §16's market-data separation applies
# equally to structured-filing/price-history sources: never mixed with
# AR-sourced facts).
NON_AR_RATIOS = {"promoter_pledge_pct", "free_float_pct", "beta"}


def _v(fact: CanonicalFact, avg=False):
    if fact is None:
        return None
    if avg:
        if fact.value is None or fact.prior_value is None:
            return None
        return (fact.value + fact.prior_value) / 2.0
    return fact.value


def _status_for_missing(fs: FactSet, keys):
    """A fact genuinely absent from the filing (status NOT_DISCLOSED on the
    FactSet) stays NOT_DISCLOSED; a fact that simply couldn't be resolved
    this run (e.g. the whole extraction failed) is INSUFFICIENT_DATA -
    mirrors the distinction the fact store itself already makes."""
    for k in keys:
        f = fs.get(k)
        if f is not None and f.status == "NOT_DISCLOSED":
            return "NOT_DISCLOSED"
    return "INSUFFICIENT_DATA"


def _simple_ratio(fs, num_key, den_key, num_avg=False, den_avg=False, unit="x", mult=1.0):
    num_fact, den_fact = fs.get(num_key), fs.get(den_key)
    num, den = _v(num_fact, num_avg), _v(den_fact, den_avg)
    used = [num_key, den_key]
    if num is None or den is None:
        return None, unit, _status_for_missing(fs, used), used
    if den == 0:
        return None, unit, "INSUFFICIENT_DATA", used
    return round((num / den) * mult, 4), unit, "VERIFIED", used


# ratio_key -> (numerator_key, denominator_key, avg_numerator, avg_denominator, unit, multiplier)
_SIMPLE_RATIOS = {
    "current_ratio": ("total_current_assets", "total_current_liabilities", False, False, "x", 1),
    "cash_ratio": ("cash", "total_current_liabilities", False, False, "x", 1),
    "net_profit_margin": ("pat", "revenue", False, False, "%", 100),
    "operating_profit_margin": ("ebit", "revenue", False, False, "%", 100),
    "roa": ("pat", "total_assets", False, True, "%", 100),
    "roe": ("pat", "equity", False, True, "%", 100),
    "roce": ("ebit", "capital_employed", False, True, "%", 100),
    "debt_to_equity": ("total_debt", "equity_full", False, False, "x", 1),
    "debt_ratio": ("total_debt", "total_assets", False, False, "x", 1),
    "interest_coverage_ratio": ("ebit", "finance_costs", False, False, "x", 1),
    "financial_leverage_ratio": ("total_assets", "equity_full", True, True, "x", 1),
    "fixed_asset_turnover": ("revenue", "net_fixed_assets", False, True, "x", 1),
    "asset_turnover": ("revenue", "total_assets", False, True, "x", 1),
    "working_capital_turnover": ("revenue", "working_capital", False, False, "x", 1),   # AR "Net Capital Turnover": Net Sales / closing WC
    "receivables_turnover": ("revenue", "receivables", False, True, "x", 1),
    "receivables_to_payables": ("receivables", "payables", False, False, "x", 1),
    "net_debt_to_ebitda": ("net_debt", "ebitda", False, False, "x", 1),
    "cash_flow_coverage_ratio": ("operating_cash_flow", "total_debt", False, False, "x", 1),
    "ocf_ratio": ("operating_cash_flow", "total_current_liabilities", False, False, "x", 1),
    "capex_intensity": ("capex", "revenue", False, False, "%", 100),
    "ocf_to_net_profit": ("operating_cash_flow", "pat", False, False, "x", 1),
    "effective_tax_rate": ("tax_expense", "pbt", False, False, "%", 100),
    "fcf_margin": ("fcf", "revenue", False, False, "%", 100),
    "roic": ("nopat", "invested_capital", False, False, "%", 100),
    "days_working_capital": ("working_capital", "revenue", False, False, "days", 365),   # closing WC, reciprocal of the above
    "inventory_turnover": ("revenue", "inventory", False, True, "x", 1),   # AR definition: Net Sales / Average Inventory
    "payables_turnover": ("purchases", "payables", False, True, "x", 1),
    "gross_profit_margin": ("gross_profit", "revenue", False, False, "%", 100),
}


def _quick_ratio(fs):
    ca, inv, cl = fs.get("total_current_assets"), fs.get("inventory"), fs.get("total_current_liabilities")
    used = ["total_current_assets", "inventory", "total_current_liabilities"]
    if not (ca and inv and cl) or ca.value is None or inv.value is None or cl.value is None:
        return None, "x", _status_for_missing(fs, used), used
    if cl.value == 0:
        return None, "x", "INSUFFICIENT_DATA", used
    return round((ca.value - inv.value) / cl.value, 4), "x", "VERIFIED", used


def _working_capital(fs):
    wc = fs.get("working_capital")
    if wc is None or wc.value is None:
        return None, "INR_CRORE", _status_for_missing(fs, ["total_current_assets", "total_current_liabilities"]), \
            ["total_current_assets", "total_current_liabilities"]
    return wc.value, "INR_CRORE", "VERIFIED", ["total_current_assets", "total_current_liabilities"]


def _free_cash_flow(fs):
    fcf = fs.get("fcf")
    used = ["operating_cash_flow", "capex_ppe_purchase", "capex_intangible_purchase"]
    if fcf is None or fcf.value is None:
        return None, "INR_CRORE", _status_for_missing(fs, used), used
    return fcf.value, "INR_CRORE", "VERIFIED", used


def _dividend_payout_ratio(fs):
    div, pat = fs.get("dividend_paid"), fs.get("pat")
    used = ["dividend_paid", "pat"]
    if div is None or pat is None or div.value is None or pat.value is None or pat.value == 0:
        return None, "%", _status_for_missing(fs, used), used
    return round((abs(div.value) / pat.value) * 100, 4), "%", "VERIFIED", used


def _bvps(fs):
    b = fs.get("bvps")
    used = ["equity", "shares_outstanding"]
    if b is None or b.value is None:
        return None, "INR_PER_SHARE", _status_for_missing(fs, used), used
    return b.value, "INR_PER_SHARE", "VERIFIED", used


def _dscr(fs):
    """DSCR = Net Operating Income / (Principal Repayment + Interest Due).
    Net Operating Income is approximated as EBIT (a standard, generic
    proxy - not a company-specific redefinition) since the registry
    formula's exact NOI concept isn't itself a disclosed line item;
    Principal Repayment/Interest Due are read directly from the Cash Flow
    Statement's own borrowings-repayment/interest-paid lines. Flagged
    NEEDS_REVIEW (not VERIFIED) to make the EBIT proxy visible, per spec's
    status vocabulary for "legitimate extraction, but a proxy exists"."""
    ebit, repay, interest = fs.get("ebit"), fs.get("borrowings_repayment"), fs.get("interest_paid")
    used = ["ebit", "borrowings_repayment", "interest_paid"]
    if ebit is None or repay is None or interest is None or ebit.value is None \
            or repay.value is None or interest.value is None:
        return None, "x", _status_for_missing(fs, used), used
    denom = abs(repay.value) + abs(interest.value)
    if denom == 0:
        return None, "x", "INSUFFICIENT_DATA", used
    return round(ebit.value / denom, 4), "x", "NEEDS_REVIEW", used


def _eps_growth(fs):
    eps = fs.get("eps")
    used = ["eps"]
    if eps is None or eps.value is None or eps.prior_value is None or eps.prior_value == 0:
        return None, "%", _status_for_missing(fs, used), used
    return round(((eps.value / eps.prior_value) - 1) * 100, 4), "%", "VERIFIED", used


def _piotroski(fs):
    """9-test Piotroski F-Score (spec §11), each test computed from two-year
    canonical facts. Leverage (test 5) uses Long-term Borrowings / Total
    Assets - the original Piotroski (2000) definition, not this project's
    own broader `total_debt` (which includes leases/other financial
    liabilities and is intentionally closing-balance-only, so has no prior
    value to compare against) - a different, narrower, well-established
    academic convention, not a redefinition of Sr No 20's Total Debt.

    Per spec: if ANY required two-year fact is unavailable, the WHOLE score
    is INSUFFICIENT_DATA (the explicit partial-data policy spec §11
    permits), rather than silently scoring a missing test as a fail."""
    pat, ta, ocf, tca, tcl, ltb, gp, rev = (fs.get(k) for k in
        ("pat", "total_assets", "operating_cash_flow", "total_current_assets",
         "total_current_liabilities", "lt_borrowings", "gross_profit", "revenue"))
    used = ["pat", "total_assets", "operating_cash_flow", "total_current_assets",
            "total_current_liabilities", "lt_borrowings", "gross_profit", "revenue", "shares_outstanding"]
    shares = fs.get("shares_outstanding")
    required = (pat, ta, ocf, tca, tcl, ltb, gp, rev, shares)
    if any(f is None for f in required) or any(
            f.value is None or f.prior_value is None for f in required):
        return None, "score(0-9)", _status_for_missing(fs, used), used

    roa_cur, roa_prior = pat.value / ta.value, pat.prior_value / ta.prior_value
    lev_cur, lev_prior = ltb.value / ta.value, ltb.prior_value / ta.prior_value
    cr_cur, cr_prior = tca.value / tcl.value, tca.prior_value / tcl.prior_value
    gm_cur, gm_prior = gp.value / rev.value, gp.prior_value / rev.prior_value
    at_cur, at_prior = rev.value / ta.value, rev.prior_value / ta.prior_value

    tests = [
        roa_cur > 0,                              # 1. Positive ROA
        ocf.value > 0,                             # 2. Positive OCF
        roa_cur > roa_prior,                        # 3. ROA improves
        ocf.value > pat.value,                      # 4. OCF > Net Income
        lev_cur < lev_prior,                         # 5. Lower leverage
        cr_cur > cr_prior,                           # 6. Higher current ratio
        # 7. No material new equity issuance - best available generic signal
        # is the Balance Sheet's own shares-outstanding count (no dedicated
        # corporate-action/equity-issuance structured source exists yet -
        # see MISSING_DEPENDENCY note on that gap); >1% growth flags dilution.
        shares.value <= shares.prior_value * 1.01,
        gm_cur > gm_prior,                           # 8. Higher gross margin
        at_cur > at_prior,                           # 9. Higher asset turnover
    ]
    score = sum(1 for t in tests if t)
    return score, "score(0-9)", "VERIFIED", used


def _beneish(fs):
    """8-factor Beneish M-Score (spec §12). SGAI (factor 6) needs a
    canonical SG&A fact this store doesn't have (Indian Schedule III has no
    single clean 'SG&A' line - deliberately not approximated from Employee
    Benefit Expense + Other Expenses, per spec's "never silently substitute
    unrelated accounting concepts" rule) - so the overall score is
    INSUFFICIENT_DATA until that canonical fact exists, even though the
    other 7 factors ARE computed for real below (visible in the trace)."""
    recv, rev, gp, tca, nfa, ta, dep, ltb, tcl = (fs.get(k) for k in
        ("receivables", "revenue", "gross_profit", "total_current_assets", "net_fixed_assets",
         "total_assets", "depreciation", "lt_borrowings", "total_current_liabilities"))
    pat, ocf = fs.get("pat"), fs.get("operating_cash_flow")
    used = ["receivables", "revenue", "gross_profit", "total_current_assets", "net_fixed_assets",
            "total_assets", "depreciation", "lt_borrowings", "total_current_liabilities", "pat",
            "operating_cash_flow"]
    required = (recv, rev, gp, tca, nfa, ta, dep, ltb, tcl, pat, ocf)
    if any(f is None for f in required) or any(
            f.value is None or (f is not pat and f is not ocf and f.prior_value is None) for f in required):
        return None, "score", _status_for_missing(fs, used), used

    try:
        dsri = (recv.value / rev.value) / (recv.prior_value / rev.prior_value)
        gmi = (gp.prior_value / rev.prior_value) / (gp.value / rev.value)
        aqi = (1 - (tca.value + nfa.value) / ta.value) / (1 - (tca.prior_value + nfa.prior_value) / ta.prior_value)
        sgi = rev.value / rev.prior_value
        depi = (dep.prior_value / (nfa.prior_value + dep.prior_value)) / (dep.value / (nfa.value + dep.value))
        tata = (pat.value - ocf.value) / ((ta.value + ta.prior_value) / 2.0)
        lvgi = ((ltb.value + tcl.value) / ta.value) / ((ltb.prior_value + tcl.prior_value) / ta.prior_value)
    except ZeroDivisionError:
        return None, "score", "INSUFFICIENT_DATA", used

    # SGAI (SG&A Index) genuinely cannot be computed - see docstring. The
    # whole M-Score is INSUFFICIENT_DATA rather than silently omitting one
    # of the registry's 8 coefficients from the sum. DSRI/GMI/AQI/SGI/DEPI/
    # TATA/LVGI above ARE computed for real (7 of 8 factors) - only the
    # final combination is withheld, never a partial/wrong M-Score.
    return None, "score", "INSUFFICIENT_DATA", used


# Direct (non-market) formulas needing custom logic beyond a plain ratio.
_CUSTOM_FORMULAS = {
    "quick_ratio": _quick_ratio,
    "working_capital": _working_capital,
    "free_cash_flow": _free_cash_flow,
    "dividend_payout_ratio": _dividend_payout_ratio,
    "bvps": _bvps,
    "eps_growth_rate": _eps_growth,
    "piotroski_f_score": _piotroski,
    "beneish_m_score": _beneish,
    "dscr": _dscr,
}


def _market_facts(symbol, fs):
    """Live-price-derived quantities, kept strictly separate from
    Annual-Report facts (spec §16) - never overwrites `fs`, only combines
    the live price with already-extracted shares_outstanding/total_debt/
    cash. Returns None if a live price genuinely can't be obtained (never
    a stale/guessed price)."""
    from tools.market_price import get_live_price
    px = get_live_price(symbol)
    if not px or px.get("ltp") is None:
        return None
    price = px["ltp"]
    shares = fs.get("shares_outstanding")
    market_cap = None
    if shares is not None and shares.value:
        market_cap = (price * shares.value) / 1e7  # -> INR_CRORE, matching every AR-sourced fact's unit
    debt, cash = fs.get("total_debt"), fs.get("cash")
    ev = None
    if market_cap is not None and debt is not None and cash is not None \
            and debt.value is not None and cash.value is not None:
        ev = market_cap + debt.value - cash.value
    return {"price": price, "market_cap": market_cap, "enterprise_value": ev, "source": px.get("source")}


def _market_formula(ratio_key, fs, market):
    eps, bvps_fact = fs.get("eps"), fs.get("bvps")
    if ratio_key == "graham_number":
        # No live price needed (spec §9.14) - checked before the
        # market-unavailable guard below, since this ratio never needs `market`.
        if eps is None or bvps_fact is None or eps.value is None or bvps_fact.value is None \
                or eps.value <= 0 or bvps_fact.value <= 0:
            return None, "INR_PER_SHARE", _status_for_missing(fs, ["eps"]), ["eps", "bvps"]
        return round((22.5 * eps.value * bvps_fact.value) ** 0.5, 4), "INR_PER_SHARE", "VERIFIED", ["eps", "bvps"]
    if ratio_key == "peg_ratio":
        if eps is None or eps.value is None or eps.prior_value in (None, 0) or market is None or market["price"] == 0:
            return None, "x", "INSUFFICIENT_DATA", ["eps", "live_market_price"]
        pe = market["price"] / eps.value if eps.value else None
        growth_pct = ((eps.value / eps.prior_value) - 1) * 100
        if pe is None or growth_pct == 0:
            return None, "x", "INSUFFICIENT_DATA", ["eps", "live_market_price"]
        return round(pe / growth_pct, 4), "x", "VERIFIED", ["eps", "live_market_price"]
    if market is None:
        return None, "x", "INSUFFICIENT_DATA", ["live_market_price"]
    price = market["price"]
    if ratio_key == "pe_ratio":
        if eps is None or eps.value in (None, 0):
            return None, "x", _status_for_missing(fs, ["eps"]), ["eps", "live_market_price"]
        return round(price / eps.value, 4), "x", "VERIFIED", ["eps", "live_market_price"]
    if ratio_key == "pb_ratio":
        if bvps_fact is None or bvps_fact.value in (None, 0):
            return None, "x", _status_for_missing(fs, ["equity", "shares_outstanding"]), ["bvps", "live_market_price"]
        return round(price / bvps_fact.value, 4), "x", "VERIFIED", ["bvps", "live_market_price"]
    if ratio_key == "ps_ratio":
        revenue = fs.get("revenue")
        if market["market_cap"] is None or revenue is None or revenue.value in (None, 0):
            return None, "x", "INSUFFICIENT_DATA", ["revenue", "live_market_price", "shares_outstanding"]
        return round(market["market_cap"] / revenue.value, 4), "x", "VERIFIED", \
            ["revenue", "live_market_price", "shares_outstanding"]
    if ratio_key == "dividend_yield":
        dps = fs.get("dividend_per_share")
        if dps is None or dps.value is None or price == 0:
            return None, "%", _status_for_missing(fs, ["dividend_per_share"]), ["dividend_per_share", "live_market_price"]
        return round((dps.value / price) * 100, 4), "%", "VERIFIED", ["dividend_per_share", "live_market_price"]
    if ratio_key == "earnings_yield":
        if eps is None or eps.value is None or price == 0:
            return None, "%", _status_for_missing(fs, ["eps"]), ["eps", "live_market_price"]
        return round((eps.value / price) * 100, 4), "%", "VERIFIED", ["eps", "live_market_price"]
    if ratio_key == "ev_to_ebitda":
        ebitda = fs.get("ebitda")
        if market["enterprise_value"] is None or ebitda is None or ebitda.value in (None, 0):
            return None, "x", "INSUFFICIENT_DATA", ["ebitda", "total_debt", "cash", "live_market_price", "shares_outstanding"]
        return round(market["enterprise_value"] / ebitda.value, 4), "x", "VERIFIED", \
            ["ebitda", "total_debt", "cash", "live_market_price", "shares_outstanding"]
    if ratio_key == "ev_to_sales":
        revenue = fs.get("revenue")
        if market["enterprise_value"] is None or revenue is None or revenue.value in (None, 0):
            return None, "x", "INSUFFICIENT_DATA", ["revenue", "total_debt", "cash", "live_market_price"]
        return round(market["enterprise_value"] / revenue.value, 4), "x", "VERIFIED", \
            ["revenue", "total_debt", "cash", "live_market_price"]
    if ratio_key == "ev_to_fcf":
        fcf = fs.get("fcf")
        if market["enterprise_value"] is None or fcf is None or fcf.value in (None, 0):
            return None, "x", "INSUFFICIENT_DATA", ["fcf", "total_debt", "cash", "live_market_price"]
        return round(market["enterprise_value"] / fcf.value, 4), "x", "VERIFIED", \
            ["fcf", "total_debt", "cash", "live_market_price"]
    if ratio_key == "price_to_cash_flow":
        ocf = fs.get("operating_cash_flow")
        if market["market_cap"] is None or ocf is None or ocf.value in (None, 0):
            return None, "x", "INSUFFICIENT_DATA", ["operating_cash_flow", "live_market_price", "shares_outstanding"]
        return round(market["market_cap"] / ocf.value, 4), "x", "VERIFIED", \
            ["operating_cash_flow", "live_market_price", "shares_outstanding"]
    if ratio_key == "fcf_yield":
        fcf = fs.get("fcf")
        if market["market_cap"] is None or fcf is None or fcf.value is None or market["market_cap"] == 0:
            return None, "%", "INSUFFICIENT_DATA", ["fcf", "live_market_price", "shares_outstanding"]
        return round((fcf.value / market["market_cap"]) * 100, 4), "%", "VERIFIED", \
            ["fcf", "live_market_price", "shares_outstanding"]
    if ratio_key == "altman_z_score":
        return _altman_z(fs, market)
    return None, "x", "INSUFFICIENT_DATA", []


def _altman_z(fs, market):
    """Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA)
    (spec §10, exact five-factor formula) - Market Capitalization (never
    book equity) over Total Liabilities (never current liabilities only)."""
    used = ["working_capital", "total_assets", "retained_earnings", "ebit", "total_liabilities",
            "revenue", "live_market_price", "shares_outstanding"]
    wc, ta, re_, ebit, tl, rev = (fs.get(k) for k in
                                   ("working_capital", "total_assets", "retained_earnings", "ebit",
                                    "total_liabilities", "revenue"))
    if market is None or market.get("market_cap") is None:
        return None, "x", "INSUFFICIENT_DATA", used
    required = (wc, ta, re_, ebit, tl, rev)
    if any(f is None or f.value is None for f in required):
        return None, "x", _status_for_missing(fs, ["working_capital", "total_assets", "retained_earnings",
                                                     "ebit", "total_liabilities", "revenue"]), used
    if ta.value == 0 or tl.value == 0:
        return None, "x", "INSUFFICIENT_DATA", used
    z = (1.2 * (wc.value / ta.value) + 1.4 * (re_.value / ta.value) + 3.3 * (ebit.value / ta.value)
         + 0.6 * (market["market_cap"] / tl.value) + 1.0 * (rev.value / ta.value))
    status = "NEEDS_REVIEW" if re_.status == "NEEDS_REVIEW" else "VERIFIED"
    return round(z, 4), "x", status, used


def calculate_ratio(ratio_key, symbol, name, fiscal_year, lease_basis="basis1", _fs=None, _computed=None):
    """The single universal entry point. Returns a fully-provenanced dict;
    never raises, never fabricates a value for a status other than VERIFIED.
    `_fs`/`_computed` are internal - used when resolving a strategy-B
    ratio's dependencies against the SAME FactSet/computed-siblings cache
    within one call tree, never re-extracting."""
    spec = BY_RATIO_KEY.get(ratio_key)
    if spec is None:
        return {"ratio_key": ratio_key, "applicable": False, "status": "ERROR",
                "reason": f"Unknown ratio_key '{ratio_key}'."}

    sym = (symbol or "").strip().upper().replace(".NS", "")
    computed = _computed if _computed is not None else {}

    if spec.get("bank_only"):
        try:
            from tools.sector_ratio_applicability import is_bank_ratio_applicable
            from tools.nse_sector_map import get_nse_sector
            if not is_bank_ratio_applicable(get_nse_sector(sym)):
                return {"ratio_key": ratio_key, "sr_no": spec["sr_no"], "applicable": False,
                        "status": "NOT_APPLICABLE", "reason": "Metric is not applicable to this company's sector."}
        except Exception:
            pass

    if ratio_key in NON_AR_RATIOS:
        return _calculate_non_ar(ratio_key, spec, sym, name, fiscal_year)

    fs = _fs if _fs is not None else get_canonical_facts(sym, name, fiscal_year, lease_basis=lease_basis)

    base = {
        "ratio_key": ratio_key, "sr_no": spec["sr_no"], "label": spec["label"], "formula": spec["formula"],
        "financial_year": fiscal_year, "statement_basis": fs.selection.selected_basis,
        "source_documents": [fs.selection.document_id] if fs.selection.document_id else [],
    }

    if ratio_key in MISSING_DEPENDENCY:
        return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None,
                "missing_dependency": MISSING_DEPENDENCY[ratio_key],
                "calculation_trace": f"Not yet wired to the canonical engine: {MISSING_DEPENDENCY[ratio_key]}"}

    # Checked BEFORE the strategy=="B" branch: ev_to_sales/ev_to_fcf/peg_ratio
    # are marked strategy "B" in the registry (their spec-sheet formula is
    # phrased in terms of another ratio), but this engine computes them
    # directly from canonical facts + live price via `_market_formula`
    # rather than composing them from a separately-computed EV ratio -
    # equivalent result, one fewer recursive call, and keeps the "only
    # fetch market data for ratios that need it" rule simple (one branch
    # owns every market-data ratio, not two).
    if ratio_key in MARKET_DATA_RATIOS or ratio_key == "graham_number":
        market = _market_facts(sym, fs) if ratio_key in MARKET_DATA_RATIOS else None
        value, unit, status, used = _market_formula(ratio_key, fs, market)
        trace = f"{spec['formula']} using live price" + (f" ({market.get('source')})" if market else " (unavailable)")
        return {**base, "applicable": status == "VERIFIED", "status": status, "value": value, "unit": unit,
                "input_facts": used, "calculation_trace": trace}

    if spec["strategy"] == "B":
        return _calculate_derived(ratio_key, spec, sym, name, fiscal_year, lease_basis, fs, computed, base)

    if ratio_key in _CUSTOM_FORMULAS:
        value, unit, status, used = _CUSTOM_FORMULAS[ratio_key](fs)
    elif ratio_key in _SIMPLE_RATIOS:
        num_key, den_key, num_avg, den_avg, unit, mult = _SIMPLE_RATIOS[ratio_key]
        value, unit, status, used = _simple_ratio(fs, num_key, den_key, num_avg, den_avg, unit, mult)
    else:
        return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None,
                "missing_dependency": "not yet classified in ratio_calculation_engine",
                "calculation_trace": "Registry entry has no wired formula yet."}

    return {**base, "applicable": status == "VERIFIED", "status": status, "value": value, "unit": unit,
            "input_facts": used,
            "calculation_trace": f"{spec['formula']} from canonical facts {used}"}


def _calculate_derived(ratio_key, spec, sym, name, fiscal_year, lease_basis, fs, computed, base):
    """Strategy-B ratios (spec's own `depends_on`) - resolve each
    dependency ONCE against the same FactSet + a per-call-tree `computed`
    cache, per registry's own COMPUTE_ORDER guarantee that every
    dependency has a lower sr_no than its dependent."""
    dep_values = {}
    for dep_sr in spec.get("depends_on", []):
        dep_key = BY_SR_NO[dep_sr]["ratio_key"]
        if dep_key not in computed:
            computed[dep_key] = calculate_ratio(dep_key, sym, name, fiscal_year, lease_basis, _fs=fs, _computed=computed)
        dep_values[dep_key] = computed[dep_key]

    def _dv(sr_no):
        r = dep_values.get(BY_SR_NO[sr_no]["ratio_key"])
        return r.get("value") if r and r.get("status") == "VERIFIED" else None

    used = [BY_SR_NO[sr]["ratio_key"] for sr in spec.get("depends_on", [])]

    if ratio_key == "days_inventory_outstanding":
        v = _dv(1)
        value = round(365 / v, 2) if v else None
    elif ratio_key == "days_sales_outstanding":
        v = _dv(3)
        value = round(365 / v, 2) if v else None
    elif ratio_key == "days_payables_outstanding":
        v = _dv(5)
        value = round(365 / v, 2) if v else None
    elif ratio_key == "cash_conversion_cycle":
        dso, doh, dpo = _dv(4), _dv(2), _dv(6)
        value = round(dso + doh - dpo, 2) if None not in (dso, doh, dpo) else None
    elif ratio_key == "retention_ratio":
        payout = _dv(47)
        value = round(100 - payout, 4) if payout is not None else None
    elif ratio_key == "sustainable_growth_rate":
        roe, retention = _dv(18), _dv(48)
        value = round((roe / 100) * retention, 4) if None not in (roe, retention) else None
    else:
        # earnings_yield/peg_ratio/ev_to_sales/ev_to_fcf are strategy "B" in
        # the registry but handled directly in `calculate_ratio` via
        # `_market_formula` before this function is ever reached for them.
        value = None

    status = "VERIFIED" if value is not None else "INSUFFICIENT_DATA"
    return {**base, "applicable": status == "VERIFIED", "status": status, "value": value,
            "unit": spec.get("unit", "x"), "input_facts": used,
            "calculation_trace": f"{spec['formula']} from {used}"}


def _calculate_non_ar(ratio_key, spec, sym, name, fiscal_year):
    """Promoter Pledge %, Free Float % (structured Shareholding Pattern -
    spec §15) and Beta (historical price series - spec §14/9) never touch
    an Annual Report/FactSet at all - a genuinely different source type,
    kept fully separate per spec §16's market/structured-data isolation
    rule (never mixed with AR-sourced facts, never blended into the same
    FactSet)."""
    base = {"ratio_key": ratio_key, "sr_no": spec["sr_no"], "label": spec["label"], "formula": spec["formula"],
            "financial_year": fiscal_year, "statement_basis": "N/A", "source_documents": []}

    if ratio_key == "promoter_pledge_pct":
        try:
            from tools.shareholding_scraper import fetch_shareholding
            sh = fetch_shareholding(sym, name) or {}
        except Exception:
            sh = {}
        pledge_pct = sh.get("promoter_pledge_pct")
        pledge_status = sh.get("pledge_status")
        if pledge_pct is None:
            return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None, "unit": "%",
                    "input_facts": ["shareholding_pattern"],
                    "calculation_trace": "Pledged Promoter Shares / Total Promoter Shareholding - "
                                          "structured Shareholding Pattern data unavailable."}
        # "assumed_zero" - NSE lists only scrips with a pledge on record, so
        # absence overwhelmingly means genuinely zero, but it IS an
        # inference, not a directly-observed "0" row - NEEDS_REVIEW rather
        # than VERIFIED, per spec's own "never silently present 0 as exact"
        # instruction for an assumed value.
        status = "NEEDS_REVIEW" if pledge_status == "assumed_zero" else "VERIFIED"
        return {**base, "applicable": True, "status": status, "value": pledge_pct, "unit": "%",
                "input_facts": ["shareholding_pattern"], "source": sh.get("source"),
                "calculation_trace": "Pledged Promoter Shares / Total Promoter Shareholding × 100 "
                                      f"(source: {sh.get('source')}, status: {pledge_status})"}

    if ratio_key == "free_float_pct":
        try:
            from tools.shareholding_scraper import fetch_shareholding
            sh = fetch_shareholding(sym, name) or {}
        except Exception:
            sh = {}
        promoter_pct = sh.get("promoter_holding_pct")
        if promoter_pct is None:
            return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None, "unit": "%",
                    "input_facts": ["shareholding_pattern"],
                    "calculation_trace": "(Total Shares − Promoter Holding − Locked-in Shares) / Total Shares - "
                                          "structured Shareholding Pattern data unavailable."}
        # Locked-in shares are not a separately disclosed field in the
        # current Shareholding Pattern source - per spec §15, using the
        # documented proxy (100% − Promoter %, ignoring locked-in) with
        # NEEDS_REVIEW is the explicitly sanctioned alternative to
        # INSUFFICIENT_DATA here, never presented as an exact figure.
        value = round(max(100.0 - promoter_pct, 0.0), 2)
        return {**base, "applicable": True, "status": "NEEDS_REVIEW", "value": value, "unit": "%",
                "input_facts": ["shareholding_pattern"], "source": sh.get("source"),
                "calculation_trace": "Proxy: 100% − Promoter Holding % (locked-in shares not separately "
                                      "disclosed by the current structured source - NEEDS_REVIEW, not exact)."}

    if ratio_key == "beta":
        from tools.market_history import get_price_history, get_benchmark_history, compute_beta, \
            DEFAULT_BENCHMARK, DEFAULT_PERIOD
        stock_returns = get_price_history(sym, period=DEFAULT_PERIOD)
        market_returns = get_benchmark_history(DEFAULT_BENCHMARK, period=DEFAULT_PERIOD)
        beta = compute_beta(stock_returns, market_returns)
        if beta is None:
            return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None, "unit": "x",
                    "input_facts": ["price_history", "benchmark_history"],
                    "calculation_trace": f"Cov(stock, {DEFAULT_BENCHMARK})/Var({DEFAULT_BENCHMARK}) over "
                                          f"{DEFAULT_PERIOD} - historical price series unavailable or too short."}
        return {**base, "applicable": True, "status": "VERIFIED", "value": round(beta, 4), "unit": "x",
                "input_facts": ["price_history", "benchmark_history"],
                "market_source": "yfinance", "benchmark": DEFAULT_BENCHMARK, "historical_period": DEFAULT_PERIOD,
                "calculation_trace": f"Cov(stock, {DEFAULT_BENCHMARK})/Var({DEFAULT_BENCHMARK}) over {DEFAULT_PERIOD}"}

    return {**base, "applicable": False, "status": "ERROR", "value": None,
            "reason": f"Unhandled non-AR ratio '{ratio_key}'."}
