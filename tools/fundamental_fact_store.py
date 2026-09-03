"""
Canonical fact store (spec §6) - the authoritative "extract once, calculate
many" layer.

DOCUMENT -> EXTRACT FACT ONCE -> CANONICAL FACT -> NORMALIZE -> STORE ->
RATIOS CONSUME FACT.

Prior version of this module memoized calls to individual `fetch_X`
wrappers - each of which independently re-derived shared quantities (Total
Debt, EBIT, ...) in its own Python code even though they all read the same
underlying parsed statement. This version reads directly from the ONE
object that already IS the single-parse-per-(symbol, fiscal_year, basis)
result: `tools.annual_report_financials._get_extracted_financials(...)`
(lock-guarded, disk-cached 90 days - confirmed the shared "extract once"
entry point every `fetch_X_from_annual_report` function in that module
already calls, then each re-derives its own subset of values from). This
module is the ONE place that reads `parsed` and hands out typed,
provenance-bearing `CanonicalFact` objects - every canonical fact for a
given (symbol, fiscal_year) comes from exactly one such call, so REVENUE,
PAT, DEBT, EQUITY, etc. can never disagree on statement basis (they are
literally read out of the same dict).

Does not re-implement extraction. Total Debt reuses the existing shared
`_compute_total_debt(parsed, lease_basis)` (already the single source of
truth for Sr No 20/21/68's numerator, per that function's own docstring) -
adapted into the canonical layer rather than duplicated.
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Optional, Dict

from tools.statement_selector import select_statement_basis, StatementSelection

# Bump whenever `_DIRECT_FACT_MAP`, a derived-fact formula below, or the
# underlying `_get_extracted_financials`/`_compute_total_debt` extraction
# logic changes in a way that could change a previously-cached fact's
# value. Persisted alongside every `ratio_values` row (see
# db_ratio_reader.py); a bump here makes every row written under the OLD
# version a transparent cache miss on the next read, instead of requiring a
# manual per-symbol purge - see `tools.ratio_calculation_engine` and
# `db/002_extraction_version.sql` for the enforcement side.
# v2 - added cash-flow-statement canonical facts (operating_cash_flow,
# capex_*, borrowings_repayment, ...) and derived facts (working_capital,
# capital_employed, net_debt, capex, fcf, nopat, bvps, tax_rate).
# v3 - added retained_earnings (direct fact, NEEDS_REVIEW when sourced from
# the other_equity_proxy fallback) and derived cogs/gross_profit/purchases/
# total_liabilities.
# v4 - added lt_borrowings direct fact (Piotroski/Beneish leverage tests).
EXTRACTION_VERSION = 4


@dataclass(frozen=True)
class CanonicalFact:
    fact_key: str
    value: Optional[float]            # current-period value, already normalized to INR crore (or None)
    prior_value: Optional[float]      # prior-period value, same unit (or None) - for Average-X formulas
    unit: str                         # "INR_CRORE" | "ABSOLUTE_SHARES" | "INR_PER_SHARE" | "RATIO"
    currency: str                     # "INR"
    period: str                       # e.g. "FY2025"
    statement_basis: str              # "CONSOLIDATED" | "STANDALONE"
    company_identity: str             # resolved symbol
    source_document: Optional[str]    # Annual Report PDF URL
    source_page: Optional[int]        # balance-sheet or P&L anchor page, when known
    source_tag: Optional[str]         # which parsed[] key this came from
    extraction_method: str            # "annual_report_pdf" | "derived"
    status: str                       # "VERIFIED" | "NOT_DISCLOSED" | "INSUFFICIENT_DATA"
    confidence: Optional[float] = None


@dataclass(frozen=True)
class FactSet:
    symbol: str
    fiscal_year: int
    selection: StatementSelection
    facts: Dict[str, CanonicalFact] = field(default_factory=dict)

    def get(self, fact_key: str) -> Optional[CanonicalFact]:
        return self.facts.get(fact_key)


# canonical_key -> parsed[] key. Every one of these lives on the SAME
# `parsed` dict, so reading N of them costs one extraction, not N.
_DIRECT_FACT_MAP = {
    "revenue": "revenue",
    "pat": "pat",
    "pbt": "pbt",
    "equity": "equity",                 # owners-attributable
    "equity_full": "equity_full",       # owners + NCI
    "retained_earnings": "retained_earnings",
    "total_assets": "total_assets",
    "total_current_assets": "total_current_assets",
    "total_current_liabilities": "total_current_liabilities",
    "cash": "cash",
    "inventory": "inventory",
    "receivables": "receivables",
    "payables": "payables",
    "net_fixed_assets": "net_fixed_assets",
    "shares_outstanding": "shares_outstanding",
    "eps": "eps",
    "dividend_per_share": "dividend_per_share",
    "tax_expense": "tax_expense",
    "finance_costs": "finance_costs",
    "depreciation": "depreciation",
    "total_expenses": "total_expenses",
    "employee_benefit_expense": "employee_benefit_expense",
    "other_expenses": "other_expenses",
    "operating_cash_flow": "operating_cash_flow",
    "capex_ppe_purchase": "capex_ppe_purchase",
    "capex_intangible_purchase": "capex_intangible_purchase",
    "capex_disposal_proceeds": "capex_disposal_proceeds",
    "lt_borrowings": "lt_borrowings",   # long-term borrowings only - the classic Piotroski/Beneish leverage numerator
    "borrowings_repayment": "borrowings_repayment",
    "lease_repayment": "lease_repayment",
    "interest_paid": "interest_paid",
    "dividend_paid": "dividend_paid",
}

_PER_SHARE_FACTS = {"eps", "dividend_per_share"}
_ABSOLUTE_COUNT_FACTS = {"shares_outstanding"}

_lock = threading.Lock()
_run_cache: Dict[tuple, FactSet] = {}


def _unit_for(fact_key: str) -> str:
    if fact_key in _PER_SHARE_FACTS:
        return "INR_PER_SHARE"
    if fact_key in _ABSOLUTE_COUNT_FACTS:
        return "ABSOLUTE_SHARES"
    return "INR_CRORE"


def _split_pair(raw):
    """Most `parsed[]` entries are (current, prior) tuples (the shared shape
    every Average-X formula in the registry needs); a few are bare scalars.
    Normalizes either shape to (current, prior-or-None) without guessing a
    missing prior into 0."""
    if raw is None:
        return None, None
    if isinstance(raw, (tuple, list)):
        cur = raw[0] if len(raw) > 0 else None
        prior = raw[1] if len(raw) > 1 else None
        return cur, prior
    return raw, None


def _wrap_fact(fact_key, raw, symbol, period, basis, source_document, bs_page, pl_page) -> CanonicalFact:
    cur, prior = _split_pair(raw)
    status = "VERIFIED" if cur is not None else "NOT_DISCLOSED"
    page = bs_page if fact_key in ("total_assets", "total_current_assets", "total_current_liabilities",
                                    "equity", "equity_full", "cash", "inventory", "receivables",
                                    "payables", "net_fixed_assets", "shares_outstanding") else pl_page
    return CanonicalFact(
        fact_key=fact_key, value=cur, prior_value=prior, unit=_unit_for(fact_key),
        currency="INR", period=period, statement_basis=basis, company_identity=symbol,
        source_document=source_document, source_page=page, source_tag=fact_key,
        extraction_method="annual_report_pdf", status=status,
    )


def get_canonical_facts(symbol, name, fiscal_year, lease_basis="basis1") -> FactSet:
    """The one entry point ratios/qualitative evidence should read shared
    financial facts from. Resolves statement basis, performs (or reuses) the
    single cached extraction for (symbol, fiscal_year), and returns every
    canonical fact derived from that ONE parsed object - so two ratios that
    both need `total_debt` never trigger two independent extractions, and
    can never end up reading different statement bases.

    Memoized in-process for the lifetime of one run/request, keyed by
    (symbol, fiscal_year, lease_basis) - see `clear_run_cache`.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    key = (sym, fiscal_year, lease_basis)
    with _lock:
        cached = _run_cache.get(key)
    if cached is not None:
        return cached

    from tools.annual_report_financials import _get_extracted_financials, _compute_total_debt

    period = f"FY{fiscal_year}"

    # ONE extraction call for both the basis decision AND every canonical
    # fact - deliberately does NOT also call `select_statement_basis` here
    # (that would be a second, redundant call to `_get_extracted_financials`
    # for the exact same (symbol, fiscal_year, consolidated=True) request).
    # `select_statement_basis` remains the right entry point for OTHER
    # callers that need the basis decision alone, before doing their own
    # separate fetch (e.g. nse_xbrl.py's `_resolved_consolidated`).
    parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated=True)

    facts: Dict[str, CanonicalFact] = {}
    if not parsed or "error" in parsed:
        reason = (parsed or {}).get("error", "Annual Report not found or unreadable.")
        selection = StatementSelection(
            selected_basis="CONSOLIDATED", document_id=(parsed or {}).get("source_url"),
            financial_year=fiscal_year,
            selection_reason=f"Could not verify statement basis ({reason}); defaulting to consolidated-first.",
        )
        for fact_key in _DIRECT_FACT_MAP:
            facts[fact_key] = CanonicalFact(
                fact_key=fact_key, value=None, prior_value=None, unit=_unit_for(fact_key),
                currency="INR", period=period, statement_basis=selection.selected_basis,
                company_identity=sym, source_document=selection.document_id, source_page=None,
                source_tag=None, extraction_method="annual_report_pdf",
                status="INSUFFICIENT_DATA", confidence=None,
            )
        facts["_error"] = reason
        result = FactSet(symbol=sym, fiscal_year=fiscal_year, selection=selection, facts=facts)
        with _lock:
            _run_cache[key] = result
        return result

    source_document = parsed.get("source_url")
    bs_page = parsed.get("bs_page")
    pl_page = parsed.get("pl_page")
    # `basis_used` is what `_get_extracted_financials` ACTUALLY read after
    # its own consolidated-first/standalone-fallback logic (only falls back
    # on a genuine "not found", never on a partial-field parse gap - see
    # that function's own comments) - this IS the StatementSelection for
    # this FactSet, derived from the same single call, never re-resolved
    # independently per fact.
    actual_basis = "STANDALONE" if parsed.get("basis_used") == "standalone" else "CONSOLIDATED"
    selection = StatementSelection(
        selected_basis=actual_basis, document_id=source_document, financial_year=fiscal_year,
        selection_reason=("No consolidated financial statements found in the Annual Report "
                           "for this fiscal year; using standalone (only basis genuinely present)."
                           if actual_basis == "STANDALONE" else
                           "Consolidated financial statements found and used."),
    )

    for fact_key, parsed_key in _DIRECT_FACT_MAP.items():
        facts[fact_key] = _wrap_fact(fact_key, parsed.get(parsed_key), sym, period, actual_basis,
                                      source_document, bs_page, pl_page)

    # `retained_earnings` is "exact" (a real Reserves-and-Surplus-style row)
    # or an "other_equity_proxy" fallback (Total Other Equity, used only
    # when the filing has no distinct Retained Earnings line) - the proxy
    # is a real, disclosed number, not fabricated, but it's a materially
    # different accounting concept (includes items like Securities Premium,
    # Capital Reserve, OCI that Retained Earnings itself excludes), so
    # ratios consuming it (Altman Z) should see NEEDS_REVIEW, not VERIFIED,
    # per spec's own status vocabulary for "legitimate extraction, but a
    # proxy/ambiguity exists".
    re_fact = facts.get("retained_earnings")
    if re_fact is not None and re_fact.value is not None and parsed.get("retained_earnings_basis") == "other_equity_proxy":
        facts["retained_earnings"] = CanonicalFact(
            fact_key="retained_earnings", value=re_fact.value, prior_value=re_fact.prior_value,
            unit=re_fact.unit, currency=re_fact.currency, period=re_fact.period,
            statement_basis=re_fact.statement_basis, company_identity=re_fact.company_identity,
            source_document=re_fact.source_document, source_page=re_fact.source_page,
            source_tag="retained_earnings(other_equity_proxy)", extraction_method=re_fact.extraction_method,
            status="NEEDS_REVIEW",
        )

    # Derived shared facts - computed once here, reused by every dependent
    # ratio, rather than each ratio deriving its own copy.
    try:
        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
    except Exception:
        debt = None
    if debt and debt.get("applicable"):
        facts["total_debt"] = CanonicalFact(
            fact_key="total_debt", value=debt.get("total_debt_cur"), prior_value=debt.get("total_debt_prior"),
            unit="INR_CRORE", currency="INR", period=period, statement_basis=actual_basis,
            company_identity=sym, source_document=source_document, source_page=bs_page,
            source_tag="_compute_total_debt", extraction_method="derived", status="VERIFIED",
        )
    else:
        facts["total_debt"] = CanonicalFact(
            fact_key="total_debt", value=None, prior_value=None, unit="INR_CRORE", currency="INR",
            period=period, statement_basis=actual_basis, company_identity=sym,
            source_document=source_document, source_page=bs_page, source_tag="_compute_total_debt",
            extraction_method="derived", status="NOT_DISCLOSED" if debt is None else "INSUFFICIENT_DATA",
        )

    pbt_fact, fc_fact = facts.get("pbt"), facts.get("finance_costs")
    if pbt_fact and fc_fact and pbt_fact.value is not None and fc_fact.value is not None:
        ebit_cur = pbt_fact.value + fc_fact.value
        ebit_prior = (pbt_fact.prior_value + fc_fact.prior_value) \
            if pbt_fact.prior_value is not None and fc_fact.prior_value is not None else None
        facts["ebit"] = CanonicalFact(
            fact_key="ebit", value=ebit_cur, prior_value=ebit_prior, unit="INR_CRORE", currency="INR",
            period=period, statement_basis=actual_basis, company_identity=sym,
            source_document=source_document, source_page=pl_page, source_tag="pbt+finance_costs",
            extraction_method="derived", status="VERIFIED",
        )
        dep_fact = facts.get("depreciation")
        if dep_fact and dep_fact.value is not None:
            ebitda_cur = ebit_cur + dep_fact.value
            ebitda_prior = (ebit_prior + dep_fact.prior_value) \
                if ebit_prior is not None and dep_fact.prior_value is not None else None
            facts["ebitda"] = CanonicalFact(
                fact_key="ebitda", value=ebitda_cur, prior_value=ebitda_prior, unit="INR_CRORE",
                currency="INR", period=period, statement_basis=actual_basis, company_identity=sym,
                source_document=source_document, source_page=pl_page, source_tag="ebit+depreciation",
                extraction_method="derived", status="VERIFIED",
            )

    # COGS / Gross Profit / Purchases - reuse the EXACT formulas already
    # used identically (independently) by ~11 different `fetch_X_from_
    # annual_report` functions in this file: `cogs_cur = sum(v[0] for v in
    # components.values())` (Inventory Turnover, Gross Profit Margin, etc.)
    # and Payables Turnover's own documented a+b/fallback Purchases rule
    # (spec §9.3). Computed ONCE here instead of duplicated per ratio.
    # `components` is a dict of (cur, prior) pairs for Schedule III's COGS
    # line items ("Cost of materials consumed", "Purchases of stock-in-
    # trade", "Changes in inventories") - already extracted once as part of
    # the SAME `parsed` object, not a new PDF search.
    components = parsed.get("components") or {}
    if components:
        cogs_cur = sum(v[0] for v in components.values())
        cogs_prior = sum(v[1] for v in components.values() if len(v) > 1 and v[1] is not None) \
            if all(len(v) > 1 and v[1] is not None for v in components.values()) else None
        facts["cogs"] = _derived("cogs", round(cogs_cur, 2), round(cogs_prior, 2) if cogs_prior is not None else None,
                                  "INR_CRORE", pl_page, "sum(components)", period, actual_basis, sym, source_document)

        revenue_fact = facts.get("revenue")
        if revenue_fact is not None and revenue_fact.value is not None:
            gp_cur = revenue_fact.value - cogs_cur
            gp_prior = (revenue_fact.prior_value - cogs_prior) \
                if revenue_fact.prior_value is not None and cogs_prior is not None else None
            facts["gross_profit"] = _derived("gross_profit", round(gp_cur, 2),
                                              round(gp_prior, 2) if gp_prior is not None else None,
                                              "INR_CRORE", pl_page, "revenue-cogs", period, actual_basis,
                                              sym, source_document)

        # Purchases (spec §9.3): prefer a) Cost of materials consumed + b)
        # Purchases of stock-in-trade (summing whichever is present - a
        # pure trading business legitimately has only (b), a real ₹0 for
        # (a), not missing data); fall back to COGS - (Opening Inventory -
        # Closing Inventory) only when neither a nor b is disclosed at all.
        cogs_a, cogs_b = components.get("Cost of materials consumed"), components.get("Purchases of stock-in-trade")
        inv_fact = facts.get("inventory")
        purchases_cur = None
        purchases_tag = None
        if cogs_a is not None or cogs_b is not None:
            purchases_cur = (cogs_a[0] if cogs_a is not None else 0.0) + (cogs_b[0] if cogs_b is not None else 0.0)
            purchases_tag = "cost_of_materials+purchases_of_stock_in_trade"
        elif inv_fact is not None and inv_fact.value is not None and inv_fact.prior_value is not None:
            purchases_cur = cogs_cur - (inv_fact.prior_value - inv_fact.value)
            purchases_tag = "cogs-(opening_inventory-closing_inventory)"
        if purchases_cur is not None and purchases_cur > 0:
            facts["purchases"] = _derived("purchases", round(purchases_cur, 2), None, "INR_CRORE", pl_page,
                                           purchases_tag, period, actual_basis, sym, source_document)

    ta_fact, eqf_fact = facts.get("total_assets"), facts.get("equity_full")
    tl_cur, tl_prior = _pair(ta_fact, eqf_fact, lambda a, b: a - b)
    if tl_cur is not None:
        facts["total_liabilities"] = _derived("total_liabilities", tl_cur, tl_prior, "INR_CRORE", bs_page,
                                               "total_assets-equity_full", period, actual_basis, sym, source_document)

    _add_simple_derived_facts(facts, period, actual_basis, sym, source_document, bs_page, pl_page)

    result = FactSet(symbol=sym, fiscal_year=fiscal_year, selection=selection, facts=facts)
    with _lock:
        _run_cache[key] = result
    return result


def _derived(fact_key, value, prior_value, unit, page, source_tag, period, basis, sym, source_document, status="VERIFIED"):
    return CanonicalFact(
        fact_key=fact_key, value=value, prior_value=prior_value, unit=unit, currency="INR",
        period=period, statement_basis=basis, company_identity=sym, source_document=source_document,
        source_page=page, source_tag=source_tag, extraction_method="derived", status=status,
    )


def _pair(fact_a, fact_b, op):
    """Applies `op(a, b)` to current values (and, if both have a prior,
    to prior values too) - returns (cur, prior), leaving prior=None rather
    than guessing whenever either side lacks one. Returns (None, None) if
    either current value is missing (never silently substitutes 0)."""
    if fact_a is None or fact_b is None or fact_a.value is None or fact_b.value is None:
        return None, None
    cur = op(fact_a.value, fact_b.value)
    prior = op(fact_a.prior_value, fact_b.prior_value) \
        if fact_a.prior_value is not None and fact_b.prior_value is not None else None
    return cur, prior


def _add_simple_derived_facts(facts, period, basis, sym, source_document, bs_page, pl_page):
    """Shared derived facts computed ONCE here (spec §4/§11) so ratios that
    both need e.g. Working Capital never each derive their own copy.
    Skips (leaves unset) any derived fact whose inputs aren't available -
    a downstream ratio consuming a missing derived fact gets that fact's
    absence as NOT_DISCLOSED/INSUFFICIENT_DATA, never a fabricated 0."""
    tca, tcl = facts.get("total_current_assets"), facts.get("total_current_liabilities")
    wc_cur, wc_prior = _pair(tca, tcl, lambda a, b: a - b)
    if wc_cur is not None:
        facts["working_capital"] = _derived("working_capital", wc_cur, wc_prior, "INR_CRORE", bs_page,
                                             "total_current_assets-total_current_liabilities",
                                             period, basis, sym, source_document)

    ta = facts.get("total_assets")
    ce_cur, ce_prior = _pair(ta, tcl, lambda a, b: a - b)
    if ce_cur is not None:
        facts["capital_employed"] = _derived("capital_employed", ce_cur, ce_prior, "INR_CRORE", bs_page,
                                              "total_assets-total_current_liabilities",
                                              period, basis, sym, source_document)

    debt, cash = facts.get("total_debt"), facts.get("cash")
    nd_cur, nd_prior = _pair(debt, cash, lambda a, b: a - b)
    if nd_cur is not None:
        facts["net_debt"] = _derived("net_debt", nd_cur, nd_prior, "INR_CRORE", bs_page,
                                      "total_debt-cash", period, basis, sym, source_document)

    ppe, intang = facts.get("capex_ppe_purchase"), facts.get("capex_intangible_purchase")
    if ppe is not None and ppe.value is not None:
        capex_cur = ppe.value + (intang.value if intang and intang.value is not None else 0.0)
        facts["capex"] = _derived("capex", capex_cur, None, "INR_CRORE", pl_page,
                                   "capex_ppe_purchase+capex_intangible_purchase",
                                   period, basis, sym, source_document)

        ocf = facts.get("operating_cash_flow")
        if ocf is not None and ocf.value is not None:
            facts["fcf"] = _derived("fcf", ocf.value - capex_cur, None, "INR_CRORE", pl_page,
                                     "operating_cash_flow-capex", period, basis, sym, source_document)

    ebit, tax_exp, pbt = facts.get("ebit"), facts.get("tax_expense"), facts.get("pbt")
    if tax_exp is not None and pbt is not None and tax_exp.value is not None \
            and pbt.value not in (None, 0):
        tax_rate_cur = tax_exp.value / pbt.value
        facts["tax_rate"] = _derived("tax_rate", tax_rate_cur, None, "RATIO", pl_page,
                                      "tax_expense/pbt", period, basis, sym, source_document)
        if ebit is not None and ebit.value is not None:
            nopat_cur = ebit.value * (1 - tax_rate_cur)
            facts["nopat"] = _derived("nopat", nopat_cur, None, "INR_CRORE", pl_page,
                                       "ebit*(1-tax_rate)", period, basis, sym, source_document)

    debt, equity_o, cash2 = facts.get("total_debt"), facts.get("equity"), facts.get("cash")
    if debt is not None and equity_o is not None and cash2 is not None \
            and debt.value is not None and equity_o.value is not None and cash2.value is not None:
        facts["invested_capital"] = _derived("invested_capital", debt.value + equity_o.value - cash2.value,
                                              None, "INR_CRORE", bs_page, "total_debt+equity-cash",
                                              period, basis, sym, source_document)

    equity, shares = facts.get("equity"), facts.get("shares_outstanding")
    if equity is not None and shares is not None and equity.value is not None \
            and shares.value not in (None, 0):
        # `equity` is INR_CRORE, `shares_outstanding` is an ABSOLUTE share
        # count - dividing them directly (both "just numbers") would be
        # exactly the unit-mismatch bug the spec warns against (₹ crore ÷
        # absolute units). Scale equity to absolute INR first (×1e7) so the
        # result is genuinely ₹-per-share, not off by 10,000,000x.
        bvps_cur = (equity.value * 1e7) / shares.value
        facts["bvps"] = _derived("bvps", bvps_cur, None, "INR_PER_SHARE", bs_page,
                                  "(equity*1e7)/shares_outstanding", period, basis, sym, source_document)


def clear_run_cache():
    """Call between independent runs (e.g. the precompute worker moving to
    the next symbol) so memoized facts never leak across companies."""
    with _lock:
        _run_cache.clear()


# --------------------------------------------------------------------------- #
# Phase-2 gap (documented, not yet implemented - see spec §21/§13): neither
# `EXTRACTION_VERSION` above nor `db_ratio_reader.ratio_values` currently
# have a version column. If `_DIRECT_FACT_MAP`, `_compute_total_debt`, or
# `_get_extracted_financials`'s own parsing logic changes, existing
# Supabase `ratio_values` rows computed under the OLD logic are NOT
# automatically invalidated - they'll keep being served until their normal
# TTL/staleness check expires. The required fix: add a `extraction_version
# smallint` column to `ratio_values` (and this module's `EXTRACTION_VERSION`
# constant becomes the value written on every insert), then `try_db_ratio`
# filters `.eq("extraction_version", EXTRACTION_VERSION)` alongside its
# existing `consolidated` filter - so a version bump here makes every older
# row a transparent cache miss instead of requiring a manual purge. Not
# implemented in this pass; flagging it explicitly rather than silently
# leaving stale post-change results being served.
# --------------------------------------------------------------------------- #
