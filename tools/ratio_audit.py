"""
Bulk ratio audit — runs every Annual-Report/NSE-sourced ratio endpoint's
underlying fetch_X function for ONE company, in-process (no self-HTTP
round trips), and returns a uniform verdict per ratio: did it produce a
usable value, and if not, why.

Built for an external "check every stock x every ratio" audit automation
(n8n): instead of that automation making 54+ separate HTTP calls per
stock — and having to re-derive "was this successful" logic once per
ratio itself — it makes ONE call to /api/v1/ratio-audit/{symbol} and gets
a ready-made array back.

IMPORTANT — a real inconsistency this module deliberately sidesteps
rather than silently papering over: two DIFFERENT numbered "Sr No" ratio
specs exist in this codebase and they don't agree with each other.
Compare tools/precompute_worker.py's RATIO_FETCHERS list (Sr 24 = EPS,
Sr 25 = Book Value per Share, Sr 26 = Revenue from Operations) against
frontend/src/main.jsx's RATIO_ITEMS card list (Sr 24 = Price-to-Earnings,
Sr 25 = Price-to-Book, Sr 26 = Price-to-Sales) — same numbers, different
ratios. Forcing this audit's rows into either numbering risks silently
mislabeling one of them. Instead, each row is identified by its actual
API endpoint slug and the `ratio_name` the fetch function itself reports
in its response — unambiguous, and traceable straight back to the code
that computed it. Reconciling the two Sr-No schemes is a separate,
worthwhile cleanup this audit's existence doesn't depend on.

Covers every /api/v1/* endpoint in app.py that wraps a single
Annual-Report/NSE-sourced ratio (54 of them, verified against app.py's
own route bodies) — excludes report generation, chat, PDF download, and
business-evolution/concall endpoints (not single ratios), and
income-statement-flow (a multi-node chart, not one ratio value).
"""

import tools.nse_xbrl as _x

# (endpoint slug, fetch function name in tools.nse_xbrl) — extracted
# directly from app.py's own route bodies, not retyped by hand, so this
# can't silently drift out of sync with which function an endpoint
# actually calls.
RATIO_ENDPOINTS = [
    ("inventory-turnover", "fetch_inventory_turnover"),
    ("receivables-turnover", "fetch_receivables_turnover"),
    ("payables-turnover", "fetch_payables_turnover"),
    ("asset-turnover", "fetch_asset_turnover"),
    ("fixed-asset-turnover", "fetch_fixed_asset_turnover"),
    ("working-capital-turnover", "fetch_working_capital_turnover"),
    ("days-working-capital", "fetch_days_working_capital"),
    ("receivables-to-payables-ratio", "fetch_receivables_to_payables_ratio"),
    ("net-debt-to-ebitda", "fetch_net_debt_to_ebitda"),
    ("debt-service-coverage-ratio", "fetch_debt_service_coverage_ratio"),
    ("cash-flow-coverage-ratio", "fetch_cash_flow_coverage_ratio"),
    ("free-cash-flow", "fetch_free_cash_flow"),
    ("fcf-margin", "fetch_fcf_margin"),
    ("operating-cash-flow-ratio", "fetch_operating_cash_flow_ratio"),
    ("capex-intensity", "fetch_capex_intensity"),
    ("ocf-to-net-profit", "fetch_ocf_to_net_profit"),
    ("roic", "fetch_roic"),
    ("effective-tax-rate", "fetch_effective_tax_rate"),
    ("contribution-margin", "fetch_contribution_margin"),
    ("eps-growth", "fetch_eps_growth"),
    ("dividend-payout-ratio", "fetch_dividend_payout_ratio"),
    ("operating-cash-flow", "fetch_operating_cash_flow"),
    ("altman-z-score-components", "fetch_altman_z_score_components"),
    ("piotroski-f-score", "fetch_piotroski_f_score"),
    ("beneish-m-score", "fetch_beneish_m_score"),
    ("net-interest-margin", "fetch_net_interest_margin"),
    ("casa-ratio", "fetch_casa_ratio"),
    ("gross-npa-pct", "fetch_gross_npa_pct"),
    ("net-npa-pct", "fetch_net_npa_pct"),
    ("capital-adequacy-ratio", "fetch_capital_adequacy_ratio"),
    ("cost-to-income-ratio", "fetch_cost_to_income_ratio"),
    ("beta", "fetch_beta"),
    ("promoter-pledge-pct", "fetch_promoter_pledge_pct"),
    ("free-float-pct", "fetch_free_float_pct"),
    ("current-ratio", "fetch_current_ratio"),
    ("quick-ratio", "fetch_quick_ratio"),
    ("cash-ratio", "fetch_cash_ratio"),
    ("gross-profit-margin", "fetch_gross_profit_margin"),
    ("operating-profit-margin", "fetch_operating_profit_margin"),
    ("net-profit-margin", "fetch_net_profit_margin"),
    ("return-on-equity", "fetch_return_on_equity"),
    ("return-on-capital-employed", "fetch_return_on_capital_employed"),
    ("debt-to-equity", "fetch_debt_to_equity"),
    ("debt-ratio", "fetch_debt_ratio"),
    ("interest-coverage-ratio", "fetch_interest_coverage_ratio"),
    ("financial-leverage-ratio", "fetch_financial_leverage_ratio"),
    ("eps", "fetch_eps"),
    ("book-value-per-share", "fetch_book_value_per_share"),
    ("shares-outstanding", "fetch_shares_outstanding"),
    ("revenue-from-operations", "fetch_revenue_from_operations"),
    ("dividend-per-share", "fetch_dividend_per_share"),
    ("ebitda", "fetch_ebitda"),
    ("total-debt", "fetch_total_debt"),
    ("cash-and-equivalents", "fetch_cash_and_equivalents"),
]


def _title_from_slug(slug):
    return slug.replace("-", " ").title()


def audit_one(symbol, name=None):
    """Runs every ratio in RATIO_ENDPOINTS for one company, using the
    LIVE "latest year" path (same as a user's default view — no to_date
    passed, so this reads Supabase's fast-path first when a row exists,
    falling through to a live PDF parse otherwise). Returns a list of
    {endpoint, ratio_name, successful, reason, value} dicts, one per
    ratio, in RATIO_ENDPOINTS order. Never raises — a single ratio's
    exception is captured as that row's own failure reason instead of
    aborting the rest of the audit for this company."""
    out = []
    for slug, fn_name in RATIO_ENDPOINTS:
        fn = getattr(_x, fn_name, None)
        if fn is None:
            out.append({
                "endpoint": slug, "ratio_name": _title_from_slug(slug),
                "successful": False,
                "reason": f"Fetcher {fn_name} not found in tools.nse_xbrl (code drift — endpoint and audit map are out of sync).",
                "value": None,
            })
            continue
        try:
            r = fn(symbol, name=name) or {}
        except Exception as e:
            out.append({
                "endpoint": slug, "ratio_name": _title_from_slug(slug),
                "successful": False, "reason": f"Exception: {e}", "value": None,
            })
            continue
        applicable = bool(r.get("applicable"))
        value = r.get("value")
        successful = applicable and value is not None
        reason = None
        if not successful:
            reason = r.get("reason") or (
                "Marked applicable but no value was returned — likely a code bug, not a genuine N/A."
                if applicable else "Not applicable for this company (no reason string was given)."
            )
        out.append({
            "endpoint": slug,
            "ratio_name": r.get("ratio_name") or _title_from_slug(slug),
            "successful": successful,
            "reason": reason,
            "value": value,
        })
    return out
