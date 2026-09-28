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
    "pbt": ["profit before tax", "profit before exceptional items and tax", "profit before extraordinary items and tax"],
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
    "cash": ["cash and cash equivalents", "cash & cash equivalents", "cash and bank balances",
             "cash & bank balances", "cash balances"],
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
    "capex": ["purchase of property, plant and equipment", "purchase of fixed assets",
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
    # Needed by the narrow "..._from_annual_report" component-sum EBITDA
    # calc that Operating Profit Margin/ROCE/Net Debt-EBITDA/DSCR/ROIC read
    # from the shared `parsed` dict - the broad-fallback adapter's own
    # PBT+Finance Costs EBIT derivation doesn't feed those functions, which
    # independently rebuild EBITDA from these component lines.
    "employee_benefit_expense": ["employee benefits expense", "employee benefit expense", "employee costs"],
    "other_expenses": ["other expenses"],
    "net_fixed_assets": ["property, plant and equipment", "net fixed assets", "net block"],
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
                        "receivables", "payables", "cash", "total_debt", "equity",
                        "deposits", "advances", "gross_npa", "total_provisions",
                        "net_fixed_assets", "reserves_and_surplus", "non_controlling_interest",
                        "equity_share_capital"}
_PROFIT_LOSS_ITEMS = {"revenue", "cogs", "ebitda", "ebit", "interest_expense", "pbt", "tax", "pat", "pat_total",
                       "depreciation", "eps", "shares_outstanding", "dividend_per_share", "employee_benefit_expense",
                       "other_expenses", "cost_of_materials_consumed", "purchases_of_stock_in_trade",
                       "changes_in_inventories", "total_expenses"}
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
_UNSCALED_ITEMS = _PER_SHARE_ITEMS | {"shares_outstanding"}

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
    m = _PAGE_UNIT_RE.search(page_text[:800])  # unit is always declared near the statement's own header
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


def extract_line_items(symbol):
    """Returns {key: {value, unit, page, evidence, confidence, source} or None, ...}
    for every canonical line item, sourced from XBRL first (structured,
    higher confidence) then the uploaded Annual Report text. Never
    fabricates - a key with no confident match is None."""
    import time
    sym = symbol.strip().upper().replace(".NS", "")
    t0 = time.time()
    from tools.ar_document_cache import get_ar_pages
    ar = get_ar_pages(sym, sym)
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
        xbrl_hit = _search_xbrl(sym, key)
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
                    paidup = _extract_shares_outstanding_from_paidup_sentence(pages)
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


def _row_shell(ratio_def, value, unit, status, inputs, financial_year=None, derived_from=None):
    inputs = list(inputs)
    if financial_year:
        inputs.append({"name": "financial_year", "value": None, "unit": None,
                        "source": financial_year, "page": None})
    # Strategy "B" (Strategy-B in this registry - see fundamental_ratio_
    # registry.py's own docstring) is ALWAYS a pure formula over other
    # already-computed ratios' values, never a fresh document extraction -
    # "DERIVED" is a direct, unambiguous readout of `ratio_def["strategy"]`,
    # never inferred/guessed. Strategy "A" (nse_xbrl fetch) and "C" (local
    # Annual-Report/market-data computation) both extract their own inputs
    # directly, hence "DIRECT".
    calc_type = "DERIVED" if ratio_def.get("strategy") == "B" else "DIRECT"
    # db/006_document_analysis.sql's `fundamental_analysis_results` table
    # has a FIXED column set - `calculation_type`/`derived_from` as
    # top-level dict keys here would upsert as columns that don't exist
    # (confirmed real: a live upsert attempt raised
    # "Could not find the 'calculation_type' column..."). Rather than a
    # schema migration, both are nested inside the EXISTING flexible
    # `inputs` jsonb column as one marker entry (name-prefixed "_" so the
    # frontend can distinguish it from genuine numeric inputs and route it
    # to a metadata panel instead of rendering it as an input row) - no DB
    # change needed, and every existing consumer of `inputs` that doesn't
    # know about this marker is unaffected (it's just one more list entry).
    reason = _synthesize_reason(ratio_def, status, inputs, derived_from)
    inputs.append({"name": "_metadata", "value": None, "unit": None, "source": None, "page": None,
                    "calculation_type": calc_type, "derived_from": derived_from, "reason": reason})
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


def _row_from_nse_xbrl_out(ratio_def, out):
    """Adapts a tools.nse_xbrl fetch_X() result (applicable/value/unit/
    confidence/selected_period/numerator/denominator/reason/status shape)
    into this table's row shape. Never fabricates: an unresolved value is
    always status='not_disclosed'/'not_applicable'/'insufficient_data'
    with value=None, never a guessed number."""
    if out.get("status") == "insufficient_data":
        return _row_shell(ratio_def, None, None, "insufficient_data",
                           [{"name": "reason", "value": None, "unit": None, "source": out.get("reason"), "page": None}])
    if not out.get("applicable", True):
        reason = (out.get("reason") or "")
        # Some fetch_X wrappers flag a genuinely NOT-MEANINGFUL result with
        # their own explicit boolean (e.g. `net_cash: True` on Net Debt/
        # EBITDA for a net-cash company - "This is NOT a leverage ratio")
        # rather than the literal substring "not applicable" this status
        # check was written against - confirmed real: that reason text
        # reached the frontend correctly, but under status='not_disclosed',
        # indistinguishable from a genuine extraction failure even though
        # the underlying data was fully read and the ratio is simply
        # inapplicable by definition for this company.
        status = ("not_applicable"
                  if ("not applicable" in reason.lower() or out.get("net_cash"))
                  else "not_disclosed")
        return _row_shell(ratio_def, None, None, status,
                           [{"name": "reason", "value": None, "unit": None, "source": reason, "page": None}])
    value = out.get("value")
    if value is None:
        return _row_shell(ratio_def, None, None, "not_disclosed", [])
    confidence = out.get("confidence")
    status = "needs_review" if (out.get("estimated") or (confidence is not None and confidence < 0.85)) else "verified"
    inputs = []
    sources = out.get("sources") or []
    source_label = (sources[0] if sources else {}).get("label", "Uploaded document")
    # `source_url` is only ever populated on the FAILURE-path dicts of most
    # fetch_X_from_annual_report() functions (an early-return convenience
    # for the error message), not on the success dict - but the full URL
    # (including the document marker `_source_file_and_type` needs) is
    # already embedded in `sources[0]["url"]` as "{pdf_url}#page={N}" on
    # every successful response, so it's derived from there instead of
    # requiring source_url on ~50 individual functions' success paths.
    pdf_url = out.get("source_url") or (sources[0]["url"].split("#page=")[0] if sources else None)
    src_file, src_type = _source_file_and_type(pdf_url, sources)
    # Page is only attached when it's UNAMBIGUOUS - a ratio can legitimately
    # pull from both the P&L (e.g. a numerator) and Balance Sheet (e.g. a
    # denominator) with genuinely different page numbers, and the input
    # metadata this pipeline actually persists doesn't track which specific
    # `sources` entry each individual input came from - attaching just
    # `sources[0]`'s page to EVERY input would silently fabricate a page
    # number for whichever input didn't actually come from that page. Only
    # attached when there's exactly one source page for this whole ratio
    # (the common case - most ratios draw every input from one statement),
    # otherwise explicitly "Not available" rather than guessed.
    single_page = sources[0].get("url", "").split("page=")[-1] if len(sources) == 1 and "page=" in sources[0].get("url", "") else None

    def _evidence(label):
        return {"source_file": src_file, "source_type": src_type,
                "section": label if len(sources) > 1 else source_label,
                "page": single_page or "Not available"}

    # `line_items` (currently populated only by Quick Ratio - Sr No 11) lets
    # a fetch_X_from_annual_report function surface its OWN atomic source
    # figures as separate, unambiguously-labeled rows instead of collapsing
    # them into one combined numerator value - confirmed real need: Quick
    # Ratio's numerator is "Total Current Assets minus Inventories" as a
    # single figure, and reading that combined value as if it were the raw
    # Inventory figure (then subtracting it a second time) silently produces
    # a materially wrong ratio. Purely additive - every other ratio has no
    # `line_items` key and falls through to the unchanged numerator/
    # denominator behavior below, so no other card's inputs change.
    line_items = out.get("line_items")
    if line_items:
        for li in line_items:
            inputs.append({"name": li.get("label"), "value": li.get("value_cr"), "unit": "cr",
                            "source": source_label, "page": None, **_evidence(li.get("label"))})
    else:
        for side in ("numerator", "denominator"):
            d = out.get(side)
            if d:
                inputs.append({"name": d.get("label", side), "value": d.get("value_cr"), "unit": "cr",
                                "source": source_label, "page": None, **_evidence(d.get("label", side))})
    try:
        value = round(float(value), 4)
    except (TypeError, ValueError):
        pass
    return _row_shell(ratio_def, value, out.get("unit") or "", status, inputs, financial_year=out.get("selected_period"))


def _call_nse_xbrl(fn_name, symbol, name):
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
    try:
        return fn(symbol, name)
    except Exception as e:
        print(f"[document_analysis] {fn_name}({symbol}) failed, retrying once: {e}")
        return fn(symbol, name)


def _derived(sr_no, computed):
    """Strategy-B: pure formulas over already-computed rows' raw numeric
    values (computed[sr_no] -> {'value':..., 'unit':..., 'extra':{...}}).
    Returns (value, unit) or (None, None) if a dependency is missing -
    never re-searches the document for a value another ratio already
    resolved (matches the approved dependency graph)."""
    def val(sr):
        c = computed.get(sr)
        return c["value"] if c and c.get("value") is not None else None

    if sr_no == 2:  # DOH = 365 / Inventory Turnover
        it = val(1)
        return (365 / it, "days") if it else (None, None)
    if sr_no == 4:  # DSO = 365 / Receivables Turnover
        rt = val(3)
        return (365 / rt, "days") if rt else (None, None)
    if sr_no == 6:  # DPO = 365 / Payables Turnover
        pt = val(5)
        return (365 / pt, "days") if pt else (None, None)
    if sr_no == 9:  # CCC = DSO + DOH - DPO
        dso, doh, dpo = val(4), val(2), val(6)
        if None in (dso, doh, dpo):
            return None, None
        return dso + doh - dpo, "days"
    if sr_no == 28:  # Earnings Yield = 1 / P/E * 100
        pe = val(24)
        return (round(100 / pe, 4), "%") if pe else (None, None)
    if sr_no == 48:  # Retention Ratio = 100 - Dividend Payout Ratio (%)
        payout = val(47)
        return (100 - payout, "%") if payout is not None else (None, None)
    if sr_no == 49:  # Sustainable Growth Rate = ROE% x Retention%
        roe, retention = val(18), val(48)
        if roe is None or retention is None:
            return None, None
        return roe * retention / 100, "%"
    if sr_no == 50:  # PEG = P/E / EPS Growth Rate (%)
        pe, growth = val(24), val(45)
        if not pe or not growth:
            return None, None
        return round(pe / growth, 4), "x"
    if sr_no == 51:  # EV/Sales = Enterprise Value / Revenue
        ev_row = computed.get(29)
        ev = ev_row.get("extra", {}).get("ev") if ev_row else None
        revenue_cr = ev_row.get("extra", {}).get("revenue_cr") if ev_row else None
        if not ev or not revenue_cr:
            return None, None
        return round(ev / (revenue_cr * 1e7), 4), "x"
    if sr_no == 52:  # EV/FCF = Enterprise Value / Free Cash Flow
        ev_row = computed.get(29)
        ev = ev_row.get("extra", {}).get("ev") if ev_row else None
        fcf_cr = val(36)
        if not ev or not fcf_cr:
            return None, None
        return round(ev / (fcf_cr * 1e7), 4), "x"
    if sr_no == 54:  # Graham Number = sqrt(22.5 x EPS x BVPS)
        pe_row = computed.get(24)
        eps = pe_row.get("extra", {}).get("eps") if pe_row else None
        bvps = val(46)
        if not eps or not bvps or eps <= 0 or bvps <= 0:
            return None, None
        return round((22.5 * eps * bvps) ** 0.5, 2), "₹"
    return None, None


_DERIVED_FORMULA_NEEDS_INPUTS = {28: [24], 48: [47], 49: [18, 48], 50: [24, 45], 51: [29], 52: [29, 36], 54: [24, 46]}


def _local_group_c(sr_no, items, sector, price, sym=None):
    """Strategy-C: computed locally from extract_line_items()'s alias-
    extracted document facts + (only for the market-price ratios)
    tools.market_price.get_live_price() - never Revenue/PAT/EBITDA/Debt/
    Cash/etc. from the market-price source. Returns
    (value, unit, status, inputs, extra_dict)."""
    def get(key):
        return items.get(key)

    def num(key):
        h = items.get(key)
        return h["value"] if h else None

    def inp(*keys):
        return _inputs_for(items, list(keys), sym=sym)

    if sr_no == 13:  # Working Capital
        ca, cl = num("current_assets"), num("current_liabilities")
        if ca is None or cl is None:
            return None, None, "not_disclosed", inp("current_assets", "current_liabilities"), {}
        return round(ca - cl, 4), "₹ Cr", "verified", inp("current_assets", "current_liabilities"), {}

    if sr_no == 17:  # ROA = Net Income / Average Total Assets (registry's
        # own declared formula) - was previously dividing by CLOSING Total
        # Assets only, silently dropping the averaging entirely. Confirmed
        # real on ANURAS: closing-only gave 3.0362%; averaging (opening +
        # closing)/2, the SAME convention every other averaged ratio in
        # this suite already uses, gives a different, formula-correct
        # result. Falls back to closing-only (with reduced confidence, same
        # as the narrow parser's own averaging fallback) only when the
        # prior-year comparative wasn't itself extracted.
        pat = num("pat")
        ta_hit = get("total_assets")
        if pat is None or ta_hit is None or ta_hit.get("value") in (None, 0):
            return None, None, "not_disclosed", inp("pat", "total_assets"), {}
        ta_cur = ta_hit["value"]
        ta_prior = ta_hit.get("prior_value")
        if ta_prior and ta_prior > 0:
            avg_ta = (ta_cur + ta_prior) / 2
            status = "verified"
        else:
            avg_ta = ta_cur
            status = "needs_review"
        return round(pat / avg_ta * 100, 4), "%", status, inp("pat", "total_assets"), {}

    if sr_no in (24, 25, 26, 27, 29, 37, 53):
        if price is None:
            return None, None, "not_disclosed", [{"name": "market_price", "value": None, "unit": None,
                                                    "source": "Angel One live price unavailable", "page": None}], {}
        ltp = price["ltp"]
        shares = num("shares_outstanding")
        eps = num("eps")
        # P-B (Sr No 25, the sole consumer of `equity` in this block) needs
        # OWNERS-attributable equity specifically - shares outstanding
        # represents only the parent company's own shares, so Non-
        # Controlling Interest (and, on some filers, Money Received
        # Against Share Warrants - not yet an issued equity share) must
        # never be folded into the denominator. The section's own final
        # Balance Sheet subtotal (whether explicitly labeled "Total
        # Equity" or read via the bare-subtotal fallback) is the WHOLE
        # Equity section total, which bundles those in - so prefer
        # reconstructing owners-only equity by summing the two universally
        # separately-labeled components that ARE owners' equity (Equity
        # Share Capital + Other Equity/Reserves and Surplus - the same
        # "sum what's there" convention used throughout this file) when
        # both are independently confirmed. Falls back to the generic
        # "equity" match (bare-subtotal or explicit "Total Equity"/
        # "Shareholders' Funds" label) only when that split isn't
        # available - never blocks the ratio outright.
        _share_capital_hit = get("equity_share_capital")
        _reserves_hit = get("reserves_and_surplus")
        _equity_hit = get("equity")
        _share_capital = _share_capital_hit["value"] if _share_capital_hit else None
        _reserves = _reserves_hit["value"] if _reserves_hit else None
        # Cross-validation against the generic "equity" match's own page -
        # "equity share capital"/"other equity" are short, common phrases
        # that a whole-document scan can match inside an unrelated JV/
        # associate reconciliation note or MD&A narrative sentence
        # elsewhere in a large filing (confirmed real on LT: "equity share
        # capital" matched a narrative sentence about an ACQUISITION on a
        # completely different page, and "other equity" separately matched
        # a joint-venture equity-accounting reconciliation table - neither
        # the actual consolidated Balance Sheet's own Share Capital/Other
        # Equity rows). Only trust the reconstruction when BOTH sub-items
        # were found on the SAME page as the generic "equity" match itself
        # (the genuine Balance Sheet page, already independently located) -
        # real Balance Sheet rows always co-locate on that one page; a
        # narrative/note false positive essentially never does. Silently
        # falls back to the generic match (unchanged prior behaviour)
        # whenever this cross-check can't be satisfied - never blocks the
        # ratio outright.
        _used_equity_split = (_share_capital is not None and _reserves is not None and _equity_hit is not None
                               and _share_capital_hit.get("page") is not None
                               and _share_capital_hit.get("page") == _equity_hit.get("page")
                               and _reserves_hit.get("page") == _equity_hit.get("page"))
        if _used_equity_split:
            equity = _share_capital + _reserves
        else:
            equity = num("equity")
        revenue = num("revenue")
        dps = num("dividend_per_share")
        total_debt, cash = num("total_debt"), num("cash")
        # EBITDA is deliberately NOT read from the raw "ebitda" alias match
        # (`items.get("ebitda")`) - Schedule III filings routinely print an
        # "EBITDA" HEADING above a margin-analysis table (Reported EBITDA %,
        # Pre-R&D EBITDA %, ...) rather than the absolute figure itself, and
        # the generic alias-matcher can't tell a percentage table from the
        # real value - confirmed real on CIPLA: this alias matched "EBITDA
        # 22.5 27.0 21.0 25.9" (margin percentages, not crore) and fed a
        # 5110x EV/EBITDA. Derived instead the SAME reliable way the narrow
        # parser's own `fetch_ebitda_from_annual_report` already computes it
        # (Revenue - COGS - Employee Benefit Expense - Other Expenses) from
        # atomic P&L lines that don't have this ambiguity, falling back to
        # the raw alias only when one of those atomic lines is itself
        # unavailable (never silently substituting a value known to be
        # unreliable when a reliable derivation is possible).
        materials = num("cost_of_materials_consumed") or 0.0
        stock_in_trade = num("purchases_of_stock_in_trade") or 0.0
        inv_change = num("changes_in_inventories") or 0.0
        ebe = num("employee_benefit_expense")
        oe = num("other_expenses")
        if revenue is not None and ebe is not None and oe is not None and \
                (num("cost_of_materials_consumed") is not None or num("purchases_of_stock_in_trade") is not None):
            cogs_for_ebitda = materials + stock_in_trade + inv_change
            ebitda = revenue - cogs_for_ebitda - ebe - oe
        else:
            ebitda = num("ebitda")
        ocf = num("operating_cash_flow")
        fcf_cr = num("operating_cash_flow") - num("capex") if (num("operating_cash_flow") is not None and num("capex") is not None) else None

        # Every ratio below divides/multiplies a CURRENT market price against
        # a HISTORICAL (FY-end) financial-statement figure - two genuinely
        # different dates by design (this is what P/E, P/B etc. always are),
        # but the ratio's own `inputs` trail must show that explicitly rather
        # than silently combining them - a value can only be independently
        # re-derived (or its "why does this look wrong" investigated) if the
        # price actually used is itself part of the recorded lineage, not
        # just implied by back-solving (ratio x other_input).
        price_input = {"name": "market_price", "value": round(ltp, 2), "unit": "₹",
                        "source": f"Live quote ({price.get('source') or 'unknown source'})", "page": "Not available",
                        "source_file": "Live market quote (not a document)",
                        "source_type": "Market Data", "section": "Not available"}

        def inp_with_price(*keys):
            return inp(*keys) + [price_input]

        if sr_no == 24:  # P/E = price / EPS
            if not eps:
                return None, None, "not_disclosed", inp_with_price("eps"), {}
            return round(ltp / eps, 4), "x", "verified", inp_with_price("eps"), {"eps": eps}

        if sr_no == 25:  # P/B = price / BVPS
            equity_keys = (("equity_share_capital", "reserves_and_surplus")
                           if _used_equity_split else ("equity",))
            if not equity or not shares:
                return None, None, "not_disclosed", inp_with_price(*equity_keys, "shares_outstanding"), {}
            bvps = equity * 1e7 / shares
            return round(ltp / bvps, 4), "x", "verified", inp_with_price(*equity_keys, "shares_outstanding"), {}

        if sr_no == 26:  # P/S = Market Cap / Revenue
            if not shares or not revenue:
                return None, None, "not_disclosed", inp_with_price("shares_outstanding", "revenue"), {}
            market_cap = ltp * shares
            return round(market_cap / (revenue * 1e7), 4), "x", "verified", inp_with_price("shares_outstanding", "revenue"), {}

        if sr_no == 27:  # Dividend Yield = DPS / price
            # Per the project's own established, documented policy (see the
            # narrow parser's `_find_dividend_per_share`/Sr No 47 docstrings
            # in tools/annual_report_financials.py: "no dividend declared is
            # a real 0%, NOT missing data"), finding no dividend-per-share
            # line at all defaults to a CONFIRMED 0.0 at reduced confidence
            # (needs_review), never `not_disclosed` - a company genuinely
            # paying no dividend this year is a real, common, meaningful
            # fact, not an extraction failure. This Strategy-C path
            # previously diverged from that established policy, showing
            # not_disclosed instead - confirmed wrong on ANURAS by reading
            # the actual Directors' Report text: "For the financial year
            # 2024-25, no dividend has been recommended by the Board..." -
            # a genuine, confirmed zero, not missing information.
            if dps is None:
                return round(0.0, 4), "%", "needs_review", inp_with_price("dividend_per_share"), {}
            return round(dps / ltp * 100, 4), "%", "verified", inp_with_price("dividend_per_share"), {}

        if sr_no == 29:  # EV/EBITDA = (Market Cap + Debt - Cash) / EBITDA
            if not shares or not ebitda:
                return None, None, "not_disclosed", inp_with_price("shares_outstanding", "total_debt", "cash", "ebitda"), {}
            market_cap = ltp * shares
            ev = market_cap + (total_debt or 0) * 1e7 - (cash or 0) * 1e7
            return (round(ev / (ebitda * 1e7), 4), "x", "verified", inp_with_price("total_debt", "cash", "ebitda"),
                    {"ev": ev, "revenue_cr": revenue})

        if sr_no == 37:  # FCF Yield = FCF / Market Cap
            if not shares or fcf_cr is None:
                return None, None, "not_disclosed", inp_with_price("shares_outstanding", "operating_cash_flow", "capex"), {}
            market_cap = ltp * shares
            return round(fcf_cr * 1e7 / market_cap * 100, 4), "%", "verified", inp_with_price("operating_cash_flow", "capex"), {}

        if sr_no == 53:  # Price/Cash Flow = Market Cap / OCF
            if not shares or not ocf:
                return None, None, "not_disclosed", inp_with_price("shares_outstanding", "operating_cash_flow"), {}
            market_cap = ltp * shares
            return round(market_cap / (ocf * 1e7), 4), "x", "verified", inp_with_price("operating_cash_flow"), {}

    if sr_no in (62, 64):  # bank-only, resolved sector already gated in caller
        if sr_no == 62:  # PCR = Total Provisions / Gross NPA
            prov, npa = num("total_provisions"), num("gross_npa")
            if prov is None or npa is None or npa == 0:
                return None, None, "not_disclosed", inp("total_provisions", "gross_npa"), {}
            return round(prov / npa * 100, 4), "%", "verified", inp("total_provisions", "gross_npa"), {}
        if sr_no == 64:  # Credit-to-Deposit = Advances / Deposits
            adv, dep = num("advances"), num("deposits")
            if adv is None or dep is None or dep == 0:
                return None, None, "not_disclosed", inp("advances", "deposits"), {}
            return round(adv / dep * 100, 4), "%", "verified", inp("advances", "deposits"), {}

    return None, None, "not_disclosed", [], {}


def run_fundamental_analysis(symbol, name=None):
    """Computes all 68 ratios from tools/fundamental_ratio_registry.py and
    persists them to fundamental_analysis_results (upsert on
    symbol+ratio_key) - always exactly 68 rows, each with an honest status
    (verified/needs_review/not_disclosed/not_applicable/insufficient_data),
    never a fabricated value just to make the count look complete.

    Runs entirely inside tools/manual_mode.py's guard - see that module's
    docstring for why every reused tools.nse_xbrl fetcher is safe to call
    here without reaching live NSE/BSE/yfinance/shareholding-scraper."""
    import time
    from tools.fundamental_ratio_registry import RATIOS, COMPUTE_ORDER, BY_SR_NO
    from tools.sector_ratio_applicability import is_bank_ratio_applicable
    from tools.nse_sector_map import get_nse_sector
    from tools.market_price import get_live_price
    from tools.manual_mode import manual_mode

    sym = symbol.strip().upper().replace(".NS", "")
    t0 = time.time()

    with manual_mode():
        sector = get_nse_sector(sym)
        bank_ok = is_bank_ratio_applicable(sector)
        items = extract_line_items(sym)
        # bse_code: the company's real BSE scrip code (backfilled from the
        # Annual Report's own text - see manual_document_pipeline.py's
        # _backfill_listing_identifiers), used as a fallback market-price
        # identifier when `sym` (the internal registry symbol, which can be
        # a synthetic placeholder) isn't itself a real tradeable ticker.
        bse_code = None
        try:
            from tools.supabase_client import get_client as _get_sb
            _rows = _get_sb().table("companies").select("bse_code").eq("symbol", sym).limit(1).execute().data
            bse_code = (_rows[0].get("bse_code") if _rows else None)
        except Exception:
            pass
        price = get_live_price(sym, bse_code=bse_code)  # market-price layer, kept separate - never used for any facts above

        computed = {}  # sr_no -> {"value", "unit", "extra"}
        rows_by_sr = {}

        # Strategy A/C ratios each independently scan the (large, cached)
        # Annual Report text and have no cross-ratio dependencies - safe to
        # run concurrently. Strategy B (derived) ratios only ever depend on
        # A/C or earlier-B ratios (COMPUTE_ORDER guarantees this - see its
        # own comment), so they must stay sequential and run only after
        # every A/C ratio has finished. Mirrors the same
        # ThreadPoolExecutor-with-manual_mode()-entered-per-worker pattern
        # already proven safe for run_qualitative_analysis (contextvars
        # don't propagate into worker threads, so manual_mode() must be
        # entered INSIDE each worker, not just around the pool).
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
                        return sr_no, row, {"value": None, "unit": None, "extra": {}}

                    if ratio_def["strategy"] == "A":
                        out = _call_nse_xbrl(ratio_def["nse_xbrl_fn"], sym, name)
                        row = _row_from_nse_xbrl_out(ratio_def, out)
                        return sr_no, row, {"value": row["value"], "unit": row["unit"], "extra": {}}
                    else:  # "C"
                        value, unit, status, inputs, extra = _local_group_c(sr_no, items, sector, price, sym=sym)
                        row = _row_shell(ratio_def, value, unit, status, inputs)
                        return sr_no, row, {"value": value, "unit": unit, "extra": extra}
            except Exception as e:
                # A bug in ONE ratio's compute logic (e.g. the UnboundLocal-
                # Error class of crash confirmed real in ROCE/ROIC's
                # Total-Expenses-shortcut branch) must never take down the
                # other 60+ ratios in this same concurrent batch -
                # `ex.map` below re-raises any worker exception the moment
                # its result is consumed, which previously meant one bad
                # ratio silently aborted the ENTIRE run_fundamental_analysis
                # call (a raw HTTP 500, not even a partial result) rather
                # than reporting just that one ratio as unavailable.
                print(f"[document_analysis] sr_no={sr_no} ({ratio_def.get('label')}) compute crashed: {e}")
                row = _row_shell(ratio_def, None, None, "not_disclosed",
                                  [{"name": "reason", "value": None, "unit": None,
                                    "source": "An internal error occurred computing this ratio - please report this "
                                              "if it persists on re-analysis.", "page": None}])
                return sr_no, row, {"value": None, "unit": None, "extra": {}}

        with concurrent.futures.ThreadPoolExecutor(max_workers=_QUALITATIVE_WORKERS) as ex:
            for sr_no, row, comp in ex.map(_compute_ac, ac_sr_nos):
                rows_by_sr[sr_no] = row
                computed[sr_no] = comp

        for sr_no in b_sr_nos:
            ratio_def = BY_SR_NO[sr_no]
            # "B" derived - pure math over `computed`, cheap and sequential
            value, unit = _derived(sr_no, computed)
            needs = _DERIVED_FORMULA_NEEDS_INPUTS.get(sr_no, ratio_def.get("depends_on", []))
            missing_dep = any(computed.get(d, {}).get("value") is None for d in needs)
            status = "not_disclosed" if value is None else "verified"
            if value is None and missing_dep:
                status = "not_disclosed"
            # `derived_from` REFERENCES each dependency's own
            # already-computed row (value/formula/status) rather than
            # re-fabricating or duplicating its extraction evidence -
            # the dependency's OWN row already carries its full
            # source_file/page/section trail (or its own `derived_from`
            # chain, for a ratio derived from another derived ratio,
            # e.g. Sustainable Growth Rate <- Retention Ratio <-
            # Dividend Payout Ratio), so this is a pointer, not a copy.
            derived_from = [
                {"sr_no": d, "ratio": BY_SR_NO[d]["label"], "ratio_key": BY_SR_NO[d]["ratio_key"],
                 "value": rows_by_sr[d]["value"] if d in rows_by_sr else None,
                 "unit": rows_by_sr[d]["unit"] if d in rows_by_sr else None,
                 "formula": BY_SR_NO[d]["formula"],
                 "status": rows_by_sr[d]["status"] if d in rows_by_sr else None}
                for d in needs
            ]
            row = _row_shell(ratio_def, value, unit, status, [], derived_from=derived_from)
            rows_by_sr[sr_no] = row
            computed[sr_no] = {"value": value, "unit": unit, "extra": {}}

        results = [rows_by_sr[r["sr_no"]] for r in RATIOS]

    print(f"[document_analysis] [FUNDAMENTAL] {sym}: {len(results)}/68 ratios computed in {time.time()-t0:.2f}s "
          f"({sum(1 for r in results if r['status'] == 'verified')} verified, "
          f"{sum(1 for r in results if r['status'] == 'needs_review')} needs_review, "
          f"{sum(1 for r in results if r['status'] == 'not_disclosed')} not_disclosed, "
          f"{sum(1 for r in results if r['status'] == 'not_applicable')} not_applicable, "
          f"{sum(1 for r in results if r['status'] == 'insufficient_data')} insufficient_data)")

    t2 = time.time()
    from tools.supabase_client import get_client
    sb = get_client()
    rows = [{"symbol": sym, **r} for r in results]
    # Same transient-Windows-socket-exhaustion retry the qualitative
    # pipeline already needed (tools/qualitative_db.py's write_qualitative)
    # - this bulk upsert had NONE at all, so a single WinError 10035 hit
    # here (confirmed real: killed a whole first-time analysis run with a
    # raw HTTP 422, not a soft per-ratio failure) aborted the entire
    # fundamental analysis outright instead of just retrying once.
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
    print(f"[document_analysis] [DATABASE] {sym}: {len(rows)} fundamental rows written in {time.time()-t2:.2f}s")

    return {
        "verified": sum(1 for r in results if r["status"] == "verified"),
        "needs_review": sum(1 for r in results if r["status"] == "needs_review"),
        "not_disclosed": sum(1 for r in results if r["status"] == "not_disclosed"),
        "not_applicable": sum(1 for r in results if r["status"] == "not_applicable"),
        "insufficient_data": sum(1 for r in results if r["status"] == "insufficient_data"),
        "total": len(results),
    }


def get_fundamental_results(symbol):
    sym = symbol.strip().upper().replace(".NS", "")
    from tools.supabase_client import get_client
    sb = get_client()
    return sb.table("fundamental_analysis_results").select("*").eq("symbol", sym).order("category").execute().data


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
