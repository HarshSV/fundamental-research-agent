"""
Annual Report financials - Inventory Turnover computed from the company's own
full Annual Report PDF (BSE's `AnnualReport_New` API), per the Source Hierarchy
spec: "1. Annual Report (Audited Financial Statements)" ranks above the
quarterly/annual Reg-33 result filing.

Why this is BETTER than the Reg-33 filing, not just "more compliant":
  - The Annual Report's Balance Sheet + P&L pages extract CLEANLY with plain
    linear text (label and both years' values sit on one line) - unlike the
    Reg-33 filing's tables, which come out jumbled (label block, then a
    separate number block) and needed complex position-based reconstruction.
  - It shows the CURRENT and PRIOR year side by side in ONE document, so the
    prior-year comparator is always on the same (restated) basis as the
    current year - no separate-filing mismatch to patch (see
    bse_restated_inventory.py, which existed to fix exactly that problem for
    the Reg-33 source).

Canonical row-label matching uses the synonym lists from the ratio
specification (Mis "Extra" column) so this generalises beyond Tata Steel's
exact wording.

Cached 90 days (an Annual Report never changes once published). Never raises.
"""

import os
import re
import io
import json
import time
import threading

try:
    from tools import ssl_bootstrap  # noqa: F401
except Exception:
    pass

from tools.bse_scraper import _sess, _resolve_scrip_code, _read_cache, _write_cache
from tools.manual_mode import is_manual_mode

CACHE_TTL = 90 * 24 * 3600

# Per-(symbol, year, consolidated) locks guarding `_get_extracted_financials`.
# Every ratio derived from the same Annual Report calls it independently, and
# a first-ever visit to a company's Fundamental Ratios page fires 20-30 of
# those calls at once (confirmed: a 10-30MB PDF download + parse takes ~7s).
# Without a lock here, EVERY one of those concurrent calls sees a cache miss
# and independently re-downloads + re-parses the SAME PDF - a classic cache
# stampede that widening the thread pool (app.py) made WORSE, not better, by
# letting more of the duplicate downloads run in parallel instead of one
# request doing the work and the rest reusing it. `_LOCKS_GUARD` protects
# the lock dict itself; each individual key's lock serialises just that one
# (symbol, year) so unrelated companies/years are never blocked by each other.
_extract_locks = {}
_extract_locks_guard = threading.Lock()


def _extract_lock_for(ckey):
    with _extract_locks_guard:
        lock = _extract_locks.get(ckey)
        if lock is None:
            lock = threading.Lock()
            _extract_locks[ckey] = lock
        return lock

# PyMuPDF preserves Unicode ligature glyphs (ﬁ, ﬂ, ﬀ, ...) as their own single
# codepoints rather than decomposing them into their ASCII letter pairs, when
# the source PDF's embedded font uses them (common in professionally
# typeset/InDesign-exported Annual Reports). Left unfixed, this silently
# breaks EVERY substring search for a word containing "fi"/"fl" on such a
# filing - "Profit" extracts as "Proﬁt", "benefits" as "beneﬁts", "efficient"
# as "efﬁcient" - invisible to every "profit"/"benefit"-containing label in
# this file. Confirmed as the root cause of Eternal/Zomato's ENTIRE
# Consolidated P&L page (PBT, PAT, Employee Benefit Expense) being
# unreadable, cascading into 9+ ratios (NPM, ROA, ROE, ROCE, Interest
# Coverage, P/E, P/S, Earnings Yield, EV/EBITDA) all failing simultaneously
# for that one company. `_page_text()` normalises this immediately after
# every `page.get_text()` call - fixed ONCE at the source, rather than
# patching every downstream label list.
_LIGATURE_MAP = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st",
    # Word/InDesign-exported PDFs render the typographer's apostrophe as
    # U+2019 ("arm’s length"), not the ASCII "'" every downstream
    # regex in this codebase is written against - confirmed real on Prime
    # Fresh Limited: score_pricing_fairness's `arm'?s[- ]length` pattern
    # (and every other "'s"/"n't"-matching regex across the qualitative
    # scoring modules) silently matched nothing on this filer's AOC-2/RPT
    # text because of this single substituted character, discarding real
    # evidence as if it never existed. Left-and-right double quotes are
    # normalised too for the same reason (e.g. "“not disclosed”").
    "‘": "'", "’": "'", "“": '"', "”": '"',
    # A DIFFERENT font-subsetting quirk from the ligature one above: some
    # PDFs' embedded font maps a handful of specific glyph IDs (accented
    # Latin-Extended-A/B and Greek/Coptic lookalike codepoints, never
    # legitimate in English financial prose) onto ordinary ASCII letters/
    # digits, so PyMuPDF's cmap-based decode returns the lookalike
    # codepoint instead of the real character - confirmed real on TCS's
    # FY2026 Directors' Report narrative (NOT its audited financial
    # statement tables, which use a clean, unaffected font subset):
    # "deĐůared three interiŵ diǀidends of ₹11 eaĐh, a speĐiaů diǀidend of
    # ₹ϰϲ, and reĐoŵŵended a finaů diǀidend of ₹31 (pendinŐ shareholders'
    # approǀaů ..., for a totaů of ₹11Ϭ per share" - decodes to "declared
    # three interim dividends of ₹11 each, a special dividend of ₹46, and
    # recommended a final dividend of ₹31 (pending shareholders' approval
    # ..., for a total of ₹110 per share" once these are mapped back -
    # verified independently against this filing's own separate 10-Year
    # Financial Highlights table (clean text, unaffected font: "Dividend
    # Per Share ₹ 110.00") and the sum 3x11 (interim) + 46 (special) + 31
    # (proposed final) = 110 matching exactly. Left unfixed, this silently
    # broke `_find_dividend_per_share`'s Directors' Report narrative-
    # sentence match (no regex containing "declared"/"dividend"/"final"
    # can match text where those exact letters are substituted), cascading
    # into Dividend Payout Ratio and Retention Ratio being reported as a
    # false 0%/100% instead of the real, correctly-computed figures.
    "Đ": "c", "ů": "l", "ŵ": "m", "ǀ": "v", "Ő": "g",
    "͕": ",", "͛": "'", ";": "(", "Ϳ": ")",
    "Ϭ": "0", "Ϯ": "2", "ϰ": "4", "ϲ": "6",
})


# Some Annual Report PDFs encode grouped-thousands figures on bold/subtotal
# rows as several separate positioned text runs with a small real gap
# between them (a table-layout/kerning choice in the PDF generator, not a
# PyMuPDF bug) - get_text() faithfully reports that gap as a literal space,
# splitting one number into fragments: "1,35,705" extracts as "1, 35, 7 05".
# Confirmed real on TCS's FY2026 Consolidated Balance Sheet/Statement of
# P&L: EVERY bold subtotal row (Total current assets, TOTAL ASSETS, Total
# equity, Total current liabilities, TOTAL INCOME, ...) came out this way,
# so `_NUM_RE`/`_ALL_NUMS_RE` (which require contiguous `[\d,]+` digits)
# matched nothing at all on those rows - not because the figure is
# genuinely undisclosed, but because the extracted text broke it apart.
# Indian/Western comma-grouping is rigid (first group 1-2 digits, every
# middle group exactly 2 digits, last group exactly 3 digits, always
# comma-separated) - `_STRAY_SPACE_NUM_RE` matches exactly that shape while
# tolerating one stray space around any comma or within the final 3-digit
# group, and only ever collapses spaces THAT ARE ALREADY INSIDE ONE such
# grouped number, never across the (much larger, but text-flattened to the
# same single space) gap between two separate numbers in adjacent table
# columns (verified: "1, 35, 7 05 1, 23, 011" -> "1,35,705 1,23,011", not
# one merged number). A filing with no such artifact is unaffected - the
# pattern only fires where these exact stray spaces already exist.
_STRAY_SPACE_NUM_RE = re.compile(
    r"-?\d{1,2}(?:\s?,\s?\d{2})*\s?,\s?\d\s?\d\s?\d(?!\d)"
)


# A statement's "Page No." column prints the note's page span as a hyphenated range ("Revenue from operations 22 431-432
# 1,529,130 1,418,582", Maruti). Read as numbers, "431-432" is 431 and a NEGATIVE 432 - the row's "current" and "prior" values - and
# every ratio built on it is off by orders of magnitude while still looking verified. Real figures never have a hyphen glued
# between two digit runs ("(1,234)" / "- 1,234" / "-1,234" are the only negative forms), so such a token is a page reference and
# is blanked. Fiscal-year labels ("2024-25", "2024-2025"), dates ("31-03-2026") and decimals are left alone.
_PAGE_RANGE_RE = re.compile(r"(?<![\d,.\-\u2013/])([1-9]\d{0,3})[-\u2013]([1-9]\d{0,3})(?![\d,.%\-\u2013/])")


# Lettered note references ("Revenue From Operations 23A, 23B 81612.78 73891.43", ITC) read as the row's first figure ("23") and
# pushed the real current-year value into the prior-year slot. A reference like "23A" / "23A, 23B" directly in front of a number
# is never a figure; it is blanked.
_LETTERED_NOTE_REF_RE = re.compile(r"(?<![\w.,])\d{1,3}[A-Za-z](?:\s*,\s*\d{1,3}[A-Za-z])*(?=\s+[(\-]?\d)")


# Comma-separated plain note numbers directly in front of a figure ("Dividends paid ... 26, 15 (2,819.45)", Bata) read as two
# values (26 and 15) and pushed the real amount out of the row.
_NOTE_LIST_RE = re.compile(r"(?<![\d,.])\d{1,2}(?:,\s+\d{1,2})+(?=\s+\(?-?(?:\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+\.\d{2})\)?)")


def _blank_page_ranges(text):
    def _sub(m):
        a, b = int(m.group(1)), int(m.group(2))
        if 1900 <= a <= 2100 or b <= a:
            return m.group(0)
        return " " * len(m.group(0))
    text = _PAGE_RANGE_RE.sub(_sub, text)
    text = _NOTE_LIST_RE.sub(lambda m: " " * len(m.group(0)), text)
    return _LETTERED_NOTE_REF_RE.sub(lambda m: " " * len(m.group(0)), text)


def _fix_stray_spaced_numbers(text):
    return _blank_page_ranges(_STRAY_SPACE_NUM_RE.sub(lambda m: m.group(0).replace(" ", ""), text))


# The same PDF-generator artifact that splits numbers (above) also
# occasionally splits a WORD inside a bold/subtotal row's own label -
# confirmed real on TCS's FY2026 Consolidated Balance Sheet: "Total
# equity" extracts as "Total eq uity", "TOTAL EQUITY AND LIABILITIES" as
# "TOTAL EQ U ITY AN D LIABILITIES". Unlike the number artifact, the split
# point isn't a fixed/predictable shape (it varies by word), so rather
# than guessing every possible split, every canonical label lookup this
# file does through `_find_row_values` tolerates ONE optional stray space
# between any two characters of the label it's searching for - a label
# with no such artifact in the source text still matches exactly like a
# plain substring search (zero behavioural change, zero regression risk
# for every filing that doesn't have this artifact).
_FUZZY_LABEL_CACHE = {}


def _fuzzy_label_re(name):
    pat = _FUZZY_LABEL_CACHE.get(name)
    if pat is None:
        parts = []
        for ch in name:
            parts.append(r"[\s:]+" if ch == " " else r"\s?" + re.escape(ch))
        pat = "".join(parts)
        _FUZZY_LABEL_CACHE[name] = pat
    return pat


def _page_text(page):
    """Ligature-and-smart-quote-normalised, stray-space-number-repaired
    page.get_text() - use this everywhere instead of calling
    page.get_text() directly (see module-level comment above)."""
    text = (page.get_text() or "").translate(_LIGATURE_MAP)
    return _fix_stray_spaced_numbers(text)


def _is_toc_page(text):
    """A contents / index page: many dot-leader runs ("2.18 Revenue from operations ......... 363"). It names the statements and
    their line items but carries no statement figures, so the first such page used to win the P&L 'shape' match (Infosys
    FY26 read revenue = 363, the page number)."""
    return len(re.findall(r"\.{8,}", text)) >= 5


def _is_stmt_heading(tl, phrase):
    """True if `phrase` (e.g. "consolidated balance sheet") appears in `tl`
    as a genuine statement heading - i.e. shortly followed by a crore/lakh/
    million currency-unit marker, which every real Balance Sheet/P&L caption
    carries (e.g. "Consolidated Balance Sheet\\n(H crore)\\nNote\\nAs at...").
    A bare substring test also matches Table-of-Contents entries (heading
    text immediately followed by a bare page number, e.g. TCS's own
    "...\\n196\\nConsolidated Balance Sheet\\n197\\nConsolidated Statement of
    Profit and Loss...") and Auditor's-Report prose describing several
    statements in one sentence (e.g. "...comprise the consolidated balance
    sheet as at 31 March 2026, and the consolidated statement of profit and
    loss...") - both confirmed real on TCS's FY2026 report, both several
    pages before the real statements, both wrongly latching `section` and
    causing every page in between (including the dividend narrative) to be
    skipped via the `if section == "consolidated": continue` gate below."""
    i = tl.find(phrase)
    if i == -1:
        return False
    return re.search(r"crore|lakh|million", tl[i + len(phrase):i + len(phrase) + 40]) is not None


def _has_pl_caption(tl):
    """True if 'statement of profit and loss' appears on the page as a
    genuine statement caption/heading, not as prose. Directors' Reports
    routinely reference the statement in prose when discussing retained
    earnings - e.g. "the Board has decided to retain the entire profit ...
    in the Statement of Profit and Loss" (seen verbatim on Gopal Snacks'
    FY25 Annual Report) - and a bare substring test treats that sentence
    the same as a real heading, wrongly flipping section-tracking state (or
    matching the P&L shape fallback) on a Directors' Report page many pages
    before the real statement. A genuine heading is never preceded by
    "in/to/under/from the", which only occurs in prose referencing it."""
    return re.search(r"(?<!in the )(?<!to the )(?<!under the )(?<!from the )"
                      r"statement of profit and loss", tl) is not None


# --- Canonical row-label synonyms (from the ratio spec) ---------------------
_COGS_LABELS = {
    "Cost of materials consumed": [
        "cost of materials consumed", "material consumed", "materials consumed",
        "raw material consumed", "raw materials consumed", "consumption of raw materials",
        "consumption of raw material", "consumption of materials", "material costs",
        "material cost", "cost of raw materials consumed", "cost of material consumed",
        # caption variants naming what ELSE is consumed with the materials (Titan: "Cost of materials and components consumed")
        "cost of materials and components consumed", "cost of raw materials and components consumed",
        "cost of raw material and components consumed", "cost of materials and packing materials consumed",
        "cost of raw materials and packing materials consumed", "cost of raw material and packing material consumed",
        "cost of materials and stores consumed", "cost of raw materials, components and packing materials consumed",
        "cost of materials, components and stores consumed", "cost of materials, stores and spares consumed",
    ],
    "Purchases of stock-in-trade": [
        "purchases of stock-in-trade", "purchase of stock-in-trade", "purchases of stock in trade",
        "purchase of stock in trade", "stock-in-trade purchases", "purchase of traded goods",
        "purchases of traded goods", "traded goods purchased", "purchase of merchandise",
    ],
    "Changes in inventories": [
        "changes in inventories", "change in inventories", "changes in inventory",
        "change in inventory", "changes in inventories of finished",
        "increase/decrease in inventories", "movement in inventories",
        # Trading-company Schedule III phrasing inserts "the" and names
        # "Stock-in-Trade" explicitly instead of "finished goods/WIP" -
        # confirmed real on Prime Fresh Limited ("Changes In The
        # Inventories Of Stock In Trade"), a standard alternate caption for
        # any trader/retailer, not unique to one filing.
        "changes in the inventories of stock in trade",
        "changes in the inventories of stock-in-trade",
        "change in the inventories of stock in trade",
        "changes in inventories of stock-in-trade",
        "changes in inventories of stock in trade",
    ],
}
_INVENTORY_LABELS = [
    "inventories", "inventory", "stocks", "stock", "stock in trade", "stock-in-trade",
]
_EMPLOYEE_BENEFIT_LABELS = [
    "employee benefit expense", "employee benefits expense", "employee benefit expenses",
    "employee benefits expenses", "employee cost", "employee costs",
]
_OTHER_EXPENSES_LABELS = [
    "other expenses", "other expense",
]
# Depreciation & Amortisation Expense - a P&L line item SEPARATE from
# Employee Benefit Expense/Other Expenses. Needed for Operating Profit
# Margin (Sr No 15), which per spec is EBIT-basis (Revenue − COGS − Employee
# Costs − Other Expenses − D&A), NOT EBITDA-basis - D&A is a real operating
# cost of running the business and must be deducted, not added back.
_DEPRECIATION_LABELS = [
    "depreciation and amortisation expense", "depreciation and amortization expense",
    "depreciation, amortisation and impairment expense", "depreciation & amortisation expense",
    "depreciation and amortisation", "depreciation and amortization",
    # caption variants seen across filers (typos included - "amorization" is printed by HCLTech)
    "depreciation and amorization expense", "depreciation and amorization",
    "depreciation / amortisation and depletion expense", "depreciation/amortisation and depletion expense",
    "depreciation, amortisation, impairment and obsolescence", "depreciation, amortization, impairment and obsolescence",
    "depreciation, amortisation and impairment", "depreciation, amortization and impairment",
    "depreciation, depletion and amortisation expense", "depreciation, depletion and amortization expense",
    "depreciation, amortisation and depletion", "depreciation and depletion expense",
    "depreciation, amortisation and impairment expenses", "depreciation, amortisation expense",
    "depreciation expense", "depreciation",
]
# Direct Expenses - a P&L line item some trading/services filers print
# SEPARATELY from Cost of materials consumed/Purchases of stock-in-trade/
# Other Expenses (e.g. freight, site/project costs, labour charges directly
# tied to the goods/services sold, printed as its own Schedule III sub-line
# rather than folded into "Other Expenses"). Not a standard Schedule III
# caption (Schedule III doesn't mandate this split), so only some filers
# have it at all - never assumed present, always its own optional field.
# Needed for Operating Profit Margin (Sr No 15, manual-upload workflow
# only) so this genuine operating cost isn't silently missed just because
# it isn't captioned "Other Expenses".
_DIRECT_EXPENSES_LABELS = [
    "direct expenses", "direct expense", "direct operating expenses",
    "direct cost of services", "direct costs", "direct cost",
    "cost of services rendered", "direct trading expenses",
]
# For CONSOLIDATED statements, "Profit for the year" often means the TOTAL
# including Non-Controlling/Minority Interest - per spec, Net Profit Margin
# must use the portion attributable to OWNERS only. Tried first, in priority
# order; the generic labels (which fetch the same figure standalone reports
# call "Profit for the year") are the fallback for filings with no NCI split.
_PAT_OWNERS_LABELS = [
    "profit for the year attributable to owners of the company",
    "profit for the year attributable to owners of the parent",
    "profit attributable to owners of the company",
    "profit attributable to owners of the parent",
    # "attributed to" (past participle) is a distinct, equally common Ind AS
    # phrasing from "attributable to" - e.g. "Profit for the year attributed
    # to: Owners of the parent" followed on the SAME page by "Other
    # comprehensive income for the year ATTRIBUTABLE to: ..." (the OCI line
    # uses the other wording) - including the "profit for the year/period"
    # prefix keeps this from ever matching that OCI line by mistake.
    "profit for the year attributed to",
    "profit for the period attributed to",
    "net profit for the year attributed to",
    # Tata Steel's consolidated filing captions this as "Profit/(loss) from
    # for the year attributable to:" - an extra "from" token between the
    # (already-normalised) "Profit" and "for the year" that no other filing
    # seen so far includes. Listed literally rather than generalised into a
    # regex, since this is the only filing observed with it.
    "profit from for the year attributable to",
    "attributable to owners of the company",
    "attributable to owners of the parent",
    "attributable to the owners of the company",
    "attributable to shareholders of the company",
    "attributable to equity holders of the company",
    "attributable to equity shareholders of the company",
    # HUL captions its "Net profit attributable to:" split as "Owners of the
    # HOLDING Company" (not "the Company"/"the Parent") - confirmed this
    # caused the label to fall through entirely to `_PAT_GENERIC_LABELS`,
    # whose first entry ("profit for the year") then matched the WRONG,
    # earlier subtotal "PROFIT FOR THE YEAR FROM CONTINUING OPERATIONS (A)"
    # instead of the real combined (continuing + discontinued) owners'
    # profit - silently understating Net Profit/Dividend Payout Ratio's
    # denominator by the entire discontinued-operations gain whenever a
    # filer splits the P&L (HUL FY26: ₹10,652 Cr picked up instead of the
    # correct ₹15,040 Cr, a ~₹4,400 Cr miss from the ice-cream demerger).
    "owners of the holding company",
    # Same "/(Loss)" suffix as `_PAT_GENERIC_LABELS` below, but on the
    # owners-attributable caption - a loss-making-history consolidated filing
    # can print "Profit/(Loss) for the year attributable to Owners of the
    # Company" instead of the plain wording. `_strip_formula_refs` already
    # normalises this before matching; listed explicitly too so a match is
    # never skipped just because of the suffix.
    "profit/(loss) for the year attributable to owners of the company",
    "profit/(loss) for the year attributable to owners of the parent",
    "profit/(loss) attributable to owners of the company",
    "profit/(loss) attributable to owners of the parent",
]
_PAT_GENERIC_LABELS = [
    "profit for the year", "profit for the period", "profit after tax",
    "net profit for the year", "net profit for the period",
    # Loss-making-history filings (e.g. Eternal/Zomato) caption the bottom
    # line "Profit/(Loss) for the year" rather than plain "Profit for the
    # year" - `_find_pl_row` already normalises this via `_strip_formula_refs`
    # before matching, but these are kept explicitly in the canonical list too
    # (belt-and-suspenders): a match must never be skipped just because of
    # the "/(Loss)" suffix - that suffix is a presentation convention (the
    # company reserves the right to report either outcome), not a sign that
    # the row is something other than PAT.
    "profit/(loss) for the year", "profit/(loss) for the period",
    "profit/(loss) after tax", "net profit/(loss) for the year",
    "net profit/(loss) for the period",
]
# For CONSOLIDATED statements, "Total equity" often includes Non-Controlling
# Interest - per spec, ROE (Sr No 18) must use only the owners' portion.
# Same owners-first/generic-fallback pattern as PAT above.
_EQUITY_OWNERS_LABELS = [
    "total equity attributable to owners of the parent",
    "total equity attributable to owners of the company",
    "equity attributable to owners of the parent",
    "equity attributable to owners of the company",
    "total equity attributable to equity holders of the parent",
    "equity attributable to equity holders of the parent",
]
_EQUITY_GENERIC_LABELS = [
    "total equity", "shareholders' funds", "shareholders funds", "total shareholders' funds",
]
# Non-Controlling Interest - its own always-separate Balance Sheet line
# under Ind AS (see comment on `_EQUITY_SHARE_CAPITAL_LABELS` below). Needed
# for Debt-to-Equity (Sr No 23): unlike ROE, D/E's numerator (Total Debt) is
# the WHOLE consolidated entity's debt, not just the portion funded by the
# parent's own shareholders - so its denominator must be the WHOLE entity's
# equity (owners' + NCI), not the owners-only figure ROE uses. Using the
# owners-only figure against all-entity debt was overstating leverage for
# every company with a material minority interest.
_NCI_LABELS = [
    "non-controlling interests", "non controlling interests",
    "non-controlling interest", "non controlling interest",
    "minority interest", "minority interests",
]
# Retained Earnings (Altman Z-Score Sr No 55's RE/TA component) - the
# accumulated-profits Balance Sheet line ONLY, deliberately NOT the same
# as Total Equity (which also includes paid-up Share Capital). Ind AS
# Schedule III post-2019 filings combine all reserve sub-items (Retained
# Earnings, Securities Premium, General Reserve, etc.) under a single
# "Other Equity" line -- an approximation of pure Retained Earnings, since
# it can't be split further from face-value BS text alone (flagged via
# reduced confidence when this fallback is used). Older/pre-2019-style
# filings sometimes still print the literal "Reserves and Surplus" caption.
_RETAINED_EARNINGS_LABELS = [
    "reserves and surplus", "reserve and surplus",
]
_OTHER_EQUITY_LABELS = [
    "other equity",
]
# Owners-attributable Total Equity, most-reliable-first: Equity Share Capital
# + Other Equity are ALWAYS the parent/owners' portion under Ind AS (Non-
# Controlling Interest is always its own separate line, never blended into
# either) - summing these two face-of-Balance-Sheet rows directly is more
# robust than searching for a "Total Equity" label at all, since some filers
# print it as "Total - Equity (A)" (confirmed on HUL) rather than "Total
# Equity"/"Shareholders' Funds". A bare substring search for "total equity"
# is unsafe regardless of phrasing: it also matches inside "TOTAL EQUITY AND
# LIABILITIES" (the whole Balance Sheet grand total, not equity at all) -
# confirmed silently happening on HUL, since "Total - Equity (A)" (with the
# dash) doesn't match "total equity" as a contiguous substring, so the search
# fell through to that later, wrong, much bigger total.
_EQUITY_SHARE_CAPITAL_LABELS = [
    "equity share capital",
]
_PBT_LABELS = [
    "profit before share of profit / (loss) of associates / joint ventures and tax", "profit before share of profit of associates and joint ventures and tax",
    "profit before share of profit/(loss) of associates and joint ventures and tax", "profit before share of associates and tax",
    # The plain "profit before tax" (the TRUE final PBT - after Exceptional
    # Items, immediately before Tax Expense) is tried FIRST, ahead of the
    # "before exceptional items and tax" subtotals. Those are a DIFFERENT,
    # larger figure (Exceptional Items not yet deducted) - when a filing
    # prints both (e.g. Gopal Snacks: "Profit before exceptional items and
    # tax" → "Exceptional items" → "Profit before tax"), matching whichever
    # synonym happened to be tried first is wrong; the two are NOT
    # interchangeable. `_find_pl_row` returns on the first label that
    # matches, so this list's ORDER is a correctness decision - confirmed
    # this was silently grabbing the "before exceptional items" subtotal
    # instead of the real final PBT wherever both exist, corrupting every
    # ratio that reads `parsed["pbt"]` (ROIC, Effective Tax Rate, Altman
    # Z-Score, Interest Coverage Ratio). The "before exceptional items"
    # variants are kept as a FALLBACK only, for the (much rarer) filing that
    # never prints a separate final "profit before tax" line at all.
    #
    # Deliberately DROPPED "profit before tax AND exceptional items" (a
    # phrasing variant of the before-exceptional subtotal) - it literally
    # STARTS WITH "profit before tax", so once that's tried first it can
    # never be distinctly reached anyway (label-order search would already
    # have matched the plain-PBT prefix), making it dead weight that only
    # risked silently matching the wrong subtotal if ever reordered again.
    "profit before tax", "profit before exceptional items and tax", "profit before exceptional item and tax",
    # Same "/(Loss)" suffix issue as `_PAT_GENERIC_LABELS`/`_PAT_OWNERS_LABELS`
    # (Sr No 16 fix) - loss-making-history filings (e.g. Eternal/Zomato)
    # caption this "Profit/(Loss) before tax" rather than plain "Profit
    # before tax". `_find_pl_row` already normalises this via
    # `_strip_formula_refs` before matching, but these are kept explicitly in
    # the canonical list too (belt-and-suspenders): a match must never be
    # skipped just because of the "/(Loss)" suffix.
    "profit/(loss) before tax", "profit/(loss) before exceptional items and tax",
    "profit/(loss) before exceptional item and tax",
]
def _find_eps_row(text):
    """Basic EPS - Ind AS Schedule III mandates this disclosure on the P&L
    page (or its immediate continuation) under an "Earnings per equity
    share" heading. Three real-filing layouts seen: a single combined "Basic
    and diluted (in ₹)" SUB-LABEL row (when there are no dilutive
    instruments - same value both ways); Basic and Diluted printed as two
    SEPARATE bare-word rows ("Basic\n461.20\n429.01\nDiluted\n461.20\n429.01",
    seen on MARUTI); OR the combined-value case captioned entirely in the
    HEADING itself ("Basic and Diluted Earnings per Equity Share (in ₹)"
    followed directly by the two numbers, no separate sub-label line at
    all) - this third layout used to silently fail extraction (no "basic"/
    "diluted" text appears AFTER the heading to anchor on) until the
    pre-heading check below was added. A generic label-list scan (like every
    other row in this file) can't safely use a bare "basic" label - it could
    false-match elsewhere on the page - so this is BOUNDED to the text
    immediately after the "Earnings per equity share" heading, where "Basic"
    is unambiguous. Only Basic is read, never Diluted, per spec's "state
    explicitly whether Basic or Diluted is used". Some filings (e.g. Tata
    Steel) head this section plainly as "Earnings per share" - without
    "equity" - so the heading anchor accepts both."""
    # Some filings (e.g. Eternal/Zomato) caption this "Earnings / (loss) per
    # equity share" - the same "/(loss)" qualifier infix seen on PBT/PAT
    # captions elsewhere, here breaking the heading anchor itself.
    # "earnings?" (not just "earnings") - some filers (e.g. Prime Fresh
    # Limited) caption this "Earning Per Equity Share" in the singular,
    # which the plural-only pattern previously never matched at all,
    # silently leaving EPS (and everything derived from it - P/E, PEG,
    # EPS Growth, Dividend Payout, ...) not_disclosed despite the figure
    # being printed directly on the face of the P&L statement.
    # Built via `_fuzzy_label_re` for "per equity share"/"per share" so this
    # heading anchor tolerates the same stray-space rendering artifact
    # `_find_row_values` already does - confirmed real on TCS's FY2026 P&L,
    # whose own heading extracts as "Earnings per eq uity share:-" (a space
    # inside "equity"). Left unfixed, this heading anchor never matched at
    # all, so EPS (and P/E, EPS Growth, PEG, Graham Number, Dividend Payout
    # derived from it) were all reported not_disclosed despite Basic EPS
    # being printed directly on the face of the P&L.
    m = re.search(
        r"earnings?\s*(?:/\s*\(\s*loss\s*\))?\s*" + _fuzzy_label_re("per equity share")
        + r"|earnings?\s*(?:/\s*\(\s*loss\s*\))?\s*" + _fuzzy_label_re("per share"),
        text, re.I)
    if not m:
        return None
    window = text[m.end():m.end() + 400]
    # `_NUM_RE`'s plain-decimal alternative requires 2+ integer digits
    # (by design, to avoid mistaking a bare Note/Page-number column for a
    # real value elsewhere in this file) - but EPS is routinely a
    # single-digit-plus-decimal figure (e.g. "2.74"), which that pattern
    # silently can't see at all. Confirmed on Tata Steel: the window held
    # "Basic (I)\n2.74\n(3.62)" and `_NUM_RE` only matched "(3.62)" TWICE
    # (the parenthesised-negative alternative has no digit-count floor),
    # never the genuine "2.74" - so the current year was silently read as
    # the prior year's value. Scoped to just this function (not a global
    # `_NUM_RE` change, which is too large a blast radius per the Sr No 20
    # "bare small integer" bug fix) since by this point in the text we're
    # well past any Note/Page-number columns (confirmed those always
    # appear BEFORE the Basic/Diluted line in every filing seen).
    eps_num_re = r"\(-?[\d,]+(?:\.\d{1,2})?\)|-?[\d,]+\.\d{1,2}"
    for label in ("basic and diluted", "basic & diluted", "basic / diluted", "basic and diluted eps", "basic"):
        lm = re.search(_fuzzy_label_re(label), window, re.I)
        if not lm:
            continue
        nums = re.findall(eps_num_re, window[lm.end():lm.end() + 150])
        if len(nums) >= 2:
            a, b = _parse_num(nums[0]), _parse_num(nums[1])
            if a is not None and b is not None:
                return a, b

    # Some filings caption the combined single-value row entirely in the
    # HEADING itself - "Basic and Diluted Earnings per Equity Share (in ₹)"
    # - rather than printing a "Basic"/"Basic and Diluted" sub-label on its
    # own line before the two numbers. The loop above only searches AFTER
    # the "earnings per share" match, so it never sees "basic"/"diluted"
    # text that appeared BEFORE it in the heading, and returns None even
    # though there's genuinely only one EPS figure (current + prior) to
    # read - a real extraction gap, not a missing-data case. Check the text
    # immediately preceding the heading match for that "basic"/"diluted"
    # qualifier; if present, there's no separate label line to anchor on, so
    # read the first two EPS-shaped numbers directly from the window.
    preheading = text[max(0, m.start() - 60):m.start()].lower()
    if "basic" in preheading or "diluted" in preheading:
        nums = re.findall(eps_num_re, window)
        if len(nums) >= 2:
            a, b = _parse_num(nums[0]), _parse_num(nums[1])
            if a is not None and b is not None:
                return a, b
    return None


_ATTRIB_OWNER_RE = re.compile(
    r"(?:owners?|shareholders|equity\s+holders|proprietors)\s+of\s+the\s+(?:holding\s+|parent\s+)?"
    r"(?:company|parent|group)\s*[\s|:]*(?P<a>\(?-?[\d,]+(?:\.\d+)?\)?)\s*[\s|]+(?P<b>\(?-?[\d,]+(?:\.\d+)?\)?)", re.I)
_PROFIT_TOTAL_RE = re.compile(
    r"profit\s*(?:/\s*\(\s*loss\s*\))?\s*for\s+the\s+(?:year|period)(?:\s*\(\s*[a-z]\s*\))?\s*[\s|:]*"
    r"(?P<a>\(?-?[\d,]+(?:\.\d+)?\)?)\s*[\s|]+(?P<b>\(?-?[\d,]+(?:\.\d+)?\)?)", re.I)


def _repair_owners_pat(pat, pat_basis, pl_text, pl_factor, eps, shares):
    """Self-validating repair of the owners' PAT read from the P&L page.

    The label-matching reader can return the wrong figure (TCS: 16,234 instead of 48,553; HUL: 40,350 instead of
    10,649) when the owners' line is captioned "Shareholders of the Company" / "Owners of the Company" under a
    "Profit for the year attributable to:" heading. Candidates are every "<owners|shareholders> of the company
    <cur> <prior>" pair on the page; one is accepted ONLY when it is consistent with the statement's own totals:
      * within 35% of the page's "Profit for the year" total (the NCI share cannot be that large), and
      * within 35% of Basic EPS x shares outstanding when both are known.
    The existing value is kept whenever it already passes the same tests. Returns (pat, basis, repaired, total):
    `total` is the page's whole-entity "Profit for the year" pair when it is consistent with the owners' figure
    (so OCF/Net Profit, Piotroski and Beneish can use a whole-entity profit), else None."""
    def num(t):
        return _parse_num(t)

    def consistent(cur, ref):
        return ref is None or abs(ref) < 1e-9 or abs(cur - ref) <= 0.35 * abs(ref)

    total = None
    tm = _PROFIT_TOTAL_RE.search(pl_text)
    if tm:
        a, b = num(tm.group("a")), num(tm.group("b"))
        if a is not None and b is not None:
            total = _scale((a, b), pl_factor)
    implied = None
    if eps is not None and eps[0] is not None and shares is not None and shares[0]:
        implied = eps[0] * shares[0] / 1e7
    def ok(cand):
        return consistent(cand[0], total[0] if total else None) and consistent(cand[0], implied)
    if pat is not None and ok(pat) and (total is not None or implied is not None):
        return pat, pat_basis, False, (total if total is not None and consistent(pat[0], total[0]) else None)
    cands = []
    for m in _ATTRIB_OWNER_RE.finditer(pl_text):
        a, b = num(m.group("a")), num(m.group("b"))
        if a is not None and b is not None:
            cands.append(_scale((a, b), pl_factor))
    for cand in cands:
        if (total is not None or implied is not None) and ok(cand):
            return cand, "owners", True, (total if total is not None and consistent(cand[0], total[0]) else None)
    return pat, pat_basis, False, None



def _find_eps_owners_row(text):
    """Basic EPS ATTRIBUTABLE TO OWNERS when the P&L prints it as its own line
    ("Basic ... - Excluding Non-controlling interest" / "...attributable to
    owners of the parent"). Returns (current, prior) or None. A consolidated
    P&L that prints only ONE Basic EPS gets None here - that single figure is
    already owners-attributable under Ind AS 33 (the consumer records that as
    the basis)."""
    m = re.search(
        r"basic[^\d]{0,60}?(?:excluding\s+non[\s-]*controlling|attributable\s+to\s+(?:the\s+)?"
        r"(?:owners|equity\s+holders|shareholders))[^\d]{0,60}?"
        r"(\(-?[\d,]+(?:\.\d{1,2})?\)|-?[\d,]+\.\d{1,2})\s+(\(-?[\d,]+(?:\.\d{1,2})?\)|-?[\d,]+\.\d{1,2})",
        text, re.I)
    if not m:
        return None
    a, b = _parse_num(m.group(1)), _parse_num(m.group(2))
    return (a, b) if a is not None and b is not None else None


def _find_shares_outstanding(doc, start_idx, want_section, max_pages=250):
    """Number of Equity Shares Outstanding (Sr No 25 denominator component) -
    NOT disclosed on the primary Balance Sheet page itself; it lives in the
    "Equity Share Capital" NOTE (Ind AS Schedule III), which can be dozens to
    hundreds of pages after the statement (seen on MARUTI: BS on page ~35,
    this note on page ~190). Scans forward, page by page, from the Balance
    Sheet page already found - Notes always follow the statements they
    describe, so no need to scan backward or from page 0.

    Re-tracks the standalone/consolidated section transition using the SAME
    narrow statement-caption anchors as the main page-detection loop (not the
    broad "financial statements" phrase that caused the TOC/Notes-pollution
    bug fixed earlier this suite) - a Consolidated Annual Report's Notes
    section can also print a SUBSIDIARY's own separate share capital note;
    without re-checking section, that could be picked up instead of the
    parent company's own (the one actually relevant to Market Cap ÷ market
    price per share).

    Looks for "issued, subscribed and fully paid" (the standard sub-heading
    within the note) followed by an "X equity shares of ₹Y each" line for the
    current year, with the prior year's count usually printed in an adjacent
    "(as at <prior date>: X equity shares...)" parenthetical on the SAME
    line. Returns (current, prior) as raw share COUNTS - never Crore-scaled,
    same reasoning as EPS.

    Some filings (e.g. Tata Steel) head this sub-section just "Subscribed
    and paid up:" - no "Issued" prefix, "paid up" instead of "fully paid" -
    and call the shares "Ordinary Shares" rather than "Equity Shares"; the
    heading regex accepts both phrasings (the number-floor filter below
    doesn't depend on the word "equity"/"ordinary" appearing at all, so no
    further change was needed once the heading itself matches).

    Rebuilt with a 3-PRIORITY fallback (this was the single biggest
    cascading failure in the whole suite - Market Cap feeds Sr No 24-26/29
    and Price/Cash Flow/FCF Yield, so a share-count miss here silently broke
    four-plus ratios at once):
      1. The "Reconciliation of the number of shares outstanding" note's
         CLOSING balance ("...at the end of the year/reporting period") -
         the most authoritative figure when present, since it's explicitly
         the movement-reconciled closing count (correct even after a
         buyback/rights issue/ESOP allotment during the year), not just a
         static snapshot.
      2. The static "Issued, Subscribed and Fully Paid" (or, now, the
         version WITHOUT "Fully" - "Issued, Subscribed and Paid-up", seen on
         filings that don't use that qualifier at all) line - the previous
         sole method.
      3. Computed via Face Value: Equity Share Capital (₹) ÷ Face Value per
         share - the last-resort fallback when neither of the above prints
         a raw share count at all (some filings disclose Share Capital only
         in ₹ terms alongside a "face value of ₹X each" note)."""
    section = want_section
    # Two independent result sets: `_r` (matching `want_section`, the
    # correct/preferred scope) and `_any` (whatever section the page
    # actually belongs to, tracked as a fallback - see below for why).
    state = {"recon": None, "static": None, "face_value": None, "share_capital_cur": None}
    any_state = {"recon": None, "static": None, "face_value": None, "share_capital_cur": None}

    def _scan_page(t, tl, st):
        # Priority 1: Reconciliation table closing balance. MANUAL-UPLOAD
        # WORKFLOW ONLY: also accepts the EPS note's "Weighted Average
        # Number of Equity Shares" heading as an alternate trigger (never
        # changes the automatic/live pipeline - gated on `is_manual_mode()`).
        # Some filers (confirmed real on Prime Fresh Limited/
        # LANDMARKACHIEVE) never print a genuine "Issued, Subscribed and
        # Fully Paid" static line NOR a dedicated "Reconciliation of
        # Shares" table anywhere - the EPS computation note's own
        # "...Outstanding At The End Of The Year" row (which, by
        # construction, is the actual closing share count: a weighted
        # average that starts and ends the year at the true opening/
        # closing balances) is the ONLY place the figure is disclosed at
        # all. The "outstanding at"-anchored number extraction just below
        # is unaffected either way - it always targets that one specific
        # row, never the adjacent "at the beginning of the year" row.
        recon_heading = re.search(r"reconciliation of (?:the )?(?:number of )?shares", tl)
        if recon_heading is None:
            recon_heading = re.search(r"weighted average number of equity shares", tl)
        if st["recon"] is None and recon_heading:
            rm = re.search(r"(?:outstanding |shares )?at the end of the (?:year|reporting period)", tl)
            if rm:
                window = t[rm.end():rm.end() + 150]
                nums = [_parse_num(n) for n in _row_nums(window)]
                nums = [n for n in nums if n is not None and n >= 100000]
                if nums:
                    st["recon"] = (nums[0], None)
            if st["recon"] is None:
                # Some filers' row label wraps AROUND the numeric columns
                # instead of preceding them as one contiguous phrase - e.g.
                # "Shares Out Standing At 13,879,861 1,387.99 ... The End
                # Of The Year" (confirmed real on Prime Fresh Limited: the
                # PDF's column layout interposes the figures between "At"
                # and "The End Of The Year", so the full "at the end of
                # the year" phrase above never matches contiguously at
                # all). Anchor on "out standing at" / "outstanding at"
                # instead and read the numbers that immediately follow.
                # NOTE: this same "outstanding at" prefix also appears in
                # the EPS note's "Weighted Average Number of Equity Shares
                # Outstanding At The End Of The Year" row - a DIFFERENT
                # concept (the EPS denominator, not the closing count).
                # For a filer with no share issuance/buyback during the
                # year the two numbers are numerically identical anyway,
                # so this is a acceptable, non-fabricating fallback only
                # when the genuine "reconciliation of shares" heading
                # (checked above) is present on this same page - the outer
                # `if` already guards on that heading being found first.
                rm2 = re.search(r"out\s*standing\s+at\b", tl)
                if rm2:
                    window2 = t[rm2.end():rm2.end() + 150]
                    nums2 = [_parse_num(n) for n in _row_nums(window2)]
                    nums2 = [n for n in nums2 if n is not None and n >= 100000]
                    if nums2:
                        st["recon"] = (nums2[0], None)

        # Priority 2: static Issued/Subscribed/(Fully) Paid line - now also
        # accepting the version without "Fully" ("issued, subscribed and
        # paid" with no "up"/"fully" qualifier at all).
        if st["static"] is None:
            m = re.search(r"issued,?\s*subscribed and fully paid|issued,?\s*subscribed and paid"
                           r"|subscribed and (?:fully )?paid[\s-]?up", tl)
            if m:
                window = t[m.end():m.end() + 300]
                # The current-year share count isn't always immediately
                # adjacent to "equity shares" - some filings interpose a
                # "[as at <prior date>: <prior count>]" bracket between the
                # current count and that label (seen on DMART: "65,07,33,068
                # [31st March, 2024: 65,07,33,068] equity Shares of ₹10
                # each"), so an "equity shares"-anchored lookahead misses the
                # FIRST number entirely. Instead, take the first two numbers
                # in the window above a share-count-sized floor (>=100,000)
                # - comfortably above any face-value/₹-Crore amount printed
                # alongside (e.g. "750.00", "1,572"), which are always much
                # smaller. Handles both Western (314,402,574) and Indian
                # (65,07,33,068) comma grouping via the shared `_NUM_RE`.
                candidates = [_parse_num(n) for n in _row_nums(window)]
                share_nums = [n for n in candidates if n is not None and n >= 100000]
                if share_nums:
                    cur = share_nums[0]
                    prior = share_nums[1] if len(share_nums) >= 2 else None
                    if cur is not None and cur > 0:
                        st["static"] = (cur, prior)

        # Priority 2b: a share-class table row - "Ordinary Shares of ` 1.00 each, fully paid  12,51,41,19,781  1251.41
        # 12,48,47,21,471  1248.47" (closing count, amount, opening count, amount). The authorised row has no "fully paid".
        if st["static"] is None:
            from tools.document_analysis_engine import _CLASS_ROW_SHARES_RE
            cm2 = _CLASS_ROW_SHARES_RE.search(re.sub(r"\s+", " ", t))
            if cm2:
                try:
                    c_, p_ = float(cm2.group(1).replace(",", "")), float(cm2.group(3).replace(",", ""))
                    if c_ > 0 and 0.5 <= p_ / c_ <= 2.0:
                        st["static"] = (c_, p_)
                except ValueError:
                    pass

        # Priority 3 inputs: Equity Share Capital (₹, from the same note) and
        # Face Value per share, for the computed fallback ("shares = Equity
        # Share Capital ÷ Face Value") - used only when neither the
        # Reconciliation table nor the static Issued/Subscribed line above
        # ever discloses a raw share count directly.
        if st["share_capital_cur"] is None:
            cm = re.search(r"equity share capital", tl)
            if cm:
                window = t[cm.end():cm.end() + 150]
                nums = _row_nums(window)
                if nums:
                    v = _parse_num(nums[0])
                    if v is not None and v > 0:
                        st["share_capital_cur"] = v * _unit_factor(t)
        if st["face_value"] is None and st["share_capital_cur"] is not None:
            fm = re.search(r"face value of\s*`?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(?:each|per share)", tl)
            if fm:
                fv = _parse_num(fm.group(1))
                if fv and fv > 0:
                    st["face_value"] = (round((st["share_capital_cur"] * 1e7) / fv), None)

    # MANUAL-UPLOAD WORKFLOW ONLY: scan from the very start of the document,
    # not just forward from `start_idx` (the requested section's own
    # Balance Sheet page). "Notes always follow the statements they
    # describe" (this function's own original assumption) holds within ONE
    # section, but the note this function actually needs may only be
    # disclosed under the OTHER section - and Indian filings conventionally
    # print Standalone financials BEFORE Consolidated ones, so a
    # `want_section="consolidated"` request's relevant Standalone note can
    # sit BEFORE `start_idx` entirely, unreachable by a forward-only scan.
    # Confirmed real on Prime Fresh Limited/LANDMARKACHIEVE: the Equity
    # Share Capital/EPS note lives on a page captioned "Standalone
    # Statement of Profit and Loss", several dozen pages BEFORE the
    # Consolidated Balance Sheet this function was asked to scan forward
    # from. Never changes the automatic/live pipeline (`is_manual_mode()`
    # False keeps the original forward-only range exactly as before).
    scan_start = 0
    for i in range(scan_start, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        if "consolidated balance sheet" in tl or "consolidated statement of profit" in tl:
            section = "consolidated"
        elif "standalone balance sheet" in tl \
                or (_has_pl_caption(tl) and "consolidated" not in tl):
            section = "standalone"

        # ALWAYS scan this page into the any-section fallback set, in
        # addition to the section-matched set when it applies. Number of
        # Equity Shares Outstanding is a PARENT-COMPANY-level disclosure -
        # consolidation (adding subsidiaries' assets/liabilities/results)
        # never changes how many shares the PARENT itself has issued, so
        # the Equity Share Capital/shares-reconciliation note is routinely
        # printed ONLY under whichever section (usually standalone) came
        # first in the filing, with the other section's statements simply
        # cross-referencing it rather than repeating it - confirmed real
        # on Prime Fresh Limited/LANDMARKACHIEVE: the only page with this
        # note is captioned "Standalone Statement of Profit and Loss", so
        # a `want_section="consolidated"` request found nothing at all
        # even though the parent's share count is identical either way.
        # Matches this file's own existing "dividends are ALWAYS
        # standalone-sourced regardless of the consolidated/standalone
        # flag" precedent (`_find_dividend_per_share`) - shares outstanding
        # is the same kind of parent-entity-only concept.
        if section == want_section:
            _scan_page(t, tl, state)
        else:
            _scan_page(t, tl, any_state)

        if state["recon"] is not None:
            break

    result = state["recon"] or state["static"] or state["face_value"]
    if result is not None:
        return result
    # MANUAL-UPLOAD WORKFLOW ONLY - never changes the automatic/live
    # pipeline's existing behaviour (gated on `is_manual_mode()`): falling
    # back to a match found in the OTHER section when `want_section`
    # itself has none. See the "ALWAYS scan into the any-section fallback
    # set" comment above for why this is safe/correct (a parent-entity-
    # level disclosure, not something that genuinely differs by section).
    return any_state["recon"] or any_state["static"] or any_state["face_value"]


def _find_dividend_per_share(doc, start_idx, max_pages=250):
    """Total Dividend per Equity Share for the CURRENT fiscal year (Sr No 27
    numerator) - lives in the Retained Earnings movement note, right next to
    (often the same note number as) the Equity Share Capital note. Per spec,
    dividends are ALWAYS sourced STANDALONE regardless of which basis
    (consolidated/standalone) every other ratio in this suite uses -
    dividends are declared by the parent entity, not on a consolidated
    basis - so this ALWAYS tracks toward "standalone", ignoring the
    `consolidated` flag every other extractor respects.

    Per QA (2026-07-30, matching Screener's convention and standard market
    usage): this year's INTERIM dividend + this year's PROPOSED final
    dividend (board-recommended, subject to AGM approval, not yet a
    recognised liability) - e.g. HUL: Interim ₹19/share (FY25-26) +
    Proposed Final ₹22/share (FY25-26) = ₹41. Deliberately does NOT include
    the "declared and paid" FINAL dividend row some filers ALSO print in
    the same note - that figure is last fiscal year's approved final
    dividend, merely PAID during the current year's cash flow, not part of
    the current year's own declared dividend total (e.g. HUL's "Final
    dividend of ₹24 per share for FY 2024-25" is a PRIOR-year amount and
    must be excluded here even though the cash left the company this year).
    A tabulated note breaks these out as separate Final/Interim/Special
    rows (seen on HUL: "NOTE X DIVIDEND ON EQUITY SHARE"); Interim and
    Special rows under the (non-proposed) main heading are inherently
    ALWAYS for the current year (a company never "interim-declares" a
    PRIOR year's dividend), so those are summed unconditionally; the
    current-year Final component comes ONLY from the separate "Proposed
    dividend ... not recognised as liability" sub-heading, never from the
    main declared-and-paid Final row.

    A single narrative sentence ("During the year, a dividend of ₹X per
    share ... was paid") is tried first for filers that don't tabulate -
    that sentence describes cash actually paid (same "prior year's approved
    final" caveat applies, but there's no separate current-year proposed
    figure to add for these simpler filings, so it's used as-is).

    Per spec, "no dividend declared" is a real 0%, NOT missing data - so
    finding no match here returns 0.0 at REDUCED confidence (0.4) rather
    than None, since a genuine zero-dividend company is indistinguishable
    from an extraction miss without a stronger signal; the low confidence
    flags it for the later full-registry audit rather than silently
    asserting a fact this reader can't actually verify either way."""
    section = None
    for i in range(start_idx, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        if _is_stmt_heading(tl, "consolidated balance sheet") \
                or _is_stmt_heading(tl, "consolidated statement of profit"):
            section = "consolidated"
        elif _is_stmt_heading(tl, "standalone balance sheet") \
                or (_has_pl_caption(tl) and "consolidated" not in tl):
            section = "standalone"
        if section == "consolidated":
            continue
        # The tabulated Notes-to-Accounts path below is gated to the
        # standalone FINANCIAL STATEMENTS section (dividends are always
        # standalone-sourced, and a tabulated note can appear duplicated
        # under both standalone/consolidated notes). The narrative-sentence
        # fallback further down is NOT gated the same way - a filer that
        # never tabulates at all (e.g. Gopal Snacks) only states its
        # dividend in the DIRECTORS' REPORT, which always sits BEFORE either
        # financial-statements section even begins (`section` is still
        # `None` at that point) - confirmed this silently skipped page 32
        # entirely (Gopal's own dividend disclosure) since the old blanket
        # `if section != "standalone": continue` gate ran before the
        # narrative regexes ever got a chance to see that page.
        if section == "standalone":
            # Tabulated note (tried FIRST - a filer that tabulates Final/
            # Interim/Special separately always has this be the
            # authoritative figure; the narrative sentence below, if also
            # present, describes the same "declared and paid" cash figure
            # and would double-count Interim).
            anchor = re.search(r"declared and paid during the year", t, re.I)
        else:
            anchor = None
        if anchor:
            window = t[anchor.end():anchor.end() + 700]
            stop = re.search(r"proposed dividend", window, re.I)
            proposed_window = window[stop.start():stop.start() + 400] if stop else ""
            if stop:
                window = window[:stop.start()]

            def _sum_rows(text, kinds):
                total, found = 0.0, False
                for line in text.split("\n"):
                    line_no_paren = re.sub(r"\([^)]*\)", "", line)
                    rm = re.search(
                        rf"(?:{kinds})\s+dividend\s+of\s*[^\d\s]{{0,2}}\s*"
                        r"(nil|[\d,]+(?:\.\d+)?)\s*(?:per\s+)?(?:equity\s+)?share",
                        line_no_paren, re.I)
                    if rm:
                        v = 0.0 if rm.group(1).lower() == "nil" else _parse_num(rm.group(1))
                        if v is not None:
                            total += v
                            found = True
                return total, found

            # Interim/Special under the main heading are always CURRENT-year
            # (never a prior-year carryover) - sum unconditionally. The main
            # heading's Final row is EXCLUDED (that's last year's approved
            # dividend, merely paid in cash this year); current-year Final
            # comes only from the "Proposed" sub-section below.
            row_total, row_found = _sum_rows(window, "interim|special")
            if proposed_window:
                prop_total, prop_found = _sum_rows(proposed_window, "final")
                row_total += prop_total
                row_found = row_found or prop_found
            if row_found:
                return round(row_total, 2), True

        # Currency prefix between "dividend of" and the figure isn't always
        # a single-char symbol/placeholder - Dabur's PDF spells it out as
        # the literal word "Rs." (with its OWN trailing space/newline
        # before the number: "dividend of rs. \n2.75 per equity share"),
        # which neither the backtick placeholder nor a 0-2-char symbol class
        # can match. Shared across `m`/`m2`/`fm` below so all three
        # narrative patterns tolerate the same currency-prefix variants.
        _cur = r"(?:rs\.?\s*|inr\s*|`\s*|[^\da-z\s]{0,2}\s*)?"
        m = re.search(rf"during the year,?\s*a dividend of\s*{_cur}([\d,]+(?:\.\d+)?)\s*per share", tl)
        if m:
            v = _parse_num(m.group(1))
            if v is not None:
                return v, True  # (value, found_with_confidence)
        m2 = re.search(rf"dividend of\s*{_cur}([\d,]+(?:\.\d+)?)\s*per (?:equity )?share[^.]{{0,60}}(?:was paid|paid to)", tl)
        if m2:
            v = _parse_num(m2.group(1))
            if v is not None:
                # Some filers (e.g. Dabur's AGM Notice / Shareholder
                # Information page, never tabulated) state Interim (paid)
                # and Final/Proposed (recommended) dividends as TWO
                # SEPARATE narrative sentences on the same page - m2 above
                # only ever finds the interim "was paid" leg on its own,
                # silently dropping the equally-current-year final/proposed
                # leg (confirmed on Dabur FY26: interim ₹2.75 + final ₹5.5
                # recommended, m2 alone would report only ₹2.75). Mirrors
                # the tabulated Interim+Proposed-Final summing convention
                # above - look for a companion "final dividend ...
                # recommended/proposed" sentence on the SAME page and add it
                # if present.
                fm = re.search(
                    rf"final\s+dividend\s+of\s*{_cur}([\d,]+(?:\.\d+)?)\s*per\s*(?:equity\s+)?share"
                    r"[^.]{0,120}(?:recommended|proposed)", tl)
                if fm:
                    fv = _parse_num(fm.group(1))
                    if fv is not None:
                        return round(v + fv, 2), True
                return v, True

        # A third, common narrative phrasing puts the "paid"/"declared" verb
        # BEFORE the per-share figure instead of after (e.g. Gopal Snacks
        # FY25 Directors' Report: "the Board of Directors has paid an
        # interim dividend of ₹1.00 per equity share ... during the year") -
        # neither of the two patterns above match this word order (the first
        # requires "during the year" to IMMEDIATELY precede "a dividend of";
        # the second requires "was paid"/"paid to" to follow the per-share
        # figure within 60 chars), so this genuinely common phrasing was
        # silently returning the unconfirmed 0.0 default. Confirmed only
        # ONE such sentence is ever present when a filer narrates rather
        # than tabulates (no separate current-year Final to also add), so a
        # single match is sufficient here, unlike the tabulated path above.
        # The currency symbol before the figure isn't always the literal "`"
        # placeholder `m`/`m2` above assume (a font-specific glyph
        # substitution seen on some filings) - Gopal Snacks' PDF instead
        # embeds the genuine "₹" Unicode character, which neither `\s` nor
        # "`" can match, so `[^\d\s]{0,2}` (any 0-2 non-digit/non-space
        # symbol chars - mirrors `_sum_rows`'s own tolerance a few lines up)
        # is used here instead of a single hardcoded placeholder.
        m3 = re.search(
            rf"(?:has\s+)?(?:paid|declared|recommended)\s+(?:an?\s+)?(?:interim\s+|final\s+|special\s+)?"
            rf"dividend\s+of\s*{_cur}([\d,]+(?:\.\d+)?)\s*per\s*(?:equity\s+)?share", tl)
        if m3:
            v = _parse_num(m3.group(1))
            if v is not None:
                return v, True

        # Un-gated from manual-upload-only: BSE's own live-hosted copy of
        # TCS's FY2026 Annual Report (a genuinely different PDF file from
        # the manually-uploaded one, fetched independently by the automatic
        # pipeline) carries the IDENTICAL "for a total of ₹110 per share
        # for FY 2026" sentence - confirmed by direct comparison of both
        # PDFs' extracted text. The pattern itself names no company/wording
        # unique to either pipeline (standard Companies Act 2013 Directors'
        # Report phrasing), so restricting it to manual-mode only left the
        # automatic/live pipeline reporting a false 0% Dividend Payout
        # Ratio/100% Retention Ratio for the exact same real filing.
        #
        # A fourth narrative shape: a MULTI-COMPONENT dividend (multiple
        # interim tranches + a special dividend + a recommended final
        # dividend, or any other combination) described in a single
        # sentence that ends by stating the pre-summed TOTAL, rather than
        # a single "a dividend of X per share" figure any of m/m2/m3 above
        # can match - confirmed real on TCS FY2026 (a Performance
        # Highlights narrative, before either financial-statements section
        # begins, same as the Gopal Snacks case this function's docstring
        # already documents): "...the Board of Directors have declared
        # three interim dividends of ₹11 each, a special dividend of ₹46,
        # and recommended a final dividend of ₹31 ... for a total of ₹110
        # per share for FY 2026." None of m/m2/m3 match this - m3's
        # singular "a/an dividend of" doesn't allow for "three interim
        # dividends" (plural, with a quantifier), and there is no
        # per-component breakdown pattern generic enough to enumerate every
        # possible combination of tranches. Rather than trying to parse and
        # sum each component (fragile - filers phrase multi-part dividends
        # in many different ways), this looks for the filing's OWN stated
        # total instead - a much more universal anchor, matching the
        # existing established project convention: current-year Interim +
        # Special + PROPOSED Final (never last year's already-paid Final),
        # which is exactly what a filer's own "for a total of ₹X per share
        # for FY <year>" summary sentence already represents. Requires the
        # word "dividend" to appear within the preceding ~250 characters (a
        # Python-level check, not baked into the regex itself) so a
        # coincidental, unrelated "...for a total of ₹X per share..."
        # sentence about something else (e.g. a rights issue or bonus
        # price) is never mistaken for a dividend total.
        m4 = re.search(rf"(?:for a )?total of\s*{_cur}([\d,]+(?:\.\d+)?)\s*per\s*(?:equity\s+)?share", tl)
        if m4 and "dividend" in tl[max(0, m4.start() - 250):m4.start()]:
            v = _parse_num(m4.group(1))
            if v is not None:
                return v, True
    return 0.0, False

# NOTE on the `start_idx` argument used at the call site below: Standalone
# financial statements ALWAYS precede Consolidated ones in the regulatory
# Ind AS filing template - so this is always called with start_idx=0 (NOT
# bs_idx, which for a consolidated=True extraction points at the LATER
# Consolidated Balance Sheet page and would scan past the earlier Standalone
# Retained Earnings note entirely, forward-only).


# Debt Service Coverage Ratio (Sr No 34) denominator components - the actual
# PRINCIPAL repaid during the year, from the Cash Flow Statement's Financing
# Activities section (NOT the Balance Sheet's outstanding Borrowings
# balance, and NOT netted against fresh borrowings raised in the same
# section - per spec, only the repayment outflow itself).
_REPAYMENT_BORROWINGS_LABELS = [
    "repayment of long-term borrowings", "repayment of long term borrowings",
    "repayment of non-current borrowings", "repayment of current borrowings",
    "repayment of term loans", "repayment of debentures", "repayment of non-convertible debentures",
    "redemption of debentures", "redemption of non-convertible debentures",
    "repayment of unsecured loans", "repayment of secured loans",
    "repayment of bank loans", "repayment of commercial paper", "repayment of cash credit",
    "repayment of vehicle loans", "repayment of buyer's credit", "repayment of buyers' credit",
    "repayment of external commercial borrowings",
    # Deliberately LAST - the generic catch-all, tried only after every more
    # specific instrument label above has had a chance to match. A filer
    # printing "Proceeds/(Repayment) of borrowings (net)" or "Movement in
    # borrowings (net)" (a single NETTED line, not a gross repayment figure)
    # is NOT in this list at all - per spec, a net figure must never be
    # silently treated as the gross repayment (it understates Total Debt
    # Service whenever fresh borrowings exceeded repayments that year, and
    # can even be a net INFLOW), so a filing with only that netted line
    # correctly falls through to "Could not find" instead of a wrong number.
    # Safe to add here: the fuzzy matcher only tolerates WHITESPACE between
    # a label's own characters (see `_fuzzy_label_re`), so a netted caption
    # like "(Repayments)/Proceeds from non-current borrowings" - which has
    # ")/Proceeds from non-current" (non-whitespace characters) sitting
    # between "Repayments" and "borrowings" - still can never match any of
    # these, regardless of how many singular/generic phrasings are added.
    "repayment of borrowings", "repayments of borrowings",
    "repayment of borrowing",
    "repayment of loans", "repayment of loan",
    "repayment of debt", "repayment of debts",
]
# Ind AS 116 splits a lease payment into interest and principal components in
# the Cash Flow Statement - only the PRINCIPAL portion belongs in Total Debt
# Service (the interest portion is already inside Finance Costs). Basis 1
# (default, per Sr No 34's own spec - note this is the OPPOSITE direction
# from Sr No 20/33's Basis 1, which INCLUDES leases; each ratio's Basis 1/2
# toggle is defined independently per its own spec row) EXCLUDES this from
# Total Debt Service; Basis 2 INCLUDES it.
_REPAYMENT_LEASE_LABELS = [
    "repayment of lease liabilities", "payment of lease liabilities",
    "principal payment of lease liabilities", "principal repayment of lease liabilities",
    "repayment of lease liability", "payment of lease liability",
    "repayment of lease obligations", "payment towards lease liabilities",
    "payment of principal portion of lease liabilities",
]
# DSCR (Sr No 34) Interest components - CASH interest actually PAID during
# the year, from the Cash Flow Statement's Financing Activities section
# (2026-07-31, per QA spec) - NOT the P&L's accrual-basis Finance Costs,
# for consistency with Principal Repayment which is already CFS-sourced
# (DSCR is a cash-adequacy question: can operating cash cover CASH debt
# service, not accrued expense). Split into borrowings-interest and
# lease-interest, mirroring the existing Repayment split, so each can be
# independently included/excluded per `lease_basis` the same way.
_INTEREST_PAID_LABELS = [
    "interest paid on borrowings", "interest paid on term loans",
    "interest paid on working capital loans", "interest paid on cash credit",
    "interest paid on overdraft", "interest paid on debentures",
    "interest paid on non-convertible debentures", "interest paid on ncds",
    "interest on loans", "interest and finance charges paid",
    "interest expense paid", "finance cost paid", "finance costs paid",
    # Deliberately LAST - the generic catch-all, same reasoning as
    # `_REPAYMENT_BORROWINGS_LABELS`'s trailing entry: tried only after
    # every more specific instrument label above has had a chance to match.
    "interest paid",
]
_INTEREST_LEASE_LABELS = [
    "interest paid on lease liabilities", "interest expense on lease liabilities",
    "finance cost on lease liabilities", "interest on lease obligations",
    "interest paid on right-of-use lease liabilities", "interest on lease liabilities",
]
# Cash Flow Coverage Ratio (Sr No 35) numerator - the FINAL, post-tax
# subtotal at the bottom of the Operating Activities section, NEVER the
# interim "Cash generated from operations (before tax)" subtotal that
# usually appears a few lines above it. Requiring "net cash" in the label
# (rather than a bare "cash generated from operations") is what keeps this
# from grabbing that earlier, pre-tax figure.
_OPERATING_CASH_FLOW_LABELS = [
    "net cash flow generated from operating activities", "net cash (used in) generated from operating activities", "net cash (used in)/ generated from operating activities", "cash flow generated from operating activities", "net cash flows (used in)/generated from operating activities", "net cash flow (used in)/generated from operating activities", "net cash flow from/(used in) operating activities", "net cash generated from operating activities (a)", "net cash flows from/(used in) operating activities",
    "net cash generated from operating activities", "net cash generated from/(used in) operating activities",
    "net cash (used in)/generated from operating activities", "net cash flow from operating activities",
    "net cash from operating activities", "net cash inflow from operating activities",
    "net cash (used in) operating activities", "net cash generated by operating activities",
    "net cash provided by operating activities", "cash flow from operating activities",
    "net cash flows from operating activities", "net cash flows generated from operating activities",
    # "Net cash from/(used in) operating activities" (confirmed on Tata
    # Steel) - a DIFFERENT parenthetical insertion point than the two
    # "generated from/(used in)"/"(used in)/generated from" variants above,
    # which substring-match fails on entirely (the extra "/(used in)" text
    # sits in the middle of the phrase, breaking a match against either
    # "net cash from operating activities" or "net cash generated from
    # operating activities" alone).
    "net cash from/(used in) operating activities", "net cash used in/generated from operating activities",
    "net cash generated/(used in) operating activities",
    # Missing the "net"/"generated" prefix entirely (confirmed on Gopal
    # Snacks: "Cash flow from/(used in) operating activities") - the
    # section-heading CAPTION itself doubling as the subtotal's own row
    # label, common on smaller/recently-listed filers.
    "cash flow from/(used in) operating activities", "cash flow from operating activities",
    "cash flows from/(used in) operating activities",
]
# Free Cash Flow (Sr No 36) denominator components - Capital Expenditure,
# from the Cash Flow Statement's INVESTING ACTIVITIES section, NEVER the
# Balance Sheet's gross block movement (which can include revaluations/
# acquisitions unrelated to organic capex) and NEVER accounting Depreciation
# used as a proxy. Purchase of PP&E and Purchase of Intangible Assets are
# each their OWN separate line - summed individually rather than requiring
# both (a services business may have no PP&E purchase line at all); Proceeds
# from disposal is netted OFF per spec ("net Capex"), not ignored.
_CAPEX_PPE_PURCHASE_LABELS = [
    "expenditure for property, plant and equipment", "expenditure on property, plant and equipment",
    "expenditure on property plant and equipment and intangible assets",
    "purchase of property, plant and equipment", "purchase of property, plant & equipment",
    "purchase of fixed assets", "purchase of tangible assets", "purchase of capital assets",
    "additions to property, plant and equipment", "payments for property, plant and equipment",
    "payment for property, plant and equipment", "acquisition of property, plant and equipment",
    "purchase of property, plant and equipment (including capital work-in-progress)",
    # "PPE" abbreviated form (not spelled out) - confirmed real gap on Prime
    # Fresh Limited's Cash Flow Statement: "Purchase Of PPE, Including CWIP
    # And Capital Advances" - the plain "purchase of ppe" prefix still
    # matches even with the extra "including cwip..." qualifier trailing
    # it, since this is a substring search, not an exact-line match.
    "purchase of ppe",
]
# MANUAL-UPLOAD WORKFLOW ONLY (Capex Intensity, Sr No 40) - additional
# Purchase-of-PP&E caption variants, tried ONLY as a fallback when
# `is_manual_mode()` is True and NONE of `_CAPEX_PPE_PURCHASE_LABELS` above
# matched. Kept in a SEPARATE list (never merged into the shared list used
# unconditionally by both pipelines) so the automatic/live pipeline's
# capex_ppe_purchase extraction stays byte-for-byte unchanged - see the
# `is_manual_mode()` gate at this list's one call site. Each variant here
# was individually confirmed real on an actual manually-uploaded filing,
# not guessed:
#   - "payment for purchase of ..." (TCS): the shared list has "purchase
#     of ..." and "payment(s) for ..." as SEPARATE phrasings, but not this
#     specific combined wording.
#   - "addition to ..." (AARTIIND, singular "addition", not the shared
#     list's plural "additions") with "&" (not spelled-out "and"), plus
#     the "/Capital WIP" suffix AARTIIND's own caption carries - the label
#     match is a line-anchored PREFIX search (via `_CFS_LINE_START`, same
#     as the shared list), so the trailing "/Capital WIP" text doesn't
#     need to be part of the label itself, only listed here for clarity/
#     documentation of the exact real-world caption this was confirmed
#     against.
_CAPEX_PPE_PURCHASE_LABELS_MANUAL_ONLY = [
    "payment for purchase of property, plant and equipment",
    "payments for purchase of property, plant and equipment",
    "payment for purchase of property, plant & equipment",
    "payments for purchase of property, plant & equipment",
    "addition to property, plant and equipment",
    "addition to property, plant & equipment",
    # Comma-less variants of the same caption ("Property Plant &
    # Equipment", no comma after "Property") - confirmed real: AARTIIND's
    # CONSOLIDATED Cash Flow Statement (a separate page from its
    # standalone one, which does carry the comma) uses this exact
    # comma-less phrasing - "Addition to Property Plant & Equipment/
    # Capital WIP".
    "addition to property plant and equipment",
    "addition to property plant & equipment",
]
_CAPEX_INTANGIBLE_PURCHASE_LABELS = [
    "purchase of intangible assets", "purchase of intangibles",
    "expenditure on intangible assets under development", "purchase of other intangible assets",
    "additions to intangible assets", "payments for intangible assets",
]
_CAPEX_DISPOSAL_PROCEEDS_LABELS = [
    "proceeds from sale of property, plant and equipment", "proceeds from disposal of property, plant and equipment",
    "proceeds from sale of fixed assets", "sale of property, plant and equipment", "sale of fixed assets",
    "sale of capital assets",
    "proceeds from sale/disposal of property, plant and equipment", "sale of tangible fixed assets",
    # "Sale proceeds FROM property..." (word order reversed from the "sale
    # OF property..." variants above - confirmed on Gopal Snacks).
    "sale proceeds from property plant", "sale proceeds from property, plant",
]
# C.7 (Capital allocation decisions) - Dividend paid, Buyback spend, and
# M&A/acquisition outflow, all from the Cash Flow Statement's FINANCING
# (dividend/buyback) or INVESTING (acquisition) sections respectively. Each
# follows the exact same (current, prior) tuple / None-if-not-found
# convention as every other CFS item above - a company that genuinely did
# NOT pay a dividend/buyback/acquire anything in a given year is expected to
# simply have no matching line in that year's filing (so `None` from THIS
# extractor legitimately means "not present in the filing", not "definitely
# zero" - the caller (fetch_multi_year_cash_flow_items / C.7) is responsible
# for not silently converting that None into a fabricated 0).
_DIVIDEND_PAID_LABELS = [
    "dividend paid", "dividends paid", "dividend paid (including tax on dividend)",
    "dividends paid (including dividend distribution tax)", "payment of dividend",
    "payment of dividends", "final dividend paid", "equity dividend paid",
    "dividend paid on equity shares", "dividend paid to equity shareholders",
    "dividend distributed to equity shareholders",
]
_BUYBACK_SPEND_LABELS = [
    "buy back of equity shares", "buyback of equity shares", "buy-back of equity shares",
    "payment for buy-back of equity shares", "payment for buyback of equity shares",
    "amount paid for buyback of shares", "amount paid for buy-back of shares",
    "consideration paid for buyback of equity shares", "shares bought back",
    "expenditure on buyback of equity shares", "buy back of shares",
    "buy-back of shares", "buyback of shares",
    # Some filers fold the buyback-related transaction tax into the same
    # captioned line rather than a separate one.
    "buy back of equity shares (including tax on buy back)",
]
_ACQUISITION_OUTFLOW_LABELS = [
    "purchase consideration for acquisition", "consideration paid for acquisition",
    "acquisition of subsidiary", "acquisition of subsidiaries",
    "acquisition of subsidiary, net of cash acquired", "acquisition of business",
    "payment for acquisition of business", "payment for business acquisition",
    "investment in subsidiaries", "investment in subsidiary",
    "investment in joint ventures", "investment in joint venture",
    "investment in associates", "investment in associate",
    "acquisition of joint venture", "acquisition of associate",
    "purchase consideration paid for acquisition of subsidiary",
    "net cash paid on acquisition of subsidiary",
    "consideration paid on acquisition of business, net of cash acquired",
]


# Cash Flow Statement section headings - some filers (confirmed on HUL, TCS,
# Bharti Airtel) use the plural "Cash Flows from Operating/Investing/Financing
# Activities" instead of the singular "Cash Flow from ... Activities" every
# other checked filing uses. The literal-substring checks below used to only
# match the singular form, so the entire Cash Flow Statement extraction block
# silently never fired for plural-heading filers - every ratio depending on
# operating_cash_flow/capex/repayments came back "Could not find..." even
# though the figures were sitting right there on the page. `s?` makes both
# forms match.
# Section-heading captions routinely insert a "/(used in)" or "/(used)"
# qualifier between "from" and the activity type - very common Indian
# filing convention showing both possible directions in one caption (e.g.
# "Cash flow from/(used in) operating activities", "Cash flow from/(used)
# in financing activities" - confirmed BOTH phrasings on the SAME company's
# SAME filing, Gopal Snacks FY24/FY25). The plain "cash flows? from X
# activities" pattern doesn't match either variant AT ALL (the inserted
# text sits directly between "from" and the activity word), which
# previously made the ENTIRE Cash Flow Statement section boundary
# detection silently fail for any such filing - not just the headline
# Operating Cash Flow figure, but every other CFS-sourced field scoped by
# these same three patterns (Capex, Borrowings/Lease Repayment, Interest
# Paid, etc.). The permissive middle segment below accepts the qualifier
# in either position (inside or outside the parenthesis) or its absence
# entirely, while still requiring the literal "from" and activity-type
# anchor so it can never accidentally match somewhere unrelated.
_CFS_FROM_QUALIFIER = r"from(?:\s*/\s*\(?\s*used\s*(?:in)?\s*\)?)?\s*(?:in\s+)?\s*"
# Line-start anchor for Cash Flow Statement item labels - tolerates a
# stray bullet-point glyph PyMuPDF sometimes extracts as a raw control
# character (confirmed \x07 immediately before "Purchase of..." on Gopal
# Snacks' filing) between the line break and the label text, which the
# plain "only tabs/spaces" anchor doesn't skip over, silently failing the
# match entirely.
_CFS_LINE_START = r"(?:^|\n)[ \t]*[\x00-\x1f•●▪]?[ \t]*"
# Built via `_fuzzy_label_re` (not a plain "cash\s+flows?\s+..." literal) so
# these three section-boundary anchors tolerate the SAME stray-space
# artifact `_find_row_values`'s label matching already tolerates - confirmed
# real on TCS's FY2026 Consolidated Statement of Cash Flows, where the
# section heading itself extracts as "CASH FLOW S FROM IN V ESTIN G ACTIV
# ITIES" (stray spaces inside "FLOWS"/"INVESTING"/"ACTIVITIES", not just
# between words). Left unfixed, `_find_cash_flow_statement_items` never
# recognises ANY of the three section headings on such a filing, so Net
# Operating Cash Flow/Capex/Borrowings-Repayment/Lease-Repayment all resolve
# to None - indistinguishable from genuinely undisclosed data.
_CFS_OPERATING_PAT = _fuzzy_label_re("cash flow") + r"\s?s?\s?" + _CFS_FROM_QUALIFIER + _fuzzy_label_re("operating activities")
_CFS_INVESTING_PAT = _fuzzy_label_re("cash flow") + r"\s?s?\s?" + _CFS_FROM_QUALIFIER + _fuzzy_label_re("investing activities")
_CFS_FINANCING_PAT = _fuzzy_label_re("cash flow") + r"\s?s?\s?" + _CFS_FROM_QUALIFIER + _fuzzy_label_re("financing activities")


def _bounded_segment_module(text, start_after, stop_before):
    """Module-level twin of `_extract_from_pdf`'s nested `_bounded_segment`
    (same behaviour: slice `text` to the region between two section
    markers, or None if `start_after` isn't found) - needed here since
    `_find_cash_flow_statement_items` runs outside that closure."""
    m1 = re.search(start_after, text, re.I)
    if not m1:
        return None
    segment = text[m1.end():]
    m2 = re.search(stop_before, segment, re.I)
    if m2:
        segment = segment[:m2.start()]
    return segment


def _find_cash_flow_statement_items(doc, start_idx, want_section, max_pages=120):
    """Net Operating Cash Flow (Sr No 35 numerator), Capex components (Sr No
    36 denominator), and Repayment of Borrowings/Lease Liabilities (Sr No 34
    denominator components) - all live in the Cash Flow Statement, a
    genuinely new statement this reader hadn't parsed before (only ever used
    as an EXCLUSION marker elsewhere in this file, to skip false-positive
    BS/P&L row matches on that page). The Cash Flow Statement follows the
    Balance Sheet/P&L/Statement of Changes in Equity in the regulatory Ind
    AS filing order, so a short forward scan from the Balance Sheet page
    (much shorter than the 250-page scan used for Notes-only items like
    Share Capital) is enough.

    Net Operating Cash Flow keeps its NATURAL sign (a company can genuinely
    have negative operating cash flow - a real distress signal, never
    forced positive). Financing-activity cash OUTFLOWS (the two repayment
    lines) and Investing-activity Capex purchases are printed as negative/
    parenthesised figures (cash leaving the business) - returned here as a
    POSITIVE magnitude via `abs()`; disposal proceeds (a cash INFLOW) are
    also returned as a positive magnitude, ready to be netted OFF Capex by
    the caller (not summed in).

    Re-tracks the standalone/consolidated section transition the same way
    as every other page-scanning helper in this file. Returns a dict with
    `operating_cash_flow`, `capex_ppe_purchase`, `capex_intangible_purchase`,
    `capex_disposal_proceeds`, `borrowings_repayment`, and `lease_repayment`,
    each (current, prior) or None if that line was never found."""
    section = want_section
    operating_cash_flow = None
    capex_ppe_purchase = None
    capex_intangible_purchase = None
    capex_disposal_proceeds = None
    borrowings_repayment = None
    lease_repayment = None
    interest_paid = None
    lease_interest_paid = None
    dividend_paid = None
    buyback_spend = None
    acquisition_outflow = None
    cf_page_idx = None
    for i in range(start_idx, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        # Skip supplementary IFRS/US-GAAP reconciliation statements - some
        # ADR-listed filers (confirmed on Wipro's FY23 Integrated Annual
        # Report) include a SECOND, differently-shaped "Consolidated
        # Statement of Cash Flows" as an IFRS convenience-translation
        # reconciliation, laid out with 3 fiscal years' columns PLUS a 4th
        # "convenience translation into US dollar" column - a genuinely
        # different column count/meaning than the (current-year,
        # prior-year) 2-column layout every _NUM_RE-based `nums[0], nums[1]`
        # pick in this function assumes. Left unguarded, a label match on
        # this page silently mis-reads an OLDER year's column as if it were
        # the CURRENT fiscal year's figure (confirmed: Wipro FY23's real
        # Buyback line is genuinely absent from its own primary CFS - the
        # buyback was board-approved after FY23 year-end - but the scan fell
        # through to this IFRS table and wrongly grabbed FY21's ₹9,519.9 Cr
        # buyback figure as if it were FY23's own). Neither marker below is
        # ticker-specific - "convenience translation" and "under ifrs" are
        # standard captions any ADR-listed Indian filer's IFRS reconciliation
        # section uses.
        if "convenience translation" in tl or "under ifrs" in tl:
            continue
        # Section-tracking includes the Cash Flow Statement's OWN caption
        # (e.g. "Consolidated Statement of Cash Flows"/"Consolidated Cash
        # Flow Statement") in addition to the BS/P&L captions every other
        # page-scanning helper in this file checks - without this, a large
        # filing with many pages between the Balance Sheet and the actual
        # Cash Flow Statement (Statement of Changes in Equity, segment
        # disclosures, etc.) could have `section` drift to the wrong value
        # on an intervening page before ever reaching the real CFS page,
        # silently skipping it for the rest of the scan.
        if "consolidated balance sheet" in tl or "consolidated statement of profit" in tl \
                or "consolidated statement of cash flow" in tl or "consolidated cash flow statement" in tl:
            section = "consolidated"
        elif "standalone balance sheet" in tl \
                or (_has_pl_caption(tl) and "consolidated" not in tl) \
                or "standalone statement of cash flow" in tl or "standalone cash flow statement" in tl:
            section = "standalone"
        if section != want_section:
            continue

        factor = _unit_factor(t)

        # Boundary anchors use the FULL "cash flow from X activities" phrase
        # (the genuine section heading), never the bare "X activities" -
        # the Operating section's own adjustments routinely contain an
        # embedded, unrelated mention like "Exchange difference on items
        # grouped under financing/investing activities", which a bare
        # "investing activities" pattern matches FIRST, cutting the
        # Operating segment short before ever reaching its own "Net cash
        # generated from operating activities" subtotal (confirmed on L&T's
        # FY26 filing) - and, symmetrically, makes the Investing segment
        # START at that same false position instead of the real "B. Cash
        # flow from investing activities" heading a few lines later. The
        # fuller phrase never collides with that embedded mention.
        if operating_cash_flow is None and re.search(_CFS_OPERATING_PAT, tl, re.I):
            op_segment = _bounded_segment_module(t, _CFS_OPERATING_PAT, _CFS_INVESTING_PAT)
            if op_segment is None:
                op_segment = t[re.search(_CFS_OPERATING_PAT, tl, re.I).start():]
            for label in _OPERATING_CASH_FLOW_LABELS:
                m = re.search(_fuzzy_label_re(label), op_segment, re.I)
                if not m:
                    continue
                window = op_segment[m.end():m.end() + 200]
                # Some filers suffix the subtotal label with a cross-reference
                # marker like "- [A]" (confirmed on HUL's FY26 filing) before
                # the actual figures. _NUM_RE treats a bare "-" as a valid
                # placeholder token (parses to 0.0, not None), so left alone
                # it gets consumed as a bogus first "number" and silently
                # shifts the real current/prior-year values off by one.
                window = re.sub(r"^\s*-?\s*\[[A-Za-z]\]", "", window)
                nums = _row_nums(window)
                if len(nums) >= 2:
                    a, b = _parse_num(nums[0]), _parse_num(nums[1])
                    if a is not None and b is not None:
                        operating_cash_flow = (round(a * factor, 2), round(b * factor, 2))
                        cf_page_idx = i
                        break

        if re.search(_CFS_INVESTING_PAT, tl, re.I) and (
                capex_ppe_purchase is None or capex_intangible_purchase is None or capex_disposal_proceeds is None
                or acquisition_outflow is None):
            inv_segment = _bounded_segment_module(t, _CFS_INVESTING_PAT, _CFS_FINANCING_PAT)
            if inv_segment is None:
                inv_segment = t[re.search(_CFS_INVESTING_PAT, tl, re.I).start():]

            # All three loops below anchor the label match to the START of
            # its own line (`(?:^|\n)[ \t]*`, `re.M`), not a bare substring
            # search anywhere in the segment. Cash Flow Statement captions
            # are laid out one per line - without this anchor, a label like
            # "acquisition of property, plant and equipment" (a genuine
            # Purchase-of-PP&E variant) also matches as a literal substring
            # INSIDE a completely different, unrelated line like "Grant
            # received on acquisition of property, plant and equipment" (an
            # INFLOW, not a purchase) - confirmed on Tata Steel, where this
            # silently grabbed the grant's ₹533.30 Cr instead of the real
            # "Purchase of capital assets" line's ₹14,559.05 Cr. Same trap
            # hit disposal proceeds: "sale of property, plant and equipment"
            # matched inside "Advance received against sale of property,
            # plant and equipment" (a receivable, not actual disposal cash).
            if capex_ppe_purchase is None:
                for label in _CAPEX_PPE_PURCHASE_LABELS:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_ppe_purchase = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            # Un-gated from manual-upload-only: BSE's own live-hosted copy of
            # TCS's FY2026 Annual Report carries the IDENTICAL "Payment for
            # purchase of property, plant and equipment" Cash Flow Statement
            # line as the manually-uploaded copy (confirmed by direct
            # comparison of both PDFs' extracted text), so restricting this
            # fallback to manual-mode left the automatic/live pipeline
            # reporting a false N/A for Capex Intensity/FCF/FCF Margin on
            # the exact same real filing. Every label here is a genuine,
            # previously-confirmed real-world caption (TCS, AARTIIND), not
            # fabricated wording - safe to try unconditionally.
            if capex_ppe_purchase is None:
                for label in _CAPEX_PPE_PURCHASE_LABELS_MANUAL_ONLY:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_ppe_purchase = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if capex_intangible_purchase is None:
                for label in _CAPEX_INTANGIBLE_PURCHASE_LABELS:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_intangible_purchase = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if capex_disposal_proceeds is None:
                for label in _CAPEX_DISPOSAL_PROCEEDS_LABELS:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_disposal_proceeds = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            # C.7 M&A/acquisition outflow - same line-start anchor as the
            # three Capex loops above (a bare substring search would grab
            # "Investment in subsidiaries" or similar wording embedded
            # inside an unrelated Notes sentence rather than the actual CFS
            # line item).
            if acquisition_outflow is None:
                for label in _ACQUISITION_OUTFLOW_LABELS:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            acquisition_outflow = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

        if re.search(_CFS_FINANCING_PAT, tl, re.I) and (
                borrowings_repayment is None or lease_repayment is None
                or dividend_paid is None or buyback_spend is None):
            # Stop boundary requires "cash and cash equivalents" within a
            # short window after "net increase/decrease" - the bare "net
            # (?:increase|decrease)" pattern alone (no such requirement)
            # false-matched an INTERIM Financing-section subtotal line like
            # "Net increase / (decrease) in working capital demand loans"
            # (confirmed on Sun Pharma's FY24 consolidated filing), cutting
            # the segment short well before the real "Net increase/
            # (decrease) in cash and cash equivalents" line that actually
            # closes the Financing section - silently dropping every
            # Financing-section line item (Dividend paid, in Sun Pharma's
            # case) printed AFTER that interim subtotal but before the real
            # closing line.
            segment = _bounded_segment_module(
                t, _CFS_FINANCING_PAT,
                r"net (?:increase|decrease|increase/decrease)[^\n]{0,60}cash and cash equivalents")
            if segment is None:
                segment = t[re.search(_CFS_FINANCING_PAT, tl, re.I).start():]

            if borrowings_repayment is None:
                for label in _REPAYMENT_BORROWINGS_LABELS:
                    m = re.search(_fuzzy_label_re(label), segment, re.I)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            borrowings_repayment = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if lease_repayment is None:
                for label in _REPAYMENT_LEASE_LABELS:
                    m = re.search(_fuzzy_label_re(label), segment, re.I)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            lease_repayment = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            # DSCR (Sr No 34) Interest components - cash Interest Paid, same
            # section/window mechanics as the two Repayment components above.
            if interest_paid is None:
                for label in _INTEREST_PAID_LABELS:
                    m = re.search(_fuzzy_label_re(label), segment, re.I)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            interest_paid = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if lease_interest_paid is None:
                for label in _INTEREST_LEASE_LABELS:
                    m = re.search(_fuzzy_label_re(label), segment, re.I)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            lease_interest_paid = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            # C.7 Dividend paid / Buyback spend - both live in Financing
            # Activities, same window mechanics as Repayment/Interest above.
            # MUST be line-start anchored (`_CFS_LINE_START`, re.M) rather
            # than a bare substring search - confirmed false positive on
            # TCS's FY23 filing: a bare search for "buy-back of equity
            # shares" matches as a literal SUBSTRING inside "Expenses for
            # buy-back of equity shares" (a real but much smaller ₹49 Cr
            # transaction-cost line printed just above the actual ₹18,000 Cr
            # "Buy-back of equity shares" principal line), so the bare
            # search grabbed the ₹49 Cr expense figure as if it were the
            # entire buyback spend - the exact same substring-collision trap
            # the Capex loops above are already anchored against (see that
            # block's own comment re: Tata Steel's "Grant received on
            # acquisition of..." collision). Anchoring to line-start is what
            # fixes it: "Expenses for buy-back..." and "Tax on buy-back..."
            # don't start their own line with the label text, only the real
            # "Buy-back of equity shares" line does.
            if dividend_paid is None:
                for label in _DIVIDEND_PAID_LABELS:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), segment, re.I | re.M)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            dividend_paid = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if buyback_spend is None:
                for label in _BUYBACK_SPEND_LABELS:
                    m = re.search(_CFS_LINE_START + _fuzzy_label_re(label), segment, re.I | re.M)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = _row_nums(window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            buyback_spend = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

        # Early-exit once every REQUIRED item is found - capex_intangible_purchase
        # and capex_disposal_proceeds are genuinely optional (many companies have
        # no intangible purchases or disposals in a given year) and would never
        # gate the scan to completion if required here. Lease interest is also
        # genuinely optional (many filers fold it into a single undifferentiated
        # "Interest paid" line covering both borrowings and leases).
        if (operating_cash_flow is not None and capex_ppe_purchase is not None
                and borrowings_repayment is not None and lease_repayment is not None
                and interest_paid is not None):
            break

    return {"operating_cash_flow": operating_cash_flow,
            "capex_ppe_purchase": capex_ppe_purchase,
            "capex_intangible_purchase": capex_intangible_purchase,
            "capex_disposal_proceeds": capex_disposal_proceeds,
            "borrowings_repayment": borrowings_repayment, "lease_repayment": lease_repayment,
            "interest_paid": interest_paid, "lease_interest_paid": lease_interest_paid,
            "dividend_paid": dividend_paid, "buyback_spend": buyback_spend,
            "acquisition_outflow": acquisition_outflow,
            "cf_page": (cf_page_idx + 1) if cf_page_idx is not None else None}


_FINANCE_COST_LABELS = [
    "finance costs", "finance cost", "interest expense", "interest and finance charges",
    "interest on borrowings",
    # Same "/(Loss)"-suffix issue as `_PAT_GENERIC_LABELS`/`_PBT_LABELS` (Sr
    # No 16/19 fix) feeds Interest Coverage Ratio (Sr No 22 = EBIT ÷ Finance
    # Costs, where EBIT = PBT + Finance Costs): some filings net financing
    # income against cost and caption the row "Finance Costs/(Income)"
    # (or the reverse). `_find_pl_row` already normalises "profit/(loss)"
    # via `_strip_formula_refs`, but this is a DIFFERENT qualifier word
    # ("income", not "loss"), so it's listed explicitly here too rather than
    # relying on that substitution - a match must never be skipped just
    # because of this suffix.
    "finance costs/(income)", "finance cost/(income)",
]
_TAX_EXPENSE_LABELS = [
    # Total Tax Expense (Sr No 42's Effective Tax Rate component: current +
    # deferred tax, the P&L subtotal line - NOT the current-tax-only
    # sub-line). Feeds NOPAT = EBIT × (1 − Effective Tax Rate), where
    # Effective Tax Rate = Tax Expense ÷ Profit Before Tax.
    "total tax expense", "tax expense", "total tax expenses",
    # Same "/(Loss)"/"/(Credit)" suffix issue as PBT/Finance Costs - a
    # loss-making year can post a net tax CREDIT, captioned accordingly.
    "tax expense/(credit)", "total tax expense/(credit)",
]
# Total Debt (Sr No 20 numerator) - rebuilt as the a + b + c protocol:
#   a = Borrowings (Long-term + Short-term + Current Maturities of
#       Long-term Debt) - verified against the Borrowings Note breakup, not
#       taken from the Balance Sheet face value alone (see
#       `_find_borrowings_note_total`).
#   b = Lease Liabilities (Non-current + Current). Per the authoritative
#       Sr No 33 (Net Debt/EBITDA) spec, Basis 1 (default) INCLUDES these in
#       Total Debt - the post-Ind-AS-116 view, consistently applied to every
#       consumer of this field (D/E, Debt Ratio, Enterprise Value, Net
#       Debt/EBITDA). Basis 2 (opt-in `lease_basis="basis2"`) EXCLUDES them,
#       for callers that want the traditional pre-Ind-AS-116 definition.
#       Always surfaced informationally either way.
#   c = qualifying "Other Financial Liabilities" Notes items - only the
#       sub-items that pass the Three-Part Test in
#       `_other_financial_liabilities_qualifying` (financial-liability-note
#       item, interest-bearing/debt-like label, not a disguised operating
#       item) are added; unclassified sub-items are never guessed into debt.
# See `_compute_total_debt` for the single shared assembly used by every
# Sr-No-20-derived ratio (Debt-to-Equity, Debt Ratio, Enterprise Value).
_LT_BORROWINGS_LABELS = [
    "long-term borrowings", "long term borrowings", "non-current borrowings",
    "borrowings (non-current)",
]
_ST_BORROWINGS_LABELS = [
    "short-term borrowings", "short term borrowings", "current borrowings",
    "borrowings (current)",
]
_CURRENT_MATURITIES_LABELS = [
    "current maturities of long-term borrowings", "current maturities of long-term debt",
    "current maturity of long term borrowings", "current maturities of long term debt",
]
# Sub-item labels that identify a genuine Borrowings Note table (as opposed
# to some unrelated Note that happens to mention money) - used to verify the
# Balance Sheet face value isn't understated by a rigid single-line match
# (the DMart/Maruti-style false-zero this rebuild targets).
_BORROWINGS_NOTE_SUBITEM_TERMS = [
    "term loan", "secured", "unsecured", "debentures", "bonds", "commercial paper",
    "loans repayable on demand", "external commercial borrowings", "buyers' credit",
    "buyers credit", "suppliers' credit", "suppliers credit", "cash credit",
    "working capital loan", "loan from banks", "loan from financial institutions",
    "inter corporate deposit", "deposits from related part",
]
# Lease Liabilities - a SEPARATE Balance Sheet line from Borrowings (Ind AS
# 116). See the module-level comment above for the Basis 1/Basis 2 toggle.
_LEASE_LIABILITY_NC_LABELS = [
    "lease liabilities", "lease liability", "non-current lease liabilities",
]
_LEASE_LIABILITY_CUR_LABELS = [
    "lease liabilities", "lease liability", "current lease liabilities",
]
# Other Financial Liabilities - a catch-all BS line (Non-current/Current)
# that mixes genuinely debt-like items (interest accrued on borrowings,
# unpaid matured deposits, inter-corporate deposits) with purely operating
# ones (employee dues, capital-goods creditors, unclaimed dividends). The
# Three-Part Test (see `_other_financial_liabilities_qualifying`) decides
# per sub-item which side of that line an item falls on.
_OTHER_FIN_LIAB_LABELS = [
    "other financial liabilities",
]
_OFL_DEBT_LIKE_TERMS = [
    "interest accrued but not due on borrowings", "interest accrued and due on borrowings",
    "interest accrued on borrowings", "interest accrued on loans", "interest accrued on term loan",
    "unpaid matured deposits", "unpaid matured debentures", "fixed deposits from public",
    "inter corporate deposit", "inter-corporate deposit", "commercial paper",
]
_OFL_EXCLUDE_TERMS = [
    "employee", "capital goods", "statutory", "unclaimed dividend", "unpaid dividend",
    "security deposit received", "security deposits received", "retention money",
    "earnest money", "trade deposit", "book overdraft",
]
_REVENUE_LABELS = [
    "revenue from operations", "net sales", "total revenue from operations", "sales",
    "turnover", "gross revenue from operations", "net revenue from operations",
    "income from operations", "operating income", "revenue", "total income from operations",
]
_RECEIVABLES_LABELS = [
    "trade receivables", "trade receivable", "trade debtors", "sundry debtors", "accounts receivable",
    "debtors", "trade receivables (net of provision for doubtful debts)", "bills receivable",
]
_PAYABLES_LABELS = [
    "trade payables", "trade creditors", "sundry creditors", "accounts payable",
    "trade payables - msme", "trade payables - others", "bills payable",
]
_TOTAL_ASSETS_LABELS = [
    "total assets",
]
_TOTAL_EXPENSES_LABELS = [
    "total expenses",
]
_TOTAL_CURRENT_ASSETS_LABELS = [
    "total current assets",
]
_TOTAL_CURRENT_LIABILITIES_LABELS = [
    "total current liabilities",
]
# Net Fixed Assets (Sr No 30 denominator) - Property, Plant & Equipment net
# of accumulated depreciation. Deliberately EXCLUDES Capital Work-in-Progress
# (a separate BS line for assets not yet operational) and intangible
# assets/goodwill - per spec, only the tangible, in-service asset base.
_NET_FIXED_ASSETS_LABELS = [
    "property, plant and equipment", "property plant and equipment",
    "net block", "fixed assets (net)", "tangible assets (net)",
    "property, plant & equipment",
]
_CASH_LABELS = [
    "cash and cash equivalent",
    "cash and cash equivalents", "cash and bank balances", "balances with banks",
    "cash on hand", "cash & cash equivalents",
]
# "Other Bank Balances" (e.g. fixed deposits with banks, margin money, unpaid
# dividend accounts, escrow balances) is a SEPARATE Balance Sheet line from
# Cash and Cash Equivalents. Per spec, only its UNRESTRICTED portion (e.g.
# freely-available bank deposits) belongs in the Cash Ratio numerator - the
# restricted portion (unpaid dividend/margin money/escrow) must be excluded.
# The split is rebuilt as a deterministic Base -> Net-off -> Optional-Add
# pipeline (see `_other_bank_balances_unrestricted`) instead of leaving the
# restricted/unrestricted call to AI judgement: Base is the line's own total;
# Net-off subtracts any sub-item lines printed directly under it that match
# an explicit restricted-label test; Optional-Add folds the remainder into
# the Cash Ratio numerator ONLY when that Net-off test actually matched
# something (i.e. a real breakup was found to classify) - if no sub-item
# breakup is printed at all, the split can't be determined and the figure
# stays informational-only rather than guessed.
_OTHER_BANK_BALANCES_LABELS = [
    "other bank balances", "other bank balance", "bank balances other than cash and cash equivalents",
]
# Deterministic "exclude" test for Other Bank Balances sub-items - reuses
# `_RESTRICTED_CASH_TERMS` (unpaid/unclaimed dividend, earmarked, margin
# money, escrow, restricted) plus lien/pledge/security-deposit/guarantee
# terms specific to bank-deposit notes, which don't otherwise appear against
# plain Cash and Cash Equivalents rows.
_OBB_RESTRICTED_SUBITEM_TERMS = [
    "unpaid dividend", "unclaimed dividend", "earmarked", "margin money",
    "escrow", "restricted", "pledged", "lien", "security deposit",
    "bank guarantee",
]
# Contribution Margin (Sr No 44) - volume-linked sub-items recognised inside
# the "Other Expenses" Note breakup (Schedule III doesn't itself classify
# fixed vs. variable, but individual Note captions are explicit enough to
# classify deterministically: freight/carriage/transportation, power & fuel
# consumed in production, packing materials, and sales-volume-linked
# commission/discount/royalty are always genuinely variable regardless of
# business model - unlike rent, legal/professional fees, insurance, or
# admin costs, which stay fixed even though they also sit inside "Other
# Expenses"). Only sub-items whose caption matches one of these terms are
# ever added to Variable Costs - nothing in "Other Expenses" is assumed
# variable by default.
_VARIABLE_OPEX_NOTE_TERMS = [
    "freight", "carriage outward", "carriage inward", "carriage and freight",
    "forwarding", "transportation", "transport charges", "loading and unloading",
    "loading & unloading", "handling charges", "power and fuel", "power & fuel",
    "fuel and power", "fuel & power", "power, fuel", "utility charges",
    "utility expenses", "packing material",
    "packing expenses", "packaging material", "packaging expenses",
    "sales commission", "commission on sales", "selling commission", "brokerage",
    "commission expenses", "commission expense",
    "discount on sales", "cash discount", "trade discount", "royalty on sales",
    "distribution expenses", "outward freight", "freight outward",
    "freight and forwarding", "freight & forwarding", "export freight",
    "clearing and forwarding", "clearing & forwarding",
    "stores and spares", "consumption of stores",
]
# Captions that CAN contain one of the terms above as a substring but are
# fixed, not volume-linked (e.g. "Freight" inside "Rent, Rates and Freight
# Insurance" headings never occurs in practice, but "Power and Fuel -
# Administrative Office" style captions do) - checked before accepting a
# match so an office/admin qualifier doesn't get misclassified as variable.
_VARIABLE_OPEX_NOTE_EXCLUDE_QUALIFIERS = [
    "office", "administrative", "corporate", "guest house", "township",
    "director", "directors",
]


def _find_variable_opex_note(doc, start_idx, max_pages=200, caption="other expenses"):
    """Contribution Margin (Sr No 44)'s Variable Cost component beyond raw
    materials: scans forward from the P&L page for a Notes-to-Accounts
    breakup NOTE whose heading caption is `caption` (the sub-item breakup
    printed in Notes to Accounts, not a single face value on the P&L) and
    sums only the sub-items whose caption matches `_VARIABLE_OPEX_NOTE_TERMS`
    (freight/power & fuel/packing/sales commission/...), each independently
    checked against `_VARIABLE_OPEX_NOTE_EXCLUDE_QUALIFIERS` to reject
    admin/office-qualified variants of the same word. Rent, legal/
    professional fees, insurance, donations, CSR, audit fees, and every
    other sub-item NOT matching a volume-linked term is left out - never
    assumed variable.

    `caption` defaults to "other expenses" (the note this was originally
    built for) but is genuinely parameterised - e.g. `caption="direct
    expenses"` scans a filing's separate "Direct Expenses" Note (some
    trading/services filers print operational costs like loading/unloading/
    transportation/packing there instead of folding them into "Other
    Expenses" - confirmed real on Prime Fresh Limited's FY26 AR). Same
    classification discipline either way: only caption-matched sub-items
    are treated as variable, never the Note's total on the assumption that
    a whole "Direct Expenses"/"Other Expenses" caption is inherently
    variable just because of its heading.

    Returns None if no such Note breakup is found at all (so the caller
    falls back to materials/stock-in-trade only, same as before - no
    guessing). If the Note IS found, returns a dict with `items` (label ->
    (cur, prior)) and `total_cur`/`total_prior` - `items` may be `{}` (a
    real, determined zero: the Note was found but none of its sub-items are
    volume-linked) rather than None."""
    caption_fuzzy = r"\s+".join(re.escape(w) for w in caption.split())
    # The infix between the note number and the target caption tolerates a
    # SHORT qualifying prefix word/phrase (e.g. "Note No.: 32 - TRADING &
    # DIRECT EXPENSES:" - confirmed real on Prime Fresh Limited's FY26 AR,
    # whose Direct Expenses Note is captioned "Trading & Direct Expenses",
    # not a bare "Direct Expenses") rather than requiring the caption
    # immediately after the note number - `[^\n]{0,30}` bounds this to a
    # handful of words so it can't accidentally skip past an unrelated
    # Note entirely and match some other caption many words later.
    infix = r"[^\n]{0,30}?"
    heading_note_re = re.compile(rf"note\s*(?:no\.?)?[:\-.\s]*\d+{infix}{caption_fuzzy}")
    heading_bare_re = re.compile(rf"\n\s*\d{{1,3}}[.\t ]{{1,3}}{infix}{caption_fuzzy}\b")
    for i in range(start_idx, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        # Require an actual Note heading for Other Expenses, not just an
        # incidental "other expenses" mention (e.g. a cross-reference like
        # "Refer note 35 Other Expenses" on an unrelated page, a Related
        # Party Transactions row "Purchases of services (other expenses)",
        # or a Total Expenses breakdown listing "Other expenses" as a P&L
        # line) - those would otherwise match here first and return an
        # empty `items` dict, ending the scan before the real Note page
        # (often several pages later) is ever reached. Three heading shapes
        # are seen in practice: "NOTE 35 OTHER EXPENSES" (word "note"
        # spelled out, digits immediately after), "Note No.: 36 - OTHER
        # EXPENSES:" (the word "No"/"No." inserted between "note" and the
        # digits, with a colon/dash before the caption - confirmed real on
        # Prime Fresh Limited's FY26 AR, whose Note 36 uses exactly this
        # shape; the original regex required digits immediately after
        # "note", so it never matched this filing's Note heading at all,
        # silently returning None for every company using this common
        # "Note No.: NN" style, not just this one), and a bare numbered
        # heading "26  Other expenses" / "26\tOther expenses" (no "note"
        # word at all, tab/space-separated) - all three required to start a
        # fresh line, never mid-sentence.
        if not heading_note_re.search(tl) and not heading_bare_re.search(tl):
            continue
        # Require this to look like a genuine Notes-to-Accounts breakup
        # page (several distinct line-items with figures), not just an
        # incidental "Other Expenses" mention in the P&L face or MD&A.
        if tl.count("\n") < 8:
            continue
        if "cash flow" in tl[:200]:
            continue
        factor = _unit_factor(t)
        lines = t.split("\n")
        items = {}
        total_cur = total_prior = 0.0
        for idx, line in enumerate(lines):
            ll = line.lower()
            matched_term = next((term for term in _VARIABLE_OPEX_NOTE_TERMS if term in ll), None)
            if matched_term is None:
                continue
            if any(q in ll for q in _VARIABLE_OPEX_NOTE_EXCLUDE_QUALIFIERS):
                continue
            # Value pair is usually on the SAME line as the label, but many
            # filings print the "Other Expenses" Note as label-only lines
            # followed by a separate "Notes" column line (a bare "-" when
            # the row has no footnote reference) and THEN the current-year/
            # prior-year value lines (a column-block table layout) - look
            # ahead a few lines for the numeric tokens if the label's own
            # line has none.
            #
            # BUG FIXED (Contribution Margin, Sr No 44, confirmed on
            # Anupam Rasayan's FY25 Note 30 "Other Expenses"): the lookahead
            # used to stop as soon as it collected 2 tokens, so a leading
            # bare "-" Notes-column placeholder (present on most rows here,
            # e.g. "Consumption - Packing Materials" / "-" / "68.87" /
            # "96.30") was itself counted as the "current year" value,
            # shifting the real current-year figure into the "prior year"
            # slot and losing the real prior-year figure entirely -
            # collapsing genuine values like (68.87, 96.30) down to
            # (0.0, 6.89)-scale noise. Collect up to 3 tokens instead of 2:
            # a genuine value pair is always the LAST two collected - a
            # leading Notes-column placeholder (if present at all) is
            # always the token(s) before them, never after.
            # `_NUM_RE` alone requires a comma or 2-decimal-place figure (to
            # reject bare Note-reference numbers sitting next to a label on
            # the SAME line - see its module comment) - that's too strict
            # for a lookahead line that is ONLY ever a value in this table
            # shape, so a lookahead line gets the more permissive bare-
            # integer pattern too (mirrors `_find_row_values_spatial`'s
            # documented `permissive=True` case for the same reason).
            nums = re.findall(_NUM_RE, line)
            # A same-line match of fewer than 2 tokens is ambiguous (e.g. a
            # stray " - " inside the label text itself, like "Consumption -
            # Packing Materials", which is punctuation, not a value) - only
            # trust a same-line match when it already found the full pair;
            # otherwise discard it and read the value pair from the
            # lookahead lines instead, exactly as if the label line had no
            # numbers at all.
            if len(nums) < 2:
                nums = []
                for lookahead in lines[idx + 1:idx + 6]:
                    stripped = lookahead.strip()
                    if stripped and not re.fullmatch(r"-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|-", stripped):
                        break  # hit the next label line before finding enough numbers
                    if stripped:
                        nums.append(stripped)
                    if len(nums) >= 3:
                        break
            if len(nums) < 2:
                continue
            # The value pair is always the LAST two tokens collected - drop
            # any leading Notes-column placeholder(s) (bare "-") first.
            cur_tok, prior_tok = nums[-2], nums[-1]
            a, b = _parse_num(cur_tok), _parse_num(prior_tok)
            if a is None or b is None:
                continue
            label = line.strip()[:60]
            if label in items:
                continue  # keep the first (closest-to-heading) match for a repeated caption
            items[label] = (round(a * factor, 2), round(b * factor, 2))
            total_cur += a * factor
            total_prior += b * factor
        # Only treat this as a genuine Note page (vs. a false-positive
        # heading match) once we've also seen a handful of numeric tokens
        # on the page - guards against a page that has the heading text but
        # no actual table (e.g. a table of contents entry). Figures may be
        # printed one-per-line (see the lookahead above), so this counts
        # numeric TOKENS across the whole page rather than same-line pairs.
        if len(re.findall(_NUM_RE, t)) < 6:
            continue
        return {"items": items, "total_cur": round(total_cur, 2), "total_prior": round(total_prior, 2)}
    return None

# Matches a genuine tabulated amount while excluding bare note-reference
# numbers - both the plain kind (e.g. the "27" next to "Cost of materials
# consumed" pointing at note 27) AND the decimal-dotted kind some filings use
# (e.g. Infosys numbers its notes "2.1", "2.8", "2.17" - which, before a
# guard was added, looked exactly like a small decimal AMOUNT and got
# mistaken for one, e.g. reading Trade Receivables as "2.8" instead of the
# real 30,337).
#
# The comma-grouped branch must handle BOTH numbering conventions filings
# use - companies reporting in ₹ Crore (Tata Steel, Infosys, ...) use INDIAN
# grouping (2-digit groups after the first: "1,48,819" = 148819), while
# companies reporting in ₹ Million (Sun Pharma, ...) use WESTERN 3-digit
# grouping ("114,929.3" = 114929.3). Assuming only one convention silently
# truncates every large figure under the other: an Indian-only regex reads
# "114,929.3" (Western) as "14,929.3" (dropping the first digit); a
# Western-only regex reads "2,32,139.94" (Indian) as "32,139.94" (dropping
# the whole first group). Trying Western first is safe: it only matches when
# EVERY group is exactly 3 digits, so on a genuinely Indian-grouped number it
# fails outright (a 2-digit middle group breaks the `+` requirement) and
# falls through to the Indian branch, rather than matching a wrong substring.
# The no-comma-decimal branch needs a 2+ digit integer part, not 3+: real
# small amounts under ₹1000 (e.g. Asian Paints' "Revenue from Sale of
# Services" at 100.12, or "Other Operating Revenue" at 67.17) commonly have
# only 2 digits before the decimal, and excluding those (as an earlier 3+
# digit version did) silently dropped legitimate rows from a sum. Infosys's
# note numbers ("2.1", "2.8", "2.17", ...) all have a SINGLE-digit integer
# part, so a 2+ digit floor excludes those - but Maruti numbers its notes
# "24.1", "24.2" (2-digit.1-digit), which a 1-2 digit DECIMAL part would still
# match. Real amounts always carry exactly 2 decimal digits (paise
# precision) when not comma-grouped; note references have 1. Requiring
# exactly 2 decimal digits here (not 1-2) closes that gap without losing any
# real value - a genuine 1-decimal amount always has a comma anyway once
# it's large enough to matter (e.g. Sun Pharma's "64,491.0").
_NUM_RE = (r"\([\d,]+(?:\.\d{1,2})?\)"                  # parenthesised (negative)
           r"|-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"        # Western comma grouping
           r"|-?\d{1,3}(?:,\d{2})*,\d{3}(?:\.\d{1,2})?"  # Indian comma grouping
           r"|-?\d{2,}\.\d{2}"                           # plain decimal, no comma, 2+ digit integer, exactly 2 decimals
           r"|(?<=\s)-(?=\s)")                           # lone dash placeholder ("-")
# Indian grouping's leading group was `\d{1,2}` (2-digit cap) until this fix -
# WRONG for any genuinely Indian-formatted number >= 100 crore, whose own
# leading group is 3 digits ("361,80,87,518" = 361.81 crore). At the old
# 2-digit cap, the regex couldn't match starting from "361" at all (no comma
# follows just "36"), so it silently matched one character later instead -
# "61,80,87,518" - reading 618,087,518 instead of the real 3,618,087,518
# (off by exactly 3,000,000,000). Confirmed real on TCS's Equity Share
# Capital note ("Issued, Subscribed and Fully paid up 361,80,87,518 equity
# shares"), corrupting Book Value per Share (Sr No 46) - a general regex
# bug, not unique to this one company's share count; ANY Indian-formatted
# figure of 100+ crore/lakh/whatever-the-page's-unit hit the identical
# truncation. `\d{1,3}` matches the Western alternative's own leading-group
# cap (already correctly 1-3 digits) and is safe for the same reason that
# alternative already is: Western numbers are consumed by the EARLIER
# Western alternative before the parser ever reaches this one.


def _unit_factor(text):
    """Detect the reporting unit declared on a statement page (e.g.
    '(In ` Million)', '(₹ in Lakh)', '(` in Crores)') and return the
    multiplier to convert its raw figures into ₹ Crore. Per spec: 'Normalise
    numerator and denominator to the same unit (₹ Crore) before dividing;
    never divide a Crore figure by a Lakh/Million figure.' Companies that
    report in ₹ Million (e.g. Sun Pharma, Maruti) or ₹ Lakh would otherwise
    have every extracted figure mislabelled as Crore while being 10x/100x too
    large - the RATIO itself is still correct (same unit top and bottom), but
    the displayed absolute values ('How we calculated this') would be wrong.
    Searches the WHOLE page, not just the top: the unit note is sometimes a
    signature-block footnote (seen on Maruti's Balance Sheet: '(in ` million,
    unless otherwise stated)' ~3000 characters in), not a page-top header.
    Defaults to 1.0 (already Crore) when no unit is stated."""
    # `\bmillion\b` requires the word to end exactly there - but the plural
    # "millions" (e.g. Bharti Airtel's "(All amounts are in millions of
    # Indian Rupee)") has no word-boundary between the "n" and the "s", so
    # the un-pluralised pattern silently never matched it at all, leaving
    # the factor at the default 1.0 - every figure on that filing came out
    # 10x too large (confirmed on Bharti Airtel: Net Cash from Operating
    # Activities read as ₹1,222,296 Cr instead of the real ₹1,22,229.60 Cr).
    # `million` (without the closing `\b`) matches "millions" too, same
    # asymmetric-boundary trick "lakh" below already relies on.
    # "(` in '000s)" (ICICI) / "(₹ in thousands)" (Kotak, glyph extracted as 'H'): a statement header naming the currency
    # glyph directly before "in thousands" - tight on purpose (a bare "thousand" in prose must not rescale a page).
    if re.search(r"[`₹H]\s*in\s*(?:[‘'’]\s*000s?|thousands?)\b", text):
        return 1e-4
    if re.search(r"\bmillion", text, re.I):
        return 0.1
    if re.search(r"\blakh", text, re.I):
        return 0.01
    return 1.0


def _scale(pair, factor):
    """Apply a unit-conversion factor to a (current, prior) tuple, or pass
    through None/untouched when factor is already 1.0."""
    if pair is None or factor == 1.0:
        return pair
    return (round(pair[0] * factor, 2), round(pair[1] * factor, 2) if pair[1] is not None else None)


def _parse_num(tok):
    """'48,018.48' -> 48018.48 ; '(1,329.69)' -> -1329.69 ; '-' -> 0.0"""
    tok = tok.strip()
    if tok == "-":
        return 0.0
    neg = tok.startswith("(") and tok.endswith(")")
    tok = tok.strip("()").replace(",", "")
    try:
        v = float(tok)
        return -v if neg else v
    except Exception:
        return None


_PERMISSIVE_NUM_RE = r"\(?-?[\d,]+(?:\.\d{1,2})?\)?|(?<=\s)-(?=\s)"


_WIDE_TOKEN_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


def _row_nums(window):
    """`re.findall(_NUM_RE, window)` for the figures that follow a row label, corrected for a single-digit-crore amount
    (see `_single_digit_row_values`): returns the repaired (current, prior) pair as tokens when the row contains one."""
    sd = _single_digit_row_values(window)
    if sd is not None:
        return [repr(sd[0]), repr(sd[1])] + re.findall(_NUM_RE, window)[2:]
    return re.findall(_NUM_RE, window)


def _single_digit_row_values(window):
    """Row values when `_NUM_RE` cannot see one of the row's own figures.

    `_NUM_RE` deliberately ignores (a) a 1-digit-integer decimal (Infosys prints note numbers like "2.17") and (b) a plain
    integer with no comma/decimal. So a row "Depreciation and amortisation expense  25  693  584" (a filer that reports whole
    crore, e.g. Titan) lost its 693/584 and silently returned the NEXT row's "5,150 4,496" - wrong data, not missing data;
    "Cash and Cash Equivalent  10  9.22  55.31" did the same. This reads the row as ONE cluster of figures (stopping at the next
    label), drops a leading note-reference column when three or more figures follow, and returns (current, prior) ONLY when
    one of those two figures is something `_NUM_RE` would have skipped; otherwise None and the caller keeps its result."""
    # a label's own parenthetical - "Total assets (1+2)", "Revenue (a)", "Other income (Note 5)" - is not a figure
    for _ in range(2):
        window = re.sub(r"^[\s:]*\((?![\d,.\s]+\))[^)\n]{0,24}\)", "", window)
    toks, last_end = [], None
    for m in _WIDE_TOKEN_RE.finditer(window):
        gap = window[last_end:m.start()] if last_end is not None else ""
        if last_end is not None and len(re.findall(r"[A-Za-z]", gap)) >= 3:
            break
        toks.append(m.group())
        last_end = m.end()
        if len(toks) == 4:
            break
    if len(toks) < 2:
        return None

    def note_like(t):
        return bool(re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?", t))

    def strict(t):
        return re.fullmatch(_NUM_RE, t) is not None
    vals = toks
    if (len(toks) == 4 and note_like(toks[0]) and re.fullmatch(r"\d{2,4}", toks[1]) and strict(toks[2]) and strict(toks[3])):
        return None             # "Notes | Page No. | current | prior" layout (Maruti "24.1 432 873,183 789,153"): both leading cells are references
    if len(vals) >= 3 and re.fullmatch(r"\d{1,2}", vals[0]):
        vals = vals[1:]                                    # a bare 1-2 digit integer ahead of two more figures = a Note number
    elif len(vals) >= 3 and note_like(vals[0]) and not note_like(vals[1]):
        vals = vals[1:]
    if len(vals) < 2 or (strict(vals[0]) and strict(vals[1])):
        return None                                        # nothing `_NUM_RE` would have missed: existing behaviour stands
    a, b = _parse_num(vals[0]), _parse_num(vals[1])
    return (a, b) if a is not None and b is not None else None


def _find_row_values(text, canonical_names, after=None, reject_after=None, permissive=False, words=None):
    """Find a row by any of its canonical label variants and return
    (current_year_value, prior_year_value) - the two trailing numbers on that
    logical line - or None. Case-insensitive, tries each synonym in order.

    `after`: an optional regex; if given, the search starts AFTER the first
    match of it. Used for Trade Receivables, which the Balance Sheet often
    lists twice (a small long-term portion under Non-Current Assets, then the
    real circulating balance under Current Assets) - without this, the first
    (wrong, non-current) occurrence would win.

    `reject_after`: an optional regex; if the text immediately following a
    label match starts with it, that match is skipped and the NEXT
    occurrence of the same label (or the next label) is tried instead. Used
    for "total equity", which is a literal substring of "TOTAL EQUITY AND
    LIABILITIES" (the whole Balance Sheet grand total, a completely
    different and much bigger figure) - without this, a filer whose actual
    equity subtotal is phrased some other way (e.g. "Total - Equity (A)",
    confirmed on HUL) silently falls through to that wrong total instead of
    correctly returning None.

    `permissive`: use a comma-optional number pattern instead of the strict
    `_NUM_RE`. `_NUM_RE` deliberately requires a comma or 2-decimal suffix
    (to avoid grabbing stray note-reference numbers on big-number rows like
    Revenue/Trade Payables), but that means a genuinely small face-value row
    like Equity Share Capital (e.g. "235", no comma) is invisible to it -
    the window scan then skips straight past it to the NEXT comma'd number,
    silently grabbing a completely different, unrelated row instead
    (confirmed on HUL: "Equity share capital ... 235 235" was skipped in
    favour of the following "Other equity ... 48,504 49,167" line). Only use
    this for labels where the value is known to often be a small number.

    `words`: optional page word-boxes from `_page_words`, used ONLY as a
    fallback when the near-window scan above finds nothing at all - see
    `_find_row_values_spatial`."""
    num_pattern = _PERMISSIVE_NUM_RE if permissive else _NUM_RE
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    for name in canonical_names:
        name_re = _fuzzy_label_re(name)
        matches = re.finditer(name_re, search_text, re.I) if reject_after else [re.search(name_re, search_text, re.I)]
        for m in matches:
            if not m:
                continue
            if reject_after and re.match(reject_after, search_text[m.end():m.end() + 30], re.I):
                continue
            window = search_text[m.end():m.end() + 250]
            nums = []
            for nm in re.finditer(num_pattern, window):
                tok = nm.group()
                # A lone "-" is normally a genuine nil-value table cell, but
                # on a page where labels and values are printed as two
                # separate blocks (see `_find_row_values_spatial`), the same
                # pattern also matches a plain-text "- " BULLET before an
                # unrelated label a few rows down (e.g. Gopal Snacks FY25:
                # "Employee benefits expense\n...\n - Current tax\n -
                # Deferred tax" - those two dashes are list markers for
                # "Current tax"/"Deferred tax", not Employee Benefit
                # Expense's own figures) - confirmed this silently returned
                # (0.0, 0.0) instead of falling through to the spatial
                # fallback below, which has the real numbers. A genuine nil
                # cell is never immediately followed by a new label word.
                if tok == "-" and window[nm.end():].lstrip(" \t")[:1].isalpha():
                    continue
                nums.append(tok)
            sd = _single_digit_row_values(window)
            if sd is not None:
                return sd
            if len(nums) >= 2:
                a, b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None and b is not None:
                    return a, b
    if words:
        result = _find_row_values_spatial(words, canonical_names, permissive=permissive, after=after)
        if result is not None:
            return result
    return None


def _page_words(page):
    """Ligature-normalised `page.get_text("words")` - (x0, y0, x1, y1, text)
    boxes for every word on the page. Used only by `_find_row_values_spatial`
    as a fallback when a statement's rows don't sit in the same linear
    reading order plain text extraction produces (see that function)."""
    return [(w[0], w[1], w[2], w[3], w[4].translate(_LIGATURE_MAP)) for w in page.get_text("words")]


def _side_by_side_split_x(words):
    """When the Balance Sheet and Statement of Profit and Loss are printed
    as two tables SIDE BY SIDE on one landscape page (Gopal Snacks FY25),
    `_find_row_values_spatial` must only look at whichever half its target
    statement is on - otherwise a generic BS synonym (e.g. "stock" for
    Inventories) can match a substring inside a completely unrelated P&L row
    on the other half of the same page (e.g. "Purchase of STOCK-in-trade"),
    silently returning that row's figures instead.

    Finds the vertical gap between the two tables by looking for the widest
    horizontal gap between consecutive distinct word x-positions (a real
    page-wide gutter between two tables is far wider than the gap between
    any two adjacent columns WITHIN one table - confirmed on Gopal Snacks:
    123pt between the tables vs a next-widest of 22pt within one). Returns
    the x to split on, or None if there's no gap wide enough to be a genuine
    table gutter (the normal single-statement-per-page case - nothing to
    split)."""
    MIN_GUTTER = 60  # pt; comfortably above any real within-table column gap
    xs = sorted(set(round(w[0]) for w in words))
    if len(xs) < 2:
        return None
    widest_gap, split_x = 0, None
    for prev, cur in zip(xs, xs[1:]):
        if cur - prev > widest_gap:
            widest_gap, split_x = cur - prev, (prev + cur) / 2
    return split_x if widest_gap >= MIN_GUTTER else None


def _bs_only_words(words):
    """Restrict `words` to the Balance Sheet's own half of the page - see
    `_side_by_side_split_x`. The Balance Sheet is always the LEFT-hand table
    (its own caption always precedes the P&L's in the filing). Returns
    `words` unchanged when there's no side-by-side split to make."""
    split_x = _side_by_side_split_x(words)
    return [w for w in words if w[0] < split_x] if split_x is not None else words


def _pl_only_words(words):
    """P&L-side counterpart to `_bs_only_words` - see that function and
    `_side_by_side_split_x`."""
    split_x = _side_by_side_split_x(words)
    return [w for w in words if w[0] >= split_x] if split_x is not None else words


def _cluster_lines(words):
    """Group word-boxes into visual table rows by y-midpoint (a small
    tolerance absorbs sub-pixel jitter within one printed line), each row
    returned sorted by x - i.e. left-to-right READING order within that row,
    regardless of the order PyMuPDF originally emitted the words in."""
    Y_TOL = 3.0
    rows = []
    cur, cur_y = [], None
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        ymid = (w[1] + w[3]) / 2
        if cur_y is None or abs(ymid - cur_y) <= Y_TOL:
            cur.append(w)
            cur_y = cur_y if cur_y is not None else ymid
        else:
            rows.append(sorted(cur, key=lambda w: w[0]))
            cur, cur_y = [w], ymid
    if cur:
        rows.append(sorted(cur, key=lambda w: w[0]))
    return rows


# Number-token regexes for `_find_row_values_spatial` - same shape as
# `_NUM_RE`/`_PERMISSIVE_NUM_RE` but without the whitespace-lookaround dash
# alternative (meaningless against a single already-tokenised word); a bare
# "-" placeholder is instead checked for directly.
_NUM_TOKEN_RE = re.compile(
    r"\A(?:\([\d,]+(?:\.\d{1,2})?\)|-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|-?\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d{1,2})?|-?\d{2,}\.\d{2})\Z")
_PERMISSIVE_NUM_TOKEN_RE = re.compile(r"\A\(?-?[\d,]+(?:\.\d{1,2})?\)?\Z")


def _merge_loss_qualifier_tokens(texts, row):
    """Merge a 'Profit/(loss)'-style loss-qualifier into the preceding word
    so spatial label matching sees the same normalised text the
    character-based path gets via `_strip_formula_refs` - some filers (e.g.
    Gopal Snacks) caption a P&L subtotal as 'Profit/ (loss) before tax',
    which PyMuPDF tokenises as SEPARATE word-boxes ('Profit/', '(loss)',
    'before', 'tax'); a plain substring search for 'profit before tax'
    never matches that. Handles both the split-token form ('Profit/' +
    '(loss)') and a single merged token ('Profit/(loss)'). Keeps `texts`
    and `row` in lockstep (same shrunk length) so the caller's word-index
    math stays valid."""
    out_t, out_r = [], []
    i = 0
    while i < len(texts):
        t = texts[i]
        merged_single = re.sub(r"/\s*\(\s*loss\s*\)", "", t, flags=re.I)
        if merged_single != t:
            out_t.append(merged_single)
            out_r.append(row[i])
            i += 1
            continue
        stripped = t.rstrip("/")
        if stripped != t and i + 1 < len(texts) and re.fullmatch(r"\(\s*loss\s*\)", texts[i + 1], re.I):
            out_t.append(stripped)
            out_r.append(row[i])
            i += 2
            continue
        out_t.append(t)
        out_r.append(row[i])
        i += 1
    return out_t, out_r


def _find_row_values_spatial(words, canonical_names, permissive=False, after=None, before=None, reject_context=None):
    """Spatial counterpart to `_find_row_values`'s near-window text scan:
    locates a row by its label and reads the two numbers immediately to its
    RIGHT on the same visual table row (grouped by y-coordinate via
    `_cluster_lines`), instead of by how close they sit in PyMuPDF's linear
    text-extraction order.

    Exists for filings where a statement's PRINTED layout puts a row's
    numbers right next to its label, but plain text extraction reads them
    far apart - confirmed on Gopal Snacks Ltd's FY25 Annual Report, where
    the Balance Sheet and Statement of Profit and Loss are laid out as two
    tables SIDE BY SIDE on one landscape page (extraction interleaves BOTH
    tables' rows by absolute y-position, so a P&L row's own note-number and
    values can land 1,000+ characters after its label in linear text, with
    an unrelated Balance Sheet row's cells in between). Reading by table ROW
    instead sidesteps that entirely: it doesn't matter what page-extraction
    order put nearby, only what's physically printed on the row's own line.

    `before`: optional regex, upper y-bound counterpart to `after` - needed
    for a generically-labeled row (e.g. plain "Borrowings") that repeats
    under BOTH "Non-current Liabilities" and "Current Liabilities" sections
    with identical label text; without an upper bound, a company with NO
    non-current entry for that label would have its `after="Non-current
    Liabilities"` search run straight past the empty section and wrongly
    grab the Current section's row instead (same mislabelling risk
    `_find_bs_row_bounded`'s text-based version already guards against).

    `reject_context`: optional list of lowercase terms; if any appears in the
    row's own joined text, this occurrence is disqualified and the next
    occurrence/name is tried instead - mirrors `_find_cash_row`'s
    `_RESTRICTED_CASH_TERMS` check (e.g. "unpaid dividend accounts" printed
    as a face-level Cash sub-line must never be counted as unrestricted
    cash, even though it also says "cash"/"bank balances")."""
    token_re = _PERMISSIVE_NUM_TOKEN_RE if permissive else _NUM_TOKEN_RE
    rows = _cluster_lines(words)
    y_cutoff = None
    if after:
        for row in rows:
            # `after` patterns are written for TEXT search (e.g.
            # r"\nCurrent Assets\b", expecting the boundary at the START of
            # a line) - a row here has no leading "\n" of its own (words are
            # joined with plain spaces), so prepend one to preserve that
            # same "start of this row" semantics; otherwise the pattern can
            # never match at all and `after` silently does nothing.
            row_text = "\n" + " ".join(w[4] for w in row)
            if re.search(after, row_text, re.I):
                y_cutoff = (row[0][1] + row[0][3]) / 2
                break
    y_upper = None
    if before:
        for row in rows:
            row_text = "\n" + " ".join(w[4] for w in row)
            if re.search(before, row_text, re.I):
                y_upper = (row[0][1] + row[0][3]) / 2
                break
    for row in rows:
        if y_upper is not None and (row[0][1] + row[0][3]) / 2 >= y_upper:
            continue
        if y_cutoff is not None and (row[0][1] + row[0][3]) / 2 <= y_cutoff:
            continue
        texts, row = _merge_loss_qualifier_tokens([w[4] for w in row], row)
        joined = " ".join(texts).lower()
        for name in canonical_names:
            idx = joined.find(name.lower())
            if idx == -1:
                continue
            # Walk the row's own words to find which one the match starts
            # and ends inside, so only numbers STRICTLY to its right are
            # considered (and so the guard below can look strictly to its
            # left).
            pos, start_word_i, end_word_i = 0, None, None
            for wi, t in enumerate(texts):
                pos_end = pos + len(t)
                if start_word_i is None and pos_end > idx:
                    start_word_i = wi
                if pos_end >= idx + len(name):
                    end_word_i = wi
                    break
                pos = pos_end + 1  # +1 for the joining space in `joined`
            if end_word_i is None or start_word_i is None:
                continue
            if reject_context and any(term in joined for term in reject_context):
                continue
            # Two independent tables printed side-by-side can land on the
            # SAME visual row purely by coincidence of height (seen on Gopal
            # Snacks: a Balance Sheet non-current-asset row and the P&L's
            # "Changes in inventories..." row share a y-band). If numbers
            # already appear in the row BEFORE our match, our match is a
            # second, unrelated table's label glued onto the same row, not
            # this row's own leading label - skip it rather than risk
            # pairing it with the wrong table's figures.
            if any(t == "-" or token_re.match(t) for t in texts[:start_word_i]):
                continue
            nums = []
            for w in row[end_word_i + 1:]:
                tok = w[4]
                if tok == "-" or token_re.match(tok):
                    nums.append(tok)
                if len(nums) >= 6:  # plenty for note-ref + 2 values; avoids scanning the whole row
                    break
            if len(nums) < 2:
                continue
            # Permissive mode (comma-optional, so a genuine small face value
            # like "1.81" - one digit before the decimal, which the strict
            # pattern deliberately excludes to avoid grabbing a bare
            # note-reference - matches too) means a bare note-ref number
            # (e.g. "12a"'s numeric-only sibling shape, or a lone "24") could
            # itself slip through as a false first "value". The note
            # reference always sits FIRST on the row, the two real values
            # always LAST - taking the last two sidesteps that regardless
            # (mirrors `_find_payables_row`'s same last-two-in-window
            # approach, same reasoning). Strict mode never has this
            # ambiguity (a bare note number never matches `_NUM_TOKEN_RE` at
            # all), so first-two vs last-two makes no difference there.
            pick = nums[-2:] if permissive else nums[:2]
            a, b = _parse_num(pick[0]), _parse_num(pick[1])
            if a is not None and b is not None:
                return a, b
    return None


# Terms that mark a balance as restricted/earmarked - must NEVER be counted
# in the Cash Ratio numerator even if the line also happens to contain a
# "cash"/"bank balances" phrase (e.g. some filings print "Balances with
# banks - Unpaid dividend accounts" as a face-level sub-line, not just in the
# Notes). Checked in a window AROUND the match (both the label text itself
# and a little before it), not just after - the disqualifying word can
# precede the label ("Unpaid dividend account balances with banks").
_RESTRICTED_CASH_TERMS = [
    "unpaid dividend", "unclaimed dividend", "earmarked", "margin money",
    "escrow", "restricted",
]


def _find_cash_row(text, canonical_names, after=None, words=None):
    """Same matching as `_find_row_values`, but for Cash and Cash Equivalents
    specifically: skips any occurrence whose surrounding text marks it as
    restricted/earmarked (unpaid dividend accounts, margin money, escrow -
    see `_RESTRICTED_CASH_TERMS`), instead of blindly taking the first
    label match. Tries every occurrence of every label, not just the first,
    so a disqualified match doesn't block a genuine one later on the page.

    `words`: optional page word-boxes, tried only when the near-window text
    scan above finds nothing at all - see `_find_row_values_spatial` (same
    fallback `_find_row_values` uses, needed for the same reason: Gopal
    Snacks Ltd's FY25 Annual Report prints the Balance Sheet and P&L side by
    side on one page, so "Cash and cash equivalents"'s own figures can land
    far away from its label in linear text order)."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    for name in canonical_names:
        for m in re.finditer(_fuzzy_label_re(name), search_text, re.I):
            context = search_text[max(0, m.start() - 60):m.end() + 60].lower()
            if any(term in context for term in _RESTRICTED_CASH_TERMS):
                continue  # disqualified - e.g. "unpaid dividend accounts" - try the next occurrence
            window = search_text[m.end():m.end() + 250]
            nums = _row_nums(window)
            if len(nums) >= 2:
                a, b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None and b is not None:
                    return a, b
    if words:
        # `permissive=True`: Cash and Cash Equivalents is routinely a small
        # face value (e.g. Gopal Snacks FY25: "1.81") that the strict
        # pattern's 2+-digit-integer requirement would otherwise miss
        # entirely (see `_find_row_values`'s `permissive` doc for why that
        # requirement exists) - the last-two-of-row pick above keeps a bare
        # note-reference number from being mistaken for a real value.
        result = _find_row_values_spatial(words, canonical_names, after=after,
                                           reject_context=_RESTRICTED_CASH_TERMS, permissive=True)
        if result is not None:
            return result
    return None


def _other_bank_balances_unrestricted(text, canonical_names, after=None):
    """Rebuilds the Other Bank Balances numerator (Cash Ratio, Sr No 12) as a
    deterministic Base -> Net-off -> Optional-Add pipeline:
      Base       = the line's own (current, prior) total, via `_find_row_values`.
      Net-off    = sub-item lines printed directly under the label that match
                   an explicit restricted-label test (`_OBB_RESTRICTED_SUBITEM_TERMS`)
                   - unpaid dividend, margin money, escrow, pledged/lien,
                   security deposits, bank guarantees.
      Optional-Add = Base minus Net-off, folded into the Cash Ratio numerator
                   - but ONLY when Net-off actually matched at least one
                   sub-item (i.e. a real breakup was found to classify). If no
                   sub-item breakup is printed at all, there's nothing to run
                   the include/exclude test against, so nothing is guessed -
                   the Base total is still returned for transparency but
                   `unrestricted_cur`/`unrestricted_prior` stay None.

    Returns None if the line isn't found at all, else a dict with
    base_cur/base_prior, netoff_cur/netoff_prior (None if no breakup found),
    and unrestricted_cur/unrestricted_prior (None if not determinable)."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]

    label_match = None
    for name in canonical_names:
        label_match = re.search(_fuzzy_label_re(name), search_text, re.I)
        if label_match:
            break
    if label_match is None:
        return None

    base = _find_row_values(search_text, canonical_names)
    if base is None:
        return None
    base_cur, base_prior = base

    window = search_text[label_match.end():label_match.end() + 500]
    netoff_cur = netoff_prior = 0.0
    matched_any = False
    for line in window.split("\n"):
        if not any(term in line.lower() for term in _OBB_RESTRICTED_SUBITEM_TERMS):
            continue
        nums = re.findall(_NUM_RE, line)
        if len(nums) >= 2:
            a, b = _parse_num(nums[0]), _parse_num(nums[1])
            if a is not None and b is not None:
                netoff_cur += a
                netoff_prior += b
                matched_any = True

    if not matched_any:
        return {"base_cur": round(base_cur, 2), "base_prior": round(base_prior, 2),
                "netoff_cur": None, "netoff_prior": None,
                "unrestricted_cur": None, "unrestricted_prior": None}

    unrestricted_cur = round(base_cur - netoff_cur, 2)
    unrestricted_prior = round(base_prior - netoff_prior, 2) if base_prior is not None else None
    return {"base_cur": round(base_cur, 2), "base_prior": round(base_prior, 2),
            "netoff_cur": round(netoff_cur, 2), "netoff_prior": round(netoff_prior, 2),
            "unrestricted_cur": unrestricted_cur, "unrestricted_prior": unrestricted_prior}


def _other_financial_liabilities_qualifying(text, canonical_names, after=None):
    """Total Debt (Sr No 20) component c: the qualifying portion of "Other
    Financial Liabilities" - a catch-all BS line that mixes genuinely
    debt-like items with purely operating ones. Applies a deterministic
    Three-Part Test to each sub-item line printed directly under the label:
      1. It's a sub-item of THIS financial-liabilities line at all (i.e. a
         real breakup was printed to test - never guessed if not).
      2. Its label matches an interest-bearing/debt-like term
         (`_OFL_DEBT_LIKE_TERMS`: interest accrued on borrowings, unpaid
         matured deposits, inter-corporate deposits, commercial paper, ...).
      3. Its label does NOT match a disguised-operating term
         (`_OFL_EXCLUDE_TERMS`: employee dues, capital-goods creditors,
         statutory dues, unclaimed dividends, security deposits received,
         ...) - Test 2 alone isn't enough since some debt-like phrasing
         (e.g. "deposit") also appears in operating contexts.
    Same shape as `_other_bank_balances_unrestricted`: returns None if the
    line isn't found at all; if found but no sub-item breakup is printed,
    returns with qualifying_cur=None (informational only, nothing folded
    into Total Debt); if a breakup IS found, qualifying_cur is the sum of
    sub-items passing all three tests (0.0 if none qualify - a real,
    determined zero, not a missing value)."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]

    label_match = None
    for name in canonical_names:
        label_match = re.search(_fuzzy_label_re(name), search_text, re.I)
        if label_match:
            break
    if label_match is None:
        return None

    base = _find_row_values(search_text, canonical_names)
    if base is None:
        return None
    base_cur, base_prior = base

    window = search_text[label_match.end():label_match.end() + 500]
    qualifying_cur = qualifying_prior = 0.0
    matched_any = False
    for line in window.split("\n"):
        ll = line.lower()
        if any(term in ll for term in _OFL_EXCLUDE_TERMS):
            continue  # Test 3 fails - disguised operating item, never debt
        if not any(term in ll for term in _OFL_DEBT_LIKE_TERMS):
            continue  # Test 2 fails - not recognisably interest-bearing
        nums = re.findall(_NUM_RE, line)
        if len(nums) >= 2:
            a, b = _parse_num(nums[0]), _parse_num(nums[1])
            if a is not None and b is not None:
                qualifying_cur += a
                qualifying_prior += b
                matched_any = True

    if not matched_any:
        return {"base_cur": round(base_cur, 2), "base_prior": round(base_prior, 2),
                "qualifying_cur": None, "qualifying_prior": None}

    return {"base_cur": round(base_cur, 2), "base_prior": round(base_prior, 2),
            "qualifying_cur": round(qualifying_cur, 2), "qualifying_prior": round(qualifying_prior, 2)}


def _find_borrowings_note_total(doc, start_idx, max_pages=60):
    """Total Debt (Sr No 20) component a's mandatory Notes verification: the
    Balance Sheet FACE VALUE for Borrowings is never trusted in isolation -
    this scans forward from the Balance Sheet page for the actual Borrowings
    Note (the sub-item breakup: secured/unsecured loans, term loans,
    debentures, commercial paper, ...) and sums its disclosed sub-items as an
    independent cross-check figure. This is what catches the DMart/Maruti-
    style false-zero: a rigid single-line face-value match can miss or
    misparse the Borrowings row entirely while the Note itself, a page or two
    later, plainly discloses real outstanding debt.

    Returns (note_total_cur, subitem_count) - subitem_count is 0 (not None)
    when a plausible Note heading was found but no recognisable sub-item
    matched, to distinguish "found the note, it's genuinely all zero/absent"
    from "never found a Borrowings note at all" (returns None)."""
    for i in range(start_idx, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        # A genuine Borrowings Note heading, not just an incidental mention
        # (e.g. a covenant discussion in MD&A) - require the word "borrowings"
        # near a "Note"/numbered-heading context AND at least one recognised
        # sub-item term on the same page.
        if not re.search(r"\bborrowings\b", tl):
            continue
        if not any(term in tl for term in _BORROWINGS_NOTE_SUBITEM_TERMS):
            continue
        if "cash flow" in tl[:200]:
            continue
        factor = _unit_factor(t)
        total_cur = 0.0
        subitem_count = 0
        for line in t.split("\n"):
            ll = line.lower()
            if not any(term in ll for term in _BORROWINGS_NOTE_SUBITEM_TERMS):
                continue
            nums = re.findall(_NUM_RE, line)
            if len(nums) >= 2:
                a, _b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None:
                    total_cur += a
                    subitem_count += 1
        if subitem_count > 0:
            return round(total_cur * factor, 2), subitem_count
    return None


def _sum_after_label(text, labels, stop_pattern, default_window=400, after=None, words=None):
    """Find the first matching label, then SUM every (current, prior) number
    pair between it and `stop_pattern` (or `default_window` chars if the stop
    pattern isn't found). Handles the common case where a total is disclosed
    only as an unlabelled sum of sub-items (e.g. Revenue split into 'Sale of
    Products' / 'Sale of Services' / 'Other Operating Revenue' with no single
    total row; Trade Payables split into MSME / Others / Acceptances with no
    single total row) - this also correctly reduces to just reading the
    number when there's only one row, so one code path covers both shapes.
    `after`: optional regex: only search after its first match (see
    `_find_row_values`'s `after` for why - restricts to the right sub-section).
    `words`: optional page word-boxes, tried only as a single-row fallback
    (see `_find_row_values_spatial`) when the text-based scan above finds
    nothing - doesn't attempt the multi-row sum spatially, just the common
    single-row case."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    m = None
    for lbl in labels:
        m = re.search(_fuzzy_label_re(lbl), search_text, re.I)
        if m:
            break
    if m:
        tail = search_text[m.end():]
        stop = re.search(stop_pattern, tail, re.I) if stop_pattern else None
        window = tail[:stop.start()] if stop else tail[:default_window]
        nums = _row_nums(window)
        # A Balance Sheet that discloses an Ind AS-transition opening
        # balance sheet (first-time adopters, common for recent IPOs/SME
        # migrations) prints THREE comparative columns per row - "As at
        # March 31 YYYY / As at March 31 YYYY-1 / As at April 1 YYYY-2" -
        # not the usual two. For a SINGLE-row label (the common case this
        # function handles - one label, no sub-item split), that leaves an
        # odd count of trailing numbers (e.g. 3), which the strict
        # even-pair-count path below can never satisfy, so it always
        # returned None even though the current/prior figures are right
        # there as the first two numbers. Confirmed real on Prime Fresh
        # Limited's Consolidated Balance Sheet ("Trade Payables 23 544.35
        # 168.13 398.87" - the 3rd figure is the April-1-2024 opening
        # balance). Trimming to the first two numbers only applies when the
        # count is EXACTLY 3 (this specific shape); a genuine multi-row sum
        # landing on some other odd count (5, 7, ...) is left alone and
        # still fails, same as before this fix.
        if len(nums) == 3:
            nums = nums[:2]
        if len(nums) >= 2 and len(nums) % 2 == 0:
            cur_vals = [_parse_num(n) for n in nums[0::2]]
            prior_vals = [_parse_num(n) for n in nums[1::2]]
            if not any(v is None for v in cur_vals) and not any(v is None for v in prior_vals):
                return round(sum(cur_vals), 2), round(sum(prior_vals), 2)
    if words:
        result = _find_row_values_spatial(words, labels, after=after)
        if result is not None:
            return result
    return None


def _find_revenue(pl_text, words=None):
    """Revenue from Operations, from the P&L page already located for COGS.
    Most filings print a single total row (e.g. HUL, Tata Steel, Sun Pharma) -
    matched directly. Some (e.g. Asian Paints) print only sub-items under a
    'REVENUE FROM OPERATIONS' section header with no total row before 'Other
    Income' - sum every row in between instead."""
    return _sum_after_label(pl_text, _REVENUE_LABELS, r"other\s+income", words=words)


def _bs_grand_total_is_three_column(bs_text):
    """Structural, phrasing-independent detector for an Ind AS first-time-
    adoption Balance Sheet (3 comparative columns: current year, prior
    year, April-1 opening balance) vs. the normal 2-column shape. Detected
    once from the grand total row itself ("Total assets" / "Total equity
    and liabilities"), which is on the same statement and therefore always
    carries the identical column count as every other row on the page -
    reused by every MANUAL-UPLOAD-ONLY 3-column fix in this file (Total
    Current Liabilities via `_find_subtotal_before`, Lease Liabilities/
    Trade Payables via `_find_payables_row`), the same technique already
    used for Working Capital in tools/document_analysis_engine.py's
    `_extract_bare_section_subtotal`."""
    m = re.search(r"total\s+equity\s+and\s+liabilit|total\s+assets\b", bs_text, re.I)
    if not m:
        return False
    # Line-based, not a flat char-window count: a flat window can run past
    # this row's OWN numbers into the next section's unrelated figures
    # (confirmed real: "TOTAL ASSETS"'s 3 numbers followed a few lines
    # later by "Equity Share Capital"'s own 3 numbers, a 150-char window
    # picked up all 6 and never returned exactly 3). Counts consecutive
    # bare-number lines immediately after the label, stopping at the first
    # non-numeric line (this row's own label text has already been
    # consumed by `m`, so line 1 onward is either this row's own figures
    # or the next row's label).
    count = 0
    for line in bs_text[m.end():m.end() + 200].split("\n"):
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(_NUM_RE, s):
            count += 1
            if count > 3:
                break
            continue
        break
    return count == 3


def _find_payables_row(search_text, label_pattern, boundary_pattern, window_cap=250, three_column=False):
    """Extracts one (current, prior) row from the Balance Sheet's Trade
    Payables block, given the row's own label pattern and a regex marking
    where the NEXT row/section starts (so the window never reaches into it).

    Real filings routinely insert a bare note-reference number (e.g. "24")
    between the label and the actual figures, AND print sub-Rs-1,000 figures
    with no thousands separator (e.g. HUL's "458") that the stricter
    `_NUM_RE` used elsewhere can't match at all. Taking the LAST two numbers
    in a tightly bounded window - rather than the first two, and using a
    permissive comma-optional pattern - handles both: a note-reference is
    always the number closest to the label, and the window boundary keeps
    a followed row's numbers from ever entering the window at all.

    `three_column` (MANUAL-UPLOAD WORKFLOW ONLY - callers only ever pass
    True when `is_manual_mode()` and `_bs_grand_total_is_three_column()`
    both hold, so the automatic/live pipeline's behaviour here is always
    identical to before): an Ind AS first-time adopter prints a THIRD
    column (April-1 opening balance) on this row too, e.g. "48.56  -  -"
    for a lease that only started this year - blindly taking the LAST two
    numbers then grabs (prior, opening) = (0, 0) instead of (current,
    prior) = (48.56, 0), silently zeroing out a real balance. Confirmed
    real on Prime Fresh Limited/LANDMARKACHIEVE's FY26 Consolidated
    Balance Sheet Lease Liabilities row, which fed a ~7% understated Total
    Debt (Sr No 20) into Cash Flow Coverage Ratio (Sr No 35). Takes the
    last THREE numbers instead and reads (current, prior) off the first
    two of those three."""
    m = re.search(label_pattern, search_text, re.I)
    if not m:
        return None, None
    boundary = re.search(boundary_pattern, search_text[m.end():m.end() + window_cap], re.I)
    window = search_text[m.end():m.end() + (boundary.start() if boundary else window_cap)]
    nums = list(re.finditer(r"\(?-?[\d,]+(?:\.\d{1,2})?\)?|(?<=\s)-(?=\s)", window))
    n = 3 if three_column else 2
    if len(nums) < n:
        return None, None
    last_n = nums[-n:]
    cur, prior = _parse_num(last_n[0].group()), _parse_num(last_n[1].group())
    if cur is None or prior is None:
        return None, None
    return (cur, prior), m.end() + nums[-1].end()


def _find_payables(text, after=None):
    """Trade Payables under Current Liabilities. Ind AS Schedule III requires
    the Balance Sheet to disclose it as two sub-items: (a) dues to Micro &
    Small Enterprises and (b) dues to all other creditors - sum both.

    This is called on Balance Sheet text only (never the deeper Notes-to-
    Accounts page, which sometimes breaks item (b) down further into its own
    Acceptances/Trade-payables/Total sub-rows) - confirmed by every call site
    in this file. So exactly two rows are ever expected here.
    """
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]

    msme_pat = r"total\s+outstanding\s+dues\s+of\s+micro\s+enterprises\s+and\s+small\s+enterprises"
    # The word "creditors" before "other than" isn't universal - Gopal
    # Snacks' Annual Report (both FY24 and FY25) phrases the complement row
    # as "Total outstanding dues of OTHER THAN micro enterprises and small
    # enterprises", with no "creditors" at all. The old pattern required it
    # literally, so `others_pat` never matched, the boundary-bounded MSME
    # window search then also failed, and `_find_payables` returned None -
    # not a missing-MSME-row bug (both rows ARE present and correctly
    # split), just a stricter-than-necessary label match. Made "creditors "
    # optional to cover both phrasings.
    others_pat = r"total\s+outstanding\s+dues\s+of\s+(?:creditors\s+)?other\s+than\s+micro\s+enterprises\s+and\s+small\s+enterprises"
    msme_anchor = re.search(msme_pat, search_text, re.I)
    if not msme_anchor:
        # No MSME/non-MSME split disclosed at all (rare, e.g. very old/small
        # filers) - fall back to the previous label-based approach unchanged.
        return _sum_after_label(search_text, _PAYABLES_LABELS,
                                 r"derivative\s+liabilities|other\s+financial\s+liabilities|\(iv\)")

    msme_row, msme_end = _find_payables_row(search_text[msme_anchor.start():], msme_pat, others_pat)
    if msme_row is None:
        return None
    rest = search_text[msme_anchor.start() + msme_end:]
    others_row, _ = _find_payables_row(
        rest, others_pat,
        r"derivative\s+liabilities|other\s+financial\s+liabilities|\(iv\)|other\s+current\s+liabilities|provisions")
    if others_row is None:
        return None
    return round(msme_row[0] + others_row[0], 2), round(msme_row[1] + others_row[1], 2)


def _find_subtotal_before(text, stop_label, after=None, window=150):
    """Some filings (e.g. Asian Paints) print the Current Assets / Current
    Liabilities subtotal as a BARE (current, prior) number pair with no
    label of its own - it just sits on the line directly above 'TOTAL
    ASSETS' / 'TOTAL EQUITY AND LIABILITIES'. Grabs the last two numbers
    found in a short window immediately before `stop_label`.

    `stop_label` may be a single string or a list of candidate labels -
    some filers (e.g. Bharti Airtel) print an INTERMEDIATE "Total
    liabilities" subtotal between the bare Current Liabilities subtotal
    and the final "Total equity and liabilities" line; searching only for
    the final label pulled the Total Liabilities figures into the window
    instead (both sit well within the same 150-char lookback), silently
    returning the wrong, much larger subtotal. Always uses whichever
    candidate label occurs FIRST/nearest after the section start - the one
    genuinely closest to the bare subtotal - so filers with no intermediate
    caption (only "total equity and liabilities" ever matches) keep
    behaving exactly as before, generically, for any filer shape.

    A different filing shape (confirmed on ITC's Consolidated Balance
    Sheet) prints the LAST line item's own value together with the
    (also unlabelled) subtotal on the same visual row for BOTH the
    current and prior year, e.g.:
        "...Other current assets  1783.61  50708.41  1365.78  43893.28  TOTAL ASSETS"
                                   item_cur subtotal_cur item_prior subtotal_prior
    A blind "last two numbers" grab picks (item_prior, subtotal_prior) =
    (1365.78, 43893.28) - the prior year's single line-item value
    masquerading as the prior-year subtotal, alongside a completely
    unrelated number for the current year. This produced a
    ~30x-too-small Total Current Assets on ITC, which cascaded into a
    negative Quick Ratio (-14.03) and a 15x Operating Cash Flow Ratio.
    When 4+ numbers are found, a genuine subtotal is virtually always
    >= the single line item immediately preceding it in the SAME column
    (it's a cumulative sum) - use that to prefer the (subtotal_cur,
    subtotal_prior) pair over the raw last two tokens. Falls back to the
    original last-two-numbers behavior whenever that condition doesn't
    clearly hold, so the Asian Paints-style clean 2-number case (and any
    ambiguous case) is unaffected."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    labels = [stop_label] if isinstance(stop_label, str) else list(stop_label)
    candidates = [m for m in (re.search(_fuzzy_label_re(lbl), search_text, re.I) for lbl in labels) if m]
    if not candidates:
        return None
    m = min(candidates, key=lambda mm: mm.start())
    win = search_text[max(0, m.start() - window):m.start()]
    # the subtotal is the cluster of figures AFTER the last label word in the window; reading the window from its (mid-row)
    # start picked the previous row's figures (Titan: "Provisions 19 155 100" -> current liabilities = 100)
    words_ = list(re.finditer(r"[A-Za-z]{3,}", win))
    nums = _row_nums(win[words_[-1].end():]) if words_ else _row_nums(win)
    vals = [v for v in (_parse_num(n) for n in nums) if v is not None]
    if len(vals) < 2:
        nums = _row_nums(win)
        vals = [v for v in (_parse_num(n) for n in nums) if v is not None]
    if len(vals) < 2:
        return None
    a, b = vals[-2], vals[-1]
    # MANUAL-UPLOAD WORKFLOW ONLY (never changes the automatic/live
    # pipeline's existing behaviour - gated on `is_manual_mode()`, checked
    # first so it takes priority over the item+subtotal heuristic below,
    # which is a different filing shape entirely and wouldn't structurally
    # trigger on a genuine 3-column page anyway): an Ind AS first-time
    # adopter (e.g. a recent IPO/SME migration) prints a THIRD column on
    # the WHOLE Balance Sheet - "As at March 31 YYYY / As at March 31
    # YYYY-1 / As at April 1 YYYY-2" - so this bare, label-less subtotal
    # row also has 3 trailing numbers (current, prior, opening), not the
    # usual 2 - blindly taking the last two then silently returns (prior,
    # opening) instead of (current, prior). Detected structurally, not by
    # page-header phrasing: the grand-total row right after `stop_label`
    # (e.g. "Total assets"/"Total equity and liabilities") is on the same
    # statement, so it always carries the identical column count. Same fix
    # shape already applied for Working Capital (Sr No 13) in
    # tools/document_analysis_engine.py's _extract_bare_section_subtotal -
    # confirmed real on the same filing (Prime Fresh Limited/
    # LANDMARKACHIEVE FY26 Consolidated Balance Sheet), this time corrupting
    # Cash Ratio (Sr No 12)'s Total Current Liabilities: FY25's 1,002.13
    # was being read as "current" instead of FY26's real 2,028.87.
    three_column = False
    if len(vals) >= 3:
        grand_total_window = search_text[m.end():m.end() + 120]
        grand_total_nums = _row_nums(grand_total_window)
        three_column = len(grand_total_nums) == 3
    if three_column:
        a, b = vals[-3], vals[-2]
    elif len(vals) >= 4:
        item_cur, subtotal_cur, item_prior, subtotal_prior = vals[-4], vals[-3], vals[-2], vals[-1]
        if subtotal_cur >= item_cur and subtotal_prior >= item_prior:
            a, b = subtotal_cur, subtotal_prior
    return (a, b)


def _page_sources(pdf_url, fiscal_year, pl_page=None, bs_page=None):
    """Builds the `sources` list for a ratio's response, one entry per
    statement page it draws from, each linking DIRECTLY to that page via the
    PDF `#page=N` fragment (respected by browser-native PDF viewers) - so
    clicking "Source" opens the Annual Report already scrolled to the exact
    page the number came from, not just the PDF's first page."""
    out = []
    if pl_page:
        out.append({"period": f"FY{fiscal_year}", "label": "P&L",
                     "url": f"{pdf_url}#page={pl_page}", "note": f"P&L p.{pl_page}"})
    if bs_page:
        out.append({"period": f"FY{fiscal_year}", "label": "Balance Sheet",
                     "url": f"{pdf_url}#page={bs_page}", "note": f"Balance Sheet p.{bs_page}"})
    return out


# --------------------------------------------------------------------------------------------
# Contract adapters - the legacy `fetch_*_from_annual_report` response shape over the ONE ratio
# definition in `tools.ratio_contract` and the ONE fact layer in `tools.fundamental_fact_store`.
# --------------------------------------------------------------------------------------------
_LEGACY_RESULT_KEYS = (
    "value_raw", "tests", "max_score", "tests_evaluated", "partial_score", "variables", "components", "market_price",
    "shared_dependencies", "line_items", "other_bank_balances_cr", "other_bank_balances_breakup", "approximation",
    "formula", "averaging", "net_cash", "dividend_found", "dividend_basis", "dps_basis", "ev_cr", "derived_from",
    "variable_cost_extraction_status", "acquisition_flag", "breakdown", "reference_ev_incl_nci", "dividend_components", "reference_declared_for_year_payout_pct", "obb_classification",
)


def _contract_to_legacy(res, fs, fiscal_year):
    """ratio_contract result -> the dict every existing consumer (dashboard cards, nse_xbrl wrappers,
    document-analysis rows, DB write-back) already understands, plus the new provenance fields."""
    import datetime as _dt
    pdf_url = (fs.extras or {}).get("source_url")
    basis = "consolidated" if fs.selection.selected_basis == "CONSOLIDATED" else "standalone"
    status = res.get("status")
    raw = res.get("value_raw")
    applicable = raw is not None and status in ("verified", "needs_review")
    pages = {i.get("source_page") for i in res.get("inputs") or [] if i.get("source_page")}
    pl_page, bs_page = (fs.extras or {}).get("pl_page"), (fs.extras or {}).get("bs_page")
    sources = _page_sources(pdf_url, fiscal_year, pl_page if (pl_page in pages or not pages) else None,
                            bs_page if (bs_page in pages or not pages) else None) if pdf_url else []
    out = {
        "applicable": applicable, "status": status, "value": res.get("value") if applicable else None,
        "unit": res.get("unit"), "confidence": res.get("confidence"), "estimated": bool(res.get("estimated")),
        "period": f"FY{str(fiscal_year)[-2:]} ({basis})", "statement_basis": basis,
        "numerator": res.get("numerator"), "denominator": res.get("denominator"), "sources": sources,
        "note": " ".join(x for x in [res.get("methodology")] + list(res.get("warnings") or []) if x),
        "warnings": list(res.get("warnings") or []), "formula_version": res.get("formula_version"),
        "methodology": res.get("methodology"), "perimeter": res.get("perimeter"), "period_basis": res.get("period_basis"),
        "provenance": res.get("inputs"), "source_url": pdf_url,
        "calculated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    if raw is not None and not applicable:
        out["mathematical_value"] = raw if status == "not_meaningful" else None
    if res.get("reason"):
        out["reason"] = res["reason"]
    for k in _LEGACY_RESULT_KEYS:
        if k in res and res[k] is not None:
            out[k] = res[k]
    if applicable:
        out["value_raw"] = raw
    return out


def _contract_cache_key(kind, sym, fiscal_year, consolidated, lease_basis):
    from tools.ratio_contract import FORMULA_VERSION
    from tools.ratio_breakdown import BREAKDOWN_VERSION
    return (f"ar_contract_{kind}_{FORMULA_VERSION}b{BREAKDOWN_VERSION}_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
            f"{'_manual' if is_manual_mode() else ''}_{_document_identity_tag(sym, fiscal_year)}")


def _contract_fetch(ratio_key, symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """Single adapter every `fetch_*_from_annual_report` ratio goes through. Never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    from tools import ratio_contract as rc
    market_dependent = ratio_key in rc.MARKET_KEYS
    ckey = _contract_cache_key(ratio_key, sym, fiscal_year, consolidated, lease_basis)
    if not market_dependent:
        cached = _read_cache(ckey)
        if cached is not None:
            return cached
    try:
        from tools.fundamental_fact_store import get_canonical_facts
        fs = get_canonical_facts(sym, name, fiscal_year, lease_basis=lease_basis, consolidated=consolidated)
        err = fs.facts.get("_error")
        if err:
            out = {"applicable": False, "reason": err, "source_url": (fs.extras or {}).get("source_url"),
                   "status": "not_disclosed", "formula_version": rc.FORMULA_VERSION}
            if not market_dependent:
                _write_cache(ckey, out)
            return out
        market = rc.live_market(sym) if market_dependent else None
        res = rc.compute_with_parents(ratio_key, fs, market)
        out = _contract_to_legacy(res, fs, fiscal_year)
        if not market_dependent:
            _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] contract fetch {ratio_key} failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def _contract_fact_fetch(fact_key, label, unit, symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """Legacy-shaped response for a single normalized fact (EPS, shares, EBITDA, Total Debt, ...). Never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    from tools import ratio_contract as rc
    ckey = _contract_cache_key("fact_" + fact_key, sym, fiscal_year, consolidated, lease_basis)
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    try:
        import datetime as _dt
        from tools.fundamental_fact_store import get_canonical_facts
        fs = get_canonical_facts(sym, name, fiscal_year, lease_basis=lease_basis, consolidated=consolidated)
        err = fs.facts.get("_error")
        pdf_url = (fs.extras or {}).get("source_url")
        if err:
            out = {"applicable": False, "reason": err, "source_url": pdf_url, "status": "not_disclosed"}
            _write_cache(ckey, out)
            return out
        f = fs.get(fact_key)
        basis = "consolidated" if fs.selection.selected_basis == "CONSOLIDATED" else "standalone"
        if f is None or f.value is None:
            why = (list(f.warnings)[0] if f is not None and f.warnings else f"{label} was not found in the filing.")
            out = {"applicable": False, "reason": why, "source_url": pdf_url,
                   "status": "insufficient_data" if f is not None and f.status == "INSUFFICIENT_DATA" else "not_disclosed",
                   "formula_version": rc.FORMULA_VERSION}
            _write_cache(ckey, out)
            return out
        est = bool(f.estimated or f.status == "NEEDS_REVIEW")
        conf = f.confidence if f.confidence is not None else (0.8 if est else 1.0)
        pages = {f.source_page} if f.source_page else set()
        pl_page, bs_page = (fs.extras or {}).get("pl_page"), (fs.extras or {}).get("bs_page")
        numerator = {"label": label, "value_cr": f.value}
        if fact_key == "total_debt":
            numerator["components"] = (fs.extras or {}).get("debt_components")
        out = {
            "applicable": True, "status": "needs_review" if est else "verified", "value": round(f.value, 2) if unit != "shares" else f.value,
            "value_raw": f.value, "unit": unit, "confidence": conf, "estimated": est,
            "period": f"FY{str(fiscal_year)[-2:]} ({basis})", "statement_basis": basis,
            "numerator": numerator, "sources": _page_sources(pdf_url, fiscal_year, pl_page if pl_page in pages else None,
                                                             bs_page if bs_page in pages else None),
            "note": " ".join(x for x in [f.raw_label or f.source_tag] + list(f.warnings) if x),
            "warnings": list(f.warnings), "provenance": [rc._prov(f)], "formula_version": rc.FORMULA_VERSION,
            "perimeter": f.perimeter, "source_url": pdf_url,
            "calculated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        if fact_key == "dps":
            out["dividend_found"] = True
            out["dps_declared"] = (fs.extras or {}).get("dps_declared")
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] contract fact fetch {fact_key} failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


_GOVERNANCE_SECTION_ANCHORS = {
    # AR-02: KMP remuneration table (Board's Report Annexure, Sec. 197(12))
    "remuneration": [
        "particulars of employees", "managerial remuneration",
        "remuneration of directors", "remuneration to directors",
        "ratio of remuneration",
    ],
    # AR-03: ESOP disclosure note (SEBI SBEB Regulations 2021 Annexure)
    "esop": [
        "employee stock option", "stock option scheme", "esop disclosure",
    ],
    # AR-06 subsection: Key Managerial Personnel - appointments/resignations,
    # the closest a standard AR gets to "management bench depth" evidence.
    "kmp_changes": [
        "key managerial personnel", "change in key managerial",
    ],
    # B.2.2: Shareholding of Directors and KMP (distinct from the promoter-
    # group shareholding table, which is a different section).
    "shareholding_kmp": [
        "shareholding of directors and key managerial personnel",
        "shareholding of directors and kmp", "shares held by directors and kmp",
        "shareholding of key managerial personnel", "equity shares held by directors",
    ],
    # B.2.4: Remuneration Policy - fixed/variable and long-term/short-term
    # incentive design language (distinct from the B.2.1 remuneration TABLE).
    "remuneration_policy": [
        "remuneration policy", "nomination and remuneration policy",
        "policy on remuneration", "policy for remuneration",
    ],
}


def _fetch_ar_text_sections(symbol, name, anchors, cache_key_prefix, prefer_prose=False, fiscal_year=None):
    """Shared plumbing behind fetch_governance_text_sections and
    fetch_founder_track_record_text: downloads the company's latest Annual
    Report PDF once (cached) and returns the best-scoring real page-text
    window per anchor-dict key (`<key>_text`). An anchor phrase can appear
    many times incidentally (AGM notice text, cross-references) before the
    real disclosure - candidate windows for tables are scored by digit density;
    narrative prose candidate windows (when prefer_prose=True) are scored by
    richness of alphabetic words. Returns {'pdf_url', 'fiscal_year', <key>_text: ...}
    or {'error': reason}. Never raises. Reuses the same PDF-fetch plumbing as the
    ratio extractors (BSE/NSE lookup, retry, cache), so a company already visited
    for its ratios pays no extra download cost."""
    try:
        sym = symbol.strip().upper().replace(".NS", "")
        if fiscal_year is None:
            years = list_annual_report_years(sym, name)
            if not years:
                return {"error": _no_annual_report_message(sym)}
            fiscal_year = years[0]
        ckey = f"{cache_key_prefix}_{sym}_{fiscal_year}"
        cached = _read_cache(ckey)
        if cached is not None:
            return cached

        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            out = {"error": "Annual Report PDF URL not found."}
            _write_cache(ckey, out)
            return out

        # Reuses the shared PDF-bytes disk cache (cache/ar_pdfs/, 30-day TTL)
        # instead of this function's own inline download - Phase 1E dedup.
        # Deliberately does NOT switch to ar_document_cache's Stage-2
        # NORMALIZED page-text cache: this function's TOC false-positive
        # guard below depends on RAW (non-whitespace-collapsed) newlines
        # (`toc_number_hits` regex matches "\n\s{0,3}\d{1,3}\s*(?:\n|\t)"),
        # which the normalized cache's whitespace-collapse would destroy -
        # swapping to it would silently change which pages get flagged as
        # Table-of-Contents false positives, a real evidence-interpretation
        # change, not just a caching optimization. Only the download is
        # deduplicated here; per-page fitz parsing stays exactly as-is.
        from tools.ar_table_extractor import download_ar_pdf_bytes
        content = download_ar_pdf_bytes(sym, name, fiscal_year, pdf_url=pdf_url)
        if content is None or len(content) < 50000:
            return {"error": "Could not download the Annual Report right now.", "source_url": pdf_url}

        try:
            import fitz
        except Exception as e:
            return {"error": f"pymupdf unavailable: {e}"}
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            return {"error": f"PDF read failed: {e}"}

        # Keeps the TOP-2 scoring windows per key, not just the single best
        # one - confirmed real gap from live testing: a company's Date-of-
        # Appointment TABLE and its directors' role/designation profiles
        # routinely sit on DIFFERENT pages, so whichever page happened to
        # score marginally higher would win and silently drop the other
        # page's information (TCS: one page had clean appointment dates
        # with no role/designation, another had roles with no clean dates -
        # keeping only the top-1 window meant the result flipped between
        # "dates but no roles" and "roles but no dates" depending on scoring
        # noise, rather than ever seeing both).
        best = {k: [] for k in anchors}
        for page in doc:
            try:
                t = _page_text(page)
            except Exception:
                continue
            tl = t.lower()
            for key, anchor_list in anchors.items():
                for anchor in anchor_list:
                    idx = tl.find(anchor)
                    if idx == -1:
                        continue
                    # "tenure" gets a much larger window than other keys -
                    # a Board of Directors / KMP appointment-date TABLE is
                    # often several director rows long and separate from
                    # any single director's bio paragraph, so a 1300-char
                    # window (fine for a single-anchor prose match) was
                    # routinely cutting the table off before it reached the
                    # actual dates for directors listed further down.
                    # "milestones" (Chairman/MD message) also needs a much
                    # larger window than a single-anchor prose match - a
                    # Chairman's Statement runs several pages, and the
                    # specific completed/delayed/failed initiative language
                    # B.1.1 actually needs almost never appears in the
                    # opening paragraph a 1300-char window captured; it's
                    # further down the letter (confirmed real: HINDUNILVR's
                    # 1300-char window only captured generic opening
                    # remarks, with zero classifiable initiative sentences).
                    tail = 6000 if key in ("tenure", "milestones") else 1300
                    window = t[max(0, idx - 200):idx + tail].strip()
                    if prefer_prose:
                        base_words = len([w for w in window.split() if w.isalpha() and len(w) > 2])
                        wl = window.lower()
                        # A Table of Contents page matches an anchor phrase
                        # (e.g. "Chairman's Statement") just as reliably as
                        # the real page, but is a list of short headings each
                        # followed by a lone page-number token, not prose -
                        # confirmed real false-positive: HINDUNILVR's B.1.1
                        # anchor was landing on the ToC instead of the actual
                        # Chairman's Statement. Detect via a high density of
                        # isolated 1-3 digit numbers standing alone on a line.
                        toc_number_hits = len(re.findall(r"(?:^|\n)\s{0,3}\d{1,3}\s*(?:\n|\t)", window))
                        if toc_number_hits >= 5:
                            score = base_words * 0.05
                        elif any(bad in wl for bad in ["notice of the", "item no.", "proxy form", "book closure"]):
                            score = base_words * 0.1
                        else:
                            if key == "milestones":
                                boost = sum(1 for kw in ["commissioned", "expanded", "launched", "achieved", "growth", "completed", "capacity", "turnaround", "investment", "milestone"] if kw in wl)
                            elif key == "tenure":
                                boost = sum(1 for kw in ["appointed", "w.e.f", "din", "director", "years", "experience", "qualification", "managing director", "tenure"] if kw in wl)
                            elif key == "strategy":
                                boost = sum(1 for kw in ["strategy", "focus", "priority", "growth", "expansion", "market", "target", "pillar", "roadmap"] if kw in wl)
                            else:
                                boost = 0
                            score = base_words * (1.0 + 0.5 * min(boost, 5))
                    else:
                        score = sum(c.isdigit() for c in window)
                    if not any(w == window for _, w in best[key]):
                        best[key].append((score, window))
                        best[key].sort(key=lambda sw: -sw[0])
                        # "tenure" keeps more candidate pages than other
                        # keys - a company's Board's Report appointment
                        # announcement, its Corporate Governance director
                        # table, AND a cessation notice can each independently
                        # score well on different pages, and the individual
                        # executive's appointment sentence (the one thing
                        # this sub-point actually needs) isn't reliably the
                        # single or even second-highest scoring page.
                        keep = 4 if key == "tenure" else 2
                        del best[key][keep:]

        out = {"pdf_url": pdf_url, "fiscal_year": fiscal_year}
        for key in anchors:
            windows = [w for _, w in best[key]]
            out[f"{key}_text"] = "\n\n=== (separate page) ===\n\n".join(windows) if windows else None
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] _fetch_ar_text_sections failed for {symbol}: {e}")
        return {"error": f"Error: {e}"}


def fetch_governance_text_sections(symbol, name):
    """Real, grounded text excerpts from the company's OWN latest Annual
    Report PDF for the governance sub-points (B.2 remuneration/ESOP, B.3 KMP
    changes) that need AR-02/AR-03/AR-06 content - not a business-description
    proxy, the actual filing. Returns {'pdf_url', 'fiscal_year',
    'remuneration_text', 'esop_text', 'kmp_changes_text'} (each text field
    None if that section wasn't located) or {'error': reason}. Never raises."""
    return _fetch_ar_text_sections(symbol, name, _GOVERNANCE_SECTION_ANCHORS, "ar_gov_text_v3")


# Founder/CEO track-record evidence anchors (B.1.1-B.1.3). Three independent
# families: milestones (Chairman/MD message - B.1.1 past successes/failures),
# tenure (Corporate Governance Report director appointment detail - B.1.2),
# strategy (MD&A Business Strategy + director profiles - B.1.3 relevance to
# current strategy).
_FOUNDER_TRACK_RECORD_ANCHORS = {
    "milestones": [
        "chairman's message", "chairman & managing director", "chairman and managing director",
        "message to shareholders", "managing director's message", "md's message",
        "letter to shareholders", "letter from the chairman", "chairman's statement",
        "statement from the chairman", "reflections & outlook", "reflections and outlook",
        # Deliberately excludes bare "milestones" / "our journey" / "key
        # milestones" / "historical milestones" - confirmed real false-
        # positive source: those single generic words/phrases match
        # anywhere a report happens to use them (e.g. an unrelated CSR
        # section reading "...28 girls have achieved significant
        # milestones this season..."), silently pulling in an unrelated
        # page instead of the actual Chairman/MD message. A missed year is
        # reported honestly as N/A; a wrong section is not.
    ],
    "tenure": [
        "date of appointment", "appointed as director", "director since",
        "brief profile of directors", "brief resume of directors", "brief resume of the directors",
        "profile of directors", "details of directors", "board of directors profile",
        "particulars of directors", "term of appointment", "date of birth / appointment",
    ],
    "strategy": [
        "business strategy", "strategic priorities", "our strategy",
        "key strategic", "growth strategy", "director profile", "strategic roadmap",
        "strategic focus", "growth drivers", "strategic pillars",
    ],
}


def fetch_founder_track_record_text(symbol, name):
    """Real, grounded text excerpts from the company's OWN latest Annual
    Report PDF for B.1's three sub-points - B.1.1 past successes/failures
    (Chairman/MD message + historical-milestones narrative), B.1.2
    management tenure (Corporate Governance Report director
    appointment/tenure detail), B.1.3 relevance to current strategy (MD&A
    Business Strategy + director profiles). Returns {'pdf_url',
    'fiscal_year', 'milestones_text', 'tenure_text', 'strategy_text'} (each
    text field None if that section wasn't located) or {'error': reason}.
    Never raises. Shares PDF-fetch plumbing with fetch_governance_text_sections."""
    # v5: widened the "tenure" key's captured window (1300 -> 6000 chars) so
    # a multi-director appointment-date table isn't cut off - bumped so this
    # doesn't keep serving pre-widening cached text forever.
    return _fetch_ar_text_sections(symbol, name, _FOUNDER_TRACK_RECORD_ANCHORS, "ar_founder_text_v8", prefer_prose=True)


def fetch_founder_milestones_multi_year(symbol, name, n_years=5):
    """B.1.1's real sourcing pathway: the Chairman/MD message across the
    last up to `n_years` Annual Reports (not just the latest one) - a
    single-year read can't tell successful from failed/ongoing initiatives,
    since an initiative announced in year N often only resolves in year
    N+1/N+2. Returns a list of {'fiscal_year', 'pdf_url', 'milestones_text'}
    (oldest-fetch-failure years simply omitted), newest first. Never raises;
    empty list if no Annual Reports are found at all. Each year's PDF is
    cached independently, so a year already fetched for a different
    sub-point (or a prior run) costs nothing extra."""
    sym = symbol.strip().upper().replace(".NS", "")
    try:
        years = list_annual_report_years(sym, name)
    except Exception as e:
        print(f"[annual_report_financials] fetch_founder_milestones_multi_year year-list failed for {sym}: {e}")
        years = []
    out = []
    for yr in (years or [])[:n_years]:
        res = _fetch_ar_text_sections(
            sym, name, {"milestones": _FOUNDER_TRACK_RECORD_ANCHORS["milestones"]},
            "ar_milestones_multi_v2", prefer_prose=True, fiscal_year=yr,
        )
        if res.get("milestones_text"):
            out.append({"fiscal_year": yr, "pdf_url": res.get("pdf_url"), "milestones_text": res["milestones_text"]})
    return out


# Revenue-characteristics evidence anchors (A.1.2 - recurring vs cyclical
# revenue). Two independent evidence families: RECURRING (subscription/
# contract/renewal language) and CYCLICALITY (demand/economic-sensitivity
# language). Anchors are phrase families, not exact headings - different
# filers word this differently, so this is deliberately broad; the caller
# still has to interpret the surrounding text, this only locates candidates.
_REVENUE_CHAR_SECTION_ANCHORS = {
    "recurring": [
        "recurring revenue", "subscription revenue", "annual maintenance contract",
        "maintenance contract", "amc revenue", "long-term contract", "long term contract",
        "contracted revenue", "annuity revenue", "annuity income", "renewal rate",
        "renewal of contract", "renewal of", "repeat customer", "repeat business",
        "recurring in nature", "annual recurring revenue", "committed revenue",
        "steady state revenue", "revenue recognition", "contract liabilities",
        "contract assets", "customer contracts", "order book",
    ],
    "cyclicality": [
        "cyclical", "cyclicality", "demand cycle", "industry cycle", "economic cycle",
        "economic sensitivity", "discretionary spending", "discretionary demand",
        "commodity cycle", "interest rate sensitivity", "interest-rate sensitivity",
        "capex cycle", "capital expenditure cycle", "seasonal demand", "seasonality",
        "demand volatility", "credit cycle", "inventory cycle", "economic downturn",
        "demand fluctuation", "market volatility", "resilience across", "business cycle",
    ],
}


# Brand-evidence anchors (A.2.A / row 2A) - phrase families used only to
# LOCATE candidate windows in the Annual Report's MD&A/Business Overview
# text; the actual 0-5 scoring regex categorization happens downstream in
# tools/moat_brand_scoring.py's `_matches_in`, kept as the single source of
# truth for what counts as evidence so this fetcher and the scorer can never
# drift apart on what "brand evidence" means.
_BRAND_EVIDENCE_ANCHORS = [
    # "leadership position" deliberately excluded - confirmed (HGINFRA) it
    # matches Independent Director BIOS ("...significant leadership
    # positions as Additional Chief Secretary...") far more often than any
    # genuine company-brand claim. "leading position"/"leading player" are
    # kept since they're rarely used to describe an individual's career.
    "market leader", "leading position", "leading player",
    "brand recall", "brand equity", "brand loyalty", "trusted brand", "preferred brand",
    "preferred choice", "customer preference", "consumer preference", "customer loyalty",
    "repeat customers", "repeat business", "repeat purchase", "customer retention",
    "premium pricing", "premium positioning", "premium segment", "pricing power",
    "market share", "dominant position", "flagship brand", "strong brand",
    "well-known brand", "established brand",
]
# A window is a director/KMP BIOGRAPHY, not a brand-evidence claim about the
# COMPANY, if it carries these markers near the matched anchor - e.g. "holds
# a bachelor's degree", "Mr./Ms./Dr. <Name>", "Independent Director",
# "career", "graduated". Confirmed false-positive case: HGINFRA's only
# "leading position"-family match was a director's civil-service career
# summary, not anything about the company's market position.
_BIO_CONTEXT_RE = re.compile(
    r"\bindependent director\b|\bboard of directors?\b|\bchief secretary\b|\bkey managerial personnel\b|"
    r"\bholds a\b|\bbachelor'?s degree\b|\bmaster'?s degree\b|\bmba\b|\bgraduated\b|\bcareer\b|"
    r"\bmr\.\s|\bms\.\s|\bdr\.\s|\bappointed as\b|\bresignation\b|\bdate of birth\b",
    re.I,
)


def _fetch_ar_evidence_excerpts(symbol, name, anchors, cache_prefix, fiscal_year=None,
                                 bio_filter=False, max_excerpts=8, max_per_page=1, fetch_label="evidence",
                                 extra_manual_document_types=None):
    """Shared scan-every-page-for-anchor-phrases engine behind every A.2.x
    moat-factor evidence fetcher (Brand, Distribution, and - as they're
    built - Cost Leadership/Network Effects/Switching Costs). Extracted out
    of the original `fetch_brand_evidence_from_annual_report` so each new
    factor only has to supply its own anchor phrase list and cache prefix,
    not re-implement PDF download/scan/score/cache plumbing.

    `bio_filter=True` rejects any candidate window that reads as a director/
    KMP biography rather than a claim about the company itself (see the
    HGINFRA false-positive this guards against - a director's career bio
    matched "leading position").

    `extra_manual_document_types`, when given, is a tuple of
    tools.manual_document_pipeline.QUALITATIVE_DOCUMENT_TYPES values (e.g.
    ("corporate_governance_report", "brsr_esg_report")) - in the manual
    document-upload workflow (tools.manual_mode.is_manual_mode()), any of
    these that were actually uploaded and extracted are scanned alongside
    the Annual Report with the exact same anchor-phrase logic below, so a
    claim found in a Corporate Governance Report/BRSR/Investor Presentation/
    etc. is evidence too, not just one found in the Annual Report. A type
    with no uploaded document is silently skipped - never fabricated. Has
    no effect outside manual mode (the automatic live pipeline never has
    these uploads to begin with).

    Returns {'pdf_url', 'fiscal_year', 'excerpts': [{'text','page','anchor','source'}]}
    or {'error': reason}. Never raises. Cached 90 days.
    """
    try:
        sym = symbol.strip().upper().replace(".NS", "")

        # Stage 1+2 document cache (tools/ar_document_cache.py, Phase 1D):
        # resolves the year/URL (companies.latest_ar_url fast path first,
        # live BSE/NSE lookup only as its own fallback - never fabricated),
        # then reuses a cached PDF download and cached extracted page text
        # if another qualitative task already fetched this company's AR.
        # This REPLACES this function's own previous inline
        # resolve-year/download/fitz-open/per-page-normalize block; the
        # anchor-matching loop below is otherwise byte-for-byte unchanged,
        # and receives the SAME normalized text it always did (ligature
        # map + whitespace collapse + control-char strip), so scoring
        # behavior is unaffected - only where the text comes from changed.
        from tools.ar_document_cache import get_ar_pages
        doc_result = get_ar_pages(sym, name, fiscal_year=fiscal_year)
        if "error" in doc_result:
            fy = fiscal_year or doc_result.get("fiscal_year")
            ckey = f"{cache_prefix}_{sym}_{fy}" if fy else None
            out = {"error": doc_result["error"]}
            if "source_url" in doc_result:
                out["source_url"] = doc_result["source_url"]
            if ckey:
                _write_cache(ckey, out)
            return out

        fy = doc_result["fiscal_year"]
        pdf_url = doc_result["pdf_url"]

        # Manual-mode-only widening: union in whichever requested supporting
        # documents were actually uploaded and extracted for this symbol.
        # Cache key gets a distinguishing suffix so this never collides with
        # (or serves stale results to/from) the AR-only cache entry the
        # automatic live pipeline and every non-widened caller still use.
        sources = [("annual_report", doc_result["pages"])]
        extra_suffix = ""
        if extra_manual_document_types:
            from tools.manual_mode import is_manual_mode
            if is_manual_mode():
                from tools.manual_document_pipeline import get_supporting_document_pages
                used_types = []
                for doc_type in extra_manual_document_types:
                    extra_pages = get_supporting_document_pages(sym, doc_type)
                    if extra_pages:
                        sources.append((doc_type, extra_pages))
                        used_types.append(doc_type)
                if used_types:
                    extra_suffix = "_manual_" + "_".join(sorted(used_types))

        # Folds in `_EXTRACTION_LOGIC_VERSION` (shared with every fundamental
        # wrapper cache - see that constant's docstring) so a fix to an
        # anchor-phrase list here automatically invalidates every
        # previously-cached excerpt result instead of waiting out this
        # cache's own 90-day TTL.
        ckey = f"{cache_prefix}_{sym}_{fy}{extra_suffix}_qv{_EXTRACTION_LOGIC_VERSION}"
        cached = _read_cache(ckey)
        if cached is not None:
            return cached

        candidates = []
        for source, pages in sources:
            for pgi, t in enumerate(pages):
                tl = t.lower()
                for anchor in anchors:
                    idx = tl.find(anchor)
                    if idx == -1:
                        continue
                    start = max(0, idx - 200)
                    if start > 0:
                        sp = t.rfind(" ", 0, start + 1)
                        start = sp + 1 if sp != -1 else 0
                    end = idx + 900
                    if end < len(t):
                        sp = t.rfind(" ", idx, end)
                        if sp > idx:
                            end = sp
                    window = t[start:end].strip()
                    if bio_filter and _BIO_CONTEXT_RE.search(window):
                        continue
                    # Digits/%/named years make a window more likely to carry
                    # the kind of concrete anchor (a count, a date, a
                    # ranking) the 5/5 tier needs - same scoring heuristic
                    # as fetch_revenue_characteristics_evidence.
                    score = sum(c.isdigit() for c in window)
                    candidates.append({"text": window, "page": pgi + 1, "anchor": anchor, "score": score,
                                        "start": start, "end": end, "source": source})

        # Default max_per_page=1 preserves every existing caller's behaviour
        # exactly (one best-scoring window per page). A.3's revenue-model
        # fetcher opts into a higher max_per_page - confirmed on MARUTI, a
        # single AR page carried BOTH the primary point-in-time "Sale of
        # products" clause AND the ancillary over-time "Income from
        # services" clause, and capping at one-per-page silently discarded
        # the primary clause in favour of whichever had a higher digit
        # score, producing a wrong classification even though the correct
        # evidence was on the very same scanned page.
        # Several anchor phrases are substrings of one another (e.g. "over a
        # period of time" is contained in "satisfied over a period of
        # time") and so legitimately match the SAME sentence at nearly the
        # SAME character position - without deduping, those near-duplicate
        # windows would consume the whole max_per_page budget for one page,
        # crowding out a genuinely distinct clause elsewhere on that same
        # page (confirmed on MARUTI: 3 near-duplicate "...satisfied over a
        # period of time" windows over the ancillary services clause filled
        # all 3 per-page slots, silently excluding the page's separate,
        # primary "point in time" vehicle-sale clause). A candidate is
        # treated as a duplicate of an already-accepted one on the same page
        # when their character ranges overlap by more than half of the
        # shorter window.
        per_page_ranges = {}
        per_page_counts = {}
        excerpts = []
        for c in sorted(candidates, key=lambda c: -c["score"]):
            page_key = (c["source"], c["page"])
            if per_page_counts.get(page_key, 0) >= max_per_page:
                continue
            ranges = per_page_ranges.setdefault(page_key, [])
            overlap_len = max(
                (min(c["end"], r_end) - max(c["start"], r_start) for r_start, r_end in ranges),
                default=0,
            )
            if overlap_len > 0.5 * (c["end"] - c["start"]):
                continue
            ranges.append((c["start"], c["end"]))
            per_page_counts[page_key] = per_page_counts.get(page_key, 0) + 1
            excerpts.append({"text": c["text"], "page": c["page"], "anchor": c["anchor"],
                              "source": c["source"], "start": c["start"]})
            if len(excerpts) >= max_excerpts:
                break

        # Candidates above are picked by digit-density SCORE (best evidence
        # first), but the final list is re-ordered by (PAGE, position on
        # page) - callers that join excerpt text in order (e.g. A.3's
        # classify_contract_type, which treats the first recognition-timing
        # sentence found as the company's PRIMARY disclosure, matching how
        # Notes to Accounts are actually laid out) need real document
        # order, not score order. Sorting by page alone isn't enough:
        # confirmed on MARUTI, where the "point in time" vehicle-sale clause
        # sits ABOVE the "over a period of time" services clause on the very
        # same page, but the higher-digit-score services window kept
        # sorting first under page-only ordering. Every other existing
        # caller pools all excerpt text without relying on ordering, so
        # this is safe to apply unconditionally.
        excerpts.sort(key=lambda e: (e["source"] != "annual_report", e["source"], e["page"], e["start"]))
        for e in excerpts:
            del e["start"]

        out = {"pdf_url": pdf_url, "fiscal_year": fy, "excerpts": excerpts}
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {fetch_label} fetch failed for {symbol}: {e}")
        return {"error": f"Error: {e}"}


def fetch_brand_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Business Overview / MD&A) for A.2.A (Brand moat). This is the ACTUAL
    MD&A narrative, not the thin yfinance company-blurb proxy previously
    used - that blurb is a dry factual description and structurally almost
    never contains brand-marketing language, which was causing
    near-universal "Missing" brand scores even for companies with real,
    citable brand evidence in their own Annual Report.
    """
    return _fetch_ar_evidence_excerpts(
        symbol, name, _BRAND_EVIDENCE_ANCHORS, "ar_brandevid_text_v2",
        fiscal_year=fiscal_year, bio_filter=True, fetch_label="brand-evidence",
        extra_manual_document_types=("investor_presentation", "earnings_call_transcript", "credit_rating_report"),
    )


# Distribution-evidence anchors (A.2.B / row 2B) - network reach, exclusivity,
# and channel-depth language. Unlike Brand, a specific numeric/dated AR claim
# here (dealer counts, state coverage, exclusivity terms) is PRIMARY evidence
# in its own right per the spec - not capped at MANAGEMENT_CLAIM - since
# operational distribution stats disclosed in a regulated Annual Report are
# treated as verifiable facts, not marketing prose. Generic, unquantified
# claims ("pan-India presence", "wide network") stay capped, same as Brand.
_DISTRIBUTION_EVIDENCE_ANCHORS = [
    "distribution network", "dealer network", "dealers across", "distributor network",
    "distributors across", "retail outlets", "sales outlets", "franchise network",
    "exclusive distribution", "exclusive distributor", "exclusive dealer",
    "channel partners", "sales network", "pan-india presence", "pan india presence",
    "states and union territories", "touchpoints", "retail touchpoints",
    "distribution reach", "network of dealers", "network of distributors",
]


def fetch_distribution_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Business Overview / MD&A) for A.2.B (Distribution moat) - dealer/
    distributor network reach, exclusivity agreements, channel depth."""
    return _fetch_ar_evidence_excerpts(
        symbol, name, _DISTRIBUTION_EVIDENCE_ANCHORS, "ar_distevid_text_v1",
        fiscal_year=fiscal_year, bio_filter=True, fetch_label="distribution-evidence",
        extra_manual_document_types=("investor_presentation", "earnings_call_transcript", "credit_rating_report"),
    )


# Cost-leadership evidence anchors (A.2.C / row 2C) - a NAMED source of cost
# advantage (scale, captive input, proprietary process/technology), never
# just a margin number by itself (the margin-vs-peers comparison is the
# separate quant leg, computed from Screener data via
# tools/moat_peer_scoring.score_quant_pillars - never text-scanned).
_COST_LEADERSHIP_EVIDENCE_ANCHORS = [
    "economies of scale", "scale advantage", "scale efficienc", "cost per unit",
    "cost per tonne", "lowest cost producer", "low-cost producer", "low cost producer",
    "cost leadership", "cost advantage", "captive mine", "captive raw material",
    "captive power", "backward integration", "vertically integrated",
    "proprietary technology", "proprietary process", "in-house technology",
    "patented process", "cost efficient operations", "cost-efficient operations",
]


def fetch_cost_leadership_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Business Overview / MD&A) for A.2.C (Cost leadership moat) - the
    qualitative leg only: a NAMED reason for a lower cost base (scale,
    captive input, proprietary technology). The quantitative leg (operating
    margin vs peer set) is computed separately from real Screener data via
    tools/moat_peer_scoring.score_quant_pillars, never text-scanned."""
    return _fetch_ar_evidence_excerpts(
        symbol, name, _COST_LEADERSHIP_EVIDENCE_ANCHORS, "ar_costevid_text_v1",
        fiscal_year=fiscal_year, bio_filter=True, fetch_label="cost-leadership-evidence",
        extra_manual_document_types=("investor_presentation", "earnings_call_transcript", "credit_rating_report"),
    )


# Network-effects evidence anchors (A.2.D / row 2D) - two distinct anchor
# tiers, scanned together in one pass and split apart downstream by
# tools/moat_network_effects_scoring.py:
#   - platform-language anchors (does this business even HAVE a platform/
#     marketplace element at all? gates the N/A branch - a company with none
#     of these anywhere is N/A, not a low score, per the spec's explicit
#     "N/A means the factor doesn't apply" instruction).
#   - growth-linkage anchors (GMV/transaction-value terms alongside user-base
#     terms) - the actual evidence the rubric requires; platform language
#     ALONE never reaches above 3/5.
#     Bare "platform" / "ecosystem" / "marketplace" are deliberately
#     EXCLUDED - confirmed false positives: "platform"/"ecosystem" matched
#     generic corporate boilerplate (HGINFRA's "SAP S/4HANA Enterprise
#     platform", "transport ecosystem"); bare "marketplace" matched ordinary
#     English usage meaning "the market"/competitive landscape (DABUR:
#     "remain distinctive in the marketplace", JYOTHYLAB: "competitive
#     marketplace") rather than an actual two-sided marketplace BUSINESS;
#     bare "online platform(s)" matched a company merely SELLING THROUGH
#     existing third-party platforms as a distribution channel (HERITGFOOD:
#     "wider availability through supermarkets and online platforms"), not
#     the company itself OWNING/OPERATING one. Only phrases that require
#     explicit ownership or an unambiguous marketplace-business-model
#     meaning are kept.
_NETWORK_EFFECTS_PLATFORM_ANCHORS = [
    "network effect", "two-sided market", "two sided market", "aggregator model",
    "gig economy", "marketplace model", "marketplace business", "marketplace platform",
    "our marketplace", "digital marketplace", "online marketplace",
    "e-commerce platform", "ecommerce platform", "our platform connects",
    "the platform connects", "platform business model", "platform-based business",
    "buyers and sellers", "sellers and buyers",
    # v4: "network of merchants"/"merchant partners" - confirmed false
    # NEGATIVE on RELIANCE, whose AR describes JioMart Digital as a business
    # that "partners with a large network of merchants nationwide for
    # distribution" - a real platform-business description using retail-tech
    # vocabulary ("merchants" rather than "buyers and sellers"/"marketplace")
    # that none of the anchors above matched, so the whole factor fell
    # through to N/A even though a genuine platform element was disclosed.
    # Generic across any company using this common retail-tech phrasing, not
    # Reliance-specific.
    "network of merchants", "merchant partners", "merchant network",
]
_NETWORK_EFFECTS_GROWTH_ANCHORS = [
    "gross merchandise value", "gmv", "transaction value", "active users",
    "monthly active users", "registered users", "user base", "seller base",
    "buyer base", "customer base grew", "network of buyers", "network of sellers",
    # v4: merchant-side growth vocabulary, same rationale as above.
    "merchant base", "merchant engagement", "expanding customer base",
    "growing customer base",
]
_NETWORK_EFFECTS_ANCHORS = _NETWORK_EFFECTS_PLATFORM_ANCHORS + _NETWORK_EFFECTS_GROWTH_ANCHORS


def fetch_network_effects_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Business Overview / MD&A) for A.2.D (Network effects moat) - platform/
    marketplace language AND, separately, GMV/transaction-value-vs-user-base
    growth-linkage language (the actual evidence the rubric requires; mere
    platform existence is explicitly NOT sufficient evidence per the spec)."""
    return _fetch_ar_evidence_excerpts(
        symbol, name, _NETWORK_EFFECTS_ANCHORS, "ar_neteffevid_text_v6",
        # v5: max_excerpts raised 8 -> 20 - confirmed on RELIANCE, whose
        # "transaction value" anchor (kept for legitimate GMV-adjacent
        # e-commerce vocabulary) ALSO matches ordinary related-party-
        # transaction disclosure boilerplate ("transaction value... for the
        # immediately preceding financial year"), which appears on 8+ pages
        # and is digit-dense enough to win every slot in the default 8-item
        # cap, crowding out the one genuine "network of merchants" sentence
        # (plain prose, few digits) before it could ever be selected. Same
        # crowding pattern already fixed for A.3's revenue-model anchors.
        # v6: max_per_page raised 1 -> 3 - max_excerpts alone wasn't enough:
        # RELIANCE's page 46 has BOTH "network of merchants" (the real
        # platform-presence evidence) and "merchant engagement" (30-40 words
        # later, in a sentence whose window happened to reach a nearby
        # "1,500 cities" figure and so out-scored the first on digit
        # density) - with the default max_per_page=1, only the higher-
        # scoring one survived, discarding the anchor that actually gates
        # the applicability check.
        fiscal_year=fiscal_year, bio_filter=True, max_excerpts=20, max_per_page=3,
        fetch_label="network-effects-evidence",
        extra_manual_document_types=("investor_presentation", "earnings_call_transcript"),
    )


# Switching-costs evidence anchors (A.2.E / row 2E) - contract lock-in term
# length, renewal rate, and regulatory/certification switching barriers.
# SECONDARY source per spec is the Ind AS 115 revenue-recognition note
# (contract-balance/performance-obligation disclosures) - approximated here
# by scanning the same AR text for its characteristic phrasing
# ("remaining performance obligations", "average contract term") rather
# than parsing the note's structured table, consistent with every other
# A.2.x factor's text-anchor approach (never a dedicated table parser).
_SWITCHING_COSTS_EVIDENCE_ANCHORS = [
    "contract term", "average contract term", "contract lock-in", "lock-in period",
    "renewal rate", "customer retention rate", "contract renewal", "long-term contract",
    "long term contract", "take-or-pay", "take or pay", "remaining performance obligations",
    "unsatisfied performance obligations", "sticky customer", "long-standing relationship",
    "long standing relationship", "vendor qualification", "customer qualification",
    "switching cost", "regulatory approval requirement", "certification requirement",
    # Insurance-sector-specific renewal terminology - confirmed (HDFCLIFE)
    # that "renewal rate" alone missed real, disclosed renewal-equivalent
    # data because insurers use this term of art instead.
    "persistency ratio",
]


def fetch_switching_costs_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Business Overview / MD&A + Ind AS 115 revenue-recognition note text) for
    A.2.E (Switching costs moat) - contract lock-in terms, renewal rates,
    and regulatory/certification switching barriers."""
    return _fetch_ar_evidence_excerpts(
        symbol, name, _SWITCHING_COSTS_EVIDENCE_ANCHORS, "ar_switchevid_text_v2",  # v2: added "persistency ratio" (insurance-sector renewal term)
        fiscal_year=fiscal_year, bio_filter=True, fetch_label="switching-costs-evidence",
        extra_manual_document_types=("investor_presentation", "earnings_call_transcript", "credit_rating_report"),
    )


# Revenue-model evidence anchors (A.3 / row 3) - Ind AS 115 revenue-
# recognition TIMING language (point-in-time vs over-time, the deciding
# factor for Transactional vs Recurring/Annuity), AMC/O&M contract-tenure
# phrasing (the Annuity signal - a DEFINED term length), subscription/
# recurring-revenue phrasing, and separately renewal-rate/persistency
# anchors for the 3D contract-renewal-dynamics sub-row. Deliberately a
# DIFFERENT anchor list from _SWITCHING_COSTS_EVIDENCE_ANCHORS even though
# both scan AR MD&A/notes text - that list looks for lock-in/switching
# FRICTION, this one looks for revenue-recognition TIMING/contract-type
# language; a few renewal-rate anchors are intentionally shared since
# renewal dynamics are evidence for both switching costs and A.3's 3D.
_REVENUE_MODEL_EVIDENCE_ANCHORS = [
    "recognised at a point in time", "recognized at a point in time",
    "point in time when control", "point in time at which control",
    # v2: bare "point in time"/"over a period of time" added - confirmed on
    # MARUTI, whose real "Sale of products" policy note read "recognises
    # the revenue at a point in time when products are dispatched", a
    # phrasing the rigid substrings above never match. False-positive risk
    # is contained downstream: tools/revenue_model_scoring.py's
    # classify_contract_type only accepts a "point in time"/"over time" hit
    # when a revenue/control/performance-obligation word co-occurs nearby in
    # the SAME sentence, so a stray unrelated "at some point in time" phrase
    # elsewhere in the AR still gets rejected as None, not fabricated.
    "point in time",
    "recognised over time", "recognized over time",
    "over a period of time",
    "performance obligation is satisfied over time",
    "performance obligations satisfied over time",
    "performance obligations that are satisfied over a period of time",
    "satisfied over time", "satisfied over a period of time", "satisfied at a point in time",
    "annual maintenance contract", "annual maintenance contracts",
    # NOTE: deliberately NOT scanning bare "amc" as an anchor - confirmed
    # false positive on HDFCBANK, where "amc" matched "HDFC AMC" (Asset
    # Management Company, a subsidiary name), not Annual Maintenance
    # Contract. "annual maintenance contract(s)" (the full phrase) is kept.
    "operation and maintenance contract", "operation and maintenance agreement",
    "o&m contract", "o&m agreement",
    "subscription revenue", "subscription-based revenue", "recurring revenue",
    "one-time sale", "one time sale",
    "revenue recognition policy", "revenue from contracts with customers",
    "renewal rate", "contracts renewed", "persistency ratio",
    # v8: "transferred to the customer" - confirmed missing on VIP
    # Industries, whose real policy note ("...control of the products is
    # said to have been transferred to the customer when the products are
    # delivered to the customer...") was never even fetched because none
    # of the anchors above happened to land near it on that page (it only
    # got picked up incidentally for other companies via a coincidentally
    # nearby different anchor). This is the standard Ind AS 115 control-
    # transfer phrase used generically across virtually every goods-sale
    # revenue note, not company-specific.
    "transferred to the customer",
    # v9: "transferred to the buyer" (trading/distribution filers commonly
    # use "buyer" instead of "customer"), plus the pre-Ind AS 115 "risks
    # and rewards of ownership" test and its "retains no effective
    # control" negative-form counterpart, which many filers still state
    # verbatim in the same Sale-of-Goods paragraph - confirmed missing on
    # Prime Fresh Limited, whose real policy note ("...risks and rewards
    # of ownership had been transferred to the buyer...Company retains no
    # effective control over the goods dispatched...") matched NONE of the
    # anchors above and so was never even fetched, despite being
    # unambiguous point-in-time revenue-recognition language.
    "transferred to the buyer", "risks and rewards of ownership",
    "retains no effective control", "revenue recognition",
]


def fetch_revenue_model_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Ind AS 115 revenue-recognition note text, MD&A/Business Overview) for
    A.3 (Revenue model quality) - recognition-timing language (point-in-time
    vs over-time), AMC/O&M contract-tenure phrasing, subscription/recurring
    phrasing, and renewal-rate/persistency-ratio disclosures. Own cache-key
    prefix and anchor list - deliberately NOT reusing
    _SWITCHING_COSTS_EVIDENCE_ANCHORS, which targets lock-in FRICTION
    language rather than recognition-timing/contract-type language."""
    return _fetch_ar_evidence_excerpts(
        symbol, name, _REVENUE_MODEL_EVIDENCE_ANCHORS, "ar_revmodelevid_text_v9",  # v9: added "transferred to the buyer"/"risks and rewards of ownership" anchors (see comment above)
        # v3: max_per_page=3 - confirmed on MARUTI, whose primary
        # point-in-time "Sale of products" clause AND ancillary over-time
        # "Income from services" clause both live on the SAME AR page; the
        # shared helper's default one-window-per-page cap was silently
        # discarding the primary clause. max_excerpts raised to match so
        # the extra per-page windows aren't immediately squeezed back out.
        fiscal_year=fiscal_year, bio_filter=True, max_per_page=3, max_excerpts=16,
        fetch_label="revenue-model-evidence",
        extra_manual_document_types=("investor_presentation", "earnings_call_transcript"),
    )


# Related-party-transactions note anchors (C.3 / row C.3) - Ind AS 24
# "Related Party Disclosures" is a mandatory Notes-to-Accounts section in
# every Indian company's Annual Report, but its heading wording and internal
# layout (flat list vs. matrix vs. split transactions/balances tables) vary
# by filer - there is no small fixed label universe like the Cash Flow
# Statement's line items. These anchors target the SECTION HEADER and the
# transaction-type/relationship-type vocabulary Ind AS 24 itself mandates
# (so they generalize across filers, per CLAUDE.md's no-ticker-specific-logic
# rule), not any one company's phrasing.
_RPT_EVIDENCE_ANCHORS = [
    "related party disclosures", "related party disclosure",
    "related party transactions", "related party transaction",
    "disclosure of related party", "related parties and transactions",
    "as per ind as 24", "ind as 24",
    "key management personnel", "kmp compensation",
    "transactions with related part",
    "balances outstanding with related part",
    "nature of relationship",
]


# Ind AS 24 filers frequently split "loans/advances given to related
# parties" (KMP, promoters, subsidiaries) into its OWN note, separate
# from the main Related Party Disclosures note, and merely
# cross-reference it there (e.g. HINDUNILVR's Note 44: "Refer note 43
# for terms and conditions of loans given to subsidiaries" - Note 43
# itself, with the real amounts/rates/terms, sits on a different page
# and was never captured by `_RPT_EVIDENCE_ANCHORS` alone). Generic
# Ind AS 24 vocabulary for that note's own heading/table language, not
# any one filer's phrasing.
_LOANS_ADVANCES_EVIDENCE_ANCHORS = [
    "loans and advances to related part", "loans given to related part",
    "loans to related part", "loans given to subsidiar", "loans to subsidiar",
    "loans given to key management", "loans to key management personnel",
    "loans given to director", "loans to director",
    "loans and advances in the nature of loans",
    "disclosure of loans and advances", "loans/advances", "loans /advances",
    "loan given", "loan taken", "loan granted",
]


def fetch_loans_advances_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report
    PDF for the dedicated Loans/Advances-to-related-parties note (Ind AS
    24), used alongside `fetch_rpt_evidence_from_annual_report` for D.5
    since this note is frequently a SEPARATE note from the main RPT
    note, only cross-referenced from it (see anchors' docstring above).
    Own cache prefix so this doesn't collide with C.3's RPT-note cache.
    """
    return _fetch_ar_evidence_excerpts(
        symbol, name, _LOANS_ADVANCES_EVIDENCE_ANCHORS, "ar_loansadvevid_text_v1",
        fiscal_year=fiscal_year, bio_filter=False,
        max_per_page=4, max_excerpts=24, fetch_label="loans-advances-evidence",
        extra_manual_document_types=("corporate_governance_report",),
    )


def fetch_rpt_evidence_from_annual_report(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    (Ind AS 24 "Related Party Disclosures" note, Notes to Financial
    Statements) for C.3 (Related-party transactions) - counterparty names,
    relationship types, transaction types and amounts. Own anchor list and
    cache prefix - deliberately generic Ind AS 24 vocabulary, not any one
    filer's table layout (no ticker-specific logic, per CLAUDE.md).

    RPT notes are frequently long, multi-page tables - max_per_page and
    max_excerpts are raised well above the single-clause moat-factor
    fetchers (e.g. switching-costs evidence) so a real table isn't silently
    truncated to one window."""
    return _fetch_ar_evidence_excerpts(
        symbol, name, _RPT_EVIDENCE_ANCHORS, "ar_rptevid_text_v1",
        fiscal_year=fiscal_year, bio_filter=False,  # bio_filter is for director-CAREER bios; KMP compensation rows legitimately mention director names/roles and must not be dropped
        max_per_page=4, max_excerpts=24, fetch_label="rpt-evidence",
        extra_manual_document_types=("corporate_governance_report",),
    )


def fetch_revenue_characteristics_evidence(symbol, name, fiscal_year=None):
    """Real, grounded text excerpts from the company's OWN Annual Report PDF
    for A.1.2 (cyclical vs recurring revenue) - mirrors
    `fetch_governance_text_sections`'s approach (scan every page, score
    candidate windows by digit density, keep the best per anchor family),
    but additionally preserves the PAGE NUMBER each excerpt came from so the
    frontend can show real source traceability. Returns
    {'pdf_url', 'fiscal_year', 'recurring_excerpts': [...], 'cyclicality_excerpts': [...]}
    where each excerpt is {'text', 'page', 'anchor'}, or {'error': reason}.
    Never raises. Reuses the same PDF-fetch plumbing as the ratio/governance
    extractors (BSE/NSE lookup, retry, cache) - no new data source.

    `fiscal_year` defaults to the latest Annual Report on file; pass an
    explicit year (e.g. for a multi-year Recurring/Cyclical trend) to pull
    that year's own filing instead - same function, same reconciliation
    guarantees, just a different year's PDF."""
    try:
        sym = symbol.strip().upper().replace(".NS", "")
        years = list_annual_report_years(sym, name)
        if not years:
            return {"error": _no_annual_report_message(sym)}
        if fiscal_year is None:
            fiscal_year = years[0]
        elif fiscal_year not in years:
            return {"error": f"No Annual Report on file for FY{fiscal_year}."}
        ckey = f"ar_revchar_text_v5_{sym}_{fiscal_year}"
        cached = _read_cache(ckey)
        if cached is not None:
            return cached

        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            out = {"error": "Annual Report PDF URL not found."}
            _write_cache(ckey, out)
            return out

        # Reuses the shared PDF-bytes disk cache instead of this function's
        # own inline download - Phase 1E dedup. Not migrated to
        # ar_document_cache's Stage-2 NORMALIZED text cache: this function's
        # own scoring relies on RAW (non-whitespace-collapsed) `_page_text`
        # output for its word-boundary snapping (`t.rfind(" ", ...)`) -
        # swapping to pre-collapsed text would change which anchor matches
        # are found and where windows start/end, a real evidence-
        # interpretation change. Only the download is deduplicated here.
        from tools.ar_table_extractor import download_ar_pdf_bytes
        content = download_ar_pdf_bytes(sym, name, fiscal_year, pdf_url=pdf_url)
        if content is None or len(content) < 50000:
            return {"error": "Could not download the Annual Report right now.", "source_url": pdf_url}

        try:
            import fitz
        except Exception as e:
            return {"error": f"pymupdf unavailable: {e}"}
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            return {"error": f"PDF read failed: {e}"}

        # Keep the best few (not just one) candidate windows per family so
        # the LLM interpretation step downstream has enough real evidence to
        # distinguish a genuine numeric disclosure from a passing mention -
        # e.g. "revenue recognition" appears in almost every AR's accounting
        # policy note (low value) vs an actual AMC/subscription % disclosure
        # elsewhere (high value); scoring by digit density favours the latter
        # without hardcoding which anchor phrase matters most.
        #
        # Digit density alone systematically loses to a different failure
        # mode: real recurring/cyclicality NARRATIVE (MD&A prose describing
        # subscriptions, renewals, annuity income, demand sensitivity) is
        # usually digit-light, while generic accounting-note boilerplate
        # (contract assets/liabilities balance tables) is digit-heavy but
        # contains no actual repeat/renewal or cyclicality signal. A window
        # that contains real signal language gets a large score bonus so it
        # isn't buried under numeric tables that only matched on a weak
        # anchor like "contract assets".
        _signal_re = re.compile(
            r"recurr|subscript|renew|annuity|\bamc\b|annual maintenance|repeat (purchase|custom|business)|"
            r"steady state|committed revenue|cyclical|demand (fluctuat|volatil)|economic (cycle|downturn|"
            r"sensitivit)|discretionary (spend|demand)|resilien|market volatilit",
            re.I,
        )
        candidates = {"recurring": [], "cyclicality": []}
        try:
            for pgi, page in enumerate(doc):
                try:
                    t = _page_text(page)
                except Exception:
                    continue
                tl = t.lower()
                for family, anchors in _REVENUE_CHAR_SECTION_ANCHORS.items():
                    for anchor in anchors:
                        idx = tl.find(anchor)
                        if idx == -1:
                            continue
                        # Snap both ends to a whitespace boundary rather than
                        # cutting at a fixed character offset - otherwise the
                        # window routinely starts/ends mid-word (e.g. "er
                        # assets consist of..." instead of "Other assets
                        # consist of..."), which looks broken in the
                        # frontend's quoted source excerpt.
                        start = max(0, idx - 200)
                        if start > 0:
                            # Look BACKWARD for the nearest whitespace at/before
                            # `start` and begin right after it, so the first
                            # word is kept whole rather than skipped entirely.
                            sp = t.rfind(" ", 0, start + 1)
                            if sp != -1:
                                start = sp + 1
                            else:
                                start = 0
                        end = idx + 900
                        if end < len(t):
                            sp = t.rfind(" ", idx, end)
                            if sp > idx:
                                end = sp
                        window = t[start:end].strip()
                        score = sum(c.isdigit() for c in window)
                        if _signal_re.search(window):
                            score += 500
                        candidates[family].append({
                            "text": window, "page": pgi + 1, "anchor": anchor, "score": score,
                        })
        finally:
            doc.close()

        def _top(family, n=6):
            seen_pages = set()
            ranked = sorted(candidates[family], key=lambda c: -c["score"])
            out = []
            for c in ranked:
                if c["page"] in seen_pages:
                    continue
                seen_pages.add(c["page"])
                out.append({"text": c["text"], "page": c["page"], "anchor": c["anchor"]})
                if len(out) >= n:
                    break
            return out

        out = {
            "pdf_url": pdf_url,
            "fiscal_year": fiscal_year,
            "recurring_excerpts": _top("recurring"),
            "cyclicality_excerpts": _top("cyclicality"),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] fetch_revenue_characteristics_evidence failed for {symbol}: {e}")
        return {"error": f"Error: {e}"}


def _no_annual_report_message(symbol):
    """Formal, consistent 'no Annual Report on file' message - used
    everywhere `list_annual_report_years` comes back empty, i.e. BOTH BSE's
    AnnualReport_New API AND NSE's annual-reports API returned zero filings
    for this company (that dual-source check is what `list_annual_report_years`
    performs before returning an empty list). This is a genuine, verified
    data-availability gap, not a fetch/parse failure - most commonly because
    the company IPO'd recently and hasn't reached its first post-listing AGM
    yet (a maiden Annual Report is typically filed 12-18 months after
    listing). Distinguishing this explicitly from other NOT_DISCLOSED
    reasons (e.g. "found the report but couldn't parse a section out of it")
    matters for anyone auditing why a sub-point came back blank."""
    return (
        f"NO ANNUAL REPORT ON FILE - checked both BSE's Annual Report archive and NSE's "
        f"Annual Report archive for {symbol}; neither has a filing on record. This is most "
        f"commonly because the company IPO'd recently and has not yet reached its first "
        f"post-listing AGM (a maiden Annual Report is typically filed 12-18 months after "
        f"listing). Not a fetch error - both primary sources were reachable and responded, "
        f"they simply have nothing filed for this company yet."
    )


def list_annual_report_years(symbol, name):
    """All fiscal years (as ints) an Annual Report exists for, newest first,
    deduplicated. Tries BSE first, then falls back to NSE for companies BSE
    doesn't list (many NSE-only/SME names - e.g. AAKASH). Never raises.

    In tools/manual_mode.py's manual document-analysis workflow, this
    NEVER reaches live BSE/NSE - only the years already sitting in the
    on-disk AR text cache (i.e. actually uploaded) are returned."""
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        from tools.ar_document_cache import manual_cached_years
        return manual_cached_years(symbol)
    try:
        code = _resolve_scrip_code(symbol, name)
        if code:
            s = _sess()
            r = s.get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}", timeout=25)
            rows = json.loads(r.text).get("Table", []) or []
            years = sorted({int(row["Year"]) for row in rows if str(row.get("Year", "")).isdigit()}, reverse=True)
            if years:
                return years
    except Exception as e:
        print(f"[annual_report_financials] BSE year list failed for {symbol}: {e}")
    # BSE had nothing (unlisted there, or no filings) - try NSE.
    try:
        from tools.nse_annual_reports import nse_annual_report_years
        return nse_annual_report_years(symbol)
    except Exception as e:
        print(f"[annual_report_financials] NSE year list failed for {symbol}: {e}")
        return []


def fetch_multi_year_segment_revenue(symbol, name, n_years=4):
    """Multi-year segment revenue for A.4 (product lifecycle stage - segment-
    level CAGR needs 4 consecutive annual data points, same convention as
    tools/metrics_engine.py's company-level cagr_3y_revenue). Calls the
    EXISTING `_get_extracted_financials` (already cached 90 days) once per
    fiscal year for the latest `n_years` years on file, and reads each
    year's `parsed["segments"]` (`[{"label", "value_cr"}]`, absolute crore
    values for that single year).

    Returns {year: [{"label", "value_cr"}, ...]}. A year with no reconciled
    segment note (parsed["segments"] falsy, or an extraction error) is simply
    absent from the dict - never a fabricated/zeroed entry. Never raises.

    This is the slow part of A.4 (up to n_years AR PDF fetches instead of
    today's single latest-year fetch), but each individual year is already
    cached 90 days via `_get_extracted_financials`, so only the FIRST
    computation per company pays the full cost - do not attempt to further
    parallelize/optimize this; per the approved A.4 plan, follow as written.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    out = {}
    try:
        years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[annual_report_financials] fetch_multi_year_segment_revenue: year list failed for {sym}: {e}")
        return out
    for fy in years[:n_years]:
        try:
            parsed = _get_extracted_financials(sym, name, fy, consolidated=True)
        except Exception as e:
            print(f"[annual_report_financials] fetch_multi_year_segment_revenue: FY{fy} fetch failed for {sym}: {e}")
            continue
        if not parsed or "error" in parsed:
            continue
        segments = parsed.get("segments")
        if not segments:
            continue
        out[fy] = [{"label": s["label"], "value_cr": s["value_cr"]} for s in segments]
    return out


def fetch_multi_year_cash_flow_items(symbol, name, n_years=6):
    """Multi-year Capex / M&A / Buyback / Dividend cash outflows for C.7
    (Capital allocation decisions - spec calls for a 5-8 year table; default
    6). Mirrors `fetch_multi_year_segment_revenue`'s pattern exactly: loop
    `list_annual_report_years` for the latest `n_years` years, call the
    already-90-day-cached `_get_extracted_financials` once per year, and pull
    each year's OWN Cash Flow Statement line items out of the result.

    Year-alignment logic (the double-counting trap):
    Each `_get_extracted_financials(sym, name, fy)` call returns a
    (current_year, prior_year) TUPLE per field - fy's own filing shows BOTH
    fy's figures (as "current") AND fy-1's figures (as "prior", a
    comparative column every Ind AS filing prints). If this function looped
    every year in `years` and blindly took `[0]` (current) from each call,
    that's correct and never overlaps - year fy's loop iteration reads ONLY
    fy's current-year column, never fy-1's. So there is actually no
    structural double-count risk from using `[0]` alone across the loop,
    PROVIDED every year's OWN filing is fetched via its own loop iteration.

    The real gap this function has to handle honestly is the opposite case:
    a year whose OWN filing isn't reachable at all (`_get_extracted_financials`
    returns an error, e.g. AR not found/download failure) - that year is
    simply left OUT of the result dict entirely, rather than backfilled from
    the following year's "prior" column. Backfilling from fy+1's prior
    column might look tempting (the data IS sitting right there), but doing
    so would produce a fy entry that's silently sourced from a DIFFERENT
    filing than every other year in the table, with no record of that origin
    switch - and worse, if BOTH fy's own filing AND fy+1's filing end up
    contributing a value for the same fy (e.g. fy's filing partially parses
    some fields but not others), backfilled-from-neighbour values could
    silently coexist with directly-parsed ones inside the same year's row,
    which is a correctness trap for anyone downstream summing/averaging
    across the table. So: ONLY a year's own current-year column, from its
    own filing, ever populates that year's entry here - including the
    OLDEST year in the window, which (same as every other year) is read from
    its own filing's current-year column, not from `years[n_years]`'s prior
    column (that older filing, one year further back than what
    `list_annual_report_years` restricted this loop to, is deliberately never
    fetched at all - outside the requested window).

    Returns {year: {"capex": float_or_None, "dividend_paid": ..., "buyback_spend": ...,
    "acquisition_outflow": ...}}. Capex = capex_ppe_purchase + capex_intangible_purchase
    (both None-safe: if BOTH are None, "capex" is None, not 0; if only one is
    present, uses just that one - a services company legitimately has no PP&E
    purchase line at all). A year absent from `_get_extracted_financials`
    entirely (fetch/parse error) is simply absent from the output dict, same
    "never a fabricated/zeroed entry" convention as
    `fetch_multi_year_segment_revenue`. Never raises."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    out = {}
    try:
        years = list_annual_report_years(sym, name) or []
    except Exception as e:
        print(f"[annual_report_financials] fetch_multi_year_cash_flow_items: year list failed for {sym}: {e}")
        return out
    for fy in years[:n_years]:
        try:
            parsed = _get_extracted_financials(sym, name, fy, consolidated=True)
        except Exception as e:
            print(f"[annual_report_financials] fetch_multi_year_cash_flow_items: FY{fy} fetch failed for {sym}: {e}")
            continue
        if not parsed or "error" in parsed:
            continue

        def _cur(field):
            # Read ONLY the current-year ([0]) column of a (cur, prior)
            # tuple - see docstring above for why the prior column is never
            # used to backfill a different year.
            v = parsed.get(field)
            return v[0] if isinstance(v, (tuple, list)) and len(v) >= 1 else None

        ppe = _cur("capex_ppe_purchase")
        intang = _cur("capex_intangible_purchase")
        if ppe is None and intang is None:
            capex = None
        else:
            capex = (ppe or 0.0) + (intang or 0.0)

        dividend_paid = _cur("dividend_paid")
        buyback_spend = _cur("buyback_spend")
        acquisition_outflow = _cur("acquisition_outflow")

        # A year where every single one of the four categories came back
        # unparsed contributes nothing usable - leave it out entirely rather
        # than adding an all-None row (matches the "absent, not fabricated"
        # convention `fetch_multi_year_segment_revenue` follows for a year
        # with no segment note at all).
        if capex is None and dividend_paid is None and buyback_spend is None and acquisition_outflow is None:
            continue

        out[fy] = {
            "capex": capex,
            "dividend_paid": dividend_paid,
            "buyback_spend": buyback_spend,
            "acquisition_outflow": acquisition_outflow,
        }
    return out


def _find_annual_report_pdf(symbol, name, year):
    """Annual Report URL for the given fiscal year (e.g. 2024 for FY ended
    March 2024). Tries BSE first, then falls back to NSE for companies BSE
    doesn't list. Returns the URL or None. An NSE URL may point at a .zip
    for some older years - `_get_extracted_financials` handles unwrapping.

    In tools/manual_mode.py's manual document-analysis workflow, this
    NEVER reaches live BSE/NSE - only returns the synthetic
    manual-upload:// URL if that year is actually in the AR text cache."""
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        from tools.ar_document_cache import manual_cached_years
        sym = symbol.strip().upper().replace(".NS", "")
        return f"manual-upload://{sym}_{year}" if year in manual_cached_years(sym) else None
    try:
        code = _resolve_scrip_code(symbol, name)
        if code:
            s = _sess()
            r = s.get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}", timeout=25)
            rows = json.loads(r.text).get("Table", []) or []
            for row in rows:
                if str(row.get("Year")) == str(year):
                    url = row.get("PDFDownload")
                    if url and url.startswith("http"):
                        return url
    except Exception as e:
        print(f"[annual_report_financials] BSE lookup failed for {symbol} {year}: {e}")
    try:
        from tools.nse_annual_reports import nse_annual_report_pdf_url
        return nse_annual_report_pdf_url(symbol, year)
    except Exception as e:
        print(f"[annual_report_financials] NSE lookup failed for {symbol} {year}: {e}")
        return None


_SEGMENT_CAPTION_RE = re.compile(
    r"segment\s+revenue|"
    # The Ind AS 108 note is far more commonly titled "Segment Information"
    # (a numbered note, e.g. "19) Segment information") than "Segment
    # Revenue" - without this, the whole note is skipped for any filer using
    # the standard heading (confirmed missing TCS's real, reconciling
    # 6-segment table, which sits under exactly this caption).
    r"\bsegment\s+information\b|\boperating\s+segments?\b",
    re.I)
_SEGMENT_STOP_RE = re.compile(
    r"segment\s+result|inter\s*-?\s*segment|unallocated|total\s+revenue|segment\s+assets|segment\s+liabilit",
    re.I)
_SEGMENT_ROW_RE = re.compile(
    # Allow a parenthetical qualifier in the label (e.g. "Others (includes
    # Exports)", "Beauty & Wellbeing*") - segment names commonly carry one.
    r"([A-Za-z][A-Za-z0-9 &/,'\.\-\(\)]{2,60}?)\s+((?:\([\d,]+(?:\.\d{1,2})?\)|-?[\d,]+(?:\.\d{1,2})?))(?:\s|$)")
_SEGMENT_EXCLUDE_RE = re.compile(
    # "unalloc\w*" rather than a literal "unallocated": filers spell this
    # column "Unallocable" just as often, and that spelling was slipping
    # through as if it were a real reportable segment.
    r"^(total|sub\s*-?\s*total|inter\s*-?\s*segment|unalloc\w*|eliminat|less\s*:|add\s*:|external|internal|"
    r"segment\s+revenue|revenue\s+from\s+operations|external\s+revenue|net\s+revenue)|"
    # Any label that IS or CONTAINS a subtotal/grand-total row (e.g. "FMCG -
    # Total", "Segment Total", "Gross Revenue from sale of products and
    # services") - these duplicate the sum of the real segment rows above
    # them; including them alongside the individual segments triple-counts
    # the same revenue instead of reconciling to it.
    r"\btotal\b|gross\s+revenue|revenue\s+from\s+sale\s+of\s+products|"
    # A fixed-length text window after the caption can bleed in an adjacent
    # note's rows when a PDF's two-column layout gets flattened out of order
    # by extraction (confirmed on HUL: a Key-Managerial-Personnel
    # remuneration note's rows - "Post-employment benefits", "Share-based
    # payments", "Dividend paid", "Commission paid" - appeared inside the
    # segment-note window before the real segment table). None of these are
    # ever genuine Ind AS 108 segment names, so they're safe to exclude
    # generically rather than fixing the underlying text-ordering issue.
    r"remuneration|employee.?s?\s+benefit|post-?\s*employment|share-?\s*based\s+payment|dividend\s+paid|"
    r"commission\s+paid|non-?\s*executive|contribution|employer.?s\s+contribution|"
    # PDF text-extraction artifacts from a date split across lines (e.g. "31st
    # March, 2026" fragmenting into a stray "st March," label) - never a real
    # segment name, always noise.
    r"^\w{0,3}(st|nd|rd|th)\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
    # Narrative/period text sitting inside the segment note. Numbers embedded
    # in that prose ("March 31", "April 1", "Ind AS 115") otherwise parse as
    # if they were segment figures: Infosys' note yielded 9 such phantom
    # columns worth 31/1/115 Cr alongside its 4 real geographies, and the
    # combined set still slipped under the reconciliation tolerance because
    # the junk is tiny next to a 1,78,650 Cr revenue base. A reportable
    # segment is a NAME, never a sentence fragment or a period caption.
    r"\b(year|quarter|period|month)s?\s+end(ed|ing)\b|\bas\s+(at|of)\b|"
    r"\b(for|during)\s+the\b|\bind\s*as\b|\bifrs\b|practical\s+expedient|"
    r"unearned|\b(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b|"
    r"^(the|of|and|from|arising|applying|including)\b",
    re.I)


_SEGMENT_YEAR_ROW_RE = re.compile(r"^\d{4}\s*-\s*\d{2,4}$")


def _extract_segment_revenue_matrix(page, caption_word_y, total_revenue_cr, factor):
    """Fallback for a segment table laid out as a MATRIX - segment names as
    column headers, one numeric row below (e.g. Reliance's "Primary Segment
    Information" table) - rather than ITC-style repeated label-then-numbers
    rows. Plain linear text order scrambles this layout (a header wrapped
    across two PDF lines, or two column headers merged onto one line, both
    seen on Reliance's actual filing), so this uses word BOUNDING BOXES
    instead: the numeric row's word x-positions define the true column
    centers, and every header word - regardless of which visual line it
    printed on - is assigned to whichever numeric column it sits closest to
    on the x-axis, then joined in reading order into that column's label.
    Returns [(label, value)] or []. Never raises."""
    try:
        words = _page_words(page)
        rows = _cluster_lines(words)

        # The numbers row: some filers print a whole reconciliation waterfall
        # under the same column headers (External Turnover -> Inter Segment
        # Turnover -> Value of Sales and Services -> less: GST Recovered ->
        # Revenue from Operations net of GST - all seen on Reliance's own
        # filing, interleaved with an unrelated Borrowings note's numbers on
        # the same page besides), so the FIRST numeric-heavy row isn't
        # necessarily the right one. Scan every candidate row in a window
        # below the caption and pick whichever sums CLOSEST to the company's
        # actual reported Revenue - the row whose total doesn't reconcile is
        # never the one we want, regardless of which row a caption happens
        # to sit closest to.
        num_row_idx, numeric_tokens, best_diff = None, None, None
        for i, row in enumerate(rows):
            row_y = (row[0][1] + row[0][3]) / 2
            if row_y <= caption_word_y + 1 or row_y > caption_word_y + 400:
                continue
            toks = [w for w in row if _NUM_TOKEN_RE.match(w[4]) or _PERMISSIVE_NUM_TOKEN_RE.match(w[4]) or w[4] == "-"]
            if len(toks) < 3:
                continue
            # A row's own "Total" column (one of its tokens, not the row's
            # SUM - that column already equals the sum of every other
            # column in the same row) should closely match the company's
            # reported Revenue when this is the right row.
            vals = [v for v in (_parse_num(t[4]) for t in toks) if v is not None]
            if not vals:
                continue
            diff = min(abs(v - total_revenue_cr) for v in vals)
            if best_diff is None or diff < best_diff:
                num_row_idx, numeric_tokens, best_diff = i, toks, diff
        if num_row_idx is None or len(numeric_tokens) < 3:
            return []

        # The data row's own tokens define the true column geometry. Every
        # later x-based decision is bounded by this span, which is what keeps
        # a SECOND, unrelated table printed alongside on the same visual rows
        # from contaminating the parse (confirmed on Reliance: a Cash Flow
        # Hedge note occupies x~150-470 while the segment table sits at
        # x~860-1140, and PDF extraction flattens both onto shared lines).
        col_centers = [((w[0] + w[2]) / 2) for w in numeric_tokens]
        spacings = [b - a for a, b in zip(col_centers, col_centers[1:])] or [40.0]
        col_pitch = min(spacings)
        x_lo, x_hi = col_centers[0] - col_pitch, col_centers[-1] + col_pitch

        def _in_table(w):
            wx = (w[0] + w[2]) / 2
            return x_lo <= wx <= x_hi

        def _numeric_tokens_in_table(row):
            return [w for w in row
                    if _in_table(w)
                    and (_NUM_TOKEN_RE.match(w[4]) or _PERMISSIVE_NUM_TOKEN_RE.match(w[4]) or w[4] == "-")]

        # Header block: the fiscal-year row and the wrapped header lines
        # around it, down to (not including) the numbers row. The year row
        # must be INCLUDED, not skipped: filers commonly print the year in
        # the table's stub column on the SAME line as the segment names
        # (Reliance: "2023-24  O2C  Oil and Gas  Retail  ...  Total"), so
        # starting below it discarded every segment name and left nothing to
        # label the columns with. The stray year token itself is stripped
        # from the rebuilt label further down.
        year_row_idx = None
        for i in range(len(rows) - 1, -1, -1):
            row_y = (rows[i][0][1] + rows[i][0][3]) / 2
            if row_y >= caption_word_y:
                continue
            row_text = " ".join(w[4] for w in rows[i])
            if re.search(r"\b\d{4}\s*-\s*\d{2,4}\b", row_text.strip()):
                year_row_idx = i
                break
        if year_row_idx is not None:
            # A header can wrap onto the line(s) ABOVE the year row too
            # (Reliance splits "Digital Services" across the rows either side
            # of it), so reach a little further up rather than starting
            # exactly at the year row.
            year_row_y = (rows[year_row_idx][0][1] + rows[year_row_idx][0][3]) / 2
            header_start = year_row_idx
            while header_start > 0:
                prev_y = (rows[header_start - 1][0][1] + rows[header_start - 1][0][3]) / 2
                if year_row_y - prev_y > 30:
                    break
                header_start -= 1
        else:
            header_start = max(0, num_row_idx - 6)

        header_words = []
        for i in range(header_start, num_row_idx):
            row_text_lower = " ".join(w[4] for w in rows[i]).strip().lower()
            if row_text_lower in ("segment", "revenue", "segment revenue") or row_text_lower.isdigit():
                continue
            # Other DATA rows of the same table sit between the header band
            # and the chosen numbers row (Reliance prints External Turnover /
            # Inter Segment Turnover / Value of Sales / GST above it). Their
            # figures are not header text, so never fold them into labels.
            if len(_numeric_tokens_in_table(rows[i])) >= 3:
                continue
            header_words.extend(w for w in rows[i] if _in_table(w))
        if not header_words:
            return []

        # Assign each header word to its nearest numeric column by x-center,
        # then join words per column in reading order (top-to-bottom, then
        # left-to-right) to rebuild that column's full label.
        col_words = [[] for _ in col_centers]
        for w in header_words:
            wx = (w[0] + w[2]) / 2
            nearest = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - wx))
            col_words[nearest].append(w)

        seg_cols = []  # [(column index, cleaned label)] for real segment columns only
        for ci, ws in enumerate(col_words):
            if not ws:
                continue
            label = " ".join(w[4] for w in sorted(ws, key=lambda w: (round(w[1]), w[0]))).strip(" *:.-")
            # Strip stray junk that can leak into the leftmost column when the
            # fiscal-year row wasn't cleanly detected: fiscal-year tokens,
            # bare serial-number digits, and the "Segment Revenue" caption
            # text itself, none of which are real segment names.
            label = re.sub(r"\b\d{4}\s*-\s*\d{2,4}\b", "", label, flags=re.I)
            label = re.sub(r"\bsegment\s+revenue\b", "", label, flags=re.I)
            label = re.sub(r"(?<!\w)\d+(?!\w)", "", label)
            label = re.sub(r"\s{2,}", " ", label).strip(" *:.-")
            if len(label) < 3 or len(label) > 45 or _SEGMENT_EXCLUDE_RE.search(label):
                continue
            # A real segment name is a short label of words - if this column
            # picked up text from an UNRELATED table interleaved on the same
            # page (confirmed possible: e.g. a Borrowings note sharing rows
            # with Reliance's actual segment table), the reassembled label
            # reads as visibly garbled prose/numbers rather than a plausible
            # segment name. Reject on any of those tells rather than ever
            # show a label an analyst would immediately recognize as broken.
            # Reject a label carrying a NUMERIC token (a stray figure that
            # drifted in from a neighbouring column) rather than any digit at
            # all - real segment names do contain digits ("O2C" is Reliance's
            # largest segment, and a blanket digit test silently dropped it).
            if (any(re.fullmatch(r"[\d,.()\-]+", tok) for tok in label.split())
                    or label.count(",") >= 2 or len(label.split()) > 6):
                continue
            seg_cols.append((ci, label))
        if len(seg_cols) < 2:
            return []

        # Align EVERY data row of this table to the column geometry above, so
        # the right revenue row can be chosen by whether it reconciles rather
        # than by which one happened to sit nearest the caption. A segment
        # note stacks several rows under one set of headers (Reliance prints
        # External Turnover / Inter Segment Turnover / Value of Sales and
        # Services / less: GST Recovered / Revenue from Operations), and only
        # some of them are on the same basis as the P&L's revenue line.
        def _row_vector(row):
            vec = {}
            for w in _numeric_tokens_in_table(row):
                wx = (w[0] + w[2]) / 2
                nearest = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - wx))
                # A token must actually sit in its column, not merely be
                # nearest to one - this rejects the neighbouring table's
                # figures instead of folding them into the first/last column.
                if abs(col_centers[nearest] - wx) > col_pitch / 2:
                    continue
                val = _parse_num(w[4])
                if val is not None:
                    vec[nearest] = val * factor
            return vec

        candidates = []  # (row_text_lower, vector)
        for i, row in enumerate(rows):
            row_y = (row[0][1] + row[0][3]) / 2
            if row_y <= caption_word_y + 1 or row_y > caption_word_y + 400:
                continue
            vec = _row_vector(row)
            if len(vec) >= max(2, len(seg_cols) - 1):
                candidates.append((" ".join(w[4] for w in row).lower(), vec))
        if not candidates:
            return []

        def _reconciles(vec, tol):
            # Every labelled segment column must be present: a row missing one
            # sums low and could otherwise sneak under the tolerance while
            # silently dropping a whole segment from the breakdown.
            if any(ci not in vec for ci, _ in seg_cols):
                return None
            segs = [(lbl, vec[ci]) for ci, lbl in seg_cols]
            if len(segs) < 2 or any(v <= 0 for _, v in segs):
                return None
            total = sum(v for _, v in segs)
            if total > 0 and abs(total - total_revenue_cr) / total_revenue_cr <= tol:
                return segs
            return None

        # 1) A row that already reconciles on its own is always preferred.
        for _, vec in candidates:
            hit = _reconciles(vec, 0.06)
            if hit:
                return hit

        # 2) Otherwise the disclosed per-segment revenue is gross of
        #    inter-segment sales, which the consolidated P&L eliminates - so
        #    it legitimately sums ABOVE the company's revenue (Reliance FY24:
        #    segment rows total 10,23,840 vs revenue 9,14,472). Subtracting
        #    the note's own "Inter Segment" row, column by column, is a
        #    deterministic subtraction of two reported figures.
        #
        #    This path is held to a much tighter tolerance than the direct one
        #    and restricted to revenue-basis rows. A segment note stacks
        #    Assets / Liabilities / Capital Expenditure / Result rows under
        #    the SAME column headers, and those are large enough that
        #    subtracting inter-segment turnover from one can land within a
        #    loose band of revenue by coincidence (confirmed: Segment Assets
        #    minus Inter Segment came within 2.2% of Reliance's revenue and
        #    would have been published as the revenue split). A genuine
        #    elimination reconciles essentially exactly, so requiring that
        #    costs nothing real and rejects the coincidences.
        inter_vecs = [v for txt, v in candidates if re.search(r"inter\s*-?\s*segment", txt)]
        for txt, vec in candidates:
            if not re.search(r"turnover|revenue|sales|income", txt):
                continue
            if re.search(r"asset|liabilit|expenditure|depreciation|amorti|result|capital|"
                         r"profit|tax|interest", txt):
                continue
            for iv in inter_vecs:
                hit = _reconciles({ci: vec[ci] - iv.get(ci, 0.0) for ci in vec}, 0.005)
                if hit:
                    return hit
        return []
    except Exception:
        return []


def _extract_segment_revenue(pdf_bytes, total_revenue_cr):
    """Best-effort Ind AS 108 business/geographic segment revenue for the
    CURRENT year - Apple-style Sankey reference diagrams show segments
    merging into Revenue on the left; this is the only place in the
    codebase that could legitimately supply that layer. Deliberately
    conservative: a segment note bundles Revenue/Result/Assets/Liabilities
    sub-tables on the same page(s), so a generic label+number row parser
    WILL sometimes grab the wrong sub-table or a decoy page - rather than
    building out the same iterative false-positive hardening the P&L/BS
    parser has (a multi-day effort), this uses a self-validating gate: the
    parsed segments' sum must reconcile to the P&L's own Revenue figure
    within a tight tolerance, or the whole result is discarded as None. A
    wrong parse essentially never coincidentally sums to the right total,
    so this fails safe far more often than it fails open. Returns
    [{'label', 'value_cr'}, ...] or None. Never raises."""
    if not total_revenue_cr or total_revenue_cr <= 0:
        return None
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None

    try:
        for pgi, page in enumerate(doc):
            try:
                t = _page_text(page)
            except Exception:
                continue
            m = _SEGMENT_CAPTION_RE.search(t)
            if not m:
                continue
            # Bound the row-parsing window to just the Segment Revenue
            # sub-table - stop at the next sub-table caption (Result/Assets/
            # Liabilities) or reconciliation rows (inter-segment, unallocated).
            #
            # The FIRST stop match isn't always the real boundary: some
            # filers' segment note opens with a preamble sentence that uses
            # BOTH "segment revenue" (the caption match) and "segment
            # results" (a stop keyword) back to back - e.g. HINDUNILVR's
            # FY2025 AR: "Segment revenue relating to ... Segment results
            # relate to profit before other income..." - which made the stop
            # regex fire on that second phrase just ~140 characters later,
            # long before the actual REVENUE data table (which appears
            # further down the same page, itself correctly bounded by a
            # later "Total Revenue" stop match). Confirmed by inspecting the
            # extracted page text directly. Rather than trust the first stop
            # match blindly, try each successive stop candidate in order and
            # use the first one whose window actually parses to 2+ segment
            # rows - a false-early stop inside descriptive prose has no real
            # data before it, so it naturally fails this check and the next
            # candidate (the genuine sub-table boundary) is tried instead.
            window_start = m.end()
            factor = _unit_factor(t)
            segments = []
            search_from = window_start + 1
            while True:
                stop = _SEGMENT_STOP_RE.search(t, search_from)
                window = t[window_start:stop.start() if stop else window_start + 3500]
                candidate = []
                for row_m in _SEGMENT_ROW_RE.finditer(window):
                    label = row_m.group(1).strip(" :.-")
                    if len(label) < 3 or _SEGMENT_EXCLUDE_RE.search(label):
                        continue
                    val = _parse_num(row_m.group(2))
                    if val is None:
                        continue
                    candidate.append((label, val * factor))
                if len(candidate) >= 2 or not stop:
                    segments = candidate
                    break
                search_from = stop.end()

            if len(segments) < 2 and re.search(r"(primary\s+segment\s+information|segment\s+information|"
                                                r"operating\s+segments?\b)", t, re.I):
                # Row-list parsing found nothing usable - try the matrix-table
                # layout instead (segment names as column headers, e.g.
                # Reliance's "Primary Segment Information" table). Gated on
                # an actual table-heading marker, not just a co-occurrence of
                # "segment"/"revenue" words - those two words alone can
                # false-positive on unrelated prose (e.g. a forex-hedging
                # note that happens to mention both), which would otherwise
                # feed the matrix parser a completely wrong page.
                def _row_text(r):
                    return " ".join(w[4].lower() for w in r).strip(" :")

                def _find_caption_row(rows):
                    # A genuine "Segment Revenue" sub-table caption prints as
                    # either one short row ("Segment Revenue") or two
                    # stacked single-word rows ("Segment" / "Revenue" on
                    # consecutive lines - confirmed on Reliance's filing) -
                    # never as part of a long prose sentence, which is what
                    # filters out unrelated same-page mentions (seen on
                    # Reliance: a forex-hedging note using both words too).
                    for i, r in enumerate(rows):
                        rt = _row_text(r)
                        words_lower = [w[4].lower() for w in r]
                        if len(r) <= 4 and "segment" in rt and "revenue" in rt:
                            return r, False
                        if rt == "revenue" and i > 0 and _row_text(rows[i - 1]) == "segment":
                            return r, False
                        # An interleaved page (a second, unrelated table's text
                        # sharing the same visual row - seen on Reliance's
                        # filing) can bury the caption at the END of an
                        # otherwise contaminated row; catch "...Segment
                        # Revenue" as the row's trailing two words specifically.
                        if len(words_lower) >= 2 and words_lower[-2] == "segment" and words_lower[-1] == "revenue":
                            return r, False
                        # Some filers (e.g. TCS) print no "Segment Revenue"
                        # caption at all - the reportable-segment names are
                        # the table's own column headers, and "Revenue from
                        # operations" IS the data row directly (label +
                        # numbers on the same visual row), not a caption
                        # above a separate numeric row. Flagged with
                        # `is_data_row=True` so the matrix parser's window
                        # start is nudged to include this row itself, not
                        # only rows strictly below it.
                        if rt.startswith("revenue from operations") or rt.startswith("external revenue"):
                            return r, True
                    return None, False

                try:
                    caption_row, is_data_row = _find_caption_row(_cluster_lines(_page_words(page)))
                    match_page = page
                    if not caption_row and pgi + 1 < len(doc):
                        # The note's heading/definition text and its actual
                        # segment table are frequently split across a page
                        # break (confirmed on TCS: "19) Segment information"
                        # heading on one page, the reconciling 6-segment
                        # table on the next) - a same-page-only search misses
                        # this entirely.
                        next_page = doc[pgi + 1]
                        caption_row, is_data_row = _find_caption_row(_cluster_lines(_page_words(next_page)))
                        if caption_row:
                            match_page = next_page
                    if caption_row:
                        caption_y = (caption_row[0][1] + caption_row[0][3]) / 2
                        if is_data_row:
                            caption_y -= 3  # keep the data row itself inside the scan window below (row_y <= caption_word_y + 1 must be false for this exact row)
                        segments = _extract_segment_revenue_matrix(match_page, caption_y, total_revenue_cr, factor)
                except Exception:
                    segments = []
            if len(segments) < 2:
                continue
            # A genuine per-segment external-revenue row is never larger than
            # total company revenue; drop obvious non-candidates (e.g. a
            # stray "Segment Assets" figure bleeding past the stop boundary).
            segments = [(l, v) for l, v in segments if 0 < v <= total_revenue_cr * 1.05]
            if len(segments) < 2:
                continue
            total = sum(v for _, v in segments)
            if total <= 0:
                continue
            if abs(total - total_revenue_cr) / total_revenue_cr <= 0.06:
                return [{"label": l, "value_cr": round(v, 2)} for l, v in segments]
        return None
    except Exception:
        return None
    finally:
        doc.close()


_SEGMENT_SINGLE_STATEMENT_RE = re.compile(
    r"\b(?:operates?|operating)\s+(?:in\s+)?(?:only\s+)?(?:a\s+|one\s+)?single\s+(?:reportable\s+|operating\s+|business\s+)?segment\b|"
    r"\bsingle\s+(?:reportable\s+|operating\s+|business\s+)?segment\s+(?:company|entity)\b",
    re.I,
)
_SEGMENT_DOMINANT_PCT_RE = re.compile(
    r"constitutes?\s+(?:almost|approximately|about|around)?\s*(\d{1,3}(?:\.\d+)?)\s?%\s+of\s+"
    r"(?:the\s+)?(?:total\s+|combined\s+|company'?s\s+)?(?:operating\s+)?revenue",
    re.I,
)


def _extract_prose_dominant_segment_pct(pdf_bytes, total_revenue_cr):
    """Ind AS 108 fallback for genuinely SINGLE-reportable-segment filers.
    A company below the standard's 10% materiality threshold for its
    non-dominant activities is not required to (and routinely does not)
    present a formal multi-column Segment Revenue table at all - it
    instead states its dominant activity's own share of revenue in prose,
    right in the "Operating Segment" accounting-policy paragraph, as the
    materiality justification for reporting a single segment. Confirmed
    real on Prime Fresh Limited: "...wholesale trading of Fruits and
    Vegetable...which constitutes almost 90.00% of operating revenues of
    the company..." with NO accompanying table - `_extract_segment_revenue`
    (which only parses a formal table) correctly returns None here, but
    the classification this KPI needs (Single Product, >=90% dominant
    segment) is fully, unambiguously stated in that same sentence. This
    is Ind AS 108's own standard materiality-threshold phrasing, not
    specific to any one filer. Returns [{'label','value_cr'}] (a single
    synthetic segment sized to the stated %, so downstream math recovers
    the same % back out) or None if no such prose statement is found.
    Deliberately scoped to pages that also match `_SEGMENT_CAPTION_RE`
    (the Operating Segment/Segment Information note itself), never a
    bare "% of revenue" match anywhere else in the report (e.g. customer-
    concentration disclosures use identical wording for an unrelated
    fact)."""
    if not total_revenue_cr or total_revenue_cr <= 0:
        return None
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None
    try:
        for page in doc:
            try:
                t = _page_text(page)
            except Exception:
                continue
            if not _SEGMENT_CAPTION_RE.search(t):
                continue
            if _SEGMENT_SINGLE_STATEMENT_RE.search(t):
                return [{"label": "Dominant segment", "value_cr": round(total_revenue_cr, 2)}]
            m = _SEGMENT_DOMINANT_PCT_RE.search(t)
            if m:
                try:
                    pct = float(m.group(1))
                except (TypeError, ValueError):
                    continue
                if 0 < pct <= 100:
                    return [{"label": "Dominant segment", "value_cr": round(total_revenue_cr * pct / 100, 2)}]
        return None
    except Exception:
        return None
    finally:
        doc.close()


def _extract_from_pdf(pdf_bytes, consolidated=True):
    """Extract COGS components (current+prior year) and Inventories
    (current+prior year) from the Annual Report's own financial statements.
    Returns a dict or {'error': reason}.

    Annual Reports run 200-400+ pages; pypdf's extract_text() is slow enough
    per page that eagerly parsing every page up front (the previous approach)
    took 30-45s on a large filing. Both target sections are only ever a
    handful of pages apart in practice, so we parse lazily, page by page, and
    stop the moment both are found - typically a few seconds instead. Uses
    PyMuPDF (fitz) rather than pypdf: on a 500+ page Annual Report, pypdf's
    extract_text() took ~20-25s per full-document scan (e.g. the failure case,
    where the target page doesn't exist and every page must be checked);
    PyMuPDF does the same scan in ~1-2s."""
    try:
        import fitz
    except Exception as e:
        return {"error": f"pymupdf unavailable: {e}"}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return {"error": f"PDF read failed: {e}"}

    # Statement heading POSITION on the page is not reliable across filings:
    # some print a page-number label above the heading, others lay the
    # Balance Sheet and P&L out as two columns on the SAME page with the
    # headings as a caption line in between the two tables (seen on Asian
    # Paints' Annual Report) - a `startswith`/leading-window heading match
    # misses both. Instead, detect the page by CONTENT.
    #
    # P&L page: all three COGS rows (manufacturing/goods businesses), OR -
    # for services/IT companies with no COGS at all (Infosys, TCS, ...) -
    # Revenue plus the standard expense-category rows that only appear on the
    # real P&L (not a segment/summary page).
    # Balance Sheet page: Inventories alongside a non-current-assets marker,
    # OR - again for no-inventory businesses - Trade Receivables (in the
    # Current Assets section) alongside a whole-balance-sheet marker.
    # Standalone vs consolidated is tracked from the section headers that
    # precede each statement (auditor's report / notes captions always name
    # the section) rather than from the statement's own heading.
    # Two candidates are tracked per statement: the STRONG signal (COGS rows /
    # Inventories - essentially unambiguous) and a looser SHAPE fallback for
    # no-inventory businesses. Early-exit only fires once BOTH strong signals
    # are found (preserves the fast path for goods businesses); otherwise we
    # keep scanning to the end of the document so a shape-match decoy earlier
    # in the filing (e.g. an MD&A financial-highlights page that happens to
    # mention Revenue + Other income + Employee benefits) can't pre-empt the
    # real statement page found later. Strong match always wins over shape.
    section = None  # None -> 'standalone' -> 'consolidated', in filing order
    want = "consolidated" if consolidated else "standalone"

    pl_cogs_idx, pl_cogs_text = None, None
    pl_shape_idx, pl_shape_text = None, None
    bs_inv_idx, bs_inv_text = None, None
    bs_shape_idx, bs_shape_text = None, None
    for i, page in enumerate(doc):
        if pl_cogs_idx is not None and bs_inv_idx is not None:
            break
        try:
            t = _page_text(page)
        except Exception:
            continue
        # Normalise the "Profit/(loss)" caption qualifier down to plain
        # "Profit" before any substring test below - loss-making-history
        # filings (e.g. Eternal/Zomato) caption the bottom line "Profit/(Loss)
        # for the year"/"Profit/(loss) before tax", and the literal "/(loss)"
        # infix breaks a plain "profit for the year"/"profit before tax"
        # substring match entirely, not just in `_find_pl_row` (which already
        # strips this - see `_strip_formula_refs`) but also in the page-shape
        # detection below (`is_real_pl_statement`), which used to silently
        # fail to recognise the real P&L statement page on such filings.
        tl = re.sub(r"profit\s*/\s*\(\s*loss\s*\)", "profit", t.lower())
        # Only trust the standalone/consolidated marker when it appears on an
        # actual STATEMENT page (balance sheet or P&L caption), not a bare
        # mention of "Consolidated/Standalone Financial Statements" - that
        # generic phrase also appears in the Table of Contents and inside
        # Notes-to-Accounts pages throughout large Integrated Annual Reports
        # (seen on ONGC: it flipped section on nearly every Notes page,
        # 300+ pages before the real statements, leaving the wrong section
        # "active" by the time the genuine standalone P&L was reached, so it
        # got skipped as if it were consolidated). The narrower captions below
        # only occur on the statement's own page/heading, never in a TOC line
        # or a Notes reference.
        if "consolidated balance sheet" in tl or "consolidated statement of profit" in tl:
            section = "consolidated"
        elif "standalone balance sheet" in tl \
             or (_has_pl_caption(tl) and "consolidated" not in tl):
            section = "standalone"

        if section != want:
            continue
        if _is_toc_page(t):
            continue
        # The Cash Flow Statement reconciles operating profit to cash and, in
        # doing so, carries its own "(increase)/decrease in inventories" and
        # "(increase)/decrease in trade receivables" ADJUSTMENT lines (with
        # sign-flipped, wrong-basis values) plus "purchase of property, plant
        # and equipment", "depreciation and amortisation" add-backs, etc. -
        # enough to false-positive every shape-based check below. Exclude it.
        is_cash_flow_page = "cash flow" in tl[:200]
        # A Notes-to-Accounts page can itemize EVERY COGS component as its own
        # note table (e.g. "39. Purchase of Stock in Trade" / "40. Changes in
        # inventories...") and satisfy the "all 3 COGS labels present" check
        # without being the real P&L statement at all (seen on ONGC: this
        # locked pl_idx onto a Notes page hundreds of pages away from the
        # actual statement, so PBT/PAT/Employee Benefit Expense - which only
        # exist on the real statement page - were never found). Require the
        # page to also carry the statement's own bottom-line subtotals, which
        # a components-only Notes page never has.
        is_real_pl_statement = "total expenses" in tl and (
            "profit before tax" in tl or "profit for the year" in tl or "profit for the period" in tl)
        # Some Integrated Annual Reports' Management Discussion & Analysis
        # section prints its OWN presentation-style summary table captioned
        # literally "Consolidated statement of profit and loss" - with
        # "Total expenses"/"Profit for the year" wording too - defeating
        # BOTH safeguards above (seen on Eternal/Zomato: this MD&A table sat
        # on page 42, ~140 pages before the real audited statement, and got
        # mistaken for it, so PBT/PAT/EPS/Employee Benefit Expense - which
        # only the real statement carries in the right note-referenced
        # detail - were never found there). The one reliable tell: a running
        # header naming the MD&A section itself ("Statutory Reports: MD&A"),
        # which the genuine statement (always under "Financial Statements")
        # never carries - and a genuine statement always has a Note-number
        # reference column, which this summary table never does.
        is_mda_page = "md&a" in tl or "management discussion and analysis" in tl
        # Word boxes for this page, split to each statement's own half when
        # the Balance Sheet and P&L are printed SIDE BY SIDE on one landscape
        # page (see `_side_by_side_split_x`) - a no-op split on the ordinary
        # one-statement-per-page layout. Tried as a fallback ONLY when the
        # text-only near-window check below finds nothing, so a row whose
        # label and figures sit far apart in linear text order (confirmed on
        # Gopal Snacks Ltd's FY25 filing) still lets its OWN page pass
        # detection, instead of losing out to some other page's shape-match.
        try:
            page_words = _page_words(page)
        except Exception:
            page_words = []
        pl_page_words = _pl_only_words(page_words)
        bs_page_words = _bs_only_words(page_words)
        if pl_cogs_idx is None:
            if is_real_pl_statement and not is_mda_page and all(
                    _find_row_values(t, names, words=pl_page_words) is not None
                    for names in _COGS_LABELS.values()):
                pl_cogs_idx, pl_cogs_text = i, t
            # Shape fallback for no-COGS (services/IT) businesses. Content
            # shape alone isn't enough - Integrated Annual Reports carry
            # multiple MD&A analysis tables (a "Financial performance"
            # summary, an "Expenditure" breakdown, ...) that mention Revenue,
            # Other income, Employee benefits AND Depreciation together
            # without being the actual statement, and got mistaken for it.
            # Require the literal "Statement of Profit and Loss" heading
            # somewhere on the page too (heading POSITION is unreliable, per
            # the header-window issue above, but heading PRESENCE reliably
            # rules out every MD&A analysis table, which never carries it).
            #
            # A plain substring test isn't enough, though: Directors' Reports
            # routinely reference the statement in prose when discussing
            # retained earnings - "the Board has decided to retain the
            # entire profit ... in the Statement of Profit and Loss" (seen
            # verbatim on Gopal Snacks' FY25 Annual Report) - and that
            # sentence sits on the SAME page as the Directors' Report's own
            # "Financial Performance" summary table, which independently
            # satisfies the Revenue/Other income/Finance costs shape check.
            # Together they falsely won pl_shape_idx on a page ~40 pages
            # before the real (COGS-bearing) statement, permanently blocking
            # the strong match from ever overriding it. A genuine heading is
            # never preceded by "in/to/under/from the" (which only occurs in
            # prose referencing the statement) - require that instead of a
            # bare substring test.
            elif pl_shape_idx is None and not is_cash_flow_page and not is_mda_page \
                    and _has_pl_caption(tl) \
                    and _find_revenue(t, words=pl_page_words) is not None \
                    and "other income" in tl \
                    and any(k in tl for k in ("employee benefit", "finance cost", "depreciation and amortisation")):
                pl_shape_idx, pl_shape_text = i, t
        if bs_inv_idx is None and not is_cash_flow_page:
            has_non_current_marker = "property, plant and equipment" in tl or "non-current assets" in tl
            # A genuine Balance Sheet ALWAYS carries a whole-statement subtotal
            # ("Total Assets" or "Equity and Liabilities") - require one here.
            # Without it, a COGS/Depreciation NOTES page false-matches this
            # "strong" inventory signal: such a page mentions "Inventory" (as
            # a COGS sub-line, often a nil "Inventory at the end of the year:
            # -") AND "property, plant and equipment" (in a depreciation
            # note), passing both old checks despite not being a Balance Sheet
            # at all - and since inv-match outranks the shape fallback, it
            # OVERRODE the real BS page (seen on AAKASH, a no-inventory
            # services company: a notes page hijacked bs_idx, so Total Current
            # Assets / Total Equity / Borrowings - which only the real BS has -
            # were all unreadable). Same principle as the P&L's "total
            # expenses" guard against components-only notes pages.
            has_bs_subtotal = "total assets" in tl or "equity and liabilities" in tl
            if _find_row_values(t, _INVENTORY_LABELS, words=bs_page_words) is not None and has_non_current_marker \
                    and has_bs_subtotal:
                bs_inv_idx, bs_inv_text = i, t
            # Shape fallback for no-inventory businesses: "total assets" (the
            # Balance Sheet's own subtotal line - never appears on the Cash
            # Flow Statement) alongside the PPE/non-current marker. Some
            # filings split Assets and Equity-and-Liabilities across two
            # pages, so "equity and liabilities" can't be required on this
            # SAME page - "total assets" already rules out the CFS page.
            elif bs_shape_idx is None and "total assets" in tl and has_non_current_marker \
                    and _find_row_values(t, _RECEIVABLES_LABELS, after=r"\nCurrent Assets\b",
                                         words=bs_page_words) is not None:
                bs_shape_idx, bs_shape_text = i, t

    pl_idx, pl_text = (pl_cogs_idx, pl_cogs_text) if pl_cogs_idx is not None else (pl_shape_idx, pl_shape_text)
    bs_idx, bs_text = (bs_inv_idx, bs_inv_text) if bs_inv_idx is not None else (bs_shape_idx, bs_shape_text)

    if pl_idx is None:
        return {"error": f"{'Consolidated' if consolidated else 'Standalone'} Statement of Profit and Loss "
                          "not found in the Annual Report."}
    if bs_idx is None:
        return {"error": f"{'Consolidated' if consolidated else 'Standalone'} Balance Sheet "
                          "not found in the Annual Report."}

    # Best-effort per row from here - a ratio only needs SOME of these fields
    # (Inventory Turnover needs components+inventory; Receivables Turnover
    # needs revenue+receivables), so a missing row doesn't fail the whole
    # extraction; each `fetch_*_from_annual_report` checks what it needs.
    pl_factor = _unit_factor(pl_text)
    bs_factor = _unit_factor(bs_text)

    # Word boxes for the spatial fallback (`_find_row_values_spatial`) - only
    # needed when the near-window text scan fails, but cheap enough (one
    # `get_text("words")` call per already-identified page) to compute
    # upfront. When both statements share ONE page (Gopal Snacks FY25:
    # Balance Sheet and P&L printed side by side on a landscape page),
    # restrict each to its own half - see `_bs_only_words`/`_pl_only_words`.
    combined_page = pl_idx == bs_idx

    def _label_directly_followed_by_number(text, label_pattern, after=None):
        """True if `label_pattern`'s FIRST match in `text` is followed
        (skipping only whitespace/note-number tokens) by an actual number -
        i.e. the label's own figures sit right after it, not several OTHER
        labels away. Used to distinguish a page where the near-window text
        scan is trustworthy from one where it isn't: on Gopal Snacks' FY24
        Annual Report, "Total Current liabilities" is followed immediately
        by "1,201.18" - safe. On the SAME company's FY25 filing (different
        page layout - two statements interleaved), the same label is
        followed by two MORE subtotal labels ("Total Liabilities", "Total
        Equity and Liabilities") and a column of note-reference numbers
        before any real figure appears - the near-window scan then quietly
        returns some OTHER row's numbers instead of failing outright, which
        a bare "did it return 2 numbers" check can't catch. Cheap and
        page-agnostic: doesn't matter WHY a page is laid out either way,
        only whether this specific label's own value sits right next to it."""
        search_text = text
        if after:
            m = re.search(after, text, re.I)
            if m:
                search_text = text[m.end():]
        m = re.search(label_pattern, search_text, re.I)
        if not m:
            return False
        # The very next non-whitespace text after the label: a genuine
        # match has a NUMBER here (its own note-reference or value). A
        # wrong match - the label found, but its real figures sit far away
        # - has more LABEL WORDS here instead (e.g. "Total Liabilities").
        tail = search_text[m.end():m.end() + 10].lstrip()
        return bool(re.match(r"\(?-?[\d,]", tail))

    try:
        pl_words = _page_words(doc[pl_idx])
        bs_words = _page_words(doc[bs_idx])
        if combined_page:
            pl_words = _pl_only_words(pl_words)
            bs_words = _bs_only_words(bs_words)
    except Exception:
        pl_words, bs_words = [], []

    components = {}
    for canon, names in _COGS_LABELS.items():
        vals = _find_row_values(pl_text, names, words=pl_words)
        if vals is not None:
            components[canon] = _scale(vals, pl_factor)  # (current, prior), normalised to ₹ Cr

    # Employee Benefit Expense + Other Expenses - needed (alongside COGS) for
    # EBITDA-basis Operating Profit (Sr No 15): Revenue − COGS − these two.
    # Kept as their OWN fields (not folded into `components`), since Inventory
    # Turnover's COGS sum must stay exactly (a+b+c) - never silently widened.
    employee_benefit_expense = _scale(_find_row_values(pl_text, _EMPLOYEE_BENEFIT_LABELS, words=pl_words), pl_factor)
    other_expenses = _scale(_find_row_values(pl_text, _OTHER_EXPENSES_LABELS, words=pl_words), pl_factor)
    # Depreciation & Amortisation - needed (alongside COGS/Employee
    # Costs/Other Expenses) for EBIT-basis Operating Profit (Sr No 15):
    # Revenue − COGS − Employee Costs − Other Expenses − D&A.
    depreciation = _scale(_find_row_values(pl_text, _DEPRECIATION_LABELS, words=pl_words), pl_factor)
    # Direct Expenses (Sr No 15, manual-upload workflow only - see the
    # label-list comment) - same page, no extra scan, computed unconditionally
    # like Employee Benefit Expense/Other Expenses/D&A above; simply unused
    # by the automatic pipeline's Operating Profit Margin fetch function.
    direct_expenses = _scale(_find_row_values(pl_text, _DIRECT_EXPENSES_LABELS, words=pl_words), pl_factor)
    # Total Expenses - the Schedule III P&L's own mandatory grand-total
    # expense line ("Total Expenses (IV)"), universal across EVERY Indian
    # filer regardless of business type. Used as a generic fallback for
    # EBIT-dependent ratios (Operating Profit Margin, ROCE, ROIC, ...) on
    # service/telecom companies with no COGS at all - EBIT = Revenue -
    # (Total Expenses - Finance Costs) is mathematically correct whether or
    # not the company has any Cost of Goods Sold line, unlike the granular
    # Revenue-COGS-EmployeeCosts-OtherExpenses reconstruction, which
    # previously returned "not a goods business"/not_disclosed for ANY
    # company whose P&L has no COGS sub-items at all (confirmed real on
    # Bharti Airtel, a pure telecom/services business).
    total_expenses = _scale(_find_row_values(pl_text, _TOTAL_EXPENSES_LABELS, words=pl_words), pl_factor)
    if total_expenses is None:
        # Some filers (e.g. Bharti Airtel) never caption "Total Expenses"
        # at all - the last expense line item is simply followed by an
        # unlabelled subtotal before the next subtotal caption ("Profit
        # before depreciation, amortisation...", "Profit before exceptional
        # items and tax", or plain "Profit before tax", depending on the
        # filer's own P&L layout). Same bare-subtotal convention as Total
        # Current Assets/Liabilities on the Balance Sheet (`_find_bs_row`'s
        # `subtotal_before`) - reused here via `_find_subtotal_before`
        # directly since this is the P&L, not the Balance Sheet.
        total_expenses = _scale(_find_subtotal_before(
            pl_text, ["profit before depreciation", "profit before exceptional",
                      "profit before tax", "profit/(loss) before tax"]), pl_factor)

    inv = _scale(_find_row_values(bs_text, _INVENTORY_LABELS, words=bs_words), bs_factor)
    revenue = _scale(_find_revenue(pl_text, words=pl_words), pl_factor)
    receivables = _scale(_find_row_values(bs_text, _RECEIVABLES_LABELS, after=r"\nCurrent Assets\b",
                                           words=bs_words), bs_factor)
    # Cash and Cash Equivalents - only the specifically-labelled row, never
    # "Bank balances other than Cash and Cash Equivalents" (a separate,
    # often part-restricted, line some filings print just below it), and
    # never a restricted/earmarked balance like unpaid dividend accounts or
    # margin money even if it happens to say "cash"/"bank balances" (see
    # `_find_cash_row`).
    #
    # On some combined BS+P&L pages, "Cash and cash equivalents" is followed
    # immediately by the NEXT label ("(iii) Bank balance other than...")
    # rather than its own figures, which sit far away - confirmed on Gopal
    # Snacks FY25. The near-window text scan then quietly returns some
    # OTHER row's numbers instead of failing outright. Verify the label is
    # genuinely followed by a number (as it is on, e.g., the same company's
    # FY24 filing, a differently-laid-out combined page where this is safe)
    # before trusting the result - force N/A rather than risk silently
    # attributing the wrong sub-item's figures to Cash.
    #
    # Only apply this on a `combined_page` (see the identical, confirmed-
    # regression rationale on `tcl_label_ok` above) - `_find_cash_row` has
    # its own separate near-window text scan AND spatial fallback, and a
    # filer whose "Cash and cash equivalents" label doesn't exist verbatim
    # (e.g. a filing captioning it differently) must not be blocked here
    # just because this narrow check can't confirm it.
    cash_label_ok = (not combined_page) or any(
        _label_directly_followed_by_number(bs_text, _fuzzy_label_re(n), after=r"\nCurrent Assets\b")
        for n in _CASH_LABELS)
    cash = None if not cash_label_ok else _scale(
        _find_cash_row(bs_text, _CASH_LABELS, after=r"\nCurrent Assets\b", words=bs_words), bs_factor)
    # Other Bank Balances - kept SEPARATE from `cash` on purpose (see
    # _OTHER_BANK_BALANCES_LABELS comment). Restricted/unrestricted split is
    # rebuilt deterministically via `_other_bank_balances_unrestricted`
    # (Base -> Net-off -> Optional-Add) rather than left to AI judgement.
    other_bank_balances = _scale(_find_row_values(bs_text, _OTHER_BANK_BALANCES_LABELS,
                                                   after=r"\nCurrent Assets\b", words=bs_words), bs_factor)
    other_bank_balances_breakup = _other_bank_balances_unrestricted(
        bs_text, _OTHER_BANK_BALANCES_LABELS, after=r"\nCurrent Assets\b")
    if other_bank_balances_breakup is not None and bs_factor != 1.0:
        for k in ("base_cur", "base_prior", "netoff_cur", "netoff_prior",
                  "unrestricted_cur", "unrestricted_prior"):
            if other_bank_balances_breakup.get(k) is not None:
                other_bank_balances_breakup[k] = round(other_bank_balances_breakup[k] * bs_factor, 2)
    # Trade Payables sits under Current Liabilities (Equity & Liabilities
    # side). Some filings print Assets and Equity-and-Liabilities as two
    # separate pages of the same statement (seen on Tata Steel) - the page
    # `bs_idx` was located via (Inventories + Assets markers) may not carry
    # Current Liabilities at all, so also try the immediately following page.
    # Whichever page payables is actually found on determines its own unit
    # factor (usually the same as the primary BS page, but detected fresh in
    # case a filing switches units - unlikely but cheap to guard against).
    payables_raw = _find_payables(bs_text, after=r"\nCurrent Liabilities\b")
    payables_factor = bs_factor
    if payables_raw is None and bs_idx + 1 < doc.page_count:
        try:
            next_text = _page_text(doc[bs_idx + 1])
            payables_raw = _find_payables(next_text, after=r"\nCurrent Liabilities\b")
            payables_factor = _unit_factor(next_text)
        except Exception:
            pass
    payables = _scale(payables_raw, payables_factor)

    def _strip_formula_refs(text):
        """Subtotal P&L lines are often annotated with a Roman-numeral
        formula reference right after the label - e.g. "Profit for the year
        (VII - VIII)". The " - " inside that parenthetical is a SUBTRACTION
        sign, not the "-" placeholder `_NUM_RE` uses for a nil/blank cell -
        but `_NUM_RE` can't tell the difference, and matching it as a stray
        "nil" value shifts every real number one slot to the right (current
        year reads as 0, prior year reads as what should have been current).
        Stripping these formula references before searching for numbers
        avoids that misread; they never carry real data themselves.

        ALSO normalises the "Profit/(loss)" caption qualifier down to plain
        "Profit" - many large/diversified filings (e.g. Tata Steel) caption
        every P&L subtotal as "Profit/(loss) before tax" / "Profit/(loss)
        for the year" rather than a plain "Profit before tax"/"Profit for
        the year", to cover both a profit or a loss outcome. Every label in
        `_PBT_LABELS`/`_PAT_OWNERS_LABELS`/`_PAT_GENERIC_LABELS` only ever
        expected the plain wording - the literal "/(loss)" infix broke the
        substring match entirely, a real bug (not a genuinely missing row)
        that silently produced 'Could not find Profit before tax/for the
        year' on any filing using this extremely common caption style.

        The formula-reference parenthetical itself also uses "=" as a
        separator, not just "+"/"-" (e.g. Eternal/Zomato: "(IX= VII-VIII)",
        "(VII= V-VI)") - the original pattern only recognised "+"/"-"
        between the Roman-numeral groups, so parentheticals using "="
        survived stripping and were then mistaken by the line-based reader
        for the row's own "current year" value (since it's the first
        non-blank line after the label, but isn't a pure digit token
        either) - silently producing 0.0 for both years instead of the
        real PBT/PAT figures."""
        text = re.sub(r"profit\s*/\s*\(\s*loss\s*\)", "profit", text, flags=re.I)
        return re.sub(r"\([IVXLCM]+(?:\s*[+\-=]\s*[IVXLCM]+)+\)", "", text, flags=re.I)

    def _find_single_label_loose(segment, label, max_skip=2, words=None):
        """Find ONE label's (current, prior) pair in `segment`, tolerating a
        BARE 1-4 digit value with no comma/decimal (e.g. "331") that `_NUM_RE`
        deliberately never matches - that pattern is indistinguishable from a
        Note-number/Page-number column by regex alone, and sacrifices genuine
        small values to avoid grabbing those. Critically, this ISN'T a
        "no match found" case (which `_find_row_values`'s fallback-on-None
        handles) - the regex scan still finds A match, just the WRONG one (it
        skips past "331" straight to the next label's comma-formatted number,
        e.g. "2,082"), so a bare `is None` check never catches it. Real
        financial-statement rows are laid out one token per line though
        (Label / Note# / Page#(-range) / Current / Prior), so this goes
        straight to a line-based read - skip leading pure digit/digit-range
        tokens (note + page columns), then parse the next two lines directly
        via `_parse_num` (which itself handles bare integers fine; only the
        REGEX used to locate candidates was the problem).

        `max_skip` BOUNDS how many leading tokens can be treated as
        metadata (Note#, Page#) rather than real data - needed because a
        genuinely small bare-integer VALUE (e.g. Eternal/Zomato's PAT of
        "527") is textually indistinguishable from a note-number token, so
        an unbounded skip silently ate the real current/prior values
        themselves whenever a P&L subtotal row happened to have NO Note/Page
        metadata directly after it (unlike Balance Sheet rows, which almost
        always do) - the Borrowings use-case this was built for has at most
        2 metadata tokens (Note#, Page#), so callers with no such metadata
        (e.g. `_find_pl_row`) must pass `max_skip=0`."""
        m = re.search(_fuzzy_label_re(label), segment, re.I)
        if not m:
            return None
        window = segment[m.end():m.end() + 250]
        lines = [ln.strip() for ln in window.split("\n") if ln.strip()]
        i = 0
        while i < len(lines) and i < max_skip and re.fullmatch(r"\d{1,4}(-\d{1,4})?", lines[i]):
            i += 1
        # a second reference column ("Notes | Page No."): a bare integer directly in front of TWO comma/decimal figures is a page
        # number, not the current-year value (Maruti "Finance costs 26 433 1,942 1,936" read 433)
        while (i + 2 < len(lines) and re.fullmatch(r"\d{1,4}(-\d{1,4})?", lines[i])
               and re.fullmatch(_NUM_RE, lines[i + 1]) and re.fullmatch(_NUM_RE, lines[i + 2])):
            i += 1
        if i + 1 < len(lines):
            a, b = _parse_num(lines[i]), _parse_num(lines[i + 1])
            if a is not None and b is not None:
                _yr = re.compile(r"(?:19|20)\d\d")
                _tiny = re.compile(r"\d{1,2}")
                if (_yr.fullmatch(lines[i + 1]) and _tiny.fullmatch(lines[i])) or (_yr.fullmatch(lines[i]) and _tiny.fullmatch(lines[i + 1])):
                    return _find_row_values(segment, [label], words=words)        # a note number next to a year, not two amounts
                return (a, b)
        return _find_row_values(segment, [label], words=words)

    def _find_pl_row(labels, after=None, max_skip=0):
        """Find a P&L row on the primary pl_text page, falling back to the
        immediately following page - the bottom-line Profit figure often sits
        on a SECOND page of the same statement (Revenue/expenses down to
        Profit Before Tax on page 1, Profit For The Year + OCI + EPS on page
        2), unlike the COGS/Revenue rows which are always on page 1.

        Uses `_find_single_label_loose` per label (line-based: skip leading
        Note/Page-number tokens, then read the next two lines directly via
        `_parse_num`) rather than a flat regex scan over the raw window -
        `_NUM_RE` deliberately never matches a bare 1-4 digit value with no
        comma/decimal (indistinguishable from a Note/Page column by regex
        alone), which silently broke PBT/PAT on any filing reporting whole
        crores under 1000 with no decimals (confirmed on Eternal/Zomato:
        697/291/527/351 are all bare integers - the regex scan skipped past
        them straight to the next visible token, a lone "-" placeholder from
        the following "Exceptional items: -, -" line, giving a bogus (0.0,
        0.0) instead of failing cleanly or finding the real values).

        `max_skip` defaults to 0 (right for PBT/PAT/Tax Expense - computed
        SUBTOTAL rows that carry no Note-number column of their own). A real
        P&L LINE ITEM like Finance Costs DOES have its own Note reference
        printed right after the label (e.g. HUL's "Finance costs \n 33 \n
        410 \n 381") - at max_skip=0 that note number ("33") was silently
        read as the CURRENT-YEAR value and the real 410/381 pair discarded
        entirely (confirmed on HUL: finance_costs came back as (33.0, 410.0)
        instead of (410.0, 381.0), corrupting Interest Coverage Ratio's
        denominator). Callers for genuine line items must pass max_skip>=1."""
        def _try(text, page_words=None):
            search_text = text
            if after:
                m = re.search(after, text, re.I)
                if m:
                    search_text = text[m.end():]
            for label in labels:
                r = _find_single_label_loose(search_text, label, max_skip=max_skip, words=page_words)
                if r is not None:
                    return r
            return None

        raw = _try(_strip_formula_refs(pl_text), pl_words)
        factor = pl_factor
        if raw is None and pl_idx + 1 < doc.page_count:
            try:
                next_text = _strip_formula_refs(_page_text(doc[pl_idx + 1]))
                raw = _try(next_text)
                factor = _unit_factor(next_text)
            except Exception:
                pass
        return _scale(raw, factor)

    def _find_tax_expense():
        """Total Tax Expense (Sr No 42/43's Effective Tax Rate component).

        Two DIFFERENT sign conventions exist across filers for the
        Current/Deferred tax sub-lines under a bare "Tax expense(s)" header
        (confirmed on both):
          - TCS: Current tax printed POSITIVE (16,910), Deferred tax as a
            signed adjustment (376) [a credit], PLUS an explicit "TOTAL TAX
            EXPENSE" line (16,534) that is already correctly signed.
          - HUL: no explicit Total line at all - Current tax AND Deferred
            tax both printed in the PROFIT-WALK convention (parenthesized =
            subtracted from Profit Before Tax), e.g. "Current tax (3,163)"
            + "Deferred tax credit/(charge) 3" -> PBT 13,812 - 3,163 + 3 =
            Profit for the year 10,652 - their SUM is negative, needing a
            sign flip to get the positive expense magnitude NOPAT expects.

        Naively matching "tax expense" (a substring of both filers' bare
        header) and reading only the FIRST trailing number grabs just
        Current tax with whatever sign it happens to carry, silently
        breaking the Effective Tax Rate (HUL) or missing the cleaner
        explicit Total line already available (TCS).

        Fixed by: (1) preferring an explicit "total tax expense" line when
        one is printed - trusted as-is, since a filer's own Total line is
        always correctly signed; (2) only when no such line exists, summing
        the Current + Deferred sub-lines (skipping the note-reference token,
        e.g. "9A", between each label and its figures - mirrors
        `_find_single_label_loose`'s skip logic, but restarts from the next
        full line since "Deferred tax credit / (charge)" has trailing
        caption text on the SAME line as the label) and normalising the
        result to positive (a negative sum only ever means the profit-walk
        convention was in play, never a genuine net tax credit at this
        pipeline's guarded PBT > 0)."""
        def _sub_line(window, label):
            m = re.search(_fuzzy_label_re(label), window, re.I)
            if not m:
                return None
            nl = window.find("\n", m.end())
            start = nl + 1 if nl != -1 else m.end()
            lines = [ln.strip() for ln in window[start:start + 150].split("\n") if ln.strip()]
            # max_skip=1, not 2: unlike Borrowings (Note# + Page# both
            # possible), only ONE note-reference token ever sits between a
            # Current/Deferred tax label and its two figures here - skipping
            # 2 would misread a genuinely tiny bare-digit VALUE (e.g.
            # Deferred tax of "3") as a second metadata token instead of the
            # real current-year figure (confirmed on HUL FY26). The pattern
            # covers BOTH note-numbering styles seen in practice: a bare
            # int+letter ("9A", HUL) and a dotted decimal ("2.17", Infosys)
            # - without the dotted-decimal branch, "2.17" reads as the real
            # current-year value instead of a note ref, shifting every
            # subsequent figure one slot and corrupting the sum (confirmed
            # on Infosys: silently produced a ~0% effective tax rate).
            i = 0
            while i < len(lines) and i < 1 and re.fullmatch(r"\d{1,3}(\.\d{1,3})?[A-Za-z]?", lines[i]):
                i += 1
            if i + 1 < len(lines):
                a, b = _parse_num(lines[i]), _parse_num(lines[i + 1])
                if a is not None and b is not None:
                    return (a, b)
            return None

        def _try(text, page_words=None):
            for lbl in ("total tax expense", "total tax expenses",
                        "tax expense/(credit)", "total tax expense/(credit)"):
                total = _find_single_label_loose(text, lbl, max_skip=0, words=page_words)
                if total is not None:
                    return total

            m = re.search(r"tax\s*expenses?\b", text, re.I)
            if not m:
                return None
            window = text[m.end():m.end() + 400]
            cur = _sub_line(window, "current tax")
            dfd = _sub_line(window, "deferred tax")
            if cur is not None or dfd is not None:
                cur = cur or (0.0, 0.0)
                dfd = dfd or (0.0, 0.0)
                total_cur, total_prior = cur[0] + dfd[0], cur[1] + dfd[1]
                if total_cur < 0:
                    total_cur, total_prior = -total_cur, -total_prior
                return (total_cur, total_prior)
            # No Current/Deferred sub-lines and no Total line either --
            # last resort: read the first two numbers directly after the
            # bare header.
            nums = _row_nums(window)
            if len(nums) >= 2:
                a, b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None and b is not None:
                    return (a, b)
            return None

        raw = _try(_strip_formula_refs(pl_text), pl_words)
        factor = pl_factor
        if raw is None and pl_idx + 1 < doc.page_count:
            try:
                next_text = _strip_formula_refs(_page_text(doc[pl_idx + 1]))
                raw = _try(next_text)
                factor = _unit_factor(next_text)
            except Exception:
                pass
        if raw is not None:
            return _scale(raw, factor)
        return _find_pl_row(_TAX_EXPENSE_LABELS)

    # Net Profit (Sr No 16 numerator): owners-attributable portion tried
    # first (consolidated statements often ALSO print a "Total profit for
    # the year" including Non-Controlling Interest just above/below it - per
    # spec we must never use that combined figure); falls back to the
    # generic "Profit for the year" labels for standalone reports with no
    # NCI split, where that IS the owners' figure.
    pat = _find_pl_row(_PAT_OWNERS_LABELS)
    pat_basis = "owners" if pat is not None else None
    if pat is None:
        pat = _find_pl_row(_PAT_GENERIC_LABELS)
        pat_basis = "generic" if pat is not None else None

    # EBIT approximation (Sr No 19 numerator) = Profit Before Tax + Finance
    # Costs. Both are single, unambiguous P&L lines - no owners/NCI split
    # concern like PAT (PBT is struck before the profit is even attributed).
    pbt = _find_pl_row(_PBT_LABELS)
    finance_costs = _find_pl_row(_FINANCE_COST_LABELS, max_skip=1)
    tax_expense = _find_tax_expense()
    # Basic EPS (Sr No 24 denominator) - same page-fallback as PAT/PBT/OCI,
    # since the "Earnings per equity share" line sits in the same bottom
    # section of the P&L statement. EPS is a per-share ₹ figure, NEVER a
    # ₹ Crore statement line - deliberately bypasses `_scale()`'s Crore/
    # Lakh/Million unit-factor normalisation (that factor is derived from
    # the page's aggregate-figures unit note, e.g. "₹ in Crore", and would
    # wrongly multiply/divide a per-share rupee value by 10 million).
    eps_raw = _find_eps_row(pl_text)
    if eps_raw is None and pl_idx + 1 < doc.page_count:
        try:
            eps_raw = _find_eps_row(_page_text(doc[pl_idx + 1]))
        except Exception:
            pass
    eps = eps_raw
    eps_owners = _find_eps_owners_row(pl_text)
    if eps_owners is None and pl_idx + 1 < doc.page_count:
        try:
            eps_owners = _find_eps_owners_row(_page_text(doc[pl_idx + 1]))
        except Exception:
            pass

    # Number of Equity Shares Outstanding (Sr No 25 denominator component) -
    # lives in a Notes-to-Accounts page far from bs_idx, so this is a
    # dedicated forward scan (see _find_shares_outstanding's own docstring).
    shares_outstanding = _find_shares_outstanding(doc, bs_idx, want)
    # Owners' PAT from the statement's own attribution split when the generic label picked the whole-entity profit: the row
    # "Owners of the Company X / Non-controlling interest Y" under "Profit for the year attributable to" is the owners' figure
    # (Reliance, L&T: the whole-entity 81,309 / 17,673 was being used as owners' profit). First such row on the P&L page =
    # the profit split (the OCI / total-comprehensive splits follow it).
    _pat_total_from_split = None
    if pat is not None and pat_basis != "owners":
        try:
            from tools.bank_extractor import rows_of as _rows_of, _norm as _bnorm
            _pl_f = _unit_factor(_page_text(doc[pl_idx]))
            _hit = None
            for _pj in (pl_idx, pl_idx + 1):
                if _pj >= doc.page_count or _hit is not None:
                    continue
                for _lab, _nums in _rows_of(doc[_pj]):
                    _n = _bnorm(_lab)
                    if len(_nums) >= 2 and re.search(r"owners of the (?:company|parent)|equity holders of the (?:company|parent)", _n)                             and "comprehensive" not in _n:
                        _hit = _nums
                        break
            if _hit is not None:
                _o = (round(_hit[0] * _pl_f, 2), round(_hit[1] * _pl_f, 2))
                if 0.3 * abs(pat[0]) <= abs(_o[0]) <= 1.0001 * abs(pat[0]) and _o[0] != pat[0]:
                    _pat_total_from_split = pat
                    pat, pat_basis = _o, "owners"
        except Exception as _e:
            print(f"[annual_report_financials] owners attribution row skipped: {_e}")
    # Owners' PAT is validated/repaired against the statement's own totals and EPS x shares (see helper).
    try:
        _eps_for_check = eps_owners or eps
        pat, pat_basis, _pat_repaired, _pat_total_pair = _repair_owners_pat(
            pat, pat_basis, _strip_formula_refs(pl_text), pl_factor, _eps_for_check, shares_outstanding)
    except Exception:
        _pat_repaired, _pat_total_pair = False, None
    if _pat_total_pair is None and _pat_total_from_split is not None:
        _pat_total_pair = _pat_total_from_split
    if _pat_total_pair is None and pat is not None and pat_basis == "owners":
        # whole-entity profit (owners + NCI) printed as its own row (e.g. "PROFIT AFTER TAX 3,709.71 5,557.69" above the
        # "attributable to: owners / NCI" split). Accepted only when it is consistent with the owners' figure.
        try:
            from tools.bank_extractor import rows_of as _rows_of, _norm as _bnorm
            _pl_factor = _unit_factor(_page_text(doc[pl_idx]))
            for _lab, _nums in _rows_of(doc[pl_idx]):
                if len(_nums) >= 2 and re.fullmatch(r"profit after tax|profit for the (?:year|period)|net profit for the (?:year|period)|"
                                                    r"profit for the year from continuing operations", _bnorm(_lab)):
                    _tot = (round(_nums[0] * _pl_factor, 2), round(_nums[1] * _pl_factor, 2))
                    if abs(_tot[0] - pat[0]) <= 0.5 * max(abs(pat[0]), 1.0) and _tot[0] != pat[0]:
                        _pat_total_pair = _tot
                        break
            if _pat_total_pair is None:
                # side-by-side layouts print the total only as an unlabelled figure; the statement's own attribution split is
                # "Owners of the Company X / Non-controlling interest Y" - total = X + Y (the first split on the page is the profit)
                _own = _nci_p = None
                for _lab, _nums in _rows_of(doc[pl_idx]):
                    _n = _bnorm(_lab)
                    if len(_nums) >= 2 and _nci_p is None and re.search(r"non.?controlling interests?", _n) and _own is not None:
                        _nci_p = _nums
                    if len(_nums) >= 2 and _own is None and re.search(r"owners of the (?:company|parent)", _n):
                        _own = _nums
                if _own is not None and _nci_p is not None and abs(_own[0] - pat[0]) < 0.01 * max(abs(pat[0]), 1.0):
                    _pat_total_pair = (round((_own[0] + _nci_p[0]) * _pl_factor, 2), round((_own[1] + _nci_p[1]) * _pl_factor, 2))
        except Exception as _e:
            print(f"[annual_report_financials] whole-entity profit row skipped: {_e}")

    # Net Operating Cash Flow (Sr No 35 numerator), Capex components (Sr No
    # 36 denominator), and Repayment of Borrowings/Lease Liabilities (Sr No
    # 34 denominator components) - all from the Cash Flow Statement (see
    # _find_cash_flow_statement_items's own docstring).
    cf_items = _find_cash_flow_statement_items(doc, bs_idx, want)

    # Dividend per Share (Sr No 27 numerator) - ALWAYS standalone (see
    # `_find_dividend_per_share`'s docstring), scanned from page 0 since
    # Standalone statements always precede Consolidated ones in the Ind AS
    # filing template, regardless of which section THIS extraction (`want`)
    # was requested for.
    dividend_per_share, dividend_found = _find_dividend_per_share(doc, 0)

    def _find_bs_row(labels, after=None, subtotal_before=None, reject_after=None, permissive=False):
        """Find a Balance Sheet row on the primary bs_text page, falling back
        to the immediately following page (Assets/Equity-and-Liabilities are
        sometimes split across two pages of the same statement - seen on
        Tata Steel), each normalised to ₹ Cr with its OWN detected unit. If
        `subtotal_before` is given and the labelled search fails on a page,
        also tries reading the BARE number pair immediately preceding that
        marker on the same page (some filings, e.g. Asian Paints, print the
        Current Assets/Liabilities subtotal with no label of its own).

        The NEXT page is skipped if it's a Cash Flow Statement - that
        statement carries its own "(increase)/decrease"-style ADJUSTMENT
        lines with the SAME labels a genuine BS row would use (e.g. "Short
        term borrowings (Net)" as a financing-activities cash-flow line, a
        completely different, wrong-basis, sign-flipped figure from the
        actual Balance Sheet closing balance) - seen on MARUTI, where the BS
        is immediately followed by the Cash Flow Statement and a naive
        next-page read grabbed a negative cash-flow adjustment instead of the
        real (positive, or genuinely absent) Balance Sheet borrowings figure."""
        def _try(text, page_words=None):
            v = _find_row_values(text, labels, after=after, reject_after=reject_after,
                                  permissive=permissive, words=page_words)
            if v is None and subtotal_before:
                v = _find_subtotal_before(text, subtotal_before, after=after)
            return v
        raw = _try(bs_text, bs_words)
        factor = bs_factor
        if raw is None and bs_idx + 1 < doc.page_count:
            try:
                next_text = _page_text(doc[bs_idx + 1])
                if "cash flow" in next_text.lower()[:200]:
                    return None
                raw = _try(next_text)
                factor = _unit_factor(next_text)
            except Exception:
                pass
        return _scale(raw, factor)

    def _bounded_segment(text, start_after, stop_before):
        """Slices `text` to the region between two section markers, or None
        if `start_after` isn't found on this page at all."""
        m1 = re.search(start_after, text, re.I)
        if not m1:
            return None
        segment = text[m1.end():]
        m2 = re.search(stop_before, segment, re.I)
        if m2:
            segment = segment[:m2.start()]
        return segment


    def _find_bs_row_bounded(labels, start_after, stop_before):
        """Like `_find_bs_row`, but restricted to the text BETWEEN two section
        markers - needed for a generically-labeled row like plain
        "Borrowings" that appears under BOTH "Non-current Liabilities" and
        "Current Liabilities" sections with the SAME label text (only the
        section heading distinguishes long-term from short-term). Without an
        upper bound, searching "after Non-current Liabilities" for a company
        with NO non-current borrowings (e.g. MARUTI) would run straight past
        the empty Non-current section and wrongly grab the Current section's
        entry instead, mislabelling short-term debt as long-term. Also tries
        the immediately FOLLOWING page (skipping Cash Flow Statement pages,
        same as `_find_bs_row`) - the Balance Sheet's Equity & Liabilities
        side, where Borrowings sits, is sometimes a "(CONTD.)" continuation
        page (seen on Tata Steel).

        Also tries the spatial (row-position) fallback, BOUNDED by the same
        two section markers via `_find_row_values_spatial`'s `after`/`before`
        - needed for combined-page layouts (Gopal Snacks FY25) where the
        section markers and the "Borrowings" row sit far apart in linear
        text order but are a well-formed table row spatially."""
        segment = _bounded_segment(bs_text, start_after, stop_before)
        raw = None
        if segment:
            # FIRST the bounded, note-reference-aware row reader (the one that fixed Lease Liabilities): a
            # borrowings row whose real figures are small bare numbers ("Borrowings 23 1 13") was previously
            # skipped by the strict number matcher, which then fell through to the NEXT comma-formatted
            # numbers on the page (HUL: Trade Payables 11,052 read as short-term borrowings).
            try:
                raw, _ = _find_payables_row(
                    segment, re.escape(labels[0]).replace(r"\ ", r"\s+") + r"\b",
                    r"lease\s+liabilit|trade\s+payables|other\s+financial|other\s+(?:non-?)?current|provisions|"
                    r"deferred\s+tax|current\s+tax|income\s+tax|\n\s*total\b|\n\s*contract\s+liabilit",
                    three_column=bs_three_column)
            except Exception:
                raw = None
            if raw is None:
                raw = _find_single_label_loose(segment, labels[0])
        factor = bs_factor
        if raw is None and bs_idx + 1 < doc.page_count:
            try:
                next_text = _page_text(doc[bs_idx + 1])
                if "cash flow" not in next_text.lower()[:200]:
                    next_segment = _bounded_segment(next_text, start_after, stop_before)
                    if next_segment:
                        raw = _find_single_label_loose(next_segment, labels[0])
                        factor = _unit_factor(next_text)
            except Exception:
                pass
        if raw is None and bs_words:
            raw = _find_row_values_spatial(bs_words, labels, permissive=True,
                                            after=start_after, before=stop_before)
        return _scale(raw, factor)

    # Total Assets is the Balance Sheet's own closing subtotal (the last line
    # of the Assets side).
    total_assets = _find_bs_row(_TOTAL_ASSETS_LABELS)
    # Total Current Assets / Total Current Liabilities - the two subtotals
    # Working Capital (Sr No 13/26) is built from: Working Capital = Total
    # Current Assets − Total Current Liabilities. Fall back to the bare
    # number pair before TOTAL ASSETS / TOTAL EQUITY AND LIABILITIES when
    # there's no explicit "Total current assets/liabilities" label.
    total_current_assets = _find_bs_row(_TOTAL_CURRENT_ASSETS_LABELS, after=r"\nCurrent Assets\b",
                                         subtotal_before="total assets")
    # On some combined BS+P&L pages, "Total Current liabilities" is followed
    # by MORE subtotal labels ("Total Liabilities", "Total Equity and
    # Liabilities") and a column of note-reference numbers before its own
    # real figures appear far away - confirmed on Gopal Snacks FY25 (the
    # text-window scan then quietly returns some OTHER row's numbers, and
    # the spatial fallback is ALSO unreliable for this specific row despite
    # working correctly for Total Assets/Total Current Assets on the same
    # page - not yet root-caused). Verify the label is genuinely followed by
    # a number first - force N/A rather than risk a silently ~10x-wrong
    # Current/Quick/Cash Ratio.
    #
    # CRITICAL: only apply this suspicion check on a `combined_page` (the
    # confirmed-bad scenario) - some filers (e.g. HUL) never print an
    # explicit "Total Current Liabilities" LABEL at all and rely entirely
    # on `_find_bs_row`'s own `subtotal_before` bare-number-pair fallback
    # (the figure sits unlabelled directly above "Total Equity and
    # Liabilities"). `_label_directly_followed_by_number` only checks for a
    # number after the LABEL text, so on a filing with no such label it
    # always returns False - applying this guard unconditionally wrongly
    # blocked a perfectly good extraction on every ordinary (non-combined-
    # page) filing that uses the label-less bare-subtotal convention,
    # regressing Sr No 39 (Operating Cash Flow Ratio, which reads this
    # field directly) among others. Confirmed: HUL has no "total current
    # liabilities" text anywhere on its Balance Sheet page at all.
    tcl_label_ok = (not combined_page) or any(
        _label_directly_followed_by_number(bs_text, _fuzzy_label_re(n), after=r"\nCurrent Liabilities\b")
        for n in _TOTAL_CURRENT_LIABILITIES_LABELS)
    total_current_liabilities = None if not tcl_label_ok else _find_bs_row(
        _TOTAL_CURRENT_LIABILITIES_LABELS, after=r"\nCurrent Liabilities\b",
        subtotal_before=["total liabilities", "total equity and liabilities"])

    # Net Fixed Assets (Sr No 30 denominator).
    net_fixed_assets = _find_bs_row(_NET_FIXED_ASSETS_LABELS)
    # Components of the Navrist Net Fixed Assets policy (PPE + ROU assets +
    # Capital WIP + Intangibles, excluding goodwill) and the other balance-
    # sheet rows the ratio contract consumes.
    ppe_row = net_fixed_assets
    rou_row = _find_bs_row(["right-of-use assets", "right of use assets", "right-of-use asset", "rights-of-use assets"])
    cwip_row = _find_bs_row(["capital work-in-progress", "capital work in progress"])
    intangibles_row = _find_bs_row(["other intangible assets", "intangible assets"])
    goodwill_row = _find_bs_row(["goodwill on consolidation", "goodwill"])
    total_liabilities_row = _find_bs_row(["total liabilities"])
    _bs_low = bs_text.lower()
    lease_evidence = ("none_on_balance_sheet" if ("lease" not in _bs_low and "right-of-use" not in _bs_low
                                                    and "right of use" not in _bs_low) else "unparsed")

    # MANUAL-UPLOAD WORKFLOW ONLY - see `_find_payables_row`'s `three_column`
    # doc and `_bs_grand_total_is_three_column`. Computed once, here, and
    # reused below AND by the Lease Liabilities extraction further down (
    # `bs_three_column`) - never recomputed with different results for the
    # same page.
    bs_three_column = _bs_grand_total_is_three_column(bs_text)

    # Total Equity (Sr No 18 denominator): owners-attributable portion.
    # Preferred path: sum Equity Share Capital + Other Equity directly - both
    # are ALWAYS the parent/owners' portion under Ind AS (Non-Controlling
    # Interest is always its own separate line, never blended into either),
    # so this is correct regardless of how (or whether) the filer prints an
    # explicit "Total Equity" subtotal at all.
    # "Equity share capital" is looked up with the same bounded, note-
    # reference-tolerant helper written for the Payables MSME fix (a plain
    # `permissive` number match alone would grab the note-reference digit
    # printed between the label and the real figures, e.g. "...capital \n 17
    # \n 235 \n 235" - taking the LAST two numbers before the next row's
    # label avoids that regardless of whether a reference digit is present).
    # `three_column=bs_three_column`: MANUAL-UPLOAD ONLY, same fix as Lease
    # Liabilities - an Ind AS first-time adopter's Equity Share Capital row
    # also has 3 trailing numbers (current, prior, opening), and taking the
    # last two silently returns (prior, opening) as if it were (current,
    # prior). Also, unlike `_find_bs_row`, `_find_payables_row` does NOT
    # normalise its result to ₹ Cr on its own - confirmed real gap: this raw
    # ₹-Lakh Equity Share Capital figure was being added directly to
    # `other_equity_amt` (which DOES go through `_find_bs_row`'s own
    # `_scale()` call), silently mixing units and inflating Total Equity
    # ~100x above the real figure on Prime Fresh Limited/LANDMARKACHIEVE's
    # FY26 filing, which corrupted Financial Leverage Ratio (Sr No 23), ROE,
    # Debt-to-Equity, and BVPS alike. `_scale(..., bs_factor)` applied here
    # only under `is_manual_mode()`, matching the scope of every other fix
    # in this session - the automatic/live pipeline's behaviour is
    # unchanged.
    equity_share_capital, _ = _find_payables_row(bs_text, r"equity\s+share\s+capital", r"other\s+equity",
                                                   three_column=bs_three_column)
    equity_share_capital = _scale(equity_share_capital, bs_factor)
    other_equity_amt = _find_bs_row(_OTHER_EQUITY_LABELS)
    if equity_share_capital is not None and other_equity_amt is not None:
        equity = (round(equity_share_capital[0] + other_equity_amt[0], 2),
                  round(equity_share_capital[1] + other_equity_amt[1], 2))
        equity_basis = "owners"
    else:
        # Fall back to an explicit "...attributable to owners..." label,
        # then a generic "Total Equity"/"Shareholders' Funds" label - the
        # latter REJECTS a match immediately followed by "and liabilities",
        # since "total equity" is a literal substring of "TOTAL EQUITY AND
        # LIABILITIES" (the whole Balance Sheet grand total, not equity at
        # all - confirmed silently happening on HUL, whose actual equity
        # subtotal is phrased "Total - Equity (A)" and so never matched the
        # bare "total equity" search to begin with).
        equity = _find_bs_row(_EQUITY_OWNERS_LABELS)
        equity_basis = "owners" if equity is not None else None
        if equity is None:
            equity = _find_bs_row(_EQUITY_GENERIC_LABELS, reject_after=r"\s*and\s+liabilities")
            equity_basis = "generic" if equity is not None else None

    # Total Equity, WHOLE-entity (owners' + Non-Controlling Interest) - Sr
    # No 23 Debt-to-Equity's denominator (see `_NCI_LABELS` comment above).
    # NCI is genuinely absent (real ₹0, standalone company or no minority
    # shareholders) whenever its label isn't found at all - `equity_full`
    # then correctly reduces to the same owners-only figure as `equity`.
    # Same note-reference-digit hazard as Equity Share Capital/Lease
    # Liabilities above (NCI is routinely a small, comma-less figure with a
    # note number printed right after its label) - reuses the same
    # last-two-numbers-before-the-next-label helper rather than a blind
    # permissive first-two match.
    # Some filers (e.g. Tata Steel) print Assets and Equity-and-Liabilities
    # as two SEPARATE pages of the same statement - `bs_text` here is
    # whichever page the module located the BS on (confirmed on Tata Steel:
    # the Assets-only page, with Equity/NCI actually one page later), so a
    # search restricted to `bs_text` alone silently finds nothing. Falls
    # back to the immediately following page, same as `_find_bs_row`'s own
    # cross-page fallback (which is how `equity` above still resolves
    # correctly even when `bs_text` itself has no Equity section at all).
    nci_amt = None
    if equity_basis == "owners":
        nci_search_pages = [(bs_text, bs_factor)]
        if bs_idx + 1 < doc.page_count:
            try:
                next_text = _page_text(doc[bs_idx + 1])
                nci_search_pages.append((next_text, _unit_factor(next_text)))
            except Exception:
                pass
        # Row-structured read first: the label and its two figures are taken from the SAME printed row (word coordinates),
        # so an unlabelled "Total equity" subtotal printed directly under the NCI row can never be mistaken for it
        # (Asian Paints: NCI 659.24 was read as the 20,059.05 subtotal beneath it).
        try:
            from tools.bank_extractor import rows_of as _rows_of, find_row as _find_row, _norm as _bnorm
            for _pi in (bs_idx, bs_idx + 1):
                if _pi >= doc.page_count or nci_amt is not None:
                    continue
                _ptxt = _page_text(doc[_pi])
                _rows = _rows_of(doc[_pi])
                for _lab, _nums in _rows:
                    if len(_nums) >= 2 and re.search(r"non.?controlling interests?|minority interests?", _bnorm(_lab))                             and not re.search(r"total|equity attributable", _bnorm(_lab)):
                        _pair = (_nums[0], _nums[1])
                        # four interleaved figures "NCI(cur) Total-equity(cur) NCI(prior) Total-equity(prior)": identified by the
                        # identity Owners' equity + NCI = Total equity, then NCI = columns 1 and 3
                        if len(_nums) >= 4 and equity is not None and abs(_nums[1] - (equity[0] + _nums[0])) <= 0.01 * abs(_nums[1]):
                            _pair = (_nums[0], _nums[2])
                        nci_amt = _scale(_pair, _unit_factor(_ptxt))
                        break
        except Exception as _e:
            print(f"[annual_report_financials] row-based NCI read skipped: {_e}")
        for page_text, page_factor in nci_search_pages:
            if nci_amt is not None:
                break
            for lbl in _NCI_LABELS:
                nci_raw, _ = _find_payables_row(
                    page_text, lbl, r"total\s*-?\s*equity|liabilities")
                if nci_raw is not None:
                    nci_amt = _scale(nci_raw, page_factor)
                    break
            if nci_amt is not None:
                break
    if equity is not None:
        if nci_amt is not None:
            equity_full = (round(equity[0] + nci_amt[0], 2),
                            round(equity[1] + (nci_amt[1] or 0), 2) if equity[1] is not None else None)
        else:
            equity_full = equity
    else:
        equity_full = None

    # Retained Earnings (Altman Z-Score Sr No 55's RE/TA component) --
    # literal "Reserves and Surplus" tried first (confidence 1.0, an exact
    # match); "Other Equity" (post-2019 Ind AS combined reserves line) used
    # as a fallback approximation (confidence 0.8 -- may include Securities
    # Premium/General Reserve alongside genuine retained profits, can't be
    # split further from face-value text).
    retained_earnings = _find_bs_row(_RETAINED_EARNINGS_LABELS)
    retained_earnings_basis = "exact" if retained_earnings is not None else None
    if retained_earnings is None:
        retained_earnings = _find_bs_row(_OTHER_EQUITY_LABELS)
        retained_earnings_basis = "other_equity_proxy" if retained_earnings is not None else None

    # Total Debt (Sr No 20 numerator): Long-term + Short-term Borrowings +
    # Current maturities of long-term debt. Each may be absent for a
    # genuinely debt-free company (a real ₹0, not missing data) - summed
    # individually rather than gated on all three being present.
    #
    # Many filings label the row just "Borrowings" (no "long-term"/"current"
    # prefix) since the Non-current-vs-Current split already comes from
    # which SECTION it sits under, not the label itself - tried as a
    # section-scoped fallback when the more specific label isn't found.
    # `permissive=True`: same reasoning as Cash and Cash Equivalents above -
    # Borrowings/Current Maturities are routinely small (sub-1,000, no
    # thousands separator) figures on smaller filers (confirmed on Gopal
    # Snacks: "5.73"/"36.65"), which the strict spatial-fallback number token
    # (`_NUM_TOKEN_RE`, requires a comma or 2+ integer digits before the
    # decimal) can't match at all - silently returning no value even though
    # the row is spatially well-formed. The permissive path's last-two-tokens
    # rule already exists specifically to skip a leading note-reference digit
    # (e.g. "18" before "5.73"/"36.65"), so this carries the same low risk
    # already accepted for Cash.
    lt_borrowings = _find_bs_row(_LT_BORROWINGS_LABELS, permissive=True)
    if lt_borrowings is None:
        lt_borrowings = _find_bs_row_bounded(["borrowings"], r"\nNon-current Liabilities\b", r"\nCurrent Liabilities\b")
    st_borrowings = _find_bs_row(_ST_BORROWINGS_LABELS, permissive=True)
    if st_borrowings is None:
        st_borrowings = _find_bs_row_bounded(["borrowings"], r"\nCurrent Liabilities\b", r"\nTotal Equity and Liabilities\b")
    current_maturities = _find_bs_row(_CURRENT_MATURITIES_LABELS, permissive=True)

    # Distinguishes "genuinely absent" (real ₹0 - a debt-free company) from
    # "extraction failure" (the label IS present on the face of the Balance
    # Sheet but its value pair couldn't be parsed) - a bare substring probe
    # across both liabilities sections, independent of whether the value-pair
    # read above succeeded. Used by `_compute_total_debt`'s hard Finance-Costs
    # cross-check so a parse failure is never silently reported as a
    # confident, debt-free "0".
    borrowings_face_label_found = bool(re.search(r"\bborrowings\b", bs_text, re.I))

    # Lease Liabilities (Total Debt Sr No 20 component b) - Non-current and
    # Current, section-scoped. Lease Liabilities is routinely a small
    # (sub-1,000, no thousands separator) figure with a note-reference digit
    # printed right after the label - e.g. HUL's Current Lease Liabilities
    # row is "Lease Liabilities \n 20 \n 374 \n 404" - the exact same shape
    # as the Equity Share Capital fix above, so it reuses that fix's helper
    # (`_find_payables_row`: permissive number matching + take the LAST two
    # numbers before the next row's label, which skips the note-ref digit
    # AND stays bounded so it can never reach into a later row). Plain
    # `_find_bs_row`'s strict `_NUM_RE` can't match "374"/"404" at all (no
    # comma, no 2-decimal suffix) and was silently falling through to the
    # NEXT comma-formatted numbers on the page - HUL's Trade Payables row
    # (12,867 / 11,052) - reporting someone else's trade payables as if they
    # were lease liabilities.
    # `bs_three_column` already computed once above (before the Equity
    # Share Capital extraction) and reused here - see that comment.
    lease_nc_anchor = re.search(r"\nNon-current Liabilities\b", bs_text, re.I)
    lease_liabilities_nc = None
    if lease_nc_anchor:
        lease_nc_row, _ = _find_payables_row(
            bs_text[lease_nc_anchor.end():], r"lease\s+liabilit(?:y|ies)",
            r"other\s+financial\s+liabilit|provisions|deferred\s+tax|\nCurrent Liabilities\b",
            three_column=bs_three_column)
        lease_liabilities_nc = _scale(lease_nc_row, bs_factor)
    if lease_liabilities_nc is None:
        lease_liabilities_nc = _find_bs_row_bounded(
            _LEASE_LIABILITY_NC_LABELS, r"\nNon-current Liabilities\b", r"\nCurrent Liabilities\b")
    lease_cur_anchor = re.search(r"\nCurrent Liabilities\b", bs_text, re.I)
    lease_liabilities_cur = None
    if lease_cur_anchor:
        lease_cur_row, _ = _find_payables_row(
            bs_text[lease_cur_anchor.end():], r"lease\s+liabilit(?:y|ies)",
            r"trade\s+payables|other\s+financial\s+liabilit|other\s+current\s+liabilit|provisions",
            three_column=bs_three_column)
        lease_liabilities_cur = _scale(lease_cur_row, bs_factor)
    if lease_liabilities_cur is None:
        lease_liabilities_cur = _find_bs_row_bounded(
            _LEASE_LIABILITY_CUR_LABELS, r"\nCurrent Liabilities\b", r"\nTotal Equity and Liabilities\b")

    # Other Financial Liabilities (Total Debt Sr No 20 component c) - Three-
    # Part Test applied separately to the Non-current and Current sections
    # (each may carry a different sub-item breakup).
    ofl_nc_segment = _bounded_segment(bs_text, r"\nNon-current Liabilities\b", r"\nCurrent Liabilities\b")
    ofl_cur_segment = _bounded_segment(bs_text, r"\nCurrent Liabilities\b", r"\nTotal Equity and Liabilities\b")
    other_fin_liab_nc = (_other_financial_liabilities_qualifying(ofl_nc_segment, _OTHER_FIN_LIAB_LABELS)
                          if ofl_nc_segment else None)
    other_fin_liab_cur = (_other_financial_liabilities_qualifying(ofl_cur_segment, _OTHER_FIN_LIAB_LABELS)
                           if ofl_cur_segment else None)
    if bs_factor != 1.0:
        for d in (other_fin_liab_nc, other_fin_liab_cur):
            if d is not None:
                for k in ("base_cur", "base_prior", "qualifying_cur", "qualifying_prior"):
                    if d.get(k) is not None:
                        d[k] = round(d[k] * bs_factor, 2)

    # Borrowings Note verification (Total Debt Sr No 20 component a) -
    # mandatory cross-check against the Notes-to-Accounts Borrowings
    # breakup, not the Balance Sheet face value alone. Scans forward from
    # the Balance Sheet page (Notes always follow the statements).
    try:
        borrowings_note = _find_borrowings_note_total(doc, bs_idx)
    except Exception:
        borrowings_note = None
    borrowings_note_total_cur, borrowings_note_subitems = (
        borrowings_note if borrowings_note is not None else (None, None))

    # Contribution Margin (Sr No 44) Variable Cost component beyond raw
    # materials - scans forward from the P&L page for the "Other Expenses"
    # Note breakup (see `_find_variable_opex_note`). Run for every company
    # regardless of pipeline (QA correction 2026-09-05 unified the
    # automatic live-fetch and manual document-upload methodologies).
    variable_opex_note = None
    try:
        variable_opex_note = _find_variable_opex_note(doc, pl_idx)
    except Exception:
        variable_opex_note = None

    # Same scan, but for a separate "Direct Expenses" Note - some trading/
    # services filers print operational costs (loading/unloading,
    # transportation, packing, ...) there instead of folding them into
    # "Other Expenses" (confirmed real on Prime Fresh Limited's FY26 AR).
    # Only the caption-matched sub-items are ever treated as variable -
    # never the Note's total, same discipline as the Other Expenses scan.
    variable_direct_expenses_note = None
    try:
        variable_direct_expenses_note = _find_variable_opex_note(doc, pl_idx, caption="direct expenses")
    except Exception:
        variable_direct_expenses_note = None

    return {
        "components": components,    # {label: (cur, prior)} - may be partial/empty, normalised to ₹ Cr
        "inventory": inv,            # (cur, prior) or None, normalised to ₹ Cr
        "revenue": revenue,          # (cur, prior) or None, normalised to ₹ Cr
        "receivables": receivables,  # (cur, prior) or None
        "payables": payables,        # (cur, prior) or None
        "cash": cash,                # (cur, prior) or None, normalised to ₹ Cr
        "other_bank_balances": other_bank_balances,  # (cur, prior) or None - line total, informational
        "other_bank_balances_breakup": other_bank_balances_breakup,  # dict or None - Base/Net-off/Optional-Add, see comment above
        "employee_benefit_expense": employee_benefit_expense,  # (cur, prior) or None, normalised to ₹ Cr
        "other_expenses": other_expenses,  # (cur, prior) or None, normalised to ₹ Cr
        "depreciation": depreciation,  # (cur, prior) or None, normalised to ₹ Cr
        "direct_expenses": direct_expenses,  # (cur, prior) or None, normalised to ₹ Cr - Sr No 15 manual-upload-only
        "total_expenses": total_expenses,  # (cur, prior) or None, normalised to ₹ Cr - Schedule III "Total Expenses (IV)"
        "pat": pat,  # (cur, prior) or None, normalised to ₹ Cr - owners-attributable Profit After Tax
        "pat_basis": pat_basis,  # "owners" (explicit attribution line found) or "generic" (no NCI split found)
        "pbt": pbt,  # (cur, prior) or None, normalised to ₹ Cr - Profit Before Tax
        "finance_costs": finance_costs,  # (cur, prior) or None, normalised to ₹ Cr
        "tax_expense": tax_expense,  # (cur, prior) or None, normalised to ₹ Cr - Sr No 42/43
        "eps": eps,  # (cur, prior) or None, ₹ per share (Basic) - NEVER Crore-scaled, unlike every other field here
        "shares_outstanding": shares_outstanding,  # (cur, prior) or None, raw share COUNT - NEVER Crore-scaled
        "borrowings_repayment": cf_items.get("borrowings_repayment"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 34
        "lease_repayment": cf_items.get("lease_repayment"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 34
        "interest_paid": cf_items.get("interest_paid"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 34, cash-basis (Cash Flow Statement)
        "lease_interest_paid": cf_items.get("lease_interest_paid"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 34
        "cf_page": cf_items.get("cf_page"),   # page of the Cash Flow Statement (provenance of every cash-flow fact)
        "operating_cash_flow": cf_items.get("operating_cash_flow"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 35
        "capex_ppe_purchase": cf_items.get("capex_ppe_purchase"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 36
        "capex_intangible_purchase": cf_items.get("capex_intangible_purchase"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 36
        "capex_disposal_proceeds": cf_items.get("capex_disposal_proceeds"),  # (cur, prior) or None, normalised to ₹ Cr - Sr No 36
        "dividend_paid": cf_items.get("dividend_paid"),  # (cur, prior) or None, normalised to ₹ Cr - C.7, cash-basis (Financing Activities)
        "buyback_spend": cf_items.get("buyback_spend"),  # (cur, prior) or None, normalised to ₹ Cr - C.7 (Financing Activities)
        "acquisition_outflow": cf_items.get("acquisition_outflow"),  # (cur, prior) or None, normalised to ₹ Cr - C.7 (Investing Activities, M&A)
        # DPS declared during the year, ALWAYS standalone-sourced. None - NEVER 0.0 - when no
        # disclosure was found: an extraction miss is not evidence of a zero dividend.
        "dividend_per_share": dividend_per_share if dividend_found else None,
        "dividend_per_share_found": dividend_found,
        # NCI was SEARCHED for only when an explicit owners'-equity line was found; in that case an absent
        # NCI row is a genuine nil (the owners/NCI split is printed), otherwise it is simply unknown.
        "non_controlling_interest": nci_amt, "nci_evaluated": equity_basis == "owners",
        "pat_total": _pat_total_pair,
        "eps_owners": eps_owners, "ppe": ppe_row, "rou_assets": rou_row, "cwip": cwip_row,
        "intangibles": intangibles_row, "goodwill": goodwill_row, "total_liabilities": total_liabilities_row,
        "dividend_paid": cf_items.get("dividend_paid"), "lease_evidence": lease_evidence,
        "lt_borrowings": lt_borrowings,  # (cur, prior) or None, normalised to ₹ Cr
        "st_borrowings": st_borrowings,  # (cur, prior) or None, normalised to ₹ Cr
        "current_maturities": current_maturities,  # (cur, prior) or None, normalised to ₹ Cr
        "borrowings_face_label_found": borrowings_face_label_found,  # bool - "Borrowings" text present on the BS face at all
        "borrowings_note_total_cur": borrowings_note_total_cur,  # ₹ Cr or None - independent Notes-breakup cross-check
        "borrowings_note_subitems": borrowings_note_subitems,  # int or None - how many Note sub-items were summed
        "lease_liabilities_nc": lease_liabilities_nc,  # (cur, prior) or None, normalised to ₹ Cr - Total Debt component b
        "lease_liabilities_cur": lease_liabilities_cur,  # (cur, prior) or None, normalised to ₹ Cr - Total Debt component b
        "other_fin_liab_nc": other_fin_liab_nc,  # dict or None - Non-current Other Financial Liabilities, Three-Part Test
        "other_fin_liab_cur": other_fin_liab_cur,  # dict or None - Current Other Financial Liabilities, Three-Part Test
        "total_assets": total_assets,  # (cur, prior) or None, normalised to ₹ Cr
        "total_current_assets": total_current_assets,           # (cur, prior) or None, normalised to ₹ Cr
        "total_current_liabilities": total_current_liabilities,  # (cur, prior) or None, normalised to ₹ Cr
        "net_fixed_assets": net_fixed_assets,  # (cur, prior) or None, normalised to ₹ Cr - Sr No 30
        "equity": equity,  # (cur, prior) or None, normalised to ₹ Cr - owners-attributable Total Equity
        "equity_basis": equity_basis,  # "owners" (explicit exclusion of NCI found) or "generic" (no NCI split found)
        "equity_full": equity_full,  # (cur, prior) or None, normalised to ₹ Cr - WHOLE-entity Total Equity (owners' + NCI); same as `equity` when NCI is absent
        "retained_earnings": retained_earnings,  # (cur, prior) or None, normalised to ₹ Cr - Sr No 55 (Altman Z-Score)
        "retained_earnings_basis": retained_earnings_basis,  # "exact" (Reserves and Surplus) or "other_equity_proxy"
        "variable_opex_note": variable_opex_note,  # dict or None - Sr No 44, {"items": {...}, "total_cur", "total_prior"} from the Other Expenses Note breakup
        "variable_direct_expenses_note": variable_direct_expenses_note,  # dict or None - Sr No 44, same shape, from a separate "Direct Expenses" Note breakup
        "pl_page": pl_idx + 1, "bs_page": bs_idx + 1,
    }


def _broad_extraction_to_parsed_shape(sym, fiscal_year, consolidated, content=None):
    """Fallback for the manual document-analysis workflow ONLY: when the
    narrow, exact-phrase/spatial page-locator in _extract_from_pdf() (tuned
    against specific real filings' exact headings/table shapes) can't find
    this particular Annual Report's Balance Sheet/P&L pages, reuse
    tools.document_analysis_engine.extract_line_items()'s broad, alias-rich
    extraction instead - the SAME reliable extraction already used by the
    Strategy-C ratios (P/E, P/B, ROA, Working Capital) and confirmed working
    on this exact PDF. Translates its ~20 canonical facts into the
    (current_value, prior_value) 2-tuple shape every "..._from_annual_report"
    function in this file expects from `parsed`.

    Current AND prior-year values are both used when the page-anchored
    extractor found both columns (see document_analysis_engine.py's
    _extract_from_anchor_page) - falls back to closing-balance-only
    (prior=None, the SAME reduced-confidence degradation these functions
    already implement for a single-Annual-Report upload, see e.g.
    fetch_inventory_turnover_from_annual_report's inv_prior handling) only
    when a genuine second column wasn't found on that statement's page.
    Fields this broad extractor doesn't capture at all (lease-liability/
    borrowings sub-item breakdowns beyond the summed total, bank-specific
    facts) are simply absent from the returned dict - the calling
    function's own existing "could not find X" handling reports those
    honestly as not_disclosed, never a fabricated number. Never raises."""
    from tools.document_analysis_engine import extract_line_items
    items = extract_line_items(sym, fiscal_year)           # the SAME fiscal year as the PDF being parsed, in every pipeline

    def val(key):
        hit = items.get(key)
        return hit["value"] if hit else None

    def pair(key):
        hit = items.get(key)
        if not hit or hit.get("value") is None:
            return None
        return (hit["value"], hit.get("prior_value"))

    revenue = pair("revenue")
    # The exact component keys ("Cost of materials consumed" / "Purchases
    # of stock-in-trade") several narrow-parser functions (Contribution
    # Margin, Beneish M-Score) read individually via components.get(...) -
    # a pure manufacturer legitimately has only the first, a pure trader
    # legitimately has only the second; only include a component when its
    # OWN specific line was actually found, never a combined guess.
    components = {}
    materials_pair = pair("cost_of_materials_consumed")
    stock_pair = pair("purchases_of_stock_in_trade")
    # Third COGS component (Schedule III's "a + b + c", same _COGS_LABELS
    # set the narrow parser validates) - was missing from this broad-
    # extraction fallback entirely, understating COGS (and therefore
    # overstating Gross Profit Margin) for every company routed through
    # this path with a material inventory-level change during the year.
    # Confirmed real on ANURAS: Gross Profit Margin came out as Revenue
    # minus Cost of materials consumed ALONE (34.80%), omitting Changes in
    # Inventories entirely. Same "only include a component when its own
    # specific line was actually found" rule as the other two - a company
    # with no inventory movement to report legitimately has no such line.
    inventory_change_pair = pair("changes_in_inventories")
    if materials_pair is not None:
        components["Cost of materials consumed"] = materials_pair
    if stock_pair is not None:
        components["Purchases of stock-in-trade"] = stock_pair
    if inventory_change_pair is not None:
        components["Changes in inventories"] = inventory_change_pair
    if not components:
        # Neither specific sub-item was found - fall back to the combined
        # "cogs" figure under a generic label, still honestly sourced, just
        # not attributable to one specific Schedule III line.
        cogs_val = val("cogs")
        if cogs_val is not None:
            components = {"Cost of Goods Sold (broad extraction)": (cogs_val, None)}
    pat = pair("pat")
    equity = pair("equity")
    # `equity_basis` was unconditionally set to "consolidated"/"standalone"
    # below - a STATEMENT-BASIS label, not the "owners-vs-NCI-inclusive"
    # label every consumer of this field actually checks (ROE Sr18,
    # Financial Leverage Sr23, Debt-to-Equity Sr20, BVPS Sr46 all test
    # `equity_basis == "owners"`). Since "consolidated"/"standalone" can
    # NEVER equal "owners", every company routed through this broad-
    # extraction fallback (narrow parser failed to locate its statement
    # pages) had its equity treated as NCI-ambiguous by every one of those
    # ratios, regardless of whether the extracted figure genuinely excludes
    # NCI - confirmed real on ANURAS: Financial Leverage Ratio's own
    # "equity" hit matched "Total Equity 28,503.13 ... NON-CONTROLLING
    # INTEREST 2,313.42 ..." (still inside the ~160-char evidence window
    # this module already captures) - Ind AS Schedule III always prints
    # NCI as its own SEPARATE Balance Sheet line, never blended into "Total
    # Equity", so an NCI mention appearing shortly after the matched figure
    # is exactly the same "genuinely owners-only" signal the narrow parser
    # itself relies on (see `_NCI_LABELS`'s comment) - reusing the evidence
    # text already fetched, no new page scan. When no NCI mention is
    # nearby, the value's basis is genuinely still ambiguous (could be a
    # true single-entity company with real 0 NCI, or a whole-entity figure
    # this simpler extractor can't distinguish) - falls back to the
    # original consolidated/standalone label, keeping the existing
    # (conservative) confidence downgrade for that case unchanged.
    equity_hit = items.get("equity") or {}
    equity_evidence = (equity_hit.get("evidence") or "").lower()
    equity_owners_confirmed = equity is not None and (
        "non-controlling interest" in equity_evidence or "minority interest" in equity_evidence)
    equity_basis_label = "owners" if equity_owners_confirmed else (
        "consolidated" if consolidated else "standalone")
    # Whole-entity equity (owners' + NCI) - Debt-to-Equity (Sr No 20) needs
    # this, not the owners-only `equity` above, since its numerator (Total
    # Debt) is the WHOLE consolidated entity's debt (see `_NCI_LABELS`'s
    # comment for the same reasoning in the narrow parser). Previously
    # `equity_full` was set identically to `equity` here, unconditionally -
    # silently reusing the owners-only figure and understating Debt-to-
    # Equity's denominator by the NCI amount whenever a company routed
    # through this broad-extraction fallback had a material minority
    # interest. Only added back when NCI was actually found AND the equity
    # figure is confirmed owners-only (summing NCI onto an already-whole-
    # entity or ambiguous equity figure would double-count it) - falls back
    # to the same value as `equity` (the prior, safe behavior) whenever
    # either condition isn't met, never fabricating a whole-entity figure
    # from an unconfirmed base.
    # PAT basis: the "pat" alias list tries owners-attributable phrasing
    # first, so when the matched evidence text itself reads "...attributable
    # to Owners/equity holders...", the figure IS the owners-only profit -
    # report that explicitly (consumers test `pat_basis == "owners"` for the
    # label and confidence) instead of the statement-basis word, which could
    # never satisfy that check.
    _pat_ev = ((items.get("pat") or {}).get("evidence") or "").lower()[:120]
    pat_owners_confirmed = pat is not None and re.search(
        r"attributable\s+to\s+(?:the\s+)?(?:owners|equity\s+holders|shareholders)", _pat_ev) is not None
    pat_basis_label = "owners" if pat_owners_confirmed else ("consolidated" if consolidated else "standalone")
    nci_pair = pair("non_controlling_interest")
    if equity_owners_confirmed and nci_pair is not None:
        equity_full = (round(equity[0] + nci_pair[0], 2),
                       round(equity[1] + nci_pair[1], 2) if equity[1] is not None and nci_pair[1] is not None else None)
    else:
        equity_full = equity
    total_debt_hit = items.get("total_debt")

    # Total Tax Expense - preferred DERIVED as (PBT - TOTAL PAT) rather than
    # the raw "tax" alias match, whenever both are available. Confirmed real
    # on ANURAS: the filing has no explicit "Total Tax Expense" subtotal
    # line at all - it prints a bare "Tax Expenses" SECTION HEADING followed
    # by separate "Current tax"/"Deferred tax" rows - and the "tax" alias
    # ("tax expense" is a substring of "Tax Expenses") matched that heading
    # and grabbed only the nearest number (Current tax, Rs 43.81 Cr),
    # silently dropping the Deferred tax component (Rs -5.93 Cr this year)
    # entirely and overstating Effective Tax Rate (Sr No 43) and ROIC's
    # (Sr No 42) tax adjustment. PBT - PAT is always exactly Total Tax
    # Expense by definition, so it sidesteps this presentation-format
    # fragility entirely - but PBT is a pre-NCI-split, WHOLE-ENTITY figure,
    # so it must be paired with `pat_total` (also whole-entity), NEVER the
    # owners-only `pat` above - using owners-only `pat` here would silently
    # reintroduce a wrong tax figure understated by exactly the NCI profit
    # share (confirmed while writing this fix: `pat` was reordered to
    # owners-first earlier in this same file for Net Profit Margin/ROE,
    # which would have broken this derivation had `pat` been reused here
    # instead of the dedicated `pat_total`). Falls back to the raw alias
    # match only when PBT or the total PAT weren't found - never fabricates
    # a tax figure neither can support.
    pbt_pair = pair("pbt")
    pat_total = pair("pat_total")
    if pbt_pair is not None and pat_total is not None:
        tax_prior = (round(pbt_pair[1] - pat_total[1], 2)
                     if pbt_pair[1] is not None and pat_total[1] is not None else None)
        tax_expense = (round(pbt_pair[0] - pat_total[0], 2), tax_prior)
    else:
        tax_expense = pair("tax")

    out = {
        "revenue": revenue,
        "components": components,
        "pat": pat, "pat_basis": pat_basis_label,
        "pbt": pbt_pair,
        "tax_expense": tax_expense,
        "interest_expense": pair("interest_expense"),
        "finance_costs": pair("interest_expense"),
        "depreciation": pair("depreciation"),
        "total_assets": pair("total_assets"),
        "total_current_assets": pair("current_assets"),
        "total_current_liabilities": pair("current_liabilities"),
        "inventory": pair("inventory"),
        "receivables": pair("receivables"),
        "payables": pair("payables"),
        "cash": pair("cash"),
        # --- fields added by the 2026-10 global remediation (each consumed by
        # the single ratio contract in tools/ratio_contract.py) -------------
        "eps_owners": pair("eps_owners"),                    # Basic EPS "excluding NCI"/owners, when printed
        "pat_total": pair("pat_total"),                       # whole-entity profit (owners + NCI)
        "dividend_paid": pair("dividends_paid"),             # CF Financing "Dividend paid" (cash, as printed: negative)
        "lease_liabilities_total": pair("lease_liabilities"),  # non-current + current lease rows summed
        "lease_evidence": ("found" if pair("lease_liabilities") is not None else
                            "none_on_balance_sheet" if pair("rou_assets") is None else "unparsed"),
        "total_liabilities": pair("total_liabilities"),      # the statement's own subtotal
        "goodwill": pair("goodwill"), "ppe": pair("ppe"), "rou_assets": pair("rou_assets"),
        "cwip": pair("cwip"), "intangibles": pair("intangibles"),
        "non_controlling_interest": pair("non_controlling_interest"),
        "nci_evaluated": bool(equity_owners_confirmed or not consolidated),
        # Informational line total only - the broad extractor has no Notes
        # breakup to classify restricted vs unrestricted, so Cash Ratio keeps
        # it OUT of the numerator but now sees it exists (drops confidence to
        # 0.8 instead of silently reporting a confirmed 1.0).
        "other_bank_balances": pair("other_bank_balances"),
        "equity": equity, "equity_full": equity_full, "equity_basis": equity_basis_label,
        "operating_cash_flow": pair("operating_cash_flow"),
        "capex_ppe_purchase": pair("capex"),
        "eps": pair("eps"),
        "shares_outstanding": pair("shares_outstanding"),
        "dividend_per_share": pair("dividend_per_share"),
        "employee_benefit_expense": pair("employee_benefit_expense"),
        "other_expenses": pair("other_expenses"),
        "net_fixed_assets": pair("net_fixed_assets"),
        "retained_earnings": pair("reserves_and_surplus"), "retained_earnings_basis": "consolidated" if consolidated else "standalone",
        "total_expenses": pair("total_expenses"),
        # Whole Total Debt placed in st_borrowings (_compute_total_debt sums
        # whatever sub-items are present, defaulting missing ones to 0) -
        # this extractor can't split it into long/short-term or lease
        # sub-components, so the lease-basis toggle has no effect here.
        "st_borrowings": (total_debt_hit["value"], total_debt_hit.get("prior_value")) if total_debt_hit and total_debt_hit.get("value") is not None else None,
        "bs_page": (items.get("current_assets") or {}).get("page"),
        "pl_page": (items.get("revenue") or {}).get("page"),
        "cf_page": (items.get("operating_cash_flow") or {}).get("page"),
        "basis_used": "broad_extraction",
    }

    # Contribution Margin (Sr No 44)'s variable-cost-beyond-materials
    # component (`_find_variable_opex_note`) - was never wired into this
    # broad-extraction fallback at all, so every company routed through it
    # (the narrow parser couldn't locate its Balance Sheet/P&L pages)
    # always got Variable Costs = goods cost ONLY, silently understating
    # Contribution Margin. Confirmed real on ANURAS, which is routed
    # through this exact fallback. `revenue`'s own found page is the P&L
    # page - reuse it (1-indexed -> 0-indexed) instead of re-locating it;
    # skip entirely (never guess a page) if it wasn't found.
    pl_page_num = (items.get("revenue") or {}).get("page")
    if pl_page_num:
        try:
            import fitz
            _bytes = content
            if _bytes is None:
                pdf_cache_path = os.path.normpath(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "..", "cache", "ar_pdfs", f"{sym}_{fiscal_year}.pdf"))
                if os.path.exists(pdf_cache_path):
                    with open(pdf_cache_path, "rb") as fh:
                        _bytes = fh.read()
            if _bytes is not None:
                doc = fitz.open(stream=_bytes, filetype="pdf")
                out["variable_opex_note"] = _find_variable_opex_note(doc, pl_page_num - 1)
                out["variable_direct_expenses_note"] = _find_variable_opex_note(doc, pl_page_num - 1, caption="direct expenses")
        except Exception:
            pass

    return out


_NOTE_NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?"
# Schedule III's "Cost of Materials Consumed" note:
#   Opening stock ... / Add: Purchases during the year  P_cur P_prior [S_cur S_prior]
#   Less: Closing stock  C_cur C_prior / Total [note-ref]  T_cur T_prior
_PURCHASES_NOTE_RE = re.compile(
    r"add\s*:?\s*purchases?(?:\s+of\s+(?:raw\s+)?materials?)?(?:\s+during\s+the\s+(?:year|period))?"
    rf"[\s\-–—]*(?P<p1>{_NOTE_NUM})\s+(?P<p2>{_NOTE_NUM})"
    rf"(?:\s+(?P<s1>{_NOTE_NUM})\s+(?P<s2>{_NOTE_NUM}))?"
    r".{0,80}?less\s*:?\s*closing\s+(?:stock|inventor\w*)[^\d(]{0,60}?"
    rf"[\s\-–—]*(?P<c1>{_NOTE_NUM})\s+(?P<c2>{_NOTE_NUM})"
    r".{0,60}?total[^\d(]{0,25}?(?:\d+\s*\([a-z]\)\s*)?"
    rf"(?P<t1>{_NOTE_NUM})\s+(?P<t2>{_NOTE_NUM})",
    re.I | re.S)
# crore, million, lakh, thousand, rupee -> multiplier to ₹ Cr
_UNIT_TO_CRORE = (1.0, 0.1, 0.01, 1e-4, 1e-7)


def _note_num(tok):
    if tok is None:
        return None
    t = tok.strip()
    neg = t.startswith("(") or t.startswith("-")
    t = t.strip("()-").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _find_disclosed_raw_material_purchases(page_texts, consumed_cr, first_page=1):
    """The Annual Report's own "Add: Purchases during the year" line from the
    Cost of Materials Consumed note, as (cur, prior, page) in ₹ Cr - or None
    when no note validates. Cost of Materials Consumed (the P&L line) is
    opening RM stock + purchases - closing RM stock, NOT purchases, so using
    it as a Payables-Turnover numerator misstates it whenever raw-material
    stock moves.

    Self-validating, never guesses: a candidate is accepted only if its note
    "Total" equals the already-extracted P&L Cost of Materials Consumed
    (`consumed_cr`) at one of the standard reporting units (so the right
    statement - standalone vs consolidated - and the unit are both proven),
    and, when the note prints a subtotal, subtotal - closing stock == total.
    The unit is derived from that match, not assumed."""
    if not page_texts or not consumed_cr or consumed_cr <= 0:
        return None
    for offset, text in enumerate(page_texts):
        if not text or "purchase" not in text.lower():
            continue
        for m in _PURCHASES_NOTE_RE.finditer(text):
            p1, p2, c1, t1 = (_note_num(m.group(g)) for g in ("p1", "p2", "c1", "t1"))
            if p1 is None or t1 is None or t1 <= 0 or p1 <= 0:
                continue
            scale = consumed_cr / t1
            unit = next((u for u in _UNIT_TO_CRORE if abs(scale / u - 1.0) <= 0.005), None)
            if unit is None:
                continue
            s1 = _note_num(m.group("s1"))
            if s1 is not None and c1 is not None and abs((s1 - c1) - t1) > 0.005 * t1:
                continue
            return (round(p1 * unit, 2),
                    round(p2 * unit, 2) if p2 is not None else None,
                    first_page + offset)
    return None


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_DATE_RES = (
    re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")[\s,]+(\d{4})", re.I),
    re.compile(r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?[\s,]+(\d{4})", re.I),
)
_DIVIDEND_RE = re.compile(
    r"\b(interim|final|special)\s+dividend[^.\d₹`]{0,70}?(?:of|@|at)\s*"
    r"(?:rs\.?|inr|₹|`)?\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*"
    r"(?:per\s+(?:fully\s+paid[\s-]*up\s+)?(?:equity\s+)?share|each\s+equity\s+share|per\s+share)", re.I)
_DIVIDEND_GENERIC_RE = re.compile(
    r"dividend[^.\d₹`]{0,60}?(?:of|@|at)\s*(?:rs\.?|inr|₹|`)?\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*"
    r"(?:per\s+(?:fully\s+paid[\s-]*up\s+)?(?:equity\s+)?share|each\s+equity\s+share)", re.I)
_NO_DIVIDEND_RE = re.compile(
    r"(?:no\s+dividend\s+(?:has\s+been|was|is|shall\s+be|have\s+been)\s*(?:recommended|declared|proposed|paid)"
    r"|(?:not|no)\s+(?:recommended|declared|proposed)\s+any\s+dividend"
    r"|(?:does|do|did)\s+not\s+(?:recommend|propose|declare)\s+any\s+dividend"
    r"|decided\s+not\s+to\s+(?:recommend|declare|pay)\s+(?:any\s+)?dividend"
    r"|board\s+has\s+not\s+recommended\s+any\s+dividend)", re.I)
_ACQUISITION_RE = re.compile(
    r"(?:stock\s+inwards?\s+on\s+acquisition|on\s+acquisition\s+of\s+(?:the\s+)?(?:subsidiary|business)"
    r"|acquisition\s+of\s+(?:the\s+)?(?:subsidiary|business|controlling)|business\s+combination"
    r"|became\s+a\s+(?:wholly[\s-]*owned\s+)?subsidiary|acquired\s+(?:\d+(?:\.\d+)?\s*%|control))", re.I)


def _dates_in(text):
    import datetime as _dt
    out = []
    for i, rx in enumerate(_DATE_RES):
        for m in rx.finditer(text):
            try:
                if i == 0:
                    d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
                else:
                    mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
                out.append(_dt.date(y, mo, d))
            except (ValueError, KeyError):
                continue
    return out


_OTHER_ENTITY_RE = re.compile(r"subsidiar|associate\s+compan|joint\s+venture|investee|step-down", re.I)


def _is_other_entity_dividend(text, start, end):
    """A dividend sentence about a SUBSIDIARY / associate / joint venture (their own per-share dividend, or the
    parent's share of it) is not the parent's DPS and must never be added to it."""
    seg = text[max(0, start - 220): start]
    # only the SAME sentence counts ("Rs. 4.50" is not a sentence end)
    bounds = list(re.finditer(r"(?<!Rs)(?<!INR)(?<!Re)\.\s+(?=[A-Z(])", seg))
    if bounds:
        seg = seg[bounds[-1].end():]
    tail = text[end:end + 90]
    fwd = re.search(r"(?<!Rs)(?<!INR)(?<!Re)\.\s+(?=[A-Z(])", tail)
    if fwd:
        tail = tail[:fwd.start()]
    return bool(_OTHER_ENTITY_RE.search(seg + text[start:end] + tail))


_FY_TOKEN_RES = (
    re.compile(r"(?:financial\s+year|f\.?\s?y\.?|year|fy)\s*(?:ended\s+)?(\d{4})\s*[-\u2013/]\s*(\d{2,4})", re.I),
    re.compile(r"(?:year|period)\s+ended\s+(?:on\s+)?(?:the\s+)?(?:31(?:st)?\s+march,?\s+|march\s+31(?:st)?,?\s+)(\d{4})", re.I),
    re.compile(r"(?:financial\s+year|f\.?\s?y\.?|fy)\s*(\d{4})\b", re.I),
)
_SENT_END_RE = re.compile(r"(?<!Rs)(?<!INR)(?<!Re)\.\s+(?=[A-Z(])")


def _dividend_target_fy(text, end):
    """The fiscal year (ending year) a dividend sentence says the dividend is FOR, read from the same sentence AFTER the
    amount ("... out of the retained earnings available for the financial year 2024-25", "... for the financial year
    ended March 31, 2026"). None when the sentence names no year - the caller then falls back to dating the event.
    A dividend is attributed by the year it is declared FOR, never by the date it happens to be declared or paid."""
    seg = text[end:end + 320]
    cut = _SENT_END_RE.search(seg)
    if cut:
        seg = seg[:cut.start()]
    best = None
    for i, rx in enumerate(_FY_TOKEN_RES):
        m = rx.search(seg)
        if not m:
            continue
        if i == 0:
            a, b = int(m.group(1)), m.group(2)
            y = int(b) if len(b) == 4 else (a // 100) * 100 + int(b)
        else:
            y = int(m.group(1))
        if best is None or m.start() < best[0]:
            best = (m.start(), y)
    return best[1] if best else None


def _scan_dividend_disclosures(page_texts, fiscal_year):
    """Dividend PER SHARE declared in respect of the fiscal year, read from
    the narrative disclosures (Directors' Report, AGM notice, notes).

    Navrist DPS policy (kept from the earlier documented QA decision):
        DPS = interim/special dividend declared DURING the fiscal year
              + final dividend RECOMMENDED for the fiscal year.
    A sentence counts only when it is dated/labelled inside the fiscal year:
    an interim must sit under a date within [1-Apr-(FY-1), 31-Mar-FY] or name
    the fiscal year; a final must name the fiscal year (so last year's final,
    merely paid this year, is never added). Distinct (kind, amount) pairs are
    de-duplicated across the many places a report repeats the same figure.

    `no_dividend_evidence` is True only on an explicit statement that no
    dividend was recommended/declared for the year - the only thing that
    supports a genuine zero. Finding nothing at all is NOT zero: `found`
    stays False and the consumers report the value as unavailable."""
    import datetime as _dt
    fy = int(fiscal_year)
    lo, hi = _dt.date(fy - 1, 4, 1), _dt.date(fy, 3, 31)
    labels = {f"{fy - 1}-{str(fy)[-2:]}", f"{fy - 1}-{fy}", f"{fy - 1}–{str(fy)[-2:]}",
              f"{fy - 1}–{fy}", f"{fy - 1}/{str(fy)[-2:]}", f"march 31, {fy}", f"march {fy}",
              f"31st march, {fy}", f"31st march {fy}", f"31 march {fy}", f"31 march, {fy}"}
    prior_labels = {f"{fy - 2}-{str(fy - 1)[-2:]}", f"{fy - 2}-{fy - 1}", f"{fy - 2}–{str(fy - 1)[-2:]}"}
    found = {"interim": set(), "final": set(), "special": set()}
    pages_hit, no_div, events = [], False, []
    for pi, text in enumerate(page_texts):
        if not text or "dividend" not in text.lower():
            continue
        for m in _DIVIDEND_RE.finditer(text):
            kind, amt = m.group(1).lower(), float(m.group(2))
            if not (0 < amt <= 5000) or 1900 <= amt <= 2100:
                continue
            if _is_other_entity_dividend(text, m.start(), m.end()):
                continue
            ctx = text[max(0, m.start() - 320): m.end() + 320]
            ctx_low = ctx.lower()
            cur_label = any(lb in ctx_low for lb in labels)
            prior_label = any(lb in ctx_low for lb in prior_labels)
            dated_in_fy = any(lo <= d <= hi for d in _dates_in(ctx))
            target = _dividend_target_fy(text, m.end())
            if target is not None:                          # explicit "for the financial year X" wins over any date
                ok = target == fy
                basis = "stated financial year"
            elif kind == "final":
                ok = cur_label and not (prior_label and not dated_in_fy and "recommend" not in ctx_low)
                basis = "labelled/dated"
            else:
                ok = dated_in_fy or (cur_label and not prior_label)
                basis = "labelled/dated"
            events.append({"kind": kind, "amount": amt, "page": pi + 1, "target_fy": target, "counted": bool(ok), "basis": basis})
            if ok:
                found[kind].add(amt)
                pages_hit.append(pi + 1)
        # unlabelled "dividend of Rs X per share": classified by the words right before it
        for m in _DIVIDEND_GENERIC_RE.finditer(text):
            amt = float(m.group(1))
            if not (0 < amt <= 5000) or 1900 <= amt <= 2100:
                continue
            if _is_other_entity_dividend(text, m.start(), m.end()):
                continue
            lead = text[max(0, m.start() - 140): m.start() + 12].lower()
            if re.search(r"\b(?:interim|special|final)\s+dividend", text[max(0, m.start() - 12): m.end()], re.I):
                continue                                    # already handled by the labelled pattern
            kind = ("interim" if "interim" in lead else "special" if "special" in lead else
                    "final" if re.search(r"recommend|propos|final", lead) else None)
            if kind is None:
                continue
            ctx = text[max(0, m.start() - 320): m.end() + 320]
            ctx_low = ctx.lower()
            cur_label = any(lb in ctx_low for lb in labels)
            prior_label = any(lb in ctx_low for lb in prior_labels)
            dated_in_fy = any(lo <= d <= hi for d in _dates_in(ctx))
            target = _dividend_target_fy(text, m.end())
            if target is not None:
                ok = target == fy
            else:
                ok = (cur_label and not (prior_label and not dated_in_fy and "recommend" not in ctx_low)) if kind == "final" \
                    else (dated_in_fy or (cur_label and not prior_label))
            events.append({"kind": kind, "amount": amt, "page": pi + 1, "target_fy": target, "counted": bool(ok),
                           "basis": "stated financial year" if target is not None else "labelled/dated"})
            if ok:
                found[kind].add(amt)
                pages_hit.append(pi + 1)
        nm = _NO_DIVIDEND_RE.search(text)
        if nm:
            ctx_low = text[max(0, nm.start() - 300): nm.end() + 300].lower()
            if any(lb in ctx_low for lb in labels) or "financial year" in ctx_low:
                no_div = True
    total = sum(sum(v) for v in found.values())
    any_found = any(found.values())
    return {"interim": sorted(found["interim"]), "final": sorted(found["final"]),
            "special": sorted(found["special"]),
            "total": round(total, 4) if any_found else None, "found": any_found,
            "no_dividend_evidence": bool(no_div and not any_found),
            "policy": "interim/special + final dividends declared FOR the fiscal year (attributed by the year the sentence "
                      "states, else by date/label)",
            "pages": sorted(set(pages_hit)), "events": events[:40]}


_OWNERS_DIV_PAID_RE = re.compile(
    r"(?:less:?\s*)?(?:equity\s+share(?:s|holders?)?|equity)\s+(?:(?:final|interim|special)\s+)?dividends?\s+paid"
    r"(?:\s+(?:for|on|in\s+respect\s+of)\s+(?:the\s+)?(?:f\.?\s?y\.?|financial\s+year|year)?\s*[\d\-–/ ]{4,9})?"
    r"\s*\(\s*([\d,]+(?:\.\d+)?)\s*\)\s*\(\s*([\d,]+(?:\.\d+)?)\s*\)", re.I)
_NCI_DIV_RE = re.compile(
    r"(?:nci|non[\s-]*controlling\s+interests?|minority\s+interests?)\s+share\s+of\s+dividends?\s*\(?\s*([\d,]+(?:\.\d+)?)\s*\)?"
    r"|dividends?\s+(?:paid\s+)?to\s+(?:the\s+)?(?:nci|non[\s-]*controlling\s+interests?|minority(?:\s+shareholders)?)\s*"
    r"\(?\s*([\d,]+(?:\.\d+)?)\s*\)?(?:\s*\(?\s*([\d,]+(?:\.\d+)?)\s*\)?)?", re.I)


def _scan_dividend_components(page_texts):
    """Splits the dividends PAID in the year by recipient, from the notes (the cash-flow statement prints only the whole-entity total):
        owners  - 'Equity share ... dividend paid (cur) (prior)' rows of the reserves / statement-of-changes-in-equity note
                  (the parent's own dividends; identical on the standalone and consolidated pages)
        nci     - the minorities' share of subsidiaries' dividends ('NCI share of dividend', 'dividend paid to non-controlling
                  interests'); current year only
    Returns {"owners_candidates": [{cur, prior, page}], "nci": {"cur", "prior", "page"} | None}. Amounts are converted to rupee
    crore with the unit declared on the page they were read from. Nothing is inferred: a figure that is not printed stays absent."""
    owners, nci = [], None
    for pi, text in enumerate(page_texts):
        if not text or "dividend" not in text.lower():
            continue
        f = _unit_factor(text)
        rows = [(float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))) for m in _OWNERS_DIV_PAID_RE.finditer(text)]
        if rows:
            owners.append({"cur": round(sum(r[0] for r in rows) * f, 4), "prior": round(sum(r[1] for r in rows) * f, 4),
                           "page": pi + 1, "rows": len(rows)})
        if nci is None:
            m = _NCI_DIV_RE.search(text)
            if m:
                c = next((g for g in (m.group(1), m.group(2)) if g), None)
                if c is not None:
                    p_ = m.group(3) if m.lastindex and m.lastindex >= 3 else None
                    nci = {"cur": round(float(c.replace(",", "")) * f, 4),
                           "prior": round(float(p_.replace(",", "")) * f, 4) if p_ else None, "page": pi + 1}
    return {"owners_candidates": owners, "nci": nci}


_OBB_HEADER_RE = re.compile(r"other\s+bank\s+balances?", re.I)
_OBB_NUM = r"\(?(?:[\d,]*\d\.\d+|\d{1,3}(?:,\d{2,3})+)\)?"          # a figure; a bare '-' is the Notes-column placeholder
_OBB_PAIR_RE = re.compile(r"(" + _OBB_NUM + r")\s+(" + _OBB_NUM + r")(?=\s|$)")
_OBB_LIEN_RE = re.compile(
    r"(?:lien|pledged?|marked|under\s+charge)[^.]{0,90}?(?:INR|Rs\.?|₹|`)\s*([\d,]+(?:\.\d+)?)\s*(million|crores?|lakhs?|mn)?"
    r"(?:[^.]{0,40}?(?:previous\s+year|prior\s+year)[^.]{0,20}?(?:INR|Rs\.?|₹|`)\s*([\d,]+(?:\.\d+)?))?", re.I)


def _scan_other_bank_balance_note(page_texts, obb_total_cr):
    """Classifies the lines of the 'Other bank balances' NOTE (current assets) so the Cash Ratio counts only what is available:
        restricted   - unclaimed / unpaid dividend, earmarked, margin money, escrow, pledged, bank-guarantee, security deposits, and any
                       fixed-deposit amount the note itself says is under LIEN (the lien amount is carved out of its deposit row)
        unclassified - a line whose nature the note does not state (e.g. a bare 'Deposit account'): kept as unrestricted but flagged
        deposit      - fixed deposits (maturity < 12 months) with no stated restriction
    Accepted only on a page whose printed Total equals the balance-sheet figure (`obb_total_cr`, rupee crore) - the right note, unit and
    basis are thereby proven. Returns None when no such note is found; never guesses a split."""
    if not obb_total_cr:
        return None
    for pi, text in enumerate(page_texts):
        if not text or not re.search(r"other\s+bank\s+balances?", text, re.I):
            continue
        f = _unit_factor(text)
        for hm in _OBB_HEADER_RE.finditer(text):
            seg = text[hm.end():hm.end() + 1600]
            seg = re.sub(r"(?i)amount\s*\([^)]*\)\s*in\s+\w+", " ", seg)
            seg = re.sub(r"(?i)particulars|notes?\s+as\s+at[^A-Za-z]{0,60}?(?:\d{4})\s+as\s+at\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4}", " ", seg)
            seg = re.sub(r"(?i)as\s+at\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4}", " ", seg)
            rows, pos, total = [], 0, None
            for pm in _OBB_PAIR_RE.finditer(seg):
                label = re.sub(r"(?i)\bnote\s+[A-Za-z0-9]+\b|(?<!\S)-(?!\S)|\*", " ", seg[pos:pm.start()])
                label = re.sub(r"\s+", " ", label).strip(" :-")
                label = re.sub(r"(?i)^notes?\s+", "", label)
                pos = pm.end()
                def num(x):
                    if x == "-":
                        return 0.0
                    neg = x.startswith("(")
                    v = float(x.strip("()").replace(",", ""))
                    return -v if neg else v
                cur, prior = num(pm.group(1)), num(pm.group(2))
                if label.lower().startswith("total") or re.search(r"(?i)\btotal$", label):   # a nil row ("Earmarked ... - -") may precede it
                    total = (cur, prior)
                    break
                if label and re.search(r"[A-Za-z]{3,}", label) and len(label) < 120:
                    rows.append({"label": label, "cur": cur, "prior": prior})
            if total is None or not rows:
                continue
            if abs(total[0] * f - obb_total_cr) > 0.01 * obb_total_cr + 0.01:
                continue
            tail = text[hm.end() + 0:hm.end() + 2600]
            lien_cur = lien_prior = 0.0
            lm = _OBB_LIEN_RE.search(tail)
            if lm:
                unit = (lm.group(2) or "").lower()
                lf = {"million": 0.1, "mn": 0.1, "crore": 1.0, "crores": 1.0, "lakh": 0.01, "lakhs": 0.01}.get(unit, f)
                lien_cur = float(lm.group(1).replace(",", "")) * lf
                lien_prior = float(lm.group(3).replace(",", "")) * lf if lm.group(3) else None
            comps, restricted, unclass = [], 0.0, 0.0
            lien_left = lien_cur
            for r in rows:
                amt = r["cur"] * f
                if amt <= 0:
                    continue
                low = r["label"].lower()
                if any(t in low for t in _OBB_RESTRICTED_SUBITEM_TERMS):
                    comps.append({"label": r["label"], "amount_cr": round(amt, 4), "class": "restricted"})
                    restricted += amt
                elif "fixed deposit" in low or re.search(r"\bfd\b|term deposit", low):
                    take = min(lien_left, amt)
                    lien_left -= take
                    if take > 0:
                        comps.append({"label": r["label"] + " - under lien", "amount_cr": round(take, 4), "class": "restricted"})
                        restricted += take
                    if amt - take > 0:
                        comps.append({"label": r["label"], "amount_cr": round(amt - take, 4), "class": "deposit"})
                else:
                    comps.append({"label": r["label"], "amount_cr": round(amt, 4), "class": "unclassified"})
                    unclass += amt
            base = total[0] * f
            return {"base_cur": round(base, 4), "base_prior": round(total[1] * f, 4), "netoff_cur": round(restricted, 4),
                    "netoff_prior": None, "unrestricted_cur": round(base - restricted, 4), "unrestricted_prior": None,
                    "unclassified_cur": round(unclass, 4), "components": comps, "page": pi + 1, "source": "note"}
    return None


def _parse_note_table(text, header_re, f):
    """Rows of a notes table that follows `header_re` on a (whitespace-collapsed) page: [(label, cur, prior)], the printed total
    (cur, prior) and the page unit factor. Only rows with two printed figures are read; a bare '-' is the Notes-column placeholder."""
    out = []
    for hm in header_re.finditer(text):
        seg = text[hm.end():hm.end() + 2200]
        seg = re.sub(r"(?i)amount\s*\([^)]*\)\s*in\s+\w+", " ", seg)
        seg = re.sub(r"(?i)particulars|notes?\s+as\s+at[^A-Za-z]{0,60}?(?:\d{4})\s+as\s+at\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4}", " ", seg)
        seg = re.sub(r"(?i)as\s+at\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4}", " ", seg)
        rows, pos, total = [], 0, None
        for pm in _OBB_PAIR_RE.finditer(seg):
            label = re.sub(r"(?i)\bnote\s+\w+(?:\(\w+\))?|(?<!\S)-(?!\S)|\*", " ", seg[pos:pm.start()])
            label = re.sub(r"\s+", " ", label).strip(" :-")
            label = re.sub(r"(?i)^notes?\s+", "", label)
            pos = pm.end()
            cur, prior = float(pm.group(1).strip("()").replace(",", "")), float(pm.group(2).strip("()").replace(",", ""))
            if label.lower().startswith("total") or re.search(r"(?i)\btotal$", label):
                total = (cur, prior)
                break
            if label and re.search(r"[A-Za-z]{3,}", label) and len(label) < 160:
                rows.append((label, cur, prior))
        if total is not None and rows:
            out.append({"rows": rows, "total": total, "factor": f})
    return out


def _scan_other_financial_liabilities_note(page_texts, bs_totals_cr):
    """Evaluates the Three-Part Test (`_OFL_DEBT_LIKE_TERMS` / `_OFL_EXCLUDE_TERMS`) on the 'Other financial liabilities' NOTE tables
    when the balance-sheet face has no sub-items to test. `bs_totals_cr` = the face figures [(cur, prior), ...] (non-current and/or
    current, rupee crore); a note table is accepted only if its printed total equals one of them (right note, unit, basis).
    Returns {"qualifying_cur", "qualifying_prior", "evaluated_cur", "tables", "candidates"} or None when no table was matched.
    'candidates' lists debt-LIKE rows the term lists do not accept (e.g. sale-and-lease-back liability, interest due to banks) so the
    policy question stays visible; they are never added silently."""
    hdr = re.compile(r"other\s+financial\s+liabilit(?:y|ies)", re.I)
    matched, qual_c, qual_p, cands = [], 0.0, 0.0, []
    for pi, text in enumerate(page_texts):
        if not text or not hdr.search(text):
            continue
        f = _unit_factor(text)
        for tb in _parse_note_table(text, hdr, f):
            tc = tb["total"][0] * f
            hit = next((b for b in bs_totals_cr if b and abs(tc - b[0]) <= 0.01 * abs(b[0]) + 0.01), None)
            if hit is None or any(abs(tc - m) < 1e-9 for m in (x["total_cr"] for x in matched)):
                continue
            q_c = q_p = 0.0
            for label, c, p in tb["rows"]:
                ll = label.lower()
                if any(t in ll for t in _OFL_EXCLUDE_TERMS):
                    continue
                if any(t in ll for t in _OFL_DEBT_LIKE_TERMS):
                    q_c += c * f
                    q_p += p * f
                elif re.search(r"lease\s*back|leaseback|interest\s+(?:accrued|due|payable)|borrowing|loan|deposit", ll):
                    cands.append({"label": label, "amount_cr": round(c * f, 4)})
            qual_c += q_c
            qual_p += q_p
            matched.append({"page": pi + 1, "total_cr": tc, "qualifying_cr": q_c})
    if not matched:
        return None
    return {"qualifying_cur": round(qual_c, 4), "qualifying_prior": round(qual_p, 4), "tables": matched, "candidates": cands,
            "source": "note"}


def _scan_acquisition_signals(page_texts):
    """Pages carrying business-combination language (acquisition of a
    subsidiary/business, stock inwards on acquisition...). Only a SIGNAL - the
    contract combines it with the balance-sheet movement (goodwill, total
    assets) before warning that year-end balances and flows are not
    comparable; it never adjusts any number."""
    hits = []
    for pi, text in enumerate(page_texts):
        if text and _ACQUISITION_RE.search(text):
            hits.append(pi + 1)
    return {"hits": len(hits), "pages": hits[:12]}


_SHARES_OPEN_RE = re.compile(
    r"(?:outstanding|balance|shares)[^.|]{0,50}?at\s+the\s+beginning\s+of\s+the\s+(?:year|period)[\s|:\-–]*(?P<n>\d[\d,]{4,})", re.I)
_SHARES_CLOSE_RE = re.compile(
    r"(?:outstanding|balance|shares)[^.|]{0,50}?at\s+the\s+end\s+of\s+the\s+(?:year|period)[\s|:\-–]*(?P<n>\d[\d,]{4,})", re.I)


def _scan_shares_opening(page_texts, shares_closing):
    """Prior-year share count = the OPENING row of the Share Capital note's mandated reconciliation table
    ("... at the beginning of the year"). Accepted only on a page whose CLOSING row equals the extracted current
    share count (so the right table and the right unit are proven); returns the opening count or None."""
    if not shares_closing:
        return None
    for text in page_texts:
        if not text or "beginning of the" not in text.lower():
            continue
        mo, mc = _SHARES_OPEN_RE.search(text), _SHARES_CLOSE_RE.search(text)
        if not mo or not mc:
            continue
        try:
            opening = float(mo.group("n").replace(",", ""))
            closing = float(mc.group("n").replace(",", ""))
        except ValueError:
            continue
        if opening > 0 and abs(closing - shares_closing) <= 0.005 * shares_closing:
            return opening
    return None


def _attach_text_disclosures(parsed, content, fiscal_year=None):
    """Adds the document-text facts no statement row carries:
      parsed["purchases_disclosed"]  - the Cost of Materials Consumed note's
                                       "Add: Purchases during the year" (₹ Cr)
      parsed["dps_declared"]         - see `_scan_dividend_disclosures`
      parsed["acquisition_signals"]  - see `_scan_acquisition_signals`
    One text pass over the PDF, never raises (each fact simply stays None)."""
    parsed["purchases_disclosed"] = None
    parsed["dps_declared"] = None
    parsed["acquisition_signals"] = None
    parsed["dividend_components"] = None
    parsed["obb_note"] = None
    parsed["ofl_note"] = None
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        texts = [re.sub(r"\s+", " ", doc[i].get_text()) for i in range(len(doc))]
    except Exception as e:
        print(f"[annual_report_financials] text-disclosure scan skipped: {e}")
        return parsed
    try:
        consumed = (parsed.get("components") or {}).get("Cost of materials consumed")
        if consumed and consumed[0] is not None and consumed[0] > 0:
            start = max((parsed.get("pl_page") or 1) - 1, 0)
            hit = _find_disclosed_raw_material_purchases(texts[start:start + 150], consumed[0], first_page=start + 1)
            if hit:
                parsed["purchases_disclosed"] = {"cur": hit[0], "prior": hit[1], "page": hit[2]}
    except Exception as e:
        print(f"[annual_report_financials] disclosed-purchases scan skipped: {e}")
    try:
        if fiscal_year:
            parsed["dps_declared"] = _scan_dividend_disclosures(texts, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] dividend scan skipped: {e}")
    try:
        if parsed.get("other_fin_liab_nc") is None and parsed.get("other_fin_liab_cur") is None:
            bsp = parsed.get("bs_page")
            btxt = texts[bsp - 1] if bsp and 0 < bsp <= len(texts) else ""
            f = _unit_factor(btxt)
            tots = []
            for m in re.finditer(r"other\s+financial\s+liabilit(?:y|ies)\s+(?:\d{1,2}[A-Za-z]?(?:\.\d+)?\s+)?(" + _OBB_NUM + r")\s+(" + _OBB_NUM + r")", btxt, re.I):
                tots.append((float(m.group(1).strip("()").replace(",", "")) * f, float(m.group(2).strip("()").replace(",", "")) * f))
            if tots:
                parsed["ofl_note"] = _scan_other_financial_liabilities_note(texts, tots)
    except Exception as e:
        print(f"[annual_report_financials] other-financial-liabilities note scan skipped: {e}")
    try:
        _obb = parsed.get("other_bank_balances")
        if _obb and (_obb[0] if isinstance(_obb, (tuple, list)) else _obb):
            parsed["obb_note"] = _scan_other_bank_balance_note(texts, _obb[0] if isinstance(_obb, (tuple, list)) else _obb)
    except Exception as e:
        print(f"[annual_report_financials] other-bank-balance note scan skipped: {e}")
    try:
        parsed["dividend_components"] = _scan_dividend_components(texts)
    except Exception as e:
        print(f"[annual_report_financials] dividend-component scan skipped: {e}")
    try:
        parsed["acquisition_signals"] = _scan_acquisition_signals(texts)
    except Exception as e:
        print(f"[annual_report_financials] acquisition scan skipped: {e}")
    try:
        sh = parsed.get("shares_outstanding")
        if sh is not None and (sh[0] if isinstance(sh, (tuple, list)) else sh) and \
                (not isinstance(sh, (tuple, list)) or len(sh) < 2 or sh[1] is None):
            parsed["shares_opening"] = _scan_shares_opening(texts, sh[0] if isinstance(sh, (tuple, list)) else sh)
    except Exception as e:
        print(f"[annual_report_financials] share-reconciliation scan skipped: {e}")
    return parsed


_attach_disclosed_purchases = _attach_text_disclosures   # legacy name


# Bump this alongside `_get_extracted_financials_impl`'s own cache-key
# "_vNN" suffix (see that function's version-history comment) whenever its
# extraction LOGIC changes - not for document-identity changes, which
# `_document_identity_tag` already handles separately. This single
# constant, folded into every wrapper cache key in this file via
# `_document_identity_tag`, is what makes a shared-extractor logic fix
# automatically invalidate all ~50 downstream wrapper caches at once - see
# `_document_identity_tag`'s docstring for the bug this closes.
# "61" - Payables Turnover uses the disclosed "Purchases during the year";
# Inventory Turnover numerator is Net Sales; WC Turnover/Days WC use closing
# working capital; broad extraction now captures Other Bank Balance(s) and
# the owners-attributable PAT basis.
# "72" - dividends are attributed by the fiscal year the sentence says they are FOR (not by the date declared/paid);
# Cash Ratio counts current Other Bank Balances; Inventory Turnover = COGS / Average Inventory.
# "78" - Notes + Page-No reference columns ahead of the figures are skipped together.
# "77" - more cost-of-materials caption variants.
# "76" - bare subtotal read from the figures after the last label (Titan).
# "75" - lettered note refs ("23A, 23B") and contents (dot-leader) pages are no longer read as figures / statements.
# "74" - hyphenated page-number ranges ("431-432") in a Notes/Page-No column are no longer read as two values.
# "73" - page unit declared as a footnote far below the table (Maruti "(in ` million ...)") is now honoured.
# "86" - "attributable to: Shareholders of the Company" label (colon) matches; (note, year) token pairs are not amounts.
# "85" - ONE extraction path for every pipeline: manual-only extraction branches and the broad fallback now apply to all.
# "84" - Total Debt is no longer rounded to 2dp.
# "83" - Other financial liabilities NOTE tables are evaluated with the Three-Part Test (debt-like candidates listed, not added).
# "82" - the Other-bank-balances NOTE is classified (restricted / lien / unclassified) for the Cash Ratio.
# "81" - dividends paid are split by recipient (owners vs minorities) from the notes.
# "80" - comma-separated note-number lists ("26, 15") ahead of a figure are blanked.
# "79" - second reference column in the line-based P&L row reader.
_EXTRACTION_LOGIC_VERSION = "86"


def _document_identity_tag(symbol, fiscal_year):
    """Cheap, generic document-identity fingerprint for cache-key scoping -
    a short hex digest of the underlying on-disk ar_text cache file's mtime
    and size for this (symbol, fiscal_year) slot, or "" if that file
    doesn't exist yet (nothing uploaded/fetched for this slot at all, or
    the live/non-manual pipeline, which re-downloads by URL rather than a
    fixed local slot).

    Purpose: a manual re-upload of a DIFFERENT document into the SAME
    (symbol, fiscal_year) slot (e.g. correcting a bad initial upload, or -
    looking ahead - replacing ANURAS's FY2024-25 filing with a restated
    version) overwrites `cache/ar_text/{SYM}_{fiscal_year}.json` in place,
    changing its mtime/size - this tag changes automatically as a result,
    so every ckey built from it changes too, and the old cached extraction
    is never looked up again. This does NOT replace the manual "_vNN"
    version bumps used throughout this file for LOGIC changes (a code diff
    has no effect on any file's mtime) - the two mechanisms are
    complementary: this tag catches "the document changed", the version
    number catches "the code changed". Never raises; a stat failure just
    yields "" (falls back to the old symbol+fiscal_year-only scoping,
    exactly the previous behaviour).

    Also folds in `_EXTRACTION_LOGIC_VERSION` (bumped alongside
    `_get_extracted_financials_impl`'s own "_vNN" cache key, see that
    function's version-history comment) - EVERY wrapper cache in this file
    keyed off this tag (Receivables/Payables Turnover, FCF, Capex
    Intensity, FCF Margin, Dividend Payout, EPS Growth, Altman Z-Score,
    Beneish M-Score, Piotroski F-Score, ...) reuses `_get_extracted_
    financials`'s shared parse result, but each has ALSO wrapped that
    result in its OWN separately versioned cache. A logic fix inside the
    shared inner extractor (e.g. a new label alias, a Balance Sheet
    column-count fix) previously only busted `_get_extracted_financials`'s
    own cache key - every wrapper's outer cache kept serving its
    pre-fix cached failure/result indefinitely (up to the 90-day TTL),
    because nothing in ITS OWN cache key had changed. Confirmed real on
    Prime Fresh Limited: fixing the Trade Receivable/3-column-Balance-Sheet
    extraction bugs made `_get_extracted_financials` return the correct
    receivables/payables immediately, but `fetch_receivables_turnover_
    from_annual_report`'s own `ar_recvturn_v2_...` cache kept returning its
    stale pre-fix "not found" result until this tag - which that cache key
    is built from - changed too. Bumping `_EXTRACTION_LOGIC_VERSION` here
    once, instead of hand-bumping every one of the ~50 wrapper cache keys
    in this file individually, makes this class of bug impossible to
    reintroduce by omission in the future."""
    try:
        from tools.ar_document_cache import _text_cache_path
        sym = re.sub(r"[^A-Z0-9]", "", (symbol or "").upper())
        p = _text_cache_path(sym, fiscal_year)
        import hashlib
        if not os.path.exists(p):
            # live pipeline (no local text cache): still scope by the code versions, never an empty tag
            from tools.ratio_contract import FORMULA_VERSION as _FV
            from tools.fundamental_fact_store import EXTRACTION_VERSION as _XV
            return hashlib.sha1(f"nodoc_{_EXTRACTION_LOGIC_VERSION}_{_FV}_f{_XV}".encode()).hexdigest()[:10]
        st = os.stat(p)
        from tools.ratio_contract import FORMULA_VERSION
        from tools.fundamental_fact_store import EXTRACTION_VERSION as _FACT_VERSION   # fact derivation + integrity layer
        return hashlib.sha1(
            f"{st.st_mtime_ns}_{st.st_size}_{_EXTRACTION_LOGIC_VERSION}_{FORMULA_VERSION}_f{_FACT_VERSION}".encode()).hexdigest()[:10]
    except Exception:
        return ""


def _get_extracted_financials(symbol, name, fiscal_year, consolidated=True):
    """Lock-guarded entry point for `_get_extracted_financials_impl` - see
    that function's docstring for what the actual fetch+parse does. This
    wrapper exists solely to fix a cache stampede: a first-ever visit to a
    company's Fundamental Ratios page fires 20-30 ratio requests at once,
    ALL keyed to the same (symbol, year, consolidated) PDF. Without a lock,
    every one of them would see a cache miss simultaneously and each
    independently pay the ~7s PDF download + parse cost, instead of one
    request doing the work and the rest reusing its result. Re-checks the
    cache after acquiring the lock (not just before), since another thread
    may have already finished the fetch while this one was waiting."""
    sym = symbol.strip().upper().replace(".NS", "")
    from tools.manual_mode import is_manual_mode
    # Manual document-analysis workflow (tools/manual_mode.py) and the OLD
    # automatic live-fetch pipeline share this symbol+year cache key by
    # coincidence - without a distinct suffix, whichever pipeline last wrote
    # this key silently serves its result to the OTHER pipeline too (e.g. a
    # stale automatic-pipeline failure masking a perfectly good manually
    # uploaded PDF, or vice versa). Never let that cross-contaminate - rule
    # "never silently use stale values from the old automatic pipeline".
    suffix = "_manual_v12" if is_manual_mode() else ""
    # Document-identity tag - makes this cache key self-invalidating when
    # the UNDERLYING uploaded document changes for the same (symbol,
    # fiscal_year) slot, without requiring a manual "_vNN" bump for that
    # specific class of change (a genuine document replacement, as opposed
    # to a code/logic change, which still needs its own version bump - the
    # two are orthogonal: this tag can't detect a logic change, and a
    # logic-version bump can't detect a document replacement). Cheap by
    # design - reads the on-disk ar_text cache file's mtime (already
    # written by tools/manual_document_pipeline.py whenever a document is
    # (re-)uploaded), no re-download/re-parse needed just to check
    # freshness. Falls back to "" when the file doesn't exist yet (nothing
    # to distinguish from) - never blocks a first-time fetch.
    doc_tag = _document_identity_tag(sym, fiscal_year)
    ckey = f"ar_extract_v29_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}{suffix}_{doc_tag}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    with _extract_lock_for(ckey):
        cached = _read_cache(ckey)
        if cached is not None:
            return cached
        return _get_extracted_financials_impl(symbol, name, fiscal_year, consolidated)


def _bank_core_parsed(content, fiscal_year):
    """Schedule-III-shaped `parsed` dict for an RBI-format bank (standalone statements - see tools/bank_extractor.py), so
    P/E, P/B, EPS growth, BVPS, ROA, yields and payout run on a bank through the SAME contract as on any other company.
    Revenue/EBITDA/inventory/working-capital concepts do not exist for a bank and are simply absent. Returns None when the
    document is not a readable RBI-format bank filing."""
    try:
        import fitz
        from tools import bank_extractor as be
        doc = fitz.open(stream=content, filetype="pdf")
        r = be.extract_bank(doc, "standalone")
        if "deposits" not in r or "advances" not in r or not (r.get("identities") or {}).get("balance_sheet_total"):
            return None
        core = be.extract_bank_core(doc, r)
    except Exception as e:
        print(f"[annual_report_financials] bank core parse skipped: {e}")
        return None
    if not core.get("pat") or not core.get("capital") or not core.get("reserves"):
        return None

    def pair(d):
        return (round(d["cur"], 4), round(d["prior"], 4)) if d else None
    cap, res = core["capital"], core["reserves"]
    equity = (cap["cur"] + res["cur"], cap["prior"] + res["prior"])
    fv = core.get("face_value")
    shares = ((cap["cur"] * 1e7 / fv), (cap["prior"] * 1e7 / fv)) if fv else None
    eps = core.get("eps")
    return {
        "basis_used": "standalone", "equity_basis": "owners", "nci_evaluated": True, "retained_earnings_basis": "exact",
        "pat": pair(core["pat"]), "pat_total": pair(core["pat"]), "pat_basis": "owners",
        "equity": equity, "equity_full": equity, "non_controlling_interest": (0.0, 0.0),
        "retained_earnings": pair(res), "total_assets": pair(core.get("total_assets")),
        "eps": (eps["cur"], eps["prior"]) if eps else None, "eps_owners": (eps["cur"], eps["prior"]) if eps else None,
        "shares_outstanding": shares,
        "bs_page": cap["page"], "pl_page": core["pat"]["page"], "bank_statements": True,
    }


def _get_extracted_financials_impl(symbol, name, fiscal_year, consolidated=True):
    """Shared, cached PDF fetch + parse. Every ratio derived from the same
    Annual Report (Inventory Turnover, Receivables Turnover, ...) reuses this
    single result instead of re-downloading a 10-30MB PDF per ratio. Returns
    `_extract_from_pdf`'s dict (with `source_url` added) or
    {'error': reason, 'source_url': ...}. Cached 90 days - EXCEPT network/IO
    failures (timeouts etc.), which are transient and must NOT be persisted
    for a week (the shared cache TTL): a user hitting a slow network blip
    would otherwise see that exact failure baked in for every subsequent
    visit. Never raises, and never surfaces a raw exception string - that's
    an internal detail, not something a user should see on the dashboard."""
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" cache-busts every extraction cached before the Cash Flow
    # Statement parser fix (broader max_pages, CFS-caption-aware section
    # tracking, relaxed boundary regexes, expanded label coverage) - older
    # cached extractions had operating_cash_flow/capex_*/*_repayment/
    # net_fixed_assets all silently null and would otherwise keep being
    # served for the remainder of their 90-day TTL regardless of the fix.
    # "_v15" (bumped from "_v14") - C.7 build added dividend_paid/
    # buyback_spend/acquisition_outflow to `_find_cash_flow_statement_items`;
    # pre-v15 cache entries don't have these keys at all (dict.get returns
    # None either way, but bumping avoids ever conflating "not computed in
    # this older cache entry" with "genuinely not found in the filing").
    # "_v16" (bumped from "_v15") - `parsed["segments"]` (Ind AS 108 segment
    # revenue, added below) was wired into this function WITHOUT a matching
    # version bump at the time, so every fiscal year cached under "_v15"
    # before that change silently has no "segments" key at all. That's what
    # made A.4 (Product lifecycle stage) show 100% Unclassified for
    # HINDUNILVR: fetch_multi_year_segment_revenue found segments for only
    # the one most-recently-fetched year (FY2026), and
    # compute_segment_cagr_from_multi_year requires 2+ years to compute any
    # CAGR at all - so with 3 of the 4 requested years serving stale
    # pre-segment cache entries, every segment came back unclassified, not
    # because HUL actually renamed its segments across the window.
    # "_v17" (bumped from "_v16") - `_extract_segment_revenue`'s stop-boundary
    # search picked the FIRST "segment result/assets/liabilit/..." match as
    # the sub-table's end, but some filers' segment note opens with a
    # preamble sentence mentioning both "segment revenue" (the caption) and
    # "segment results" (a stop keyword) back to back - confirmed on
    # HINDUNILVR's FY2025 AR, where that preamble sentence made the window
    # end ~140 characters after the caption, before ever reaching the real
    # REVENUE data table further down the same page. Now retries successive
    # stop candidates until one whose window actually parses to 2+ segment
    # rows. Pre-v17 cache entries may have `segments: None` purely from this
    # false-early-stop bug, not a genuine "couldn't find/reconcile" case.
    # "_v18" (bumped from "_v17") - added the symmetric standalone-requested-
    # but-not-found -> retry-consolidated fallback (mirrors the pre-existing
    # consolidated->standalone one just above) AND switched EPS/EPS-Growth to
    # request consolidated=False by default (Standalone-first policy for
    # per-share earnings figures - see fetch_eps/fetch_eps_growth in
    # tools/nse_xbrl.py). Pre-v18 cache entries for a Standalone request that
    # genuinely has no separate Standalone P&L page (narrow parser's content-
    # based page-shape heuristics failed to locate it, distinct from a
    # confirmed "the company files no Standalone statements at all") are
    # stuck as a permanent `{"error": ...}` with no chance to ever retry the
    # Consolidated fallback that now exists - confirmed real on Anupam
    # Rasayan (ANURAS): a stale pre-fix `ar_extract_v17_ANURAS_2025_S` cache
    # entry (written before this fallback existed) kept being served as a
    # flat "not found" for every subsequent Standalone EPS request, even
    # though the fallback code itself was correct once actually reached.
    # "_v19" (bumped from "_v18") - this function's manual-mode fallback
    # (`_broad_extraction_to_parsed_shape`, a few lines below) internally
    # calls `document_analysis_engine.extract_line_items()` and caches ITS
    # result under this same key - but that inner function's own EPS
    # basis/anchor logic changed (Standalone-first -> reverted to
    # Consolidated-first) WITHOUT a matching bump here, so a cache entry
    # written under the old logic kept being served indefinitely (90-day
    # TTL) even after the inner fix landed. Confirmed real on ANURAS:
    # `ar_extract_v18_ANURAS_2025_C_manual` held `eps: [6.62, 10.84]`
    # (Standalone) under `basis_used: "broad_extraction"`, silently feeding
    # EPS Growth (Strategy-A, routes through this cache) stale Standalone
    # figures while P/E (Strategy-C, calls `extract_line_items()` directly -
    # no cache at all) was already correctly reading Consolidated 14.56.
    # This is the generic lesson: ANY cache that wraps a call to another
    # module's function must be version-bumped whenever THAT function's
    # logic changes, not just when this function's own code changes.
    # "_v20" (bumped from "_v19") - `_broad_extraction_to_parsed_shape`'s
    # `components` dict now includes "Changes in inventories" as a third
    # COGS component (previously missing entirely) - every cached
    # broad_extraction entry pre-dates this and would keep understating
    # COGS/overstating Gross Profit Margin/Inventory Turnover indefinitely.
    # "_v21" (bumped from "_v20") - `equity_basis` in the broad-extraction
    # fallback now correctly resolves to "owners" when the equity match's
    # own evidence text shows Non-Controlling Interest as a separate line
    # (previously always "consolidated"/"standalone", which could never
    # satisfy any consumer's `== "owners"` check - see the comment on
    # `equity_basis_label` in `_broad_extraction_to_parsed_shape` above).
    # "_v22" (bumped from "_v21") - `equity_full` now genuinely sums NCI
    # onto owners-only equity when confirmable (previously always identical
    # to `equity`), fixing Debt-to-Equity's (Sr No 20) denominator.
    # "_v23" (bumped from "_v22") - the broad-extraction fallback's "pat"
    # alias now tries owners-attributable phrasing FIRST (previously the
    # generic "profit after tax"/"profit for the year" phrasing won first,
    # picking up the TOTAL profit including NCI on a Consolidated statement
    # instead of the owners-only figure) - fixes Net Profit Margin (Sr 16)
    # and ROE's (Sr 18) numerator.
    # "_v26" (bumped from "_v25") - `_sum_after_label` now trims a
    # 3-comparative-column single row (Ind AS transition opening Balance
    # Sheet) down to the first two numbers instead of failing outright -
    # see that function's own comment. Fixes Trade Payables (and anything
    # else routed through `_sum_after_label`) for such filers.
    # "_v25" (bumped from "_v24") - `_RECEIVABLES_LABELS` now includes the
    # singular "trade receivable" (some filers print the Balance Sheet row
    # as "Trade Receivable", not "Trade Receivables" - the plural-only
    # alias list previously found NOTHING for such filers, silently
    # blanking Receivables Turnover/DSO/Cash Conversion Cycle/
    # Receivables-to-Payables even though the value was right there on the
    # page - confirmed real on Prime Fresh Limited's Consolidated Balance
    # Sheet, "Trade Receivable 12  8,891.29  5,490.26").
    # "_v27" (bumped from "_v26") - `_find_variable_opex_note` (Contribution
    # Margin, Sr No 44's variable-cost-beyond-materials component) had a
    # lookahead bug: most "Other Expenses" Note rows print a bare "-"
    # placeholder line for an absent Notes-column footnote reference BEFORE
    # the two real current/prior-year value lines, but the lookahead
    # stopped as soon as it collected ANY 2 numeric-or-dash tokens - so it
    # was reading (placeholder-dash, true-current-year-value) as
    # (current, prior), silently losing the true prior-year figure and
    # UNDERSTATING every matched sub-item's current-year value down to
    # whatever the placeholder happened to be (0.0). Confirmed real on
    # Anupam Rasayan's (ANURAS) FY25 Note 30 "Other Expenses" - e.g.
    # "Freight, Forwarding & Clearing" read as (0.0, 32.05) instead of the
    # real (32.05, 24.19). Now collects up to 3 tokens and always takes the
    # LAST two as the real (current, prior) pair. Also expanded
    # `_VARIABLE_OPEX_NOTE_TERMS` with "utility charges"/"stores and
    # spares" per the ratio sheet's own Sr No 44 examples (Power and Fuel,
    # Consumption of Stores and Spares) - generic Schedule III captions,
    # not unique to this one company. Pre-v27 cache entries understate
    # Contribution Margin's variable-cost component for every company that
    # matched this Note layout.
    from tools.manual_mode import is_manual_mode
    suffix = "_manual_v12" if is_manual_mode() else ""
    # Document-identity tag - see the matching comment in
    # `_get_extracted_financials` (the lock wrapper above), which this
    # function's own cache key must stay in lockstep with (both must derive
    # the SAME ckey for the same inputs, or the lock-guarded re-check after
    # acquiring the lock would look up a different key than the one this
    # function is about to write).
    doc_tag = _document_identity_tag(sym, fiscal_year)
    ckey = f"ar_extract_v29_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}{suffix}_{doc_tag}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    try:
        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            out = {"error": "Annual Report not found for this year."}
            _write_cache(ckey, out)
            return out

        # Manual document-analysis workflow (tools/manual_mode.py): _find_
        # annual_report_pdf() returns a synthetic "manual-upload://SYM_YEAR"
        # marker instead of a real URL when the year is only available from
        # an uploaded PDF, not a live BSE/NSE filing. That marker is not
        # downloadable - read the same locally-cached PDF bytes that
        # tools/manual_document_pipeline.py:_write_shared_ar_caches() and
        # tools/ar_document_cache.py already serve from, instead of trying
        # an HTTP GET on it (which fails immediately: no such URL scheme).
        # This reuses the SAME on-disk PDF cache_ar_document_cache.py's
        # get_ar_pages() reads from - just the byte-fetching step changes;
        # _extract_from_pdf() below (the actual parser) is untouched.
        if pdf_url.startswith("manual-upload://"):
            pdf_cache_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "cache", "ar_pdfs", f"{sym}_{fiscal_year}.pdf")
            pdf_cache_path = os.path.normpath(pdf_cache_path)
            if not os.path.exists(pdf_cache_path):
                out = {"error": f"No uploaded Annual Report PDF found for fiscal year {fiscal_year}.",
                       "source_url": pdf_url}
                _write_cache(ckey, out)
                return out
            with open(pdf_cache_path, "rb") as fh:
                content = fh.read()
        else:
            # NSE archive URLs (nsearchives.nseindia.com) need the cookie-primed
            # NSE session + Referer, and some older ones are .zip-wrapped - route
            # those through the NSE downloader, which handles both. BSE URLs use
            # the normal BSE session as before.
            is_nse_url = "nseindia.com" in pdf_url

            # Retry the download itself (large PDFs, 10-30MB, occasionally hit a
            # transient network blip) before giving up.
            content = None
            last_exc = None
            for attempt in range(2):
                try:
                    if is_nse_url:
                        from tools.nse_annual_reports import download_nse_pdf_bytes
                        content = download_nse_pdf_bytes(pdf_url)
                        if content is None:
                            raise RuntimeError("NSE download/zip-extract returned nothing")
                    else:
                        content = _sess().get(pdf_url, timeout=90).content
                    break
                except Exception as e:
                    last_exc = e
            if content is None:
                print(f"[annual_report_financials] PDF download failed for {sym} FY{fiscal_year} "
                      f"after retries: {last_exc}")
                return {"error": "Could not download the Annual Report right now - please try again "
                                  "in a moment.", "source_url": pdf_url}  # not cached: transient, retry next call

        if len(content) < 50000:
            out = {"error": "Annual Report download failed or too small.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        parsed = _extract_from_pdf(content, consolidated=consolidated)
        # Consolidated-to-standalone fallback (per spec: "use Consolidated
        # first; fall back to Standalone only if Consolidated is
        # unavailable"). Many companies - especially smaller/SME/NSE-only
        # names with no subsidiaries (e.g. AAKASH) - file ONLY standalone
        # statements, so a consolidated=True request legitimately finds no
        # Consolidated statement at all. Rather than N/A every ratio, re-parse
        # the SAME already-downloaded PDF as standalone. `basis_used` records
        # what was actually read so the caller can label it honestly (not
        # claim "consolidated" over standalone data). Only triggers on the
        # specific "not found" error, never on a genuine parse failure of a
        # consolidated statement that IS present.
        if consolidated and isinstance(parsed, dict) and "error" in parsed \
                and "not found in the Annual Report" in parsed["error"]:
            standalone = _extract_from_pdf(content, consolidated=False)
            if "error" not in standalone:
                standalone["source_url"] = pdf_url
                standalone["basis_used"] = "standalone"
                _attach_text_disclosures(standalone, content, fiscal_year)
                _write_cache(ckey, standalone)
                return standalone
        # Symmetric fallback for the reverse case - EPS/EPS-Growth
        # (fetch_eps/fetch_eps_growth in tools/nse_xbrl.py) deliberately
        # request consolidated=False (per the project's "use Standalone for
        # EPS/P-E when both bases are available" policy - a company's own
        # headline EPS/dividend is its Standalone Note 33 figure, not a
        # subsidiary-inflated Consolidated one). A company that files ONLY
        # Consolidated statements (no separate Standalone P&L at all - some
        # holding-company structures) would otherwise legitimately return
        # "not found" for every EPS/EPS-Growth request even though the
        # Annual Report plainly states an EPS figure, just under the
        # Consolidated heading. Re-parse the SAME PDF as consolidated rather
        # than reporting N/A - `basis_used` records what was actually read.
        if not consolidated and isinstance(parsed, dict) and "error" in parsed \
                and "not found in the Annual Report" in parsed["error"]:
            consol = _extract_from_pdf(content, consolidated=True)
            if "error" not in consol:
                consol["source_url"] = pdf_url
                consol["basis_used"] = "consolidated"
                _attach_text_disclosures(consol, content, fiscal_year)
                _write_cache(ckey, consol)
                return consol
        if "error" in parsed:
            bank = _bank_core_parsed(content, fiscal_year)
            if bank is not None:                       # an RBI-format bank: statements read by the bank extractor
                bank["source_url"] = pdf_url
                _attach_text_disclosures(bank, content, fiscal_year)
                _write_cache(ckey, bank)
                return bank
            if content is not None:                      # same fallback in every pipeline (parity with the manual document pipeline)
                # The narrow, exact-phrase/spatial page-locator (tuned for
                # specific real filings) could not find the Balance Sheet/
                # P&L pages in THIS uploaded PDF (both consolidated and
                # standalone attempts). Rather than report the whole
                # extraction as failed, fall back to the broad-alias
                # extractor already proven to read this exact PDF (Strategy-
                # C ratios use it successfully) - never silently returns
                # empty data, and never fabricates a value the broad
                # extractor didn't itself find.
                fallback = _broad_extraction_to_parsed_shape(sym, fiscal_year, consolidated, content=content)
                fallback["source_url"] = pdf_url
                fallback["narrow_parser_error"] = parsed["error"]
                _attach_text_disclosures(fallback, content, fiscal_year)
                _write_cache(ckey, fallback)
                return fallback
            out = {"error": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        parsed["source_url"] = pdf_url
        parsed["basis_used"] = "consolidated" if consolidated else "standalone"
        # Best-effort segment revenue (Ind AS 108 note) - self-validated: only
        # kept if the segments actually reconcile to the P&L's own Revenue
        # figure, so an imperfect page-find/row-parse fails safe (silently
        # None) rather than ever surfacing a wrong breakdown. Never blocks
        # the main P&L result if this fails.
        try:
            revenue_pair = parsed.get("revenue")
            if revenue_pair:
                parsed["segments"] = _extract_segment_revenue(content, revenue_pair[0])
                if not parsed["segments"]:
                    # Formal table not found (or filer never presents one -
                    # see _extract_prose_dominant_segment_pct's docstring
                    # for why that's a real, common, compliant outcome for
                    # a single-reportable-segment company) - fall back to
                    # the prose materiality-justification statement before
                    # giving up entirely.
                    parsed["segments"] = _extract_prose_dominant_segment_pct(content, revenue_pair[0])
        except Exception as e:
            print(f"[annual_report_financials] segment revenue scan skipped: {e}")
            parsed["segments"] = None
        _attach_text_disclosures(parsed, content, fiscal_year)
        _write_cache(ckey, parsed)
        return parsed
    except Exception as e:
        print(f"[annual_report_financials] unexpected error for {sym} FY{fiscal_year}: {e}")
        return {"error": "Something went wrong reading the Annual Report - please try again."}
        # not cached: an unexpected/internal error shouldn't be locked in for a week either


def fetch_inventory_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """inventory_turnover - computed by `tools.ratio_contract` (the single definition; see SPEC['inventory_turnover']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("inventory_turnover", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_gross_profit_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """gross_profit_margin - computed by `tools.ratio_contract` (the single definition; see SPEC['gross_profit_margin']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("gross_profit_margin", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_operating_profit_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """operating_profit_margin - computed by `tools.ratio_contract` (the single definition; see SPEC['operating_profit_margin']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("operating_profit_margin", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week





def fetch_income_statement_flow_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Builds a Revenue -> Profit/Cost node+link "waterfall" for the Overview
    page Sankey, reusing the SAME cached P&L extraction as Gross/Operating
    Profit Margin (`_get_extracted_financials`) - no extra download, no
    invented numbers. Every node value is either a figure read directly off
    the Annual Report P&L, or a subtraction of two such figures (so it always
    reconciles exactly with its parent by construction).

    The depth of the flow adapts to what the statement actually discloses:
      - No COGS lines at all (services co., bank, NBFC, insurer) -> skip the
        Cost of Revenue / Gross Profit split entirely, never fabricate one.
      - COGS present but Employee/Other Expenses/D&A missing -> stop at
        Gross Profit, skip the Operating Profit split.
      - A net financing/other-income drag between operating profit and PBT
        -> shown as a single "Finance cost & other items (net)" outflow.
        A net GAIN (other income exceeds finance costs) is folded silently
        into the profit carried forward rather than drawn as a widening
        ribbon, since sankeys conventionally only ever narrow left-to-right.
      - Tax vs Net Profit only split out when Tax Expense and PAT actually
        reconcile against PBT within tolerance; otherwise collapsed into a
        single "Tax & other adjustments" node (or, if net profit exceeds
        PBT - e.g. a tax credit/NCI reversal - the split is skipped, never
        shown as a negative-cost lie).

    Returns {'applicable': False, 'reason': ...} when there isn't enough to
    build even the shallowest Revenue -> PBT -> Net Profit flow (fiscal-year
    caller should fall back to a coarser, non-AR-sourced source in that
    case). Values are returned in ₹ Cr (matching every other AR ratio in
    this module) - the API layer converts to raw rupees for the frontend.
    Cached 90 days via the shared extraction cache. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_incflow_v10_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{_document_identity_tag(sym, fiscal_year)}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        pbt = parsed.get("pbt")
        pat = parsed.get("pat")
        if revenue is None or revenue[0] in (None, 0):
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if pbt is None or pat is None:
            out = {"applicable": False,
                   "reason": "Could not find both Profit Before Tax and Profit After Tax on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur = round(revenue[0], 2)
        pbt_cur = round(pbt[0], 2)
        pat_cur = round(pat[0], 2)
        tol = max(0.5, abs(rev_cur) * 0.003)  # ₹0.5 Cr or 0.3% of revenue, whichever is larger

        nodes, links = [], []

        def add_node(nid, label, value, category, note=None):
            nodes.append({"id": nid, "label": label, "value": round(value, 2), "category": category, "note": note})

        def add_link(src, tgt, value):
            links.append({"source": src, "target": tgt, "value": round(value, 2)})

        add_node("revenue", "Revenue", rev_cur, "neutral")
        cursor_id, cursor_val = "revenue", rev_cur

        # Business/geographic segments merging into Revenue (only present
        # when `_extract_segment_revenue` found a note that reconciles) -
        # the one place a MERGE (multiple sources -> one node) appears in
        # this otherwise strictly one-parent-per-node tree.
        segments = parsed.get("segments")
        if segments and len(segments) >= 2:
            for i, seg in enumerate(segments):
                sid = f"segment_{i}"
                add_node(sid, seg["label"], seg["value_cr"], "neutral")
                add_link(sid, "revenue", seg["value_cr"])

        # --- Cost of Revenue / Gross Profit -----------------------------------
        components = parsed.get("components") or {}
        if components:
            cogs_cur = sum(v[0] for v in components.values())
            gross_profit = cursor_val - cogs_cur
            if abs(cogs_cur) > tol:
                add_node("cogs", "Cost of Revenue", cogs_cur, "cost",
                         note="Cost of materials consumed + Purchases of stock-in-trade + Changes in inventories")
                add_node("gross_profit", "Gross Profit", gross_profit, "profit")
                add_link(cursor_id, "cogs", cogs_cur)
                add_link(cursor_id, "gross_profit", gross_profit)
                cursor_id, cursor_val = "gross_profit", gross_profit

                # Branch Cost of Revenue into its own reported sub-items (a
                # pure trader may legitimately have only 1 of the 3 - only
                # branch when there's more than one, otherwise the "branch"
                # would just duplicate the parent's own value under a new name).
                real_components = {k: v[0] for k, v in components.items() if abs(v[0]) > tol}
                if len(real_components) > 1:
                    for i, (label, val) in enumerate(real_components.items()):
                        cid = f"cogs_{i}"
                        add_node(cid, label, val, "cost")
                        add_link("cogs", cid, val)

        # --- Operating Expenses / Operating Profit ------------------------------
        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        dep = parsed.get("depreciation")
        if ebe is not None and oe is not None and dep is not None:
            opex_cur = ebe[0] + oe[0] + dep[0]
            operating_profit = cursor_val - opex_cur
            if abs(opex_cur) > tol:
                add_node("opex", "Operating Expenses", opex_cur, "cost",
                         note="Employee Benefit Expense + Other Expenses + Depreciation and Amortisation")
                add_node("operating_profit", "Operating Profit", operating_profit, "profit")
                add_link(cursor_id, "opex", opex_cur)
                add_link(cursor_id, "operating_profit", operating_profit)
                cursor_id, cursor_val = "operating_profit", operating_profit

                # Branch Operating Expenses into its own reported components,
                # same rationale as the Cost of Revenue branch above.
                opex_components = {"Employee Benefit Expense": ebe[0], "Other Expenses": oe[0],
                                    "Depreciation & Amortisation": dep[0]}
                real_opex = {k: v for k, v in opex_components.items() if abs(v) > tol}
                if len(real_opex) > 1:
                    for i, (label, val) in enumerate(real_opex.items()):
                        cid = f"opex_{i}"
                        add_node(cid, label, val, "cost")
                        add_link("opex", cid, val)

        # --- Bridge to Profit Before Tax ---------------------------------------
        # If the Operating Expenses split above succeeded, this bridge is a
        # genuine "below the operating line" item (finance costs, other
        # income, exceptional items). If it didn't (couldn't isolate Employee
        # Benefit Expense/Other Expenses/D&A), this bridge is carrying ALL of
        # operating expenses PLUS finance costs/other income lumped together -
        # label it honestly so it isn't read as a pure financing cost.
        bridge = cursor_val - pbt_cur  # positive = net drag (costs > other income)
        if bridge > tol:
            drag_val = bridge
            remaining = cursor_val - drag_val
            if cursor_id == "operating_profit":
                bridge_label = "Finance Cost & Other Items (net)"
                bridge_note = "Finance Costs less net Other Income/exceptional items between operating profit and PBT"
            elif cursor_id == "gross_profit":
                bridge_label = "Operating & Other Expenses (net)"
                bridge_note = ("Employee Benefit Expense, Other Expenses and Depreciation could not be isolated "
                               "separately, so this combines all operating costs plus Finance Costs, net of Other "
                               "Income/exceptional items")
            else:
                bridge_label = "Total Costs & Expenses (net)"
                bridge_note = ("No goods-based Cost of Revenue or operating-expense breakdown found on the P&L "
                               "page, so this combines every cost line between Revenue and Profit Before Tax")
            add_node("pbt_bridge", bridge_label, drag_val, "cost", note=bridge_note)
            add_link(cursor_id, "pbt_bridge", drag_val)
            add_node("pbt", "Profit Before Tax", pbt_cur, "profit")
            add_link(cursor_id, "pbt", remaining)
            cursor_id, cursor_val = "pbt", pbt_cur
        else:
            # Net gain (or ~flat) between this stage and PBT - fold silently
            # into the carried-forward profit rather than draw a widening
            # ribbon; PBT node still shows the true audited figure.
            add_node("pbt", "Profit Before Tax", pbt_cur, "profit",
                     note=("Includes net Other Income/exceptional gains beyond Finance Costs"
                           if bridge < -tol else None))
            add_link(cursor_id, "pbt", cursor_val)
            cursor_id, cursor_val = "pbt", pbt_cur

        # --- Tax / Net Profit ---------------------------------------------------
        tax_expense = parsed.get("tax_expense")
        tax_cur = tax_expense[0] if tax_expense is not None else None
        implied_deduction = pbt_cur - pat_cur
        if tax_cur is not None and abs((pbt_cur - tax_cur) - pat_cur) <= tol and tax_cur > tol:
            add_node("tax", "Tax", tax_cur, "tax")
            add_node("net_profit", "Net Profit", pat_cur, "profit")
            add_link("pbt", "tax", tax_cur)
            add_link("pbt", "net_profit", pat_cur)
        elif implied_deduction > tol:
            add_node("tax", "Tax & Other Adjustments", implied_deduction, "tax",
                     note="Tax expense could not be cleanly isolated from other PBT-to-PAT items "
                          "(e.g. minority interest) - shown combined.")
            add_node("net_profit", "Net Profit", pat_cur, "profit")
            add_link("pbt", "tax", implied_deduction)
            add_link("pbt", "net_profit", pat_cur)
        else:
            # Net profit >= PBT (tax credit / NCI reversal) - never show a
            # negative-cost node; carry PBT straight through to Net Profit.
            add_node("net_profit", "Net Profit", pat_cur, "profit",
                     note="Net profit exceeds Profit Before Tax (tax credit or minority-interest adjustment) "
                          "- not separable from the P&L page alone.")
            add_link("pbt", "net_profit", pat_cur)

        out = {
            "applicable": True,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "fiscal_year": fiscal_year,
            "basis": "consolidated" if consolidated else "standalone",
            "revenue_cr": rev_cur,
            "nodes": nodes,
            "links": links,
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "Built entirely from the company's own Annual Report P&L - every node is either a reported "
                    "line item or a deterministic subtraction of two reported figures; nothing is estimated.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_net_profit_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """net_profit_margin - computed by `tools.ratio_contract` (the single definition; see SPEC['net_profit_margin']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("net_profit_margin", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_return_on_equity_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """roe - computed by `tools.ratio_contract` (the single definition; see SPEC['roe']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("roe", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_return_on_capital_employed_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """roce - computed by `tools.ratio_contract` (the single definition; see SPEC['roce']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("roce", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week




def _compute_total_debt(parsed, lease_basis="basis1"):
    """Single shared source-of-truth assembly of Total Debt (Sr No 20),
    reused by every derived ratio (Debt-to-Equity, Debt Ratio, Enterprise
    Value) instead of each duplicating its own a+b+c logic - the drift
    between those duplicated copies (only Borrowings, no Notes fallback, no
    Finance-Costs cross-check) was the systemic under-capture this rebuild
    fixes (DMart/Maruti-style false-zeros).

    Total Debt = a + (b if lease_basis == "basis1") + c:
      a) Borrowings (Long-term + Short-term + Current Maturities), verified
         against the Notes-to-Accounts breakup (`borrowings_note_total_cur`):
           - face value ₹0/missing but Notes disclose real debt -> Notes
             total is used instead (flagged, reduced confidence) - this is
             the specific fix for a rigid single-line match silently
             reporting a debt-free company that Isn't.
           - both found but diverge >5% -> face value kept (Balance Sheet is
             authoritative) but flagged at reduced confidence.
      b) Lease Liabilities (Non-current + Current). Per the authoritative
         Sr No 33 (Net Debt/EBITDA) spec, Basis 1 (default) INCLUDES these in
         Total Debt - the post-Ind-AS-116 view; Basis 2 (opt-in
         `lease_basis="basis2"`) EXCLUDES them, for callers wanting the
         traditional pre-Ind-AS-116 definition. Always surfaced in
         `components` regardless of which basis is active.
      c) Other Financial Liabilities - only the sub-items passing the
         Three-Part Test (`_other_financial_liabilities_qualifying`) are
         added; never a guess when no sub-item breakup was printed.

    Hard Finance-Costs cross-check: if NEITHER Borrowings (face or Notes) nor
    any of the above signal any debt at all, but Finance Costs shows a real,
    non-trivial interest expense, that flatly contradicts "debt-free" - this
    is reported as an extraction failure (`applicable: False`), NEVER as a
    silently-confident Total Debt of ₹0. Only when there's genuinely no
    interest expense either does a ₹0 Total Debt stand as a real result
    (same "sum what's there" principle as every other component-summed
    ratio in this file).

    Returns a dict: on success, {"applicable": True, "total_debt_cur",
    "components", "confidence", "estimated", "lease_basis", "note"}; on the
    Finance-Costs cross-check failure, {"applicable": False, "reason"}.
    Never raises."""
    lt = parsed.get("lt_borrowings")
    st = parsed.get("st_borrowings")
    cm = parsed.get("current_maturities")
    duplicate_row = False
    if lt is not None and st is not None and tuple(lt) == tuple(st) and any(x for x in lt if x):
        # an identical (current, prior) pair in both slots is the SAME physical row matched twice (a generic
        # "Borrowings" caption searched under both liability sections), never two equal debts - count it once
        st, duplicate_row = None, True
    finance_costs = parsed.get("finance_costs")
    fc_cur = finance_costs[0] if finance_costs is not None else None
    borrowings_label_found = parsed.get("borrowings_face_label_found", False)
    note_total = parsed.get("borrowings_note_total_cur")
    note_subitems = parsed.get("borrowings_note_subitems")

    lt_cur = lt[0] if lt is not None else 0.0
    st_cur = st[0] if st is not None else 0.0
    cm_cur = cm[0] if cm is not None else 0.0
    face_borrowings_cur = lt_cur + st_cur + cm_cur
    components_found = sum(1 for v in (lt, st, cm) if v is not None)

    # a) Borrowings - mandatory Notes verification, not face-value only.
    a_cur = face_borrowings_cur
    a_source = "face"
    note_mismatch = False
    if note_total is not None:
        if face_borrowings_cur == 0 and note_total > 0:
            a_cur = note_total
            a_source = "note_fallback"
        elif face_borrowings_cur > 0 and abs(face_borrowings_cur - note_total) > 0.05 * max(
                face_borrowings_cur, note_total):
            note_mismatch = True  # face value kept, but flagged

    # b) Lease Liabilities - computed BEFORE the Finance-Costs cross-check
    # below, since Ind-AS-116 lease interest is itself a legitimate,
    # non-Borrowings source of Finance Costs (confirmed on HUL FY26: zero
    # Borrowings anywhere, but ₹1,478 Cr of Lease Liabilities plausibly
    # explains the ₹33 Cr Finance Costs on its own) - the cross-check must
    # not mistake lease interest for evidence of unparsed Borrowings.
    # Lease liabilities (component b): the broad extractor supplies one TOTAL
    # (non-current + current rows summed); the narrow parser supplies the two
    # sections separately. A lease line that simply was not extracted is
    # UNKNOWN, never 0 - the only thing that supports a genuine 0 is positive
    # evidence the balance sheet carries no lease line at all
    # (`lease_evidence == "none_on_balance_sheet"`).
    lease_total = parsed.get("lease_liabilities_total")
    lease_nc = parsed.get("lease_liabilities_nc")
    lease_cur_bs = parsed.get("lease_liabilities_cur")
    lease_prior = None
    if lease_total is not None:
        b_cur = lease_total[0]
        lease_prior = lease_total[1]
        lease_status = "found"
    elif lease_nc is not None or lease_cur_bs is not None:
        b_cur = (lease_nc[0] if lease_nc is not None else 0.0) + (lease_cur_bs[0] if lease_cur_bs is not None else 0.0)
        lease_prior = ((lease_nc[1] if lease_nc is not None else 0.0) + (lease_cur_bs[1] if lease_cur_bs is not None else 0.0)) \
            if all(x is None or x[1] is not None for x in (lease_nc, lease_cur_bs)) else None
        lease_status = "found"
    elif parsed.get("lease_evidence") == "none_on_balance_sheet":
        b_cur, lease_prior, lease_status = 0.0, 0.0, "none_on_balance_sheet"
    else:
        b_cur, lease_status = 0.0, "not_found"
    include_leases = (lease_basis == "basis1")

    # Hard Finance-Costs cross-check - fires only when EVERY debt signal
    # (face Borrowings, Notes Borrowings, Lease Liabilities) came back
    # empty/zero, so a_cur is still 0 at this point, yet the company is
    # visibly paying real interest with no legitimate source for it.
    if a_cur == 0 and note_total is None and b_cur <= 0 and fc_cur is not None and fc_cur > 1.0:
        if borrowings_label_found:
            return {"applicable": False,
                    "reason": "A 'Borrowings' line is present on the Balance Sheet but its value could not be "
                              f"parsed, and Finance Costs of ₹{fc_cur:,.2f} Cr indicate real interest-bearing "
                              "debt exists - reporting Total Debt as ₹0 would be misleading, so this is flagged "
                              "as a likely extraction failure rather than a debt-free company."}
        return {"applicable": False,
                "reason": f"No Borrowings line was found on the Balance Sheet or in its Notes, but Finance Costs "
                          f"of ₹{fc_cur:,.2f} Cr indicate this company does carry interest-bearing debt - "
                          "reporting Total Debt as ₹0 would be misleading, so this is flagged rather than "
                          "silently reported as debt-free."}

    # c) Other Financial Liabilities - Three-Part Test qualifying sub-items only
    ofl_nc = parsed.get("other_fin_liab_nc")
    ofl_cur = parsed.get("other_fin_liab_cur")
    ofl_candidates = None
    if ofl_nc is None and ofl_cur is None and parsed.get("ofl_note"):
        # the face has no sub-items to test, but the Notes tables were read and classified (Three-Part Test): that IS an evaluation
        _n = parsed["ofl_note"]
        ofl_nc = {"qualifying_cur": _n.get("qualifying_cur"), "qualifying_prior": _n.get("qualifying_prior"), "source": "note"}
        ofl_candidates = _n.get("candidates") or None
    c_nc_cur = ofl_nc.get("qualifying_cur") if ofl_nc else None
    c_cur_cur = ofl_cur.get("qualifying_cur") if ofl_cur else None
    c_cur = (c_nc_cur or 0.0) + (c_cur_cur or 0.0)

    total_debt_cur = a_cur + (b_cur if include_leases else 0.0) + c_cur

    confidence = 1.0
    estimated = False
    if duplicate_row:
        confidence = min(confidence, 0.9)
        estimated = True
    if components_found < 3:
        confidence = min(confidence, 0.95)
    if include_leases and lease_status == "not_found":
        # Leases could not be read and there is no evidence they do not exist:
        # the Total Debt shown omits an unknown amount - flagged, not "included".
        confidence = min(confidence, 0.85)
        estimated = True
    ofl_evaluated = ofl_nc is not None or ofl_cur is not None
    if not ofl_evaluated:
        # Debt-like Other Financial Liabilities (Three-Part Test) were not
        # evaluated on this extraction path - they are excluded by default,
        # never silently assumed to be zero.
        confidence = min(confidence, 0.9)
        estimated = True
    if a_source == "note_fallback":
        confidence = min(confidence, 0.9)
        estimated = True
    if note_mismatch:
        confidence = min(confidence, 0.85)
        estimated = True

    components_out = {
        "a) Borrowings (Long-term + Short-term + Current Maturities)": round(a_cur, 2),
        "b) Lease Liabilities": round(b_cur, 2) if lease_status != "not_found" else None,
        "b) Lease Liabilities status": ("extracted" if lease_status == "found" else
                                        "none on balance sheet" if lease_status == "none_on_balance_sheet" else
                                        "NOT EXTRACTED - total debt omits any lease liabilities"),
        "b) Lease Liabilities included in Total Debt": include_leases and lease_status != "not_found",
        "c) Other Financial Liabilities (qualifying, Three-Part Test)": round(c_cur, 2),
    }
    if ofl_candidates:
        components_out["c) Debt-like items NOT included (not accepted by the Three-Part Test terms)"] = [
            {"label": c["label"], "amount_cr": round(c["amount_cr"], 2)} for c in ofl_candidates]
    if a_source == "note_fallback":
        components_out["a) Borrowings source"] = "Notes breakup (Balance Sheet face value was ₹0/missing)"
    if note_mismatch:
        components_out["a) Borrowings - face value"] = round(face_borrowings_cur, 2)
        components_out["a) Borrowings - Notes cross-check total"] = round(note_total, 2)

    note_parts = [f"Total Debt = a (Borrowings, cross-checked against the Notes breakup) + "
                  f"b (Lease Liabilities, {'included' if include_leases else 'excluded'} - "
                  f"{'Basis 1 (default)' if include_leases else 'Basis 2'}) + c (qualifying Other Financial "
                  "Liabilities, Three-Part Test)."]
    if a_source == "note_fallback":
        note_parts.append(f"Borrowings' Balance Sheet face value was ₹0/missing but its Notes breakup disclosed "
                           f"real debt (₹{note_total:,.2f} Cr across {note_subitems} sub-item(s)) - used instead "
                           "of silently reporting a false ₹0.")
    if note_mismatch:
        note_parts.append(f"Face value (₹{face_borrowings_cur:,.2f} Cr) and the Notes breakup "
                           f"(₹{note_total:,.2f} Cr) diverge by more than 5% - the face value is used (the "
                           "Balance Sheet is authoritative) but flagged at reduced confidence.")

    prior_ok = (lt is None or lt[1] is not None) and (st is None or st[1] is not None) \
        and (cm is None or cm[1] is not None) and (lease_prior is not None or not include_leases) \
        and components_found > 0 and c_cur == 0.0
    total_debt_prior = None
    if prior_ok:
        a_prior = sum(x[1] for x in (lt, st, cm) if x is not None)
        total_debt_prior = a_prior + ((lease_prior or 0.0) if include_leases else 0.0)
    return {
        "applicable": True,
        "total_debt_prior": total_debt_prior,
        "lease_status": lease_status,
        "total_debt_cur": total_debt_cur,          # UNROUNDED - rounding is for display only
        "components": components_out,
        # unrounded building blocks (display provenance only - the arithmetic above is unchanged)
        "components_raw": {"borrowings": a_cur, "leases": (b_cur if lease_status != "not_found" else None),
                           "leases_included": bool(include_leases and lease_status != "not_found"),
                           "ofl": c_cur, "ofl_evaluated": bool(ofl_evaluated), "lease_status": lease_status},
        "confidence": confidence,
        "estimated": estimated,
        "lease_basis": lease_basis,
        "note": " ".join(note_parts),
    }


def fetch_debt_to_equity_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """debt_to_equity - computed by `tools.ratio_contract` (the single definition; see SPEC['debt_to_equity']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("debt_to_equity", symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)


        # not cached: an unexpected/transient error shouldn't be locked in for a week


        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_debt_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """debt_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['debt_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("debt_ratio", symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_interest_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """interest_coverage_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['interest_coverage_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("interest_coverage_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_financial_leverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """financial_leverage_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['financial_leverage_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("financial_leverage_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_eps_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`eps` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("eps", 'Basic EPS (attributable to owners)', '₹', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_book_value_per_share_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """bvps - computed by `tools.ratio_contract` (the single definition; see SPEC['bvps']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("bvps", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_shares_outstanding_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`shares_outstanding` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("shares_outstanding", 'Equity Shares Outstanding', 'shares', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_revenue_from_operations_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`revenue` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("revenue", 'Revenue from Operations', '₹ Cr', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_dividend_per_share_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`dps` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("dps", 'Dividend per Share (declared for the FY)', '₹', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_ebitda_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`ebitda` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("ebitda", 'EBITDA (EBIT + Depreciation & Amortisation)', '₹ Cr', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_total_debt_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """`total_debt` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("total_debt", 'Total Debt', '₹ Cr', symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_cash_and_equivalents_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`cash` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("cash", 'Cash and Cash Equivalents', '₹ Cr', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_receivables_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """receivables_turnover - computed by `tools.ratio_contract` (the single definition; see SPEC['receivables_turnover']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("receivables_turnover", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_payables_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """payables_turnover - computed by `tools.ratio_contract` (the single definition; see SPEC['payables_turnover']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("payables_turnover", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_asset_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """asset_turnover - computed by `tools.ratio_contract` (the single definition; see SPEC['asset_turnover']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("asset_turnover", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_fixed_asset_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """fixed_asset_turnover - computed by `tools.ratio_contract` (the single definition; see SPEC['fixed_asset_turnover']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("fixed_asset_turnover", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_current_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """current_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['current_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("current_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_quick_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """quick_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['quick_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("quick_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_cash_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """cash_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['cash_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("cash_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_days_working_capital_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """days_working_capital - computed by `tools.ratio_contract` (the single definition; see SPEC['days_working_capital']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("days_working_capital", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_receivables_to_payables_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """receivables_to_payables - computed by `tools.ratio_contract` (the single definition; see SPEC['receivables_to_payables']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("receivables_to_payables", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_net_debt_to_ebitda_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """net_debt_to_ebitda - computed by `tools.ratio_contract` (the single definition; see SPEC['net_debt_to_ebitda']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("net_debt_to_ebitda", symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_debt_service_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """dscr - computed by `tools.ratio_contract` (the single definition; see SPEC['dscr']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("dscr", symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_cash_flow_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """cash_flow_coverage_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['cash_flow_coverage_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("cash_flow_coverage_ratio", symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_free_cash_flow_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """free_cash_flow - computed by `tools.ratio_contract` (the single definition; see SPEC['free_cash_flow']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("free_cash_flow", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_fcf_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """fcf_margin - computed by `tools.ratio_contract` (the single definition; see SPEC['fcf_margin']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("fcf_margin", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_operating_cash_flow_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """ocf_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['ocf_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("ocf_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_capex_intensity_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """capex_intensity - computed by `tools.ratio_contract` (the single definition; see SPEC['capex_intensity']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("capex_intensity", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_working_capital_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """working_capital_turnover - computed by `tools.ratio_contract` (the single definition; see SPEC['working_capital_turnover']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("working_capital_turnover", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_ocf_to_net_profit_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """ocf_to_net_profit - computed by `tools.ratio_contract` (the single definition; see SPEC['ocf_to_net_profit']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("ocf_to_net_profit", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_roic_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """roic - computed by `tools.ratio_contract` (the single definition; see SPEC['roic']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("roic", symbol, name, fiscal_year, consolidated, lease_basis=lease_basis)
        # not cached: an unexpected/transient error shouldn't be locked in for a week




def fetch_effective_tax_rate_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """effective_tax_rate - computed by `tools.ratio_contract` (the single definition; see SPEC['effective_tax_rate']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("effective_tax_rate", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_contribution_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """contribution_margin - computed by `tools.ratio_contract` (the single definition; see SPEC['contribution_margin']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("contribution_margin", symbol, name, fiscal_year, consolidated)


        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_eps_growth_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """eps_growth_rate - computed by `tools.ratio_contract` (the single definition; see SPEC['eps_growth_rate']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("eps_growth_rate", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_dividend_payout_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """dividend_payout_ratio - computed by `tools.ratio_contract` (the single definition; see SPEC['dividend_payout_ratio']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("dividend_payout_ratio", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_operating_cash_flow_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """`operating_cash_flow` normalized fact (tools.fundamental_fact_store) in the legacy fetch response shape. Cached; never raises."""
    return _contract_fact_fetch("operating_cash_flow", 'Net Cash Flow from Operating Activities', '₹ Cr', symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_altman_z_score_components_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """altman_z_score - computed by `tools.ratio_contract` (the single definition; see SPEC['altman_z_score']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("altman_z_score", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_piotroski_f_score_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """piotroski_f_score - computed by `tools.ratio_contract` (the single definition; see SPEC['piotroski_f_score']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("piotroski_f_score", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_beneish_m_score_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """beneish_m_score - computed by `tools.ratio_contract` (the single definition; see SPEC['beneish_m_score']).
    This wrapper only builds the legacy response shape. Cached; never raises."""
    return _contract_fetch("beneish_m_score", symbol, name, fiscal_year, consolidated)
        # not cached: an unexpected/transient error shouldn't be locked in for a week


# --------------------------------------------------------------------------- #
# BANK/NBFC EXTRACTION -- Sr No 58 (Net Interest Margin) is the FIRST ratio
# in this suite that needs data from a Bank/NBFC's own financial
# statements. Every ratio 1-57 excludes Banks/NBFC/Insurance because they
# file in the RBI-prescribed format (Form A Balance Sheet / Form B Profit
# and Loss Account) -- "Interest Earned"/"Interest Expended"/"Advances"/
# "Investments", NOT the Ind AS Schedule III format `_extract_from_pdf`
# above is built for (no "Revenue from Operations", no COGS lines). This
# is a genuinely SEPARATE, lighter-weight parser -- reuses the same PDF
# download/annual-report-lookup infrastructure (`_find_annual_report_pdf`,
# `_sess`, the NSE downloader) and the same generic `_find_row_values`
# row-matching helper, but its OWN page-detection logic, since the
# Schedule-III COGS/shape-based detection in `_extract_from_pdf` would
# never match a bank filing at all.
#
# KNOWN FIRST-PASS LIMITATION (flagged, not yet hardened): this scanner
# does not yet have the same anti-decoy protections the Schedule-III
# extractor accumulated over many sessions (MD&A/segment-note false-
# positive guards, Notes-page exclusions). It should be expected to need
# the same kind of iterative real-filing hardening once tested against a
# range of actual bank/NBFC Annual Reports.
# --------------------------------------------------------------------------- #
_BANK_INTEREST_INCOME_LABELS = ["interest earned", "interest income"]
_BANK_INTEREST_EXPENSE_LABELS = ["interest expended", "interest expense"]
_BANK_ADVANCES_LABELS = ["advances", "gross advances"]
_BANK_INVESTMENTS_LABELS = ["investments"]
_BANK_DEPOSITS_LABELS = ["deposits"]
# CASA Ratio (Sr No 59) numerator components -- the RBI Schedule 3 Deposits
# breakup captions these "Demand Deposits" (= Current Account deposits) and
# "Savings Bank Deposits" (= Savings Account deposits), NEVER "Term
# Deposits" (the higher-cost complement, deliberately excluded).
_BANK_DEMAND_DEPOSITS_LABELS = ["demand deposits"]
_BANK_SAVINGS_DEPOSITS_LABELS = ["savings bank deposits", "savings deposits"]
# Gross NPA % (Sr No 60) numerator -- the RBI IRAC-norms Asset Quality
# disclosure in Notes to Accounts, NEVER Net NPA (Sr No 61, a distinct,
# always-lower, post-provision figure).
_BANK_GROSS_NPA_LABELS = ["gross non-performing assets", "gross npas", "gross npa"]
# Net NPA % (Sr No 61) -- both searched DIRECTLY in the Asset Quality note
# (most bank filings disclose Net NPA and Net Advances as their own
# explicit lines alongside Gross NPA/Gross Advances, rather than requiring
# a Total-Provisions subtraction this parser can't reliably source).
_BANK_NET_NPA_LABELS = ["net non-performing assets", "net npas", "net npa"]
_BANK_NET_ADVANCES_LABELS = ["net advances"]
# Capital Adequacy Ratio / CRAR (Sr No 63) -- Basel III disclosure in Notes
# to Accounts. Tier I + Tier II Capital and Risk-Weighted Assets are the
# spec's own formula components; a directly-disclosed "CRAR (%)"/"Capital
# Adequacy Ratio (%)" summary line (present in virtually every bank's
# Basel III Pillar 3 table) is used as a fallback when the two capital
# tiers or RWA aren't individually found -- the reported figure itself,
# not a recomputation, so it's still a faithful (if less granular) read.
_BANK_TIER1_CAPITAL_LABELS = ["tier i capital", "tier 1 capital", "common equity tier 1", "cet1 capital"]
_BANK_TIER2_CAPITAL_LABELS = ["tier ii capital", "tier 2 capital"]
_BANK_RWA_LABELS = ["risk weighted assets", "risk-weighted assets", "total risk weighted assets"]
_BANK_CRAR_DIRECT_LABELS = ["capital adequacy ratio", "crar"]
# Cost-to-Income Ratio (Sr No 65) -- both on the SAME P&L page as Interest
# Earned/Interest Expended (RBI Form B). "Other Income" is a mandatory
# standalone P&L line for banks (Schedule 14), distinct from the "Other
# Income" fallback PAT/generic-label pattern used elsewhere in this file.
_BANK_EMPLOYEE_COST_LABELS = ["employees cost", "employee cost", "payments to and provisions for employees"]
_BANK_OTHER_OPEX_LABELS = ["other operating expenses"]
_BANK_OTHER_INCOME_LABELS = ["other income"]


def _bank_row(text, labels):
    """`_find_row_values` for a MONEY row of a bank statement, converted to Rs Crore using the unit declared on the same
    page. (Percent rows - the directly disclosed CRAR - are read with plain `_find_row_values`.)"""
    return _scale(_find_row_values(text, labels), _unit_factor(text))


def fetch_provision_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Provision Coverage Ratio (Sr 62) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "provision_coverage_ratio", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio provision_coverage_ratio failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def fetch_credit_to_deposit_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Credit-to-Deposit Ratio (Sr 64) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "credit_to_deposit_ratio", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio credit_to_deposit_ratio failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def _extract_bank_from_pdf(pdf_bytes, consolidated=True):
    """Bank/NBFC statement reader -> `tools.bank_extractor` (layout-aware, identity-checked, unit-normalised, standalone
    basis by policy). `consolidated` is ignored on purpose. Returns the extractor's dict (+ 'disclosed' ratios) or
    {'error': reason}."""
    try:
        import fitz
        from tools import bank_extractor as be
    except Exception as e:
        return {"error": f"bank extractor unavailable: {e}"}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return {"error": f"PDF read failed: {e}"}
    r = be.extract_bank(doc, "standalone")
    rng = r.pop("_disclosure_range", None)
    if rng:
        r["disclosed"] = be.find_disclosed_ratios(doc, rng)
        for _k, _v in be.find_disclosed_prose(doc, rng, [n for n in ("pcr_pct", "gross_npa_pct", "net_npa_pct")
                                                         if n not in r["disclosed"]]).items():
            r["disclosed"][_k] = _v
        r["capital_amounts"] = be.find_capital_amounts(doc, rng)
        try:
            r["core"] = be.extract_bank_core(doc, r)
        except Exception as _e:
            print(f"[annual_report_financials] bank core facts skipped: {_e}")
    if "deposits" not in r and "advances" not in r:
        nb = be.extract_nbfc(doc)                       # not an RBI bank layout: try Ind AS NBFC / HFC statements
        if "loans" in nb and "interest_income" in nb:
            rng2 = nb.pop("_disclosure_range", None)
            nb["disclosed"] = be.find_disclosed_ratios(doc, rng2) if rng2 else {}
            for _k, _v in be.find_disclosed_prose(doc, rng2, [n for n in ("pcr_pct", "gross_npa_pct", "net_npa_pct")
                                                              if n not in nb["disclosed"]]).items():
                nb["disclosed"][_k] = _v
            nb["capital_amounts"] = be.find_capital_amounts(doc, rng2) if rng2 else None
            return nb
    if "deposits" not in r and "advances" not in r:
        r["error"] = ("Could not find a standalone RBI-format balance sheet (Deposits / Advances / Investments / Borrowings "
                      "rows) in the Annual Report - this does not look like a bank filing.")
    return r


def _get_extracted_bank_financials(symbol, name, fiscal_year, consolidated=True):
    """Shared, cached PDF fetch + parse for Bank/NBFC ratios (Sr No 58+),
    mirroring `_get_extracted_financials`'s own download/retry/consolidated-
    to-standalone-fallback logic, but calling `_extract_bank_from_pdf`
    instead of the Schedule-III `_extract_from_pdf`. Cached 90 days --
    EXCEPT network/IO failures. Never raises."""
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v6" cache-busts extractions cached before Employee Cost/Other
    # Opex/Other Income (Sr No 65) were added -- see the analogous
    # "_v2".."_v5" cache-key comment on `_get_extracted_financials`.
    ckey = f"ar_bank_extract_v8_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    try:
        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            out = {"error": "Annual Report not found for this year."}
            _write_cache(ckey, out)
            return out

        is_nse_url = "nseindia.com" in pdf_url
        content = None
        last_exc = None
        for attempt in range(2):
            try:
                if is_nse_url:
                    from tools.nse_annual_reports import download_nse_pdf_bytes
                    content = download_nse_pdf_bytes(pdf_url)
                    if content is None:
                        raise RuntimeError("NSE download/zip-extract returned nothing")
                else:
                    content = _sess().get(pdf_url, timeout=90).content
                break
            except Exception as e:
                last_exc = e
        if content is None:
            print(f"[annual_report_financials] Bank PDF download failed for {sym} FY{fiscal_year} "
                  f"after retries: {last_exc}")
            return {"error": "Could not download the Annual Report right now -- please try again "
                              "in a moment.", "source_url": pdf_url}

        if len(content) < 50000:
            out = {"error": "Annual Report download failed or too small.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        parsed = _extract_bank_from_pdf(content, consolidated=consolidated)
        if consolidated and isinstance(parsed, dict) and "error" in parsed \
                and "not find the consolidated" in parsed["error"]:
            standalone = _extract_bank_from_pdf(content, consolidated=False)
            if "error" not in standalone:
                standalone["source_url"] = pdf_url
                standalone["basis_used"] = "standalone"
                _write_cache(ckey, standalone)
                return standalone

        if "error" not in parsed:
            parsed["source_url"] = pdf_url
        else:
            parsed["source_url"] = pdf_url
        _write_cache(ckey, parsed)
        return parsed
    except Exception as e:
        print(f"[annual_report_financials] Bank extraction failed for {symbol} FY{fiscal_year}: {e}")
        return {"error": "Something went wrong reading the Annual Report -- please try again."}


def fetch_net_interest_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Net Interest Margin (Sr 58) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "net_interest_margin", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio net_interest_margin failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def fetch_casa_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """CASA Ratio (Sr 59) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "casa_ratio", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio casa_ratio failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def fetch_gross_npa_pct_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Gross NPA % (Sr 60) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "gross_npa_pct", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio gross_npa_pct failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def fetch_net_npa_pct_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Net NPA % (Sr 61) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "net_npa_pct", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio net_npa_pct failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def fetch_capital_adequacy_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Capital Adequacy Ratio / CRAR (Sr 63) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "capital_adequacy_ratio", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio capital_adequacy_ratio failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def fetch_cost_to_income_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """Cost-to-Income Ratio (Sr 65) - computed by `tools.bank_ratios` from the bank's identity-checked STANDALONE RBI statements
    (`tools.bank_extractor`); `consolidated` is accepted for API compatibility but bank ratios are standalone by
    policy. Never raises."""
    try:
        from tools import bank_ratios
        return bank_ratios.compute(__import__(__name__, fromlist=['x']), "cost_to_income_ratio", symbol, name, fiscal_year)
    except Exception as e:
        print(f"[annual_report_financials] bank ratio cost_to_income_ratio failed for {symbol}: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report - please try again."}


def _install_bank_guards():
    from tools import ratio_contract as _rc
    for _name, _key in (("net_interest_margin", "net_interest_margin"), ("casa_ratio", "casa_ratio"),
                        ("gross_npa_pct", "gross_npa_pct"), ("net_npa_pct", "net_npa_pct"),
                        ("capital_adequacy_ratio", "capital_adequacy_ratio"), ("cost_to_income_ratio", "cost_to_income_ratio"),
                        ("provision_coverage_ratio", "provision_coverage_ratio"), ("credit_to_deposit_ratio", "credit_to_deposit_ratio")):
        _fn = f"fetch_{_name}_from_annual_report"
        globals()[_fn] = _rc.bank_guard(_key)(globals()[_fn])


_install_bank_guards()
