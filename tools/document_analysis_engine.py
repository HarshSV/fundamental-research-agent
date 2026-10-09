"""
Document Analysis engine - the NEW workflow behind Upload Documents -> Analyse.

This is deliberately NOT the old per-ratio fetching pipeline
(tools/nse_xbrl.py's ~40 fetch_* functions, tools/annual_report_financials.py's
exact-phrase parser) - that pipeline is tuned for a company-resolved, live
BSE/NSE lookup and its narrow phrase-matching is exactly why a manually
uploaded Annual Report kept coming back "Consolidated Statement of Profit
and Loss not found" / N/A. This module does its own broader, alias-rich
extraction directly over the uploaded Annual Report (+ optional XBRL) and
computes a fixed, standard set of Fundamental ratios from what it finds - 
generic across every company (CLAUDE.md), never a per-ticker rule.

Two independent halves:
 - Fundamental: extract_line_items() + compute_fundamental_ratios(), written
    to db/006_document_analysis.sql's fundamental_analysis_results table.
 - Qualitative: reuses the EXISTING A-U framework unchanged
    (tools/qualitative_engine.py's 185 already-implemented, non-LLM
    compute_fn's, selected via tools/qualitative_task_registry.py's
    batch_enabled flag) - this module only orchestrates calling them for
    one symbol; results land in the existing qualitative_values table via
    each compute_fn's own write_qualitative() call, so the existing
    read endpoints (/api/v1/qualitative/{symbol}) already serve them.
"""

import concurrent.futures
import threading
import importlib
import re

from tools.qualitative_task_registry import TASK_REGISTRY

_QUALITATIVE_WORKERS = 12  # Re-benchmarked (this session): 6 workers took 97.8s for
# TCS's 244 sub-points; 12 workers completed the same run in 60.6s (0 failed) -
# a ~38% wall-clock reduction users were explicitly waiting on. Re-tested
# against CIPLA specifically (the 465-page filing that originally drove
# this constant down to 6, per the history below) at 12 workers: 0 failed,
# 102.5s. 24 previously caused Windows socket-pool exhaustion (WinError
# 10035) on concurrent Supabase writes, silently failing some individual
# result persists even though the compute itself succeeded - confirmed
# real via a live run. 12, then 8, were each previously believed to be the
# highest concurrency that ran clean, but larger Annual Reports (e.g.
# CIPLA's 465-page filing) push far more simultaneous PDF-page/network
# reads through the pool at once, and at the time this was written, even
# 8 workers consistently exhausted sockets on CIPLA (one task failed after
# all 3 retries, every run) - lowered to 6 for headroom. Re-verified clean
# at 12 on the exact same CIPLA filing just now, so raised back up; if a
# future heavier filing (or higher concurrent user load) reproduces the
# original failure mode, lower this again rather than re-litigating from
# scratch - the retry/verification machinery below already surfaces a
# real failure honestly rather than silently miscounting it as success.
# These are never silently miscounted as successful (see `_run_one`'s
# persistence-verification retry loop
# below, which explicitly returns "failed" only after 3 verified-failed
# attempts), but fewer transient failures means fewer unnecessary
# recomputes on the next run.


# ---------------------------------------------------------------------------
# Fundamental: line-item extraction
# ---------------------------------------------------------------------------

# Canonical line item -> broad alias phrases (lowercase). Deliberately wide - 
# this is the fix for the old pipeline's single-exact-phrase failure mode.
# Generic across every company; no per-ticker wording.
_LINE_ITEM_ALIASES = {
    "revenue": ["revenue from operations", "revenue from operations (net)",
                "income from operations", "total revenue", "net sales", "turnover", "sales"],
    "cogs": ["cost of materials consumed", "cost of goods sold", "purchases of stock-in-trade",
             "cost of sales", "cost of revenue"],
    # The narrow "..._from_annual_report" functions (Contribution Margin,
    # Beneish M-Score) need the P&L's COGS sub-items SEPARATELY, not the
    # single combined "cogs" figure above - Schedule III shows these as
    # distinct line items, and a pure manufacturer often has only the
    # first with no "Purchases of stock-in-trade" line at all (real, not
    # missing data).
    "cost_of_materials_consumed": ["cost of materials consumed"],
    "purchases_of_stock_in_trade": ["purchases of stock-in-trade"],
    # Third COGS component (Schedule III's "a + b + c" - see _COGS_LABELS in
    # tools/annual_report_financials.py, the SAME three canonical components
    # Inventory Turnover/Gross Profit Margin/Contribution Margin's narrow
    # parser already validates). Was missing here entirely - confirmed real
    # bug on ANURAS: this module's manual-mode fallback path
    # (`_broad_extraction_to_parsed_shape` in annual_report_financials.py)
    # only ever summed materials-consumed + purchases-of-stock-in-trade,
    # silently OMITTING Changes in Inventories - Gross Profit Margin came
    # out as Revenue minus materials-consumed ALONE (34.80%, Gross Profit
    # Rs 500.05 Cr) instead of Revenue minus the full a+b+c COGS. A company
    # whose inventory grew during the year (a large negative "changes in
    # inventories" adjustment, as Ind AS presents it) has its true COGS -
    # and therefore Gross Profit - substantially understated/overstated by
    # this omission. Usually printed in parentheses (inventory increased ->
    # negative COGS adjustment) - the shared `_ALL_NUMS_RE`/sign handling
    # already used throughout this module handles that correctly.
    "changes_in_inventories": ["changes in inventories", "change in inventories", "changes in inventory",
                                "change in inventory", "changes in inventories of finished",
                                "increase/decrease in inventories", "movement in inventories",
                                # Trading-company Schedule III phrasing inserts "the" and names
                                # "Stock-in-Trade" explicitly instead of "finished goods/WIP" -
                                # confirmed real on Prime Fresh Limited ("Changes In The
                                # Inventories Of Stock In Trade"), a standard alternate caption
                                # for any trader/retailer, not unique to one filing.
                                "changes in the inventories of stock in trade",
                                "changes in the inventories of stock-in-trade",
                                "change in the inventories of stock in trade",
                                "changes in inventories of stock-in-trade",
                                "changes in inventories of stock in trade"],
    "ebitda": ["earnings before interest, tax, depreciation and amortisation", "ebitda"],
    "ebit": ["profit before interest and tax", "operating profit", "ebit"],
    "interest_expense": ["finance costs", "interest expense", "interest and finance charges",
                          "finance charges", "interest cost"],
    "pbt": ["profit before tax", "profit before share of profit / (loss) of associates / joint ventures and tax", "profit before share of profit of associates and joint ventures and tax", "profit before exceptional items and tax", "profit before extraordinary items and tax"],
    "tax": ["tax expense", "total tax expense", "provision for tax", "income tax expense"],
    # Owners-attributable phrasing is tried FIRST, matching the narrow
    # parser's own established `_PAT_OWNERS_LABELS`-before-`_PAT_GENERIC_
    # LABELS` priority (tools/annual_report_financials.py) - a CONSOLIDATED
    # statement with Non-Controlling Interest always ALSO prints a generic
    # "Profit after tax for the year" line for the TOTAL (owners + NCI)
    # figure, and the previous order tried that generic phrasing first,
    # locking onto the total before ever reaching the owners-only line.
    # Confirmed real on ANURAS: PAT resolved to Rs 159.97 Cr (total, incl.
    # NCI's Rs 66.62 Cr) instead of Rs 93.35 Cr (Net Profit attributable to
    # Owners of the company) - overstating Net Profit Margin (11.13% vs the
    # correct ~6.50%) and, since ROE's denominator is already the owners-
    # only equity figure, silently mixing a total-PAT numerator against an
    # owners-only-equity denominator (inflating ROE to 5.70% instead of an
    # internally consistent 3.33%). Falls back to the generic phrasing only
    # when no owners-specific line exists at all - correct for Standalone
    # filings, or a Consolidated filing with genuinely zero NCI, where
    # "profit for the year" already IS the owners' figure (no split to
    # begin with).
    "pat": ["profit attributable to owners", "profit attributable to equity holders",
            "net profit attributable to owners",
            "profit for the year", "profit after tax", "net profit", "profit for the period",
            "net income"],
    # TOTAL (pre-NCI-split) PAT - deliberately a SEPARATE key from "pat"
    # above, using ONLY the generic phrasing (never the owners-attributable
    # one), for the few consumers that specifically need the whole-entity
    # profit figure rather than the owners-only one "pat" now resolves to -
    # e.g. deriving Total Tax Expense as PBT - PAT when a filing prints no
    # explicit tax subtotal (PBT is itself a pre-NCI-split, whole-entity
    # figure, so it must be paired with whole-entity PAT, not owners-only
    # PAT, or the derived tax figure would be wrong by exactly the NCI
    # profit share).
    "pat_total": ["profit after tax", "profit for the year", "net profit", "profit for the period",
                  "net income"],
    "depreciation": ["depreciation and amortisation expense", "depreciation and amortization",
                      "depreciation, amortization and impairment"],
    "total_expenses": ["total expenses"],
    "total_assets": ["total assets"],
    "current_assets": ["total current assets"],
    "current_liabilities": ["total current liabilities"],
    "inventory": ["inventories", "inventory", "stock-in-trade"],
    "receivables": ["trade receivables", "receivables", "sundry debtors", "debtors"],
    "payables": ["trade payables", "payables", "sundry creditors", "creditors"],
    "cash": ["cash and cash equivalents", "cash and cash equivalent", "cash & cash equivalents", "cash and bank balances",
             "cash & bank balances", "cash balances"],
    # Bank balances OTHER than cash equivalents (fixed deposits, margin money,
    # unpaid-dividend accounts...) - a separate Balance Sheet line Cash Ratio
    # must surface even when it can't classify restricted vs unrestricted
    # (singular and plural captions both occur, e.g. "Other Bank Balance").
    "other_bank_balances": ["other bank balances", "other bank balance",
                             "bank balances other than cash and cash equivalents"],
    "total_debt": ["total borrowings", "long-term borrowings", "total debt", "total loans"],
    "equity": ["total equity", "shareholders funds", "shareholders' funds", "net worth",
               "equity attributable to owners", "total shareholders equity"],
    # Non-Controlling Interest - its own always-separate Balance Sheet line
    # under Ind AS (same canonical labels as _NCI_LABELS in
    # tools/annual_report_financials.py). Needed so this module's "equity"
    # (owners-only when NCI is confirmed separate) can be added back to NCI
    # to form the WHOLE-entity equity figure Debt-to-Equity (Sr No 20)
    # requires - the numerator (Total Debt) is the whole consolidated
    # entity's debt, so the denominator must be the whole entity's equity,
    # not just the parent shareholders' portion. Previously this module had
    # no way to capture NCI at all, so "equity_full" was set identically to
    # "equity" in `_broad_extraction_to_parsed_shape`, silently understating
    # Debt-to-Equity's denominator by the NCI amount for any company routed
    # through the broad-extraction fallback with a material minority
    # interest.
    "non_controlling_interest": ["non-controlling interests", "non controlling interests",
                                  "non-controlling interest", "non controlling interest",
                                  "minority interest", "minority interests"],
    # Deliberately excludes the bare section HEADER "cash flow from operating
    # activities" - confirmed real bug: that header is immediately followed
    # by the first reconciliation line (PBT), not the section's actual
    # total, so it silently extracted the wrong number. Every alias here
    # names the TOTAL line specifically.
    "operating_cash_flow": ["net cash from operating activities", "net cash generated from operating activities",
                             "net cash flow generated from operating activities", "net cash (used in) generated from operating activities", "net cash (used in)/ generated from operating activities", "cash flow generated from operating activities", "net cash flows (used in)/generated from operating activities", "net cash flow (used in)/generated from operating activities", "net cash flow from/(used in) operating activities", "net cash generated from operating activities (a)", "net cash flows from/(used in) operating activities",
                             "net cash generated from/(used in) operating activities",
                             "net cash (used in)/generated from operating activities",
                             "net cash flow from operating activities",
                             # "flows" (plural) - standard Ind AS Schedule III phrasing some
                             # filers use instead of the singular "flow" every other alias
                             # above already covers - confirmed real on TCS's FY2026
                             # Consolidated Statement of Cash Flows: "Net cash flows
                             # generated from operating activities", not "...cash flow...".
                             "net cash flows generated from operating activities",
                             "net cash flows from operating activities", "cash generated from operations",
                             "net cash generated from/(utilized in) operations",
                             "net cash generated from (utilized in) operations",
                             "net cash used in/generated from operations",
                             "net cash generated from operations", "net cash used in operations"],
    # "capital expenditure" deliberately excluded - confirmed real bug: too
    # generic, matched an MD&A capacity-expansion sentence ("...29,800 MT")
    # instead of the cash flow statement's actual purchase-of-PPE line.
    "capex": ["purchase of property, plant and equipment", "expenditure for property, plant and equipment", "expenditure on property, plant and equipment", "purchase of fixed assets",
              "additions to property, plant and equipment", "acquisition of property, plant and equipment",
              "payments for property, plant and equipment", "payments to acquire property, plant and equipment",
              # Singular "Payment for purchase of..." - standard Ind AS Cash Flow
              # Statement (investing activities) phrasing some filers use instead of
              # the plural "Payments for..." every other alias above covers -
              # confirmed real on TCS's FY2026 Consolidated Statement of Cash Flows.
              "payment for purchase of property, plant and equipment"],
    # Added for the 68-ratio framework's Sr 13/17/24-29/37/53/62/64 (see
    # tools/fundamental_ratio_registry.py) - reuses the SAME AR-fallback
    # extraction machinery, never a per-ticker rule.
    # SINGULAR "Earning Per (Equity) Share" (not "Earnings") - confirmed
    # real gap on Prime Fresh Limited/LANDMARKACHIEVE: this filer's own
    # P&L row is captioned "XVI. Earning Per Equity Share [Face Value Rs.
    # 10/- Each] / Basic 9.68 / Diluted 9.40" - singular "Earning", which
    # none of the (all-plural) aliases below matched on the correctly-
    # identified P&L anchor page, so extraction fell through to a whole-
    # document scan. That scan's FIRST hit was an unrelated Significant
    # Accounting Policies sentence naming the Ind AS 33 standard ("...
    # 'Earnings Per Share' issued by Central Government... : Please refer
    # to note no. 45...") - a boilerplate mention, not a genuine EPS
    # figure - and read the trailing NOTE-REFERENCE number "45" as if it
    # were the actual EPS value (real Basic EPS is 9.68), corrupting both
    # P/E (Sr No 24) and Graham Number (Sr No 54, which reuses P/E's own
    # extracted EPS). Listed first/second so the correctly-anchored page's
    # own row is preferred whenever this singular phrasing is present.
    # EPS ATTRIBUTABLE TO OWNERS - a consolidated P&L may print two Basic EPS
    # lines (one on whole-entity profit, one "Excluding Non-controlling
    # interest"); shareholder valuation (P/E, Earnings Yield, EPS Growth, PEG,
    # Graham) must use the owners' one. Absent => the single printed Basic EPS
    # is already owners-attributable per Ind AS 33 (handled by the consumer).
    "eps_owners": ["basic earnings per equity share - excluding non controlling interest",
                   "basic earnings per equity share - excluding non-controlling interest",
                   "basic earnings per equity share excluding non controlling interest",
                   "basic earnings per equity share excluding non-controlling interest",
                   "basic earnings per share - excluding non controlling interest",
                   "basic earnings per share - excluding non-controlling interest",
                   "basic earnings per share excluding non-controlling interest",
                   "basic earning per equity share - excluding non controlling interest",
                   "basic earning per share - excluding non controlling interest",
                   "basic earnings per equity share attributable to owners",
                   "basic earnings per share attributable to owners",
                   "basic eps attributable to owners",
                   "basic earnings per share attributable to equity holders"],
    "eps": ["basic earning per equity share", "basic earning per share",
            "earning per equity share", "earning per share",
            "basic earnings per equity share", "basic earnings per share", "earnings per share (basic)",
            "earnings per equity share", "earnings per share",
            # A filer whose Basic and Diluted EPS are identical (no dilutive
            # securities) commonly captions the P&L row itself just "Basic
            # and diluted" (or "Basic & diluted") rather than repeating
            # "earnings per share" - standard Ind AS phrasing (also handled
            # in tools/annual_report_financials.py's own EPS finder),
            # confirmed real on TCS's FY2026 P&L: "Basic and diluted ...
            # 136.01 134.19" with no "earnings per share" words on that row
            # at all - none of the aliases above matched it, leaving EPS
            # (and everything derived from it: P/E, EPS Growth, PEG,
            # Graham Number) not_disclosed despite the figure being printed
            # directly on the P&L. Scoped safely by the anchor-page
            # extraction this key already goes through (P&L page only).
            "basic and diluted", "basic & diluted"],
    # Deliberately EXCLUDES "weighted average number of equity shares" - that
    # note is the EPS DENOMINATOR (a distinct concept from the closing share
    # count every ratio that reads THIS key actually needs: P/B's BVPS,
    # Market Cap, EV, Dividend Yield's per-share basis - all of which must
    # use the CLOSING outstanding count, per spec's "use the closing balance
    # and the closing share count for consistency with the market price
    # date", same reasoning as `fetch_shares_outstanding_from_annual_report`
    # in tools/annual_report_financials.py). Including it here let a filing
    # whose "issued/outstanding" note wasn't found (or scored lower) silently
    # fall back to the weighted-average EPS note instead - confirmed real on
    # ANURAS: this key resolved to the 10,98,55,778 weighted-average-for-EPS
    # figure, not the 10,99,31,337 actually-outstanding count.
    # Most filings don't caption a bare "number of equity shares outstanding"
    # row at all - the actual disclosure is the Equity Share Capital note's
    # "Issued, Subscribed and (Fully) Paid-up" reconciliation (Ind AS
    # Schedule III), same standard phrasing already handled by the narrow
    # parser's `_find_shares_outstanding` in tools/annual_report_financials.py.
    # The "...at the end of the year" variant is listed FIRST and matched
    # verbatim (not just "issued, subscribed...") because the reconciliation
    # table always ALSO prints an "...outstanding at the BEGINNING of the
    # year" row just above it with the SAME leading words - a generic
    # "issued, subscribed and fully paid" alias would match that opening-
    # balance row first (it appears earlier in the page's text) and silently
    # read last year's closing count instead of this year's. Confirmed real
    # on Anupam Rasayan (ANURAS): this key returned nothing at all before
    # (no alias matched either of the filing's actual phrasings), not a
    # company-specific string - this is standard Schedule III language used
    # across Indian filers generically.
    "shares_outstanding": [
        "issued, subscribed and fully paid up equity shares outstanding at the end of the year",
        "issued, subscribed and fully paid-up equity shares outstanding at the end of the year",
        "issued, subscribed and paid up equity shares outstanding at the end of the year",
        "issued, subscribed and paid-up equity shares outstanding at the end of the year",
        "number of equity shares outstanding", "total number of equity shares",
        "no. of equity shares outstanding",
        "issued, subscribed and fully paid up equity shares",
        "issued, subscribed and fully paid-up equity shares",
        # Deliberately EXCLUDES "...share capital" phrasings (e.g. "issued,
        # subscribed and paid-up share capital") - that caption is ambiguous
        # between the ₹ CAPITAL AMOUNT and the share COUNT, both of which are
        # legitimately printed right after it depending on filing style.
        # Confirmed real regression on CIPLA: a narrative sentence "...paid-
        # up share Capital of the Company increased from Rs 1,61,52,34,240/-
        # (divided into 80,76,17,120 equity shares of Rs 2/- each)..." - the
        # alias matched, and the window's FIRST number was the capital AMOUNT
        # (Rs 1.615 Cr's worth, printed in full rupees) rather than the
        # 80,76,17,120 share count that follows it - exactly the "amount vs
        # count" confusion this key exists to prevent. Every remaining alias
        # here ends in "shares"/"shares outstanding", never "share capital",
        # so the number immediately following can only be a count.
    ],
    "dividend_per_share": ["dividend per share", "dividend per equity share"],
    # Cash dividends actually PAID (Financing Activities). "dividend income" /
    # "interest and dividend income" (Investing) deliberately never match.
    "dividends_paid": ["dividend paid on equity shares", "dividends paid on equity shares", "equity dividend paid",
                       "payment of dividend", "dividend paid", "dividends paid", "final dividend paid",
                       "interim dividend paid"],
    # Needed by the narrow "..._from_annual_report" component-sum EBITDA
    # calc that Operating Profit Margin/ROCE/Net Debt-EBITDA/DSCR/ROIC read
    # from the shared `parsed` dict - the broad-fallback adapter's own
    # PBT+Finance Costs EBIT derivation doesn't feed those functions, which
    # independently rebuild EBITDA from these component lines.
    "employee_benefit_expense": ["employee benefits expense", "employee benefit expense", "employee costs"],
    "other_expenses": ["other expenses"],
    "net_fixed_assets": ["property, plant and equipment", "net fixed assets", "net block"],
    # Components of Navrist's Net Fixed Assets definition (PPE + ROU assets +
    # Capital WIP + Intangibles, EXCLUDING goodwill) - each its own face-of-
    # Balance-Sheet row, so the policy never depends on one blended alias.
    "ppe": ["property, plant and equipment", "property, plant & equipment", "net block"],
    "rou_assets": ["right-of-use assets", "right of use assets", "rights-of-use assets",
                   "right-of-use asset", "right of use asset"],
    "cwip": ["capital work-in-progress", "capital work in progress", "capital work-in progress"],
    "intangibles": ["other intangible assets", "intangible assets", "intangible asset"],
    "goodwill": ["goodwill on consolidation", "goodwill"],
    # Lease liabilities are summed across the non-current + current rows (see
    # _SUM_GROUPS); Total Liabilities is the statement's own subtotal.
    "lease_liabilities": ["lease liabilities", "lease liability"],
    "total_liabilities": ["total liabilities"],
    "reserves_and_surplus": ["other equity", "reserves and surplus"],
    # Equity Share Capital (P-B/Sr No 25 only - see that key's sole
    # consumer) - a virtually-always-explicitly-labeled Balance Sheet row,
    # unlike the section's own final subtotal (which may be printed
    # unlabelled and bundles in Non-Controlling Interest/Share Warrants -
    # see "equity"'s own comment). Summed with "reserves_and_surplus"
    # ("Other Equity") as a "sum what's there" owners-only equity
    # reconstruction when the bare-subtotal/labeled "equity" match isn't
    # confirmed to already exclude NCI - never a guess, only used when
    # both this and "reserves_and_surplus" are independently found.
    "equity_share_capital": ["equity share capital", "share capital"],
    # Bank/NBFC-only (Sr 62 PCR, Sr 64 Credit-to-Deposit) - only searched
    # when the resolved sector is Banks/NBFC (see run_fundamental_analysis).
    "deposits": ["total deposits", "deposits"],
    "advances": ["total advances", "advances", "loans and advances"],
    "gross_npa": ["gross non-performing assets", "gross npa"],
    "total_provisions": ["provision for non-performing assets", "total provisions held", "provisions for npa"],
}

_UNIT_MULTIPLIERS = {
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
    "million": 1e6, "millions": 1e6, "mn": 1e6,
    "billion": 1e9, "billions": 1e9, "bn": 1e9,
    "thousand": 1e3, "thousands": 1e3,
}
_ALL_NUMS_RE = re.compile(
    r"(\(?-?[\d,]+\.?\d*\)?)\s*(crore|crores|cr|lakh|lakhs|lac|million|millions|mn|billion|billions|bn|thousand|thousands|%)?",
    re.I,
)
_STATEMENT_HEADER_HINTS = ("balance sheet", "statement of profit and loss", "profit & loss",
                            "cash flow statement", "financial statements", "financial results")
# A number window right after a line-item label almost always starts with the
# schedule/note reference ("25(a)", "8", "10"), NOT the actual rupee figure -
# confirmed real: naive "first number after the phrase" picked up "25" from
# "Cost of Materials Consumed 25(a) 6,483.58" instead of 6,483.58 itself.
# Real financial-statement figures are comma-grouped or carry a decimal;
# a bare 1-3 digit integer with neither is almost always a note reference.

# Some Annual Report PDFs bake a stray single space directly into the text
# of specific bold/subtotal rows (a PDF-generator kerning-pair quirk in the
# embedded font, not missing data) - confirmed real on TCS's FY2026 filing:
# "Total equity" extracts as "Total eq uity", "TOTAL EQUITY AND LIABILITIES"
# as "TOTAL EQ U ITY AN D LIABILITIES". A plain `str.find(alias)` silently
# never matches these, so "equity" (and anything else this hits) resolved
# to None across the whole document even though the figure is right there -
# indistinguishable, from the outside, from a genuinely undisclosed line
# item. `_fuzzy_find` below tolerates ONE optional stray space between any
# two characters of the alias (a real space already in the alias, between
# two words, still requires at least one whitespace char) - a clean filing
# with no such artifact matches identically to plain substring search, so
# this is zero-risk for every company that doesn't have the artifact.
_FUZZY_PHRASE_CACHE = {}


def _fuzzy_phrase_pattern(phrase):
    pat = _FUZZY_PHRASE_CACHE.get(phrase)
    if pat is None:
        # A real space IN the phrase (the gap between two words) requires
        # at least that one whitespace char (\s+ - never fewer). Every
        # other character additionally tolerates ONE optional stray space
        # immediately before it (\s?), which is where the PDF artifact
        # lands (e.g. the "q"/"u" boundary in "eq uity"). A phrase with no
        # matching artifact in the source text still matches exactly like
        # a plain substring search - this never turns into a false match
        # anywhere else, since every one of the phrase's own characters
        # must still appear in the same order.
        parts = []
        for ch in phrase:
            parts.append(r"\s+" if ch == " " else r"\s?" + re.escape(ch))
        pat = re.compile("".join(parts))
        _FUZZY_PHRASE_CACHE[phrase] = pat
    return pat


def _fuzzy_find(low_text, phrase, start=0):
    """Like `low_text.find(phrase, start)` but tolerant of the stray-space
    artifact above. Returns (pos, end) of the match (end being where a
    plain find's `pos + len(phrase)` would normally point), or (-1, -1)."""
    m = _fuzzy_phrase_pattern(phrase).search(low_text, start)
    return (m.start(), m.end()) if m else (-1, -1)


def _extract_best_number(window):
    """Scans every number in `window`, skips bare small note/schedule
    reference integers, and prefers the earliest properly-formatted
    (comma-grouped or decimal) figure. Returns (value, unit) or
    (None, None)."""
    candidates = []
    for m in _ALL_NUMS_RE.finditer(window):
        raw = m.group(1)
        digits_only = raw.strip("()").replace(",", "").replace(".", "").replace("-", "")
        if not digits_only:
            continue
        has_comma = "," in raw
        has_decimal = "." in raw.strip("()")
        is_note_ref = (not has_comma and not has_decimal and len(digits_only) <= 3)
        try:
            value = float(raw.strip("()").replace(",", ""))
        except ValueError:
            continue
        if raw.startswith("(") and raw.endswith(")"):
            value = -abs(value)
        candidates.append({"value": value, "unit": (m.group(2) or "").lower() or None,
                            "is_note_ref": is_note_ref, "has_comma": has_comma, "start": m.start()})
    if not candidates:
        return None, None
    real = [c for c in candidates if not c["is_note_ref"]]
    pool = real if real else candidates
    pool.sort(key=lambda c: (not c["has_comma"], c["start"]))
    best = pool[0]
    return best["value"], best["unit"]


# Which financial statement each canonical line item actually lives on - 
# used to find that statement's own page once (via density of its own
# distinctive header terms) and strongly prefer extracting from THAT page,
# rather than whichever page happens to mention the phrase first (an MD&A
# highlights graphic, a subsidiary note, or a ratio-analysis table nearby
# all mention the same words without being the actual statement line).
_BALANCE_SHEET_ITEMS = {"total_assets", "current_assets", "current_liabilities", "inventory",
                        "receivables", "payables", "cash", "other_bank_balances", "total_debt", "equity",
                        "deposits", "advances", "gross_npa", "total_provisions",
                        "net_fixed_assets", "reserves_and_surplus", "non_controlling_interest",
                        "equity_share_capital", "ppe", "rou_assets", "cwip", "intangibles", "goodwill",
                        "lease_liabilities", "total_liabilities"}
_PROFIT_LOSS_ITEMS = {"revenue", "cogs", "ebitda", "ebit", "interest_expense", "pbt", "tax", "pat", "pat_total",
                       "depreciation", "eps", "shares_outstanding", "dividend_per_share", "employee_benefit_expense",
                       "other_expenses", "cost_of_materials_consumed", "purchases_of_stock_in_trade",
                       "changes_in_inventories", "total_expenses", "eps_owners"}
_CASH_FLOW_ITEMS = {"operating_cash_flow", "capex"}

# EPS, Dividend per Share and Shares Outstanding are NEVER stated "in
# Crore/Lakh/Million" the way aggregate P&L/Balance-Sheet lines (Revenue,
# PAT, Equity, ...) are - EPS/DPS are already a bare ₹-per-share figure (a
# per-share amount in lakhs/crores would be meaningless), and Shares
# Outstanding is a raw COUNT of shares, not a monetary amount at all.
# `_page_unit_multiplier` reads the statement PAGE's unit declaration (e.g.
# "(Rs in Million)") and applies it to every figure pulled off that page -
# correct for Revenue/PAT/etc, but wrong for all three of these: confirmed
# real on ANURAS, where the P&L page declares "in Million" and Basic EPS is
# printed as plain "6.62" - multiplying by the page's Million-to-Crore
# factor (0.1) silently turned it into 0.662. The same mechanism would
# equally corrupt a share COUNT found on a unit-declaring anchor page (e.g.
# 10,99,31,337 shares x 0.1 -> a nonsense 109,931,133.7) if that filing's
# Balance Sheet anchor page happens to carry the "issued/outstanding" note
# text directly, rather than needing the whole-document fallback scan.
_PER_SHARE_ITEMS = {"eps", "dividend_per_share"}
_UNSCALED_ITEMS = _PER_SHARE_ITEMS | {"shares_outstanding", "eps_owners"}

_ANCHOR_HINTS = {
    "balance_sheet": ["total current assets", "total current liabilities", "total equity", "total assets"],
    "profit_loss": ["profit before tax", "total expenses", "revenue from operations", "total income"],
    "cash_flow": ["net cash from operating activities", "cash flow from operating activities",
                  "cash flow from financing activities", "cash generated from operations",
                  "net cash generated from"],
}

# Explicit "Consolidated <statement>" header phrases - checked BEFORE the
# generic score-based anchor search below. Per the Consolidation Priority
# rule ("use Consolidated first, fall back to Standalone only if
# Consolidated is unavailable"), a page carrying this exact header always
# wins over a same-scoring Standalone page - confirmed real bug: without
# this, a Standalone statement earlier in the document (which scores
# identically on the generic hint set) could win by page order alone,
# silently mixing a Standalone Balance Sheet with a Consolidated P&L.
_CONSOLIDATED_STATEMENT_HEADERS = {
    "balance_sheet": ("consolidated balance sheet",),
    "profit_loss": ("consolidated statement of profit and loss", "statement of consolidated profit and loss",
                     "consolidated profit and loss"),
    # "consolidated statement of cash flow(s)" - the word order some filers
    # use ("Consolidated Statement of Cash Flow", e.g. Prime Fresh Limited/
    # LANDMARKACHIEVE) is DIFFERENT from "consolidated cash flow statement"
    # - the same word-order variance already anticipated for profit_loss
    # above, but this category only had the one rigid phrasing. Without
    # this, a same-scoring Standalone Cash Flow Statement (which prints
    # earlier in the document, per standard Indian AR convention) won by
    # page order alone, silently feeding Price/Cash Flow (Sr No 53) the
    # Standalone OCF figure instead of the requested Consolidated one -
    # confirmed real on LANDMARKACHIEVE (-₹1.21 Cr Standalone vs the real
    # -₹11.91 Cr Consolidated) and the same class of issue on AARTIIND.
    "cash_flow": ("consolidated cash flow statement", "consolidated statement of cash flow",
                  "consolidated statement of cash flows"),
}
def _find_anchor_pages(pages):
    """Scores every page by how many of a statement's own distinctive
    header/total-line terms it contains, returns {statement: page_idx}
    for whichever page scores highest per statement (None if no page
    scores > 1 - a single incidental mention isn't enough to anchor on).
    A page carrying the explicit "Consolidated <statement>" header always
    wins outright over any Standalone-only page, regardless of score."""
    anchors = {}
    for stmt, hints in _ANCHOR_HINTS.items():
        # A page carrying the "Consolidated <statement>" header AND scoring
        # on the generic content hints is the real statement page; a page
        # that only NAMES the consolidated statement in passing (e.g. the
        # Independent Auditor's Report's opening paragraph, which lists
        # every statement it audited) carries the header phrase too but
        # has none of the statement's own total-line content - confirmed
        # real: without the score co-requirement, that auditor's-report
        # page (appearing earlier in the document) won by being the FIRST
        # header match, hijacking every fact extraction onto the wrong page.
        consolidated_idx, consolidated_score = None, 1
        for page_idx, text in enumerate(pages):
            low = text.lower()
            if not any(h in low for h in _CONSOLIDATED_STATEMENT_HEADERS.get(stmt, ())):
                continue
            score = sum(1 for h in hints if h in low)
            if score > consolidated_score:
                consolidated_idx, consolidated_score = page_idx, score
        if consolidated_idx is not None:
            anchors[stmt] = consolidated_idx
            continue
        best_idx, best_score = None, 1
        for page_idx, text in enumerate(pages):
            low = text.lower()
            score = sum(1 for h in hints if h in low)
            if score > best_score:
                best_idx, best_score = page_idx, score
        anchors[stmt] = best_idx
    return anchors


# Page-level unit declaration ("Amount (Rs) in millions", "(Rs in Crore)",
# "(All amounts in Rs Lakhs unless otherwise stated)", ...) - Indian
# Annual Reports state the unit ONCE near a statement's own header, not
# next to every individual figure, so a number extracted without reading
# this is silently off by 10x/100x/1000x. Detected once per anchor page,
# applied to every figure read from that same page. Missing/undetected
# unit is treated as already-crore (1.0x) - never guessed as something
# else.
#
# MANUAL-UPLOAD WORKFLOW ONLY (tools/document_analysis_engine.py's own
# Strategy-C extraction - never shared with tools/annual_report_financials.py's
# extractor, which the automatic/live pipeline uses via its own separate
# _unit_factor()). Confirmed real gap: "(All amounts in INR Lakhs, except
# per share data and as stated otherwise)" (Prime Fresh Limited/
# LANDMARKACHIEVE FY26 Consolidated Balance Sheet) puts the currency token
# (INR) BETWEEN "in" and the unit word ("in INR Lakhs"), not BEFORE "in"
# (the only shape the original pattern covered - "Rs in Lakhs", "(₹ in
# Crore)"). The original pattern silently returned no match for this
# filing, defaulting to the 1.0x "assume already crore" fallback and
# leaving every Lakh-denominated figure on that page 100x too large -
# confirmed real on Working Capital (Sr No 13): Current Assets displayed
# as ₹11,517 Cr instead of the correct ₹115.17 Cr. The second alternative
# below adds the "in <currency> <unit>" shape as an equal alternative to
# the original "<currency> in <unit>" shape - either phrasing is now
# recognised, never assumed.
_PAGE_UNIT_RE = re.compile(
    r"(?:amount|figures|values)?\s*\(?\s*(?:rs\.?|inr|`|₹)?\s*\)?\s*in\s+(crores?|lakhs?|lacs?|millions?|billions?|thousands?)\b"
    r"|in\s+(?:rs\.?|inr|`|₹)\s+(crores?|lakhs?|lacs?|millions?|billions?|thousands?)\b",
    re.I,
)
_PAGE_UNIT_FOOTNOTE_RE = re.compile(
    r"\(\s*(?:all\s+)?(?:amounts?\s+|figures\s+|values\s+)?(?:are\s+)?(?:stated\s+)?(?:in|(?:rs\.?|inr|`|\u20b9)\s+in)\s+"
    r"(?:(?:rs\.?|inr|`|\u20b9)\s*)?(?:of\s+)?(crores?|lakhs?|lacs?|millions?|billions?|thousands?)\b"
    r"|\(\s*(?:rs\.?|inr|`|\u20b9)\s+in\s+(crores?|lakhs?|lacs?|millions?|billions?|thousands?)\b",
    re.I,
)
_PAGE_UNIT_TO_CRORE = {
    "crore": 1.0, "crores": 1.0,
    "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01,
    "million": 0.1, "millions": 0.1,
    "billion": 100.0, "billions": 100.0,
    "thousand": 0.0001, "thousands": 0.0001,
}


def _page_unit_multiplier(page_text):
    """Crore-normalization multiplier for every raw figure on this page, or
    1.0 (assume already crore) if no unit declaration is found - never
    fabricates a unit, and 1.0 is the pre-existing implicit assumption this
    replaces, so an undetected page is no worse off than before."""
    m = _PAGE_UNIT_RE.search(page_text[:800])  # unit is usually declared near the statement's own header ...
    if not m:
        # ... but some filers print it as a footnote far below the table (Maruti: "(in ` million, unless otherwise stated)"
        # ~3,000 characters in, after the signature block). A PARENTHESISED declaration anywhere on the page is accepted;
        # bare prose ("... in million units") is not, so a stray phrase cannot rescale a page.
        m = _PAGE_UNIT_FOOTNOTE_RE.search(page_text)
    if not m:
        return 1.0
    # Two alternatives in the pattern ("<currency> in <unit>" vs "in
    # <currency> <unit>") - whichever one matched captures the unit word
    # into its own group, the other's group is None.
    unit_word = m.group(1) or m.group(2)
    return _PAGE_UNIT_TO_CRORE.get(unit_word.lower(), 1.0)


_BARE_SUBTOTAL_SECTIONS = {
    # key -> (section-start regex, [candidate stop-label regexes, nearest wins])
    # Some filers (e.g. Bharti Airtel's Standalone/Consolidated Balance
    # Sheet) never caption "Total current assets"/"Total current
    # liabilities" at all - the sub-items are simply followed by an
    # UNLABELLED subtotal number pair before the next section starts.
    # Universal Schedule III/Ind AS structure guarantees the subtotal is
    # always the LAST number pair printed inside the section, whether or
    # not it's captioned - so this fallback works for any filer using this
    # presentation style, not a specific company.
    "current_assets": (r"\bCurrent\s+assets\b", [r"\bTotal\s+assets\b"]),
    "current_liabilities": (r"(?<!Non-)(?<!Non )\bCurrent\s+liabilities\b",
                             [r"\bTotal\s+liabilities\b", r"\bTotal\s+equity\s+and\s+liabilities\b"]),
    # Total Equity (Sr No 25/P-B) - some filers never caption "Total
    # Equity" on the Balance Sheet face itself either (same unlabelled-
    # subtotal presentation style as current assets/liabilities above,
    # confirmed real on Prime Fresh Limited/LANDMARKACHIEVE: the Equity
    # section's own sub-items - Equity Share Capital, Other Equity, Money
    # Received Against Share Warrants, Non-Controlling Interest - are
    # followed by a bare, unlabelled subtotal with no "Total Equity"
    # caption at all). Without this, `extract_line_items`'s generic
    # "equity" alias falls through to a whole-document scan, which can
    # latch onto an unrelated "Total Equity Recognised Under Previous
    # GAAP" row inside an Ind AS first-time-adoption reconciliation note
    # instead (a genuine, confirmed false positive - see the trailing-
    # context reject list in `_search_ar_pages` for the accompanying
    # guard). Scoped to the Balance Sheet's own "Equity and Liabilities"
    # major heading, ending before the Liabilities section starts -
    # generic Schedule III/Ind AS structure, not filer-specific.
    "equity": (r"\bEquity\s+and\s+Liabilities\b", [r"\bNon-current\s+Liabilities\b", r"\bLiabilities\b"]),
}


def _extract_bare_section_subtotal(page_text, key, unit_mult):
    """Fallback for `_BARE_SUBTOTAL_SECTIONS` keys when no explicit "Total
    current assets"/"Total current liabilities" label exists on the page
    at all (see that dict's comment). Finds the section's own start marker,
    then the NEAREST of the candidate stop labels after it (an
    intermediate subtotal - e.g. "Total liabilities" - sitting between the
    section and its own final grand-total caption must not be skipped
    past, or its numbers get mistaken for this section's subtotal), and
    takes the last two numbers printed in that bounded window - EXCEPT on
    an Ind AS first-time-adoption Balance Sheet, which prints a THIRD
    column (an April-1 opening-balance date, alongside the usual current-
    and prior-year columns) - see below. Returns {value, prior_value,
    unit, evidence, confidence} or None."""
    m = re.search(_BARE_SUBTOTAL_SECTIONS[key][0], page_text, re.I)
    if not m:
        return None
    tail = page_text[m.end():]
    stops = [sm for sm in (re.search(p, tail, re.I) for p in _BARE_SUBTOTAL_SECTIONS[key][1]) if sm]
    if not stops:
        return None
    stop = min(stops, key=lambda sm: sm.start())
    window = tail[:stop.start()]
    nums = []
    for nm in _ALL_NUMS_RE.finditer(window):
        raw = nm.group(1)
        digits_only = raw.strip("()").replace(",", "").replace(".", "").replace("-", "")
        if not digits_only:
            continue
        has_comma, has_decimal = "," in raw, "." in raw.strip("()")
        if not has_comma and not has_decimal and len(digits_only) <= 3:
            continue  # note/schedule reference
        try:
            val = float(raw.strip("()").replace(",", ""))
        except ValueError:
            continue
        nums.append(-abs(val) if raw.startswith("(") and raw.endswith(")") else val)
    if len(nums) < 2:
        return None
    # Column-count check: an Ind AS first-time adopter (e.g. a recent IPO/
    # SME migration) prints THREE comparative columns on the WHOLE Balance
    # Sheet - "As at March 31 YYYY / As at March 31 YYYY-1 / As at April 1
    # YYYY-2" - not the usual two, so this section's own bare subtotal row
    # ALSO has 3 numbers (current, prior, opening), and blindly taking the
    # last two would silently return (prior, opening) instead of (current,
    # prior). Detected structurally, not by phrasing: the grand-total row
    # immediately after the stop label (e.g. "Total assets"/"Total equity
    # and liabilities") is on the SAME statement, so it carries the exact
    # same column count - read off ITS own number count instead of
    # guessing from page-header text, which varies by filer. Confirmed
    # real on Prime Fresh Limited/LANDMARKACHIEVE's FY26 Consolidated
    # Balance Sheet: "TOTAL EQUITY AND LIABILITIES 11,993.81 8,126.42
    # 6,851.77" - 3 numbers - while this section's own bare subtotal
    # "2,028.87 1,002.13 608.46" was being read as (1,002.13, 608.46)
    # instead of the correct (2,028.87, 1,002.13).
    # The grand-total caption isn't always immediately after `stop` - for
    # `key`s whose stop candidates are themselves section BOUNDARIES rather
    # than the grand total itself (e.g. "equity"'s stop is "Liabilities",
    # not "Total Equity and Liabilities" - the real grand total sits much
    # further down the page, past the entire Liabilities section), search
    # a wider window for the first genuine grand-total caption
    # ("total assets" / "total equity and liabilities") rather than
    # assuming it's right at `stop`. For `current_assets`/
    # `current_liabilities`, `stop` IS already the grand total, so this
    # still finds it immediately - behaviour there is unchanged.
    grand_total_search = tail[stop.end():stop.end() + 4000]
    gt_match = re.search(r"total\s+assets\b|total\s+equity\s+and\s+liabilit", grand_total_search, re.I)
    grand_total_window = (grand_total_search[gt_match.end():gt_match.end() + 120]
                           if gt_match else tail[stop.end():stop.end() + 120])
    grand_total_nums = []
    for gm in _ALL_NUMS_RE.finditer(grand_total_window):
        graw = gm.group(1)
        gdigits = graw.strip("()").replace(",", "").replace(".", "").replace("-", "")
        if not gdigits:
            continue
        ghas_comma, ghas_decimal = "," in graw, "." in graw.strip("()")
        if not ghas_comma and not ghas_decimal and len(gdigits) <= 3:
            continue
        grand_total_nums.append(graw)
        if len(grand_total_nums) >= 4:
            break  # only need to know if it's 3 (vs. 2), not the exact count
    three_column = len(grand_total_nums) == 3
    if three_column and len(nums) >= 3:
        current_val, prior_val = nums[-3], nums[-2]
    else:
        current_val, prior_val = nums[-2], nums[-1]
    return {"value": round(current_val * unit_mult, 4), "prior_value": round(prior_val * unit_mult, 4),
            "unit": "crore", "evidence": f"Unlabelled section subtotal ("
                                          f"{'first two of the last three' if three_column and len(nums) >= 3 else 'last two'} "
                                          f"figures before '{stop.group()}')", "confidence": 0.85}


_SHARE_ROW_NUM_RE = re.compile(r"\(?-?[\d,]+(?:\.\d+)?\)?")


def _shares_prior_from_page(page_text, alias_variants):
    """Prior-year share COUNT for a direct-alias `shares_outstanding` hit.

    The Share Capital note prints "<caption> <shares_cur> <amount_cur>
    <shares_prior> <amount_prior>" - four interleaved numbers (Ind AS
    mandated shape), so the plain "first two numbers" read used by every
    other row yields (current shares, current amount) and never finds the
    prior count. Takes positions 0 and 2, but only when positions 1 and 3
    look like the rupee AMOUNT columns (decimal figures) - otherwise the
    layout is something else and nothing is guessed (returns None)."""
    low = page_text.lower()
    for alias in alias_variants:
        pos, end = _fuzzy_find(low, alias, 0)
        if pos == -1:
            continue
        toks = []
        for m in _SHARE_ROW_NUM_RE.finditer(page_text[end:end + 160]):
            raw = m.group()
            digits = raw.strip("()").replace(",", "").replace(".", "")
            if digits:
                toks.append(raw)
            if len(toks) == 4:
                break
        if len(toks) == 4 and "." in toks[1] and "." in toks[3] and "." not in toks[0] and "." not in toks[2]:
            try:
                cur = float(toks[0].strip("()").replace(",", ""))
                prior = float(toks[2].strip("()").replace(",", ""))
            except ValueError:
                return None
            if cur > 0 and prior > 0:
                return prior
    return None


def _extract_shares_outstanding_from_reconciliation(pages):
    """Fallback for `shares_outstanding` when none of the direct captions in
    `_LINE_ITEM_ALIASES` are present. Ind AS 1/Schedule III universally
    REQUIRES every Indian listed company's Share Capital note to include a
    "Reconciliation of the shares outstanding at the beginning and at the
    end of the year" table, ending in a row captioned "Outstanding at the
    end of the year" - this is a mandated disclosure shape, not a
    company-specific phrasing choice (confirmed real gap on Bharti Airtel,
    which uses ONLY this reconciliation-table caption, not any of the
    'issued, subscribed and fully paid up ... outstanding' phrasings the
    direct aliases above look for).

    That row's shape is (shares_cur, amount_cur, shares_prior, amount_prior)
    - four interleaved numbers, not the plain (current, prior) two-number
    shape every other aliased row has - a blind "first two numbers" read
    would misread the CURRENT YEAR'S FACE-VALUE AMOUNT as the prior year's
    SHARE COUNT. Explicitly takes positions 0 and 2 (the two share-count
    columns) instead, since this exact 4-column layout is itself the
    IND AS-mandated shape, not a per-filer guess."""
    for p in pages:
        text = p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else "")
        if not text:
            continue
        m = re.search(r"reconciliation of the?\s*shares outstanding", text, re.I)
        if not m:
            continue
        # The actual data row can appear BEFORE the caption in extracted
        # text order - multi-column PDF layouts (a caption printed above a
        # table, with the table's own numeric cells in a different visual
        # column) often extract out of the caption's own reading order.
        # Search the whole page for the row, not just the text after the
        # caption match, and use whichever occurrence is nearest to the
        # caption (the row genuinely belonging to THIS reconciliation
        # table, not a same-page unrelated mention).
        row_matches = list(re.finditer(r"outstanding at the end of the year", text, re.I))
        if not row_matches:
            continue
        row_m = min(row_matches, key=lambda rm: abs(rm.start() - m.start()))
        window = text[row_m.end():row_m.end() + 200]
        nums = []
        for nm in re.finditer(r"\(?-?[\d,]+(?:\.\d+)?\)?", window):
            raw = nm.group()
            digits = raw.strip("()").replace(",", "").replace(".", "")
            if not digits:
                continue
            try:
                nums.append(float(raw.strip("()").replace(",", "")))
            except ValueError:
                continue
            if len(nums) == 4:
                break
        if len(nums) < 3:
            continue
        shares_cur, shares_prior = nums[0], nums[2]
        # The table's own column header states the unit (commonly "No. of
        # shares '000"/"(in thousands)" for large filers like Bharti
        # Airtel, but not universally) - only scale by 1000 when that
        # header is actually present nearby, rather than assuming it,
        # since a smaller filer's identical reconciliation table often
        # states plain absolute share counts instead.
        # PDF column-based tables often extract with the unit header AFTER
        # the row it describes (the header sits visually above the table,
        # but multi-column PDF text extraction can reorder it past the
        # first data row) - checked both before AND after the matched row.
        lo, hi = min(m.start(), row_m.start()), max(m.end(), row_m.end())
        header_window = text[max(0, lo - 300):hi + 300]
        in_thousands = bool(re.search(r"'000|\(000|in\s+thousands", header_window, re.I))
        mult = 1000 if in_thousands else 1
        return {"value": round(shares_cur * mult, 2), "prior_value": round(shares_prior * mult, 2),
                "unit": "shares", "evidence": "Reconciliation of shares outstanding - "
                                               "'Outstanding at the end of the year' row",
                "confidence": 0.9}
    return None


# Second, distinct standard phrasing for the Equity Share Capital note's
# "Issued, Subscribed and Paid-up" disclosure - the share count is embedded
# INSIDE the sentence ("Issued, Subscribed and Fully paid up 361,80,87,518
# equity shares of Rs 1 each"), between "paid up" and "equity shares",
# rather than either a reconciliation-table row or a "label: trailing
# value" caption. Neither `_LINE_ITEM_ALIASES`'s substring aliases nor
# `_extract_shares_outstanding_from_reconciliation` above can match this
# shape at all (the number sits mid-phrase, not after a matched label) -
# confirmed real on TCS's FY2026 filing, a standard, common Companies
# Act 2013/Schedule III phrasing choice, not unique to this one company.
_ISSUED_PAIDUP_SHARES_RE = re.compile(
    r"issued,?\s*subscribed\s*and\s*(?:fully\s*)?paid[\s-]*up\s+([\d,]+)\s+equity\s+shares", re.I)


def _extract_shares_outstanding_from_paidup_sentence(pages):
    """Fallback for `shares_outstanding` when neither the direct aliases
    nor the reconciliation-table fallback found anything - reads the
    Equity Share Capital note's own "Issued, Subscribed and Fully paid-up
    N equity shares of Rs F each" sentence. The comparative year's count is
    usually restated in the same sentence's parenthetical ("(March 31,
    <prior>: N equity shares...)") right after - read as `prior_value` when
    present, else the SAME current-year count applies for the earlier
    reporting period (only the number of NEW/BUYBACK'd shares would differ,
    which a bare word-for-word repeat of the count already confirms
    unchanged for that filer). Returns None if the sentence isn't present
    at all - never fabricates a count."""
    for p in pages:
        text = p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else "")
        if not text:
            continue
        m = _ISSUED_PAIDUP_SHARES_RE.search(text)
        if not m:
            continue
        try:
            cur = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        tail = text[m.end():m.end() + 120]
        m2 = re.search(r"[\d,]+", tail)
        prior = None
        if m2:
            try:
                prior_val = float(m2.group().replace(",", ""))
                # A genuine restated prior-year count is comparable
                # magnitude to the current count (never off by orders of
                # magnitude - that would be a face-value amount or an
                # unrelated small number, e.g. a note reference, caught by
                # this same-order-of-magnitude sanity check).
                if 0.5 <= prior_val / cur <= 2.0:
                    prior = prior_val
            except (ValueError, ZeroDivisionError):
                pass
        return {"value": round(cur, 2), "prior_value": round(prior, 2) if prior is not None else round(cur, 2),
                "unit": "shares", "evidence": "Equity Share Capital note - 'Issued, Subscribed and Fully "
                                               "paid-up' sentence", "confidence": 0.9}
    return None


# Third standard phrasing of the Share Capital note: a table row per share class, e.g.
#   "Ordinary Shares of ` 1.00 each, fully paid  12,51,41,19,781  1251.41  12,48,47,21,471  1248.47"
# = (closing count, closing amount, opening count, opening amount). The AUTHORISED row of the same table has no "fully paid"
# and is therefore never matched. A generic Companies Act / Schedule III layout, not specific to one filer.
_CLASS_ROW_SHARES_RE = re.compile(
    r"(?:ordinary|equity)\s+shares?(?:\s+with\s+voting\s+rights)?\s+of\s+(?:[`₹]|rs\.?|inr)?\s*[\d.]+\s*(?:/-)?\s*each,?\s*"
    r"(?:fully\s+)?paid[\s-]*(?:up)?,?\s+(\d[\d,]{6,})\s+([\d,]+(?:\.\d+)?)\s+(\d[\d,]{6,})\s+([\d,]+(?:\.\d+)?)", re.I)


def _extract_shares_outstanding_from_class_row(pages):
    for p in pages:
        text = p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else "")
        m = _CLASS_ROW_SHARES_RE.search(text) if text else None
        if not m:
            continue
        try:
            cur, prior = float(m.group(1).replace(",", "")), float(m.group(3).replace(",", ""))
        except ValueError:
            continue
        if cur <= 0 or not 0.5 <= prior / cur <= 2.0:
            continue
        return {"value": round(cur, 2), "prior_value": round(prior, 2), "unit": "shares",
                "evidence": "Equity Share Capital note - fully paid share-class row (closing / opening count)", "confidence": 0.9}
    return None


def _extract_from_anchor_page(page_text, aliases, unit_mult, exclude_percent=True, permissive=False):
    """Page-anchored, unit-normalized, column-position-aware extraction:
    once a specific statement's own page is known (via _find_anchor_pages),
    read BOTH the current-year and prior-year columns for a label directly
    from that page - Indian financial statements always list the current
    period's column first (Schedule III / Ind AS convention: "March 31,
    2025  March 31, 2024") - rather than a whole-document alias scan that
    can match a DIFFERENT occurrence of the same phrase elsewhere (a prior
    year's restated figure, an MD&A summary table, a different entity's
    statement) and silently pick a value from the wrong year or the wrong
    consolidation basis. Returns {value, prior_value, unit, page_offset,
    evidence, confidence} for the FIRST usable alias match on this page, or
    None if the label isn't on this page at all (caller falls back to the
    existing whole-document search)."""
    low = page_text.lower()
    for alias in aliases:
        search_from = 0
        while True:
            pos, end = _fuzzy_find(low, alias, search_from)
            if pos == -1:
                break
            search_from = end
            trailing = low[end:end + 20]
            # "total equity" is a genuine SUBSTRING of the Balance Sheet's
            # own page-grand-total caption "TOTAL EQUITY AND LIABILITIES"
            # (Total Equity + Total Liabilities combined, not equity alone)
            # - confirmed real on ASIANPAINT: the "equity" alias matched
            # that caption and read 34,534.49 (the WHOLE balance sheet
            # total) as "equity", corrupting BVPS/P-B (implied BVPS ~360
            # instead of the correct ~223) exactly the same false-match this
            # codebase's OWN narrow parser (`_EQUITY_SHARE_CAPITAL_LABELS`'s
            # comment in tools/annual_report_financials.py) already
            # documented and worked around for a different extraction path -
            # this second, simpler alias-matcher never got the same guard.
            if ("ratio" in trailing or "turnover" in trailing or "and liabilit" in trailing
                    or "recognised under" in trailing or "recognized under" in trailing
                    or "previous gaap" in trailing):
                continue
            window = page_text[end:end + 200]
            nums = []
            # Note-reference column guard (permissive mode): a Schedule III
            # statement prints "<label> <Note No> <current> <prior>". A bare
            # small integer FOLLOWED BY two or more formatted (comma/decimal)
            # figures is that Note No, never the current-year value - reading
            # it as one shifted every column by one (a Note "16" became 1.6 Cr
            # with the real current figure demoted to "prior").
            _formatted_after = [mm for mm in _ALL_NUMS_RE.finditer(window)
                                if "," in mm.group(1) or "." in mm.group(1).strip("()")]
            _first_tok = next(iter(_ALL_NUMS_RE.finditer(window)), None)
            _lead_is_note_ref = bool(
                permissive and _first_tok is not None and len(_formatted_after) >= 2
                and "," not in _first_tok.group(1) and "." not in _first_tok.group(1).strip("()")
                and len(_first_tok.group(1).strip("()").replace("-", "")) <= 3
                and _first_tok.start() < _formatted_after[0].start())
            for m in _ALL_NUMS_RE.finditer(window):
                raw = m.group(1)
                digits_only = raw.strip("()").replace(",", "").replace(".", "").replace("-", "")
                if not digits_only:
                    continue
                has_comma, has_decimal = "," in raw, "." in raw.strip("()")
                # `permissive` (used for Equity Share Capital, a row whose
                # real value is routinely a small bare 2-4 digit face-value
                # amount with no comma - e.g. "362") skips this note-ref
                # filter entirely: confirmed real on TCS, where "Equity
                # Share Capital 8(m) 362 362 Other equity 1,06,878 94,394"
                # had its genuine "362 362" figures discarded as note
                # references, silently falling through to Other Equity's
                # numbers on the very next row instead (equity_share_capital
                # resolved to 1,06,878 - IDENTICAL to reserves_and_surplus -
                # corrupting Sr No 25's Price-to-Book, the only consumer of
                # this key). Every other field keeps the filter (a genuine
                # note/schedule reference like "25(a)" is virtually always
                # this exact shape, and most Balance Sheet/P&L rows are
                # comma-grouped or decimal, so the filter stays valuable
                # there).
                bare_small = not has_comma and not has_decimal and len(digits_only) <= 3
                if bare_small:
                    if not permissive:
                        continue  # schedule/note reference (e.g. "25(a)"), not a figure
                    # Permissive mode still rejects the UNAMBIGUOUS note-
                    # reference shape - a bare 1-2 digit number immediately
                    # followed by a lettered sub-reference in parens
                    # ("8(m)", "10(a)") is never itself a real rupee figure,
                    # even on a row whose genuine value is a bare number.
                    if _lead_is_note_ref and m.start() == _first_tok.start():
                        continue  # the Note No. column
                    if len(digits_only) <= 2 and window[m.end():m.end() + 1] == "(":
                        continue
                try:
                    val = float(raw.strip("()").replace(",", ""))
                except ValueError:
                    continue
                if raw.startswith("(") and raw.endswith(")"):
                    val = -abs(val)
                trail_unit = (m.group(2) or "").lower()
                if exclude_percent and trail_unit == "%":
                    continue
                nums.append(val)
                if len(nums) == 2:
                    break
            if not nums:
                continue
            current_val = round(nums[0] * unit_mult, 4)
            prior_val = round(nums[1] * unit_mult, 4) if len(nums) > 1 else None
            return {
                "value": current_val, "prior_value": prior_val, "unit": "crore",
                "evidence": (page_text[pos:pos + 160]).strip(),
                "confidence": 0.97,
            }
    return None


# Sub-item groups for Balance Sheet lines that Schedule III mandates be
# SPLIT rather than shown as one total (e.g. Trade Payables must be split
# "Due to Micro and Small Enterprises" / "Due to others" for every Indian
# company; Borrowings are split Non-Current/Current). A single-alias search
# for "trade payables"/"total borrowings" only ever finds the SPLIT's own
# sub-heading (no figure) or one sub-item's own figure, silently
# undercounting - confirmed real: it returned the MSME-only Trade Payables
# sub-line, missing the much larger "Due to others" line entirely. Sums
# every sub-item phrase found on the anchor page instead.
_SUM_GROUPS = {
    "lease_liabilities": ["lease liability", "lease liabilities"],
    "payables": ["due to micro and small enterprises", "due to other than micro and small enterprises",
                 "due to micro enterprises and small enterprises", "due to other than micro enterprises and small enterprises"],
    "total_debt": ["borrowings"],
}


def _sum_from_anchor_page(page_text, phrases, unit_mult):
    """Sums the first current-year figure found after EVERY occurrence of
    every phrase in `phrases` on this one page (each phrase's occurrences
    counted once - Schedule III's split sub-items are each a distinctly
    worded row, so summing every matched row is the correct total, not
    double-counting). Returns (total, prior_total) or (None, None) if
    nothing matched."""
    low = page_text.lower()
    total_cur, total_prior, any_hit = 0.0, 0.0, False
    for phrase in phrases:
        search_from = 0
        while True:
            pos, end = _fuzzy_find(low, phrase, search_from)
            if pos == -1:
                break
            search_from = end
            window = page_text[end:end + 120]
            nums = []
            for m in _ALL_NUMS_RE.finditer(window):
                raw = m.group(1)
                digits_only = raw.strip("()").replace(",", "").replace(".", "").replace("-", "")
                if not digits_only:
                    continue
                has_comma, has_decimal = "," in raw, "." in raw.strip("()")
                if not has_comma and not has_decimal and len(digits_only) <= 3:
                    continue
                try:
                    val = float(raw.strip("()").replace(",", ""))
                except ValueError:
                    continue
                if raw.startswith("(") and raw.endswith(")"):
                    val = -abs(val)
                nums.append(val)
                if len(nums) == 2:
                    break
            if nums:
                any_hit = True
                total_cur += nums[0]
                if len(nums) > 1:
                    total_prior += nums[1]
    if not any_hit:
        return None, None
    return round(total_cur * unit_mult, 4), round(total_prior * unit_mult, 4) if total_prior else None


def _category_for(key):
    if key in _BALANCE_SHEET_ITEMS:
        return "balance_sheet"
    if key in _PROFIT_LOSS_ITEMS:
        return "profit_loss"
    return "cash_flow"


def _search_ar_pages(pages, aliases, anchor_page=None, exclude_percent=True):
    """Scans every page for any alias phrase, returns the best-confidence
    hit: {value, unit, page, evidence, confidence}. Boosts confidence when
    the hit lands on a page that also looks like a real financial
    statement, and MUCH more when it lands on this item's own detected
    anchor page (the actual Balance Sheet/P&L/Cash Flow statement, not an
    MD&A highlights graphic or a ratio-analysis table mentioning the same
    words). Skips occurrences that are clearly a RATIO-ANALYSIS table row
    (e.g. "Trade Receivables Turnover Ratio") rather than the line item
    itself."""
    best = None
    for page_idx, text in enumerate(pages):
        low = text.lower()
        on_statement_page = any(h in low for h in _STATEMENT_HEADER_HINTS)
        on_anchor_page = anchor_page is not None and page_idx == anchor_page
        for alias in aliases:
            search_from = 0
            while True:
                pos, end = _fuzzy_find(low, alias, search_from)
                if pos == -1:
                    break
                search_from = end
                trailing = low[end:end + 20]
                # "total equity" is a genuine SUBSTRING of the Balance Sheet's
                # own page-grand-total caption "TOTAL EQUITY AND LIABILITIES"
                # (Total Equity + Total Liabilities combined, not equity
                # alone) - confirmed real on ASIANPAINT: the "equity" alias
                # matched that caption and read 34,534.49 (the WHOLE balance
                # sheet total) as "equity", corrupting BVPS/P-B (implied
                # BVPS ~360 instead of the correct ~223), exactly the same
                # false-match this codebase's OWN narrow parser
                # (`_EQUITY_SHARE_CAPITAL_LABELS`'s comment in
                # tools/annual_report_financials.py) already documented and
                # worked around for a different extraction path - this
                # second, simpler alias-matcher never got the same guard.
                if ("ratio" in trailing or "turnover" in trailing or "and liabilit" in trailing
                        or "recognised under" in trailing or "recognized under" in trailing
                        or "previous gaap" in trailing):
                    continue  # a ratio-analysis table row, or an Ind AS transition/previous-GAAP
                              # reconciliation note row, not the raw current-period line item
                # Ind AS 33's own mandated EPS-methodology sentence
                # ("Basic/diluted earnings per share is computed by dividing
                # ... by the weighted average number of equity shares
                # outstanding during the period") is boilerplate every
                # company's EPS note carries, and its trailing text has no
                # number nearby worth reading - but "shares_outstanding"'s
                # own generic aliases ("number of equity shares outstanding")
                # are a literal substring of it. Confirmed real on TCS: this
                # sentence's own aftermath contains an unrelated "31" (from
                # "...outstanding during the period. The Company did not
                # have...(H crore) Year ended March 31...") that got read as
                # the share COUNT (31 instead of the real ~361.8 Cr),
                # corrupting every market-cap-dependent ratio (BVPS, P/B,
                # P/S, EV/Sales, EV/FCF, Price/Cash Flow). Generic guard, not
                # scoped to shares_outstanding alone - this exact phrase
                # combination never legitimately precedes/follows any OTHER
                # line item's real figure either.
                preceding = low[max(0, pos - 25):pos]
                if "weighted average" in preceding and "during the period" in trailing:
                    continue
                value, unit = _extract_best_number(text[end:end + 160])
                if value is None:
                    continue
                if exclude_percent and unit == "%":
                    continue
                confidence = 0.7
                if on_statement_page:
                    confidence += 0.15
                if on_anchor_page:
                    confidence += 0.5  # decisive - this IS the statement for this item
                if alias == aliases[0]:
                    confidence += 0.05
                candidate = {"value": value, "unit": unit, "page": page_idx + 1,
                             "evidence": text[pos:pos + 160].strip(), "confidence": min(confidence, 1.4),
                             "source": "Annual Report"}
                if best is None or candidate["confidence"] > best["confidence"]:
                    best = candidate
    if best is not None:
        best["confidence"] = min(best["confidence"], 0.97)
    return best


# Best-effort XBRL Ind-AS tag names per line item - used as a structured
# cross-check/primary source when a manual XBRL filing was uploaded.
_XBRL_TAGS = {
    "revenue": ["RevenueFromOperations"],
    "pat": ["ProfitLossForPeriod"],
    "pbt": ["ProfitBeforeExceptionalItemsAndTax", "ProfitBeforeTax"],
    "inventory": ["Inventories"],
    "cash": ["CashAndCashEquivalents"],
    "total_debt": ["Borrowings", "LongtermBorrowings"],
    "equity": ["Equity", "TotalEquity"],
    # Extended coverage - standard Ind-AS/in-bse-fin taxonomy element names,
    # for when a genuine Financial Results/Statement XBRL (not e.g. a
    # Corporate Announcement filing uploaded into the wrong slot) is
    # available. A tag absent from a given filing simply yields no cross-
    # check for that fact, never a fabricated one.
    "total_assets": ["Assets"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "receivables": ["TradeReceivablesCurrent", "TradeReceivables"],
    "payables": ["TradePayablesCurrent", "TradePayables"],
    "interest_expense": ["FinanceCosts"],
    "tax": ["CurrentTax", "TaxExpense"],
    "depreciation": ["DepreciationDepletionAndAmortisationExpense"],
    "eps": ["BasicEarningsPerEquityShare"],
    "shares_outstanding": ["NumberOfSharesOutstanding"],
}


def _search_xbrl(symbol, key):
    try:
        from tools.nse_xbrl import _manual_xbrl_path, _parse_xbrl, _latest_instant_value, _annual_context, _fact_in_context
        import os
        p = _manual_xbrl_path(symbol)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            contexts, facts = _parse_xbrl(fh.read())
        for tag in _XBRL_TAGS.get(key, []):
            inst = _latest_instant_value(contexts, facts, tag)
            if inst:
                return {"value": round(inst[1] / 1e7, 2), "unit": "crore", "page": None,
                        "evidence": f"XBRL tag {tag} = {inst[1]}", "confidence": 0.95, "source": "NSE/BSE XBRL"}
            acid = _annual_context(contexts, facts, probe_tag="RevenueFromOperations")
            if acid:
                v = _fact_in_context(facts, tag, acid)
                if v is not None:
                    return {"value": round(v / 1e7, 2), "unit": "crore", "page": None,
                            "evidence": f"XBRL tag {tag} = {v}", "confidence": 0.95, "source": "NSE/BSE XBRL"}
        return None
    except Exception:
        return None


def _manual_xbrl_allowed():
    """Uploaded-XBRL facts belong to the manual document pipeline only; another pipeline asking for a specific year must not pick up
    a stale uploaded file from a different period."""
    from tools.manual_mode import is_manual_mode
    return is_manual_mode()


def extract_line_items(symbol, fiscal_year=None):
    """Returns {key: {value, unit, page, evidence, confidence, source} or None, ...}
    for every canonical line item, sourced from XBRL first (structured,
    higher confidence) then the uploaded Annual Report text. Never
    fabricates - a key with no confident match is None."""
    import time
    sym = symbol.strip().upper().replace(".NS", "")
    t0 = time.time()
    from tools.ar_document_cache import get_ar_pages
    ar = get_ar_pages(sym, sym, fiscal_year=fiscal_year)         # a requested year is read as THAT year in every pipeline
    pages = ar.get("pages") or []
    print(f"[document_analysis] [DOCUMENT] {sym}: Annual Report - {len(pages)} pages "
          f"({'from cache' if ar.get('text_from_cache') else 'freshly parsed'}) in {time.time()-t0:.2f}s")
    t1 = time.time()
    # EPS/Dividend-per-Share now anchor to the SAME Consolidated-first P&L
    # page as every other P&L line item (Revenue/PAT/EBITDA/...) - a prior
    # version of this function anchored them to the Standalone P&L
    # specifically, but that broke internal consistency with the rest of
    # the 68-ratio framework (Net Profit Margin/ROE/ROCE/BVPS/Dividend
    # Payout all read Consolidated-first PAT/equity) and wasn't backed by
    # the project's own Excel/framework spec, which doesn't document a
    # Standalone-only rule for EPS at all. Reverted per the project's
    # explicit "Consolidated-first, Standalone-fallback" policy decision -
    # this is a project-wide rule, not conditioned on any specific company.
    anchors = _find_anchor_pages(pages) if pages else {}
    print(f"[document_analysis] [DOCUMENT] {sym}: anchor pages (balance sheet/P&L/cash flow) located in {time.time()-t1:.2f}s")

    t2 = time.time()
    out = {}
    for key, aliases in _LINE_ITEM_ALIASES.items():
        xbrl_hit = _search_xbrl(sym, key) if _manual_xbrl_allowed() else None
        ar_hit = None
        if pages:
            # Page-anchored, unit-normalized, current/prior-column-correct
            # extraction is tried FIRST when this item's statement has a
            # known anchor page - reads directly from that ONE page rather
            # than scanning the whole document, so it can't mix a Standalone
            # page's figure with a Consolidated one, or a prior-year
            # restatement elsewhere with the current year's real column.
            anchor_page_idx = anchors.get(_category_for(key))
            if anchor_page_idx is not None:
                unit_mult = 1.0 if key in _UNSCALED_ITEMS else _page_unit_multiplier(pages[anchor_page_idx])
                # Schedule III-mandated split items (Trade Payables MSME/
                # non-MSME, Borrowings Non-Current/Current) - a single-alias
                # match only ever finds one sub-item's own figure or the
                # bare split heading with no figure; sum every sub-item
                # instead. Tried first for these keys since it's the
                # correct total, not a fallback.
                if key in _SUM_GROUPS:
                    total_cur, total_prior = _sum_from_anchor_page(pages[anchor_page_idx], _SUM_GROUPS[key], unit_mult)
                    if total_cur is not None:
                        ar_hit = {"value": total_cur, "prior_value": total_prior, "unit": "crore",
                                  "evidence": f"Sum of {_SUM_GROUPS[key]} sub-items on this page",
                                  "confidence": 0.95, "page": anchor_page_idx + 1, "source": "Annual Report"}
                if ar_hit is None:
                    anchored = _extract_from_anchor_page(pages[anchor_page_idx], aliases, unit_mult, exclude_percent=True,
                                                          permissive=(key == "equity_share_capital"))
                    if anchored is not None:
                        ar_hit = {**anchored, "page": anchor_page_idx + 1, "source": "Annual Report"}
                # current_assets/current_liabilities: try the CORRECT
                # anchor page's own bare (unlabelled) subtotal BEFORE ever
                # falling to a whole-document scan. Some filers' Balance
                # Sheet has no "Total current assets/liabilities" caption
                # at all (see `_BARE_SUBTOTAL_SECTIONS`'s comment), but
                # coincidentally DO use that exact caption elsewhere in the
                # document (e.g. Bharti Airtel's Schedule III "Additional
                # Information" table breaking down subsidiaries' own
                # standalone assets/liabilities) - a whole-document scan
                # would silently latch onto that unrelated table's numbers
                # instead, since it has no way to know the anchor page's
                # own bare-subtotal fallback exists and is far more
                # trustworthy for this specific page. Confirmed real on
                # Bharti Airtel: the whole-document scan matched "Total
                # current assets 12,158 15,227..." from a subsidiary
                # break-down schedule instead of the real consolidated
                # Balance Sheet total.
                if ar_hit is None and key in _BARE_SUBTOTAL_SECTIONS:
                    bare = _extract_bare_section_subtotal(pages[anchor_page_idx], key, unit_mult)
                    if bare is not None:
                        ar_hit = {**bare, "page": anchor_page_idx + 1, "source": "Annual Report"}
            # Magnitude line items are never legitimately expressed as a "%"
            # in the source text - a percentage hit means the alias matched
            # an unrelated ratio/commentary sentence (confirmed real:
            # "Revenue from Operations ... 82.81% in FY24" from an ESG
            # sourcing paragraph, not the P&L revenue figure). Falls back to
            # the whole-document scan only when the anchor page itself
            # didn't carry this specific label.
            if ar_hit is None:
                ar_hit = _search_ar_pages(pages, aliases, anchor_page=anchor_page_idx, exclude_percent=True)
            if ar_hit is None and key == "shares_outstanding":
                recon = _extract_shares_outstanding_from_reconciliation(pages)
                if recon is not None:
                    ar_hit = {**recon, "page": None, "source": "Annual Report"}
                else:
                    paidup = _extract_shares_outstanding_from_paidup_sentence(pages)                         or _extract_shares_outstanding_from_class_row(pages)
                    if paidup is not None:
                        ar_hit = {**paidup, "page": None, "source": "Annual Report"}

        if xbrl_hit is not None and ar_hit is not None:
            # Cross-check: both sources found a value for the same concept.
            # Same unit basis (both already normalized to crore) needed for
            # a fair comparison - a >5% relative difference is flagged as a
            # genuine disagreement rather than silently picking one.
            same_unit = (xbrl_hit.get("unit") or "crore") == (ar_hit.get("unit") or "crore")
            if same_unit and xbrl_hit["value"] and abs(xbrl_hit["value"] - ar_hit["value"]) / abs(xbrl_hit["value"]) > 0.05:
                xbrl_hit = {**xbrl_hit, "conflict": True,
                            "evidence": xbrl_hit["evidence"] + f" (Annual Report shows {ar_hit['value']} - sources disagree)"}
            hit = xbrl_hit
        else:
            hit = xbrl_hit if xbrl_hit is not None else ar_hit
        # Capex is a Cash Flow Statement investing-activities OUTFLOW, shown
        # in parentheses (negative) in the source like every other outflow
        # on that statement - but every ratio using it (FCF = OCF - Capex,
        # Capex Intensity = Capex / Revenue) expects it as a positive spend
        # amount, per the registry's own formula convention. Normalize the
        # sign here, once, at the source, rather than in every consumer.
        if key == "shares_outstanding" and hit is not None and hit.get("prior_value") is None \
                and hit.get("page") and pages:
            _prior_sh = _shares_prior_from_page(pages[hit["page"] - 1], aliases)
            if _prior_sh is not None:
                hit = {**hit, "prior_value": _prior_sh}
        if key == "capex" and hit is not None:
            hit = {**hit, "value": abs(hit["value"]) if hit.get("value") is not None else None,
                   "prior_value": abs(hit["prior_value"]) if hit.get("prior_value") is not None else None}
        # "dividend per share" is a common alias phrase that ALSO appears
        # verbatim as a column header in the "Unclaimed/Unpaid Dividend ->
        # IEPF Transfer" disclosure table every Indian listed company
        # prints (a Companies Act requirement, generic, not company-
        # specific) - that table lists PAST years' dividends alongside
        # their IEPF transfer due-dates, and a plain alias match can lock
        # onto a YEAR from that table (e.g. "2018") as if it were a rupee
        # DPS amount. It also appears in MD&A narrative comparison
        # sentences ("dividend per share has risen from Rs 7.5 to Rs
        # 27.5..."), where the number-window can grab an unrelated nearby
        # figure instead of the actual current-year disclosure. Confirmed
        # real on CIPLA (matched the IEPF table, read "2018" as Rs 2018/
        # share) and ASIANPAINT (matched MD&A narrative, read a negative
        # value) - both fed an impossible Dividend Yield (140% and -0.98%
        # respectively). Reject the match generically when its own
        # evidence text contains "iepf" (the universal, Companies-Act-
        # mandated unclaimed-dividend fund name, never legitimately near a
        # genuine current-year DPS row) or when the value itself is
        # obviously not a per-share rupee figure (a 4-digit number in the
        # "looks like a calendar year" range, or negative - DPS is never
        # negative) - falls back to None (honest "not found"), never a
        # fabricated correct value, so the existing "no dividend found ->
        # confirmed 0 at reduced confidence" policy still applies.
        if key == "dividend_per_share" and hit is not None:
            evidence_low = (hit.get("evidence") or "").lower()
            val = hit.get("value")
            implausible = (val is not None and (val < 0 or 1900 <= val <= 2100))
            if "iepf" in evidence_low or implausible:
                hit = None
        out[key] = hit

    # EBIT/EBITDA are almost never printed as their own single labeled row
    # on an Indian P&L (Schedule III shows "Profit Before Tax" as the
    # bottom-line subtotal, with Finance Costs and Depreciation as separate
    # expense lines above it) - a bare "ebit"/"ebitda" alias search matches
    # whatever unrelated text happens to contain those words elsewhere in
    # the document (confirmed real: landed on an MD&A page, nowhere near
    # the actual P&L, giving an implausible small number). Derive both
    # instead from the now page-anchored, unit-correct PBT/Finance Costs/
    # Depreciation - the standard, generic definition (EBIT = PBT + Finance
    # Costs; EBITDA = EBIT + Depreciation & Amortisation), not a per-ticker
    # rule. Only overrides when the raw alias search landed off this item's
    # own P&L anchor page (page-anchored PBT/interest/depreciation hits are
    # trustworthy; a genuine same-page EBIT/EBITDA row, if ever found, is
    # left as-is).
    pl_anchor = anchors.get("profit_loss")
    pbt_hit, interest_hit, dep_hit = out.get("pbt"), out.get("interest_expense"), out.get("depreciation")
    on_pl_anchor = (pl_anchor is not None and pbt_hit and interest_hit
                    and pbt_hit.get("page") == pl_anchor + 1 and interest_hit.get("page") == pl_anchor + 1)
    if on_pl_anchor and (out.get("ebit") is None or out["ebit"].get("page") != pl_anchor + 1):
        ebit_val = round(pbt_hit["value"] + interest_hit["value"], 4)
        out["ebit"] = {"value": ebit_val, "prior_value": (
            round(pbt_hit["prior_value"] + interest_hit["prior_value"], 4)
            if pbt_hit.get("prior_value") is not None and interest_hit.get("prior_value") is not None else None),
            "unit": "crore", "page": pl_anchor + 1, "confidence": 0.95, "source": "Annual Report",
            "evidence": "Derived: Profit Before Tax + Finance Costs (Schedule III P&L)"}
        if dep_hit and dep_hit.get("page") == pl_anchor + 1:
            ebitda_val = round(ebit_val + dep_hit["value"], 4)
            out["ebitda"] = {"value": ebitda_val, "prior_value": (
                round(out["ebit"]["prior_value"] + dep_hit["prior_value"], 4)
                if out["ebit"].get("prior_value") is not None and dep_hit.get("prior_value") is not None else None),
                "unit": "crore", "page": pl_anchor + 1, "confidence": 0.95, "source": "Annual Report",
                "evidence": "Derived: EBIT + Depreciation and Amortisation (Schedule III P&L)"}

    print(f"[document_analysis] [FACTS] {sym}: {sum(1 for v in out.values() if v)}/{len(out)} line items "
          f"extracted in {time.time()-t2:.2f}s")
    return out


# ---------------------------------------------------------------------------
# Fundamental: 68-ratio orchestrator (tools/fundamental_ratio_registry.py is
# the authoritative Sr 1-68 framework, transcribed from the Excel). Runs
# entirely inside tools/manual_mode.py's guard, so every reused
# tools.nse_xbrl fetch_* call is confined to the uploaded Annual Report/
# XBRL/Shareholding Pattern (never live NSE/BSE/yfinance/shareholding-
# scraper) - see that module's docstring.
# ---------------------------------------------------------------------------

def _v(items, key):
    hit = items.get(key)
    return hit["value"] if hit else None


def _document_source_label(sym):
    """(source_file, source_type) for Strategy-C's Annual-Report-only
    extraction (`extract_line_items()` never reads Shareholding Pattern/
    market data - that's kept in a strictly separate layer per this
    module's own architecture, see `_local_group_c`'s docstring), derived
    from the SAME on-disk document-identity lookup every other cache/source
    label in this codebase already uses - never fabricated, "Not available"
    when no document is actually on record for this symbol."""
    try:
        from tools.ar_document_cache import manual_cached_years
        years = manual_cached_years(sym)
        if years:
            return f"{sym}_{years[0]}.pdf (uploaded Annual Report)", "Annual Report"
    except Exception:
        pass
    return "Not available", "Not available"


def _inputs_for(items, keys, sym=None):
    src_file, src_type = _document_source_label(sym) if sym else ("Not available", "Not available")
    out = []
    for k in keys:
        hit = items.get(k)
        out.append({
            "name": k, "value": hit["value"] if hit else None, "unit": hit["unit"] if hit else None,
            "source": hit["source"] if hit else None, "page": hit["page"] if hit else None,
            "source_file": src_file if hit else "Not available",
            "source_type": src_type if hit else "Not available",
            "section": (hit.get("evidence", "")[:60] + "...") if hit and hit.get("evidence") else "Not available",
            "evidence": hit.get("evidence") if hit else None,
            "confidence": hit.get("confidence") if hit else None,
        })
    return out


def _synthesize_reason(ratio_def, status, inputs, derived_from=None):
    """Generic, non-fabricated human-readable explanation for why a ratio's
    status isn't 'verified' - built ENTIRELY from evidence already present
    on this row (which of its own `inputs` came back with value=None,
    which of its `derived_from` dependencies aren't themselves resolved,
    or an existing `reason`/`sector` explanation a Strategy-A nse_xbrl
    fetcher or the bank-sector gate already attached) - never a generic
    boilerplate sentence, and never company-specific (built the same way
    for every symbol/ratio). Returns None for 'verified'/'needs_review'
    (those already show their own real evidence in `inputs`)."""
    if status in ("verified", "needs_review"):
        return None

    # An upstream fetcher (tools/nse_xbrl.py's fetch_X wrappers, or the
    # bank-sector `not_applicable` gate in run_fundamental_analysis) may
    # already have attached a specific, evidence-based explanation as a
    # "reason" or "sector" input - always prefer that real, already-proven
    # explanation over a synthesized one.
    for inp in inputs:
        if inp.get("name") in ("reason", "sector") and inp.get("source"):
            return inp["source"]

    if status == "not_applicable":
        return (f"{ratio_def['label']} applies to a specific business type (e.g. Banks/NBFCs) that "
                f"this company is not classified as.")

    if status == "insufficient_data":
        return (f"{ratio_def['label']} requires external data (e.g. market price, beta, or other "
                f"market-sourced input) that could not be retrieved right now - not something the "
                f"Annual Report itself would disclose.")

    # not_disclosed: point at the SPECIFIC missing input(s) this ratio's own
    # `inputs` list already recorded as value=None, rather than a vague
    # "data not found" - `_inputs_for`/`inp_with_price` build every input
    # entry (found or not) the same way, so `value is None` is an honest,
    # already-computed signal of exactly what's missing, not a guess.
    missing = sorted({inp["name"].replace("_", " ") for inp in inputs
                       if inp.get("name") not in ("reason", "sector", "market_price")
                       and inp.get("value") is None})
    if missing:
        return (f"Required input(s) - {', '.join(missing)} - could not be found in the uploaded "
                f"Annual Report (or, for ratios needing it, current market data).")
    if any(inp.get("name") == "market_price" and inp.get("value") is None for inp in inputs):
        return "Requires a live market price, which could not be retrieved right now."
    if derived_from:
        broken = [d for d in derived_from if d.get("status") not in ("verified", "needs_review")]
        if broken:
            names = ", ".join(d["ratio"] for d in broken)
            return (f"Depends on {names}, which could not itself be calculated from the available "
                     f"documents - see that ratio's own card for the specific missing input.")
    return ("The required underlying financial data could not be located in the uploaded Annual "
            "Report's Balance Sheet, Profit & Loss, or Cash Flow Statement.")


def _row_shell(ratio_def, value, unit, status, inputs, financial_year=None, derived_from=None, meta=None, reason=None):
    inputs = list(inputs)
    if financial_year:
        inputs.append({"name": "financial_year", "value": None, "unit": None,
                        "source": financial_year, "page": None})
    calc_type = "DERIVED" if ratio_def.get("strategy") == "B" else "DIRECT"
    reason = reason or _synthesize_reason(ratio_def, status, inputs, derived_from)
    md = {"name": "_metadata", "value": None, "unit": None, "source": None, "page": None,
          "calculation_type": calc_type, "derived_from": derived_from, "reason": reason,
          "status_detail": status}
    # provenance of the calculation (formula version, statement basis, perimeter, input facts,
    # warnings, timestamp) travels with the stored row so the evidence panel can show exactly what
    # was used and a later formula change can tell this row is stale.
    if meta:
        md.update(meta)
    from tools.ratio_contract import FORMULA_VERSION as _FV
    import datetime as _dtm
    md.setdefault("formula_version", _FV)          # EVERY row is versioned, so staleness is decidable for all
    from tools.ratio_breakdown import BREAKDOWN_VERSION as _BV
    md.setdefault("breakdown_version", _BV)        # rows saved before the calculation breakdown existed are refreshed on read
    md.setdefault("calculated_at", _dtm.datetime.now(_dtm.timezone.utc).isoformat())
    inputs.append(md)
    row = {
        "ratio_key": ratio_def["ratio_key"], "label": ratio_def["label"],
        "category": ratio_def["category"], "value": value, "unit": unit,
        "status": status, "formula": ratio_def["formula"], "inputs": inputs,
    }
    return row


def _source_file_and_type(pdf_url, sources):
    """Derives a human-readable (source_file, source_type) pair PURELY from
    data already present in a fetch_X()/fetch_X_from_annual_report()
    response - never fabricated.

    `source_type` is read from the response's OWN `sources[0]["label"]`
    whenever that label already identifies a non-Annual-Report document
    (e.g. "NSE Shareholding Pattern") - confirmed real bug in an earlier
    version of this helper: it assumed EVERY http(s) `source_url` meant
    "Annual Report", which silently mislabeled Promoter Pledge/Free Float
    (Sr No 67/68, genuinely sourced from the Shareholding Pattern filing,
    a live NSE endpoint with its own https URL) as "Annual Report" - exactly
    the "say Annual Report when the value came from another file" failure
    this task explicitly warned against. Falls back to "Annual Report" only
    when the label is a plain statement name (P&L/Balance Sheet/Cash Flow)
    that this pipeline only ever populates FROM the Annual Report.

    `pdf_url` shapes handled:
      - "manual-upload://{SYMBOL}_{fiscal_year}" (manual document-analysis
        workflow) - the symbol/year are literally encoded in the marker
        itself, a direct readout, not a guess.
      - a real https:// URL (BSE/NSE Annual Report archive, OR an NSE
        Shareholding Pattern endpoint, OR similar) - the URL's own filename/
        path component is used as-is; the TYPE comes from the label logic
        above, not from the URL shape.
      - None/empty - "Not available", never defaulted to "Annual Report"."""
    label = (sources[0] if sources else {}).get("label", "")
    label_low = label.lower()
    if "shareholding" in label_low:
        source_type = "Shareholding Pattern"
    elif "xbrl" in label_low:
        source_type = "XBRL Filing"
    elif label_low in ("p&l", "balance sheet", "cash flow", "cash flow statement", ""):
        source_type = "Annual Report"
    else:
        # An unrecognised label is preserved as-is rather than guessed into
        # "Annual Report" - honest, even if less tidy than a fixed category.
        source_type = label or "Not available"

    if not pdf_url:
        return "Not available", source_type
    if pdf_url.startswith("manual-upload://"):
        marker = pdf_url[len("manual-upload://"):]
        return f"{marker}.pdf (uploaded Annual Report)", source_type
    if pdf_url.startswith("http"):
        fname = pdf_url.rstrip("/").rsplit("/", 1)[-1] or pdf_url
        return fname, source_type
    return "Not available", source_type


def _meta_from_out(out):
    keys = ("formula_version", "calculated_at", "warnings", "perimeter", "statement_basis", "period_basis",
            "methodology", "confidence", "provenance", "estimated", "breakdown")
    return {k: out.get(k) for k in keys if out.get(k) not in (None, [], {})}


_ROW_STATUSES = ("verified", "needs_review", "not_meaningful", "insufficient_data", "not_disclosed", "not_applicable")


def _row_from_nse_xbrl_out(ratio_def, out):
    """Adapts a ratio fetch result (the legacy `fetch_X` shape, which the ratio contract now also produces)
    into this table's row shape. Never fabricates: an unresolved value is always status='not_disclosed'/
    'not_applicable'/'insufficient_data' with value=None, never a guessed number. When the result carries an
    explicit contract `status` that status IS the row status (it already folds in parent uncertainty,
    estimates, acquisition/perimeter warnings and 'not meaningful' multiples)."""
    meta = _meta_from_out(out)
    if "breakdown" not in meta and (out.get("numerator") and out.get("denominator")):
        try:                                    # dedicated bank-module results: legacy legs (rounded) -> same payload
            from tools.ratio_breakdown import legacy_breakdown
            _bd = legacy_breakdown(ratio_def["ratio_key"], out, ratio_def.get("formula"))
            if _bd:
                meta["breakdown"] = _bd
        except Exception as _e:
            print(f"[document_analysis] legacy breakdown failed for {ratio_def.get('ratio_key')}: {_e}")
    st_in = out.get("status")
    if st_in == "insufficient_data":
        return _row_shell(ratio_def, None, None, "insufficient_data",
                           [{"name": "reason", "value": None, "unit": None, "source": out.get("reason"), "page": None}],
                           meta=meta, reason=out.get("reason"))
    if not out.get("applicable", True) and st_in != "not_meaningful":
        reason = (out.get("reason") or "")
        if st_in in ("not_applicable", "not_disclosed"):
            status = st_in
        else:
            status = ("not_applicable"
                      if ("not applicable" in reason.lower() or out.get("net_cash"))
                      else "not_disclosed")
        return _row_shell(ratio_def, None, None, status,
                           [{"name": "reason", "value": None, "unit": None, "source": reason, "page": None}],
                           meta=meta, reason=reason or None)
    value = out.get("mathematical_value") if st_in == "not_meaningful" else out.get("value")
    if value is None:
        if st_in == "not_meaningful":
            # the contract withheld the number on purpose (negative EPS/equity/FCF...): that is "not meaningful", never
            # "not disclosed" - the data WAS found, the ratio just has no economic meaning
            return _row_shell(ratio_def, None, None, "not_meaningful", [], meta=meta, reason=out.get("reason"))
        return _row_shell(ratio_def, None, None, "not_disclosed", [], meta=meta, reason=out.get("reason"))
    confidence = out.get("confidence")
    if st_in in ("verified", "needs_review", "not_meaningful"):
        status = st_in
    else:
        status = "needs_review" if (out.get("estimated") or (confidence is not None and confidence < 0.85)) else "verified"
    inputs = []
    sources = out.get("sources") or []
    source_label = (sources[0] if sources else {}).get("label", "Uploaded document")
    pdf_url = out.get("source_url") or (sources[0]["url"].split("#page=")[0] if sources else None)
    src_file, src_type = _source_file_and_type(pdf_url, sources)
    single_page = sources[0].get("url", "").split("page=")[-1] if len(sources) == 1 and "page=" in sources[0].get("url", "") else None

    def _evidence(label):
        return {"source_file": src_file, "source_type": src_type,
                "section": label if len(sources) > 1 else source_label,
                "page": single_page or "Not available"}

    line_items = out.get("line_items")
    if line_items:
        for li in line_items:
            inputs.append({"name": li.get("label"), "value": li.get("value_cr"), "unit": "cr",
                            "source": source_label, "page": None, **_evidence(li.get("label"))})
    else:
        for side in ("numerator", "denominator"):
            d = out.get(side)
            if d:
                inputs.append({"name": d.get("label", side), "value": d.get("value_cr"), "unit": d.get("unit") or "cr",
                                "source": d.get("source") or source_label, "page": None, **_evidence(d.get("label", side))})
    try:
        value = round(float(value), 4)
    except (TypeError, ValueError):
        pass
    return _row_shell(ratio_def, value, out.get("unit") or "", status, inputs, financial_year=out.get("selected_period"),
                      meta=meta, reason=out.get("reason") or (("; ".join(out.get("warnings") or [])) or None))


def _call_nse_xbrl(fn_name, symbol, name, lender=False):
    """Every Strategy-A ratio funnels through here, running on a shared
    ThreadPoolExecutor (_QUALITATIVE_WORKERS concurrent workers) that all
    hit the SAME on-disk PDF-extraction cache (tools.annual_report_
    financials._read_cache/_write_cache) for the same document at once -
    confirmed real: a transient hiccup (a concurrent cache read racing a
    sibling worker's write, a momentary network blip on the one live-price
    call this pipeline makes) intermittently raised inside one specific
    ratio's fetch_X call while the other 60+ ratios in the same batch
    succeeded, silently persisting as a false 'not_disclosed' with no
    retry at all - indistinguishable from the document genuinely lacking
    that data. One retry (a fresh call, not a cached failure) is enough
    to absorb this kind of one-off flakiness without masking a genuine,
    repeatable extraction gap - a real "not found in the P&L" failure
    reproduces identically on the retry and is still reported honestly."""
    import tools.nse_xbrl as nse_xbrl
    fn = getattr(nse_xbrl, fn_name)
    with nse_xbrl.lender_context(lender):        # sector-based lender gating (not just company-name keywords)
        try:
            return fn(symbol, name)
        except Exception as e:
            print(f"[document_analysis] {fn_name}({symbol}) failed, retrying once: {e}")
            return fn(symbol, name)






def rc_bounds(key):
    from tools.ratio_contract import BANK_BOUNDS
    return BANK_BOUNDS[key]


def _local_bank_group_c(sr_no, items, sym=None):
    """Bank-only Strategy-C ratios (Sr 62 PCR, Sr 64 Credit-to-Deposit) computed from the document's own
    banking line items. Every non-bank Strategy-C ratio now comes from `tools.ratio_contract`.
    Returns (value, unit, status, inputs, extra)."""
    def num(key):
        h = items.get(key)
        return h["value"] if h else None

    def inp(*keys):
        return _inputs_for(items, list(keys), sym=sym)

    if sr_no == 62:  # PCR = Total Provisions / Gross NPA
        prov, npa = num("total_provisions"), num("gross_npa")
        if prov is None or npa is None or npa == 0:
            return None, None, "not_disclosed", inp("total_provisions", "gross_npa"), {}
        v = prov / npa * 100
        lo, hi = rc_bounds("provision_coverage_ratio")
        if not lo <= v <= hi:
            return None, None, "insufficient_data", inp("total_provisions", "gross_npa"), {}
        return round(v, 4), "%", "verified", inp("total_provisions", "gross_npa"), {}
    if sr_no == 64:  # Credit-to-Deposit = Advances / Deposits
        adv, dep = num("advances"), num("deposits")
        if adv is None or dep is None or dep == 0:
            return None, None, "not_disclosed", inp("advances", "deposits"), {}
        v = adv / dep * 100
        lo, hi = rc_bounds("credit_to_deposit_ratio")
        if not lo <= v <= hi:
            return None, None, "insufficient_data", inp("advances", "deposits"), {}
        return round(v, 4), "%", "verified", inp("advances", "deposits"), {}
    return None, None, "not_disclosed", [], {}


_DB_STATUSES = ("verified", "needs_review", "not_disclosed", "not_applicable", "insufficient_data")


def _db_status(status):
    """`fundamental_analysis_results.status` carries a CHECK constraint that predates 'not_meaningful'. The true
    status is always stored in the row's `_metadata.status_detail` and restored on read (see
    `regroup_fundamental_rows`), so no schema migration is needed; a not-meaningful multiple is parked in the
    column as 'needs_review' (it is never a verified number)."""
    return status if status in _DB_STATUSES else "needs_review"


def _persist_fundamental_rows(sb, sym, results_rows):
    """Upserts the computed rows. `computed_at` is written EXPLICITLY on every upsert: the column default only
    fires on INSERT, so without this a recalculated row kept its first-ever timestamp. Statuses are written
    in their DB-constraint-safe form (see `_db_status`); the true status lives in `_metadata.status_detail`."""
    import time
    import datetime as _dt
    stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    rows = [{"symbol": sym, "computed_at": stamp, **r, "status": _db_status(r["status"])} for r in results_rows]
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        for attempt in range(3):
            try:
                sb.table("fundamental_analysis_results").upsert(batch, on_conflict="symbol,ratio_key").execute()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"[document_analysis] [DATABASE] {sym}: fundamental batch write failed (attempt {attempt+1}): {e} - retrying")
                time.sleep(0.3 * (3 ** attempt))
    return len(rows)


def _like(ratio_def, out, row):
    """Result-shaped view of a computed row (what the contract's derived ratios consume as a parent)."""
    raw = out.get("value_raw") if out.get("value_raw") is not None else row.get("value")
    return {"ratio_key": ratio_def["ratio_key"], "label": ratio_def["label"], "value_raw": raw,
            "status": row["status"], "confidence": out.get("confidence") if out.get("confidence") is not None else 1.0,
            "estimated": bool(out.get("estimated")), "warnings": out.get("warnings") or [], "reason": out.get("reason"),
            "unit": row.get("unit"), "breakdown": out.get("breakdown")}


# Ratios that have no meaning for a lender (its balance sheet is loans and deposits): working capital, enterprise-value
# multiples (debt is raw material, not capital structure), free-cash-flow yields and price/sales. A lender whose statements are
# not Schedule III (RBI format) is therefore Not Applicable for them rather than "could not be read".
_LENDER_NA_KEYS = {"working_capital", "ps_ratio", "ev_to_ebitda", "fcf_yield", "ev_to_sales", "ev_to_fcf", "price_to_cash_flow"}
_LENDER_NA_REASON = ("Not applicable - this is a lender (Banks/NBFC sector): working capital, enterprise-value, free-cash-flow "
                     "and price/sales measures are not defined for a balance sheet made of loans and deposits.")


def run_fundamental_analysis(symbol, name=None):
    """Computes all 68 ratios from tools/fundamental_ratio_registry.py and
    persists them to fundamental_analysis_results (upsert on
    symbol+ratio_key) - always exactly 68 rows, each with an honest status
    (verified/needs_review/not_meaningful/not_disclosed/not_applicable/insufficient_data),
    never a fabricated value just to make the count look complete.

    Every non-bank ratio is computed by `tools.ratio_contract` from the ONE normalized FactSet
    (Strategy A rows through the legacy fetch adapters, Strategy C/B directly), so this table, the
    dashboard endpoints and the canonical API cannot disagree. Rows carry the formula version,
    statement basis, perimeter, input facts and a fresh `computed_at`.

    Runs entirely inside tools/manual_mode.py's guard - see that module's
    docstring for why every reused tools.nse_xbrl fetcher is safe to call
    here without reaching live NSE/BSE/yfinance/shareholding-scraper."""
    import time
    import datetime as _dt
    from tools.fundamental_ratio_registry import RATIOS, COMPUTE_ORDER, BY_SR_NO
    from tools.sector_ratio_applicability import is_bank_ratio_applicable
    from tools.nse_sector_map import get_nse_sector
    from tools.market_price import get_live_price
    from tools.manual_mode import manual_mode
    from tools import ratio_contract as rc

    sym = symbol.strip().upper().replace(".NS", "")
    t0 = time.time()

    with manual_mode():
        sector = get_nse_sector(sym)
        bank_ok = is_bank_ratio_applicable(sector)
        items = extract_line_items(sym)  # banking line items for the bank-only Strategy-C ratios
        bse_code = None
        try:
            from tools.supabase_client import get_client as _get_sb
            _rows = _get_sb().table("companies").select("bse_code").eq("symbol", sym).limit(1).execute().data
            bse_code = (_rows[0].get("bse_code") if _rows else None)
        except Exception:
            pass
        price = get_live_price(sym, bse_code=bse_code)  # market-price layer, kept separate - never used for any facts
        market = {"price": float(price["ltp"]), "source": price.get("source") or "unknown",
                  "as_of": "live quote", "prev_close": price.get("close"),
                  "quoted_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                  } if price and price.get("ltp") else None

        # ONE fact set for the whole run (same document the Strategy-A fetchers read)
        fs, fy = None, None
        try:
            from tools.ar_document_cache import get_ar_pages
            from tools.fundamental_fact_store import get_canonical_facts
            fy = (get_ar_pages(sym, sym) or {}).get("fiscal_year")
            if fy:
                _fs = get_canonical_facts(sym, name, fy)
                fs = None if _fs.facts.get("_error") else _fs
        except Exception as e:
            print(f"[document_analysis] fact set unavailable for {sym}: {e}")

        results = {}      # ratio_key -> result-shaped dict (parents for derived ratios)
        rows_by_sr = {}

        ac_sr_nos = [sr_no for sr_no in COMPUTE_ORDER if BY_SR_NO[sr_no]["strategy"] != "B"]
        b_sr_nos = [sr_no for sr_no in COMPUTE_ORDER if BY_SR_NO[sr_no]["strategy"] == "B"]

        def _compute_ac(sr_no):
            ratio_def = BY_SR_NO[sr_no]
            try:
                with manual_mode():
                    if ratio_def.get("bank_only") and not bank_ok:
                        sector_label = sector or "this company's sector"
                        row = _row_shell(ratio_def, None, None, "not_applicable",
                                          [{"name": "sector", "value": None, "unit": None,
                                            "source": (f"{ratio_def['label']} is a banking/NBFC-specific ratio and "
                                                       f"is not applicable to {sector_label} companies."),
                                            "page": None}])
                        return sr_no, row, None

                    if ratio_def["strategy"] == "A":
                        out = _call_nse_xbrl(ratio_def["nse_xbrl_fn"], sym, name, lender=bank_ok)
                        row = _row_from_nse_xbrl_out(ratio_def, out)
                        return sr_no, row, _like(ratio_def, out, row)
                    # strategy "C": contract ratios from the fact set; bank-only ones from banking line items
                    if ratio_def["ratio_key"] in rc.COMPUTABLE:
                        if bank_ok and ratio_def["ratio_key"] in _LENDER_NA_KEYS:
                            row = _row_shell(ratio_def, None, None, "not_applicable", [], reason=_LENDER_NA_REASON)
                            return sr_no, row, {"ratio_key": ratio_def["ratio_key"], "label": ratio_def["label"], "value_raw": None,
                                                "status": "not_applicable", "confidence": 0.0, "estimated": False,
                                                "warnings": [], "reason": _LENDER_NA_REASON, "unit": None}
                        if fs is None:
                            row = _row_shell(ratio_def, None, None, "insufficient_data", [],
                                              reason="The uploaded Annual Report's statements could not be read.")
                            return sr_no, row, None
                        from tools.annual_report_financials import _contract_to_legacy
                        res = rc.compute_ratio(ratio_def["ratio_key"], fs, market, {})
                        legacy = _contract_to_legacy(res, fs, fy)
                        row = _row_from_nse_xbrl_out(ratio_def, legacy)
                        return sr_no, row, _like(ratio_def, legacy, row)
                    # PCR (Sr 62) / Credit-to-Deposit (Sr 64): the same identity-checked bank reader as Sr 58-61/63/65
                    import tools.annual_report_financials as _arf
                    _fn = getattr(_arf, f"fetch_{ratio_def['ratio_key']}_from_annual_report", None)
                    if _fn is not None and fy:
                        out = _fn(sym, name, fy, True)
                        row = _row_from_nse_xbrl_out(ratio_def, out)
                        return sr_no, row, _like(ratio_def, out, row)
                    value, unit, status, inputs, _extra = _local_bank_group_c(sr_no, items, sym=sym)
                    row = _row_shell(ratio_def, value, unit, status, inputs)
                    return sr_no, row, _like(ratio_def, {}, row)
            except Exception as e:
                # A bug in ONE ratio's compute logic must never take down the other 60+ ratios in this
                # concurrent batch - report just that one ratio as unavailable.
                print(f"[document_analysis] sr_no={sr_no} ({ratio_def.get('label')}) compute crashed: {e}")
                row = _row_shell(ratio_def, None, None, "not_disclosed",
                                  [{"name": "reason", "value": None, "unit": None,
                                    "source": "An internal error occurred computing this ratio - please report this "
                                              "if it persists on re-analysis.", "page": None}])
                return sr_no, row, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=_QUALITATIVE_WORKERS) as ex:
            for sr_no, row, like in ex.map(_compute_ac, ac_sr_nos):
                rows_by_sr[sr_no] = row
                if like is not None:
                    results[BY_SR_NO[sr_no]["ratio_key"]] = like

        for sr_no in b_sr_nos:
            ratio_def = BY_SR_NO[sr_no]
            key = ratio_def["ratio_key"]
            if (bank_ok and key in _LENDER_NA_KEYS) or fs is None:
                na_parent = next((results[pk] for pk in rc.PARENTS.get(key, []) if (results.get(pk) or {}).get("status") == "not_applicable"), None)
                if na_parent is not None or (bank_ok and key in _LENDER_NA_KEYS):
                    why = (f"{na_parent['label']} is not applicable: {na_parent.get('reason') or ''}" if na_parent is not None
                           else _LENDER_NA_REASON)
                    res = {"ratio_key": key, "label": ratio_def["label"], "value_raw": None, "unit": "x", "status": "not_applicable",
                           "confidence": 0.0, "estimated": False, "warnings": [], "reason": why}
                else:
                    res = {"ratio_key": key, "label": ratio_def["label"], "value_raw": None, "unit": "x",
                           "status": "insufficient_data", "confidence": 0.0, "estimated": False, "warnings": [],
                           "reason": "The uploaded Annual Report's statements could not be read."}
            else:
                deps = {p: results.get(p) for p in rc.PARENTS.get(key, [])}
                res = rc.compute_ratio(key, fs, market, deps)
            needs = ratio_def.get("depends_on", [])
            derived_from = [
                {"sr_no": d, "ratio": BY_SR_NO[d]["label"], "ratio_key": BY_SR_NO[d]["ratio_key"],
                 "value": rows_by_sr[d]["value"] if d in rows_by_sr else None,
                 "unit": rows_by_sr[d]["unit"] if d in rows_by_sr else None,
                 "formula": BY_SR_NO[d]["formula"],
                 "status": rows_by_sr[d]["status"] if d in rows_by_sr else None}
                for d in needs
            ]
            meta = {k: res.get(k) for k in ("formula_version", "perimeter", "period_basis", "methodology", "confidence")
                    if res.get(k) is not None}
            if res.get("warnings"):
                meta["warnings"] = res["warnings"]
            if res.get("breakdown"):
                meta["breakdown"] = res["breakdown"]
            meta["calculated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
            if fs is not None:
                meta["statement_basis"] = "consolidated" if fs.selection.selected_basis == "CONSOLIDATED" else "standalone"
            row = _row_shell(ratio_def, res.get("value_raw"), res.get("unit") or "x", res["status"], [],
                              derived_from=derived_from, meta=meta, reason=res.get("reason"))
            rows_by_sr[sr_no] = row
            results[key] = {**res, "label": ratio_def["label"]}

        results_rows = [rows_by_sr[r["sr_no"]] for r in RATIOS]

    print(f"[document_analysis] [FUNDAMENTAL] {sym}: {len(results_rows)}/68 ratios computed in {time.time()-t0:.2f}s "
          f"({sum(1 for r in results_rows if r['status'] == 'verified')} verified, "
          f"{sum(1 for r in results_rows if r['status'] == 'needs_review')} needs_review, "
          f"{sum(1 for r in results_rows if r['status'] == 'not_meaningful')} not_meaningful, "
          f"{sum(1 for r in results_rows if r['status'] == 'not_disclosed')} not_disclosed, "
          f"{sum(1 for r in results_rows if r['status'] == 'not_applicable')} not_applicable, "
          f"{sum(1 for r in results_rows if r['status'] == 'insufficient_data')} insufficient_data)")

    t2 = time.time()
    from tools.supabase_client import get_client
    n_written = _persist_fundamental_rows(get_client(), sym, results_rows)
    print(f"[document_analysis] [DATABASE] {sym}: {n_written} fundamental rows written in {time.time()-t2:.2f}s")

    return {
        "verified": sum(1 for r in results_rows if r["status"] == "verified"),
        "needs_review": sum(1 for r in results_rows if r["status"] == "needs_review"),
        "not_meaningful": sum(1 for r in results_rows if r["status"] == "not_meaningful"),
        "not_disclosed": sum(1 for r in results_rows if r["status"] == "not_disclosed"),
        "not_applicable": sum(1 for r in results_rows if r["status"] == "not_applicable"),
        "insufficient_data": sum(1 for r in results_rows if r["status"] == "insufficient_data"),
        "total": len(results_rows),
    }


def _row_formula_version(row):
    for i in row.get("inputs") or []:
        if isinstance(i, dict) and i.get("name") == "_metadata":
            return i.get("formula_version")
    return None


def _row_breakdown_version(row):
    for i in row.get("inputs") or []:
        if isinstance(i, dict) and i.get("name") == "_metadata":
            return i.get("breakdown_version")
    return None


def mark_stale_rows(rows):
    """Flags (never hides) rows computed under an older ratio-contract formula version, or before formula
    versions existed - they must not silently pass as current. Bank/not-applicable rows that carry no
    metadata of their own are judged by the rest of the set."""
    from tools.ratio_contract import FORMULA_VERSION
    from tools.ratio_breakdown import BREAKDOWN_VERSION
    out = []
    for r in rows:
        v = _row_formula_version(r)
        out.append({**r, "stale": v != FORMULA_VERSION, "formula_version": v or None,
                    # same numbers, but saved without the calculation breakdown (display provenance) - refreshed on read
                    "breakdown_outdated": _row_breakdown_version(r) != BREAKDOWN_VERSION})
    return out


def get_fundamental_results(symbol):
    sym = symbol.strip().upper().replace(".NS", "")
    from tools.supabase_client import get_client
    sb = get_client()
    rows = sb.table("fundamental_analysis_results").select("*").eq("symbol", sym).execute().data or []
    return mark_stale_rows(regroup_fundamental_rows(rows))


_RECALC_LOCKS = {}
_RECALC_GUARD = threading.Lock()


def ensure_current_fundamental_results(symbol, name=None):
    """Rows computed under an older formula/extraction version are recalculated from the uploaded documents
    on read (once, serialised per symbol) instead of being served as if they were current. If the documents
    are gone or the recalculation fails, the stale rows are still returned - flagged `stale` - never hidden."""
    sym = symbol.strip().upper().replace(".NS", "")
    rows = get_fundamental_results(sym)
    if rows and any(r.get("stale") or r.get("breakdown_outdated") for r in rows):
        with _RECALC_GUARD:
            lock = _RECALC_LOCKS.setdefault(sym, threading.Lock())
        with lock:
            rows = get_fundamental_results(sym)       # another request may have refreshed it meanwhile
            if any(r.get("stale") or r.get("breakdown_outdated") for r in rows):
                try:
                    run_fundamental_analysis(sym, name)
                    rows = get_fundamental_results(sym)
                except Exception as e:
                    print(f"[document_analysis] lazy recalculation failed for {sym}: {e}")
    return rows


def regroup_fundamental_rows(rows):
    """Presentation only: re-labels each stored row's `category` from the
    registry's current classification (rows persisted before the 8-category
    regrouping still carry the old text), applies the current display `label` and
    `display_priority`, and orders them: the 13 display-priority ratios first, then
    category-then-Sr No.
    Values, statuses and inputs are never touched."""
    from tools.fundamental_ratio_registry import BY_RATIO_KEY, CATEGORY_ORDER
    out = []
    for r in rows:
        spec = BY_RATIO_KEY.get(r.get("ratio_key"))
        row = {**r, "category": spec["category"], "sr_no": spec["sr_no"]} if spec else dict(r)
        for i in row.get("inputs") or []:                       # restore the true status (see _db_status)
            if isinstance(i, dict) and i.get("name") == "_metadata" and i.get("status_detail") in (
                    "verified", "needs_review", "not_meaningful", "not_disclosed", "not_applicable", "insufficient_data"):
                row["status"] = i["status_detail"]
        out.append(row)
    from tools.ratio_display import apply_display_names
    out = [apply_display_names(r) for r in out]            # user-facing label + display_priority (presentation only)
    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    # the 13 display-priority ratios first (in their defined order), then the other 55 exactly as before
    out.sort(key=lambda r: (0, r["display_priority"], 0) if r.get("display_priority")
            else (1, rank.get(r.get("category"), len(rank)), r.get("sr_no") or 10**6))
    return out


# ---------------------------------------------------------------------------
# Qualitative: orchestrate the EXISTING A-U framework, unchanged
# ---------------------------------------------------------------------------

def _resolve_compute_fn(dotted_path):
    module_path, func_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


# Tasks whose sourcing genuinely requires something other than the uploaded
# Annual Report/XBRL - peer-quintile market data, CRISIL ratings (as the
# PRIMARY, not merely a cross-check), NSE shareholding-pattern/insider-
# trading/corporate-announcements filings, commodity benchmarks,
# screener.in. Per the strict "uploaded documents only, no external
# financial-data source" rule for this workflow, these are excluded from a
# document-analysis run even though they're perfectly valid for the
# automatic pipeline (which still exists unchanged). None of them require
# an API key - they're free scrapers - but they aren't the uploaded
# document, so they're out of scope here.
#
# Checks the task's own `primary_source` sourcing PATHWAY, not just whether
# a marker word appears anywhere in the text - several AR-primary tasks
# (e.g. A.2.B Distribution) mention CRISIL only as a secondary cross-check
# ("...open Annual Report attachment/PDF → MD&A → ...; cross-check CRISIL/
# ICRA rationale"), and a naive substring match on "crisil" wrongly
# excluded them (confirmed real bug - A.2.B's actual PRIMARY source is the
# uploaded Annual Report itself).
_NON_AR_NSE_PORTALS = ("shareholding-pattern", "insider-trading", "corporate-filings-announcements",
                       # "corporate-filings-governance" (Composition of Board/Audit Committee/
                       # Nomination & Remuneration Committee, updated quarterly on NSE's live
                       # portal) is a genuinely different, non-Annual-Report NSE filing type -
                       # missing from this list meant C.5.1-C.5.3 (Board/Audit Committee/NRC
                       # composition) fell through this gate, got computed anyway, their
                       # compute_fn's internal NSE-live-endpoint call correctly found nothing in
                       # document-only mode, and the result was mislabeled SEARCH_INCONCLUSIVE
                       # instead of the honest EXTERNAL_DATA_REQUIRED this task always needed.
                       "corporate-filings-governance")

# Excel-text-driven classification (below) is a coarse heuristic - it reads
# the Excel's own "primary_source" wording, which sometimes names CRISIL/a
# live NSE portal as the nominal primary source even though the task's
# ACTUAL compute_fn was later verified (by direct code inspection) to run
# entirely off uploaded documents (the Annual Report/XBRL/Shareholding
# Pattern, plus the optional Corporate Governance/BRSR/Investor
# Presentation/Earnings Call/Credit Rating/Corporate Actions uploads via
# _fetch_ar_evidence_excerpts's extra_manual_document_types), with any live
# fallback (e.g. tools.crisil_scraper) itself guarded by
# tools.manual_mode.is_manual_mode() so it never actually reaches out.
# Each entry here was individually verified, not guessed - see the
# compute_fn's own source for the manual_mode/document-only proof.
_VERIFIED_DOCUMENT_ONLY_OVERRIDE = {
    "A.2.A",  # Brand - AR + Investor Presentation/Earnings Call/Credit Rating Report; crisil_scraper manual_mode-guarded
    "A.2.C",  # Cost leadership - same as above
    "A.2.E",  # Switching costs - same as above
    "Q.1.2",  # CFO/finance leadership churn - AR + Corporate Actions upload, _fetch_ar_evidence_excerpts only
    "R.1.1",  # Sudden departures - AR + Corporate Actions upload, _fetch_ar_evidence_excerpts only
    "R.3.1",  # Capital raise frequency - AR + Corporate Actions upload, _fetch_ar_evidence_excerpts only
    "R.3.2",  # Discount / pricing - AR + Corporate Actions upload, _fetch_ar_evidence_excerpts only
    "R.6.1",  # Response cadence - AR + Corporate Actions upload, _fetch_ar_evidence_excerpts only
    "R.6.2",  # Substance of response - AR + Corporate Actions upload, _fetch_ar_evidence_excerpts only
    "U.1.1",  # Top management-identified risk - AR + Earnings Call/Investor Presentation, _fetch_ar_evidence_excerpts only
    "C.1.1",  # Control levels - uploaded Shareholding Pattern filing (single snapshot), never live NSE/BSE
    "C.2.1",  # Presence of pledging - uploaded Shareholding Pattern filing (single snapshot)
    "C.2.2",  # Size of pledged shares - uploaded Shareholding Pattern filing (single snapshot)
    "C.2.4",  # Margin-call risk - uploaded Shareholding Pattern filing (single snapshot)
}


# Generic portal/source-marker -> the actual document a user would need to
# upload to resolve it. Keyed on the SOURCE TYPE (a URL path fragment or a
# module name), never a company/KPI name - the same document requirement
# applies to every task that shares that source type, for any company.
_EXTERNAL_SOURCE_DOCUMENT = {
    "shareholding-pattern": "Latest NSE/BSE Shareholding Pattern filing",
    "insider-trading": "NSE/BSE Insider Trading disclosures",
    "corporate-filings-announcements": "NSE/BSE Corporate Announcements history",
    "corporate-filings-governance": "NSE/BSE quarterly Corporate Governance filing",
    "peer_universe": "peer-company market/financial data",
    "crisil_scraper": "a CRISIL credit rating rationale report",
    "commodity": "external commodity price data",
    "screener": "external market/peer screening data",
}

# Which of the 4 NSE-portal source types now has a real, dedicated upload
# slot (see tools.manual_document_pipeline.QUALITATIVE_DOCUMENT_TYPES) that
# a compute_fn can actually search. Only these 4 are eligible for the
# upload-bypass below - peer_universe/crisil_scraper/commodity/screener stay
# unconditionally EXTERNAL_DATA_REQUIRED (no PDF/document upload can satisfy
# a live peer-market-data or commodity-price feed).
_PORTAL_TO_UPLOAD_DOC_TYPE = {
    "shareholding-pattern": "shareholding_pattern_filing",
    "insider-trading": "insider_trading_disclosures",
    "corporate-filings-announcements": "corporate_actions",
    "corporate-filings-governance": "quarterly_corporate_governance_filing",
}


def _requires_external_source(task, sym=None):
    """Returns (True, required_document_description) when this task's own
    declared primary source is genuinely outside the uploaded Annual
    Report - e.g. a live NSE portal, CRISIL, or peer market data - else
    (False, None). The document description is derived generically from
    WHICH source-type marker matched (see `_EXTERNAL_SOURCE_DOCUMENT`),
    never from the task_id or company, so the same lookup produces the
    right instruction for any task/company sharing that source type.

    When `sym` is given and the matched portal is one of the 4 in
    `_PORTAL_TO_UPLOAD_DOC_TYPE` (shareholding pattern, insider trading,
    corporate announcements, quarterly corporate governance), this checks
    whether that symbol actually has an uploaded document of the
    corresponding type (tools.manual_document_pipeline.get_document_coverage)
    before forcing EXTERNAL_DATA_REQUIRED - if uploaded, returns (False,
    None) so the compute_fn actually runs against the real uploaded
    document's text instead of being short-circuited. Never assumes a
    document exists; a lookup failure/None coverage is treated the same as
    "not uploaded" (still externally required)."""
    if task.get("task_id") in _VERIFIED_DOCUMENT_ONLY_OVERRIDE:
        return False, None
    ps = (task.get("primary_source") or "").lower()
    fn = (task.get("compute_fn") or "").lower()
    first_segment = ps.split("→")[0].strip()  # text before the sourcing pathway's first arrow
    if first_segment.startswith("crisil"):
        return True, _EXTERNAL_SOURCE_DOCUMENT["crisil_scraper"]  # CRISIL is the task's actual primary source
    for marker in ("peer_universe", "crisil_scraper", "commodity", "screener"):
        if marker in fn:
            return True, _EXTERNAL_SOURCE_DOCUMENT[marker]
    if "nseindia.com" in ps and "annual-report" not in ps:
        for portal in _NON_AR_NSE_PORTALS:
            if portal in ps:
                if sym:
                    doc_type = _PORTAL_TO_UPLOAD_DOC_TYPE.get(portal)
                    if doc_type:
                        try:
                            from tools.manual_document_pipeline import get_document_coverage
                            coverage = get_document_coverage(sym)
                            if coverage and coverage.get(doc_type, {}).get("uploaded"):
                                return False, None
                        except Exception as e:
                            print(f"[document_analysis] _requires_external_source: coverage check failed "
                                  f"for {sym}/{doc_type}: {e}")
                return True, _EXTERNAL_SOURCE_DOCUMENT.get(portal, "an additional NSE/BSE filing")
    return False, None


def run_qualitative_analysis(symbol, name=None):
    """Runs every batch_enabled (implemented, non-LLM, non-derived) A-U task
 - the SAME compute_fn's the automatic pipeline uses, unchanged. Tasks
    that would otherwise reach out to an external financial-data source
    (see _EXTERNAL_SOURCE_MARKERS) are NOT called - instead a
    status='EXTERNAL_DATA_REQUIRED' row is written for them via the
    existing write_qualitative(), so they still show up in the framework
    (never silently hidden) with an honest reason instead of a fabricated
    result. Results land in the existing qualitative_values table.
    Returns {completed, failed, external_data_required, total,
    skipped_llm}."""
    import time
    t0 = time.time()
    sym = symbol.strip().upper().replace(".NS", "")
    from tools.qualitative_engine import write_qualitative
    tasks = [t for t in TASK_REGISTRY if t["batch_enabled"] and t["compute_fn"]]
    skipped_llm = sum(1 for t in TASK_REGISTRY if t.get("llm_dependent") and t["implemented"])
    print(f"[document_analysis] [QUALITATIVE] {sym}: {len(tasks)} sub-points eligible "
          f"({skipped_llm} skipped app-wide - LLM disabled)")

    from tools.qualitative_engine import read_qualitative
    from tools.manual_mode import manual_mode
    completed, failed, external = 0, 0, 0

    def _run_one(task):
        # contextvars set in the calling thread (is_manual_mode's
        # ContextVar) are NOT propagated into ThreadPoolExecutor worker
        # threads by this runtime - confirmed by direct test: wrapping the
        # ex.map() call itself in manual_mode() left is_manual_mode()
        # False inside every worker, silently letting every compute_fn's
        # live-fetch guard (crisil_scraper, shareholding pledge, insider
        # trading, etc.) fall through to a real external call despite this
        # being the document-only manual workflow. Entering manual_mode()
        # HERE, inside the actual worker-thread function, is what makes it
        # actually apply per-thread.
        with manual_mode():
            return _run_one_task(task)

    def _run_one_task(task):
        needs_external, required_doc = _requires_external_source(task, sym=sym)
        if needs_external:
            write_qualitative(
                sym, task["task_id"],
                {"rationale": f"{task['title']} requires {required_doc}, which is not part of the "
                               f"uploaded Annual Report. Upload: {required_doc}.",
                 "required_document": required_doc, "title": task["title"]},
                "EXTERNAL_DATA_REQUIRED", name=name,
            )
            return "external"
        # write_qualitative() swallows its own DB-write exceptions (prints,
        # never raises - confirmed real: a burst of concurrent writes hit
        # transient WinError 10035 socket exhaustion, and the compute_fn
        # would otherwise be counted "completed" despite nothing actually
        # landing in the table). Verify the row actually persisted; retry
        # the whole (cheap, idempotent, force=True) compute on a miss.
        for attempt in range(3):
            # Exponential backoff (0.3s/0.9s/2.7s) instead of a flat 0.3s -
            # a burst of concurrent WinError 10035 socket exhaustion needs
            # time for the OS to free up sockets before a retry has any
            # better chance than the failed attempt; a flat short delay
            # just re-hits the same exhausted pool immediately.
            if attempt > 0:
                time.sleep(0.3 * (3 ** attempt))
            try:
                # Phase 3 final pass: the SAME migration gate the batch
                # worker uses (tools.qualitative_migration) decides here
                # too, so a task_id never executes through a different
                # engine depending on whether it was triggered by the
                # manual-upload workflow or the batch worker. Falls back to
                # this file's own `_resolve_compute_fn` for anything not
                # yet migrated - unchanged behaviour for those tasks.
                from tools.qualitative_migration import resolve_execution_fn
                fn, _exec_path = resolve_execution_fn(task, _resolve_compute_fn)
                try:
                    fn(sym, name, force=True)
                except TypeError:
                    fn(sym, name)
            except Exception as e:
                print(f"[document_analysis] [QUALITATIVE] {sym} {task['task_id']} compute FAILED (attempt {attempt+1}): {e}")
                continue
            if read_qualitative(sym, task["task_id"]) is not None:
                return "ok"
            print(f"[document_analysis] [QUALITATIVE] {sym} {task['task_id']}: computed but DB write "
                  f"didn't persist (attempt {attempt+1}), retrying...")
        print(f"[document_analysis] [QUALITATIVE] {sym} {task['task_id']} FAILED: could not persist after 3 attempts")
        return "failed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=_QUALITATIVE_WORKERS) as ex:
        for outcome in ex.map(_run_one, tasks):
            if outcome == "ok":
                completed += 1
            elif outcome == "external":
                external += 1
            else:
                failed += 1

    qual_time = time.time() - t0
    print(f"[document_analysis] [QUALITATIVE] {sym}: {completed} computed, "
          f"{external} external-data-required, {failed} failed, in {qual_time:.2f}s")
    return {"completed": completed, "failed": failed, "external_data_required": external,
            "total": len(tasks), "skipped_llm": skipped_llm, "seconds": round(qual_time, 2)}


def run_full_analysis(symbol, name=None):
    """The Upload Documents -> Analyse entrypoint. Runs Fundamental +
    Qualitative. Raises if EITHER half produces no usable results - the
    caller (the /run endpoint) must not report success on an empty
    analysis; see CLAUDE.md-adjacent 'do not accept empty success' rule."""
    import time
    t_total = time.time()
    sym = symbol.strip().upper().replace(".NS", "")
    print(f"[document_analysis] [RUN] {sym}: starting full analysis")
    t_f = time.time()
    fundamental = run_fundamental_analysis(sym, name)
    fundamental["seconds"] = round(time.time() - t_f, 2)
    if fundamental["total"] != 68:
        raise RuntimeError(f"Fundamental analysis produced {fundamental['total']}/68 results - "
                            f"not marking analysis complete.")
    qualitative = run_qualitative_analysis(sym, name)
    if qualitative["total"] == 0:
        raise RuntimeError("Qualitative analysis produced zero results - not marking analysis complete.")
    total_seconds = round(time.time() - t_total, 2)
    print(f"[document_analysis] [RUN] {sym}: complete in {total_seconds}s - "
          f"fundamental {fundamental['verified']+fundamental['needs_review']}/{fundamental['total']} with a value, "
          f"qualitative {qualitative['completed']}/{qualitative['total']} computed")
    return {"symbol": sym, "fundamental": fundamental, "qualitative": qualitative, "seconds": total_seconds}
