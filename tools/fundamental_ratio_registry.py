"""
The authoritative 68-ratio Fundamental framework, transcribed verbatim
from "Ratio_Sheet_V8_patched 2.xls", sheet "Ratios", rows 1-68 (Sr No,
Ratio, Formula columns) - the single source of truth for both the
document-analysis orchestrator (tools/document_analysis_engine.py) and
the frontend's category grouping.

`strategy`:
  "A" - call the named tools.nse_xbrl fetch_* function (already builds
        current/prior-year pairing, lease-basis toggle, consolidated
        priority; already guarded for tools/manual_mode.py's manual
        document-analysis workflow via the fetch_filings/
        list_annual_report_years/try_db_ratio patches).
  "B" - derived locally from other ratios already computed earlier in the
        SAME run (never re-searches the Annual Report for a value another
        ratio already resolved).
  "C" - computed locally in the orchestrator from tools.document_
        analysis_engine.extract_line_items()'s alias-extracted raw facts
        (+ tools.market_price.get_live_price() for the market-price
        component, kept strictly separate from financial-statement facts).

`bank_only`: True for Sr 58-65 - computed only when
tools.sector_ratio_applicability.is_bank_ratio_applicable() is True for
the resolved sector; written status='not_applicable' otherwise, without
ever calling the fetcher.
"""

RATIOS = [
    {"sr_no": 1, "ratio_key": "inventory_turnover", "label": "Inventory Turnover", "category": "P&L + Balance Sheet",
     "formula": "Cost of Goods Sold ÷ Average Inventory", "strategy": "A", "nse_xbrl_fn": "fetch_inventory_turnover"},
    {"sr_no": 2, "ratio_key": "days_inventory_outstanding", "label": "Inventory Days", "display_priority": 1, "category": "P&L + Balance Sheet",
     "formula": "365 ÷ Inventory Turnover", "strategy": "B", "depends_on": [1]},
    {"sr_no": 3, "ratio_key": "receivables_turnover", "label": "Receivables Turnover", "category": "P&L + Balance Sheet",
     "formula": "Net Credit Sales ÷ Average Accounts Receivable", "strategy": "A", "nse_xbrl_fn": "fetch_receivables_turnover"},
    {"sr_no": 4, "ratio_key": "days_sales_outstanding", "label": "Debtor Days", "display_priority": 2, "category": "P&L + Balance Sheet",
     "formula": "365 ÷ Receivables Turnover", "strategy": "B", "depends_on": [3]},
    {"sr_no": 5, "ratio_key": "payables_turnover", "label": "Payables Turnover", "category": "P&L + Balance Sheet",
     "formula": "Net Purchases ÷ Average Accounts Payable", "strategy": "A", "nse_xbrl_fn": "fetch_payables_turnover"},
    {"sr_no": 6, "ratio_key": "days_payables_outstanding", "label": "Days Payable", "display_priority": 3, "category": "P&L + Balance Sheet",
     "formula": "365 ÷ Payables Turnover", "strategy": "B", "depends_on": [5]},
    {"sr_no": 7, "ratio_key": "asset_turnover", "label": "Asset Turnover", "category": "P&L + Balance Sheet",
     "formula": "Net Sales ÷ Average Total Assets", "strategy": "A", "nse_xbrl_fn": "fetch_asset_turnover"},
    {"sr_no": 8, "ratio_key": "working_capital_turnover", "label": "Working Capital Turnover", "category": "P&L + Balance Sheet",
     "formula": "Net Sales ÷ Average Working Capital (Current Assets − Current Liabilities)", "strategy": "A", "nse_xbrl_fn": "fetch_working_capital_turnover"},
    {"sr_no": 9, "ratio_key": "cash_conversion_cycle", "label": "Cash Conversion Cycle", "display_priority": 4, "category": "P&L + Balance Sheet",
     "formula": "DSO + DOH − DPO", "strategy": "B", "depends_on": [4, 2, 6]},
    {"sr_no": 10, "ratio_key": "current_ratio", "label": "Current Ratio", "category": "Balance Sheet",
     "formula": "Current Assets ÷ Current Liabilities", "strategy": "A", "nse_xbrl_fn": "fetch_current_ratio"},
    {"sr_no": 11, "ratio_key": "quick_ratio", "label": "Quick Ratio", "category": "Balance Sheet",
     "formula": "(Current Assets − Inventory) ÷ Current Liabilities", "strategy": "A", "nse_xbrl_fn": "fetch_quick_ratio"},
    {"sr_no": 12, "ratio_key": "cash_ratio", "label": "Cash Ratio", "category": "Balance Sheet",
     "formula": "(Cash + Cash Equivalents) ÷ Current Liabilities", "strategy": "A", "nse_xbrl_fn": "fetch_cash_ratio"},
    {"sr_no": 13, "ratio_key": "working_capital", "label": "Working Capital", "category": "Balance Sheet",
     "formula": "Current Assets − Current Liabilities", "strategy": "C"},
    {"sr_no": 14, "ratio_key": "gross_profit_margin", "label": "Gross Profit Margin", "category": "P&L",
     "formula": "Gross Profit ÷ Revenue", "strategy": "A", "nse_xbrl_fn": "fetch_gross_profit_margin"},
    {"sr_no": 15, "ratio_key": "operating_profit_margin", "label": "EBIT Margin %", "display_priority": 5, "category": "P&L",
     "formula": "Operating Profit (EBIT) ÷ Revenue", "strategy": "A", "nse_xbrl_fn": "fetch_operating_profit_margin"},
    {"sr_no": 16, "ratio_key": "net_profit_margin", "label": "Net Profit Margin", "category": "P&L",
     "formula": "Net Income ÷ Revenue", "strategy": "A", "nse_xbrl_fn": "fetch_net_profit_margin"},
    {"sr_no": 17, "ratio_key": "roa", "label": "Return on Assets (ROA)", "category": "P&L + Balance Sheet",
     "formula": "Net Income ÷ Average Total Assets", "strategy": "C"},
    {"sr_no": 18, "ratio_key": "roe", "label": "ROE %", "display_priority": 6, "category": "P&L + Balance Sheet",
     "formula": "Net Income ÷ Average Shareholders' Equity", "strategy": "A", "nse_xbrl_fn": "fetch_return_on_equity"},
    {"sr_no": 19, "ratio_key": "roce", "label": "ROCE %", "display_priority": 7, "category": "P&L + Balance Sheet",
     "formula": "EBIT ÷ Average Capital Employed", "strategy": "A", "nse_xbrl_fn": "fetch_return_on_capital_employed"},
    {"sr_no": 20, "ratio_key": "debt_to_equity", "label": "Debt-to-Equity Ratio", "category": "Balance Sheet",
     "formula": "Total Debt ÷ Total Equity (incl. NCI)", "strategy": "A", "nse_xbrl_fn": "fetch_debt_to_equity"},
    {"sr_no": 21, "ratio_key": "debt_ratio", "label": "Debt Ratio", "category": "Balance Sheet",
     "formula": "Total Debt ÷ Total Assets", "strategy": "A", "nse_xbrl_fn": "fetch_debt_ratio"},
    {"sr_no": 22, "ratio_key": "interest_coverage_ratio", "label": "Interest Coverage Ratio", "category": "P&L",
     "formula": "EBIT ÷ Interest Expense", "strategy": "A", "nse_xbrl_fn": "fetch_interest_coverage_ratio"},
    {"sr_no": 23, "ratio_key": "financial_leverage_ratio", "label": "Financial Leverage Ratio", "category": "Balance Sheet",
     "formula": "Average Total Assets ÷ Average Total Equity (incl. NCI)", "strategy": "A", "nse_xbrl_fn": "fetch_financial_leverage_ratio"},
    {"sr_no": 24, "ratio_key": "pe_ratio", "label": "Stock P/E", "display_priority": 8, "category": "Market / Valuation",
     "formula": "Market Price per Share ÷ Basic EPS (owners)", "strategy": "C"},
    {"sr_no": 25, "ratio_key": "pb_ratio", "label": "Price-to-Book (P/B)", "category": "Market / Valuation",
     "formula": "Market Price per Share ÷ Book Value per Share", "strategy": "C"},
    {"sr_no": 26, "ratio_key": "ps_ratio", "label": "Price-to-Sales (P/S)", "category": "Market / Valuation",
     "formula": "Market Cap ÷ Total Revenue", "strategy": "C"},
    {"sr_no": 27, "ratio_key": "dividend_yield", "label": "Dividend Yield %", "display_priority": 9, "category": "Market / Valuation",
     "formula": "Dividend per Share ÷ Market Price per Share", "strategy": "C"},
    {"sr_no": 28, "ratio_key": "earnings_yield", "label": "Earnings Yield", "category": "Market / Valuation",
     "formula": "EPS ÷ Market Price per Share", "strategy": "B", "depends_on": [24]},
    {"sr_no": 29, "ratio_key": "ev_to_ebitda", "label": "Enterprise Value/EBITDA", "category": "Market / Valuation",
     "formula": "(Market Cap + Debt − Cash) ÷ EBITDA (EBIT + D&A)", "strategy": "C"},
    {"sr_no": 30, "ratio_key": "fixed_asset_turnover", "label": "Fixed Asset Turnover", "category": "P&L + Balance Sheet",
     "formula": "Net Sales ÷ Average Net Fixed Assets (PPE + ROU + CWIP + Intangibles)", "strategy": "A", "nse_xbrl_fn": "fetch_fixed_asset_turnover"},
    {"sr_no": 31, "ratio_key": "days_working_capital", "label": "Working Capital Days", "display_priority": 10, "category": "P&L + Balance Sheet",
     "formula": "(Average Working Capital ÷ Revenue) × 365", "strategy": "A", "nse_xbrl_fn": "fetch_days_working_capital"},
    {"sr_no": 32, "ratio_key": "receivables_to_payables", "label": "Receivables-to-Payables Ratio", "category": "Balance Sheet",
     "formula": "Trade Receivables ÷ Trade Payables", "strategy": "A", "nse_xbrl_fn": "fetch_receivables_to_payables_ratio"},
    {"sr_no": 33, "ratio_key": "net_debt_to_ebitda", "label": "Net Debt/EBITDA", "category": "P&L + Balance Sheet",
     "formula": "(Total Debt − Cash) ÷ EBITDA (EBIT + D&A)", "strategy": "A", "nse_xbrl_fn": "fetch_net_debt_to_ebitda"},
    {"sr_no": 34, "ratio_key": "dscr", "label": "Debt Service Coverage Ratio (DSCR)", "category": "Cash Flow",
     "formula": "Net Operating Income (EBITDA proxy) ÷ (Gross Principal Repayment + Interest Due)", "strategy": "A", "nse_xbrl_fn": "fetch_debt_service_coverage_ratio"},
    {"sr_no": 35, "ratio_key": "cash_flow_coverage_ratio", "label": "Cash Flow Coverage Ratio", "category": "Cash Flow",
     "formula": "Operating Cash Flow ÷ Total Debt", "strategy": "A", "nse_xbrl_fn": "fetch_cash_flow_coverage_ratio"},
    {"sr_no": 36, "ratio_key": "free_cash_flow", "label": "Free Cash Flow", "display_priority": 11, "category": "Cash Flow",
     "formula": "Operating Cash Flow − Capital Expenditure", "strategy": "A", "nse_xbrl_fn": "fetch_free_cash_flow"},
    {"sr_no": 37, "ratio_key": "fcf_yield", "label": "FCF Yield", "category": "Market / Valuation",
     "formula": "Free Cash Flow ÷ Market Capitalisation", "strategy": "C"},
    {"sr_no": 38, "ratio_key": "fcf_margin", "label": "FCF Margin", "category": "Cash Flow",
     "formula": "Free Cash Flow ÷ Revenue", "strategy": "A", "nse_xbrl_fn": "fetch_fcf_margin"},
    {"sr_no": 39, "ratio_key": "ocf_ratio", "label": "Operating Cash Flow Ratio", "category": "Cash Flow",
     "formula": "Operating Cash Flow ÷ Current Liabilities", "strategy": "A", "nse_xbrl_fn": "fetch_operating_cash_flow_ratio"},
    {"sr_no": 40, "ratio_key": "capex_intensity", "label": "Capex Intensity", "category": "Cash Flow",
     "formula": "Capital Expenditure ÷ Revenue", "strategy": "A", "nse_xbrl_fn": "fetch_capex_intensity"},
    {"sr_no": 41, "ratio_key": "ocf_to_net_profit", "label": "OCF/Net Profit", "category": "Cash Flow",
     "formula": "Operating Cash Flow ÷ Net Profit (whole entity)", "strategy": "A", "nse_xbrl_fn": "fetch_ocf_to_net_profit"},
    {"sr_no": 42, "ratio_key": "roic", "label": "Return on Invested Capital (ROIC)", "category": "P&L + Balance Sheet",
     "formula": "NOPAT ÷ Invested Capital", "strategy": "A", "nse_xbrl_fn": "fetch_roic"},
    {"sr_no": 43, "ratio_key": "effective_tax_rate", "label": "Tax %", "display_priority": 12, "category": "P&L",
     "formula": "Tax Expense ÷ Profit Before Tax", "strategy": "A", "nse_xbrl_fn": "fetch_effective_tax_rate"},
    {"sr_no": 44, "ratio_key": "contribution_margin", "label": "Contribution Margin", "category": "P&L",
     "formula": "(Revenue − Variable Costs) ÷ Revenue", "strategy": "A", "nse_xbrl_fn": "fetch_contribution_margin"},
    {"sr_no": 45, "ratio_key": "eps_growth_rate", "label": "EPS Growth Rate", "category": "P&L",
     "formula": "(Current Year EPS ÷ Prior Year EPS) − 1", "strategy": "A", "nse_xbrl_fn": "fetch_eps_growth"},
    {"sr_no": 46, "ratio_key": "bvps", "label": "Book Value per Share (BVPS)", "category": "Balance Sheet",
     "formula": "Total Equity ÷ Number of Equity Shares Outstanding", "strategy": "A", "nse_xbrl_fn": "fetch_book_value_per_share"},
    {"sr_no": 47, "ratio_key": "dividend_payout_ratio", "label": "Dividend Payout %", "display_priority": 13, "category": "Multi-source / Derived",
     "formula": "Dividends Paid to the Company's shareholders ÷ Net Profit (owners)", "strategy": "A", "nse_xbrl_fn": "fetch_dividend_payout_ratio"},
    {"sr_no": 48, "ratio_key": "retention_ratio", "label": "Retention Ratio", "category": "Multi-source / Derived",
     "formula": "1 − Dividend Payout Ratio", "strategy": "B", "depends_on": [47]},
    {"sr_no": 49, "ratio_key": "sustainable_growth_rate", "label": "Sustainable Growth Rate", "category": "Multi-source / Derived",
     "formula": "Return on Equity × Retention Ratio", "strategy": "B", "depends_on": [18, 48]},
    {"sr_no": 50, "ratio_key": "peg_ratio", "label": "PEG Ratio", "category": "Market / Valuation",
     "formula": "Price-to-Earnings ÷ EPS Growth Rate", "strategy": "B", "depends_on": [24, 45]},
    {"sr_no": 51, "ratio_key": "ev_to_sales", "label": "EV/Sales", "category": "Market / Valuation",
     "formula": "Enterprise Value (Mkt Cap + Debt − Cash) ÷ Revenue", "strategy": "B", "depends_on": [29]},
    {"sr_no": 52, "ratio_key": "ev_to_fcf", "label": "EV/FCF", "category": "Market / Valuation",
     "formula": "Enterprise Value (Mkt Cap + Debt − Cash) ÷ Free Cash Flow", "strategy": "B", "depends_on": [29, 36]},
    {"sr_no": 53, "ratio_key": "price_to_cash_flow", "label": "Price/Cash Flow", "category": "Market / Valuation",
     "formula": "Market Capitalisation ÷ Operating Cash Flow", "strategy": "C"},
    {"sr_no": 54, "ratio_key": "graham_number", "label": "Graham Number", "category": "Market / Valuation",
     "formula": "√(22.5 × EPS × Book Value per Share)", "strategy": "B", "depends_on": [24, 46]},
    {"sr_no": 55, "ratio_key": "altman_z_score", "label": "Altman Z-Score", "category": "Multi-source / Derived",
     "formula": "1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA)", "strategy": "A", "nse_xbrl_fn": "fetch_altman_z_score_components"},
    {"sr_no": 56, "ratio_key": "piotroski_f_score", "label": "Piotroski F-Score", "category": "Multi-source / Derived",
     "formula": "Sum of 9 binary fundamental-strength tests (0-9 scale)", "strategy": "A", "nse_xbrl_fn": "fetch_piotroski_f_score"},
    {"sr_no": 57, "ratio_key": "beneish_m_score", "label": "Beneish M-Score", "category": "Multi-source / Derived",
     "formula": "-4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI - 0.172·SGAI + 4.679·TATA - 0.327·LVGI", "strategy": "A", "nse_xbrl_fn": "fetch_beneish_m_score"},
    {"sr_no": 58, "ratio_key": "net_interest_margin", "label": "Net Interest Margin (NIM)", "category": "Banking-specific",
     "formula": "(Interest Income − Interest Expense) ÷ Average Interest-Earning Assets", "strategy": "A", "nse_xbrl_fn": "fetch_net_interest_margin", "bank_only": True},
    {"sr_no": 59, "ratio_key": "casa_ratio", "label": "CASA Ratio", "category": "Banking-specific",
     "formula": "(Current Account + Savings Account Deposits) ÷ Total Deposits", "strategy": "A", "nse_xbrl_fn": "fetch_casa_ratio", "bank_only": True},
    {"sr_no": 60, "ratio_key": "gross_npa_pct", "label": "Gross NPA %", "category": "Banking-specific",
     "formula": "Gross Non-Performing Assets ÷ Gross Advances", "strategy": "A", "nse_xbrl_fn": "fetch_gross_npa_pct", "bank_only": True},
    {"sr_no": 61, "ratio_key": "net_npa_pct", "label": "Net NPA %", "category": "Banking-specific",
     "formula": "Net Non-Performing Assets ÷ Net Advances", "strategy": "A", "nse_xbrl_fn": "fetch_net_npa_pct", "bank_only": True},
    {"sr_no": 62, "ratio_key": "provision_coverage_ratio", "label": "Provision Coverage Ratio (PCR)", "category": "Banking-specific",
     "formula": "Total Provisions Held ÷ Gross Non-Performing Assets", "strategy": "C", "bank_only": True},
    {"sr_no": 63, "ratio_key": "capital_adequacy_ratio", "label": "Capital Adequacy Ratio (CRAR)", "category": "Banking-specific",
     "formula": "(Tier I Capital + Tier II Capital) ÷ Risk-Weighted Assets", "strategy": "A", "nse_xbrl_fn": "fetch_capital_adequacy_ratio", "bank_only": True},
    {"sr_no": 64, "ratio_key": "credit_to_deposit_ratio", "label": "Credit-to-Deposit Ratio", "category": "Banking-specific",
     "formula": "Total Advances ÷ Total Deposits", "strategy": "C", "bank_only": True},
    {"sr_no": 65, "ratio_key": "cost_to_income_ratio", "label": "Cost-to-Income Ratio", "category": "Banking-specific",
     "formula": "Operating Expenses ÷ (Net Interest Income + Other Income)", "strategy": "A", "nse_xbrl_fn": "fetch_cost_to_income_ratio", "bank_only": True},
    {"sr_no": 66, "ratio_key": "beta", "label": "Beta", "category": "Market / Shareholding",
     "formula": "Covariance(Stock Returns, Market Returns) ÷ Variance(Market Returns)", "strategy": "A", "nse_xbrl_fn": "fetch_beta"},
    {"sr_no": 67, "ratio_key": "promoter_pledge_pct", "label": "Promoter Pledge %", "category": "Market / Shareholding",
     "formula": "Pledged Promoter Shares ÷ Total Promoter Shareholding", "strategy": "A", "nse_xbrl_fn": "fetch_promoter_pledge_pct"},
    {"sr_no": 68, "ratio_key": "free_float_pct", "label": "Free Float %", "category": "Market / Shareholding",
     "formula": "(Total Shares − Promoter Holding − Locked-in Shares) ÷ Total Shares", "strategy": "A", "nse_xbrl_fn": "fetch_free_float_pct"},
]

# The authoritative, mutually-exclusive 68-ratio classification (each ratio's
# "category" above is its ONLY group). CATEGORY_ORDER is the display order;
# the first DEFAULT_VISIBLE_CATEGORIES are shown on load, the rest sit behind
# "Show More Ratios". Within a category ratios are ordered by Sr No.
# --- display names / order (presentation only; internal ids - sr_no, ratio_key - never change) ---------------------
# The 13 ratios that have a Screener-comparable metric carry `display_priority` 1..13 and are shown FIRST, in that order,
# under Screener's terminology. They are ordinary Navrist ratios with Navrist's own calculations - only the label and the
# position differ. LEGACY_LABELS maps the labels they had before to their current ones so that rows / breakdown payloads
# saved earlier read consistently (see tools/ratio_display.py).
LEGACY_LABELS = {
    "Days Inventory Outstanding (DOH)": "Inventory Days",
    "Days Sales Outstanding (DSO)": "Debtor Days",
    "Days Payables Outstanding (DPO)": "Days Payable",
    "Operating Profit Margin (EBIT Basis)": "EBIT Margin %",
    "OPM %": "EBIT Margin %",
    "Return on Equity (ROE)": "ROE %",
    "Return on Capital Employed (ROCE)": "ROCE %",
    "Price-to-Earnings (P/E)": "Stock P/E",
    "Free Cash Flow (FCF)": "Free Cash Flow",
    "Dividend Payout Ratio": "Dividend Payout %",
}
PRIORITY_RATIOS = sorted((r for r in RATIOS if r.get("display_priority")), key=lambda r: r["display_priority"])
assert [r["display_priority"] for r in PRIORITY_RATIOS] == list(range(1, 14)), "display_priority must be exactly 1..13"
assert [r["sr_no"] for r in PRIORITY_RATIOS] == [2, 4, 6, 9, 15, 18, 19, 24, 27, 31, 36, 43, 47]


CATEGORY_ORDER = [
    "Balance Sheet", "P&L", "P&L + Balance Sheet", "Cash Flow", "Multi-source / Derived",
    "Market / Valuation", "Banking-specific", "Market / Shareholding",
]
DEFAULT_VISIBLE_CATEGORIES = ["Balance Sheet", "P&L"]

assert len(RATIOS) == 68, f"Fundamental framework must have exactly 68 ratios, has {len(RATIOS)}"
assert {r["category"] for r in RATIOS} == set(CATEGORY_ORDER), "every ratio must sit in exactly one CATEGORY_ORDER category"

# Compute order: every strategy-A/C ratio (raw facts) before any strategy-B
# (derived) ratio, and within strategy-B, in ascending Sr No - every
# depends_on always has a lower Sr No than its dependent in this table, so
# a single ascending pass over (strategy != 'B', then strategy == 'B') by
# Sr No always resolves dependencies before they're needed.
COMPUTE_ORDER = (
    [r["sr_no"] for r in RATIOS if r["strategy"] != "B"] +
    [r["sr_no"] for r in RATIOS if r["strategy"] == "B"]
)

BY_SR_NO = {r["sr_no"]: r for r in RATIOS}
BY_RATIO_KEY = {r["ratio_key"]: r for r in RATIOS}
