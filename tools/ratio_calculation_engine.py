"""
Canonical ratio API (spec §1.1/§19/§55) - the entry point behind `/api/v1/ratio/{ratio_key}`.

    calculate_ratio(ratio_key, symbol, name, fiscal_year)
        -> FactSet   (tools.fundamental_fact_store: ONE extraction, normalized, provenance-bearing)
        -> compute   (tools.ratio_contract: the ONE formula for every ratio, shared with the
                      document-analysis engine and the nse_xbrl dashboard endpoints)
        -> {value, value_raw, unit, status, confidence, estimated, formula_version, warnings,
            numerator, denominator, inputs (fact provenance), calculation_trace}

This module contains NO formulas. It only (a) gates bank-only ratios by sector, (b) supplies live market
data for the ratios that need it, (c) routes the three non-statement providers (Beta, Promoter Pledge %,
Free Float %) to their single shared policy, and (d) renders the contract result in the canonical API
shape (upper-case status vocabulary, canonical units, value rounded to 4 dp for display only).

Banking-specific ratios (Sr 58-65) read bank-taxonomy facts that live in a separate banking extraction
path; the canonical endpoint reports them as not-yet-wired so the generic API falls back to that legacy,
real bank module (the only implementation of those ratios - there is no second copy to diverge).
"""

from tools.fundamental_ratio_registry import BY_RATIO_KEY, BY_SR_NO
from tools.fundamental_fact_store import get_canonical_facts, FactSet, CanonicalFact
from tools import ratio_contract as rc

# Ratios whose formula needs live market price (kept strictly separate from Annual-Report facts).
MARKET_DATA_RATIOS = set(rc.MARKET_KEYS)

MISSING_DEPENDENCY = {
    k: "banking-taxonomy facts are extracted by the dedicated bank module (real value available via the legacy nse_xbrl fetcher)"
    for k in ("net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct", "provision_coverage_ratio",
              "capital_adequacy_ratio", "credit_to_deposit_ratio", "cost_to_income_ratio")
}

# Ratios whose data source is NOT the Annual Report at all.
NON_AR_RATIOS = {"promoter_pledge_pct", "free_float_pct", "beta"}

_STATUS_UP = {"verified": "VERIFIED", "needs_review": "NEEDS_REVIEW", "not_meaningful": "NOT_MEANINGFUL",
              "insufficient_data": "INSUFFICIENT_DATA", "not_disclosed": "NOT_DISCLOSED", "not_applicable": "NOT_APPLICABLE"}
_UNIT_CANON = {"₹ Cr": "INR_CRORE", "₹": "INR_PER_SHARE", "shares": "ABSOLUTE_SHARES"}


def _market(symbol):
    """Live price for market-dependent ratios; None if unobtainable (never a stale/guessed price)."""
    return rc.live_market(symbol)


def _render(res, base):
    st = _STATUS_UP.get(res.get("status"), "INSUFFICIENT_DATA")
    raw = res.get("value_raw")
    applicable = raw is not None and st in ("VERIFIED", "NEEDS_REVIEW")
    out = {
        **base, "applicable": applicable, "status": st,
        "value": round(raw, 4) if raw is not None else None, "value_raw": raw,
        "unit": _UNIT_CANON.get(res.get("unit"), res.get("unit")),
        "confidence": res.get("confidence"), "estimated": bool(res.get("estimated")),
        "input_facts": [i["fact"] for i in res.get("inputs") or []],
        "inputs": res.get("inputs"), "warnings": res.get("warnings"),
        "numerator": res.get("numerator"), "denominator": res.get("denominator"),
        "formula_version": res.get("formula_version"), "perimeter": res.get("perimeter"),
        "period_basis": res.get("period_basis"), "methodology": res.get("methodology"),
        "calculation_trace": res.get("methodology") or res.get("formula"),
    }
    if res.get("reason"):
        out["reason"] = res["reason"]
    for k in ("tests", "max_score", "tests_evaluated", "partial_score", "variables", "derived_from"):
        if k in res:
            out[k] = res[k]
    return out


def calculate_ratio(ratio_key, symbol, name, fiscal_year, lease_basis="basis1", _fs=None, _computed=None):
    """The single universal entry point. Returns a fully-provenanced dict; never raises, never fabricates a
    value for a status other than VERIFIED/NEEDS_REVIEW. `_fs`/`_computed` are internal - used when resolving
    a derived ratio's dependencies against the SAME FactSet/computed-siblings cache within one call tree."""
    spec = BY_RATIO_KEY.get(ratio_key)
    if spec is None:
        return {"ratio_key": ratio_key, "applicable": False, "status": "ERROR",
                "reason": f"Unknown ratio_key '{ratio_key}'."}

    sym = (symbol or "").strip().upper().replace(".NS", "")
    base = {"ratio_key": ratio_key, "sr_no": spec["sr_no"], "label": spec["label"], "formula": spec["formula"],
            "financial_year": fiscal_year}

    if spec.get("bank_only"):
        try:
            from tools.sector_ratio_applicability import is_bank_ratio_applicable
            from tools.nse_sector_map import get_nse_sector
            if not is_bank_ratio_applicable(get_nse_sector(sym)):
                return {**base, "statement_basis": "N/A", "source_documents": [], "applicable": False,
                        "status": "NOT_APPLICABLE", "reason": "Metric is not applicable to this company's sector."}
        except Exception:
            pass

    if ratio_key in NON_AR_RATIOS:
        return _calculate_non_ar(ratio_key, base, sym, name)

    if ratio_key in MISSING_DEPENDENCY:
        fs0 = _fs if _fs is not None else get_canonical_facts(sym, name, fiscal_year, lease_basis=lease_basis)
        return {**base, "statement_basis": fs0.selection.selected_basis,
                "source_documents": [fs0.selection.document_id] if fs0.selection.document_id else [],
                "applicable": False, "status": "INSUFFICIENT_DATA", "value": None,
                "missing_dependency": MISSING_DEPENDENCY[ratio_key],
                "calculation_trace": f"Not wired to the canonical engine: {MISSING_DEPENDENCY[ratio_key]}"}

    fs = _fs if _fs is not None else get_canonical_facts(sym, name, fiscal_year, lease_basis=lease_basis)
    base = {**base, "statement_basis": fs.selection.selected_basis,
            "source_documents": [fs.selection.document_id] if fs.selection.document_id else []}
    if fs.facts.get("_error"):
        return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None,
                "reason": fs.facts["_error"], "calculation_trace": "Annual Report facts unavailable."}

    market = _market(sym) if ratio_key in rc.MARKET_KEYS else None
    cache = _computed if _computed is not None else {}
    try:
        res = rc.compute_with_parents(ratio_key, fs, market, cache)
    except KeyError:
        return {**base, "applicable": False, "status": "INSUFFICIENT_DATA", "value": None,
                "missing_dependency": "not classified in the ratio contract",
                "calculation_trace": "Registry entry has no contract formula."}
    out = _render(res, base)
    if market is not None:
        out["input_facts"] = list(out["input_facts"]) + ["live_market_price"]
        out["market"] = {k: market.get(k) for k in ("price", "source", "as_of")}
    return out


def _calculate_non_ar(ratio_key, base, sym, name):
    """Promoter Pledge %, Free Float % (structured Shareholding Pattern) and Beta (price history) never touch an
    Annual Report/FactSet - one shared policy each (ratio_contract / market_history)."""
    base = {**base, "statement_basis": "N/A", "source_documents": []}
    if ratio_key == "beta":
        from tools.market_history import weekly_beta
        return _render(rc.beta_result(weekly_beta(sym), sym), base)
    try:
        from tools.shareholding_scraper import fetch_shareholding
        sh = fetch_shareholding(sym, name) or None
    except Exception:
        sh = None
    res = rc.pledge_result(sh) if ratio_key == "promoter_pledge_pct" else rc.free_float_result(sh)
    return _render(res, base)
