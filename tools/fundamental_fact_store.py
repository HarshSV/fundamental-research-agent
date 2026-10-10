"""
Canonical fact store (spec §6) - the authoritative "extract once, calculate
many" layer.

    DOCUMENT -> EXTRACT FACT ONCE -> CANONICAL FACT -> NORMALIZE -> STORE ->
    RATIOS CONSUME FACT.

Every ratio in every pipeline (document-analysis engine, the `nse_xbrl`
endpoints behind the dashboard, the canonical calculation engine) now reads
its inputs from the `FactSet` this module builds - never from a private
re-parse. A `FactSet` is derived from the ONE object that already is the
single-parse-per-(symbol, fiscal_year, basis) result,
`tools.annual_report_financials._get_extracted_financials(...)`, so Revenue,
PAT, Debt, Equity ... can never disagree on statement basis.

What a `CanonicalFact` carries (the Phase-1 data contract):
    value / prior_value (INR crore unless the unit says otherwise), unit,
    period, statement basis (CONSOLIDATED/STANDALONE), company, source
    document + page, which `parsed[]` key it came from (`source_tag`),
    extraction method, status, confidence, `estimated`, `perimeter`
    (owners / whole_entity / n/a), raw label and `warnings`.

NAVRIST POLICIES IMPLEMENTED HERE (each one fact, defined once):
  * EBIT    = PBT + Finance Costs (Other Income is INCLUDED).
    EBITDA  = EBIT + Depreciation/Amortisation/Impairment (so Other Income is
              included in BOTH - they can never disagree).
  * Total Debt = Borrowings (non-current + current + current maturities)
              + Lease Liabilities [basis1] + debt-like Other Financial
              Liabilities that pass the Three-Part Test (when evaluated).
              A lease line that was not extracted is UNKNOWN, never 0 - the
              fact is flagged `estimated` and says so.
  * Total Liabilities = the statement's own "Total Liabilities" subtotal;
              otherwise Total Assets - (Owners' Equity + NCI). Never
              Total Assets - Owners' Equity when NCI exists (that books NCI
              as a liability).
  * Net Fixed Assets = PPE + Right-of-use assets + Capital WIP + Intangible
              assets (goodwill, investments and deferred tax excluded).
  * Owners' vs whole-entity: `pat` is owners-attributable; `pat_total` is the
              whole-entity profit; `equity` is owners' equity; `equity_full`
              adds NCI. Each ratio's perimeter is declared in
              `tools.ratio_contract.SPEC`.
  * EPS for valuation = Basic EPS attributable to OWNERS (the "excluding NCI"
              line when the P&L prints two Basic EPS lines; otherwise the
              single printed Basic EPS, which is owners-attributable under
              Ind AS 33).
  * DPS      = interim/special dividend declared during the FY + final
              dividend recommended for the FY (text-evidenced); unavailable
              - never 0 - when nothing is found. Dividends PAID is the cash
              flow statement's Financing line.
  * Prior-year values are kept on every fact so "Average X" never needs a
    second extraction.
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, Tuple

from tools.statement_selector import select_statement_basis, StatementSelection

# Bump whenever `_DIRECT_FACT_MAP`, a derived-fact formula below, or the
# underlying `_get_extracted_financials`/`_compute_total_debt` extraction
# logic changes in a way that could change a previously-cached fact's value.
# Persisted alongside every `ratio_values` row (see db_ratio_reader.py).
# v2 cash-flow facts + derived working_capital/capital_employed/net_debt/...
# v3 retained_earnings, cogs/gross_profit/purchases/total_liabilities.
# v4 lt_borrowings.
# v5 inventory_turnover numerator = Net Sales; purchases prefer disclosed note line; WC turnover/days use closing WC (superseded 2026.10.8: both are average-WC).
# v6 2026-10 global remediation: owners EPS, dividends paid/DPS evidence, lease
#    liabilities, reported Total Liabilities, policy Net Fixed Assets, EBITDA =
#    EBIT + D&A, acquisition signals, perimeter-aware PAT/equity, provenance.
EXTRACTION_VERSION = 22


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
    extraction_method: str            # "annual_report_pdf" | "derived" | "document_text"
    status: str                       # "VERIFIED" | "NEEDS_REVIEW" | "NOT_DISCLOSED" | "INSUFFICIENT_DATA"
    confidence: Optional[float] = None
    estimated: bool = False
    perimeter: Optional[str] = None   # "owners" | "whole_entity" | None
    raw_label: Optional[str] = None
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FactSet:
    symbol: str
    fiscal_year: int
    selection: StatementSelection
    facts: Dict[str, Any] = field(default_factory=dict)
    # Non-numeric / structured by-products of the same single extraction
    # (component dicts, dividend/acquisition disclosures, notes) that ratios
    # such as Contribution Margin, Cash Ratio and the working-capital
    # acquisition guard need. Same provenance as `facts`.
    extras: Dict[str, Any] = field(default_factory=dict)

    def get(self, fact_key: str) -> Optional[CanonicalFact]:
        f = self.facts.get(fact_key)
        if f is None and fact_key == "net_sales":
            # Net sales = revenue from operations less excise duty. Where no excise duty is charged (or none was read) net sales IS the
            # reported revenue; the fallback keeps the two facts one number instead of inventing a second.
            f = self.facts.get("revenue")
        return f if isinstance(f, CanonicalFact) else None


# canonical_key -> parsed[] key. Every one of these lives on the SAME
# `parsed` dict, so reading N of them costs one extraction, not N.
_DIRECT_FACT_MAP = {
    "revenue": "revenue",
    "excise_duty": "excise_duty",       # expense line below 'Total income'; revenue is gross of it when present
    "pat": "pat",                       # owners-attributable
    "pat_total": "pat_total",           # whole-entity (owners + NCI), when printed
    "pbt": "pbt",
    "equity": "equity",                 # owners-attributable
    "equity_full": "equity_full",       # owners + NCI (as extracted)
    "nci": "non_controlling_interest",
    "retained_earnings": "retained_earnings",
    "total_assets": "total_assets",
    "total_current_assets": "total_current_assets",
    "total_current_liabilities": "total_current_liabilities",
    "cash": "cash",
    "other_bank_balances": "other_bank_balances",
    "inventory": "inventory",
    "receivables": "receivables",
    "payables": "payables",
    "ppe": "ppe",
    "rou_assets": "rou_assets",
    "cwip": "cwip",
    "intangibles": "intangibles",
    "goodwill": "goodwill",
    "net_fixed_assets_legacy": "net_fixed_assets",   # PPE-only parse; used only when no component was found
    "total_liabilities_reported": "total_liabilities",
    "shares_outstanding": "shares_outstanding",
    "eps_total": "eps",                 # Basic EPS as the FIRST printed line (may include NCI profit)
    "eps_owners": "eps_owners",         # Basic EPS "excluding NCI"/attributable to owners, when printed
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
    "lt_borrowings": "lt_borrowings",   # long-term borrowings only - the classic Piotroski leverage numerator
    "borrowings_repayment": "borrowings_repayment",
    "lease_repayment": "lease_repayment",
    "interest_paid": "interest_paid",
    "dividend_paid_cf": "dividend_paid",
}

_PER_SHARE_FACTS = {"eps_total", "eps_owners", "dividend_per_share", "eps", "dps"}
_ABSOLUTE_COUNT_FACTS = {"shares_outstanding"}
_PAGE_BS = {"total_assets", "total_current_assets", "total_current_liabilities", "equity", "equity_full",
            "cash", "other_bank_balances", "inventory", "receivables", "payables", "ppe", "rou_assets", "cwip",
            "intangibles", "goodwill", "net_fixed_assets_legacy", "shares_outstanding", "nci",
            "total_liabilities_reported", "retained_earnings"}
_OWNERS_PERIMETER = {"pat", "equity", "eps_owners", "eps_total"}

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


_PAGE_CF = {"operating_cash_flow", "capex_ppe_purchase", "capex_intangible_purchase", "capex_disposal_proceeds",
            "borrowings_repayment", "lease_repayment", "interest_paid", "dividend_paid_cf"}


def _wrap_fact(fact_key, raw, symbol, period, basis, source_document, bs_page, pl_page, cf_page=None) -> CanonicalFact:
    cur, prior = _split_pair(raw)
    status = "VERIFIED" if cur is not None else "NOT_DISCLOSED"
    page = bs_page if fact_key in _PAGE_BS else ((cf_page or pl_page) if fact_key in _PAGE_CF else pl_page)
    return CanonicalFact(
        fact_key=fact_key, value=cur, prior_value=prior, unit=_unit_for(fact_key),
        currency="INR", period=period, statement_basis=basis, company_identity=symbol,
        source_document=source_document, source_page=page, source_tag=fact_key,
        extraction_method="annual_report_pdf", status=status,
        perimeter="owners" if fact_key in _OWNERS_PERIMETER else None,
    )


def _replace(fact: CanonicalFact, **changes) -> CanonicalFact:
    return CanonicalFact(**{**fact.__dict__, **changes})


def get_canonical_facts(symbol, name, fiscal_year, lease_basis="basis1", consolidated=True) -> FactSet:
    """The one entry point ratios/qualitative evidence read shared financial
    facts from. Resolves statement basis, performs (or reuses) the single
    cached extraction for (symbol, fiscal_year, basis), and returns every
    canonical fact derived from that ONE parsed object.

    Memoized in-process for the lifetime of one run/request, keyed by
    (symbol, fiscal_year, lease_basis, consolidated) - see `clear_run_cache`.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    from tools.annual_report_financials import (_get_extracted_financials, _compute_total_debt,
                                                  _document_identity_tag, _EXTRACTION_LOGIC_VERSION)
    from tools.manual_mode import is_manual_mode
    # The memo key carries the document identity + extraction version + calling mode: a re-uploaded
    # document (same symbol/year slot), a logic change or the manual-vs-automatic pipeline must never
    # be served a FactSet built from a different document/logic by a long-running process.
    key = (sym, fiscal_year, lease_basis, bool(consolidated), bool(is_manual_mode()),
           _document_identity_tag(sym, fiscal_year), _EXTRACTION_LOGIC_VERSION, EXTRACTION_VERSION)
    with _lock:
        cached = _run_cache.get(key)
    if cached is not None:
        return cached

    period = f"FY{fiscal_year}"
    parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated=consolidated)

    facts: Dict[str, Any] = {}
    if not parsed or "error" in parsed:
        reason = (parsed or {}).get("error", "Annual Report not found or unreadable.")
        selection = StatementSelection(
            selected_basis="CONSOLIDATED" if consolidated else "STANDALONE",
            document_id=(parsed or {}).get("source_url"), financial_year=fiscal_year,
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
        result = FactSet(symbol=sym, fiscal_year=fiscal_year, selection=selection, facts=facts,
                         extras={"source_url": (parsed or {}).get("source_url"), "error": reason})
        with _lock:
            _run_cache[key] = result
        return result

    source_document = parsed.get("source_url")
    bs_page = parsed.get("bs_page")
    pl_page = parsed.get("pl_page")
    actual_basis = "STANDALONE" if parsed.get("basis_used") == "standalone" else "CONSOLIDATED"
    selection = StatementSelection(
        selected_basis=actual_basis, document_id=source_document, financial_year=fiscal_year,
        selection_reason=("No consolidated financial statements found in the Annual Report "
                           "for this fiscal year; using standalone (only basis genuinely present)."
                           if actual_basis == "STANDALONE" else
                           "Consolidated financial statements found and used."),
    )
    is_consolidated = actual_basis == "CONSOLIDATED"
    requested_basis = "CONSOLIDATED" if consolidated else "STANDALONE"
    basis_fallback = None
    if requested_basis != actual_basis:
        # a request for one basis must never be answered with the other WITHOUT saying so
        basis_fallback = (f"{requested_basis.capitalize()} statements were requested but the filing has no readable {requested_basis.lower()} "
                          f"statements; the {actual_basis.lower()} figures are returned and labelled {actual_basis.lower()}.")
        selection = StatementSelection(selected_basis=actual_basis, document_id=source_document, financial_year=fiscal_year,
                                       selection_reason=basis_fallback)

    for fact_key, parsed_key in _DIRECT_FACT_MAP.items():
        facts[fact_key] = _wrap_fact(fact_key, parsed.get(parsed_key), sym, period, actual_basis,
                                      source_document, bs_page, pl_page, parsed.get("cf_page"))

    def put(fact_key, value, prior, *, unit="INR_CRORE", tag, page=None, method="derived",
            status="VERIFIED", confidence=None, estimated=False, perimeter=None, label=None, warnings=()):
        facts[fact_key] = CanonicalFact(
            fact_key=fact_key, value=value, prior_value=prior, unit=unit, currency="INR", period=period,
            statement_basis=actual_basis, company_identity=sym, source_document=source_document,
            source_page=page, source_tag=tag, extraction_method=method,
            status=status if value is not None else ("NOT_DISCLOSED" if status == "VERIFIED" else status),
            confidence=confidence, estimated=estimated, perimeter=perimeter, raw_label=label,
            warnings=tuple(warnings))

    def missing(fact_key, tag, why, status="NOT_DISCLOSED", unit="INR_CRORE"):
        put(fact_key, None, None, unit=unit, tag=tag, status=status, warnings=(why,))

    # ---- NCI / perimeter -------------------------------------------------------------------
    nci = facts.get("nci")
    if is_consolidated and (nci is None or nci.value is None) and parsed.get("nci_evaluated") \
            and not (nci is not None and nci.status == "NEEDS_REVIEW"):
        # the owners'/NCI split IS printed and no NCI row exists: a genuine nil, not a missing value
        put("nci", 0.0, 0.0, tag="nci(absent from an owners/NCI split)", page=bs_page, method="annual_report_pdf",
            label="No Non-Controlling Interest line on the balance sheet")
        nci = facts.get("nci")
    integrity: list = []          # accounting-identity checks that FAILED - surfaced on every dependent fact/ratio
    _ta0, _tcl0, _eq0 = facts.get("total_assets"), facts.get("total_current_liabilities"), facts.get("equity")
    if is_consolidated and nci is not None and nci.value is not None and _ta0 is not None and _ta0.value \
            and _tcl0 is not None and _tcl0.value is not None and _eq0 is not None and _eq0.value is not None:
        # Total Assets = Equity(owners) + NCI + Non-current liabilities + Current liabilities, and non-current
        # liabilities cannot be negative => Owners' equity + NCI <= Total Assets - Current Liabilities.
        if _eq0.value + nci.value > (_ta0.value - _tcl0.value) * 1.005 + 1e-6:
            integrity.append(
                f"NCI ({nci.value:,.2f}) + owners' equity ({_eq0.value:,.2f}) exceeds Total Assets - Current Liabilities "
                f"({_ta0.value - _tcl0.value:,.2f}): impossible, so the extracted NCI is ignored (not trusted).")
            put("nci", None, None, tag="nci(rejected by balance-sheet identity)", page=bs_page, status="NEEDS_REVIEW",
                warnings=(integrity[-1],))
            nci = facts.get("nci")
    nci_val = nci.value if nci is not None else None
    nci_evaluated = (not is_consolidated) or nci_val is not None
    nci_material = bool(is_consolidated and nci_val and nci_val > 0)
    extras: Dict[str, Any] = {"nci_material": nci_material, "nci_evaluated": nci_evaluated,
                              "is_consolidated": is_consolidated, "integrity_failures": integrity,
                              "basis_requested": requested_basis.lower(), "basis_fallback": basis_fallback}

    # `retained_earnings` is "exact" or an "other_equity_proxy" (Total Other Equity, a real number
    # but a different accounting concept) - a proxy is NEEDS_REVIEW so Altman Z sees it.
    re_fact = facts.get("retained_earnings")
    if re_fact is not None and re_fact.value is not None and \
            parsed.get("retained_earnings_basis") in ("other_equity_proxy", "consolidated", "standalone"):
        facts["retained_earnings"] = _replace(
            re_fact, source_tag="retained_earnings(other_equity_proxy)", status="NEEDS_REVIEW", estimated=True,
            warnings=("Retained Earnings is proxied by 'Other Equity' (reserves incl. securities premium).",))

    # ---- whole-entity profit ----------------------------------------------------------------
    pat = facts.get("pat")
    pat_total = facts.get("pat_total")
    if pat_total is not None and pat_total.value is None:
        if pat is not None and pat.value is not None and not nci_material and nci_evaluated:
            put("pat_total", pat.value, pat.prior_value, tag="pat(no NCI)", page=pl_page, perimeter="whole_entity")
        elif pat is not None and pat.value is not None and parsed.get("pat_basis") != "owners":
            # no owners/NCI split printed: the single "Profit for the year" IS the whole-entity figure
            put("pat_total", pat.value, pat.prior_value, tag="pat(generic label)", page=pl_page,
                perimeter="whole_entity", estimated=True, status="NEEDS_REVIEW", confidence=0.8,
                warnings=("No owners/NCI profit split printed; 'Profit for the year' used as whole-entity profit.",))
        else:
            missing("pat_total", "pat_total", "Whole-entity profit (owners + NCI) was not found.")
    elif pat_total is not None:
        facts["pat_total"] = _replace(pat_total, perimeter="whole_entity")
    if pat is not None and pat.value is not None:
        if parsed.get("pat_basis") == "owners" or not is_consolidated or (nci_evaluated and not nci_material):
            facts["pat"] = _replace(pat, perimeter="owners")
        else:
            facts["pat"] = _replace(
                pat, perimeter="ambiguous", estimated=True, status="NEEDS_REVIEW", confidence=0.8,
                warnings=("Consolidated statement with NCI but no owners-attributable profit line was found - "
                          "'Profit for the year' may include NCI.",))

    # ---- equity perimeter -------------------------------------------------------------------
    eq = facts.get("equity")
    if eq is not None and eq.value is not None:
        eq_owners_confirmed = (parsed.get("equity_basis") == "owners" or not is_consolidated
                               or (nci_evaluated and not nci_material))
        if not eq_owners_confirmed:
            facts["equity"] = _replace(eq, perimeter="ambiguous", estimated=True, status="NEEDS_REVIEW",
                                       confidence=0.8, warnings=("Equity may include NCI (no separate owners' split found).",))
        else:
            facts["equity"] = _replace(eq, perimeter="owners")
        eq = facts["equity"]
        if nci_val is not None and is_consolidated:
            put("equity_full", eq.value + nci_val,
                (eq.prior_value + nci.prior_value) if eq.prior_value is not None and nci.prior_value is not None else None,
                tag="equity+nci", page=bs_page, perimeter="whole_entity")
        elif not is_consolidated or (nci_evaluated and not nci_material):
            put("equity_full", eq.value, eq.prior_value, tag="equity(no NCI)", page=bs_page, perimeter="whole_entity")
        else:
            put("equity_full", eq.value, eq.prior_value, tag="equity(NCI not evaluated)", page=bs_page,
                perimeter="whole_entity", estimated=True, status="NEEDS_REVIEW", confidence=0.8,
                warnings=("Non-controlling interest could not be read; whole-entity equity may be understated.",))
    else:
        missing("equity_full", "equity_full", "Total equity not found.")

    # ---- prior-year share count: the reconciliation table's opening balance ------------------
    _shf = facts.get("shares_outstanding")
    if _shf is not None and _shf.value is not None and _shf.prior_value is None and parsed.get("shares_opening"):
        facts["shares_outstanding"] = _replace(_shf, prior_value=parsed["shares_opening"],
                                               warnings=tuple(_shf.warnings) + (
                                                   "Prior-year shares = opening balance of the share reconciliation table.",))

    # ---- EPS (valuation basis = owners) -----------------------------------------------------
    e_own, e_tot = facts.get("eps_owners"), facts.get("eps_total")
    if e_own is not None and e_own.value is not None:
        put("eps", e_own.value, e_own.prior_value, unit="INR_PER_SHARE", tag="eps_owners", page=pl_page,
            method="annual_report_pdf", perimeter="owners", label="Basic EPS attributable to owners (excluding NCI)")
    elif e_tot is not None and e_tot.value is not None:
        warn, st, est = (), "VERIFIED", False
        pt, po = facts.get("pat_total"), facts.get("pat")
        if nci_material and pt is not None and po is not None and pt.value and po.value:
            sh = facts.get("shares_outstanding")
            implied_o = (po.value * 1e7 / sh.value) if sh is not None and sh.value else None
            implied_t = (pt.value * 1e7 / sh.value) if sh is not None and sh.value else None
            if implied_o and implied_t and abs(e_tot.value - implied_t) < abs(e_tot.value - implied_o):
                warn, st, est = (("The only printed Basic EPS tracks whole-entity profit (incl. NCI), not owners' "
                                  "profit - owners' EPS could not be read."),), "NEEDS_REVIEW", True
        put("eps", e_tot.value, e_tot.prior_value, unit="INR_PER_SHARE", tag="eps_total(ind_as_33_default)",
            page=pl_page, method="annual_report_pdf", perimeter="owners", status=st, estimated=est,
            confidence=0.8 if est else None, warnings=warn,
            label="Basic EPS (single printed line - owners-attributable under Ind AS 33)")
    else:
        missing("eps", "eps", "Basic EPS not found.", unit="INR_PER_SHARE")

    # ---- dividends --------------------------------------------------------------------------
    dd = parsed.get("dps_declared") or {}
    extras["dps_declared"] = dd or None
    dps_narrow = parsed.get("dividend_per_share")
    if dps_narrow is not None and parsed.get("dividend_per_share_found", True):
        put("dps", dps_narrow, None, unit="INR_PER_SHARE", tag="dividend_per_share(note)", page=pl_page,
            method="annual_report_pdf", label="DPS declared (interim + proposed final), Retained Earnings note")
    elif dd.get("found"):
        put("dps", dd["total"], None, unit="INR_PER_SHARE", tag="dps_declared(text)", method="document_text",
            page=(dd.get("pages") or [None])[0], label=dd.get("policy"),
            warnings=(f"interim={dd.get('interim')}, special={dd.get('special')}, final(recommended)={dd.get('final')}",))
    elif dd.get("no_dividend_evidence"):
        put("dps", 0.0, None, unit="INR_PER_SHARE", tag="no_dividend_statement", method="document_text",
            confidence=0.9, label="Explicit statement that no dividend was recommended/declared")
    else:
        missing("dps", "dps", "No dividend-per-share disclosure was found - the dividend is UNKNOWN, not zero.",
                unit="INR_PER_SHARE")
    paid = facts.get("dividend_paid_cf")
    comp = parsed.get("dividend_components") or {}
    if paid is not None and paid.value is not None:
        total, total_prior = abs(paid.value), (abs(paid.prior_value) if paid.prior_value is not None else None)
        # Dividends PAID must sit on the same perimeter as the owners' PAT it is divided by: the cash-flow line is the WHOLE-ENTITY
        # total (parent's dividends to its shareholders + subsidiaries' dividends to their minorities). Split it by recipient.
        nci_d = comp.get("nci") or {}
        nci_cur = nci_d.get("cur")
        cands = [c for c in (comp.get("owners_candidates") or []) if c.get("cur") is not None and c["cur"] <= total * 1.005 + 0.01]
        owners_c = None
        if cands:
            if nci_cur is not None:
                fit = [c for c in cands if abs(c["cur"] + nci_cur - total) <= 0.01 * total + 0.01]
                owners_c = fit[0] if fit else None
            if owners_c is None:
                vals = [round(c["cur"], 2) for c in cands]
                best = max(set(vals), key=vals.count)
                owners_c = next(c for c in cands if round(c["cur"], 2) == best)
        extras["dividend_components"] = {"total_cashflow_cr": total, "owners_cr": owners_c["cur"] if owners_c else None,
                                         "nci_cr": nci_cur, "owners_page": owners_c["page"] if owners_c else None,
                                         "nci_page": nci_d.get("page"),
                                         "reconciles": (owners_c is not None and nci_cur is not None
                                                        and abs(owners_c["cur"] + nci_cur - total) <= 0.01 * total + 0.01)}
        if owners_c is not None:
            note = ("Dividends paid to the company's own shareholders (reserves / equity-statement note)"
                    + (f"; the cash-flow total ({total:,.2f} Cr) = owners {owners_c['cur']:,.2f} + minorities {nci_cur:,.2f}"
                       if extras["dividend_components"]["reconciles"] else
                       f"; the cash-flow total ({total:,.2f} Cr) also includes {max(total - owners_c['cur'], 0):,.2f} Cr paid to others"
                       if total - owners_c["cur"] > 0.01 * total + 0.01 else ""))
            put("dividends_paid", owners_c["cur"], owners_c["prior"] if owners_c.get("prior") is not None else None,
                tag="dividend_paid(owners; equity-statement note)", page=owners_c["page"], method="annual_report_pdf",
                perimeter="owners", label=note)
        elif nci_cur is not None and total - nci_cur >= 0:
            put("dividends_paid", total - nci_cur, None, tag="dividend_paid(cash flow - NCI share)", page=paid.source_page,
                method="derived", perimeter="owners",
                label=f"Cash-flow dividends paid ({total:,.2f} Cr) less the minorities' share ({nci_cur:,.2f} Cr)")
        else:
            w, est = (), False
            if nci_material:
                w = ("Consolidated cash dividends can include amounts paid to NCI holders of subsidiaries and the owners' "
                     "share could not be separated: the payout may be overstated.",)
                est = True
            put("dividends_paid", total, total_prior,
                tag="dividend_paid(cash flow)", page=paid.source_page, method="annual_report_pdf", perimeter="whole_entity",
                estimated=est, status="NEEDS_REVIEW" if est else "VERIFIED", confidence=0.8 if est else None, warnings=w,
                label="Dividend paid (Financing Activities)")
    elif dd.get("no_dividend_evidence"):
        put("dividends_paid", 0.0, None, tag="no_dividend_statement", method="document_text", confidence=0.9,
            label="Explicit statement that no dividend was declared/paid")
    else:
        missing("dividends_paid", "dividend_paid",
                "No 'Dividend paid' line was found in the cash flow statement - dividends paid are UNKNOWN, not zero.")

    # ---- debt (ONE definition) --------------------------------------------------------------
    try:
        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
    except Exception:
        debt = None
    if debt and debt.get("applicable"):
        lw = ()
        if debt.get("lease_status") == "not_found":
            lw = ("Lease liabilities were not found on the balance sheet and nothing proves there are none - "
                  "Total Debt may be understated.",)
        put("total_debt", debt.get("total_debt_cur"), debt.get("total_debt_prior"), tag="_compute_total_debt",
            page=bs_page, status="NEEDS_REVIEW" if debt.get("estimated") else "VERIFIED",
            confidence=debt.get("confidence"), estimated=bool(debt.get("estimated")), warnings=lw)
        extras["debt_components"] = debt.get("components")
        extras["debt_components_raw"] = debt.get("components_raw")
        extras["debt_note"] = debt.get("note")
        extras["lease_status"] = debt.get("lease_status")
    else:
        put("total_debt", None, None, tag="_compute_total_debt", page=bs_page,
            status="NOT_DISCLOSED" if debt is None else "INSUFFICIENT_DATA",
            warnings=((debt or {}).get("reason") or "Total debt could not be determined.",))
        extras["debt_reason"] = (debt or {}).get("reason")

    _debt_chk, _ta_chk = facts.get("total_debt"), facts.get("total_assets")
    if _debt_chk is not None and _debt_chk.value is not None and _ta_chk is not None and _ta_chk.value \
            and _debt_chk.value > _ta_chk.value:
        msg = (f"Total Debt ({_debt_chk.value:,.2f}) exceeds Total Assets ({_ta_chk.value:,.2f}) - impossible for a "
               "balance sheet that balances; the borrowings extraction is suspect (e.g. double-counted sub-items).")
        integrity.append(msg)
        facts["total_debt"] = _replace(_debt_chk, estimated=True, status="NEEDS_REVIEW", confidence=0.4,
                                       warnings=tuple(_debt_chk.warnings) + (msg,))

    _eps_c, _sh_c, _pat_c = facts.get("eps"), facts.get("shares_outstanding"), facts.get("pat")
    if _eps_c is not None and _eps_c.value is not None and _sh_c is not None and _sh_c.value \
            and _pat_c is not None and _pat_c.value is not None:
        implied = _eps_c.value * _sh_c.value / 1e7
        if abs(implied) > 1.0 and abs(_pat_c.value - implied) > 0.35 * abs(implied):
            msg = (f"Owners' profit ({_pat_c.value:,.2f} Cr) disagrees with Basic EPS x shares outstanding "
                   f"({implied:,.2f} Cr) by more than 35% - the profit/EPS/share-count extraction is inconsistent.")
            integrity.append(msg)
            facts["pat"] = _replace(_pat_c, estimated=True, status="NEEDS_REVIEW", confidence=0.4,
                                    warnings=tuple(_pat_c.warnings) + (msg,))

    # share count vs the count IMPLIED by owners' profit / Basic EPS (EPS uses weighted shares, so agreement is
    # within a few %): a count 15%+ away is an extraction error (authorised capital, wrong class of shares...) and
    # every per-share/market-cap ratio built on it must say so.
    _sh2, _eps2, _pat2 = facts.get("shares_outstanding"), facts.get("eps"), facts.get("pat")
    if _sh2 is not None and _sh2.value and _eps2 is not None and _eps2.value and _eps2.value > 0             and _pat2 is not None and _pat2.value and _pat2.value > 0:
        implied_sh = _pat2.value * 1e7 / _eps2.value
        if abs(_sh2.value - implied_sh) > 0.15 * implied_sh:
            msg = (f"Equity shares outstanding ({_sh2.value:,.0f}) disagree by more than 15% with the count implied by "
                   f"owners' profit / Basic EPS ({implied_sh:,.0f}) - the share-count extraction is suspect.")
            integrity.append(msg)
            facts["shares_outstanding"] = _replace(_sh2, estimated=True, status="NEEDS_REVIEW", confidence=0.5,
                                                   warnings=tuple(_sh2.warnings) + (msg,))

    # ---- EBIT / EBITDA (policy: other income included in both) -----------------------------
    pbt_fact, fc_fact, dep_fact = facts.get("pbt"), facts.get("finance_costs"), facts.get("depreciation")
    if pbt_fact and fc_fact and pbt_fact.value is not None and fc_fact.value is not None:
        ebit_cur = pbt_fact.value + fc_fact.value
        ebit_prior = (pbt_fact.prior_value + fc_fact.prior_value) \
            if pbt_fact.prior_value is not None and fc_fact.prior_value is not None else None
        put("ebit", ebit_cur, ebit_prior, tag="pbt+finance_costs", page=pl_page,
            label="EBIT = Profit Before Tax + Finance Costs (Other Income included)")
        if dep_fact and dep_fact.value is not None:
            put("ebitda", ebit_cur + dep_fact.value,
                (ebit_prior + dep_fact.prior_value) if ebit_prior is not None and dep_fact.prior_value is not None else None,
                tag="ebit+depreciation", page=pl_page,
                label="EBITDA = EBIT + Depreciation, Amortisation & Impairment (Other Income included)")
        else:
            missing("ebitda", "ebit+depreciation", "Depreciation & amortisation not found, so EBITDA cannot be built.")
    else:
        # services/telecom filers whose PBT row is not read: EBIT from Total Expenses (excludes other income)
        rev_f, te_f = facts.get("revenue"), facts.get("total_expenses")
        if rev_f and te_f and fc_fact and rev_f.value is not None and te_f.value is not None and fc_fact.value is not None:
            put("ebit", rev_f.value - te_f.value + fc_fact.value, None, tag="revenue-total_expenses+finance_costs",
                page=pl_page, status="NEEDS_REVIEW", estimated=True, confidence=0.8,
                warnings=("EBIT rebuilt from Total Expenses: Other Income is NOT included on this path.",))
            if dep_fact and dep_fact.value is not None:
                put("ebitda", rev_f.value - te_f.value + fc_fact.value + dep_fact.value, None,
                    tag="revenue-total_expenses+finance_costs+depreciation", page=pl_page, status="NEEDS_REVIEW",
                    estimated=True, confidence=0.8,
                    warnings=("EBITDA rebuilt from Total Expenses: Other Income is NOT included on this path.",))
            else:
                missing("ebitda", "ebit+depreciation", "Depreciation & amortisation not found.")
        else:
            missing("ebit", "pbt+finance_costs", "Profit Before Tax / Finance Costs not found.")
            missing("ebitda", "ebit+depreciation", "EBIT unavailable.")

    # ---- Net sales (revenue from operations less excise duty) ---------------------------------
    _rev0, _ex0 = facts.get("revenue"), facts.get("excise_duty")
    if _rev0 is not None and _rev0.value is not None and _ex0 is not None and _ex0.value and 0 < _ex0.value < _rev0.value:
        put("net_sales", _rev0.value - _ex0.value,
            (_rev0.prior_value - _ex0.prior_value) if _rev0.prior_value is not None and _ex0.prior_value is not None else None,
            tag="revenue-excise_duty", page=pl_page,
            label="Net sales = Revenue from operations less Excise duty (excise is printed as an expense, so revenue is gross of it)")
    # ---- COGS / Gross Profit / Purchases ----------------------------------------------------
    components = parsed.get("components") or {}
    extras["components"] = components
    revenue_fact = facts.get("net_sales") or facts.get("revenue")
    if components:
        cogs_cur = sum(v[0] for v in components.values())
        cogs_prior = sum(v[1] for v in components.values() if len(v) > 1 and v[1] is not None) \
            if all(len(v) > 1 and v[1] is not None for v in components.values()) else None
        put("cogs", cogs_cur, cogs_prior, tag="sum(components)", page=pl_page,
            confidence=None if len(components) >= 3 else 0.95)
        if revenue_fact is not None and revenue_fact.value is not None:
            put("gross_profit", revenue_fact.value - cogs_cur,
                (revenue_fact.prior_value - cogs_prior) if revenue_fact.prior_value is not None and cogs_prior is not None else None,
                tag="revenue-cogs", page=pl_page)
        else:
            missing("gross_profit", "revenue-cogs", "Revenue not found.")
        cogs_a, cogs_b = components.get("Cost of materials consumed"), components.get("Purchases of stock-in-trade")
        inv_fact = facts.get("inventory")
        disclosed = parsed.get("purchases_disclosed")
        extras["purchases_disclosed"] = disclosed
        pur_cur, pur_tag, pur_est, pur_conf, pur_w = None, None, False, None, ()
        if cogs_a is not None or cogs_b is not None:
            if cogs_a is None:
                a_val = 0.0
            elif disclosed and disclosed.get("cur") is not None:
                a_val = disclosed["cur"]
            else:
                a_val, pur_est, pur_conf = cogs_a[0], True, 0.8
                pur_w = ("Purchases proxied by Cost of Materials Consumed (opening stock + purchases - closing stock): "
                         "the note's 'Purchases during the year' line was not found.",)
            pur_cur = a_val + (cogs_b[0] if cogs_b is not None else 0.0)
            pur_tag = "+".join(t for t in (
                ("purchases_during_the_year" if cogs_a is not None and not pur_est else
                 "cost_of_materials_consumed(proxy)" if cogs_a is not None else ""),
                "purchases_of_stock_in_trade" if cogs_b is not None else "") if t)
        elif inv_fact is not None and inv_fact.value is not None and inv_fact.prior_value is not None:
            pur_cur = cogs_cur - (inv_fact.prior_value - inv_fact.value)
            pur_tag, pur_est, pur_conf = "cogs-(opening_inventory-closing_inventory)", True, 0.8
            pur_w = ("Purchases derived as COGS - inventory movement (approximation, no direct purchases split).",)
        if pur_cur is not None and pur_cur > 0:
            put("purchases", pur_cur, None, tag=pur_tag, page=pl_page, estimated=pur_est,
                status="NEEDS_REVIEW" if pur_est else "VERIFIED", confidence=pur_conf, warnings=pur_w)
        else:
            missing("purchases", "components", "Purchases could not be determined.")
    else:
        for k in ("cogs", "gross_profit", "purchases"):
            missing(k, "components", "No Cost of Goods Sold line items were found (not a goods business, or not extracted).")

    # ---- balance-sheet derived: liabilities, working capital, capital employed, fixed assets ---
    ta, tcl, tca = facts.get("total_assets"), facts.get("total_current_liabilities"), facts.get("total_current_assets")
    tl_rep = facts.get("total_liabilities_reported")
    eqf = facts.get("equity_full")
    def _tl_plausible(v, tol=0.0):
        """Total liabilities must lie in [Total Current Liabilities, Total Assets): TL = non-current + current."""
        if ta is None or ta.value is None or v is None:
            return True
        if v < 0 or v >= ta.value * (1 + tol) * 0.9999:
            return False
        return not (tcl is not None and tcl.value is not None and v < tcl.value * 0.995)

    tl_ok = None
    if tl_rep is not None and tl_rep.value is not None:
        identity_ok = True
        if ta is not None and ta.value and eqf is not None and eqf.value is not None and not eqf.estimated:
            identity_ok = abs((tl_rep.value + eqf.value) - ta.value) <= 0.025 * ta.value
        if _tl_plausible(tl_rep.value) and identity_ok:
            tl_ok = tl_rep
        else:
            integrity.append(
                f"Reported 'Total Liabilities' ({tl_rep.value:,.2f}) fails the balance-sheet identity "
                f"(Total Liabilities + Total Equity = Total Assets {ta.value if ta is not None else None}) - it is probably the "
                "'Total Equity and Liabilities' grand total, so it is not used.")
    if tl_ok is not None:
        put("total_liabilities", tl_ok.value, tl_ok.prior_value, tag="total_liabilities(reported)", page=bs_page,
            method="annual_report_pdf")
    elif ta is not None and ta.value is not None and eqf is not None and eqf.value is not None:
        est = eqf.estimated
        derived = ta.value - eqf.value
        if not _tl_plausible(derived):
            integrity.append(f"Derived Total Liabilities ({derived:,.2f}) is impossible (must be between Current Liabilities and "
                             "Total Assets) - the equity/NCI extraction is suspect.")
            missing("total_liabilities", "total_liabilities", integrity[-1], status="INSUFFICIENT_DATA")
        else:
            put("total_liabilities", derived,
                (ta.prior_value - eqf.prior_value) if ta.prior_value is not None and eqf.prior_value is not None else None,
                tag="total_assets-(owners_equity+nci)", page=bs_page, estimated=est,
                status="NEEDS_REVIEW" if est else "VERIFIED", confidence=0.8 if est else None,
                warnings=("Total Liabilities not printed; derived as Total Assets - (Owners' Equity + NCI)."
                          + (" NCI could not be read, so NCI may be counted as a liability." if est else ""),))
    else:
        missing("total_liabilities", "total_liabilities", "Total liabilities not found.")

    wc_cur, wc_prior = _pair(tca, tcl, lambda a, b: a - b)
    if wc_cur is not None:
        put("working_capital", wc_cur, wc_prior, tag="total_current_assets-total_current_liabilities", page=bs_page)
    else:
        missing("working_capital", "total_current_assets-total_current_liabilities", "Current assets/liabilities not found.")
    ce_cur, ce_prior = _pair(ta, tcl, lambda a, b: a - b)
    if ce_cur is not None:
        put("capital_employed", ce_cur, ce_prior, tag="total_assets-total_current_liabilities", page=bs_page)
    else:
        missing("capital_employed", "total_assets-total_current_liabilities", "Total assets/current liabilities not found.")

    comp_keys = ("ppe", "rou_assets", "cwip", "intangibles")
    comps = {k: facts.get(k) for k in comp_keys}
    if comps["ppe"] is not None and comps["ppe"].value is not None:
        cur = sum(f.value for f in comps.values() if f is not None and f.value is not None)
        prior_ok = all(f is None or f.value is None or f.prior_value is not None for f in comps.values())
        prior = sum(f.prior_value for f in comps.values() if f is not None and f.value is not None) if prior_ok else None
        absent = [k for k, f in comps.items() if f is None or f.value is None]
        put("net_fixed_assets", cur, prior, tag="ppe+rou_assets+cwip+intangibles", page=bs_page,
            warnings=((f"Components not on the balance sheet face / not found (treated as absent): {', '.join(absent)}",)
                      if absent else ()))
        extras["nfa_components"] = {k: (f.value if f is not None else None) for k, f in comps.items()}
    elif facts.get("net_fixed_assets_legacy") is not None and facts["net_fixed_assets_legacy"].value is not None:
        lg = facts["net_fixed_assets_legacy"]
        put("net_fixed_assets", lg.value, lg.prior_value, tag="net_fixed_assets(PPE-only legacy parse)", page=bs_page,
            estimated=True, status="NEEDS_REVIEW", confidence=0.8,
            warnings=("Only a PPE-only net fixed asset line was found; ROU assets / Capital WIP / intangibles not read.",))
    else:
        missing("net_fixed_assets", "ppe+rou_assets+cwip+intangibles", "Property, plant & equipment not found.")

    # ---- cash, net debt, invested capital, NOPAT, tax rate ----------------------------------
    cash = facts.get("cash")
    debt_f = facts.get("total_debt")
    nd_cur, nd_prior = _pair(debt_f, cash, lambda a, b: a - b)
    if nd_cur is not None:
        put("net_debt", nd_cur, nd_prior, tag="total_debt-cash", page=bs_page,
            estimated=debt_f.estimated, status="NEEDS_REVIEW" if debt_f.estimated else "VERIFIED",
            confidence=debt_f.confidence)
    else:
        missing("net_debt", "total_debt-cash", "Total debt or cash unavailable.")
    if debt_f is not None and debt_f.value is not None and eqf is not None and eqf.value is not None \
            and cash is not None and cash.value is not None:
        ic_prior = None
        if debt_f.prior_value is not None and eqf.prior_value is not None and cash.prior_value is not None:
            ic_prior = debt_f.prior_value + eqf.prior_value - cash.prior_value
        est = debt_f.estimated or eqf.estimated
        put("invested_capital", debt_f.value + eqf.value - cash.value, ic_prior,
            tag="total_debt+total_equity(incl_nci)-cash", page=bs_page, perimeter="whole_entity", estimated=est,
            status="NEEDS_REVIEW" if est else "VERIFIED",
            confidence=min(c for c in (debt_f.confidence, eqf.confidence, 1.0) if c is not None) if est else None)
    else:
        missing("invested_capital", "total_debt+total_equity-cash", "Debt, equity or cash unavailable.")
    tax_exp, pbt = facts.get("tax_expense"), facts.get("pbt")
    ebit = facts.get("ebit")
    if tax_exp is not None and pbt is not None and tax_exp.value is not None and pbt.value not in (None, 0):
        rate = tax_exp.value / pbt.value
        put("tax_rate", rate, None, unit="RATIO", tag="tax_expense/pbt", page=pl_page)
        if ebit is not None and ebit.value is not None:
            put("nopat", ebit.value * (1 - rate), None, tag="ebit*(1-tax_rate)", page=pl_page,
                estimated=ebit.estimated, status="NEEDS_REVIEW" if ebit.estimated else "VERIFIED")
        else:
            missing("nopat", "ebit*(1-tax_rate)", "EBIT unavailable.")
    else:
        missing("tax_rate", "tax_expense/pbt", "Tax expense / PBT unavailable or PBT is zero.", unit="RATIO")
        missing("nopat", "ebit*(1-tax_rate)", "Tax rate unavailable.")

    # ---- capex / FCF ------------------------------------------------------------------------
    ppe_cx, int_cx = facts.get("capex_ppe_purchase"), facts.get("capex_intangible_purchase")
    ocf = facts.get("operating_cash_flow")
    if ppe_cx is not None and ppe_cx.value is not None:
        capex_cur = abs(ppe_cx.value) + (abs(int_cx.value) if int_cx is not None and int_cx.value is not None else 0.0)
        _no_int = int_cx is None or int_cx.value is None
        put("capex", capex_cur, None, tag="capex_ppe_purchase+capex_intangible_purchase", page=parsed.get("cf_page") or pl_page,
            label="Gross capital expenditure (cash flow statement, no disposal proceeds netted)",
            warnings=(("No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil "
                       "(the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).",)
                      if _no_int else ()))
        if ocf is not None and ocf.value is not None:
            put("fcf", ocf.value - capex_cur, None, tag="operating_cash_flow-capex", page=parsed.get("cf_page") or pl_page)
        else:
            missing("fcf", "operating_cash_flow-capex", "Operating cash flow not found.")
    else:
        missing("capex", "capex", "Capital expenditure line not found in the cash flow statement.")
        missing("fcf", "operating_cash_flow-capex", "Capital expenditure unavailable.")

    # ---- BVPS (the ONE authoritative book value per share) ----------------------------------
    equity, shares = facts.get("equity"), facts.get("shares_outstanding")
    if equity is not None and shares is not None and equity.value is not None and shares.value not in (None, 0):
        sh_prior = shares.prior_value
        put("bvps", (equity.value * 1e7) / shares.value,
            (equity.prior_value * 1e7 / sh_prior) if equity.prior_value is not None and sh_prior else None,
            unit="INR_PER_SHARE", tag="(owners_equity*1e7)/shares_outstanding", page=bs_page,
            estimated=(equity.estimated or shares.estimated),
            status="NEEDS_REVIEW" if (equity.estimated or shares.estimated) else "VERIFIED",
            confidence=min([c for c in (equity.confidence, shares.confidence) if c is not None], default=None),
            perimeter="owners", warnings=tuple(dict.fromkeys(tuple(equity.warnings) + tuple(shares.warnings))))
    else:
        missing("bvps", "(equity*1e7)/shares_outstanding", "Owners' equity or share count not found.", unit="INR_PER_SHARE")

    # ---- acquisition-distortion detector (generic; never adjusts a number) ------------------
    gw, sig = facts.get("goodwill"), parsed.get("acquisition_signals") or {}
    reasons = []
    if ta is not None and ta.value and gw is not None and gw.value is not None and gw.prior_value is not None:
        d_gw = gw.value - gw.prior_value
        if d_gw > 0.03 * ta.value:
            reasons.append(f"Goodwill rose by {d_gw:,.0f} Cr ({d_gw / ta.value:.0%} of total assets)")
    if ta is not None and ta.value and ta.prior_value and (sig.get("hits") or 0) > 0 \
            and ta.value / ta.prior_value - 1 > 0.30:
        reasons.append(f"Total assets grew {ta.value / ta.prior_value - 1:.0%} with business-combination disclosures present")
    if nci is not None and nci.value is not None and nci.prior_value is not None and ta is not None and ta.value \
            and (nci.value - nci.prior_value) > 0.08 * ta.value:
        reasons.append("Non-controlling interest rose sharply (part-year consolidation of a subsidiary)")
    extras["acquisition"] = {"flag": bool(reasons), "reasons": reasons, "text_hits": sig.get("hits"),
                             "text_pages": sig.get("pages")}
    _bk = parsed.get("other_bank_balances_breakup")
    if (_bk is None or _bk.get("unrestricted_cur") is None) and parsed.get("obb_note"):
        _bk = parsed["obb_note"]                    # the note itself classifies the lines; the face has no sub-items to test
    extras["other_bank_balances_breakup"] = _bk
    extras["variable_opex_note"] = parsed.get("variable_opex_note")
    extras["direct_expenses"] = parsed.get("direct_expenses")
    extras["lease_evidence"] = parsed.get("lease_evidence")
    extras["pat_basis"] = parsed.get("pat_basis")
    extras["equity_basis"] = parsed.get("equity_basis")
    extras["source_url"] = source_document
    extras["bs_page"], extras["pl_page"] = bs_page, pl_page
    extras["basis_used"] = parsed.get("basis_used")

    _apply_ledger_integrity(facts, integrity)
    result = FactSet(symbol=sym, fiscal_year=fiscal_year, selection=selection, facts=facts, extras=extras)
    with _lock:
        _run_cache[key] = result
    return result


def _flag(facts, keys, msg, confidence=0.5):
    for k in keys:
        f = facts.get(k)
        if isinstance(f, CanonicalFact) and f.value is not None and msg not in f.warnings:
            facts[k] = _replace(f, estimated=True, status="NEEDS_REVIEW",
                                confidence=min(confidence, f.confidence) if f.confidence is not None else confidence,
                                warnings=tuple(f.warnings) + (msg,))


def _apply_ledger_integrity(facts, integrity):
    """Accounting identities that hold in ANY filing, applied to the extracted facts as a whole. A text extractor can misread
    a row (whole-entity profit taken as owners', a subtotal taken as NCI, authorised capital taken as shares...); the
    identities below catch that without knowing the company. A failure never changes a number - it marks every fact involved
    needs_review (with the reason) so every ratio built on it inherits that status instead of presenting a suspect figure as
    verified. Run over 133 real filings (tests/universe_scan.py) these identities isolate the defects.

      eps_pat       owners' profit ~ Basic EPS x shares (within 12%)
      bs_identity   Total liabilities + Total equity (incl. NCI) ~ Total assets (within 1.5%)
      nci_bounds    0 <= NCI <= Total equity incl. NCI
      pat_vs_total  owners' profit <= whole-entity profit
    """
    def v(k):
        f = facts.get(k)
        return f.value if isinstance(f, CanonicalFact) else None
    pat, eps, sh = v("pat"), v("eps"), v("shares_outstanding")
    if pat and eps and sh:
        implied = eps * sh / 1e7
        if abs(implied) > 0.05 and abs(implied - pat) > 0.12 * abs(pat):
            msg = (f"Owners' profit ({pat:,.2f} Cr) and Basic EPS x shares outstanding ({implied:,.2f} Cr) differ by more than "
                   "12%: the profit perimeter (continuing vs total, owners vs whole entity), the EPS basis or the share count is "
                   "inconsistent.")
            integrity.append(msg)
            _flag(facts, ("pat", "eps", "shares_outstanding"), msg)
    ta, tl, ef = v("total_assets"), v("total_liabilities"), v("equity_full")
    if ta and tl is not None and ef is not None and abs(tl + ef - ta) > 0.015 * ta:
        msg = (f"Balance-sheet identity fails: Total liabilities ({tl:,.2f}) + Total equity incl. NCI ({ef:,.2f}) != Total assets "
               f"({ta:,.2f}) - one of the three was misread.")
        integrity.append(msg)
        _flag(facts, ("total_assets", "total_liabilities", "equity_full", "equity"), msg)
    nci = v("nci")
    if nci is not None and ef is not None and (nci < -0.5 or nci > ef + 0.5):
        msg = f"Non-controlling interest ({nci:,.2f}) lies outside 0..Total equity ({ef:,.2f}) - it was misread."
        integrity.append(msg)
        _flag(facts, ("nci", "equity_full"), msg)
    pt = v("pat_total")
    if pat is not None and pt is not None and pt > 0 and pat > pt + max(1.0, 0.002 * abs(pt)):
        msg = f"Owners' profit ({pat:,.2f}) exceeds whole-entity profit ({pt:,.2f}) - the profit perimeter was misread."
        integrity.append(msg)
        _flag(facts, ("pat", "pat_total"), msg)
    # current-section identities (every Schedule III / Ind AS balance sheet): the current subtotal can never be smaller than
    # the lines inside it, nor larger than the statement total. A row reader that took a note number, a page number or the
    # wrong column as the subtotal fails these without knowing anything about the company.
    tca, tcl = v("total_current_assets"), v("total_current_liabilities")
    inv, rec, csh, pay = v("inventory"), v("receivables"), v("cash"), v("payables")
    if tca is not None:
        inside = sum(x for x in (inv, rec, csh) if x is not None and x > 0)
        if (ta and tca > ta * 1.005) or (inside and tca < inside * 0.995):
            msg = (f"Total current assets ({tca:,.2f}) is inconsistent with the lines inside it (inventory + receivables + cash = "
                   f"{inside:,.2f}) or exceeds Total assets ({(ta or 0):,.2f}) - the subtotal was misread.")
            integrity.append(msg)
            _flag(facts, ("total_current_assets", "inventory", "receivables", "cash"), msg)
    if tcl is not None:
        ceiling = tl if tl else ta
        if (pay is not None and pay > 0 and tcl < pay * 0.995) or (ceiling and tcl > ceiling * 1.005):
            msg = (f"Total current liabilities ({tcl:,.2f}) is smaller than the trade payables inside it ({(pay or 0):,.2f}) or larger "
                   f"than Total liabilities/assets ({(ceiling or 0):,.2f}) - the subtotal was misread.")
            integrity.append(msg)
            _flag(facts, ("total_current_liabilities", "payables"), msg)
    rev, pt2 = v("revenue"), v("pat_total") if v("pat_total") is not None else pat
    if rev is not None and pt2 is not None and rev > 0 and abs(pt2) > 20 * rev:
        msg = (f"Revenue ({rev:,.2f}) is under 5% of profit ({pt2:,.2f}) - a statement figure or its unit was misread (a pure "
               "investment holding company is the only legitimate case).")
        integrity.append(msg)
        _flag(facts, ("revenue", "pat", "pat_total"), msg)


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


def _derived(fact_key, value, prior_value, unit, page, source_tag, period, basis, sym, source_document, status="VERIFIED"):
    return CanonicalFact(
        fact_key=fact_key, value=value, prior_value=prior_value, unit=unit, currency="INR",
        period=period, statement_basis=basis, company_identity=sym, source_document=source_document,
        source_page=page, source_tag=source_tag, extraction_method="derived", status=status,
    )


def clear_run_cache():
    """Call between independent runs (e.g. the precompute worker moving to
    the next symbol) so memoized facts never leak across companies."""
    with _lock:
        _run_cache.clear()


def factset_from_values(symbol, fiscal_year, basis, values, *, source_document, extras=None, source_label=None):
    """A FactSet built from figures a NON-Annual-Report source already read (e.g. an NSE XBRL result filing), so the ONE ratio
    contract computes the ratio from them instead of that source re-implementing the formula.

    `values` = {fact_key: (current, prior_or_None)} in Rs crore (per-share / count facts in their own unit); `basis` is
    'CONSOLIDATED' or 'STANDALONE'. Provenance (period, basis, source document) is stamped on every fact; nothing is derived
    or defaulted here - a fact that is not in `values` is simply absent (None)."""
    period = f"FY{fiscal_year}"
    selection = StatementSelection(selected_basis=basis, document_id=source_document, financial_year=fiscal_year,
                                   selection_reason=source_label or "Figures supplied by the NSE XBRL result filing.")
    facts = {}
    for fact_key, (cur, prior) in values.items():
        facts[fact_key] = CanonicalFact(
            fact_key=fact_key, value=cur, prior_value=prior, unit=_unit_for(fact_key), currency="INR", period=period,
            statement_basis=basis, company_identity=symbol, source_document=source_document, source_page=None,
            source_tag=fact_key, extraction_method="annual_report_pdf" if not source_label else "xbrl_filing",
            status="VERIFIED" if cur is not None else "NOT_DISCLOSED")
    return FactSet(symbol=symbol, fiscal_year=fiscal_year, selection=selection, facts=facts,
                   extras={"source_url": source_document, **(extras or {})})
