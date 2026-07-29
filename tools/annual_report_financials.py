"""
Annual Report financials — Inventory Turnover computed from the company's own
full Annual Report PDF (BSE's `AnnualReport_New` API), per the Source Hierarchy
spec: "1. Annual Report (Audited Financial Statements)" ranks above the
quarterly/annual Reg-33 result filing.

Why this is BETTER than the Reg-33 filing, not just "more compliant":
  - The Annual Report's Balance Sheet + P&L pages extract CLEANLY with plain
    linear text (label and both years' values sit on one line) — unlike the
    Reg-33 filing's tables, which come out jumbled (label block, then a
    separate number block) and needed complex position-based reconstruction.
  - It shows the CURRENT and PRIOR year side by side in ONE document, so the
    prior-year comparator is always on the same (restated) basis as the
    current year — no separate-filing mismatch to patch (see
    bse_restated_inventory.py, which existed to fix exactly that problem for
    the Reg-33 source).

Canonical row-label matching uses the synonym lists from the ratio
specification (Mis "Extra" column) so this generalises beyond Tata Steel's
exact wording.

Cached 90 days (an Annual Report never changes once published). Never raises.
"""

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

CACHE_TTL = 90 * 24 * 3600

# Per-(symbol, year, consolidated) locks guarding `_get_extracted_financials`.
# Every ratio derived from the same Annual Report calls it independently, and
# a first-ever visit to a company's Fundamental Ratios page fires 20-30 of
# those calls at once (confirmed: a 10-30MB PDF download + parse takes ~7s).
# Without a lock here, EVERY one of those concurrent calls sees a cache miss
# and independently re-downloads + re-parses the SAME PDF — a classic cache
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
# filing — "Profit" extracts as "Proﬁt", "benefits" as "beneﬁts", "efficient"
# as "efﬁcient" — invisible to every "profit"/"benefit"-containing label in
# this file. Confirmed as the root cause of Eternal/Zomato's ENTIRE
# Consolidated P&L page (PBT, PAT, Employee Benefit Expense) being
# unreadable, cascading into 9+ ratios (NPM, ROA, ROE, ROCE, Interest
# Coverage, P/E, P/S, Earnings Yield, EV/EBITDA) all failing simultaneously
# for that one company. `_page_text()` normalises this immediately after
# every `page.get_text()` call — fixed ONCE at the source, rather than
# patching every downstream label list.
_LIGATURE_MAP = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st",
})


def _page_text(page):
    """Ligature-normalised page.get_text() — use this everywhere instead of
    calling page.get_text() directly (see module-level comment above)."""
    return (page.get_text() or "").translate(_LIGATURE_MAP)


# --- Canonical row-label synonyms (from the ratio spec) ---------------------
_COGS_LABELS = {
    "Cost of materials consumed": [
        "cost of materials consumed", "material consumed", "materials consumed",
        "raw material consumed", "raw materials consumed", "consumption of raw materials",
        "consumption of raw material", "consumption of materials", "material costs",
        "material cost", "cost of raw materials consumed", "cost of material consumed",
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
# Depreciation & Amortisation Expense — a P&L line item SEPARATE from
# Employee Benefit Expense/Other Expenses. Needed for Operating Profit
# Margin (Sr No 15), which per spec is EBIT-basis (Revenue − COGS − Employee
# Costs − Other Expenses − D&A), NOT EBITDA-basis — D&A is a real operating
# cost of running the business and must be deducted, not added back.
_DEPRECIATION_LABELS = [
    "depreciation and amortisation expense", "depreciation and amortization expense",
    "depreciation, amortisation and impairment expense", "depreciation & amortisation expense",
    "depreciation and amortisation", "depreciation and amortization",
]
# For CONSOLIDATED statements, "Profit for the year" often means the TOTAL
# including Non-Controlling/Minority Interest — per spec, Net Profit Margin
# must use the portion attributable to OWNERS only. Tried first, in priority
# order; the generic labels (which fetch the same figure standalone reports
# call "Profit for the year") are the fallback for filings with no NCI split.
_PAT_OWNERS_LABELS = [
    "profit for the year attributable to owners of the company",
    "profit for the year attributable to owners of the parent",
    "profit attributable to owners of the company",
    "profit attributable to owners of the parent",
    # "attributed to" (past participle) is a distinct, equally common Ind AS
    # phrasing from "attributable to" — e.g. "Profit for the year attributed
    # to: Owners of the parent" followed on the SAME page by "Other
    # comprehensive income for the year ATTRIBUTABLE to: ..." (the OCI line
    # uses the other wording) — including the "profit for the year/period"
    # prefix keeps this from ever matching that OCI line by mistake.
    "profit for the year attributed to",
    "profit for the period attributed to",
    "net profit for the year attributed to",
    # Tata Steel's consolidated filing captions this as "Profit/(loss) from
    # for the year attributable to:" — an extra "from" token between the
    # (already-normalised) "Profit" and "for the year" that no other filing
    # seen so far includes. Listed literally rather than generalised into a
    # regex, since this is the only filing observed with it.
    "profit from for the year attributable to",
    "attributable to owners of the company",
    "attributable to owners of the parent",
    "attributable to the owners of the company",
    "attributable to shareholders of the company",
    # Same "/(Loss)" suffix as `_PAT_GENERIC_LABELS` below, but on the
    # owners-attributable caption — a loss-making-history consolidated filing
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
    # year" — `_find_pl_row` already normalises this via `_strip_formula_refs`
    # before matching, but these are kept explicitly in the canonical list too
    # (belt-and-suspenders): a match must never be skipped just because of
    # the "/(Loss)" suffix — that suffix is a presentation convention (the
    # company reserves the right to report either outcome), not a sign that
    # the row is something other than PAT.
    "profit/(loss) for the year", "profit/(loss) for the period",
    "profit/(loss) after tax", "net profit/(loss) for the year",
    "net profit/(loss) for the period",
]
# For CONSOLIDATED statements, "Total equity" often includes Non-Controlling
# Interest — per spec, ROE (Sr No 18) must use only the owners' portion.
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
# Non-Controlling Interest — its own always-separate Balance Sheet line
# under Ind AS (see comment on `_EQUITY_SHARE_CAPITAL_LABELS` below). Needed
# for Debt-to-Equity (Sr No 23): unlike ROE, D/E's numerator (Total Debt) is
# the WHOLE consolidated entity's debt, not just the portion funded by the
# parent's own shareholders — so its denominator must be the WHOLE entity's
# equity (owners' + NCI), not the owners-only figure ROE uses. Using the
# owners-only figure against all-entity debt was overstating leverage for
# every company with a material minority interest.
_NCI_LABELS = [
    "non-controlling interests", "non controlling interests",
    "non-controlling interest", "non controlling interest",
    "minority interest", "minority interests",
]
# Retained Earnings (Altman Z-Score Sr No 55's RE/TA component) — the
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
# either) — summing these two face-of-Balance-Sheet rows directly is more
# robust than searching for a "Total Equity" label at all, since some filers
# print it as "Total - Equity (A)" (confirmed on HUL) rather than "Total
# Equity"/"Shareholders' Funds". A bare substring search for "total equity"
# is unsafe regardless of phrasing: it also matches inside "TOTAL EQUITY AND
# LIABILITIES" (the whole Balance Sheet grand total, not equity at all) —
# confirmed silently happening on HUL, since "Total - Equity (A)" (with the
# dash) doesn't match "total equity" as a contiguous substring, so the search
# fell through to that later, wrong, much bigger total.
_EQUITY_SHARE_CAPITAL_LABELS = [
    "equity share capital",
]
_PBT_LABELS = [
    "profit before exceptional items and tax", "profit before tax and exceptional items",
    "profit before tax", "profit before exceptional item and tax",
    # Same "/(Loss)" suffix issue as `_PAT_GENERIC_LABELS`/`_PAT_OWNERS_LABELS`
    # (Sr No 16 fix) — loss-making-history filings (e.g. Eternal/Zomato)
    # caption this "Profit/(Loss) before tax" rather than plain "Profit
    # before tax". `_find_pl_row` already normalises this via
    # `_strip_formula_refs` before matching, but these are kept explicitly in
    # the canonical list too (belt-and-suspenders): a match must never be
    # skipped just because of the "/(Loss)" suffix. This feeds ROCE's (Sr No
    # 19) EBIT approximation (PBT + Finance Costs), so the same root cause
    # would otherwise silently break ROCE too.
    "profit/(loss) before exceptional items and tax", "profit/(loss) before tax and exceptional items",
    "profit/(loss) before tax", "profit/(loss) before exceptional item and tax",
]
def _find_eps_row(text):
    """Basic EPS — Ind AS Schedule III mandates this disclosure on the P&L
    page (or its immediate continuation) under an "Earnings per equity
    share" heading. Three real-filing layouts seen: a single combined "Basic
    and diluted (in ₹)" SUB-LABEL row (when there are no dilutive
    instruments — same value both ways); Basic and Diluted printed as two
    SEPARATE bare-word rows ("Basic\n461.20\n429.01\nDiluted\n461.20\n429.01",
    seen on MARUTI); OR the combined-value case captioned entirely in the
    HEADING itself ("Basic and Diluted Earnings per Equity Share (in ₹)"
    followed directly by the two numbers, no separate sub-label line at
    all) — this third layout used to silently fail extraction (no "basic"/
    "diluted" text appears AFTER the heading to anchor on) until the
    pre-heading check below was added. A generic label-list scan (like every
    other row in this file) can't safely use a bare "basic" label — it could
    false-match elsewhere on the page — so this is BOUNDED to the text
    immediately after the "Earnings per equity share" heading, where "Basic"
    is unambiguous. Only Basic is read, never Diluted, per spec's "state
    explicitly whether Basic or Diluted is used". Some filings (e.g. Tata
    Steel) head this section plainly as "Earnings per share" — without
    "equity" — so the heading anchor accepts both."""
    # Some filings (e.g. Eternal/Zomato) caption this "Earnings / (loss) per
    # equity share" — the same "/(loss)" qualifier infix seen on PBT/PAT
    # captions elsewhere, here breaking the heading anchor itself.
    m = re.search(r"earnings\s*(?:/\s*\(\s*loss\s*\))?\s*per (?:equity )?share", text, re.I)
    if not m:
        return None
    window = text[m.end():m.end() + 400]
    # `_NUM_RE`'s plain-decimal alternative requires 2+ integer digits
    # (by design, to avoid mistaking a bare Note/Page-number column for a
    # real value elsewhere in this file) — but EPS is routinely a
    # single-digit-plus-decimal figure (e.g. "2.74"), which that pattern
    # silently can't see at all. Confirmed on Tata Steel: the window held
    # "Basic (I)\n2.74\n(3.62)" and `_NUM_RE` only matched "(3.62)" TWICE
    # (the parenthesised-negative alternative has no digit-count floor),
    # never the genuine "2.74" — so the current year was silently read as
    # the prior year's value. Scoped to just this function (not a global
    # `_NUM_RE` change, which is too large a blast radius per the Sr No 20
    # "bare small integer" bug fix) since by this point in the text we're
    # well past any Note/Page-number columns (confirmed those always
    # appear BEFORE the Basic/Diluted line in every filing seen).
    eps_num_re = r"\(-?[\d,]+(?:\.\d{1,2})?\)|-?[\d,]+\.\d{1,2}"
    for label in ("basic and diluted", "basic & diluted", "basic / diluted", "basic and diluted eps", "basic"):
        lm = re.search(re.escape(label), window, re.I)
        if not lm:
            continue
        nums = re.findall(eps_num_re, window[lm.end():lm.end() + 150])
        if len(nums) >= 2:
            a, b = _parse_num(nums[0]), _parse_num(nums[1])
            if a is not None and b is not None:
                return a, b

    # Some filings caption the combined single-value row entirely in the
    # HEADING itself — "Basic and Diluted Earnings per Equity Share (in ₹)"
    # — rather than printing a "Basic"/"Basic and Diluted" sub-label on its
    # own line before the two numbers. The loop above only searches AFTER
    # the "earnings per share" match, so it never sees "basic"/"diluted"
    # text that appeared BEFORE it in the heading, and returns None even
    # though there's genuinely only one EPS figure (current + prior) to
    # read — a real extraction gap, not a missing-data case. Check the text
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


def _find_shares_outstanding(doc, start_idx, want_section, max_pages=250):
    """Number of Equity Shares Outstanding (Sr No 25 denominator component) —
    NOT disclosed on the primary Balance Sheet page itself; it lives in the
    "Equity Share Capital" NOTE (Ind AS Schedule III), which can be dozens to
    hundreds of pages after the statement (seen on MARUTI: BS on page ~35,
    this note on page ~190). Scans forward, page by page, from the Balance
    Sheet page already found — Notes always follow the statements they
    describe, so no need to scan backward or from page 0.

    Re-tracks the standalone/consolidated section transition using the SAME
    narrow statement-caption anchors as the main page-detection loop (not the
    broad "financial statements" phrase that caused the TOC/Notes-pollution
    bug fixed earlier this suite) — a Consolidated Annual Report's Notes
    section can also print a SUBSIDIARY's own separate share capital note;
    without re-checking section, that could be picked up instead of the
    parent company's own (the one actually relevant to Market Cap ÷ market
    price per share).

    Looks for "issued, subscribed and fully paid" (the standard sub-heading
    within the note) followed by an "X equity shares of ₹Y each" line for the
    current year, with the prior year's count usually printed in an adjacent
    "(as at <prior date>: X equity shares...)" parenthetical on the SAME
    line. Returns (current, prior) as raw share COUNTS — never Crore-scaled,
    same reasoning as EPS.

    Some filings (e.g. Tata Steel) head this sub-section just "Subscribed
    and paid up:" — no "Issued" prefix, "paid up" instead of "fully paid" —
    and call the shares "Ordinary Shares" rather than "Equity Shares"; the
    heading regex accepts both phrasings (the number-floor filter below
    doesn't depend on the word "equity"/"ordinary" appearing at all, so no
    further change was needed once the heading itself matches).

    Rebuilt with a 3-PRIORITY fallback (this was the single biggest
    cascading failure in the whole suite — Market Cap feeds Sr No 24-26/29
    and Price/Cash Flow/FCF Yield, so a share-count miss here silently broke
    four-plus ratios at once):
      1. The "Reconciliation of the number of shares outstanding" note's
         CLOSING balance ("...at the end of the year/reporting period") —
         the most authoritative figure when present, since it's explicitly
         the movement-reconciled closing count (correct even after a
         buyback/rights issue/ESOP allotment during the year), not just a
         static snapshot.
      2. The static "Issued, Subscribed and Fully Paid" (or, now, the
         version WITHOUT "Fully" — "Issued, Subscribed and Paid-up", seen on
         filings that don't use that qualifier at all) line — the previous
         sole method.
      3. Computed via Face Value: Equity Share Capital (₹) ÷ Face Value per
         share — the last-resort fallback when neither of the above prints
         a raw share count at all (some filings disclose Share Capital only
         in ₹ terms alongside a "face value of ₹X each" note)."""
    section = want_section
    recon_result = None
    static_result = None
    face_value_result = None
    share_capital_cur = None
    for i in range(start_idx, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        if "consolidated balance sheet" in tl or "consolidated statement of profit" in tl:
            section = "consolidated"
        elif "standalone balance sheet" in tl \
                or ("statement of profit and loss" in tl and "consolidated" not in tl):
            section = "standalone"
        if section != want_section:
            continue

        # Priority 1: Reconciliation table closing balance.
        if recon_result is None and re.search(r"reconciliation of (?:the )?(?:number of )?shares", tl):
            rm = re.search(r"(?:outstanding |shares )?at the end of the (?:year|reporting period)", tl)
            if rm:
                window = t[rm.end():rm.end() + 150]
                nums = [_parse_num(n) for n in re.findall(_NUM_RE, window)]
                nums = [n for n in nums if n is not None and n >= 100000]
                if nums:
                    recon_result = (nums[0], None)

        # Priority 2: static Issued/Subscribed/(Fully) Paid line — now also
        # accepting the version without "Fully" ("issued, subscribed and
        # paid" with no "up"/"fully" qualifier at all).
        if static_result is None:
            m = re.search(r"issued,?\s*subscribed and fully paid|issued,?\s*subscribed and paid"
                           r"|subscribed and (?:fully )?paid[\s-]?up", tl)
            if m:
                window = t[m.end():m.end() + 300]
                # The current-year share count isn't always immediately
                # adjacent to "equity shares" — some filings interpose a
                # "[as at <prior date>: <prior count>]" bracket between the
                # current count and that label (seen on DMART: "65,07,33,068
                # [31st March, 2024: 65,07,33,068] equity Shares of ₹10
                # each"), so an "equity shares"-anchored lookahead misses the
                # FIRST number entirely. Instead, take the first two numbers
                # in the window above a share-count-sized floor (>=100,000)
                # — comfortably above any face-value/₹-Crore amount printed
                # alongside (e.g. "750.00", "1,572"), which are always much
                # smaller. Handles both Western (314,402,574) and Indian
                # (65,07,33,068) comma grouping via the shared `_NUM_RE`.
                candidates = [_parse_num(n) for n in re.findall(_NUM_RE, window)]
                share_nums = [n for n in candidates if n is not None and n >= 100000]
                if share_nums:
                    cur = share_nums[0]
                    prior = share_nums[1] if len(share_nums) >= 2 else None
                    if cur is not None and cur > 0:
                        static_result = (cur, prior)

        # Priority 3 inputs: Equity Share Capital (₹, from the same note) and
        # Face Value per share, for the computed fallback ("shares = Equity
        # Share Capital ÷ Face Value") — used only when neither the
        # Reconciliation table nor the static Issued/Subscribed line above
        # ever discloses a raw share count directly.
        if share_capital_cur is None:
            cm = re.search(r"equity share capital", tl)
            if cm:
                window = t[cm.end():cm.end() + 150]
                nums = re.findall(_NUM_RE, window)
                if nums:
                    v = _parse_num(nums[0])
                    if v is not None and v > 0:
                        share_capital_cur = v * _unit_factor(t)
        if face_value_result is None and share_capital_cur is not None:
            fm = re.search(r"face value of\s*`?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(?:each|per share)", tl)
            if fm:
                fv = _parse_num(fm.group(1))
                if fv and fv > 0:
                    face_value_result = (round((share_capital_cur * 1e7) / fv), None)

        if recon_result is not None:
            break

    return recon_result or static_result or face_value_result


def _find_dividend_per_share(doc, start_idx, max_pages=250):
    """Total Dividend per Equity Share DECLARED during the year (Sr No 27
    numerator) — lives in the Retained Earnings movement note, right next to
    (often the same note number as) the Equity Share Capital note. Per spec,
    dividends are ALWAYS sourced STANDALONE regardless of which basis
    (consolidated/standalone) every other ratio in this suite uses —
    dividends are declared by the parent entity, not on a consolidated
    basis — so this ALWAYS tracks toward "standalone", ignoring the
    `consolidated` flag every other extractor respects.

    Per spec, only a dividend actually DECLARED (shareholder-approved) counts
    — a "recommended"/"proposed" final dividend awaiting AGM approval must
    be EXCLUDED even though it's disclosed on the same page (seen on
    MARUTI: the FY25 Annual Report discloses "The Board of Directors
    recommended a final dividend of ₹135 per share... subject to approval...
    has not been accounted as a liability" — that ₹135 must NOT be used).
    The line that IS correct is the "During the year, a dividend of ₹X per
    share... was paid to equity shareholders" sentence in the Retained
    Earnings note, which reports what was ACTUALLY declared+paid in cash
    during the fiscal year (typically last year's approved final dividend
    plus any interim declared this year) — exactly the "declared, not merely
    proposed" figure the spec calls for.

    Per spec, "no dividend declared" is a real 0%, NOT missing data — so
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
        if "consolidated balance sheet" in tl or "consolidated statement of profit" in tl:
            section = "consolidated"
        elif "standalone balance sheet" in tl \
                or ("statement of profit and loss" in tl and "consolidated" not in tl):
            section = "standalone"
        if section != "standalone":
            continue

        m = re.search(r"during the year,?\s*a dividend of\s*`?\s*([\d,]+(?:\.\d+)?)\s*per share", tl)
        if m:
            v = _parse_num(m.group(1))
            if v is not None:
                return v, True  # (value, found_with_confidence)
        m2 = re.search(r"dividend of\s*`?\s*([\d,]+(?:\.\d+)?)\s*per (?:equity )?share[^.]{0,60}(?:was paid|paid to)", tl)
        if m2:
            v = _parse_num(m2.group(1))
            if v is not None:
                return v, True

        # Fallback: some filers (e.g. HUL) don't print a single narrative
        # sentence at all — the "declared and paid during the year" figure
        # only exists as a TABULATED note ("NOTE X DIVIDEND ON EQUITY
        # SHARE"), broken into separate Final/Interim/Special dividend
        # rows, each with its own per-share amount, e.g. "Final dividend of
        # ₹24 per share for FY 2024-25 ... / Interim dividend of ₹19 per
        # share for FY 2025-26 ...". Sums whichever of these three rows are
        # present under that heading. Each row also repeats the SAME
        # per-share figure a second time as a prior-year comparator in a
        # trailing parenthetical on the same line (e.g. "(2023-24: ₹24 per
        # share)") — stripped per-line before matching, or it would be
        # double-counted. "Nil" (a genuinely skipped dividend type that
        # year) parses to 0 via `_parse_num`, same as a bare "-".
        anchor = re.search(r"declared and paid during the year", t, re.I)
        if anchor:
            window = t[anchor.end():anchor.end() + 700]
            stop = re.search(r"proposed dividend", window, re.I)
            if stop:
                window = window[:stop.start()]
            row_total = 0.0
            row_found = False
            for line in window.split("\n"):
                line_no_paren = re.sub(r"\([^)]*\)", "", line)
                rm = re.search(
                    r"(?:final|interim|special)\s+dividend\s+of\s*[^\d\s]{0,2}\s*"
                    r"(nil|[\d,]+(?:\.\d+)?)\s*(?:per\s+)?(?:equity\s+)?share",
                    line_no_paren, re.I)
                if rm:
                    v = 0.0 if rm.group(1).lower() == "nil" else _parse_num(rm.group(1))
                    if v is not None:
                        row_total += v
                        row_found = True
            if row_found:
                return round(row_total, 2), True
    return 0.0, False

# NOTE on the `start_idx` argument used at the call site below: Standalone
# financial statements ALWAYS precede Consolidated ones in the regulatory
# Ind AS filing template — so this is always called with start_idx=0 (NOT
# bs_idx, which for a consolidated=True extraction points at the LATER
# Consolidated Balance Sheet page and would scan past the earlier Standalone
# Retained Earnings note entirely, forward-only).


# Debt Service Coverage Ratio (Sr No 34) denominator components — the actual
# PRINCIPAL repaid during the year, from the Cash Flow Statement's Financing
# Activities section (NOT the Balance Sheet's outstanding Borrowings
# balance, and NOT netted against fresh borrowings raised in the same
# section — per spec, only the repayment outflow itself).
_REPAYMENT_BORROWINGS_LABELS = [
    "repayment of long-term borrowings", "repayment of long term borrowings",
    "repayment of non-current borrowings", "repayment of current borrowings",
    "repayment of term loans", "repayment of debentures", "repayment of non-convertible debentures",
    "redemption of debentures", "redemption of non-convertible debentures",
    "repayment of unsecured loans", "repayment of secured loans",
    "repayment of bank loans", "repayment of commercial paper", "repayment of cash credit",
    "repayment of vehicle loans", "repayment of buyer's credit", "repayment of buyers' credit",
    "repayment of external commercial borrowings",
    # Deliberately LAST — the generic catch-all, tried only after every more
    # specific instrument label above has had a chance to match. A filer
    # printing "Proceeds/(Repayment) of borrowings (net)" or "Movement in
    # borrowings (net)" (a single NETTED line, not a gross repayment figure)
    # is NOT in this list at all — per spec, a net figure must never be
    # silently treated as the gross repayment (it understates Total Debt
    # Service whenever fresh borrowings exceeded repayments that year, and
    # can even be a net INFLOW), so a filing with only that netted line
    # correctly falls through to "Could not find" instead of a wrong number.
    "repayment of borrowings",
]
# Ind AS 116 splits a lease payment into interest and principal components in
# the Cash Flow Statement — only the PRINCIPAL portion belongs in Total Debt
# Service (the interest portion is already inside Finance Costs). Basis 1
# (default, per Sr No 34's own spec — note this is the OPPOSITE direction
# from Sr No 20/33's Basis 1, which INCLUDES leases; each ratio's Basis 1/2
# toggle is defined independently per its own spec row) EXCLUDES this from
# Total Debt Service; Basis 2 INCLUDES it.
_REPAYMENT_LEASE_LABELS = [
    "repayment of lease liabilities", "payment of lease liabilities",
    "principal payment of lease liabilities", "principal repayment of lease liabilities",
    "repayment of lease liability", "payment of lease liability",
]
# Cash Flow Coverage Ratio (Sr No 35) numerator — the FINAL, post-tax
# subtotal at the bottom of the Operating Activities section, NEVER the
# interim "Cash generated from operations (before tax)" subtotal that
# usually appears a few lines above it. Requiring "net cash" in the label
# (rather than a bare "cash generated from operations") is what keeps this
# from grabbing that earlier, pre-tax figure.
_OPERATING_CASH_FLOW_LABELS = [
    "net cash generated from operating activities", "net cash generated from/(used in) operating activities",
    "net cash (used in)/generated from operating activities", "net cash flow from operating activities",
    "net cash from operating activities", "net cash inflow from operating activities",
    "net cash (used in) operating activities", "net cash generated by operating activities",
    "net cash provided by operating activities", "cash flow from operating activities",
    "net cash flows from operating activities", "net cash flows generated from operating activities",
    # "Net cash from/(used in) operating activities" (confirmed on Tata
    # Steel) — a DIFFERENT parenthetical insertion point than the two
    # "generated from/(used in)"/"(used in)/generated from" variants above,
    # which substring-match fails on entirely (the extra "/(used in)" text
    # sits in the middle of the phrase, breaking a match against either
    # "net cash from operating activities" or "net cash generated from
    # operating activities" alone).
    "net cash from/(used in) operating activities", "net cash used in/generated from operating activities",
    "net cash generated/(used in) operating activities",
]
# Free Cash Flow (Sr No 36) denominator components — Capital Expenditure,
# from the Cash Flow Statement's INVESTING ACTIVITIES section, NEVER the
# Balance Sheet's gross block movement (which can include revaluations/
# acquisitions unrelated to organic capex) and NEVER accounting Depreciation
# used as a proxy. Purchase of PP&E and Purchase of Intangible Assets are
# each their OWN separate line — summed individually rather than requiring
# both (a services business may have no PP&E purchase line at all); Proceeds
# from disposal is netted OFF per spec ("net Capex"), not ignored.
_CAPEX_PPE_PURCHASE_LABELS = [
    "purchase of property, plant and equipment", "purchase of property, plant & equipment",
    "purchase of fixed assets", "purchase of tangible assets", "purchase of capital assets",
    "additions to property, plant and equipment", "payments for property, plant and equipment",
    "payment for property, plant and equipment", "acquisition of property, plant and equipment",
    "purchase of property, plant and equipment (including capital work-in-progress)",
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
]


# Cash Flow Statement section headings — some filers (confirmed on HUL, TCS,
# Bharti Airtel) use the plural "Cash Flows from Operating/Investing/Financing
# Activities" instead of the singular "Cash Flow from ... Activities" every
# other checked filing uses. The literal-substring checks below used to only
# match the singular form, so the entire Cash Flow Statement extraction block
# silently never fired for plural-heading filers — every ratio depending on
# operating_cash_flow/capex/repayments came back "Could not find..." even
# though the figures were sitting right there on the page. `s?` makes both
# forms match.
_CFS_OPERATING_PAT = r"cash\s+flows?\s+from\s+operating\s+activities"
_CFS_INVESTING_PAT = r"cash\s+flows?\s+from\s+investing\s+activities"
_CFS_FINANCING_PAT = r"cash\s+flows?\s+from\s+financing\s+activities"


def _bounded_segment_module(text, start_after, stop_before):
    """Module-level twin of `_extract_from_pdf`'s nested `_bounded_segment`
    (same behaviour: slice `text` to the region between two section
    markers, or None if `start_after` isn't found) — needed here since
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
    denominator components) — all live in the Cash Flow Statement, a
    genuinely new statement this reader hadn't parsed before (only ever used
    as an EXCLUSION marker elsewhere in this file, to skip false-positive
    BS/P&L row matches on that page). The Cash Flow Statement follows the
    Balance Sheet/P&L/Statement of Changes in Equity in the regulatory Ind
    AS filing order, so a short forward scan from the Balance Sheet page
    (much shorter than the 250-page scan used for Notes-only items like
    Share Capital) is enough.

    Net Operating Cash Flow keeps its NATURAL sign (a company can genuinely
    have negative operating cash flow — a real distress signal, never
    forced positive). Financing-activity cash OUTFLOWS (the two repayment
    lines) and Investing-activity Capex purchases are printed as negative/
    parenthesised figures (cash leaving the business) — returned here as a
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
    for i in range(start_idx, min(start_idx + max_pages, doc.page_count)):
        try:
            t = _page_text(doc[i])
        except Exception:
            continue
        tl = t.lower()
        # Section-tracking includes the Cash Flow Statement's OWN caption
        # (e.g. "Consolidated Statement of Cash Flows"/"Consolidated Cash
        # Flow Statement") in addition to the BS/P&L captions every other
        # page-scanning helper in this file checks — without this, a large
        # filing with many pages between the Balance Sheet and the actual
        # Cash Flow Statement (Statement of Changes in Equity, segment
        # disclosures, etc.) could have `section` drift to the wrong value
        # on an intervening page before ever reaching the real CFS page,
        # silently skipping it for the rest of the scan.
        if "consolidated balance sheet" in tl or "consolidated statement of profit" in tl \
                or "consolidated statement of cash flow" in tl or "consolidated cash flow statement" in tl:
            section = "consolidated"
        elif "standalone balance sheet" in tl \
                or ("statement of profit and loss" in tl and "consolidated" not in tl) \
                or "standalone statement of cash flow" in tl or "standalone cash flow statement" in tl:
            section = "standalone"
        if section != want_section:
            continue

        factor = _unit_factor(t)

        # Boundary anchors use the FULL "cash flow from X activities" phrase
        # (the genuine section heading), never the bare "X activities" —
        # the Operating section's own adjustments routinely contain an
        # embedded, unrelated mention like "Exchange difference on items
        # grouped under financing/investing activities", which a bare
        # "investing activities" pattern matches FIRST, cutting the
        # Operating segment short before ever reaching its own "Net cash
        # generated from operating activities" subtotal (confirmed on L&T's
        # FY26 filing) — and, symmetrically, makes the Investing segment
        # START at that same false position instead of the real "B. Cash
        # flow from investing activities" heading a few lines later. The
        # fuller phrase never collides with that embedded mention.
        if operating_cash_flow is None and re.search(_CFS_OPERATING_PAT, tl, re.I):
            op_segment = _bounded_segment_module(t, _CFS_OPERATING_PAT, _CFS_INVESTING_PAT)
            if op_segment is None:
                op_segment = t[re.search(_CFS_OPERATING_PAT, tl, re.I).start():]
            for label in _OPERATING_CASH_FLOW_LABELS:
                m = re.search(re.escape(label), op_segment, re.I)
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
                nums = re.findall(_NUM_RE, window)
                if len(nums) >= 2:
                    a, b = _parse_num(nums[0]), _parse_num(nums[1])
                    if a is not None and b is not None:
                        operating_cash_flow = (round(a * factor, 2), round(b * factor, 2))
                        break

        if re.search(_CFS_INVESTING_PAT, tl, re.I) and (
                capex_ppe_purchase is None or capex_intangible_purchase is None or capex_disposal_proceeds is None):
            inv_segment = _bounded_segment_module(t, _CFS_INVESTING_PAT, _CFS_FINANCING_PAT)
            if inv_segment is None:
                inv_segment = t[re.search(_CFS_INVESTING_PAT, tl, re.I).start():]

            # All three loops below anchor the label match to the START of
            # its own line (`(?:^|\n)[ \t]*`, `re.M`), not a bare substring
            # search anywhere in the segment. Cash Flow Statement captions
            # are laid out one per line — without this anchor, a label like
            # "acquisition of property, plant and equipment" (a genuine
            # Purchase-of-PP&E variant) also matches as a literal substring
            # INSIDE a completely different, unrelated line like "Grant
            # received on acquisition of property, plant and equipment" (an
            # INFLOW, not a purchase) — confirmed on Tata Steel, where this
            # silently grabbed the grant's ₹533.30 Cr instead of the real
            # "Purchase of capital assets" line's ₹14,559.05 Cr. Same trap
            # hit disposal proceeds: "sale of property, plant and equipment"
            # matched inside "Advance received against sale of property,
            # plant and equipment" (a receivable, not actual disposal cash).
            if capex_ppe_purchase is None:
                for label in _CAPEX_PPE_PURCHASE_LABELS:
                    m = re.search(r"(?:^|\n)[ \t]*" + re.escape(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = re.findall(_NUM_RE, window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_ppe_purchase = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if capex_intangible_purchase is None:
                for label in _CAPEX_INTANGIBLE_PURCHASE_LABELS:
                    m = re.search(r"(?:^|\n)[ \t]*" + re.escape(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = re.findall(_NUM_RE, window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_intangible_purchase = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if capex_disposal_proceeds is None:
                for label in _CAPEX_DISPOSAL_PROCEEDS_LABELS:
                    m = re.search(r"(?:^|\n)[ \t]*" + re.escape(label), inv_segment, re.I | re.M)
                    if not m:
                        continue
                    window = inv_segment[m.end():m.end() + 200]
                    nums = re.findall(_NUM_RE, window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            capex_disposal_proceeds = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

        if re.search(_CFS_FINANCING_PAT, tl, re.I) and (borrowings_repayment is None or lease_repayment is None):
            segment = _bounded_segment_module(t, _CFS_FINANCING_PAT,
                                               r"net (?:increase|decrease|increase/decrease)")
            if segment is None:
                segment = t[re.search(_CFS_FINANCING_PAT, tl, re.I).start():]

            if borrowings_repayment is None:
                for label in _REPAYMENT_BORROWINGS_LABELS:
                    m = re.search(re.escape(label), segment, re.I)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = re.findall(_NUM_RE, window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            borrowings_repayment = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

            if lease_repayment is None:
                for label in _REPAYMENT_LEASE_LABELS:
                    m = re.search(re.escape(label), segment, re.I)
                    if not m:
                        continue
                    window = segment[m.end():m.end() + 200]
                    nums = re.findall(_NUM_RE, window)
                    if len(nums) >= 2:
                        a, b = _parse_num(nums[0]), _parse_num(nums[1])
                        if a is not None and b is not None:
                            lease_repayment = (round(abs(a) * factor, 2), round(abs(b) * factor, 2))
                            break

        # Early-exit once every REQUIRED item is found — capex_intangible_purchase
        # and capex_disposal_proceeds are genuinely optional (many companies have
        # no intangible purchases or disposals in a given year) and would never
        # gate the scan to completion if required here.
        if (operating_cash_flow is not None and capex_ppe_purchase is not None
                and borrowings_repayment is not None and lease_repayment is not None):
            break

    return {"operating_cash_flow": operating_cash_flow,
            "capex_ppe_purchase": capex_ppe_purchase,
            "capex_intangible_purchase": capex_intangible_purchase,
            "capex_disposal_proceeds": capex_disposal_proceeds,
            "borrowings_repayment": borrowings_repayment, "lease_repayment": lease_repayment}


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
    # relying on that substitution — a match must never be skipped just
    # because of this suffix.
    "finance costs/(income)", "finance cost/(income)",
]
_TAX_EXPENSE_LABELS = [
    # Total Tax Expense (Sr No 42's Effective Tax Rate component: current +
    # deferred tax, the P&L subtotal line — NOT the current-tax-only
    # sub-line). Feeds NOPAT = EBIT × (1 − Effective Tax Rate), where
    # Effective Tax Rate = Tax Expense ÷ Profit Before Tax.
    "total tax expense", "tax expense", "total tax expenses",
    # Same "/(Loss)"/"/(Credit)" suffix issue as PBT/Finance Costs — a
    # loss-making year can post a net tax CREDIT, captioned accordingly.
    "tax expense/(credit)", "total tax expense/(credit)",
]
# Total Debt (Sr No 20 numerator) — rebuilt as the a + b + c protocol:
#   a = Borrowings (Long-term + Short-term + Current Maturities of
#       Long-term Debt) — verified against the Borrowings Note breakup, not
#       taken from the Balance Sheet face value alone (see
#       `_find_borrowings_note_total`).
#   b = Lease Liabilities (Non-current + Current). Per the authoritative
#       Sr No 33 (Net Debt/EBITDA) spec, Basis 1 (default) INCLUDES these in
#       Total Debt — the post-Ind-AS-116 view, consistently applied to every
#       consumer of this field (D/E, Debt Ratio, Enterprise Value, Net
#       Debt/EBITDA). Basis 2 (opt-in `lease_basis="basis2"`) EXCLUDES them,
#       for callers that want the traditional pre-Ind-AS-116 definition.
#       Always surfaced informationally either way.
#   c = qualifying "Other Financial Liabilities" Notes items — only the
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
# to some unrelated Note that happens to mention money) — used to verify the
# Balance Sheet face value isn't understated by a rigid single-line match
# (the DMart/Maruti-style false-zero this rebuild targets).
_BORROWINGS_NOTE_SUBITEM_TERMS = [
    "term loan", "secured", "unsecured", "debentures", "bonds", "commercial paper",
    "loans repayable on demand", "external commercial borrowings", "buyers' credit",
    "buyers credit", "suppliers' credit", "suppliers credit", "cash credit",
    "working capital loan", "loan from banks", "loan from financial institutions",
    "inter corporate deposit", "deposits from related part",
]
# Lease Liabilities — a SEPARATE Balance Sheet line from Borrowings (Ind AS
# 116). See the module-level comment above for the Basis 1/Basis 2 toggle.
_LEASE_LIABILITY_NC_LABELS = [
    "lease liabilities", "lease liability", "non-current lease liabilities",
]
_LEASE_LIABILITY_CUR_LABELS = [
    "lease liabilities", "lease liability", "current lease liabilities",
]
# Other Financial Liabilities — a catch-all BS line (Non-current/Current)
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
    "trade receivables", "trade debtors", "sundry debtors", "accounts receivable",
    "debtors", "trade receivables (net of provision for doubtful debts)", "bills receivable",
]
_PAYABLES_LABELS = [
    "trade payables", "trade creditors", "sundry creditors", "accounts payable",
    "trade payables - msme", "trade payables - others", "bills payable",
]
_TOTAL_ASSETS_LABELS = [
    "total assets",
]
_TOTAL_CURRENT_ASSETS_LABELS = [
    "total current assets",
]
_TOTAL_CURRENT_LIABILITIES_LABELS = [
    "total current liabilities",
]
# Net Fixed Assets (Sr No 30 denominator) — Property, Plant & Equipment net
# of accumulated depreciation. Deliberately EXCLUDES Capital Work-in-Progress
# (a separate BS line for assets not yet operational) and intangible
# assets/goodwill — per spec, only the tangible, in-service asset base.
_NET_FIXED_ASSETS_LABELS = [
    "property, plant and equipment", "property plant and equipment",
    "net block", "fixed assets (net)", "tangible assets (net)",
    "property, plant & equipment",
]
_CASH_LABELS = [
    "cash and cash equivalents", "cash and bank balances", "balances with banks",
    "cash on hand", "cash & cash equivalents",
]
# "Other Bank Balances" (e.g. fixed deposits with banks, margin money, unpaid
# dividend accounts, escrow balances) is a SEPARATE Balance Sheet line from
# Cash and Cash Equivalents. Per spec, only its UNRESTRICTED portion (e.g.
# freely-available bank deposits) belongs in the Cash Ratio numerator — the
# restricted portion (unpaid dividend/margin money/escrow) must be excluded.
# The split is rebuilt as a deterministic Base -> Net-off -> Optional-Add
# pipeline (see `_other_bank_balances_unrestricted`) instead of leaving the
# restricted/unrestricted call to AI judgement: Base is the line's own total;
# Net-off subtracts any sub-item lines printed directly under it that match
# an explicit restricted-label test; Optional-Add folds the remainder into
# the Cash Ratio numerator ONLY when that Net-off test actually matched
# something (i.e. a real breakup was found to classify) — if no sub-item
# breakup is printed at all, the split can't be determined and the figure
# stays informational-only rather than guessed.
_OTHER_BANK_BALANCES_LABELS = [
    "other bank balances", "bank balances other than cash and cash equivalents",
]
# Deterministic "exclude" test for Other Bank Balances sub-items — reuses
# `_RESTRICTED_CASH_TERMS` (unpaid/unclaimed dividend, earmarked, margin
# money, escrow, restricted) plus lien/pledge/security-deposit/guarantee
# terms specific to bank-deposit notes, which don't otherwise appear against
# plain Cash and Cash Equivalents rows.
_OBB_RESTRICTED_SUBITEM_TERMS = [
    "unpaid dividend", "unclaimed dividend", "earmarked", "margin money",
    "escrow", "restricted", "pledged", "lien", "security deposit",
    "bank guarantee",
]

# Matches a genuine tabulated amount while excluding bare note-reference
# numbers — both the plain kind (e.g. the "27" next to "Cost of materials
# consumed" pointing at note 27) AND the decimal-dotted kind some filings use
# (e.g. Infosys numbers its notes "2.1", "2.8", "2.17" — which, before a
# guard was added, looked exactly like a small decimal AMOUNT and got
# mistaken for one, e.g. reading Trade Receivables as "2.8" instead of the
# real 30,337).
#
# The comma-grouped branch must handle BOTH numbering conventions filings
# use — companies reporting in ₹ Crore (Tata Steel, Infosys, ...) use INDIAN
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
# part, so a 2+ digit floor excludes those — but Maruti numbers its notes
# "24.1", "24.2" (2-digit.1-digit), which a 1-2 digit DECIMAL part would still
# match. Real amounts always carry exactly 2 decimal digits (paise
# precision) when not comma-grouped; note references have 1. Requiring
# exactly 2 decimal digits here (not 1-2) closes that gap without losing any
# real value — a genuine 1-decimal amount always has a comma anyway once
# it's large enough to matter (e.g. Sun Pharma's "64,491.0").
_NUM_RE = (r"\([\d,]+(?:\.\d{1,2})?\)"                  # parenthesised (negative)
           r"|-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"        # Western comma grouping
           r"|-?\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d{1,2})?"  # Indian comma grouping
           r"|-?\d{2,}\.\d{2}"                           # plain decimal, no comma, 2+ digit integer, exactly 2 decimals
           r"|(?<=\s)-(?=\s)")                           # lone dash placeholder ("-")


def _unit_factor(text):
    """Detect the reporting unit declared on a statement page (e.g.
    '(In ` Million)', '(₹ in Lakh)', '(` in Crores)') and return the
    multiplier to convert its raw figures into ₹ Crore. Per spec: 'Normalise
    numerator and denominator to the same unit (₹ Crore) before dividing;
    never divide a Crore figure by a Lakh/Million figure.' Companies that
    report in ₹ Million (e.g. Sun Pharma, Maruti) or ₹ Lakh would otherwise
    have every extracted figure mislabelled as Crore while being 10x/100x too
    large — the RATIO itself is still correct (same unit top and bottom), but
    the displayed absolute values ('How we calculated this') would be wrong.
    Searches the WHOLE page, not just the top: the unit note is sometimes a
    signature-block footnote (seen on Maruti's Balance Sheet: '(in ` million,
    unless otherwise stated)' ~3000 characters in), not a page-top header.
    Defaults to 1.0 (already Crore) when no unit is stated."""
    # `\bmillion\b` requires the word to end exactly there — but the plural
    # "millions" (e.g. Bharti Airtel's "(All amounts are in millions of
    # Indian Rupee)") has no word-boundary between the "n" and the "s", so
    # the un-pluralised pattern silently never matched it at all, leaving
    # the factor at the default 1.0 — every figure on that filing came out
    # 10x too large (confirmed on Bharti Airtel: Net Cash from Operating
    # Activities read as ₹1,222,296 Cr instead of the real ₹1,22,229.60 Cr).
    # `million` (without the closing `\b`) matches "millions" too, same
    # asymmetric-boundary trick "lakh" below already relies on.
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


def _find_row_values(text, canonical_names, after=None, reject_after=None, permissive=False):
    """Find a row by any of its canonical label variants and return
    (current_year_value, prior_year_value) — the two trailing numbers on that
    logical line — or None. Case-insensitive, tries each synonym in order.

    `after`: an optional regex; if given, the search starts AFTER the first
    match of it. Used for Trade Receivables, which the Balance Sheet often
    lists twice (a small long-term portion under Non-Current Assets, then the
    real circulating balance under Current Assets) — without this, the first
    (wrong, non-current) occurrence would win.

    `reject_after`: an optional regex; if the text immediately following a
    label match starts with it, that match is skipped and the NEXT
    occurrence of the same label (or the next label) is tried instead. Used
    for "total equity", which is a literal substring of "TOTAL EQUITY AND
    LIABILITIES" (the whole Balance Sheet grand total, a completely
    different and much bigger figure) — without this, a filer whose actual
    equity subtotal is phrased some other way (e.g. "Total - Equity (A)",
    confirmed on HUL) silently falls through to that wrong total instead of
    correctly returning None.

    `permissive`: use a comma-optional number pattern instead of the strict
    `_NUM_RE`. `_NUM_RE` deliberately requires a comma or 2-decimal suffix
    (to avoid grabbing stray note-reference numbers on big-number rows like
    Revenue/Trade Payables), but that means a genuinely small face-value row
    like Equity Share Capital (e.g. "235", no comma) is invisible to it —
    the window scan then skips straight past it to the NEXT comma'd number,
    silently grabbing a completely different, unrelated row instead
    (confirmed on HUL: "Equity share capital ... 235 235" was skipped in
    favour of the following "Other equity ... 48,504 49,167" line). Only use
    this for labels where the value is known to often be a small number."""
    num_pattern = _PERMISSIVE_NUM_RE if permissive else _NUM_RE
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    for name in canonical_names:
        matches = re.finditer(re.escape(name), search_text, re.I) if reject_after else [re.search(re.escape(name), search_text, re.I)]
        for m in matches:
            if not m:
                continue
            if reject_after and re.match(reject_after, search_text[m.end():m.end() + 30], re.I):
                continue
            window = search_text[m.end():m.end() + 250]
            nums = re.findall(num_pattern, window)
            if len(nums) >= 2:
                a, b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None and b is not None:
                    return a, b
    return None


# Terms that mark a balance as restricted/earmarked — must NEVER be counted
# in the Cash Ratio numerator even if the line also happens to contain a
# "cash"/"bank balances" phrase (e.g. some filings print "Balances with
# banks — Unpaid dividend accounts" as a face-level sub-line, not just in the
# Notes). Checked in a window AROUND the match (both the label text itself
# and a little before it), not just after — the disqualifying word can
# precede the label ("Unpaid dividend account balances with banks").
_RESTRICTED_CASH_TERMS = [
    "unpaid dividend", "unclaimed dividend", "earmarked", "margin money",
    "escrow", "restricted",
]


def _find_cash_row(text, canonical_names, after=None):
    """Same matching as `_find_row_values`, but for Cash and Cash Equivalents
    specifically: skips any occurrence whose surrounding text marks it as
    restricted/earmarked (unpaid dividend accounts, margin money, escrow —
    see `_RESTRICTED_CASH_TERMS`), instead of blindly taking the first
    label match. Tries every occurrence of every label, not just the first,
    so a disqualified match doesn't block a genuine one later on the page."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    for name in canonical_names:
        for m in re.finditer(re.escape(name), search_text, re.I):
            context = search_text[max(0, m.start() - 60):m.end() + 60].lower()
            if any(term in context for term in _RESTRICTED_CASH_TERMS):
                continue  # disqualified — e.g. "unpaid dividend accounts" — try the next occurrence
            window = search_text[m.end():m.end() + 250]
            nums = re.findall(_NUM_RE, window)
            if len(nums) >= 2:
                a, b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None and b is not None:
                    return a, b
    return None


def _other_bank_balances_unrestricted(text, canonical_names, after=None):
    """Rebuilds the Other Bank Balances numerator (Cash Ratio, Sr No 12) as a
    deterministic Base -> Net-off -> Optional-Add pipeline:
      Base       = the line's own (current, prior) total, via `_find_row_values`.
      Net-off    = sub-item lines printed directly under the label that match
                   an explicit restricted-label test (`_OBB_RESTRICTED_SUBITEM_TERMS`)
                   — unpaid dividend, margin money, escrow, pledged/lien,
                   security deposits, bank guarantees.
      Optional-Add = Base minus Net-off, folded into the Cash Ratio numerator
                   — but ONLY when Net-off actually matched at least one
                   sub-item (i.e. a real breakup was found to classify). If no
                   sub-item breakup is printed at all, there's nothing to run
                   the include/exclude test against, so nothing is guessed —
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
        label_match = re.search(re.escape(name), search_text, re.I)
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
    Financial Liabilities" — a catch-all BS line that mixes genuinely
    debt-like items with purely operating ones. Applies a deterministic
    Three-Part Test to each sub-item line printed directly under the label:
      1. It's a sub-item of THIS financial-liabilities line at all (i.e. a
         real breakup was printed to test — never guessed if not).
      2. Its label matches an interest-bearing/debt-like term
         (`_OFL_DEBT_LIKE_TERMS`: interest accrued on borrowings, unpaid
         matured deposits, inter-corporate deposits, commercial paper, ...).
      3. Its label does NOT match a disguised-operating term
         (`_OFL_EXCLUDE_TERMS`: employee dues, capital-goods creditors,
         statutory dues, unclaimed dividends, security deposits received,
         ...) — Test 2 alone isn't enough since some debt-like phrasing
         (e.g. "deposit") also appears in operating contexts.
    Same shape as `_other_bank_balances_unrestricted`: returns None if the
    line isn't found at all; if found but no sub-item breakup is printed,
    returns with qualifying_cur=None (informational only, nothing folded
    into Total Debt); if a breakup IS found, qualifying_cur is the sum of
    sub-items passing all three tests (0.0 if none qualify — a real,
    determined zero, not a missing value)."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]

    label_match = None
    for name in canonical_names:
        label_match = re.search(re.escape(name), search_text, re.I)
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
            continue  # Test 3 fails — disguised operating item, never debt
        if not any(term in ll for term in _OFL_DEBT_LIKE_TERMS):
            continue  # Test 2 fails — not recognisably interest-bearing
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
    Balance Sheet FACE VALUE for Borrowings is never trusted in isolation —
    this scans forward from the Balance Sheet page for the actual Borrowings
    Note (the sub-item breakup: secured/unsecured loans, term loans,
    debentures, commercial paper, ...) and sums its disclosed sub-items as an
    independent cross-check figure. This is what catches the DMart/Maruti-
    style false-zero: a rigid single-line face-value match can miss or
    misparse the Borrowings row entirely while the Note itself, a page or two
    later, plainly discloses real outstanding debt.

    Returns (note_total_cur, subitem_count) — subitem_count is 0 (not None)
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
        # (e.g. a covenant discussion in MD&A) — require the word "borrowings"
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


def _sum_after_label(text, labels, stop_pattern, default_window=400, after=None):
    """Find the first matching label, then SUM every (current, prior) number
    pair between it and `stop_pattern` (or `default_window` chars if the stop
    pattern isn't found). Handles the common case where a total is disclosed
    only as an unlabelled sum of sub-items (e.g. Revenue split into 'Sale of
    Products' / 'Sale of Services' / 'Other Operating Revenue' with no single
    total row; Trade Payables split into MSME / Others / Acceptances with no
    single total row) — this also correctly reduces to just reading the
    number when there's only one row, so one code path covers both shapes.
    `after`: optional regex: only search after its first match (see
    `_find_row_values`'s `after` for why — restricts to the right sub-section)."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    m = None
    for lbl in labels:
        m = re.search(re.escape(lbl), search_text, re.I)
        if m:
            break
    if not m:
        return None
    tail = search_text[m.end():]
    stop = re.search(stop_pattern, tail, re.I) if stop_pattern else None
    window = tail[:stop.start()] if stop else tail[:default_window]
    nums = re.findall(_NUM_RE, window)
    if len(nums) < 2 or len(nums) % 2 != 0:
        return None
    cur_vals = [_parse_num(n) for n in nums[0::2]]
    prior_vals = [_parse_num(n) for n in nums[1::2]]
    if any(v is None for v in cur_vals) or any(v is None for v in prior_vals):
        return None
    return round(sum(cur_vals), 2), round(sum(prior_vals), 2)


def _find_revenue(pl_text):
    """Revenue from Operations, from the P&L page already located for COGS.
    Most filings print a single total row (e.g. HUL, Tata Steel, Sun Pharma) —
    matched directly. Some (e.g. Asian Paints) print only sub-items under a
    'REVENUE FROM OPERATIONS' section header with no total row before 'Other
    Income' — sum every row in between instead."""
    return _sum_after_label(pl_text, _REVENUE_LABELS, r"other\s+income")


def _find_payables_row(search_text, label_pattern, boundary_pattern, window_cap=250):
    """Extracts one (current, prior) row from the Balance Sheet's Trade
    Payables block, given the row's own label pattern and a regex marking
    where the NEXT row/section starts (so the window never reaches into it).

    Real filings routinely insert a bare note-reference number (e.g. "24")
    between the label and the actual figures, AND print sub-Rs-1,000 figures
    with no thousands separator (e.g. HUL's "458") that the stricter
    `_NUM_RE` used elsewhere can't match at all. Taking the LAST two numbers
    in a tightly bounded window — rather than the first two, and using a
    permissive comma-optional pattern — handles both: a note-reference is
    always the number closest to the label, and the window boundary keeps
    a followed row's numbers from ever entering the window at all."""
    m = re.search(label_pattern, search_text, re.I)
    if not m:
        return None, None
    boundary = re.search(boundary_pattern, search_text[m.end():m.end() + window_cap], re.I)
    window = search_text[m.end():m.end() + (boundary.start() if boundary else window_cap)]
    nums = list(re.finditer(r"\(?-?[\d,]+(?:\.\d{1,2})?\)?|(?<=\s)-(?=\s)", window))
    if len(nums) < 2:
        return None, None
    cur, prior = _parse_num(nums[-2].group()), _parse_num(nums[-1].group())
    if cur is None or prior is None:
        return None, None
    return (cur, prior), m.end() + nums[-1].end()


def _find_payables(text, after=None):
    """Trade Payables under Current Liabilities. Ind AS Schedule III requires
    the Balance Sheet to disclose it as two sub-items: (a) dues to Micro &
    Small Enterprises and (b) dues to all other creditors — sum both.

    This is called on Balance Sheet text only (never the deeper Notes-to-
    Accounts page, which sometimes breaks item (b) down further into its own
    Acceptances/Trade-payables/Total sub-rows) — confirmed by every call site
    in this file. So exactly two rows are ever expected here.
    """
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]

    msme_pat = r"total\s+outstanding\s+dues\s+of\s+micro\s+enterprises\s+and\s+small\s+enterprises"
    others_pat = r"total\s+outstanding\s+dues\s+of\s+creditors\s+other\s+than\s+micro\s+enterprises\s+and\s+small\s+enterprises"
    msme_anchor = re.search(msme_pat, search_text, re.I)
    if not msme_anchor:
        # No MSME/non-MSME split disclosed at all (rare, e.g. very old/small
        # filers) — fall back to the previous label-based approach unchanged.
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
    label of its own — it just sits on the line directly above 'TOTAL
    ASSETS' / 'TOTAL EQUITY AND LIABILITIES'. Grabs the last two numbers
    found in a short window immediately before `stop_label`."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    m = re.search(re.escape(stop_label), search_text, re.I)
    if not m:
        return None
    win = search_text[max(0, m.start() - window):m.start()]
    nums = re.findall(_NUM_RE, win)
    if len(nums) < 2:
        return None
    a, b = _parse_num(nums[-2]), _parse_num(nums[-1])
    if a is None or b is None:
        return None
    return (a, b)


def _page_sources(pdf_url, fiscal_year, pl_page=None, bs_page=None):
    """Builds the `sources` list for a ratio's response, one entry per
    statement page it draws from, each linking DIRECTLY to that page via the
    PDF `#page=N` fragment (respected by browser-native PDF viewers) — so
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


def list_annual_report_years(symbol, name):
    """All fiscal years (as ints) an Annual Report exists for, newest first,
    deduplicated. Tries BSE first, then falls back to NSE for companies BSE
    doesn't list (many NSE-only/SME names — e.g. AAKASH). Never raises."""
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
    # BSE had nothing (unlisted there, or no filings) — try NSE.
    try:
        from tools.nse_annual_reports import nse_annual_report_years
        return nse_annual_report_years(symbol)
    except Exception as e:
        print(f"[annual_report_financials] NSE year list failed for {symbol}: {e}")
        return []


def _find_annual_report_pdf(symbol, name, year):
    """Annual Report URL for the given fiscal year (e.g. 2024 for FY ended
    March 2024). Tries BSE first, then falls back to NSE for companies BSE
    doesn't list. Returns the URL or None. An NSE URL may point at a .zip
    for some older years — `_get_extracted_financials` handles unwrapping."""
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


def _extract_from_pdf(pdf_bytes, consolidated=True):
    """Extract COGS components (current+prior year) and Inventories
    (current+prior year) from the Annual Report's own financial statements.
    Returns a dict or {'error': reason}.

    Annual Reports run 200-400+ pages; pypdf's extract_text() is slow enough
    per page that eagerly parsing every page up front (the previous approach)
    took 30-45s on a large filing. Both target sections are only ever a
    handful of pages apart in practice, so we parse lazily, page by page, and
    stop the moment both are found — typically a few seconds instead. Uses
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
    # Paints' Annual Report) — a `startswith`/leading-window heading match
    # misses both. Instead, detect the page by CONTENT.
    #
    # P&L page: all three COGS rows (manufacturing/goods businesses), OR —
    # for services/IT companies with no COGS at all (Infosys, TCS, ...) —
    # Revenue plus the standard expense-category rows that only appear on the
    # real P&L (not a segment/summary page).
    # Balance Sheet page: Inventories alongside a non-current-assets marker,
    # OR — again for no-inventory businesses — Trade Receivables (in the
    # Current Assets section) alongside a whole-balance-sheet marker.
    # Standalone vs consolidated is tracked from the section headers that
    # precede each statement (auditor's report / notes captions always name
    # the section) rather than from the statement's own heading.
    # Two candidates are tracked per statement: the STRONG signal (COGS rows /
    # Inventories — essentially unambiguous) and a looser SHAPE fallback for
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
        # "Profit" before any substring test below — loss-making-history
        # filings (e.g. Eternal/Zomato) caption the bottom line "Profit/(Loss)
        # for the year"/"Profit/(loss) before tax", and the literal "/(loss)"
        # infix breaks a plain "profit for the year"/"profit before tax"
        # substring match entirely, not just in `_find_pl_row` (which already
        # strips this — see `_strip_formula_refs`) but also in the page-shape
        # detection below (`is_real_pl_statement`), which used to silently
        # fail to recognise the real P&L statement page on such filings.
        tl = re.sub(r"profit\s*/\s*\(\s*loss\s*\)", "profit", t.lower())
        # Only trust the standalone/consolidated marker when it appears on an
        # actual STATEMENT page (balance sheet or P&L caption), not a bare
        # mention of "Consolidated/Standalone Financial Statements" — that
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
             or ("statement of profit and loss" in tl and "consolidated" not in tl):
            section = "standalone"

        if section != want:
            continue
        # The Cash Flow Statement reconciles operating profit to cash and, in
        # doing so, carries its own "(increase)/decrease in inventories" and
        # "(increase)/decrease in trade receivables" ADJUSTMENT lines (with
        # sign-flipped, wrong-basis values) plus "purchase of property, plant
        # and equipment", "depreciation and amortisation" add-backs, etc. —
        # enough to false-positive every shape-based check below. Exclude it.
        is_cash_flow_page = "cash flow" in tl[:200]
        # A Notes-to-Accounts page can itemize EVERY COGS component as its own
        # note table (e.g. "39. Purchase of Stock in Trade" / "40. Changes in
        # inventories...") and satisfy the "all 3 COGS labels present" check
        # without being the real P&L statement at all (seen on ONGC: this
        # locked pl_idx onto a Notes page hundreds of pages away from the
        # actual statement, so PBT/PAT/Employee Benefit Expense — which only
        # exist on the real statement page — were never found). Require the
        # page to also carry the statement's own bottom-line subtotals, which
        # a components-only Notes page never has.
        is_real_pl_statement = "total expenses" in tl and (
            "profit before tax" in tl or "profit for the year" in tl or "profit for the period" in tl)
        # Some Integrated Annual Reports' Management Discussion & Analysis
        # section prints its OWN presentation-style summary table captioned
        # literally "Consolidated statement of profit and loss" — with
        # "Total expenses"/"Profit for the year" wording too — defeating
        # BOTH safeguards above (seen on Eternal/Zomato: this MD&A table sat
        # on page 42, ~140 pages before the real audited statement, and got
        # mistaken for it, so PBT/PAT/EPS/Employee Benefit Expense — which
        # only the real statement carries in the right note-referenced
        # detail — were never found there). The one reliable tell: a running
        # header naming the MD&A section itself ("Statutory Reports: MD&A"),
        # which the genuine statement (always under "Financial Statements")
        # never carries — and a genuine statement always has a Note-number
        # reference column, which this summary table never does.
        is_mda_page = "md&a" in tl or "management discussion and analysis" in tl
        if pl_cogs_idx is None:
            if is_real_pl_statement and not is_mda_page and all(
                    _find_row_values(t, names) is not None for names in _COGS_LABELS.values()):
                pl_cogs_idx, pl_cogs_text = i, t
            # Shape fallback for no-COGS (services/IT) businesses. Content
            # shape alone isn't enough — Integrated Annual Reports carry
            # multiple MD&A analysis tables (a "Financial performance"
            # summary, an "Expenditure" breakdown, ...) that mention Revenue,
            # Other income, Employee benefits AND Depreciation together
            # without being the actual statement, and got mistaken for it.
            # Require the literal "Statement of Profit and Loss" heading
            # somewhere on the page too (heading POSITION is unreliable, per
            # the header-window issue above, but heading PRESENCE reliably
            # rules out every MD&A analysis table, which never carries it).
            elif pl_shape_idx is None and not is_cash_flow_page and not is_mda_page \
                    and "statement of profit and loss" in tl and _find_revenue(t) is not None \
                    and "other income" in tl \
                    and any(k in tl for k in ("employee benefit", "finance cost", "depreciation and amortisation")):
                pl_shape_idx, pl_shape_text = i, t
        if bs_inv_idx is None and not is_cash_flow_page:
            has_non_current_marker = "property, plant and equipment" in tl or "non-current assets" in tl
            # A genuine Balance Sheet ALWAYS carries a whole-statement subtotal
            # ("Total Assets" or "Equity and Liabilities") — require one here.
            # Without it, a COGS/Depreciation NOTES page false-matches this
            # "strong" inventory signal: such a page mentions "Inventory" (as
            # a COGS sub-line, often a nil "Inventory at the end of the year:
            # -") AND "property, plant and equipment" (in a depreciation
            # note), passing both old checks despite not being a Balance Sheet
            # at all — and since inv-match outranks the shape fallback, it
            # OVERRODE the real BS page (seen on AAKASH, a no-inventory
            # services company: a notes page hijacked bs_idx, so Total Current
            # Assets / Total Equity / Borrowings — which only the real BS has —
            # were all unreadable). Same principle as the P&L's "total
            # expenses" guard against components-only notes pages.
            has_bs_subtotal = "total assets" in tl or "equity and liabilities" in tl
            if _find_row_values(t, _INVENTORY_LABELS) is not None and has_non_current_marker \
                    and has_bs_subtotal:
                bs_inv_idx, bs_inv_text = i, t
            # Shape fallback for no-inventory businesses: "total assets" (the
            # Balance Sheet's own subtotal line — never appears on the Cash
            # Flow Statement) alongside the PPE/non-current marker. Some
            # filings split Assets and Equity-and-Liabilities across two
            # pages, so "equity and liabilities" can't be required on this
            # SAME page — "total assets" already rules out the CFS page.
            elif bs_shape_idx is None and "total assets" in tl and has_non_current_marker \
                    and _find_row_values(t, _RECEIVABLES_LABELS, after=r"\nCurrent Assets\b") is not None:
                bs_shape_idx, bs_shape_text = i, t

    pl_idx, pl_text = (pl_cogs_idx, pl_cogs_text) if pl_cogs_idx is not None else (pl_shape_idx, pl_shape_text)
    bs_idx, bs_text = (bs_inv_idx, bs_inv_text) if bs_inv_idx is not None else (bs_shape_idx, bs_shape_text)

    if pl_idx is None:
        return {"error": f"{'Consolidated' if consolidated else 'Standalone'} Statement of Profit and Loss "
                          "not found in the Annual Report."}
    if bs_idx is None:
        return {"error": f"{'Consolidated' if consolidated else 'Standalone'} Balance Sheet "
                          "not found in the Annual Report."}

    # Best-effort per row from here — a ratio only needs SOME of these fields
    # (Inventory Turnover needs components+inventory; Receivables Turnover
    # needs revenue+receivables), so a missing row doesn't fail the whole
    # extraction; each `fetch_*_from_annual_report` checks what it needs.
    pl_factor = _unit_factor(pl_text)
    bs_factor = _unit_factor(bs_text)

    components = {}
    for canon, names in _COGS_LABELS.items():
        vals = _find_row_values(pl_text, names)
        if vals is not None:
            components[canon] = _scale(vals, pl_factor)  # (current, prior), normalised to ₹ Cr

    # Employee Benefit Expense + Other Expenses — needed (alongside COGS) for
    # EBITDA-basis Operating Profit (Sr No 15): Revenue − COGS − these two.
    # Kept as their OWN fields (not folded into `components`), since Inventory
    # Turnover's COGS sum must stay exactly (a+b+c) — never silently widened.
    employee_benefit_expense = _scale(_find_row_values(pl_text, _EMPLOYEE_BENEFIT_LABELS), pl_factor)
    other_expenses = _scale(_find_row_values(pl_text, _OTHER_EXPENSES_LABELS), pl_factor)
    # Depreciation & Amortisation — needed (alongside COGS/Employee
    # Costs/Other Expenses) for EBIT-basis Operating Profit (Sr No 15):
    # Revenue − COGS − Employee Costs − Other Expenses − D&A.
    depreciation = _scale(_find_row_values(pl_text, _DEPRECIATION_LABELS), pl_factor)

    inv = _scale(_find_row_values(bs_text, _INVENTORY_LABELS), bs_factor)
    revenue = _scale(_find_revenue(pl_text), pl_factor)
    receivables = _scale(_find_row_values(bs_text, _RECEIVABLES_LABELS, after=r"\nCurrent Assets\b"), bs_factor)
    # Cash and Cash Equivalents — only the specifically-labelled row, never
    # "Bank balances other than Cash and Cash Equivalents" (a separate,
    # often part-restricted, line some filings print just below it), and
    # never a restricted/earmarked balance like unpaid dividend accounts or
    # margin money even if it happens to say "cash"/"bank balances" (see
    # `_find_cash_row`).
    cash = _scale(_find_cash_row(bs_text, _CASH_LABELS, after=r"\nCurrent Assets\b"), bs_factor)
    # Other Bank Balances — kept SEPARATE from `cash` on purpose (see
    # _OTHER_BANK_BALANCES_LABELS comment). Restricted/unrestricted split is
    # rebuilt deterministically via `_other_bank_balances_unrestricted`
    # (Base -> Net-off -> Optional-Add) rather than left to AI judgement.
    other_bank_balances = _scale(_find_row_values(bs_text, _OTHER_BANK_BALANCES_LABELS,
                                                   after=r"\nCurrent Assets\b"), bs_factor)
    other_bank_balances_breakup = _other_bank_balances_unrestricted(
        bs_text, _OTHER_BANK_BALANCES_LABELS, after=r"\nCurrent Assets\b")
    if other_bank_balances_breakup is not None and bs_factor != 1.0:
        for k in ("base_cur", "base_prior", "netoff_cur", "netoff_prior",
                  "unrestricted_cur", "unrestricted_prior"):
            if other_bank_balances_breakup.get(k) is not None:
                other_bank_balances_breakup[k] = round(other_bank_balances_breakup[k] * bs_factor, 2)
    # Trade Payables sits under Current Liabilities (Equity & Liabilities
    # side). Some filings print Assets and Equity-and-Liabilities as two
    # separate pages of the same statement (seen on Tata Steel) — the page
    # `bs_idx` was located via (Inventories + Assets markers) may not carry
    # Current Liabilities at all, so also try the immediately following page.
    # Whichever page payables is actually found on determines its own unit
    # factor (usually the same as the primary BS page, but detected fresh in
    # case a filing switches units — unlikely but cheap to guard against).
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
        formula reference right after the label — e.g. "Profit for the year
        (VII - VIII)". The " - " inside that parenthetical is a SUBTRACTION
        sign, not the "-" placeholder `_NUM_RE` uses for a nil/blank cell —
        but `_NUM_RE` can't tell the difference, and matching it as a stray
        "nil" value shifts every real number one slot to the right (current
        year reads as 0, prior year reads as what should have been current).
        Stripping these formula references before searching for numbers
        avoids that misread; they never carry real data themselves.

        ALSO normalises the "Profit/(loss)" caption qualifier down to plain
        "Profit" — many large/diversified filings (e.g. Tata Steel) caption
        every P&L subtotal as "Profit/(loss) before tax" / "Profit/(loss)
        for the year" rather than a plain "Profit before tax"/"Profit for
        the year", to cover both a profit or a loss outcome. Every label in
        `_PBT_LABELS`/`_PAT_OWNERS_LABELS`/`_PAT_GENERIC_LABELS` only ever
        expected the plain wording — the literal "/(loss)" infix broke the
        substring match entirely, a real bug (not a genuinely missing row)
        that silently produced 'Could not find Profit before tax/for the
        year' on any filing using this extremely common caption style.

        The formula-reference parenthetical itself also uses "=" as a
        separator, not just "+"/"-" (e.g. Eternal/Zomato: "(IX= VII-VIII)",
        "(VII= V-VI)") — the original pattern only recognised "+"/"-"
        between the Roman-numeral groups, so parentheticals using "="
        survived stripping and were then mistaken by the line-based reader
        for the row's own "current year" value (since it's the first
        non-blank line after the label, but isn't a pure digit token
        either) — silently producing 0.0 for both years instead of the
        real PBT/PAT figures."""
        text = re.sub(r"profit\s*/\s*\(\s*loss\s*\)", "profit", text, flags=re.I)
        return re.sub(r"\([IVXLCM]+(?:\s*[+\-=]\s*[IVXLCM]+)+\)", "", text, flags=re.I)

    def _find_single_label_loose(segment, label, max_skip=2):
        """Find ONE label's (current, prior) pair in `segment`, tolerating a
        BARE 1-4 digit value with no comma/decimal (e.g. "331") that `_NUM_RE`
        deliberately never matches — that pattern is indistinguishable from a
        Note-number/Page-number column by regex alone, and sacrifices genuine
        small values to avoid grabbing those. Critically, this ISN'T a
        "no match found" case (which `_find_row_values`'s fallback-on-None
        handles) — the regex scan still finds A match, just the WRONG one (it
        skips past "331" straight to the next label's comma-formatted number,
        e.g. "2,082"), so a bare `is None` check never catches it. Real
        financial-statement rows are laid out one token per line though
        (Label / Note# / Page#(-range) / Current / Prior), so this goes
        straight to a line-based read — skip leading pure digit/digit-range
        tokens (note + page columns), then parse the next two lines directly
        via `_parse_num` (which itself handles bare integers fine; only the
        REGEX used to locate candidates was the problem).

        `max_skip` BOUNDS how many leading tokens can be treated as
        metadata (Note#, Page#) rather than real data — needed because a
        genuinely small bare-integer VALUE (e.g. Eternal/Zomato's PAT of
        "527") is textually indistinguishable from a note-number token, so
        an unbounded skip silently ate the real current/prior values
        themselves whenever a P&L subtotal row happened to have NO Note/Page
        metadata directly after it (unlike Balance Sheet rows, which almost
        always do) — the Borrowings use-case this was built for has at most
        2 metadata tokens (Note#, Page#), so callers with no such metadata
        (e.g. `_find_pl_row`) must pass `max_skip=0`."""
        m = re.search(re.escape(label), segment, re.I)
        if not m:
            return None
        window = segment[m.end():m.end() + 250]
        lines = [ln.strip() for ln in window.split("\n") if ln.strip()]
        i = 0
        while i < len(lines) and i < max_skip and re.fullmatch(r"\d{1,4}(-\d{1,4})?", lines[i]):
            i += 1
        if i + 1 < len(lines):
            a, b = _parse_num(lines[i]), _parse_num(lines[i + 1])
            if a is not None and b is not None:
                return (a, b)
        return _find_row_values(segment, [label])

    def _find_pl_row(labels, after=None, max_skip=0):
        """Find a P&L row on the primary pl_text page, falling back to the
        immediately following page — the bottom-line Profit figure often sits
        on a SECOND page of the same statement (Revenue/expenses down to
        Profit Before Tax on page 1, Profit For The Year + OCI + EPS on page
        2), unlike the COGS/Revenue rows which are always on page 1.

        Uses `_find_single_label_loose` per label (line-based: skip leading
        Note/Page-number tokens, then read the next two lines directly via
        `_parse_num`) rather than a flat regex scan over the raw window —
        `_NUM_RE` deliberately never matches a bare 1-4 digit value with no
        comma/decimal (indistinguishable from a Note/Page column by regex
        alone), which silently broke PBT/PAT on any filing reporting whole
        crores under 1000 with no decimals (confirmed on Eternal/Zomato:
        697/291/527/351 are all bare integers — the regex scan skipped past
        them straight to the next visible token, a lone "-" placeholder from
        the following "Exceptional items: -, -" line, giving a bogus (0.0,
        0.0) instead of failing cleanly or finding the real values).

        `max_skip` defaults to 0 (right for PBT/PAT/Tax Expense — computed
        SUBTOTAL rows that carry no Note-number column of their own). A real
        P&L LINE ITEM like Finance Costs DOES have its own Note reference
        printed right after the label (e.g. HUL's "Finance costs \n 33 \n
        410 \n 381") — at max_skip=0 that note number ("33") was silently
        read as the CURRENT-YEAR value and the real 410/381 pair discarded
        entirely (confirmed on HUL: finance_costs came back as (33.0, 410.0)
        instead of (410.0, 381.0), corrupting Interest Coverage Ratio's
        denominator). Callers for genuine line items must pass max_skip>=1."""
        def _try(text):
            search_text = text
            if after:
                m = re.search(after, text, re.I)
                if m:
                    search_text = text[m.end():]
            for label in labels:
                r = _find_single_label_loose(search_text, label, max_skip=max_skip)
                if r is not None:
                    return r
            return None

        raw = _try(_strip_formula_refs(pl_text))
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
          - HUL: no explicit Total line at all — Current tax AND Deferred
            tax both printed in the PROFIT-WALK convention (parenthesized =
            subtracted from Profit Before Tax), e.g. "Current tax (3,163)"
            + "Deferred tax credit/(charge) 3" -> PBT 13,812 - 3,163 + 3 =
            Profit for the year 10,652 — their SUM is negative, needing a
            sign flip to get the positive expense magnitude NOPAT expects.

        Naively matching "tax expense" (a substring of both filers' bare
        header) and reading only the FIRST trailing number grabs just
        Current tax with whatever sign it happens to carry, silently
        breaking the Effective Tax Rate (HUL) or missing the cleaner
        explicit Total line already available (TCS).

        Fixed by: (1) preferring an explicit "total tax expense" line when
        one is printed — trusted as-is, since a filer's own Total line is
        always correctly signed; (2) only when no such line exists, summing
        the Current + Deferred sub-lines (skipping the note-reference token,
        e.g. "9A", between each label and its figures — mirrors
        `_find_single_label_loose`'s skip logic, but restarts from the next
        full line since "Deferred tax credit / (charge)" has trailing
        caption text on the SAME line as the label) and normalising the
        result to positive (a negative sum only ever means the profit-walk
        convention was in play, never a genuine net tax credit at this
        pipeline's guarded PBT > 0)."""
        def _sub_line(window, label):
            m = re.search(re.escape(label), window, re.I)
            if not m:
                return None
            nl = window.find("\n", m.end())
            start = nl + 1 if nl != -1 else m.end()
            lines = [ln.strip() for ln in window[start:start + 150].split("\n") if ln.strip()]
            # max_skip=1, not 2: unlike Borrowings (Note# + Page# both
            # possible), only ONE note-reference token ever sits between a
            # Current/Deferred tax label and its two figures here — skipping
            # 2 would misread a genuinely tiny bare-digit VALUE (e.g.
            # Deferred tax of "3") as a second metadata token instead of the
            # real current-year figure (confirmed on HUL FY26). The pattern
            # covers BOTH note-numbering styles seen in practice: a bare
            # int+letter ("9A", HUL) and a dotted decimal ("2.17", Infosys)
            # — without the dotted-decimal branch, "2.17" reads as the real
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

        def _try(text):
            for lbl in ("total tax expense", "total tax expenses",
                        "tax expense/(credit)", "total tax expense/(credit)"):
                total = _find_single_label_loose(text, lbl, max_skip=0)
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
            nums = re.findall(_NUM_RE, window)
            if len(nums) >= 2:
                a, b = _parse_num(nums[0]), _parse_num(nums[1])
                if a is not None and b is not None:
                    return (a, b)
            return None

        raw = _try(_strip_formula_refs(pl_text))
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
    # the year" including Non-Controlling Interest just above/below it — per
    # spec we must never use that combined figure); falls back to the
    # generic "Profit for the year" labels for standalone reports with no
    # NCI split, where that IS the owners' figure.
    pat = _find_pl_row(_PAT_OWNERS_LABELS)
    pat_basis = "owners" if pat is not None else None
    if pat is None:
        pat = _find_pl_row(_PAT_GENERIC_LABELS)
        pat_basis = "generic" if pat is not None else None

    # EBIT approximation (Sr No 19 numerator) = Profit Before Tax + Finance
    # Costs. Both are single, unambiguous P&L lines — no owners/NCI split
    # concern like PAT (PBT is struck before the profit is even attributed).
    pbt = _find_pl_row(_PBT_LABELS)
    finance_costs = _find_pl_row(_FINANCE_COST_LABELS, max_skip=1)
    tax_expense = _find_tax_expense()
    # Basic EPS (Sr No 24 denominator) — same page-fallback as PAT/PBT/OCI,
    # since the "Earnings per equity share" line sits in the same bottom
    # section of the P&L statement. EPS is a per-share ₹ figure, NEVER a
    # ₹ Crore statement line — deliberately bypasses `_scale()`'s Crore/
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

    # Number of Equity Shares Outstanding (Sr No 25 denominator component) —
    # lives in a Notes-to-Accounts page far from bs_idx, so this is a
    # dedicated forward scan (see _find_shares_outstanding's own docstring).
    shares_outstanding = _find_shares_outstanding(doc, bs_idx, want)

    # Net Operating Cash Flow (Sr No 35 numerator), Capex components (Sr No
    # 36 denominator), and Repayment of Borrowings/Lease Liabilities (Sr No
    # 34 denominator components) — all from the Cash Flow Statement (see
    # _find_cash_flow_statement_items's own docstring).
    cf_items = _find_cash_flow_statement_items(doc, bs_idx, want)

    # Dividend per Share (Sr No 27 numerator) — ALWAYS standalone (see
    # `_find_dividend_per_share`'s docstring), scanned from page 0 since
    # Standalone statements always precede Consolidated ones in the Ind AS
    # filing template, regardless of which section THIS extraction (`want`)
    # was requested for.
    dividend_per_share, dividend_found = _find_dividend_per_share(doc, 0)

    def _find_bs_row(labels, after=None, subtotal_before=None, reject_after=None, permissive=False):
        """Find a Balance Sheet row on the primary bs_text page, falling back
        to the immediately following page (Assets/Equity-and-Liabilities are
        sometimes split across two pages of the same statement — seen on
        Tata Steel), each normalised to ₹ Cr with its OWN detected unit. If
        `subtotal_before` is given and the labelled search fails on a page,
        also tries reading the BARE number pair immediately preceding that
        marker on the same page (some filings, e.g. Asian Paints, print the
        Current Assets/Liabilities subtotal with no label of its own).

        The NEXT page is skipped if it's a Cash Flow Statement — that
        statement carries its own "(increase)/decrease"-style ADJUSTMENT
        lines with the SAME labels a genuine BS row would use (e.g. "Short
        term borrowings (Net)" as a financing-activities cash-flow line, a
        completely different, wrong-basis, sign-flipped figure from the
        actual Balance Sheet closing balance) — seen on MARUTI, where the BS
        is immediately followed by the Cash Flow Statement and a naive
        next-page read grabbed a negative cash-flow adjustment instead of the
        real (positive, or genuinely absent) Balance Sheet borrowings figure."""
        def _try(text):
            v = _find_row_values(text, labels, after=after, reject_after=reject_after, permissive=permissive)
            if v is None and subtotal_before:
                v = _find_subtotal_before(text, subtotal_before, after=after)
            return v
        raw = _try(bs_text)
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
        markers — needed for a generically-labeled row like plain
        "Borrowings" that appears under BOTH "Non-current Liabilities" and
        "Current Liabilities" sections with the SAME label text (only the
        section heading distinguishes long-term from short-term). Without an
        upper bound, searching "after Non-current Liabilities" for a company
        with NO non-current borrowings (e.g. MARUTI) would run straight past
        the empty Non-current section and wrongly grab the Current section's
        entry instead, mislabelling short-term debt as long-term. Also tries
        the immediately FOLLOWING page (skipping Cash Flow Statement pages,
        same as `_find_bs_row`) — the Balance Sheet's Equity & Liabilities
        side, where Borrowings sits, is sometimes a "(CONTD.)" continuation
        page (seen on Tata Steel)."""
        segment = _bounded_segment(bs_text, start_after, stop_before)
        raw = _find_single_label_loose(segment, labels[0]) if segment else None
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
        return _scale(raw, factor)

    # Total Assets is the Balance Sheet's own closing subtotal (the last line
    # of the Assets side).
    total_assets = _find_bs_row(_TOTAL_ASSETS_LABELS)
    # Total Current Assets / Total Current Liabilities — the two subtotals
    # Working Capital (Sr No 13/26) is built from: Working Capital = Total
    # Current Assets − Total Current Liabilities. Fall back to the bare
    # number pair before TOTAL ASSETS / TOTAL EQUITY AND LIABILITIES when
    # there's no explicit "Total current assets/liabilities" label.
    total_current_assets = _find_bs_row(_TOTAL_CURRENT_ASSETS_LABELS, after=r"\nCurrent Assets\b",
                                         subtotal_before="total assets")
    total_current_liabilities = _find_bs_row(_TOTAL_CURRENT_LIABILITIES_LABELS, after=r"\nCurrent Liabilities\b",
                                              subtotal_before="total equity and liabilities")

    # Net Fixed Assets (Sr No 30 denominator).
    net_fixed_assets = _find_bs_row(_NET_FIXED_ASSETS_LABELS)

    # Total Equity (Sr No 18 denominator): owners-attributable portion.
    # Preferred path: sum Equity Share Capital + Other Equity directly — both
    # are ALWAYS the parent/owners' portion under Ind AS (Non-Controlling
    # Interest is always its own separate line, never blended into either),
    # so this is correct regardless of how (or whether) the filer prints an
    # explicit "Total Equity" subtotal at all.
    # "Equity share capital" is looked up with the same bounded, note-
    # reference-tolerant helper written for the Payables MSME fix (a plain
    # `permissive` number match alone would grab the note-reference digit
    # printed between the label and the real figures, e.g. "...capital \n 17
    # \n 235 \n 235" — taking the LAST two numbers before the next row's
    # label avoids that regardless of whether a reference digit is present).
    equity_share_capital, _ = _find_payables_row(bs_text, r"equity\s+share\s+capital", r"other\s+equity")
    other_equity_amt = _find_bs_row(_OTHER_EQUITY_LABELS)
    if equity_share_capital is not None and other_equity_amt is not None:
        equity = (round(equity_share_capital[0] + other_equity_amt[0], 2),
                  round(equity_share_capital[1] + other_equity_amt[1], 2))
        equity_basis = "owners"
    else:
        # Fall back to an explicit "...attributable to owners..." label,
        # then a generic "Total Equity"/"Shareholders' Funds" label — the
        # latter REJECTS a match immediately followed by "and liabilities",
        # since "total equity" is a literal substring of "TOTAL EQUITY AND
        # LIABILITIES" (the whole Balance Sheet grand total, not equity at
        # all — confirmed silently happening on HUL, whose actual equity
        # subtotal is phrased "Total - Equity (A)" and so never matched the
        # bare "total equity" search to begin with).
        equity = _find_bs_row(_EQUITY_OWNERS_LABELS)
        equity_basis = "owners" if equity is not None else None
        if equity is None:
            equity = _find_bs_row(_EQUITY_GENERIC_LABELS, reject_after=r"\s*and\s+liabilities")
            equity_basis = "generic" if equity is not None else None

    # Total Equity, WHOLE-entity (owners' + Non-Controlling Interest) — Sr
    # No 23 Debt-to-Equity's denominator (see `_NCI_LABELS` comment above).
    # NCI is genuinely absent (real ₹0, standalone company or no minority
    # shareholders) whenever its label isn't found at all — `equity_full`
    # then correctly reduces to the same owners-only figure as `equity`.
    # Same note-reference-digit hazard as Equity Share Capital/Lease
    # Liabilities above (NCI is routinely a small, comma-less figure with a
    # note number printed right after its label) — reuses the same
    # last-two-numbers-before-the-next-label helper rather than a blind
    # permissive first-two match.
    # Some filers (e.g. Tata Steel) print Assets and Equity-and-Liabilities
    # as two SEPARATE pages of the same statement — `bs_text` here is
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
        for page_text, page_factor in nci_search_pages:
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
    # genuinely debt-free company (a real ₹0, not missing data) — summed
    # individually rather than gated on all three being present.
    #
    # Many filings label the row just "Borrowings" (no "long-term"/"current"
    # prefix) since the Non-current-vs-Current split already comes from
    # which SECTION it sits under, not the label itself — tried as a
    # section-scoped fallback when the more specific label isn't found.
    lt_borrowings = _find_bs_row(_LT_BORROWINGS_LABELS)
    if lt_borrowings is None:
        lt_borrowings = _find_bs_row_bounded(["borrowings"], r"\nNon-current Liabilities\b", r"\nCurrent Liabilities\b")
    st_borrowings = _find_bs_row(_ST_BORROWINGS_LABELS)
    if st_borrowings is None:
        st_borrowings = _find_bs_row_bounded(["borrowings"], r"\nCurrent Liabilities\b", r"\nTotal Equity and Liabilities\b")
    current_maturities = _find_bs_row(_CURRENT_MATURITIES_LABELS)

    # Distinguishes "genuinely absent" (real ₹0 — a debt-free company) from
    # "extraction failure" (the label IS present on the face of the Balance
    # Sheet but its value pair couldn't be parsed) — a bare substring probe
    # across both liabilities sections, independent of whether the value-pair
    # read above succeeded. Used by `_compute_total_debt`'s hard Finance-Costs
    # cross-check so a parse failure is never silently reported as a
    # confident, debt-free "0".
    borrowings_face_label_found = bool(re.search(r"\bborrowings\b", bs_text, re.I))

    # Lease Liabilities (Total Debt Sr No 20 component b) — Non-current and
    # Current, section-scoped. Lease Liabilities is routinely a small
    # (sub-1,000, no thousands separator) figure with a note-reference digit
    # printed right after the label — e.g. HUL's Current Lease Liabilities
    # row is "Lease Liabilities \n 20 \n 374 \n 404" — the exact same shape
    # as the Equity Share Capital fix above, so it reuses that fix's helper
    # (`_find_payables_row`: permissive number matching + take the LAST two
    # numbers before the next row's label, which skips the note-ref digit
    # AND stays bounded so it can never reach into a later row). Plain
    # `_find_bs_row`'s strict `_NUM_RE` can't match "374"/"404" at all (no
    # comma, no 2-decimal suffix) and was silently falling through to the
    # NEXT comma-formatted numbers on the page — HUL's Trade Payables row
    # (12,867 / 11,052) — reporting someone else's trade payables as if they
    # were lease liabilities.
    lease_nc_anchor = re.search(r"\nNon-current Liabilities\b", bs_text, re.I)
    lease_liabilities_nc = None
    if lease_nc_anchor:
        lease_nc_row, _ = _find_payables_row(
            bs_text[lease_nc_anchor.end():], r"lease\s+liabilit(?:y|ies)",
            r"other\s+financial\s+liabilit|provisions|deferred\s+tax|\nCurrent Liabilities\b")
        lease_liabilities_nc = _scale(lease_nc_row, bs_factor)
    if lease_liabilities_nc is None:
        lease_liabilities_nc = _find_bs_row_bounded(
            _LEASE_LIABILITY_NC_LABELS, r"\nNon-current Liabilities\b", r"\nCurrent Liabilities\b")
    lease_cur_anchor = re.search(r"\nCurrent Liabilities\b", bs_text, re.I)
    lease_liabilities_cur = None
    if lease_cur_anchor:
        lease_cur_row, _ = _find_payables_row(
            bs_text[lease_cur_anchor.end():], r"lease\s+liabilit(?:y|ies)",
            r"trade\s+payables|other\s+financial\s+liabilit|other\s+current\s+liabilit|provisions")
        lease_liabilities_cur = _scale(lease_cur_row, bs_factor)
    if lease_liabilities_cur is None:
        lease_liabilities_cur = _find_bs_row_bounded(
            _LEASE_LIABILITY_CUR_LABELS, r"\nCurrent Liabilities\b", r"\nTotal Equity and Liabilities\b")

    # Other Financial Liabilities (Total Debt Sr No 20 component c) — Three-
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

    # Borrowings Note verification (Total Debt Sr No 20 component a) —
    # mandatory cross-check against the Notes-to-Accounts Borrowings
    # breakup, not the Balance Sheet face value alone. Scans forward from
    # the Balance Sheet page (Notes always follow the statements).
    try:
        borrowings_note = _find_borrowings_note_total(doc, bs_idx)
    except Exception:
        borrowings_note = None
    borrowings_note_total_cur, borrowings_note_subitems = (
        borrowings_note if borrowings_note is not None else (None, None))

    return {
        "components": components,    # {label: (cur, prior)} — may be partial/empty, normalised to ₹ Cr
        "inventory": inv,            # (cur, prior) or None, normalised to ₹ Cr
        "revenue": revenue,          # (cur, prior) or None, normalised to ₹ Cr
        "receivables": receivables,  # (cur, prior) or None
        "payables": payables,        # (cur, prior) or None
        "cash": cash,                # (cur, prior) or None, normalised to ₹ Cr
        "other_bank_balances": other_bank_balances,  # (cur, prior) or None — line total, informational
        "other_bank_balances_breakup": other_bank_balances_breakup,  # dict or None — Base/Net-off/Optional-Add, see comment above
        "employee_benefit_expense": employee_benefit_expense,  # (cur, prior) or None, normalised to ₹ Cr
        "other_expenses": other_expenses,  # (cur, prior) or None, normalised to ₹ Cr
        "depreciation": depreciation,  # (cur, prior) or None, normalised to ₹ Cr
        "pat": pat,  # (cur, prior) or None, normalised to ₹ Cr — owners-attributable Profit After Tax
        "pat_basis": pat_basis,  # "owners" (explicit attribution line found) or "generic" (no NCI split found)
        "pbt": pbt,  # (cur, prior) or None, normalised to ₹ Cr — Profit Before Tax
        "finance_costs": finance_costs,  # (cur, prior) or None, normalised to ₹ Cr
        "tax_expense": tax_expense,  # (cur, prior) or None, normalised to ₹ Cr — Sr No 42/43
        "eps": eps,  # (cur, prior) or None, ₹ per share (Basic) — NEVER Crore-scaled, unlike every other field here
        "shares_outstanding": shares_outstanding,  # (cur, prior) or None, raw share COUNT — NEVER Crore-scaled
        "borrowings_repayment": cf_items.get("borrowings_repayment"),  # (cur, prior) or None, normalised to ₹ Cr — Sr No 34
        "lease_repayment": cf_items.get("lease_repayment"),  # (cur, prior) or None, normalised to ₹ Cr — Sr No 34
        "operating_cash_flow": cf_items.get("operating_cash_flow"),  # (cur, prior) or None, normalised to ₹ Cr — Sr No 35
        "capex_ppe_purchase": cf_items.get("capex_ppe_purchase"),  # (cur, prior) or None, normalised to ₹ Cr — Sr No 36
        "capex_intangible_purchase": cf_items.get("capex_intangible_purchase"),  # (cur, prior) or None, normalised to ₹ Cr — Sr No 36
        "capex_disposal_proceeds": cf_items.get("capex_disposal_proceeds"),  # (cur, prior) or None, normalised to ₹ Cr — Sr No 36
        "dividend_per_share": dividend_per_share,  # ₹ per share DECLARED during the year, ALWAYS standalone-sourced
        "dividend_per_share_found": dividend_found,  # False when defaulted to 0.0 (genuine zero vs. unconfirmed)
        "lt_borrowings": lt_borrowings,  # (cur, prior) or None, normalised to ₹ Cr
        "st_borrowings": st_borrowings,  # (cur, prior) or None, normalised to ₹ Cr
        "current_maturities": current_maturities,  # (cur, prior) or None, normalised to ₹ Cr
        "borrowings_face_label_found": borrowings_face_label_found,  # bool — "Borrowings" text present on the BS face at all
        "borrowings_note_total_cur": borrowings_note_total_cur,  # ₹ Cr or None — independent Notes-breakup cross-check
        "borrowings_note_subitems": borrowings_note_subitems,  # int or None — how many Note sub-items were summed
        "lease_liabilities_nc": lease_liabilities_nc,  # (cur, prior) or None, normalised to ₹ Cr — Total Debt component b
        "lease_liabilities_cur": lease_liabilities_cur,  # (cur, prior) or None, normalised to ₹ Cr — Total Debt component b
        "other_fin_liab_nc": other_fin_liab_nc,  # dict or None — Non-current Other Financial Liabilities, Three-Part Test
        "other_fin_liab_cur": other_fin_liab_cur,  # dict or None — Current Other Financial Liabilities, Three-Part Test
        "total_assets": total_assets,  # (cur, prior) or None, normalised to ₹ Cr
        "total_current_assets": total_current_assets,           # (cur, prior) or None, normalised to ₹ Cr
        "total_current_liabilities": total_current_liabilities,  # (cur, prior) or None, normalised to ₹ Cr
        "net_fixed_assets": net_fixed_assets,  # (cur, prior) or None, normalised to ₹ Cr — Sr No 30
        "equity": equity,  # (cur, prior) or None, normalised to ₹ Cr — owners-attributable Total Equity
        "equity_basis": equity_basis,  # "owners" (explicit exclusion of NCI found) or "generic" (no NCI split found)
        "equity_full": equity_full,  # (cur, prior) or None, normalised to ₹ Cr — WHOLE-entity Total Equity (owners' + NCI); same as `equity` when NCI is absent
        "retained_earnings": retained_earnings,  # (cur, prior) or None, normalised to ₹ Cr — Sr No 55 (Altman Z-Score)
        "retained_earnings_basis": retained_earnings_basis,  # "exact" (Reserves and Surplus) or "other_equity_proxy"
        "pl_page": pl_idx + 1, "bs_page": bs_idx + 1,
    }


def _get_extracted_financials(symbol, name, fiscal_year, consolidated=True):
    """Lock-guarded entry point for `_get_extracted_financials_impl` — see
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
    ckey = f"ar_extract_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    with _extract_lock_for(ckey):
        cached = _read_cache(ckey)
        if cached is not None:
            return cached
        return _get_extracted_financials_impl(symbol, name, fiscal_year, consolidated)


def _get_extracted_financials_impl(symbol, name, fiscal_year, consolidated=True):
    """Shared, cached PDF fetch + parse. Every ratio derived from the same
    Annual Report (Inventory Turnover, Receivables Turnover, ...) reuses this
    single result instead of re-downloading a 10-30MB PDF per ratio. Returns
    `_extract_from_pdf`'s dict (with `source_url` added) or
    {'error': reason, 'source_url': ...}. Cached 90 days — EXCEPT network/IO
    failures (timeouts etc.), which are transient and must NOT be persisted
    for a week (the shared cache TTL): a user hitting a slow network blip
    would otherwise see that exact failure baked in for every subsequent
    visit. Never raises, and never surfaces a raw exception string — that's
    an internal detail, not something a user should see on the dashboard."""
    sym = symbol.strip().upper().replace(".NS", "")
    # "_v2" cache-busts every extraction cached before the Cash Flow
    # Statement parser fix (broader max_pages, CFS-caption-aware section
    # tracking, relaxed boundary regexes, expanded label coverage) — older
    # cached extractions had operating_cash_flow/capex_*/*_repayment/
    # net_fixed_assets all silently null and would otherwise keep being
    # served for the remainder of their 90-day TTL regardless of the fix.
    ckey = f"ar_extract_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    try:
        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            out = {"error": "Annual Report not found for this year."}
            _write_cache(ckey, out)
            return out

        # NSE archive URLs (nsearchives.nseindia.com) need the cookie-primed
        # NSE session + Referer, and some older ones are .zip-wrapped — route
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
            return {"error": "Could not download the Annual Report right now — please try again "
                              "in a moment.", "source_url": pdf_url}  # not cached: transient, retry next call

        if len(content) < 50000:
            out = {"error": "Annual Report download failed or too small.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        parsed = _extract_from_pdf(content, consolidated=consolidated)
        # Consolidated-to-standalone fallback (per spec: "use Consolidated
        # first; fall back to Standalone only if Consolidated is
        # unavailable"). Many companies — especially smaller/SME/NSE-only
        # names with no subsidiaries (e.g. AAKASH) — file ONLY standalone
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
                _write_cache(ckey, standalone)
                return standalone
        if "error" in parsed:
            out = {"error": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        parsed["source_url"] = pdf_url
        parsed["basis_used"] = "consolidated" if consolidated else "standalone"
        _write_cache(ckey, parsed)
        return parsed
    except Exception as e:
        print(f"[annual_report_financials] unexpected error for {sym} FY{fiscal_year}: {e}")
        return {"error": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/internal error shouldn't be locked in for a week either


def fetch_inventory_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Public entry point. `fiscal_year` = the calendar year the FY ends in (e.g.
    2024 for 'year ended March 31, 2024'). Returns a dict shaped like
    nse_xbrl.fetch_inventory_turnover()'s applicable-case output, or
    {'applicable': False, 'reason': ...}. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_invturn_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        components = parsed.get("components") or {}
        # Per spec, COGS = SUM of whichever of the three (a: Cost of materials
        # consumed, b: Purchases of stock-in-trade, c: Changes in inventories)
        # a company actually reports — a pure trading/retail business (e.g.
        # DMART) legitimately has ONLY (b) and possibly (c), with NO "Cost of
        # materials consumed" line at all, because it doesn't manufacture
        # anything. That's a real ₹0 for component (a), not missing data — it
        # must NOT be treated as "not a goods business". Only flag N/A when
        # NONE of the three components were found at all (e.g. a pure
        # services business with no COGS concept whatsoever).
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if parsed.get("inventory") is None:
            out = {"applicable": False, "reason": "Could not find 'Inventories' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cogs_cur = sum(v[0] for v in components.values())
        inv_cur, inv_prior = parsed["inventory"]
        if inv_cur <= 0:
            out = {"applicable": False, "reason": "Inventory value is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        # Denominator per spec: (Opening + Closing) / 2 when both are present
        # (confidence 1.0); else Closing only, flagged Estimated (confidence 0.8).
        if inv_prior and inv_prior > 0:
            avg_inv = round((inv_cur + inv_prior) / 2, 2)
            den_label = "Average Inventory (opening + closing) ÷ 2"
            inv_by_year = {f"FY{fiscal_year}": round(inv_cur, 2), f"FY{fiscal_year - 1}": round(inv_prior, 2)}
            confidence, estimated = 1.0, False
        else:
            avg_inv = round(inv_cur, 2)
            den_label = "Closing Inventory (opening/prior-year unavailable)"
            inv_by_year = {f"FY{fiscal_year}": round(inv_cur, 2)}
            confidence, estimated = 0.8, True

        # Per spec's confidence tiers, a COGS built from fewer than all three
        # disclosed line items (e.g. a trader with only Purchases of
        # stock-in-trade) is "calculated from 2-3 clearly disclosed line
        # items" territory, not the full 1.0 — cap it at 0.95 regardless of
        # how complete the inventory-averaging side is.
        if len(components) < len(_COGS_LABELS):
            confidence = min(confidence, 0.95)

        ratio = round(cogs_cur / avg_inv, 2) if avg_inv else None

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Cost of Goods Sold (a + b + c)",
                "value_cr": round(cogs_cur, 2),
                "components": {k: round(v[0], 2) for k, v in parsed["components"].items()},
            },
            "denominator": {
                "label": den_label, "value_cr": avg_inv,
                "inventory_by_year": inv_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — both years read from the same statement, "
                     "so the prior-year comparator is always on a consistent (restated) basis."
                     if not estimated else
                     "From the company's own Annual Report. Prior-year (opening) inventory was not "
                     "disclosed, so Average Inventory uses the closing figure only — flagged as an estimate."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_gross_profit_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Gross Profit Margin = (Revenue from Operations − COGS) ÷ Revenue from
    Operations, where COGS = the SAME (a+b+c) components validated for
    Inventory Turnover (Sr No 1) — Ind AS Schedule III has no explicit "Gross
    Profit" line, so it must always be reconstructed, never taken from a
    pre-computed Screener/MD&A figure without checking how it was derived.
    Point-in-time (current year only) — a margin ratio, not a turnover ratio,
    so no averaging applies. Reuses the SAME cached PDF extraction — no extra
    download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_gpm_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        components = parsed.get("components") or {}
        # Same relaxed gate as Inventory Turnover — sum whichever COGS
        # components a company actually reports (a pure trader legitimately
        # has no "Cost of materials consumed" line at all, that's a real ₹0,
        # not missing data); only N/A when NONE were found.
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur == 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cogs_cur = sum(v[0] for v in components.values())
        gross_profit = rev_cur - cogs_cur
        margin = round((gross_profit / rev_cur) * 100, 2)
        # Per spec's confidence tiers: COGS built from fewer than all three
        # disclosed line items is "2-3 line items" territory (0.95), not the
        # full 1.0 (which implies the value is directly/completely stated).
        confidence = 1.0 if len(components) == len(_COGS_LABELS) else 0.95

        out = {
            "applicable": True,
            "value": margin, "unit": "%",
            "confidence": confidence,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Gross Profit (Revenue − COGS)",
                "value_cr": round(gross_profit, 2),
                "components": {
                    "Revenue from Operations": round(rev_cur, 2),
                    **{f"less: {k}": round(v[0], 2) for k, v in components.items()},
                },
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — Ind AS Schedule III has no explicit 'Gross Profit' "
                    "line, so this is reconstructed as Revenue from Operations minus the same Cost of Goods Sold "
                    "components (a+b+c) validated for Inventory Turnover.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_operating_profit_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Operating Profit Margin (EBIT Basis) = (Revenue − COGS − Employee
    Benefit Expense − Other Expenses − Depreciation & Amortisation) ÷
    Revenue. Per spec this is EBIT-basis, NOT EBITDA-basis — Depreciation &
    Amortisation is a real operating cost of running the business and must
    be deducted; the prior definition omitted it and was actually computing
    EBITDA under the "Operating Profit Margin" name. Still excludes Finance
    Costs, Other Income and Exceptional Items (those stay non-operating).
    COGS reuses the SAME (a+b+c) components validated for Inventory
    Turnover/Gross Profit Margin (Sr No 1/14); this additionally needs
    Employee Benefit Expense, Other Expenses and Depreciation & Amortisation,
    which Gross Profit Margin doesn't. Point-in-time (current year only, no
    averaging — a margin ratio). All required line items must be present
    (same all-or-nothing gate as Sr No 1/14) — a missing one means N/A, never
    a partial/approximate margin. Reuses the SAME cached PDF extraction — no
    extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_opm_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        components = parsed.get("components") or {}
        # Same relaxed gate as Inventory Turnover/Gross Profit Margin — a pure
        # trader legitimately has no "Cost of materials consumed" line at all
        # (a real ₹0, not missing data); only N/A when NONE were found.
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        dep = parsed.get("depreciation")
        if ebe is None:
            out = {"applicable": False, "reason": "Could not find 'Employee Benefit Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if oe is None:
            out = {"applicable": False, "reason": "Could not find 'Other Expenses' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if dep is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Depreciation and Amortisation Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur == 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        dep_cur, _dep_prior = dep
        operating_profit = rev_cur - cogs_cur - ebe_cur - oe_cur - dep_cur
        margin = round((operating_profit / rev_cur) * 100, 2)
        # Per spec's confidence tiers: COGS built from fewer than all three
        # disclosed line items is "2-3 line items" territory (0.95), not 1.0.
        confidence = 1.0 if len(components) == len(_COGS_LABELS) else 0.95

        out = {
            "applicable": True,
            "value": margin, "unit": "%",
            "confidence": confidence,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Operating Profit / EBIT (Revenue − COGS − Employee Costs − Other Expenses − D&A)",
                "value_cr": round(operating_profit, 2),
                "components": {
                    "Revenue from Operations": round(rev_cur, 2),
                    **{f"less: {k}": round(v[0], 2) for k, v in components.items()},
                    "less: Employee Benefit Expense": round(ebe_cur, 2),
                    "less: Other Expenses": round(oe_cur, 2),
                    "less: Depreciation and Amortisation Expense": round(dep_cur, 2),
                },
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — EBIT-basis Operating Profit: Revenue from Operations "
                    "minus all operating expense lines (COGS a+b+c + Employee Benefit Expense + Other Expenses + "
                    "Depreciation and Amortisation Expense), excluding Finance Costs, Other Income and "
                    "Exceptional Items.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_net_profit_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Net Profit Margin = Profit After Tax (attributable to owners of the
    company/parent) ÷ Revenue from Operations. For CONSOLIDATED statements,
    per spec this must be the owners-attributable figure, NEVER the combined
    total including Non-Controlling/Minority Interest. `pat_basis` from the
    shared extraction tells us which was actually found: "owners" (an
    explicit attribution line was matched — high confidence) or "generic"
    (no NCI-split line found, so we fell back to the plain "Profit for the
    year" label — for a STANDALONE statement that's correct by definition
    since there's no NCI to speak of, but for a CONSOLIDATED statement it's
    genuinely ambiguous whether that figure already excludes NCI, so
    confidence is capped at 0.8 and this is called out in the note). No
    averaging (point-in-time, current year only — a margin ratio). Reuses
    the SAME cached PDF extraction — no extra download. Cached 90 days.
    Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_npm_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        pat = parsed.get("pat")
        if pat is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Profit for the year'/'Profit after tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur == 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pat_cur, _pat_prior = pat
        pat_basis = parsed.get("pat_basis")
        ambiguous_nci = consolidated and pat_basis != "owners"
        confidence = 0.8 if ambiguous_nci else 1.0
        margin = round((pat_cur / rev_cur) * 100, 2)

        pat_label = ("Profit for the Year Attributable to Owners of the Company"
                     if pat_basis == "owners" else "Profit for the Year")

        out = {
            "applicable": True,
            "value": margin, "unit": "%",
            "confidence": confidence,
            "estimated": ambiguous_nci,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": pat_label,
                "value_cr": round(pat_cur, 2),
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": ("From the company's own Annual Report — Profit for the Year attributable to Owners of the "
                     "Company, explicitly separate from Non-Controlling Interest."
                     if pat_basis == "owners" else
                     "From the company's own Annual Report. This filing did not print a separate "
                     "owners-vs-Non-Controlling-Interest attribution line, so 'Profit for the Year' is used as-is — "
                     "for a standalone statement this is exact; for a consolidated statement with genuine minority "
                     "interests it may include a small NCI portion, hence the reduced confidence."
                     if ambiguous_nci else
                     "From the company's own Annual Report — Profit for the Year (standalone, no Non-Controlling "
                     "Interest applies)."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_return_on_equity_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Return on Equity (ROE) = Profit After Tax (owners-attributable, reused
    from Sr No 16) ÷ Average Total Equity (owners-attributable, excluding
    Non-Controlling Interest for consolidated statements). Unlike PAT itself
    (point-in-time), the DENOMINATOR here IS averaged per spec — same
    opening+closing/2 convention as the other "Average X" ratios.

    Per spec, this must NEVER be calculated when equity is negative (closing
    or average) — a negative-equity company would otherwise show a spurious
    POSITIVE ratio (negative ÷ negative), which is actively misleading, not
    just imprecise. Confidence follows the same owners-vs-generic pattern as
    Sr No 16: 1.0 if an explicit owners/NCI-excluding equity line was found
    (or the statement is standalone with no NCI to split out), 0.8 if a
    consolidated statement had no such line and we fell back to the generic
    "Total Equity" label (genuinely uncertain whether NCI is included).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_roe_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        pat = parsed.get("pat")
        if pat is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Profit for the year'/'Profit after tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity = parsed.get("equity")
        if equity is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Total Equity'/'Shareholders' Funds' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pat_cur, _pat_prior = pat
        equity_cur, equity_prior = equity
        equity_basis = parsed.get("equity_basis")

        # Average when both years are present and BOTH are positive; if
        # either year is negative, per spec we don't calculate at all (not
        # even a closing-only fallback) — a negative-equity ROE is
        # meaningless/misleading regardless of averaging method.
        if equity_cur <= 0 or (equity_prior is not None and equity_prior <= 0):
            out = {"applicable": False,
                   "reason": "Shareholders' Equity is negative (or zero) for this company — ROE would be "
                             "meaningless/misleading (a negative ÷ negative produces a spurious positive ratio), "
                             "so it's flagged as N/A rather than reported, per spec.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Profit After Tax", "value_cr": round(pat_cur, 2)},
                   "denominator": {"label": "Total Equity", "value_cr": round(equity_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page"), bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        if equity_prior and equity_prior > 0:
            avg_equity = round((equity_cur + equity_prior) / 2, 2)
            den_label = "Average Total Equity (opening + closing) ÷ 2"
            equity_by_year = {f"FY{fiscal_year}": round(equity_cur, 2), f"FY{fiscal_year - 1}": round(equity_prior, 2)}
            averaged = True
        else:
            avg_equity = round(equity_cur, 2)
            den_label = "Closing Total Equity (opening/prior-year unavailable)"
            equity_by_year = {f"FY{fiscal_year}": round(equity_cur, 2)}
            averaged = False

        ambiguous_nci = consolidated and equity_basis != "owners"
        # Confidence takes the more cautious of the two independent concerns:
        # opening-equity unavailability (like every other "Average X" ratio)
        # and NCI ambiguity (like Sr No 16) — capped at whichever is lower.
        confidence = 1.0
        if ambiguous_nci:
            confidence = min(confidence, 0.8)
        if not averaged:
            confidence = min(confidence, 0.8)

        roe = round((pat_cur / avg_equity) * 100, 2)

        equity_label = ("Total Equity Attributable to Owners of the Company"
                        if equity_basis == "owners" else "Total Equity")

        out = {
            "applicable": True,
            "value": roe, "unit": "%",
            "confidence": confidence,
            "estimated": ambiguous_nci or not averaged,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Profit After Tax (owners-attributable)",
                "value_cr": round(pat_cur, 2),
            },
            "denominator": {
                "label": f"{den_label} — {equity_label}", "value_cr": avg_equity,
                "equity_by_year": equity_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page"), bs_page=parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — Total Equity attributable to Owners of the Company, "
                     "explicitly separate from Non-Controlling Interest."
                     if equity_basis == "owners" else
                     "From the company's own Annual Report. This filing did not print a separate "
                     "owners-vs-Non-Controlling-Interest equity split, so 'Total Equity' is used as-is — for a "
                     "standalone statement this is exact; for a consolidated statement with genuine minority "
                     "interests it may include a small NCI portion, hence the reduced confidence.")
                    + (" Prior-year (opening) equity was not disclosed, so Average Equity uses the closing figure "
                       "only — flagged as an estimate." if not averaged else ""),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_return_on_capital_employed_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Return on Capital Employed (ROCE) = EBIT ÷ Average Capital Employed, where:
      - EBIT (numerator, current year only — no averaging) is APPROXIMATED as
        Profit Before Tax + Finance Costs (adding back only interest, NEVER
        Depreciation — that would compute EBITDA and inflate ROCE).
      - Capital Employed (denominator) = Total Assets − Total Current
        Liabilities, reusing Sr No 7's Total Assets and Sr No 10's Total
        Current Liabilities — averaged (opening + closing) ÷ 2 like the
        other "Average X" ratios.
    Per spec, N/A if Average Capital Employed ≤ 0 (never divides through a
    non-positive capital base). Reuses the SAME cached PDF extraction — no
    extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_roce_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        # EBIT = Revenue − COGS − Employee Benefit Expense − Other Expenses
        # (i.e. Revenue − (Total Expenses − Finance Costs)) — the SAME
        # computation already validated for Sr No 15's Operating Profit
        # Margin, NOT "Profit Before Tax + Finance Costs". The PBT-based
        # approximation silently pulled in Other Income (non-operating,
        # never part of EBIT) — confirmed on HUL: PBT-before-exceptional
        # (Rs 14,047 Cr) implicitly includes Rs 751 Cr of Other Income and
        # nets off a Rs 15 Cr JV-share loss, inflating "EBIT" to Rs 14,457 Cr
        # versus the correct Rs 13,721 Cr. This formula also correctly stays
        # scoped to Continuing Operations only where a filer splits the P&L
        # into Continuing/Discontinued sections (Revenue/COGS/Expenses above
        # the Continuing-Operations PBT subtotal are that section's own
        # figures, never blended with a separate Discontinued-Operations
        # block further down) — Discontinued Operations and any exceptional
        # items are excluded entirely, never blended into the core metric.
        components = parsed.get("components") or {}
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        dep = parsed.get("depreciation")
        if ebe is None:
            out = {"applicable": False, "reason": "Could not find 'Employee Benefit Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if oe is None:
            out = {"applicable": False, "reason": "Could not find 'Other Expenses' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if dep is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Depreciation and Amortisation Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        total_assets = parsed.get("total_assets")
        total_current_liabilities = parsed.get("total_current_liabilities")
        if total_assets is None or total_current_liabilities is None:
            missing = "Total Assets" if total_assets is None else "Total Current Liabilities"
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        dep_cur, _dep_prior = dep
        ebit_cur = rev_cur - cogs_cur - ebe_cur - oe_cur - dep_cur

        ta_cur, ta_prior = total_assets
        tcl_cur, tcl_prior = total_current_liabilities
        ce_cur = ta_cur - tcl_cur
        ce_prior = (ta_prior - tcl_prior) if (ta_prior is not None and tcl_prior is not None) else None

        if ce_prior is not None:
            avg_ce = round((ce_cur + ce_prior) / 2, 2)
            den_label = "Average Capital Employed (opening + closing) ÷ 2"
            ce_by_year = {f"FY{fiscal_year}": round(ce_cur, 2), f"FY{fiscal_year - 1}": round(ce_prior, 2)}
            confidence, estimated = 1.0, False
        else:
            avg_ce = round(ce_cur, 2)
            den_label = "Closing Capital Employed (opening/prior-year unavailable)"
            ce_by_year = {f"FY{fiscal_year}": round(ce_cur, 2)}
            confidence, estimated = 0.8, True

        if avg_ce <= 0:
            out = {"applicable": False,
                   "reason": f"Average Capital Employed is {'negative' if avg_ce < 0 else 'zero'} "
                             f"(₹{avg_ce:,.2f} Cr) — the ratio would be meaningless, so it's flagged as N/A "
                             "rather than reported.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "EBIT (Revenue − COGS − Employee Costs − Other Expenses − D&A)", "value_cr": round(ebit_cur, 2)},
                   "denominator": {"label": den_label, "value_cr": avg_ce, "capital_employed_by_year": ce_by_year},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page"), bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        roce = round((ebit_cur / avg_ce) * 100, 2)

        out = {
            "applicable": True,
            "value": roce, "unit": "%",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "EBIT (Revenue − COGS − Employee Costs − Other Expenses − D&A)",
                "value_cr": round(ebit_cur, 2),
                "components": {
                    "Revenue from Operations": round(rev_cur, 2),
                    **{f"less: {k}": round(v[0], 2) for k, v in components.items()},
                    "less: Employee Benefit Expense": round(ebe_cur, 2),
                    "less: Other Expenses": round(oe_cur, 2),
                    "less: Depreciation and Amortisation Expense": round(dep_cur, 2),
                },
            },
            "denominator": {
                "label": den_label, "value_cr": avg_ce,
                "capital_employed_by_year": ce_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page"), bs_page=parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — Capital Employed = Total Assets − Total Current "
                     "Liabilities, both years read from the same statement."
                     if not estimated else
                     "From the company's own Annual Report. Prior-year (opening) Total Assets/Current Liabilities "
                     "was not disclosed, so Average Capital Employed uses the closing figure only — flagged as "
                     "an estimate."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def _compute_total_debt(parsed, lease_basis="basis1"):
    """Single shared source-of-truth assembly of Total Debt (Sr No 20),
    reused by every derived ratio (Debt-to-Equity, Debt Ratio, Enterprise
    Value) instead of each duplicating its own a+b+c logic — the drift
    between those duplicated copies (only Borrowings, no Notes fallback, no
    Finance-Costs cross-check) was the systemic under-capture this rebuild
    fixes (DMart/Maruti-style false-zeros).

    Total Debt = a + (b if lease_basis == "basis1") + c:
      a) Borrowings (Long-term + Short-term + Current Maturities), verified
         against the Notes-to-Accounts breakup (`borrowings_note_total_cur`):
           - face value ₹0/missing but Notes disclose real debt -> Notes
             total is used instead (flagged, reduced confidence) — this is
             the specific fix for a rigid single-line match silently
             reporting a debt-free company that Isn't.
           - both found but diverge >5% -> face value kept (Balance Sheet is
             authoritative) but flagged at reduced confidence.
      b) Lease Liabilities (Non-current + Current). Per the authoritative
         Sr No 33 (Net Debt/EBITDA) spec, Basis 1 (default) INCLUDES these in
         Total Debt — the post-Ind-AS-116 view; Basis 2 (opt-in
         `lease_basis="basis2"`) EXCLUDES them, for callers wanting the
         traditional pre-Ind-AS-116 definition. Always surfaced in
         `components` regardless of which basis is active.
      c) Other Financial Liabilities — only the sub-items passing the
         Three-Part Test (`_other_financial_liabilities_qualifying`) are
         added; never a guess when no sub-item breakup was printed.

    Hard Finance-Costs cross-check: if NEITHER Borrowings (face or Notes) nor
    any of the above signal any debt at all, but Finance Costs shows a real,
    non-trivial interest expense, that flatly contradicts "debt-free" — this
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

    # a) Borrowings — mandatory Notes verification, not face-value only.
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

    # b) Lease Liabilities — computed BEFORE the Finance-Costs cross-check
    # below, since Ind-AS-116 lease interest is itself a legitimate,
    # non-Borrowings source of Finance Costs (confirmed on HUL FY26: zero
    # Borrowings anywhere, but ₹1,478 Cr of Lease Liabilities plausibly
    # explains the ₹33 Cr Finance Costs on its own) — the cross-check must
    # not mistake lease interest for evidence of unparsed Borrowings.
    lease_nc = parsed.get("lease_liabilities_nc")
    lease_cur_bs = parsed.get("lease_liabilities_cur")
    lease_nc_cur = lease_nc[0] if lease_nc is not None else 0.0
    lease_cur_cur = lease_cur_bs[0] if lease_cur_bs is not None else 0.0
    b_cur = lease_nc_cur + lease_cur_cur
    include_leases = (lease_basis == "basis1")

    # Hard Finance-Costs cross-check — fires only when EVERY debt signal
    # (face Borrowings, Notes Borrowings, Lease Liabilities) came back
    # empty/zero, so a_cur is still 0 at this point, yet the company is
    # visibly paying real interest with no legitimate source for it.
    if a_cur == 0 and note_total is None and b_cur <= 0 and fc_cur is not None and fc_cur > 1.0:
        if borrowings_label_found:
            return {"applicable": False,
                    "reason": "A 'Borrowings' line is present on the Balance Sheet but its value could not be "
                              f"parsed, and Finance Costs of ₹{fc_cur:,.2f} Cr indicate real interest-bearing "
                              "debt exists — reporting Total Debt as ₹0 would be misleading, so this is flagged "
                              "as a likely extraction failure rather than a debt-free company."}
        return {"applicable": False,
                "reason": f"No Borrowings line was found on the Balance Sheet or in its Notes, but Finance Costs "
                          f"of ₹{fc_cur:,.2f} Cr indicate this company does carry interest-bearing debt — "
                          "reporting Total Debt as ₹0 would be misleading, so this is flagged rather than "
                          "silently reported as debt-free."}

    # c) Other Financial Liabilities — Three-Part Test qualifying sub-items only
    ofl_nc = parsed.get("other_fin_liab_nc")
    ofl_cur = parsed.get("other_fin_liab_cur")
    c_nc_cur = ofl_nc.get("qualifying_cur") if ofl_nc else None
    c_cur_cur = ofl_cur.get("qualifying_cur") if ofl_cur else None
    c_cur = (c_nc_cur or 0.0) + (c_cur_cur or 0.0)

    total_debt_cur = a_cur + (b_cur if include_leases else 0.0) + c_cur

    confidence = 1.0
    estimated = False
    if components_found < 3:
        confidence = min(confidence, 0.95)
    if a_source == "note_fallback":
        confidence = min(confidence, 0.9)
        estimated = True
    if note_mismatch:
        confidence = min(confidence, 0.85)
        estimated = True

    components_out = {
        "a) Borrowings (Long-term + Short-term + Current Maturities)": round(a_cur, 2),
        "b) Lease Liabilities": round(b_cur, 2),
        "b) Lease Liabilities included in Total Debt": include_leases,
        "c) Other Financial Liabilities (qualifying, Three-Part Test)": round(c_cur, 2),
    }
    if a_source == "note_fallback":
        components_out["a) Borrowings source"] = "Notes breakup (Balance Sheet face value was ₹0/missing)"
    if note_mismatch:
        components_out["a) Borrowings — face value"] = round(face_borrowings_cur, 2)
        components_out["a) Borrowings — Notes cross-check total"] = round(note_total, 2)

    note_parts = [f"Total Debt = a (Borrowings, cross-checked against the Notes breakup) + "
                  f"b (Lease Liabilities, {'included' if include_leases else 'excluded'} — "
                  f"{'Basis 1 (default)' if include_leases else 'Basis 2'}) + c (qualifying Other Financial "
                  "Liabilities, Three-Part Test)."]
    if a_source == "note_fallback":
        note_parts.append(f"Borrowings' Balance Sheet face value was ₹0/missing but its Notes breakup disclosed "
                           f"real debt (₹{note_total:,.2f} Cr across {note_subitems} sub-item(s)) — used instead "
                           "of silently reporting a false ₹0.")
    if note_mismatch:
        note_parts.append(f"Face value (₹{face_borrowings_cur:,.2f} Cr) and the Notes breakup "
                           f"(₹{note_total:,.2f} Cr) diverge by more than 5% — the face value is used (the "
                           "Balance Sheet is authoritative) but flagged at reduced confidence.")

    return {
        "applicable": True,
        "total_debt_cur": round(total_debt_cur, 2),
        "components": components_out,
        "confidence": confidence,
        "estimated": estimated,
        "lease_basis": lease_basis,
        "note": " ".join(note_parts),
    }


def fetch_debt_to_equity_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Debt-to-Equity = Total Debt ÷ Total Equity (owners-attributable), BOTH at
    CLOSING balance — unlike ROE/ROCE, this is point-in-time (like Current
    Ratio), never averaged.

    Total Debt is the shared a+b+c protocol assembled by `_compute_total_debt`
    (Sr No 20's own source-of-truth function) — see its docstring for the
    full Borrowings-Notes-verification / Lease-Liabilities-basis-toggle /
    Other-Financial-Liabilities-Three-Part-Test / Finance-Costs-cross-check
    details.

    Per spec, N/A if Total Equity is negative or zero (same rule as ROE) —
    never a spurious ratio. Reuses the SAME cached PDF extraction as ROE
    (Sr No 18) — no extra download — but, unlike ROE, uses the WHOLE-entity
    Total Equity (owners' + Non-Controlling Interest, `equity_full`), not
    the owners-only figure: Total Debt (the numerator) is the whole
    consolidated entity's debt, so the denominator must match that same
    scope, or leverage is overstated for any company with a material
    minority interest. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_de_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
        if not debt["applicable"]:
            out = {"applicable": False, "reason": debt["reason"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity = parsed.get("equity_full")
        if equity is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Total Equity'/'Shareholders' Funds' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        total_debt_cur = debt["total_debt_cur"]
        equity_cur, _equity_prior = equity
        equity_basis = parsed.get("equity_basis")
        nci_included = consolidated and (parsed.get("equity") != equity)

        if equity_cur <= 0:
            out = {"applicable": False,
                   "reason": f"Shareholders' Equity is {'negative' if equity_cur < 0 else 'zero'} "
                             f"(₹{equity_cur:,.2f} Cr) for this company — the ratio would be meaningless, so "
                             "it's flagged as N/A rather than reported, per spec.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Total Debt", "value_cr": total_debt_cur},
                   "denominator": {"label": "Total Equity", "value_cr": round(equity_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(total_debt_cur / equity_cur, 2)

        # Unlike ROE, NCI ambiguity isn't a confidence concern here — D/E
        # deliberately wants the whole-entity figure regardless of whether
        # NCI could be split out, so only Total Debt's own a+b+c confidence
        # applies.
        confidence = debt["confidence"]

        equity_label = "Total Equity (incl. Non-Controlling Interests)" if nci_included else "Total Equity"

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Total Debt (closing)",
                "value_cr": total_debt_cur,
                "components": debt["components"],
            },
            "denominator": {
                "label": f"{equity_label} (closing)",
                "value_cr": round(equity_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging. "
                    + debt["note"]
                    + (" Total Equity here is the WHOLE consolidated entity's equity (owners' + Non-Controlling "
                       "Interests), matching Total Debt's whole-entity scope — unlike ROE (Sr No 18), which uses "
                       "the owners-only portion." if nci_included else ""),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_debt_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Debt Ratio (Sr No 21) = Total Debt ÷ Total Assets, BOTH at CLOSING balance
    — a point-in-time ratio like Debt-to-Equity, never averaged.

    Total Debt is the SAME shared a+b+c protocol as Debt-to-Equity
    (`_compute_total_debt`, Sr No 20's own source-of-truth function) and Sr
    No 7's Total Assets field, but CLOSING ONLY — deliberately NOT the
    (opening+closing)/2 average Asset Turnover uses, since Debt Ratio must
    stay consistent with the point-in-time convention of Debt-to-Equity/
    Current Ratio. Built as its own function (not a client-side derivation of
    the D/E and Asset Turnover endpoints) because Debt-to-Equity's own N/A
    branches don't always carry a computed Total Debt figure (e.g. when
    Total Equity itself is missing, it returns before Total Debt is even
    summed) — reusing the SHARED extraction fields directly here keeps Debt
    Ratio correct independent of whatever Debt-to-Equity's own applicability
    outcome happens to be. Reuses the SAME cached PDF extraction — no extra
    download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_debtratio_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
        if not debt["applicable"]:
            out = {"applicable": False, "reason": debt["reason"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        total_assets = parsed.get("total_assets")
        if total_assets is None:
            out = {"applicable": False, "reason": "Could not find 'Total Assets' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        total_debt_cur = debt["total_debt_cur"]
        assets_cur, _assets_prior = total_assets
        if assets_cur <= 0:
            out = {"applicable": False, "reason": "Total Assets value is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(total_debt_cur / assets_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": debt["confidence"],
            "estimated": debt["confidence"] < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Total Debt (closing) — identical to Debt-to-Equity's numerator",
                "value_cr": total_debt_cur,
                "components": debt["components"],
            },
            "denominator": {
                "label": "Total Assets (closing balance, not averaged)",
                "value_cr": round(assets_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging "
                    "(unlike Asset Turnover's Average Total Assets). " + debt["note"],
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_interest_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Interest Coverage Ratio (Sr No 22) = EBIT ÷ Interest Expense (Finance
    Costs), current year only — no averaging (EBIT itself is never averaged,
    same as Sr No 19).

    EBIT here is the SAME Revenue − COGS − Employee Benefit Expense − Other
    Expenses − D&A computation already validated for Operating Profit
    Margin (Sr No 15) and ROCE (Sr No 19) — NOT "Profit Before Tax + Finance
    Costs". That PBT-based approximation was left unfixed when ROCE's own
    version of this same bug was fixed (commit "Fix Sr No 22 ROCE" — a
    historical numbering collision, that commit's "Sr No 22" was ROCE, not
    this ratio) because it wasn't yet QA-reviewed; it has the identical
    flaw: PBT implicitly bakes in Other Income (PBT = Total Income −
    Total Expenses = (Revenue + Other Income) − Total Expenses), so
    PBT + Finance Costs silently inflates "EBIT" by however much Other
    Income the company reports. QA's own cross-check formula for this ratio
    (PBT_beforeExceptional + Finance Costs − Other Income) reduces
    algebraically to exactly this Revenue-based formula. Using the
    Revenue-based computation directly (rather than PBT minus Other Income)
    also naturally satisfies QA's other two requirements without any new
    extraction: it reads Revenue/COGS/Expenses from the Continuing-
    Operations block only (never blended with a Discontinued-Operations
    section further down the statement), and it never includes Exceptional
    Items in the first place (those sit below this operating-profit line in
    the P&L, not inside COGS/Employee Costs/Other Expenses/D&A) — i.e. this
    is already QA's "EBIT excluding one-offs" by construction, with no
    separate "including one-offs" variant needed.

    Built as its OWN function (not a client-side derivation of the ROCE/OPM
    endpoints) for the same reason as Debt Ratio (Sr No 21): those ratios'
    own N/A branches don't always carry a computed EBIT (e.g. ROCE returns
    before EBIT is even used if Capital Employed can't be computed) —
    reusing the shared extraction fields directly keeps this ratio correct
    independent of ROCE/OPM's own applicability gates.

    Per spec, gross Finance Costs is used as the denominator as reported —
    never net off Interest Income. If Finance Costs is exactly nil (a
    genuinely debt-free/interest-free company), this is NOT a "could not
    compute" N/A — it's flagged as 'not_meaningful' with a distinct reason,
    since dividing by zero would either crash or fabricate an arbitrary
    "infinite" number, and per spec this must read as "Not Meaningful /
    Debt-Free" rather than either of those.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_intcov_v2_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        components = parsed.get("components") or {}
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        dep = parsed.get("depreciation")
        revenue = parsed.get("revenue")
        finance_costs = parsed.get("finance_costs")
        missing = ("Revenue from operations" if revenue is None else
                   "Employee Benefit Expense" if ebe is None else
                   "Other Expenses" if oe is None else
                   "Depreciation and Amortisation Expense" if dep is None else
                   "Finance Costs" if finance_costs is None else None)
        if missing:
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        dep_cur, _dep_prior = dep
        fc_cur, _fc_prior = finance_costs
        ebit_cur = rev_cur - cogs_cur - ebe_cur - oe_cur - dep_cur

        ebit_components = {
            "Revenue from Operations": round(rev_cur, 2),
            **{f"less: {k}": round(v[0], 2) for k, v in components.items()},
            "less: Employee Benefit Expense": round(ebe_cur, 2),
            "less: Other Expenses": round(oe_cur, 2),
            "less: Depreciation and Amortisation Expense": round(dep_cur, 2),
        }

        if abs(fc_cur) < 0.005:  # nil Finance Costs (rounds to ₹0.00 Cr) — genuinely debt-free/interest-free
            out = {"applicable": False, "not_meaningful": True,
                   "reason": "Not Meaningful — Interest Expense is nil (this company is debt-free or pays "
                             "no finance costs), so the ratio isn't defined rather than being computed as "
                             "an arbitrarily large or infinite number.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "EBIT (Revenue − COGS − Employee Costs − Other Expenses − D&A)",
                                 "value_cr": round(ebit_cur, 2), "components": ebit_components},
                   "denominator": {"label": "Interest Expense (Finance Costs)", "value_cr": round(fc_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(ebit_cur / fc_cur, 2)
        confidence = 1.0 if len(components) == len(_COGS_LABELS) else 0.95

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "EBIT (Revenue − COGS − Employee Costs − Other Expenses − D&A)",
                "value_cr": round(ebit_cur, 2),
                "components": ebit_components,
            },
            "denominator": {
                "label": "Interest Expense (Finance Costs, gross — not netted against Interest Income)",
                "value_cr": round(fc_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — EBIT is identical to Operating Profit Margin's "
                    "(Sr No 15) and Return on Capital Employed's (Sr No 19) numerator: Revenue from Operations "
                    "minus COGS, Employee Benefit Expense, Other Expenses and Depreciation & Amortisation — "
                    "scoped to Continuing Operations only, excludes Other Income and Exceptional Items. Finance "
                    "Costs used gross, as reported; Interest Income is never netted off.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_financial_leverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Financial Leverage Ratio (Sr No 23) = Average Total Assets ÷ Average
    Shareholders' Equity (owners-attributable) — the "leverage" leg of the
    DuPont ROE decomposition (ROE = Net Profit Margin × Asset Turnover ×
    Financial Leverage).

    Per spec, reuses Sr No 7's Average Total Assets and Sr No 18's Average
    Total Equity — SAME averaging convention as each ((opening+closing)/2
    when both years are disclosed, closing-only + confidence 0.8 otherwise).
    Built as its OWN function (not a client-side derivation of the Asset
    Turnover/ROE endpoints), same reasoning as Debt Ratio/Interest Coverage:
    Asset Turnover's own N/A branch fires on missing REVENUE (irrelevant to
    this ratio, which never touches Revenue) and ROE's own N/A branch fires
    on missing PAT (also irrelevant here) — neither endpoint's response can
    be trusted to expose Total Assets/Equity in every case this ratio
    actually needs them. Reuses the SAME cached PDF extraction — no extra
    download.

    Per spec, N/A if Average Shareholders' Equity is negative or zero — same
    restriction as Sr No 18 (a negative-equity denominator would produce a
    spurious ratio). Reuses the identical equity_cur/equity_prior
    positivity check as ROE for consistency. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_finlev_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        total_assets = parsed.get("total_assets")
        if total_assets is None:
            out = {"applicable": False, "reason": "Could not find 'Total Assets' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity = parsed.get("equity")
        if equity is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Total Equity'/'Shareholders' Funds' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        assets_cur, assets_prior = total_assets
        equity_cur, equity_prior = equity
        equity_basis = parsed.get("equity_basis")

        # Same rule as ROE (Sr No 18): never calculate through a
        # negative/zero equity base, in either year.
        if equity_cur <= 0 or (equity_prior is not None and equity_prior <= 0):
            out = {"applicable": False,
                   "reason": "Shareholders' Equity is negative (or zero) for this company — Financial Leverage "
                             "would be meaningless, so it's flagged as N/A rather than reported, per spec.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Total Assets", "value_cr": round(assets_cur, 2)},
                   "denominator": {"label": "Total Equity", "value_cr": round(equity_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        assets_averaged = assets_prior is not None and assets_prior > 0
        if assets_averaged:
            avg_assets = round((assets_cur + assets_prior) / 2, 2)
            assets_label = "Average Total Assets (opening + closing) ÷ 2"
            assets_by_year = {f"FY{fiscal_year}": round(assets_cur, 2), f"FY{fiscal_year - 1}": round(assets_prior, 2)}
        else:
            avg_assets = round(assets_cur, 2)
            assets_label = "Closing Total Assets (opening/prior-year unavailable)"
            assets_by_year = {f"FY{fiscal_year}": round(assets_cur, 2)}

        equity_averaged = equity_prior is not None and equity_prior > 0
        if equity_averaged:
            avg_equity = round((equity_cur + equity_prior) / 2, 2)
            equity_label = "Average Total Equity (opening + closing) ÷ 2"
            equity_by_year = {f"FY{fiscal_year}": round(equity_cur, 2), f"FY{fiscal_year - 1}": round(equity_prior, 2)}
        else:
            avg_equity = round(equity_cur, 2)
            equity_label = "Closing Total Equity (opening/prior-year unavailable)"
            equity_by_year = {f"FY{fiscal_year}": round(equity_cur, 2)}

        ratio = round(avg_assets / avg_equity, 2)

        # Confidence takes the more cautious of two independent concerns —
        # same pattern as ROE: NCI ambiguity on the equity side, and whichever
        # of the two averages fell back to closing-only.
        ambiguous_nci = consolidated and equity_basis != "owners"
        confidence = 1.0
        if ambiguous_nci:
            confidence = min(confidence, 0.8)
        if not assets_averaged or not equity_averaged:
            confidence = min(confidence, 0.8)

        equity_label_full = ("Average Total Equity Attributable to Owners of the Company"
                              if equity_basis == "owners" and equity_averaged
                              else "Closing Total Equity Attributable to Owners of the Company"
                              if equity_basis == "owners" else equity_label)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": assets_label,
                "value_cr": avg_assets,
                "total_assets_by_year": assets_by_year,
            },
            "denominator": {
                "label": equity_label_full,
                "value_cr": avg_equity,
                "equity_by_year": equity_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — the 'leverage' leg of the DuPont ROE decomposition "
                    "(ROE ≈ Net Profit Margin × Asset Turnover × Financial Leverage). Identical Average Total "
                    "Assets and Average Total Equity fields as Asset Turnover (Sr No 7) and Return on Equity "
                    "(Sr No 18)."
                    + ("" if equity_basis == "owners" else
                       " This filing did not print a separate owners-vs-Non-Controlling-Interest equity split, "
                       "so 'Total Equity' is used as-is."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_eps_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Basic Earnings per Share (Sr No 24 denominator) — as reported on the P&L
    page under "Earnings per equity share", current year only (EPS is
    already a per-share figure, never averaged). This reader deliberately
    reads ONLY Basic EPS, not Diluted, per spec's "state explicitly whether
    Basic or Diluted is used" — Basic is what's used everywhere else this
    figure could be cross-checked against (Screener, exchange filings).

    Kept as its OWN function (not folded into the PBT/PAT extraction
    functions) since P/E Ratio (Sr No 24) is the first ratio whose numerator
    is MARKET data (a live price), not a statement figure — EPS is the only
    half of that ratio sourced from the Annual Report, so it needs its own
    endpoint the frontend can pair with a live-quote fetch.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_eps_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        eps = parsed.get("eps")
        if eps is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Basic Earnings per Share' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        eps_cur, _eps_prior = eps

        out = {
            "applicable": True,
            "value": round(eps_cur, 2), "unit": "₹",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Basic Earnings per Share", "value_cr": round(eps_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — Basic EPS as reported under 'Earnings per equity "
                    "share'; Diluted EPS is not used here, per spec.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_book_value_per_share_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Book Value per Share (Sr No 25 denominator) = Total Equity (owners-
    attributable, excl. Non-Controlling Interest, reuses Sr No 18's `equity`
    field) ÷ Number of Equity Shares Outstanding — BOTH CLOSING balance
    (never averaged/weighted-average), per spec's "use the closing balance
    and the closing share count for consistency with the market price date."

    Kept as its OWN function (not folded into ROE's extraction) for the same
    reason as every other Sr-No-X-reuse ratio in this suite: ROE's own N/A
    branch fires on missing PAT, which is irrelevant to Book Value per
    Share — it never touches PAT at all. Like EPS (Sr No 24), this is the
    Annual-Report half of a market-data ratio (Price-to-Book); the frontend
    pairs it with a live quote, same architecture as P/E.

    Per spec, N/A if Book Value per Share ≤ 0 (negative equity) — same
    restriction as ROE/Financial Leverage. Reuses the SAME cached PDF
    extraction — no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_bvps_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        equity = parsed.get("equity")
        if equity is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Total Equity'/'Shareholders' Funds' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        shares = parsed.get("shares_outstanding")
        if shares is None:
            out = {"applicable": False,
                   "reason": "Could not find the 'Issued, Subscribed and Fully Paid' equity share count in the "
                             "Equity Share Capital note.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity_cur, _equity_prior = equity
        shares_cur, _shares_prior = shares
        equity_basis = parsed.get("equity_basis")

        if equity_cur <= 0:
            out = {"applicable": False,
                   "reason": "Shareholders' Equity is negative (or zero) for this company — Book Value per "
                             "Share would be meaningless, so it's flagged as N/A rather than reported, per spec.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Total Equity (closing)", "value_cr": round(equity_cur, 2)},
                   "denominator": {"label": "Equity Shares Outstanding (closing)", "value_cr": shares_cur},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        # equity_cur is in ₹ Crore; shares_cur is a raw share count — convert
        # Crore to ₹ (×1e7) before dividing to get a per-share ₹ figure.
        bvps = round((equity_cur * 1e7) / shares_cur, 2)

        confidence = 0.8 if (consolidated and equity_basis != "owners") else 1.0
        equity_label = ("Total Equity Attributable to Owners of the Company (closing)"
                         if equity_basis == "owners" else "Total Equity (closing)")

        out = {
            "applicable": True,
            "value": bvps, "unit": "₹",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": equity_label, "value_cr": round(equity_cur, 2)},
            "denominator": {"label": "Equity Shares Outstanding (closing)", "value_cr": shares_cur},
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Total Equity ÷ closing Issued/Subscribed/"
                    "Fully-Paid equity share count (from the Equity Share Capital note), consistent with the "
                    "market price's point-in-time basis."
                    + ("" if equity_basis == "owners" else
                       " This filing did not print a separate owners-vs-Non-Controlling-Interest equity split, "
                       "so 'Total Equity' is used as-is."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_shares_outstanding_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Equity Shares Outstanding — the share-count half of Market
    Capitalisation (Sr No 26 numerator = Market Price × this, paired with a
    LIVE market price). Conceptually this wants the CURRENT share count (as
    of today, to match the live price date), whereas Book Value per Share
    (Sr No 25) wants the BALANCE-SHEET-DATE share count (to match the
    closing Total Equity it divides). This PDF-only reader has no live
    registrar feed, so both currently reuse the SAME `shares_outstanding`
    field (the Annual Report's own closing/reconciled count, from
    `_find_shares_outstanding`'s 3-priority fallback) — the closest available
    proxy for "current" absent a post-fiscal-year-end share count. Kept as
    its own field/function (not literally the same value by coincidence)
    specifically so a future live-count source can override THIS one without
    touching BVPS's balance-sheet-date figure.

    Kept as its OWN function (not a client-side reuse of the Book Value per
    Share endpoint) since BVPS's own N/A branch fires when Total Equity is
    negative — completely irrelevant to the share COUNT, which is available
    regardless of whether equity is positive or negative. Market Cap must
    stay computable even for a negative-equity company. Reuses the SAME
    cached PDF extraction — no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_sharesout_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        shares = parsed.get("shares_outstanding")
        if shares is None:
            out = {"applicable": False,
                   "reason": "Could not find the 'Issued, Subscribed and Fully Paid' equity share count in the "
                             "Equity Share Capital note.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        shares_cur, _shares_prior = shares

        out = {
            "applicable": True,
            "value": shares_cur, "unit": "shares",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Equity Shares Outstanding (closing)", "value_cr": shares_cur},
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Issued/Subscribed/Fully-Paid equity share "
                    "count, from the Equity Share Capital note.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_revenue_from_operations_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Revenue from Operations (Sr No 26 denominator) — current year only, no
    averaging. Reuses Sr No 3's (Receivables Turnover) `revenue` field.

    Kept as its OWN function (not a client-side reuse of the Receivables
    Turnover endpoint) since that ratio's own N/A branch fires on missing
    Trade Receivables — irrelevant to Price-to-Sales, which never touches
    receivables at all. Reuses the SAME cached PDF extraction — no extra
    download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_revenue_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        out = {
            "applicable": True,
            "value": round(rev_cur, 2), "unit": "₹ Cr",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Revenue from Operations", "value_cr": round(rev_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — Revenue from Operations, current year only "
                    "(never Total Income, which would include Other Income).",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_dividend_per_share_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Total Dividend per Equity Share DECLARED during the year (Sr No 27
    numerator) — the "During the year, a dividend of ₹X per share... was
    paid" sentence in the Retained Earnings movement note. ALWAYS standalone
    (see `_find_dividend_per_share`'s docstring) — the `consolidated`
    parameter here only picks which PDF-parse cache entry is reused (the
    extraction itself always tracks toward the standalone section
    regardless), kept for a consistent function signature with every other
    `fetch_X_from_annual_report` in this file.

    Per spec, "no dividend declared" is a real 0% — NOT missing data. When
    the extractor found no matching sentence at all, this still returns
    applicable=True with value=0.0, but at REDUCED confidence (0.4) since a
    genuinely zero-dividend company is indistinguishable from an extraction
    miss without a stronger positive signal.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_dps_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        dps = parsed.get("dividend_per_share") or 0.0
        found = parsed.get("dividend_per_share_found", False)
        screener_fallback_used = False

        # Fallback, only when the Annual Report genuinely found NO dividend
        # sentence/note at all (found=False — indistinguishable, from PDF
        # text alone, between "no dividend this year" and "extraction
        # gap"): try Screener.in's own Dividend Yield x its own last price
        # as an independent secondary source, rather than silently
        # defaulting to a possibly-wrong ₹0. Screener's Dividend Yield uses
        # ITS OWN convention (typically trailing/most-recently-declared,
        # not necessarily this filing's own "paid in cash during the
        # fiscal year" basis) — so this is clearly labelled as a
        # different-methodology fallback, not presented as equal-confidence
        # to a confirmed Annual Report figure.
        if not found:
            try:
                from tools.screener_scraper import fetch_screener_financials
                sc = fetch_screener_financials(sym, name) or {}
                info = sc.get("info") or {}
                sc_yield = info.get("dividendYield")
                sc_price = info.get("currentPrice") or info.get("regularMarketPrice") or sc.get("lastPrice")
                if sc_yield and sc_price:
                    implied_dps = round(sc_yield * sc_price, 2)
                    if implied_dps > 0:
                        dps = implied_dps
                        screener_fallback_used = True
            except Exception as e:
                print(f"[annual_report_financials] Screener DPS fallback skipped for {sym}: {e}")

        confidence = 1.0 if found else (0.6 if screener_fallback_used else 0.4)
        out = {
            "applicable": True,
            "value": round(dps, 2), "unit": "₹",
            "confidence": confidence,
            "estimated": not found,
            "period": f"FY{str(fiscal_year)[-2:]} (standalone — dividends are always declared by the parent "
                      f"entity, not on a consolidated basis)",
            "numerator": {"label": "Dividend per Equity Share (declared, standalone)", "value_cr": round(dps, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": ("From the company's own Annual Report — the dividend actually declared and paid in cash "
                      "during the year (never a merely recommended/board-proposed dividend still awaiting "
                      "shareholder approval, which Ind AS doesn't recognise as a liability until then)."
                      if found else
                      "Could not find an explicit 'dividend per share paid during the year' disclosure in the "
                      "Annual Report. " + (
                          "Estimated instead from Screener.in's own Dividend Yield x last traded price — a "
                          "DIFFERENT convention (typically the most recently declared dividend, not necessarily "
                          "this filing's own 'paid in cash during the fiscal year' basis), shown at reduced "
                          "confidence and flagged as a fallback, not a confirmed Annual Report figure."
                          if screener_fallback_used else
                          "Defaulted to ₹0 (no dividend) at reduced confidence, since this could genuinely be a "
                          "zero-dividend year or an extraction gap; per spec, 'no dividend declared' is treated "
                          "as a real 0%, not missing data."
                      )),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_ebitda_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    EBITDA (Sr No 29 denominator) = Revenue − COGS − Employee Benefit
    Expense − Other Expenses, current year only — deliberately excludes
    Depreciation & Amortisation (that's the whole point of EBITDA). Operating
    Profit Margin (Sr No 15) used to share this exact formula, but per spec
    Sr No 15 is now EBIT-basis (also deducts D&A) — this function was NOT
    updated to match, since EBITDA must stay EBITDA regardless of what Sr No
    15 does. Kept as its own small function (mirroring internals rather than
    reusing OPM's endpoint) so Enterprise Value/EBITDA stays computable
    independent of OPM's own response shape/labeling/definition changes (same
    "own small function" reasoning as every Sr-No-X-reuse ratio since 21).
    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_ebitda_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        components = parsed.get("components") or {}
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        if ebe is None:
            out = {"applicable": False, "reason": "Could not find 'Employee Benefit Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if oe is None:
            out = {"applicable": False, "reason": "Could not find 'Other Expenses' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        ebitda = rev_cur - cogs_cur - ebe_cur - oe_cur
        confidence = 1.0 if len(components) == len(_COGS_LABELS) else 0.95

        out = {
            "applicable": True,
            "value": round(ebitda, 2), "unit": "₹ Cr",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "EBITDA (Revenue − COGS − Employee Costs − Other Expenses)",
                "value_cr": round(ebitda, 2),
                "components": {
                    "Revenue from Operations": round(rev_cur, 2),
                    **{f"less: {k}": round(v[0], 2) for k, v in components.items()},
                    "less: Employee Benefit Expense": round(ebe_cur, 2),
                    "less: Other Expenses": round(oe_cur, 2),
                },
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — identical formula to Operating Profit Margin's "
                    "numerator (Sr No 15): excludes Depreciation, Finance Costs, Other Income and Exceptional "
                    "Items.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_total_debt_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Total Debt (closing) — the SAME shared a+b+c protocol as Debt-to-Equity/
    Debt Ratio (`_compute_total_debt`, Sr No 20's own source-of-truth
    function). Built as its own function since both of those ratios' own
    N/A branches fire on concerns (missing Equity/Total Assets) irrelevant to
    Enterprise Value, which needs Total Debt regardless. Reuses the SAME
    cached PDF extraction — no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_totaldebt_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
        if not debt["applicable"]:
            out = {"applicable": False, "reason": debt["reason"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        out = {
            "applicable": True,
            "value": debt["total_debt_cur"], "unit": "₹ Cr",
            "confidence": debt["confidence"],
            "estimated": debt["confidence"] < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Total Debt (closing)",
                "value_cr": debt["total_debt_cur"],
                "components": debt["components"],
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotal, identical "
                    "components to Debt-to-Equity/Debt Ratio's numerator. " + debt["note"],
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_cash_and_equivalents_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Cash and Cash Equivalents (closing) — the SAME field as Cash Ratio's
    numerator (Sr No 12), reusing `_find_cash_row`'s restricted-cash-aware
    extraction (never "Other Bank Balances", never unpaid/unclaimed dividend
    accounts). Built as its own function since Cash Ratio's own N/A branch
    fires on missing Total Current Liabilities — irrelevant to Enterprise
    Value, which needs Cash regardless. Reuses the SAME cached PDF
    extraction — no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_cashonly_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        cash = parsed.get("cash")
        if cash is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Cash and Cash Equivalents' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cash_cur, _cash_prior = cash

        out = {
            "applicable": True,
            "value": round(cash_cur, 2), "unit": "₹ Cr",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Cash and Cash Equivalents (closing)", "value_cr": round(cash_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — Cash and Cash Equivalents only, identical field "
                    "to Cash Ratio's numerator (never 'Other Bank Balances' or restricted/earmarked balances).",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_receivables_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Receivables Turnover = Revenue from Operations ÷ Average Trade Receivables
    (Net Credit Sales is used via the Revenue-from-Operations proxy per spec,
    since Indian Annual Reports don't split cash vs. credit sales). Reuses the
    SAME cached PDF extraction as Inventory Turnover (`_get_extracted_financials`)
    — no extra download. Returns a dict shaped like the Inventory Turnover
    output, or {'applicable': False, 'reason': ...}. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_recvturn_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        receivables = parsed.get("receivables")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if receivables is None:
            out = {"applicable": False, "reason": "Could not find 'Trade receivables' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        recv_cur, recv_prior = receivables
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if recv_cur <= 0:
            out = {"applicable": False, "reason": "Trade receivables value is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        # Confidence is capped at 0.8 REGARDLESS of denominator quality: per
        # spec, "0.8 = estimated using a proxy/approximation (e.g. no
        # credit-sales split)" — and the numerator here is ALWAYS that proxy
        # (Revenue from Operations standing in for Net Credit Sales, since
        # Indian filings never disclose the cash/credit split). It only drops
        # further, to 0.4, when the denominator is ALSO incomplete (no
        # prior-year receivables) — two compounding approximations.
        if recv_prior and recv_prior > 0:
            avg_recv = round((recv_cur + recv_prior) / 2, 2)
            den_label = "Average Trade Receivables (opening + closing) ÷ 2"
            recv_by_year = {f"FY{fiscal_year}": round(recv_cur, 2), f"FY{fiscal_year - 1}": round(recv_prior, 2)}
            confidence = 0.8
        else:
            avg_recv = round(recv_cur, 2)
            den_label = "Closing Trade Receivables (opening/prior-year unavailable)"
            recv_by_year = {f"FY{fiscal_year}": round(recv_cur, 2)}
            confidence = 0.4
        estimated = True  # numerator is always the Revenue proxy, never actual Net Credit Sales

        ratio = round(rev_cur / avg_recv, 2) if avg_recv else None

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "denominator": {
                "label": den_label, "value_cr": avg_recv,
                "receivables_by_year": recv_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report. Revenue from Operations is used as a proxy for Net "
                     "Credit Sales — Indian Annual Reports don't disclose the cash/credit sales split, so an "
                     "exact figure isn't available for any company (confidence capped at 0.8 for this reason)."
                     + (" Prior-year (opening) Trade Receivables was also not disclosed, so Average Trade "
                        "Receivables uses the closing figure only, further lowering confidence to 0.4."
                        if confidence <= 0.4 else "")),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_payables_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Payables Turnover = Purchases ÷ Average Trade Payables. Purchases = (a)
    Cost of materials consumed + (b) Purchases of stock-in-trade — the a+b
    subset of Sr No 1's COGS components, deliberately EXCLUDING (c) Changes
    in Inventories (not a purchase). Falls back to
    COGS(a+b+c) - (Opening Inventories - Closing Inventories) only if a+b
    itself isn't available (per spec's fallback rule) — this fallback is
    itself an approximation, so it caps confidence the same way Receivables
    Turnover's Revenue-proxy numerator does. Reuses the SAME cached PDF
    extraction as Inventory/Receivables Turnover (`_get_extracted_financials`)
    — no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_payturn_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        components = parsed.get("components") or {}
        payables = parsed.get("payables")
        if payables is None:
            out = {"applicable": False, "reason": "Could not find 'Trade payables' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cogs_a = components.get("Cost of materials consumed")
        cogs_b = components.get("Purchases of stock-in-trade")
        purchases_fallback = False
        both_ab_present = cogs_a is not None and cogs_b is not None
        if cogs_a is not None or cogs_b is not None:
            # Per spec, Purchases = a + b — but a pure trading/retail business
            # (e.g. a supermarket chain) legitimately reports ONLY (b)
            # Purchases of stock-in-trade, with NO "Cost of materials
            # consumed" line at all, because it doesn't manufacture anything.
            # That's a real ₹0 for (a), not missing data, so summing whichever
            # of a/b IS present (rather than requiring both) is correct — only
            # the fallback path below is needed when NEITHER is disclosed.
            a_val = cogs_a[0] if cogs_a is not None else 0.0
            b_val = cogs_b[0] if cogs_b is not None else 0.0
            purchases_cur = a_val + b_val
            if both_ab_present:
                num_label = "Purchases (a: Cost of materials consumed + b: Purchases of stock-in-trade)"
            elif cogs_b is not None:
                num_label = "Purchases (b: Purchases of stock-in-trade — a pure trading business, no Cost of materials consumed)"
            else:
                num_label = "Purchases (a: Cost of materials consumed — no Purchases of stock-in-trade disclosed)"
        else:
            # Fallback: COGS(a+b+c) - (Opening Inventories - Closing Inventories)
            inv = parsed.get("inventory")
            if len(components) == 0 or inv is None:
                out = {"applicable": False,
                       "reason": "Neither Purchases (a+b) nor the COGS/Inventory fallback data was fully available.",
                       "source_url": pdf_url}
                _write_cache(ckey, out)
                return out
            cogs_total = sum(v[0] for v in components.values())
            inv_cur, inv_prior = inv
            purchases_cur = cogs_total - (inv_prior - inv_cur)
            purchases_fallback = True
            num_label = "Purchases (fallback: COGS − (Opening Inventories − Closing Inventories))"

        pay_cur, pay_prior = payables
        if purchases_cur <= 0:
            out = {"applicable": False, "reason": "Purchases is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if pay_cur <= 0:
            out = {"applicable": False, "reason": "Trade payables value is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        if pay_prior and pay_prior > 0:
            avg_pay = round((pay_cur + pay_prior) / 2, 2)
            den_label = "Average Trade Payables (opening + closing) ÷ 2"
            pay_by_year = {f"FY{fiscal_year}": round(pay_cur, 2), f"FY{fiscal_year - 1}": round(pay_prior, 2)}
            den_complete = True
        else:
            avg_pay = round(pay_cur, 2)
            den_label = "Closing Trade Payables (opening/prior-year unavailable)"
            pay_by_year = {f"FY{fiscal_year}": round(pay_cur, 2)}
            den_complete = False

        # Confidence: numerator from a+b (2 disclosed line items) + complete
        # denominator = 1.0, consistent with how Inventory Turnover treats its
        # own a+b+c numerator. The fallback numerator is itself an
        # approximation (per spec), so it caps confidence at 0.8 regardless of
        # denominator quality — same treatment as Receivables Turnover's
        # Revenue-proxy numerator; an incomplete denominator on top of that
        # fallback drops it further to 0.4.
        if purchases_fallback:
            confidence = 0.8 if den_complete else 0.4
        else:
            confidence = 1.0 if den_complete else 0.8
            # A single-component Purchases figure (only a OR b disclosed, not
            # both) is "1 clearly-disclosed line item" rather than the full
            # a+b split — cap at 0.95 regardless of denominator quality, same
            # tier Gross/Operating Profit Margin use for a partial COGS.
            if not both_ab_present:
                confidence = min(confidence, 0.95)
        estimated = purchases_fallback or not den_complete

        ratio = round(purchases_cur / avg_pay, 2) if avg_pay else None

        note_parts = []
        if purchases_fallback:
            note_parts.append("A direct Purchases split (a+b) wasn't available, so Purchases was derived from "
                               "COGS minus the inventory movement — an approximation per the spec's fallback rule.")
        if not den_complete:
            note_parts.append("Prior-year (opening) Trade Payables wasn't disclosed, so Average Trade Payables "
                               "uses the closing figure only.")
        note = ("From the company's own Annual Report — both years read from the same statement. "
                + " ".join(note_parts)) if note_parts else \
               ("From the company's own Annual Report — both years read from the same statement, so the "
                "prior-year comparator is always on a consistent (restated) basis.")

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": num_label,
                "value_cr": round(purchases_cur, 2),
            },
            "denominator": {
                "label": den_label, "value_cr": avg_pay,
                "payables_by_year": pay_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": note,
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_asset_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Asset Turnover = Revenue from Operations ÷ Average Total Assets. Reuses
    the SAME cached PDF extraction as Inventory/Receivables/Payables Turnover
    (`_get_extracted_financials`) — no extra download. Returns a dict shaped
    like the other turnover ratios' output, or {'applicable': False, ...}.
    Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_assetturn_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        total_assets = parsed.get("total_assets")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if total_assets is None:
            out = {"applicable": False, "reason": "Could not find 'Total Assets' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        assets_cur, assets_prior = total_assets
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if assets_cur <= 0:
            out = {"applicable": False, "reason": "Total Assets value is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        # Denominator per spec: (Opening + Closing) / 2 when both are present
        # (confidence 1.0); else Closing only, flagged Estimated (confidence 0.8).
        if assets_prior and assets_prior > 0:
            avg_assets = round((assets_cur + assets_prior) / 2, 2)
            den_label = "Average Total Assets (opening + closing) ÷ 2"
            assets_by_year = {f"FY{fiscal_year}": round(assets_cur, 2), f"FY{fiscal_year - 1}": round(assets_prior, 2)}
            confidence, estimated = 1.0, False
        else:
            avg_assets = round(assets_cur, 2)
            den_label = "Closing Total Assets (opening/prior-year unavailable)"
            assets_by_year = {f"FY{fiscal_year}": round(assets_cur, 2)}
            confidence, estimated = 0.8, True

        ratio = round(rev_cur / avg_assets, 2) if avg_assets else None

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "denominator": {
                "label": den_label, "value_cr": avg_assets,
                "total_assets_by_year": assets_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — both years read from the same statement, "
                     "so the prior-year comparator is always on a consistent (restated) basis."
                     if not estimated else
                     "From the company's own Annual Report. Prior-year (opening) Total Assets was not "
                     "disclosed, so Average Total Assets uses the closing figure only — flagged as an estimate."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_fixed_asset_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Fixed Asset Turnover (Sr No 30) = Revenue from Operations ÷ Average Net
    Fixed Assets. Reuses the SAME cached PDF extraction as the other
    turnover ratios (`_get_extracted_financials`) — no extra download.
    Returns a dict shaped like `fetch_asset_turnover_from_annual_report`, or
    {'applicable': False, ...}. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_fixedassetturn_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        net_fixed_assets = parsed.get("net_fixed_assets")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if net_fixed_assets is None:
            out = {"applicable": False, "reason": "Could not find 'Property, Plant and Equipment (net)' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        nfa_cur, nfa_prior = net_fixed_assets
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if nfa_cur <= 0:
            out = {"applicable": False, "reason": "Net Fixed Assets value is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        # Denominator per spec: (Opening + Closing) / 2 when both are present
        # (confidence 1.0); else Closing only, flagged Estimated (confidence 0.8).
        if nfa_prior and nfa_prior > 0:
            avg_nfa = round((nfa_cur + nfa_prior) / 2, 2)
            den_label = "Average Net Fixed Assets (opening + closing) ÷ 2"
            nfa_by_year = {f"FY{fiscal_year}": round(nfa_cur, 2), f"FY{fiscal_year - 1}": round(nfa_prior, 2)}
            confidence, estimated = 1.0, False
        else:
            avg_nfa = round(nfa_cur, 2)
            den_label = "Closing Net Fixed Assets (opening/prior-year unavailable)"
            nfa_by_year = {f"FY{fiscal_year}": round(nfa_cur, 2)}
            confidence, estimated = 0.8, True

        ratio = round(rev_cur / avg_nfa, 2) if avg_nfa else None

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "denominator": {
                "label": den_label, "value_cr": avg_nfa,
                "net_fixed_assets_by_year": nfa_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — both years read from the same statement, "
                     "so the prior-year comparator is always on a consistent (restated) basis."
                     if not estimated else
                     "From the company's own Annual Report. Prior-year (opening) Net Fixed Assets was not "
                     "disclosed, so Average Net Fixed Assets uses the closing figure only — flagged as an estimate."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_current_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Current Ratio = Total Current Assets ÷ Total Current Liabilities — a
    point-in-time (closing balance) ratio, unlike the turnover ratios above:
    per spec, use the CLOSING figure only, never an average. Reuses the SAME
    cached PDF extraction (`_get_extracted_financials`) — no extra download.
    Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_currentratio_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        tca = parsed.get("total_current_assets")
        tcl = parsed.get("total_current_liabilities")
        if tca is None or tcl is None:
            missing = "Total Current Assets" if tca is None else "Total Current Liabilities"
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tca_cur, _tca_prior = tca
        tcl_cur, _tcl_prior = tcl

        if tcl_cur == 0:
            out = {"applicable": False, "reason": "Total Current Liabilities is zero — ratio would be undefined.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Total Current Assets", "value_cr": round(tca_cur, 2)},
                   "denominator": {"label": "Total Current Liabilities", "value_cr": round(tcl_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(tca_cur / tcl_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Total Current Assets (closing)",
                "value_cr": round(tca_cur, 2),
            },
            "denominator": {
                "label": "Total Current Liabilities (closing)",
                "value_cr": round(tcl_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_quick_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Quick Ratio = (Total Current Assets − Inventories) ÷ Total Current
    Liabilities — closing balance only, per spec same as Current Ratio (Sr No
    10): no averaging. Numerator reuses Sr No 10's Total Current Assets minus
    Sr No 1's Inventory figure — does NOT exclude Trade Receivables (that
    would be the Cash Ratio, a different ratio). Reuses the SAME cached PDF
    extraction — no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_quickratio_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        tca = parsed.get("total_current_assets")
        tcl = parsed.get("total_current_liabilities")
        inv = parsed.get("inventory")
        if tca is None or tcl is None:
            missing = "Total Current Assets" if tca is None else "Total Current Liabilities"
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        # A no-inventory business (services/IT — e.g. AAKASH, oil-exploration
        # services) legitimately has NO Inventories line on its Balance Sheet
        # at all — that's a real ₹0, not missing data. Per the suite-wide
        # "sum what's there, only reject when genuinely absent" principle, a
        # missing Inventories row here means inventory = 0, so Quick Ratio
        # correctly collapses to Current Ratio (nothing to subtract) rather
        # than N/A. (Contrast: TCA/TCL missing IS a real gap, handled above.)
        inv_missing = inv is None
        inv_cur = 0.0 if inv_missing else inv[0]

        tca_cur, _tca_prior = tca
        tcl_cur, _tcl_prior = tcl

        if tcl_cur == 0:
            out = {"applicable": False, "reason": "Total Current Liabilities is zero — ratio would be undefined.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Total Current Assets − Inventories",
                                 "value_cr": round(tca_cur - inv_cur, 2)},
                   "denominator": {"label": "Total Current Liabilities", "value_cr": round(tcl_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        quick_assets = tca_cur - inv_cur
        ratio = round(quick_assets / tcl_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Total Current Assets − Inventories (closing)",
                "value_cr": round(quick_assets, 2),
                "components": {
                    "Total Current Assets": round(tca_cur, 2),
                    "less: Inventories": round(inv_cur, 2),
                },
            },
            "denominator": {
                "label": "Total Current Liabilities (closing)",
                "value_cr": round(tcl_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging. "
                    "Excludes Inventory only (not Trade Receivables).",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_cash_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Cash Ratio = Cash and Cash Equivalents ÷ Total Current Liabilities —
    closing balance only, same point-in-time nature as Current/Quick Ratio
    (Sr No 10/11). The most conservative liquidity measure: ignores
    receivables AND inventory entirely.

    Per spec, "Other Bank Balances" (fixed deposits with banks, margin money,
    unpaid dividend accounts, escrow balances — a Balance Sheet line SEPARATE
    from Cash and Cash Equivalents) may ALSO belong in the numerator, but only
    its unrestricted portion — the restricted/earmarked portion must stay
    excluded. The split is rebuilt as a deterministic Base -> Net-off ->
    Optional-Add pipeline (`_other_bank_balances_unrestricted`) instead of
    leaving the restricted/unrestricted call to AI judgement:
      Base       = the Other Bank Balances line's own total.
      Net-off    = sub-item lines printed directly under it that match an
                   explicit restricted-label test (unpaid dividend, margin
                   money, escrow, pledged/lien, security deposits, bank
                   guarantees).
      Optional-Add = Base minus Net-off, added into the Cash Ratio numerator
                   — but ONLY when that label test actually matched a real
                   sub-item breakup. If no breakup is printed at all, there's
                   nothing to run the test against, so nothing is guessed:
                   the figure stays informational-only (`other_bank_balances_cr`)
                   and is NOT folded into the numerator. Same treatment for
                   Current Investments: only included if explicitly disclosed
                   as liquid/unrestricted, which this reader also can't
                   verify, so they're excluded from the numerator too.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_cashratio_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        cash = parsed.get("cash")
        tcl = parsed.get("total_current_liabilities")
        if cash is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Cash and Cash Equivalents' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if tcl is None:
            out = {"applicable": False, "reason": "Could not find 'Total Current Liabilities' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cash_cur, _cash_prior = cash
        tcl_cur, _tcl_prior = tcl
        obb = parsed.get("other_bank_balances")
        obb_cur = round(obb[0], 2) if obb is not None else None
        obb_breakup = parsed.get("other_bank_balances_breakup")
        obb_unrestricted_cur = obb_breakup.get("unrestricted_cur") if obb_breakup else None

        # Optional-Add: fold the deterministically-classified unrestricted
        # portion of Other Bank Balances into the numerator, only when found.
        numerator_cur = cash_cur + obb_unrestricted_cur if obb_unrestricted_cur is not None else cash_cur
        numerator_label = ("Cash and Cash Equivalents + Unrestricted Other Bank Balances (closing)"
                            if obb_unrestricted_cur is not None else "Cash and Cash Equivalents (closing)")

        if tcl_cur == 0:
            out = {"applicable": False, "reason": "Total Current Liabilities is zero — ratio would be undefined.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": numerator_label, "value_cr": round(numerator_cur, 2)},
                   "denominator": {"label": "Total Current Liabilities", "value_cr": round(tcl_cur, 2)},
                   "other_bank_balances_cr": obb_cur,
                   "other_bank_balances_breakup": obb_breakup,
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(numerator_cur / tcl_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": numerator_label,
                "value_cr": round(numerator_cur, 2),
            },
            "denominator": {
                "label": "Total Current Liabilities (closing)",
                "value_cr": round(tcl_cur, 2),
            },
            "other_bank_balances_cr": obb_cur,
            "other_bank_balances_breakup": obb_breakup,
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — closing Balance Sheet subtotals, no averaging. "
                     "Other Bank Balances split into unrestricted/restricted via a deterministic label test "
                     "(Base -> Net-off -> Optional-Add); the unrestricted portion is included in the numerator. "
                     "Excludes Current Investments (only added if explicitly disclosed as liquid/unrestricted, "
                     "which can't be verified from a PDF read)."
                     if obb_unrestricted_cur is not None else
                     "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging. "
                     "Other Bank Balances has no sub-item breakup printed on the statement page, so its "
                     "restricted/unrestricted split can't be determined — surfaced as an informational figure "
                     "only, not included in the numerator. Excludes Current Investments (only added if "
                     "explicitly disclosed as liquid/unrestricted, which can't be verified from a PDF read)."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_days_working_capital_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Days Working Capital (Sr No 31) = (Average Working Capital ÷ Revenue from
    Operations) × 365 — the days-based expression of Working Capital
    Turnover (Sr No 8/26). Pure arithmetic on the SAME two figures (no new
    extraction): Average Working Capital = Total Current Assets − Total
    Current Liabilities, averaged (opening + closing) ÷ 2 when the prior
    year is disclosed, same "own small function" mirroring Sr No 26's
    internals rather than reusing its endpoint (Sr No 26's own N/A branch
    fires on Average Working Capital ≤ 0 — completely WRONG for this ratio,
    see below — so it can't just be composed client-side from that
    response).

    Per spec, a NEGATIVE result is a real, valid, and often FAVOURABLE signal
    (supplier-funded working capital — common in retail/e-commerce/QSR), NOT
    an error to withhold like Sr No 26 does — so unlike Working Capital
    Turnover, this NEVER returns N/A just because Average Working Capital is
    ≤ 0. The ONLY N/A condition is Revenue = 0 (undefined division).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_dwc_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        tca = parsed.get("total_current_assets")
        tcl = parsed.get("total_current_liabilities")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if tca is None or tcl is None:
            missing = "Total Current Assets" if tca is None else "Total Current Liabilities"
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        wc_cur = tca[0] - tcl[0]
        wc_prior = tca[1] - tcl[1] if tca[1] is not None and tcl[1] is not None else None

        if wc_prior is not None:
            avg_wc = round((wc_cur + wc_prior) / 2, 2)
            den_label = "Average Working Capital (opening + closing) ÷ 2"
            wc_by_year = {f"FY{fiscal_year}": round(wc_cur, 2), f"FY{fiscal_year - 1}": round(wc_prior, 2)}
            confidence, estimated = 1.0, False
        else:
            avg_wc = round(wc_cur, 2)
            den_label = "Closing Working Capital (opening/prior-year unavailable)"
            wc_by_year = {f"FY{fiscal_year}": round(wc_cur, 2)}
            confidence, estimated = 0.8, True

        days = round((avg_wc / rev_cur) * 365, 2)

        out = {
            "applicable": True,
            "value": days, "unit": "days",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": den_label, "value_cr": avg_wc,
                "working_capital_by_year": wc_by_year,
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — (Average Working Capital ÷ Revenue from Operations) "
                     "× 365, reusing the SAME figures as Working Capital Turnover (Sr No 8/26). A negative value "
                     "means Current Liabilities exceed Current Assets — genuinely supplier-funded working "
                     "capital, common in retail/e-commerce/QSR, and NOT treated as an error here."
                     + ("" if not estimated else
                        " Prior-year (opening) Working Capital was not disclosed, so Average Working Capital "
                        "uses the closing figure only — flagged as an estimate.")),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_receivables_to_payables_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Receivables-to-Payables Ratio (Sr No 32) = Trade Receivables ÷ Trade
    Payables — BOTH closing balance only (point-in-time, same convention as
    Current Ratio — never averaged). Pure reuse of the SAME Trade Receivables
    and Trade Payables fields already validated for Receivables Turnover (Sr
    No 3) and Payables Turnover (Sr No 5) — no new extraction, and no
    Other-Receivables/Other-Payables or Capital-Creditors/Provisions folded
    in (those aren't trade-cycle items).

    A self-financing indicator: >1x means the company is a net financer of
    its customers (receivables exceed payables); <1x means suppliers are
    effectively funding more of the working-capital cycle than customers
    owe — common in retail/QSR, and NOT an error (same non-judgemental
    treatment as Days Working Capital's negative values). Per spec, N/A only
    if Trade Payables = 0 (undefined division) — a low-but-nonzero Payables
    figure is still a real, reportable ratio.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_rtp_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        receivables = parsed.get("receivables")
        payables = parsed.get("payables")
        if receivables is None:
            out = {"applicable": False, "reason": "Could not find 'Trade Receivables' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if payables is None:
            out = {"applicable": False, "reason": "Could not find 'Trade Payables' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rec_cur, _rec_prior = receivables
        pay_cur, _pay_prior = payables

        if pay_cur == 0:
            out = {"applicable": False, "reason": "Trade Payables is zero — ratio would be undefined.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Trade Receivables (closing)", "value_cr": round(rec_cur, 2)},
                   "denominator": {"label": "Trade Payables (closing)", "value_cr": round(pay_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(rec_cur / pay_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Trade Receivables (closing)",
                "value_cr": round(rec_cur, 2),
            },
            "denominator": {
                "label": "Trade Payables (closing)",
                "value_cr": round(pay_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet balances, no averaging, "
                    "identical Trade Receivables/Trade Payables fields as Receivables Turnover (Sr No 3)/Payables "
                    "Turnover (Sr No 5). A ratio below 1x means suppliers are funding more of the working-capital "
                    "cycle than customers owe — common in retail/QSR, not treated as an error.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_net_debt_to_ebitda_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Net Debt/EBITDA (Sr No 33) = (Total Debt − Cash and Cash Equivalents) ÷
    EBITDA. The single most widely used credit-risk/leverage-capacity metric
    by lenders and rating agencies — more informative than gross Debt-to-
    Equity since it nets out available cash.

    Total Debt reuses Sr No 20's SHARED source-of-truth assembly
    (`_compute_total_debt` — the full a+b+c protocol: Borrowings verified
    against the Notes breakup, Lease Liabilities per the selected basis,
    qualifying Other Financial Liabilities via the Three-Part Test). Per the
    authoritative spec, this ratio applies "whichever basis is selected,
    consistently" — defaults to Basis 1 (includes Lease Liabilities,
    post-Ind-AS-116), matching Sr No 20/21/29's own default; pass
    `lease_basis="basis2"` for the traditional ex-lease view.

    EBITDA is its OWN independent calculation — MUST be EBITDA-basis (Sr No
    93: Revenue − COGS − Employee Benefit Expense − Other Expenses,
    deliberately excluding Depreciation & Amortisation), NEVER Sr No 15's
    EBIT-basis Operating Profit Margin (which now deducts D&A) — mirrors
    `fetch_ebitda_from_annual_report`'s internals exactly rather than
    reusing its endpoint, same "own small function" reasoning as every
    Sr-No-X-reuse ratio in this file, so this ratio's applicability stays
    independent of Total Debt's/EBITDA's own N/A branches.

    Per spec:
      - N/A if EBITDA ≤ 0 (a negative/zero denominator is meaningless).
      - If Net Debt is NEGATIVE (Cash > Total Debt), this is a genuine "Net
        Cash" position, NOT a leverage ratio — flagged as N/A with an
        explicit `net_cash: True` marker and the real underlying figures
        (never silently reported as "low leverage" without that flag, and
        never silently withheld either).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_ndebitda_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
        if not debt["applicable"]:
            out = {"applicable": False, "reason": debt["reason"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cash = parsed.get("cash")
        if cash is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Cash and Cash Equivalents' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        # EBITDA — its OWN independent calculation, mirroring
        # `fetch_ebitda_from_annual_report`'s internals exactly (see that
        # function's docstring for why this must never be Sr No 15's
        # EBIT-basis figure).
        components = parsed.get("components") or {}
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        if ebe is None:
            out = {"applicable": False, "reason": "Could not find 'Employee Benefit Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if oe is None:
            out = {"applicable": False, "reason": "Could not find 'Other Expenses' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cash_cur, _cash_prior = cash
        rev_cur, _rev_prior = revenue
        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        ebitda_cur = rev_cur - cogs_cur - ebe_cur - oe_cur

        total_debt_cur = debt["total_debt_cur"]
        net_debt_cur = round(total_debt_cur - cash_cur, 2)

        ebitda_confidence = 1.0 if len(components) == len(_COGS_LABELS) else 0.95
        confidence = min(debt["confidence"], ebitda_confidence)

        numerator = {
            "label": "Net Debt (Total Debt − Cash and Cash Equivalents)",
            "value_cr": net_debt_cur,
            "components": {
                **debt["components"],
                "less: Cash and Cash Equivalents": round(cash_cur, 2),
            },
        }
        denominator = {
            "label": "EBITDA (Revenue − COGS − Employee Costs − Other Expenses)",
            "value_cr": round(ebitda_cur, 2),
        }

        if ebitda_cur <= 0:
            out = {"applicable": False,
                   "reason": f"EBITDA is {'negative' if ebitda_cur < 0 else 'zero'} (₹{ebitda_cur:,.2f} Cr) — "
                             "the ratio would be meaningless, so it's flagged as N/A rather than reported.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        if net_debt_cur < 0:
            out = {"applicable": False, "net_cash": True,
                   "reason": f"Net Cash position — Cash and Cash Equivalents (₹{cash_cur:,.2f} Cr) exceed Total "
                             f"Debt (₹{total_debt_cur:,.2f} Cr), so Net Debt is negative (₹{net_debt_cur:,.2f} Cr). "
                             "This is NOT a leverage ratio; per spec it's flagged as 'Net Cash' rather than "
                             "reported as a spuriously 'low' Net Debt/EBITDA multiple.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(net_debt_cur / ebitda_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report — Total Debt (Sr No 20's full a+b+c protocol, "
                    f"{'Basis 1: Lease Liabilities included' if lease_basis == 'basis1' else 'Basis 2: Lease Liabilities excluded'}) "
                    "minus Cash and Cash Equivalents, divided by EBITDA (Sr No 93 — EBITDA-basis, never Sr No 15's "
                    "EBIT-basis Operating Profit Margin). " + debt["note"],
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_debt_service_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Debt Service Coverage Ratio (DSCR, Sr No 34) = Net Operating Income ÷
    Total Debt Service, where:
      - Net Operating Income is APPROXIMATED as EBITDA — its OWN independent
        calculation (mirrors `fetch_ebitda_from_annual_report`'s internals
        exactly, Sr No 93, EBITDA-basis), NEVER Sr No 15's now-EBIT-basis
        Operating Profit Margin.
      - Total Debt Service = Finance Costs (P&L) + Repayment of Borrowings
        (Cash Flow Statement, Financing Activities — the actual PRINCIPAL
        repaid during the year, via `_find_cash_flow_statement_items`, NOT
        the Balance Sheet's outstanding Borrowings balance, and never netted
        against fresh borrowings raised in the same section).
      - Lease principal repayment (Ind AS 116 splits a lease payment into
        interest — already inside Finance Costs — and principal components
        in the Cash Flow Statement): per Sr No 34's OWN spec, Basis 1
        (default) EXCLUDES this from Total Debt Service; Basis 2 (opt-in
        `lease_basis="basis2"`) INCLUDES it. NOTE this is the OPPOSITE
        direction from Sr No 20/33's Basis 1 (which INCLUDES leases in Total
        Debt) — each ratio's Basis 1/Basis 2 toggle is defined independently
        per its own spec row; "apply the same basis consistently" means
        whichever basis position the user selected, not that the literal
        include/exclude behaviour matches across ratios.

    A stricter solvency test than Interest Coverage (Sr No 22) — accounts
    for BOTH interest AND scheduled principal repayments; DSCR can fail even
    when Interest Coverage looks comfortable, if large principal repayments
    fall due (an early-warning signal used by lenders/covenant tests).

    Per spec, N/A / not calculated if Total Debt Service = 0 (a genuinely
    debt-free company — dividing by zero here is meaningless, and unlike
    Sr No 32's below-1x/Sr No 31's negative-days cases, there's no valid
    "the ratio is just very high" reading of a zero denominator).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_dscr_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        # EBITDA (Net Operating Income proxy) — own independent calculation,
        # same gates as fetch_ebitda_from_annual_report/Net Debt/EBITDA.
        components = parsed.get("components") or {}
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        if ebe is None:
            out = {"applicable": False, "reason": "Could not find 'Employee Benefit Expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if oe is None:
            out = {"applicable": False, "reason": "Could not find 'Other Expenses' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        finance_costs = parsed.get("finance_costs")
        if finance_costs is None:
            out = {"applicable": False, "reason": "Could not find 'Finance Costs' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        borrowings_repayment = parsed.get("borrowings_repayment")
        if borrowings_repayment is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Repayment of Borrowings' line in the Cash Flow Statement's "
                             "Financing Activities section.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        ebitda_cur = rev_cur - cogs_cur - ebe_cur - oe_cur
        ebitda_confidence = 1.0 if len(components) == len(_COGS_LABELS) else 0.95

        fc_cur, _fc_prior = finance_costs
        repay_cur, _repay_prior = borrowings_repayment

        lease_repayment = parsed.get("lease_repayment")
        lease_repay_cur = lease_repayment[0] if (lease_basis == "basis2" and lease_repayment is not None) else 0.0

        total_debt_service = round(fc_cur + repay_cur + lease_repay_cur, 2)

        debt_service_components = {
            "Finance Costs": round(fc_cur, 2),
            "Repayment of Borrowings (principal, Cash Flow Statement)": round(repay_cur, 2),
        }
        if lease_basis == "basis2":
            debt_service_components["Repayment of Lease Liabilities (principal, Basis 2)"] = round(lease_repay_cur, 2)

        numerator = {"label": "EBITDA (Net Operating Income proxy)", "value_cr": round(ebitda_cur, 2)}
        denominator = {"label": "Total Debt Service (Finance Costs + Principal Repayment)",
                        "value_cr": total_debt_service, "components": debt_service_components}

        if total_debt_service == 0:
            out = {"applicable": False,
                   "reason": "Total Debt Service is ₹0 — this appears to be a debt-free company, so DSCR is not "
                             "calculated (dividing by zero would be meaningless).",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(ebitda_cur / total_debt_service, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": ebitda_confidence,
            "estimated": ebitda_confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report — EBITDA (Sr No 93, EBITDA-basis, never Sr No 15's "
                    "EBIT-basis Operating Profit Margin) ÷ Total Debt Service (Finance Costs + actual Principal "
                    "Repaid during the year, from the Cash Flow Statement's Financing Activities section — never "
                    "the outstanding Balance Sheet balance, never netted against fresh borrowings raised). "
                    + ("Basis 2: Lease Liabilities principal repayment included in Total Debt Service."
                       if lease_basis == "basis2" else
                       "Basis 1 (default): Lease Liabilities principal repayment excluded from Total Debt Service."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_cash_flow_coverage_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Cash Flow Coverage Ratio (Sr No 35) = Net Cash Flow from Operating
    Activities ÷ Total Debt — a cash-based solvency check that tests whether
    the business's ACTUAL cash generation (not accounting profit/EBITDA)
    alone could retire its total debt, and over what timeframe. More
    resistant to manipulation than EBIT/EBITDA-based leverage ratios, since
    it uses real cash movements from the Cash Flow Statement rather than
    accrual accounting figures.

    Numerator: Net Cash Flow from Operating Activities (`operating_cash_flow`
    — see `_find_cash_flow_statement_items`), read directly from the Cash
    Flow Statement's own final Operating Activities subtotal — NEVER Net
    Profit or EBITDA substituted in its place, and keeps its natural sign (a
    genuinely negative OCF is a real distress signal, never forced
    positive).

    Denominator: Total Debt reuses Sr No 20's SHARED source-of-truth
    assembly (`_compute_total_debt` — the full a+b+c protocol). Per spec,
    defaults to Basis 1 (includes Lease Liabilities, post-Ind-AS-116),
    matching Sr No 20/21/29/33's own default; pass `lease_basis="basis2"`
    for the traditional ex-lease view — Cash is NEVER netted against Total
    Debt here (that's Net Debt/EBITDA, Sr No 33, a different metric).

    Per spec, N/A if Total Debt = 0 (a genuinely debt-free company — the
    ratio wouldn't be meaningful).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_cfcr_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        ocf = parsed.get("operating_cash_flow")
        if ocf is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow "
                             "Statement.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
        if not debt["applicable"]:
            out = {"applicable": False, "reason": debt["reason"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ocf_cur, _ocf_prior = ocf
        total_debt_cur = debt["total_debt_cur"]

        numerator = {"label": "Net Cash Flow from Operating Activities", "value_cr": round(ocf_cur, 2)}
        denominator = {"label": "Total Debt (closing)", "value_cr": total_debt_cur, "components": debt["components"]}

        if total_debt_cur == 0:
            out = {"applicable": False,
                   "reason": "Total Debt is ₹0 — this appears to be a debt-free company, so this ratio isn't "
                             "meaningful.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(ocf_cur / total_debt_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": debt["confidence"],
            "estimated": debt["confidence"] < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report — Net Cash Flow from Operating Activities (Cash Flow "
                    "Statement, never Net Profit/EBITDA substituted) ÷ Total Debt (Sr No 20's full a+b+c "
                    "protocol). " + debt["note"],
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_free_cash_flow_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Free Cash Flow (FCF, Sr No 36) = Net Cash Flow from Operating Activities
    − Capital Expenditure (net). The cash actually left over after the
    business reinvests in itself — the true funding source for dividends,
    debt repayment, buybacks, and M&A; considered by many analysts a more
    honest profitability measure than Net Profit, since it can't be
    distorted by non-cash accounting items (depreciation policy, provisions,
    accruals).

    Numerator: Net Operating Cash Flow (`operating_cash_flow`, Sr No 35's own
    field), never Net Profit or EBITDA substituted in its place.

    Net Capex = Purchase of Property, Plant & Equipment (`capex_ppe_purchase`
    — REQUIRED; a missing PPE-purchase line means Capex can't be determined
    at all) + Purchase of Intangible Assets (`capex_intangible_purchase` —
    optional, "sum what's there": a services business may genuinely have
    none) − Proceeds from Disposal of Fixed Assets (`capex_disposal_proceeds`
    — optional, netted OFF per spec for a "net Capex" figure). All three
    sourced from the Cash Flow Statement's Investing Activities section,
    NEVER the Balance Sheet's gross block movement (which can include
    revaluations/acquisitions unrelated to organic capex) and NEVER
    accounting Depreciation used as a proxy.

    Per spec, a NEGATIVE FCF is FLAGGED, not rejected/withheld — it's a
    genuine, real finding (e.g. a capex/growth investment phase), always
    reported as an absolute figure with no N/A gate of its own beyond the
    two required components (Operating Cash Flow, PPE Capex) actually being
    found.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_fcf_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        ocf = parsed.get("operating_cash_flow")
        if ocf is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow "
                             "Statement.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ppe = parsed.get("capex_ppe_purchase")
        if ppe is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Purchase of Property, Plant and Equipment' in the Cash Flow "
                             "Statement's Investing Activities section.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        intangible = parsed.get("capex_intangible_purchase")
        disposal = parsed.get("capex_disposal_proceeds")

        ocf_cur, _ocf_prior = ocf
        ppe_cur, _ppe_prior = ppe
        intangible_cur = intangible[0] if intangible is not None else 0.0
        disposal_cur = disposal[0] if disposal is not None else 0.0

        # "Net Capex" only actually means "net of disposal proceeds" when a
        # disposal-proceeds line was genuinely FOUND and subtracted — when
        # `disposal is None` (no such line on the Cash Flow Statement, e.g.
        # HUL), `disposal_cur` silently defaults to 0.0 and `net_capex_cur`
        # is arithmetically identical to GROSS capex, even though the label/
        # note below used to unconditionally claim "net of disposal
        # proceeds" regardless (QA-flagged: the VALUE was right, but the
        # explanation overclaimed netting that never actually happened for
        # that company). Both the numerator label and the note now say
        # "Gross Capex" whenever disposal wasn't found, "Net Capex" only
        # when it genuinely was.
        capex_is_net = disposal is not None
        net_capex_cur = round(ppe_cur + intangible_cur - disposal_cur, 2)
        fcf_cur = round(ocf_cur - net_capex_cur, 2)
        capex_label = "Net Capital Expenditure" if capex_is_net else "Capital Expenditure (gross — no disposal proceeds line found)"

        capex_components = {"Purchase of Property, Plant and Equipment": round(ppe_cur, 2)}
        if intangible is not None:
            capex_components["Purchase of Intangible Assets"] = round(intangible_cur, 2)
        if disposal is not None:
            capex_components["less: Proceeds from Disposal of Fixed Assets"] = round(disposal_cur, 2)

        out = {
            "applicable": True,
            "value": fcf_cur, "unit": "₹ Cr",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": f"Free Cash Flow (Operating Cash Flow − {'Net' if capex_is_net else 'Gross'} Capex)",
                "value_cr": fcf_cur,
                "components": {
                    "Net Cash Flow from Operating Activities": round(ocf_cur, 2),
                    f"less: {capex_label}": net_capex_cur,
                    **{f"  {k}": v for k, v in capex_components.items()},
                },
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — Net Cash Flow from Operating Activities minus net "
                      "Capital Expenditure (Purchase of PP&E and Intangible Assets, net of disposal proceeds), all "
                      "from the Cash Flow Statement (never Net Profit/EBITDA or Balance Sheet gross block movement "
                      "substituted)."
                      if capex_is_net else
                      "From the company's own Annual Report — Net Cash Flow from Operating Activities minus GROSS "
                      "Capital Expenditure (Purchase of PP&E and Intangible Assets), all from the Cash Flow "
                      "Statement (never Net Profit/EBITDA or Balance Sheet gross block movement substituted). No "
                      "'Proceeds from Disposal of Fixed Assets' line was found on this filing's Cash Flow "
                      "Statement, so nothing could be netted off — capex is reported gross, not net.")
                    + " A negative value is a real finding — often a genuine capex/growth investment "
                      "phase, not an error — and is reported as-is.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_fcf_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    FCF Margin (Sr No 38) = Free Cash Flow ÷ Revenue from Operations — a
    cash-based counterpart to Net Profit Margin (Sr No 16), showing what % of
    every rupee of sales is actually converted into free, reinvestable cash.

    Pure arithmetic reuse of the SAME components as Free Cash Flow (Sr No
    36) — mirrors that function's internals exactly (own small function,
    same reasoning as every Sr-No-X-reuse ratio in this file) rather than
    composing from its endpoint, and Revenue from Operations (Sr No 3).

    Per spec, a NEGATIVE FCF Margin is NOT automatically alarming — it can
    reflect a genuine growth/capex investment phase rather than
    deteriorating core operations — so it's never withheld, only Revenue = 0
    gates this to N/A (undefined division).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_fcfmargin_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ocf = parsed.get("operating_cash_flow")
        if ocf is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow "
                             "Statement.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ppe = parsed.get("capex_ppe_purchase")
        if ppe is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Purchase of Property, Plant and Equipment' in the Cash Flow "
                             "Statement's Investing Activities section.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        intangible = parsed.get("capex_intangible_purchase")
        disposal = parsed.get("capex_disposal_proceeds")

        ocf_cur, _ocf_prior = ocf
        ppe_cur, _ppe_prior = ppe
        intangible_cur = intangible[0] if intangible is not None else 0.0
        disposal_cur = disposal[0] if disposal is not None else 0.0

        # Same net-vs-gross wording fix as Free Cash Flow (Sr No 36) itself:
        # only call this "Net Capex" when a disposal-proceeds line was
        # actually found and subtracted.
        capex_is_net = disposal is not None
        net_capex_cur = round(ppe_cur + intangible_cur - disposal_cur, 2)
        fcf_cur = round(ocf_cur - net_capex_cur, 2)
        margin = round((fcf_cur / rev_cur) * 100, 2)
        capex_label = "Net Capital Expenditure" if capex_is_net else "Capital Expenditure (gross — no disposal proceeds line found)"

        out = {
            "applicable": True,
            "value": margin, "unit": "%",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": f"Free Cash Flow (Operating Cash Flow − {'Net' if capex_is_net else 'Gross'} Capex)",
                "value_cr": fcf_cur,
                "components": {
                    "Net Cash Flow from Operating Activities": round(ocf_cur, 2),
                    f"less: {capex_label}": net_capex_cur,
                },
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — Free Cash Flow (Sr No 36: Net Cash Flow from "
                      "Operating Activities minus net Capital Expenditure) ÷ Revenue from Operations."
                      if capex_is_net else
                      "From the company's own Annual Report — Free Cash Flow (Sr No 36: Net Cash Flow from "
                      "Operating Activities minus GROSS Capital Expenditure — no 'Proceeds from Disposal of "
                      "Fixed Assets' line was found on this filing's Cash Flow Statement, so nothing could be "
                      "netted off) ÷ Revenue from Operations.")
                    + " A negative margin can reflect a genuine growth/capex investment phase, not necessarily "
                      "deteriorating core operations, and is reported as-is.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_operating_cash_flow_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Operating Cash Flow Ratio (Sr No 39) = Net Cash Flow from Operating
    Activities ÷ Total Current Liabilities — a stricter, cash-based
    liquidity test than the Current Ratio (Sr No 10): it doesn't assume
    inventory/receivables will actually convert to cash in time, using cash
    genuinely generated during the year instead. A low ratio here alongside
    a healthy Current Ratio is a red flag — the balance-sheet "liquidity" may
    not be backed by actual cash generation.

    Numerator: `operating_cash_flow` (Sr No 35's own field), never Net Profit
    substituted. Denominator: Total Current Liabilities, CLOSING balance
    only (reuses Sr No 10's `total_current_liabilities` field — never
    averaged, consistent with the Current Ratio convention).

    Per spec, N/A if Total Current Liabilities = 0.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_ocfr_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        ocf = parsed.get("operating_cash_flow")
        if ocf is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow "
                             "Statement.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tcl = parsed.get("total_current_liabilities")
        if tcl is None:
            out = {"applicable": False, "reason": "Could not find 'Total Current Liabilities' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ocf_cur, _ocf_prior = ocf
        tcl_cur, _tcl_prior = tcl

        numerator = {"label": "Net Cash Flow from Operating Activities", "value_cr": round(ocf_cur, 2)}
        denominator = {"label": "Total Current Liabilities (closing)", "value_cr": round(tcl_cur, 2)}

        if tcl_cur == 0:
            out = {"applicable": False, "reason": "Total Current Liabilities is zero — ratio would be undefined.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(ocf_cur / tcl_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("bs_page")),
            "note": "From the company's own Annual Report — Net Cash Flow from Operating Activities (Cash Flow "
                    "Statement, never Net Profit substituted) ÷ Total Current Liabilities (closing balance, no "
                    "averaging, same convention as Current Ratio).",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_capex_intensity_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Capex Intensity (Sr No 40) = Capital Expenditure (net) ÷ Revenue from
    Operations — a structural indicator of how much of every rupee of sales
    must be reinvested just to sustain/grow the asset base. Central to
    distinguishing asset-light compounders (low, stable capex intensity)
    from capital-hungry businesses (telecom, infra, semiconductors) that
    require continuous heavy reinvestment.

    Pure arithmetic reuse of the SAME Capex components as Free Cash Flow (Sr
    No 36) — Purchase of PP&E (REQUIRED) + Purchase of Intangible Assets
    (optional, "sum what's there") − Proceeds from Disposal of Fixed Assets
    (optional, netted off) — and Revenue from Operations (Sr No 3).

    Per spec, N/A only if Revenue = 0.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_capexint_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ppe = parsed.get("capex_ppe_purchase")
        if ppe is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Purchase of Property, Plant and Equipment' in the Cash Flow "
                             "Statement's Investing Activities section.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        intangible = parsed.get("capex_intangible_purchase")
        disposal = parsed.get("capex_disposal_proceeds")

        ppe_cur, _ppe_prior = ppe
        intangible_cur = intangible[0] if intangible is not None else 0.0
        disposal_cur = disposal[0] if disposal is not None else 0.0

        net_capex_cur = round(ppe_cur + intangible_cur - disposal_cur, 2)
        intensity = round((net_capex_cur / rev_cur) * 100, 2)

        capex_components = {"Purchase of Property, Plant and Equipment": round(ppe_cur, 2)}
        if intangible is not None:
            capex_components["Purchase of Intangible Assets"] = round(intangible_cur, 2)
        if disposal is not None:
            capex_components["less: Proceeds from Disposal of Fixed Assets"] = round(disposal_cur, 2)

        out = {
            "applicable": True,
            "value": intensity, "unit": "%",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Capital Expenditure (net)",
                "value_cr": net_capex_cur,
                "components": capex_components,
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report — net Capital Expenditure (Purchase of PP&E and "
                    "Intangible Assets, net of disposal proceeds — identical components to Free Cash Flow's Sr "
                    "No 36 denominator) ÷ Revenue from Operations.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_working_capital_turnover_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Working Capital Turnover = Revenue from Operations ÷ Average Working
    Capital, where Working Capital (Sr No 13/26) = Total Current Assets −
    Total Current Liabilities for each year end. Per spec, a zero/negative
    Average Working Capital must be flagged, never silently divided (a
    negative denominator would invert the sign and mislead). Reuses the SAME
    cached PDF extraction as the other turnover ratios
    (`_get_extracted_financials`) — no extra download. Cached 90 days. Never
    raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_wcturn_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        tca = parsed.get("total_current_assets")
        tcl = parsed.get("total_current_liabilities")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if tca is None or tcl is None:
            missing = "Total Current Assets" if tca is None else "Total Current Liabilities"
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur <= 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero or missing.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        wc_cur = tca[0] - tcl[0]
        wc_prior = tca[1] - tcl[1] if tca[1] is not None and tcl[1] is not None else None

        if wc_prior is not None:
            avg_wc = round((wc_cur + wc_prior) / 2, 2)
            den_label = "Average Working Capital (opening + closing) ÷ 2"
            wc_by_year = {f"FY{fiscal_year}": round(wc_cur, 2), f"FY{fiscal_year - 1}": round(wc_prior, 2)}
            confidence, estimated = 1.0, False
        else:
            avg_wc = round(wc_cur, 2)
            den_label = "Closing Working Capital (opening/prior-year unavailable)"
            wc_by_year = {f"FY{fiscal_year}": round(wc_cur, 2)}
            confidence, estimated = 0.8, True

        # Per spec: DO NOT report this ratio if Average Working Capital <= 0 —
        # a negative/zero denominator inverts the sign and misleads, so the
        # ratio itself is withheld. But the underlying figures (Revenue,
        # Working Capital by year) are real, audited numbers we DID find —
        # withholding those too would hide data the user can see for
        # themselves, for no reason. Include them alongside the N/A flag so
        # "How we calculated this" still shows the real numerator/denominator.
        if avg_wc <= 0:
            out = {"applicable": False,
                   "reason": f"Average Working Capital is {'negative' if avg_wc < 0 else 'zero'} "
                             f"(₹{avg_wc:,.2f} Cr) — the ratio would be meaningless/sign-inverted, so it's "
                             "flagged as N/A rather than reported.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Revenue from Operations", "value_cr": round(rev_cur, 2)},
                   "denominator": {"label": den_label, "value_cr": avg_wc, "working_capital_by_year": wc_by_year},
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(rev_cur / avg_wc, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": estimated,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "denominator": {
                "label": den_label, "value_cr": avg_wc,
                "working_capital_by_year": wc_by_year,
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report — Working Capital = Total Current Assets − Total "
                     "Current Liabilities, both years read from the same statement."
                     if not estimated else
                     "From the company's own Annual Report. Prior-year (opening) Working Capital was not "
                     "disclosed, so Average Working Capital uses the closing figure only — flagged as an estimate."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_ocf_to_net_profit_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    OCF/Net Profit (Sr No 41) = Net Cash Flow from Operating Activities ÷
    Net Profit — a core earnings-quality diagnostic. Persistent divergence
    between accounting profit and actual cash generation is one of the most
    reliable early-warning signals of aggressive accounting or deteriorating
    business fundamentals.

    Numerator: `operating_cash_flow` (Sr No 35's own field), from the Cash
    Flow Statement. Denominator: Profit attributable to owners of the
    company (`pat`, reuses Sr No 16's exact numerator/basis logic — for
    consolidated statements this must be the owners-attributable figure,
    NEVER Total Profit including Minority Interest, per spec's explicit
    "inconsistent with Sr No 16 convention" warning). No averaging — both
    figures are current-year-only, same as Sr No 39 (Operating Cash Flow
    Ratio).

    Per spec, return N/A if Net Profit <= 0 (ratio not meaningful when the
    denominator is a loss) — never divide by a non-positive Net Profit.

    Confidence follows the SAME owners-vs-generic pattern as Net Profit
    Margin (Sr No 16): 1.0 when an explicit owners/NCI-excluding line was
    found, 0.8 (capped, "Estimated") when a consolidated statement fell back
    to the generic "Profit for the year" label.

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_ocfnp_v3_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        ocf = parsed.get("operating_cash_flow")
        if ocf is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow "
                             "Statement.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pat = parsed.get("pat")
        if pat is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Profit for the year'/'Profit after tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ocf_cur, _ocf_prior = ocf
        pat_cur, _pat_prior = pat
        pat_basis = parsed.get("pat_basis")
        ambiguous_nci = consolidated and pat_basis != "owners"
        confidence = 0.8 if ambiguous_nci else 1.0

        pat_label = ("Profit for the Year Attributable to Owners of the Company"
                     if pat_basis == "owners" else "Profit for the Year")

        numerator = {"label": "Net Cash Flow from Operating Activities", "value_cr": round(ocf_cur, 2)}
        denominator = {"label": pat_label, "value_cr": round(pat_cur, 2)}

        if pat_cur <= 0:
            out = {"applicable": False,
                   "reason": "Net Profit is zero or negative — the ratio is not meaningful when the "
                             "denominator is a loss.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(ocf_cur / pat_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": ambiguous_nci,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page")),
            "note": ("From the company's own Annual Report — Net Cash Flow from Operating Activities (Cash "
                     "Flow Statement) ÷ Profit for the Year attributable to Owners of the Company, explicitly "
                     "separate from Non-Controlling Interest."
                     if pat_basis == "owners" else
                     "From the company's own Annual Report — Net Cash Flow from Operating Activities ÷ Profit "
                     "for the Year. This filing did not print a separate owners-vs-Non-Controlling-Interest "
                     "attribution line, so 'Profit for the Year' is used as-is — for a standalone statement "
                     "this is exact; for a consolidated statement with genuine minority interests it may "
                     "include a small NCI portion, hence the reduced confidence."
                     if ambiguous_nci else
                     "From the company's own Annual Report — Net Cash Flow from Operating Activities ÷ Profit "
                     "for the Year (standalone, no Non-Controlling Interest applies)."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_roic_from_annual_report(symbol, name, fiscal_year, consolidated=True, lease_basis="basis1"):
    """
    Return on Invested Capital (ROIC, Sr No 42) = NOPAT / Invested Capital.

    NOPAT = EBIT x (1 - Effective Tax Rate). EBIT is the SAME Revenue -
    COGS - Employee Benefit Expense - Other Expenses - D&A computation
    already validated for Operating Profit Margin (Sr No 15) / ROCE (Sr No
    19) / Interest Coverage Ratio (Sr No 25) -- NOT "Profit Before Tax +
    Finance Costs" (that PBT-based approximation silently bakes in Other
    Income, the same bug already fixed for ROCE/ICR but originally missed
    here). Effective Tax Rate = Tax Expense / Profit Before Tax -- computed
    inline here rather than calling a Sr No 43 endpoint, since Effective
    Tax Rate (Sr No 43) has not been built yet as its own ratio; when it
    is, both should read the identical underlying `tax_expense`/`pbt`
    fields, so the two will always agree. N/A if Profit Before Tax <= 0 (an
    effective tax rate is not meaningful on a pre-tax loss).

    Invested Capital = Total Debt (Sr No 20's full a+b+c protocol, via the
    SAME shared `_compute_total_debt` used by Debt-to-Equity/Debt
    Ratio/Enterprise Value -- never a simplified Borrowings-only figure) +
    Total Equity, WHOLE-entity (owners' + Non-Controlling Interest,
    `equity_full` -- NOT the owners-only `equity` ROE/BVPS use) - Cash and
    Cash Equivalents (Sr No 12's field). Total Debt is the whole
    consolidated entity's debt, so Invested Capital's equity leg must match
    that same scope, same reasoning as Debt-to-Equity's (Sr No 23) own
    equity_full fix -- using owners-only equity here understated Invested
    Capital (and so overstated ROIC) for any company with material NCI.

    DEVIATION FROM SPEC, DISCLOSED: the spec calls for averaging Invested
    Capital over opening and closing balance sheet dates. `_compute_total_debt`
    only ever resolves a CLOSING-balance Total Debt (same limitation already
    accepted by Debt-to-Equity/Debt Ratio in this suite, which are
    closing-only by design) -- there is no reliable prior-year Total Debt
    signal to average against. Rather than fabricate a prior-year debt
    estimate, Invested Capital here is CLOSING-balance only, and this is
    surfaced explicitly in the response (`averaging`: "closing-only") and
    capped at confidence 0.8 to flag the deviation from the spec's own
    averaging convention.

    Per spec, N/A if Invested Capital <= 0.

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_roic_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}_{lease_basis}"
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

        components = parsed.get("components") or {}
        if len(components) == 0:
            out = {"applicable": False,
                   "reason": "Could not find any Cost of Goods Sold line (Cost of materials consumed / "
                             "Purchases of stock-in-trade / Changes in inventories) on the P&L page — "
                             "not a goods business.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        ebe = parsed.get("employee_benefit_expense")
        oe = parsed.get("other_expenses")
        dep = parsed.get("depreciation")
        revenue = parsed.get("revenue")
        pbt = parsed.get("pbt")
        tax_expense = parsed.get("tax_expense")
        missing = ("Revenue from operations" if revenue is None else
                   "Employee Benefit Expense" if ebe is None else
                   "Other Expenses" if oe is None else
                   "Depreciation and Amortisation Expense" if dep is None else
                   "Profit before tax" if pbt is None else
                   "Tax expense" if tax_expense is None else None)
        if missing:
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        dep_cur, _dep_prior = dep
        pbt_cur, _pbt_prior = pbt
        tax_cur, _tax_prior = tax_expense

        if pbt_cur <= 0:
            out = {"applicable": False,
                   "reason": "Profit Before Tax is zero or negative — Effective Tax Rate (and therefore NOPAT) "
                             "is not meaningful.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Profit Before Tax", "value_cr": round(pbt_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ebit_cur = rev_cur - cogs_cur - ebe_cur - oe_cur - dep_cur
        effective_tax_rate = tax_cur / pbt_cur
        nopat_cur = round(ebit_cur * (1 - effective_tax_rate), 2)

        debt = _compute_total_debt(parsed, lease_basis=lease_basis)
        if not debt["applicable"]:
            out = {"applicable": False, "reason": debt["reason"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity = parsed.get("equity_full")
        if equity is None:
            out = {"applicable": False, "reason": "Could not find a 'Total Equity' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cash = parsed.get("cash")
        equity_cur, _equity_prior = equity
        cash_cur = cash[0] if cash is not None else 0.0
        equity_basis = parsed.get("equity_basis")
        nci_included = consolidated and (parsed.get("equity") != equity)

        invested_capital_cur = round(debt["total_debt_cur"] + equity_cur - cash_cur, 2)

        numerator = {
            "label": "NOPAT (EBIT x (1 - Effective Tax Rate))",
            "value_cr": nopat_cur,
            "components": {
                "EBIT (Revenue − COGS − Employee Costs − Other Expenses − D&A)": round(ebit_cur, 2),
                "Effective Tax Rate": round(effective_tax_rate * 100, 2),
            },
        }
        denominator = {
            "label": "Invested Capital (closing) = Total Debt + Total Equity - Cash",
            "value_cr": invested_capital_cur,
            "components": {
                "Total Debt": debt["total_debt_cur"],
                "Total Equity" + (" (incl. Non-Controlling Interests)" if nci_included else ""): round(equity_cur, 2),
                "less: Cash and Cash Equivalents": round(cash_cur, 2),
            },
        }

        if invested_capital_cur <= 0:
            out = {"applicable": False,
                   "reason": f"Invested Capital is {'negative' if invested_capital_cur < 0 else 'zero'} "
                             f"(₹{invested_capital_cur:,.2f} Cr) — the ratio would be meaningless/sign-inverted, "
                             "so it's flagged as N/A rather than reported.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        roic = round((nopat_cur / invested_capital_cur) * 100, 2)

        ambiguous_nci = consolidated and equity_basis != "owners"
        confidence = min(debt["confidence"], 0.8 if ambiguous_nci else 1.0, 0.8)  # capped: closing-only, not averaged

        out = {
            "applicable": True,
            "value": roic, "unit": "%",
            "confidence": confidence,
            "estimated": True,
            "averaging": "closing-only",
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report — NOPAT (EBIT, identical to Operating Profit Margin's/"
                    "ROCE's numerator, taxed at the effective rate = Tax Expense ÷ Profit Before Tax) ÷ Invested "
                    "Capital (Total Debt, full a+b+c protocol reused from Debt-to-Equity, + Total Equity "
                    + ("(incl. Non-Controlling Interests) " if nci_included else "")
                    + "− Cash and Cash Equivalents). "
                    "Invested Capital is CLOSING-BALANCE only, not the opening+closing average the spec calls "
                    "for — Total Debt has no reliable prior-year signal in this pipeline, same limitation "
                    "already accepted by Debt-to-Equity/Debt Ratio. Benchmark against the company/sector's WACC "
                    "(typically 10-13% for Indian equities), not a fixed universal number — the ROIC-minus-WACC "
                    "spread is the real value-creation signal.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_effective_tax_rate_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Effective Tax Rate (Sr No 43) = Total Tax Expense (Current + Deferred
    Tax, `tax_expense`) ÷ Profit Before Tax (`pbt`, Sr No 19's basis) — same
    two fields ROIC (Sr No 42) already reads inline, exposed here as their
    own dedicated ratio so both agree by construction. `pbt` (via
    `_find_pl_row`) already stays scoped to CONTINUING OPERATIONS only when
    a filer splits the P&L into Continuing/Discontinued sections — it
    matches the FIRST "Profit before tax" occurrence on the page, and the
    Continuing-Operations section's own PBT subtotal always appears there,
    structurally before any separate Discontinued-Operations block further
    down (same reasoning already documented/validated for ROCE, Sr No 19).

    Per spec, N/A if Profit Before Tax <= 0 (ratio not meaningful for a
    loss-making period) — never divide by a non-positive PBT.

    Confidence is always 1.0 when both fields are found (Tax Expense and
    Profit Before Tax are both single, mandatory, unambiguous P&L
    subtotals — no owners/NCI-split ambiguity the way PAT/Equity have).

    Reuses the SAME cached PDF extraction — no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_etr_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        pbt = parsed.get("pbt")
        if pbt is None:
            out = {"applicable": False, "reason": "Could not find a 'Profit before tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tax_expense = parsed.get("tax_expense")
        if tax_expense is None:
            out = {"applicable": False, "reason": "Could not find a 'Tax expense' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pbt_cur, _pbt_prior = pbt
        tax_cur, _tax_prior = tax_expense

        numerator = {"label": "Total Tax Expense (Current + Deferred Tax)", "value_cr": round(tax_cur, 2)}
        denominator = {"label": "Profit Before Tax", "value_cr": round(pbt_cur, 2)}

        if pbt_cur <= 0:
            out = {"applicable": False,
                   "reason": "Profit Before Tax is zero or negative — Effective Tax Rate is not meaningful for a "
                             "loss-making period.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rate = round((tax_cur / pbt_cur) * 100, 2)

        out = {
            "applicable": True,
            "value": rate, "unit": "%",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — Total Tax Expense (Current Tax + Deferred Tax, the "
                    "P&L subtotal line, never Current Tax alone) ÷ Profit Before Tax. A large deviation from the "
                    "statutory rate (~25-26% concessional regime, ~30-35% older regime) should be cross-checked "
                    "against the Annual Report's Tax Reconciliation Note (a mandatory Ind AS disclosure) before "
                    "extrapolating — it often reflects a one-off item (MAT credit recognition, tax holiday "
                    "expiry, one-time settlement) rather than a sustainable change.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report — please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_contribution_margin_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Contribution Margin (Sr No 44) = (Revenue - Variable Costs) / Revenue.

    KNOWN, DELIBERATE APPROXIMATION (user-confirmed scope decision -- do not
    "fix" without a new user ask): the true spec definition needs an
    analyst-reconstructed fixed/variable cost-behaviour split, typically
    sourced from Management Discussion & Analysis or segment cost
    disclosures -- Ind AS Schedule III itself has no such classification,
    and this pipeline only parses the audited P&L/Balance Sheet/Cash Flow
    statement pages, never MD&A or segment notes. Building a genuine
    fixed/variable split is out of scope here.

    PROXY USED INSTEAD: "Variable Costs" = only the raw-material-type COGS
    components already extracted for Inventory Turnover/Gross Profit
    Margin (Sr No 1/14) -- "Cost of materials consumed" + "Purchases of
    stock-in-trade" ("sum what's there", same as those ratios), explicitly
    EXCLUDING "Changes in inventories" (an accounting timing adjustment, not
    a per-unit variable cost) and excluding ALL of "Other Expenses" (which
    mixes genuinely variable items like freight/power with fixed items like
    rent/admin that can't be split from a face-value P&L read). This
    UNDERSTATES true Contribution Margin (some genuinely variable costs
    inside Other Expenses are left out) -- the opposite direction of error
    from double-counting fixed costs as variable.

    Confidence is capped at 0.4 (below even the spec's own 0.8 "estimated
    proxy" tier) -- this is a materially rougher proxy than the spec's own
    analyst-reconstructed split, not a directly-disclosed figure, and must
    never be shown with the same confidence as a statement-line ratio.
    Always carries an "approximation" flag distinct from the ordinary
    "estimated" flag used elsewhere in this suite.

    N/A if Revenue = 0, or if NEITHER COGS component is found (a genuine
    services business -- same "not a goods business" gate as Inventory
    Turnover/Gross Profit Margin).

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_cm_v2_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, _rev_prior = revenue
        if rev_cur == 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        components = parsed.get("components", {})
        materials = components.get("Cost of materials consumed")
        stock_in_trade = components.get("Purchases of stock-in-trade")

        if materials is None and stock_in_trade is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Cost of materials consumed' or 'Purchases of stock-in-trade' on "
                             "the P&L page -- likely a services business with no goods cost to approximate "
                             "Variable Costs from.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        materials_cur = materials[0] if materials is not None else 0.0
        stock_in_trade_cur = stock_in_trade[0] if stock_in_trade is not None else 0.0
        variable_costs_cur = round(materials_cur + stock_in_trade_cur, 2)
        contribution_cur = round(rev_cur - variable_costs_cur, 2)
        margin = round((contribution_cur / rev_cur) * 100, 2)

        var_components = {}
        if materials is not None:
            var_components["Cost of materials consumed"] = round(materials_cur, 2)
        if stock_in_trade is not None:
            var_components["Purchases of stock-in-trade"] = round(stock_in_trade_cur, 2)

        out = {
            "applicable": True,
            "value": margin, "unit": "%",
            "confidence": 0.4,
            "estimated": True,
            "approximation": True,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Contribution (Revenue - Variable Costs, proxy)",
                "value_cr": contribution_cur,
                "components": {
                    "Revenue from Operations": round(rev_cur, 2),
                    "less: Variable Costs (proxy)": variable_costs_cur,
                    **{f"  {k}": v for k, v in var_components.items()},
                },
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "APPROXIMATION, not the true spec definition -- Ind AS filings don't disclose a fixed/"
                    "variable cost-behaviour split (that needs MD&A/segment data this pipeline doesn't parse). "
                    "'Variable Costs' here is only Cost of materials consumed + Purchases of stock-in-trade "
                    "(never 'Changes in inventories', never any part of 'Other Expenses' -- freight, power, and "
                    "other genuinely-variable items inside Other Expenses are NOT included), which UNDERSTATES "
                    "true Contribution Margin. Treat this figure as directional only, not precise -- confidence "
                    "is deliberately capped well below every directly-disclosed ratio in this suite.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_eps_growth_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    EPS Growth Rate (Sr No 45) = (Current Year Basic EPS / Prior Year Basic
    EPS) - 1. Reuses the SAME `eps` field already extracted for P/E (Sr No
    24) -- both years come from the identical (cur, prior) tuple, so there
    is no possibility of mixing Basic EPS in one year with Diluted in
    another, or of a "periods don't match" mismatch (both are always the
    same statement's adjacent columns).

    Per spec, N/A / Not Meaningful if Prior Year EPS is zero or negative --
    a growth percentage off a loss-making or zero base is misleading, never
    computed.

    Confidence is always 1.0 when both years are found (Basic EPS is a
    mandatory Ind AS disclosure, single unambiguous figure -- no owners/NCI
    or fixed/variable judgment call the way some other ratios in this suite
    have).

    Applicable to Banks/NBFC/Insurance too (per spec's own
    applicable_industries list has no exclusions for this ratio) -- unlike
    most ratios in this file, the caller should NOT apply the standard
    lender/financial-business exclusion.

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_epsgrowth_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        eps = parsed.get("eps")
        if eps is None:
            out = {"applicable": False,
                   "reason": "Could not find a Basic EPS row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        eps_cur, eps_prior = eps
        if eps_prior is None:
            out = {"applicable": False,
                   "reason": "Prior year Basic EPS was not disclosed alongside the current year figure.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Basic EPS (current year)", "value_cr": round(eps_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        numerator = {"label": "Basic EPS (current year)", "value_cr": round(eps_cur, 2)}
        denominator = {"label": "Basic EPS (prior year)", "value_cr": round(eps_prior, 2)}

        if eps_prior <= 0:
            out = {"applicable": False,
                   "reason": "Prior Year Basic EPS is zero or negative -- EPS Growth Rate is Not Meaningful off "
                             "a loss-making/zero base.",
                   "not_meaningful": True,
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        growth = round(((eps_cur / eps_prior) - 1) * 100, 2)

        out = {
            "applicable": True,
            "value": growth, "unit": "%",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report -- (Current Year Basic EPS / Prior Year Basic EPS) "
                    "- 1, both years read from the same Basic EPS disclosure (never mixing Basic and Diluted "
                    "across years). Highly susceptible to distortion by one-off items in either year's EPS -- "
                    "always check the Annual Report for exceptional items before trusting a single-year growth "
                    "figure, and cross-check against Net Profit Margin/Revenue growth trends adjusted for any "
                    "share count changes (buybacks/issuances).",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_dividend_payout_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Dividend Payout Ratio (Sr No 47) = Total Dividends Declared (Sr No 27's
    `dividend_per_share`, ALWAYS standalone-sourced per that ratio's own
    spec rule -- dividends are declared by the parent entity, never
    consolidated -- times `shares_outstanding`, converted to Rs Cr) / Net
    Profit (`pat`, Sr No 16's owners-attributable field).

    Reuses Sr No 27's "declared, not merely proposed" extraction as-is --
    `dividend_per_share_found=False` means the 0.0 default (no dividend
    found) rather than a genuine confirmed zero, same distinction Dividend
    Yield already carries; this ratio inherits that same reduced confidence
    when unconfirmed.

    Per spec, N/A if Net Profit <= 0 -- a payout ratio computed off a loss
    is not meaningful, even if a dividend was still paid from reserves.

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_payout_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        pat = parsed.get("pat")
        if pat is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Profit for the year'/'Profit after tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        shares = parsed.get("shares_outstanding")
        if shares is None:
            out = {"applicable": False,
                   "reason": "Could not find the 'Issued, Subscribed and Fully Paid' equity share count in the "
                             "Equity Share Capital note.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pat_cur, _pat_prior = pat
        shares_cur, _shares_prior = shares
        dps = parsed.get("dividend_per_share") or 0.0
        dps_found = parsed.get("dividend_per_share_found", False)
        pat_basis = parsed.get("pat_basis")

        total_dividends_cur = round((dps * shares_cur) / 1e7, 2)  # per-share Rs x share count -> Rs Cr

        pat_label = ("Profit for the Year Attributable to Owners of the Company"
                     if pat_basis == "owners" else "Profit for the Year")

        numerator = {
            "label": "Total Dividends Declared (Dividend per Share x Shares Outstanding)",
            "value_cr": total_dividends_cur,
            "components": {
                "Dividend per Share (declared, standalone)": round(dps, 2),
                "Equity Shares Outstanding": shares_cur,
            },
        }
        denominator = {"label": pat_label, "value_cr": round(pat_cur, 2)}

        if pat_cur <= 0:
            out = {"applicable": False,
                   "reason": "Net Profit is zero or negative -- Dividend Payout Ratio is not meaningful when "
                             "the denominator is a loss.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": numerator, "denominator": denominator,
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        payout = round((total_dividends_cur / pat_cur) * 100, 2)

        # Confidence mirrors Dividend Yield's own tiering: 1.0 when the
        # "during the year... was paid" sentence was actually found, 0.4
        # (Unconfirmed) when defaulted to 0.0 -- a genuinely-verified 0%
        # payout must read differently from an unconfirmed one.
        ambiguous_nci = consolidated and pat_basis != "owners"
        confidence = 1.0 if dps_found else 0.4
        if dps_found and ambiguous_nci:
            confidence = 0.8

        out = {
            "applicable": True,
            "value": payout, "unit": "%",
            "confidence": confidence,
            "estimated": not dps_found,
            "dividend_found": dps_found,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": numerator,
            "denominator": denominator,
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": ("From the company's own Annual Report -- Total Dividends Declared during the year "
                     "(Dividend per Share, standalone-sourced per Dividend Yield's own convention, x Equity "
                     "Shares Outstanding) / Net Profit attributable to Owners of the Company."
                     if dps_found else
                     "No 'dividend paid during the year' sentence was found in the Annual Report -- this is "
                     "reported as an UNCONFIRMED 0% (not a verified nil-dividend year), same distinction "
                     "Dividend Yield (Sr No 27) already carries, hence the reduced confidence."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_operating_cash_flow_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Net Cash Flow from Operating Activities (Sr No 53's denominator, GROSS
    -- before capex, never Free Cash Flow) -- the SAME `operating_cash_flow`
    field already extracted for Operating Cash Flow Ratio (Sr No 39)/OCF-
    Net-Profit (Sr No 41)/Free Cash Flow (Sr No 36). Built as its own
    dedicated function since none of those ratios' own N/A branches expose
    a standalone Operating Cash Flow endpoint -- Price/Cash Flow needs the
    raw figure paired with Market Capitalisation (a live-price/market-data
    combination those statement-only ratios never need).

    Per spec, N/A if Operating Cash Flow <= 0.

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_ocf_only_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        ocf = parsed.get("operating_cash_flow")
        if ocf is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Net Cash Flow from Operating Activities' in the Cash Flow "
                             "Statement.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ocf_cur, _ocf_prior = ocf

        if ocf_cur <= 0:
            out = {"applicable": False,
                   "reason": "Net Cash Flow from Operating Activities is zero or negative.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Net Cash Flow from Operating Activities", "value_cr": round(ocf_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        out = {
            "applicable": True,
            "value": round(ocf_cur, 2), "unit": "₹ Cr",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Net Cash Flow from Operating Activities", "value_cr": round(ocf_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report -- Net Cash Flow from Operating Activities, GROSS "
                    "(before capex, never Free Cash Flow -- that is Sr No 36, a different metric).",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_altman_z_score_components_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Altman Z-Score (Sr No 55) STATEMENT-SIDE components -- everything except
    Market Capitalisation, which needs a LIVE price (market data, not the
    Annual Report) and is combined client-side, same architecture as every
    other market-multiple ratio in this suite (P/E, P/B, P/S, EV/*).

    Z = 1.2*(WC/TA) + 1.4*(RE/TA) + 3.3*(EBIT/TA) + 0.6*(MktCap/TL) +
        1.0*(Sales/TA), where:
      - WC (Working Capital) reuses Sr No 13's TCA - TCL.
      - TA (Total Assets) reuses Sr No 7's `total_assets` field.
      - RE (Retained Earnings) is the NEW `retained_earnings` field --
        deliberately NOT the same as Total Equity (which also includes
        paid-up Share Capital).
      - EBIT reuses Sr No 19's basis (Profit Before Tax + Finance Costs).
      - TL (Total Liabilities) = Total Assets - Total Equity (owners-
        attributable) -- a pure Balance-Sheet-identity derivation, no new
        extraction needed (Assets = Equity + Liabilities always holds).
      - Sales reuses Sr No 3's `revenue` field.

    Per spec, N/A for Banks/NBFC/Insurance (checked by the caller via the
    standard lender exclusion) -- balance sheet structure differs
    fundamentally, this model doesn't apply. N/A if Total Assets <= 0 or
    if Total Liabilities <= 0 (MktCap/TL term undefined).

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_zscore_comp_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        total_assets = parsed.get("total_assets")
        if total_assets is None:
            out = {"applicable": False, "reason": "Could not find 'Total Assets' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity = parsed.get("equity")
        if equity is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Total Equity'/'Shareholders' Funds' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tca = parsed.get("total_current_assets")
        tcl = parsed.get("total_current_liabilities")
        if tca is None or tcl is None:
            missing = "Total Current Assets" if tca is None else "Total Current Liabilities"
            out = {"applicable": False, "reason": f"Could not find '{missing}' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        retained_earnings = parsed.get("retained_earnings")
        if retained_earnings is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Reserves and Surplus'/'Other Equity' row on the Balance Sheet "
                              "page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pbt = parsed.get("pbt")
        if pbt is None:
            out = {"applicable": False, "reason": "Could not find a 'Profit before tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        revenue = parsed.get("revenue")
        if revenue is None:
            out = {"applicable": False, "reason": "Could not find 'Revenue from operations' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ta_cur, _ta_prior = total_assets
        equity_cur, _equity_prior = equity
        tca_cur, _tca_prior = tca
        tcl_cur, _tcl_prior = tcl
        re_cur, _re_prior = retained_earnings
        pbt_cur, _pbt_prior = pbt
        finance_costs = parsed.get("finance_costs")
        fc_cur = finance_costs[0] if finance_costs is not None else 0.0
        rev_cur, _rev_prior = revenue

        if ta_cur <= 0:
            out = {"applicable": False, "reason": "Total Assets is zero or negative.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        wc_cur = round(tca_cur - tcl_cur, 2)
        ebit_cur = round(pbt_cur + fc_cur, 2)
        tl_cur = round(ta_cur - equity_cur, 2)

        if tl_cur <= 0:
            out = {"applicable": False,
                   "reason": "Total Liabilities (Total Assets - Total Equity) is zero or negative -- the "
                             "Market Cap/Total Liabilities term is undefined.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        equity_basis = parsed.get("equity_basis")
        retained_earnings_basis = parsed.get("retained_earnings_basis")
        ambiguous_nci = consolidated and equity_basis != "owners"
        confidence = 0.8 if (ambiguous_nci or retained_earnings_basis == "other_equity_proxy") else 1.0

        out = {
            "applicable": True,
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "components": {
                "total_assets_cr": ta_cur,
                "working_capital_cr": wc_cur,
                "retained_earnings_cr": re_cur,
                "retained_earnings_basis": retained_earnings_basis,
                "ebit_cr": ebit_cur,
                "total_liabilities_cr": tl_cur,
                "sales_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report -- Working Capital, Total Assets, Retained "
                     "Earnings (Reserves and Surplus, exact match), EBIT, Total Liabilities (= Total Assets - "
                     "Total Equity), and Sales, per Altman Z-Score's standard public-manufacturer formula. "
                     "Market Capitalisation (the fifth component) uses a live/current price, combined "
                     "client-side."
                     if retained_earnings_basis == "exact" else
                     "From the company's own Annual Report. Retained Earnings uses 'Other Equity' (the "
                     "post-2019 Ind AS combined reserves line) as a proxy -- it may include Securities "
                     "Premium/General Reserve alongside genuine accumulated profits, which can't be split "
                     "further from face-value Balance Sheet text, hence the reduced confidence. Market "
                     "Capitalisation (the fifth component) uses a live/current price, combined client-side."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_piotroski_f_score_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Piotroski F-Score (Sr No 56) = sum of nine binary (1/0) year-over-year
    fundamental-strength tests across Profitability, Leverage/Liquidity,
    and Operating Efficiency. Every underlying figure reuses fields
    already extracted for other ratios in this suite -- no new extraction
    -- since the shared dict already stores (current, prior) tuples for
    everything this composite needs (`pat`, `total_assets`,
    `operating_cash_flow`, `lt_borrowings`, `total_current_assets`,
    `total_current_liabilities`, `shares_outstanding`, `revenue`,
    `components` for COGS).

    SIMPLIFICATION, DISCLOSED: tests 1 and 3 (ROA) and test 9 (Asset
    Turnover) use POINT-IN-TIME (closing Total Assets), not the
    opening+closing AVERAGE Sr No 17/Sr No 7 use elsewhere -- computing a
    true average for BOTH the current and prior year would need a third,
    even-older year of Total Assets (opening balance of the prior year),
    which isn't available from a single two-column Balance Sheet read.
    This is a reasonable, standard simplification for a binary
    "improved or not" comparison test (the classic academic Piotroski
    formulation itself also uses point-in-time Total Assets), not an
    error -- flagged here and in the response note.

    Per spec's own instruction ("flag the affected test(s) rather than
    the whole score" when a component is incomplete): the four
    PROFITABILITY tests (ROA>0, OCF>0, ROA improved, OCF>NetProfit)
    require `pat`/`total_assets`/`operating_cash_flow` with BOTH years
    present -- if any of those three fields is entirely missing, the
    whole score is N/A (these are the backbone, per spec's blunt "DO NOT
    CALCULATE if fewer than two consecutive years" instruction). The
    remaining FIVE tests (leverage, current ratio, dilution, gross
    margin, asset turnover) are each individually SKIPPED (not zeroed,
    not counted, `max_score` reduced accordingly) when their own
    underlying field lacks a two-year pair -- never silently assumed to
    fail.

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_fscore_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        def _both_years(field):
            v = parsed.get(field)
            if v is None or v[0] is None or v[1] is None:
                return None
            return v

        pat = _both_years("pat")
        total_assets = _both_years("total_assets")
        ocf = _both_years("operating_cash_flow")

        if pat is None or total_assets is None or ocf is None:
            missing = "Profit After Tax" if pat is None else ("Total Assets" if total_assets is None else
                       "Net Cash Flow from Operating Activities")
            out = {"applicable": False,
                   "reason": f"Could not find two consecutive years of '{missing}' -- the four Profitability "
                             "tests (the backbone of this score) require both years.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pat_cur, pat_prior = pat
        ta_cur, ta_prior = total_assets
        ocf_cur, ocf_prior = ocf

        if ta_cur <= 0 or ta_prior <= 0:
            out = {"applicable": False, "reason": "Total Assets is zero or negative in one of the two years.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        roa_cur = pat_cur / ta_cur
        roa_prior = pat_prior / ta_prior

        tests = []
        score = 0
        max_score = 9

        # 1. ROA > 0 this year.
        t1 = roa_cur > 0
        tests.append({"name": "ROA > 0", "category": "Profitability", "applicable": True, "passed": t1,
                       "detail": f"ROA {roa_cur * 100:.2f}% (point-in-time, PAT / closing Total Assets)"})
        score += 1 if t1 else 0

        # 2. Operating Cash Flow > 0 this year.
        t2 = ocf_cur > 0
        tests.append({"name": "Operating Cash Flow > 0", "category": "Profitability", "applicable": True,
                       "passed": t2, "detail": f"OCF Rs.{ocf_cur:,.2f} Cr"})
        score += 1 if t2 else 0

        # 3. ROA this year > ROA prior year.
        t3 = roa_cur > roa_prior
        tests.append({"name": "ROA improved YoY", "category": "Profitability", "applicable": True, "passed": t3,
                       "detail": f"{roa_cur * 100:.2f}% vs {roa_prior * 100:.2f}% prior year"})
        score += 1 if t3 else 0

        # 4. Operating Cash Flow > Net Profit this year (accrual quality).
        t4 = ocf_cur > pat_cur
        tests.append({"name": "OCF > Net Profit (accrual quality)", "category": "Profitability", "applicable": True,
                       "passed": t4, "detail": f"OCF Rs.{ocf_cur:,.2f} Cr vs PAT Rs.{pat_cur:,.2f} Cr"})
        score += 1 if t4 else 0

        # 5. Long-term Debt/Total Assets this year < prior year (leverage decreased).
        lt_borrowings = _both_years("lt_borrowings")
        if lt_borrowings is not None:
            lt_cur, lt_prior = lt_borrowings
            lev_cur = lt_cur / ta_cur
            lev_prior = lt_prior / ta_prior
            t5 = lev_cur < lev_prior
            tests.append({"name": "Leverage decreased (LT Debt/TA)", "category": "Leverage/Liquidity",
                           "applicable": True, "passed": t5,
                           "detail": f"{lev_cur * 100:.2f}% vs {lev_prior * 100:.2f}% prior year"})
            score += 1 if t5 else 0
        else:
            max_score -= 1
            tests.append({"name": "Leverage decreased (LT Debt/TA)", "category": "Leverage/Liquidity",
                           "applicable": False, "passed": None,
                           "detail": "Skipped -- could not find Long-term Borrowings for both years."})

        # 6. Current Ratio this year > Current Ratio prior year.
        tca = _both_years("total_current_assets")
        tcl = _both_years("total_current_liabilities")
        if tca is not None and tcl is not None and tca[1] != 0 and tcl[1] != 0 and tcl[0] != 0:
            tca_cur, tca_prior = tca
            tcl_cur, tcl_prior = tcl
            cr_cur = tca_cur / tcl_cur
            cr_prior = tca_prior / tcl_prior
            t6 = cr_cur > cr_prior
            tests.append({"name": "Current Ratio improved YoY", "category": "Leverage/Liquidity",
                           "applicable": True, "passed": t6,
                           "detail": f"{cr_cur:.2f}x vs {cr_prior:.2f}x prior year"})
            score += 1 if t6 else 0
        else:
            max_score -= 1
            tests.append({"name": "Current Ratio improved YoY", "category": "Leverage/Liquidity",
                           "applicable": False, "passed": None,
                           "detail": "Skipped -- could not find Total Current Assets/Liabilities for both years."})

        # 7. No new shares issued this year (no dilution). Small 0.1% tolerance
        # for rounding in the share-count extraction, not a real issuance.
        shares = _both_years("shares_outstanding")
        if shares is not None:
            shares_cur, shares_prior = shares
            t7 = shares_cur <= shares_prior * 1.001
            tests.append({"name": "No dilution (shares not increased)", "category": "Leverage/Liquidity",
                           "applicable": True, "passed": t7,
                           "detail": f"{shares_cur:,.0f} vs {shares_prior:,.0f} prior year"})
            score += 1 if t7 else 0
        else:
            max_score -= 1
            tests.append({"name": "No dilution (shares not increased)", "category": "Leverage/Liquidity",
                           "applicable": False, "passed": None,
                           "detail": "Skipped -- could not find Equity Shares Outstanding for both years."})

        # 8. Gross Margin this year > Gross Margin prior year. Same
        # "sum what's there" COGS-component gate as Gross Profit Margin
        # (Sr No 14) -- never gated on ALL THREE being present.
        revenue = _both_years("revenue")
        components = parsed.get("components", {})
        materials = components.get("Cost of materials consumed")
        stock_in_trade = components.get("Purchases of stock-in-trade")
        inv_change = components.get("Changes in inventories")
        cogs_any = materials is not None or stock_in_trade is not None or inv_change is not None
        if revenue is not None and cogs_any and revenue[0] != 0 and revenue[1] != 0:
            rev_cur, rev_prior = revenue

            def _cogs_component(comp, idx):
                return comp[idx] if comp is not None else 0.0

            cogs_cur = (_cogs_component(materials, 0) + _cogs_component(stock_in_trade, 0)
                        + _cogs_component(inv_change, 0))
            cogs_prior = (_cogs_component(materials, 1) + _cogs_component(stock_in_trade, 1)
                          + _cogs_component(inv_change, 1))
            gm_cur = (rev_cur - cogs_cur) / rev_cur
            gm_prior = (rev_prior - cogs_prior) / rev_prior
            t8 = gm_cur > gm_prior
            tests.append({"name": "Gross Margin improved YoY", "category": "Operating Efficiency",
                           "applicable": True, "passed": t8,
                           "detail": f"{gm_cur * 100:.2f}% vs {gm_prior * 100:.2f}% prior year"})
            score += 1 if t8 else 0
        else:
            max_score -= 1
            tests.append({"name": "Gross Margin improved YoY", "category": "Operating Efficiency",
                           "applicable": False, "passed": None,
                           "detail": "Skipped -- not a goods business, or Revenue/COGS unavailable for both "
                                     "years."})

        # 9. Asset Turnover this year > prior year (point-in-time, same
        # simplification as tests 1/3 -- see docstring).
        if revenue is not None and revenue[0] != 0 and revenue[1] != 0:
            rev_cur, rev_prior = revenue
            at_cur = rev_cur / ta_cur
            at_prior = rev_prior / ta_prior
            t9 = at_cur > at_prior
            tests.append({"name": "Asset Turnover improved YoY", "category": "Operating Efficiency",
                           "applicable": True, "passed": t9,
                           "detail": f"{at_cur:.2f}x vs {at_prior:.2f}x prior year"})
            score += 1 if t9 else 0
        else:
            max_score -= 1
            tests.append({"name": "Asset Turnover improved YoY", "category": "Operating Efficiency",
                           "applicable": False, "passed": None,
                           "detail": "Skipped -- could not find Revenue from Operations for both years."})

        evaluated = sum(1 for t in tests if t["applicable"])
        confidence = 1.0 if evaluated == 9 else (0.8 if evaluated >= 7 else 0.4)

        out = {
            "applicable": True,
            "value": score, "max_score": max_score, "tests_evaluated": evaluated, "unit": "",
            "confidence": confidence,
            "estimated": evaluated < 9,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "tests": tests,
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": ("From the company's own Annual Report -- sum of nine binary year-over-year tests across "
                     "Profitability, Leverage/Liquidity, and Operating Efficiency, all nine evaluated."
                     if evaluated == 9 else
                     f"From the company's own Annual Report -- {evaluated} of 9 tests evaluated (the remaining "
                     f"{9 - evaluated} skipped for missing two-year data, not counted as failures), scored "
                     f"against a max of {max_score}. ROA/Asset Turnover tests use point-in-time (not averaged) "
                     "Total Assets, a standard simplification for a two-year comparison test."),
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
        # not cached: an unexpected/transient error shouldn't be locked in for a week


def fetch_beneish_m_score_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Beneish M-Score (Sr No 57) = -4.84 + 0.92*DSRI + 0.528*GMI + 0.404*AQI
    + 0.892*SGI + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI.

    An earnings-manipulation detection model -- every one of the eight
    index variables is a current-year-vs-prior-year ratio, built entirely
    from fields already extracted for other ratios in this file (all
    stored as (current, prior) tuples): `receivables`, `revenue`,
    `components` (COGS), `total_assets`, `total_current_assets`,
    `net_fixed_assets`, `depreciation`, `pat`, `operating_cash_flow`,
    `other_expenses`, and the Total Debt sub-components (`lt_borrowings`,
    `st_borrowings`, `current_maturities`, `lease_liabilities_nc`,
    `lease_liabilities_cur`).

    TWO DELIBERATE, DISCLOSED SIMPLIFICATIONS:
    (1) Ind AS Schedule III has no distinct "SG&A" line -- `other_expenses`
        (Sr No 15's own field) is used as the SGAI proxy, the standard
        substitution for Ind AS filers.
    (2) LVGI's "Total Debt" is summed directly from the raw Balance Sheet
        components (Basis 1: Borrowings + Lease Liabilities, "sum what's
        there") for BOTH years, rather than reusing `_compute_total_debt`
        (Sr No 20's own function) -- that function only ever resolves a
        CLOSING-year figure with a Notes-to-Accounts cross-check; there is
        no equivalent prior-year Notes verification available. Using the
        SAME simplified face-value approach consistently for both years
        being compared is more methodologically sound for a YoY ratio than
        applying extra rigor to only one side of it.

    Per spec, this REQUIRES two consecutive years of complete, non-restated
    data for every one of the eight variables -- unlike Piotroski F-Score
    (Sr No 56), which explicitly allows skipping individual tests, spec's
    own language here is a stricter "DO NOT CALCULATE" if any is
    incomplete. Missing ANY required field (in either year) returns N/A
    with the specific missing item named, never a partial score.

    Reuses the SAME cached PDF extraction -- no extra download. Cached 90
    days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_mscore_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        def _both_years(field, label):
            v = parsed.get(field)
            if v is None or v[0] is None or v[1] is None:
                return None, label
            return v, None

        revenue, m = _both_years("revenue", "Revenue from Operations")
        if revenue is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        receivables, m = _both_years("receivables", "Trade Receivables")
        if receivables is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        total_assets, m = _both_years("total_assets", "Total Assets")
        if total_assets is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tca, m = _both_years("total_current_assets", "Total Current Assets")
        if tca is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        net_fixed_assets, m = _both_years("net_fixed_assets", "Net Fixed Assets")
        if net_fixed_assets is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        depreciation, m = _both_years("depreciation", "Depreciation")
        if depreciation is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        pat, m = _both_years("pat", "Profit After Tax")
        if pat is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ocf, m = _both_years("operating_cash_flow", "Net Cash Flow from Operating Activities")
        if ocf is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        other_expenses, m = _both_years("other_expenses", "Other Expenses (SG&A proxy)")
        if other_expenses is None:
            out = {"applicable": False, "reason": f"Could not find two consecutive years of '{m}'.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        components = parsed.get("components", {})
        materials = components.get("Cost of materials consumed")
        stock_in_trade = components.get("Purchases of stock-in-trade")
        inv_change = components.get("Changes in inventories")
        cogs_any = materials is not None or stock_in_trade is not None or inv_change is not None
        if not cogs_any:
            out = {"applicable": False,
                   "reason": "Could not find any COGS component (Cost of materials consumed / Purchases of "
                             "stock-in-trade / Changes in inventories) -- likely a services business with no "
                             "Gross Margin to measure.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        rev_cur, rev_prior = revenue
        recv_cur, recv_prior = receivables
        ta_cur, ta_prior = total_assets
        tca_cur, tca_prior = tca
        ppe_cur, ppe_prior = net_fixed_assets
        dep_cur, dep_prior = depreciation
        pat_cur, pat_prior = pat
        ocf_cur, ocf_prior = ocf
        sga_cur, sga_prior = other_expenses

        if rev_cur == 0 or rev_prior == 0 or ta_cur == 0 or ta_prior == 0:
            out = {"applicable": False, "reason": "Revenue or Total Assets is zero in one of the two years.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        def _cogs(comp, idx):
            return comp[idx] if comp is not None else 0.0

        cogs_cur = _cogs(materials, 0) + _cogs(stock_in_trade, 0) + _cogs(inv_change, 0)
        cogs_prior = _cogs(materials, 1) + _cogs(stock_in_trade, 1) + _cogs(inv_change, 1)
        gm_cur = (rev_cur - cogs_cur) / rev_cur
        gm_prior = (rev_prior - cogs_prior) / rev_prior

        # 1. DSRI -- Days Sales in Receivables Index.
        dsri = (recv_cur / rev_cur) / (recv_prior / rev_prior)
        # 2. GMI -- Gross Margin Index (>1 means margin DETERIORATED).
        gmi = gm_prior / gm_cur if gm_cur != 0 else None
        # 3. AQI -- Asset Quality Index (non-current, non-PP&E asset share).
        aqi_cur_base = 1 - ((tca_cur + ppe_cur) / ta_cur)
        aqi_prior_base = 1 - ((tca_prior + ppe_prior) / ta_prior)
        aqi = aqi_cur_base / aqi_prior_base if aqi_prior_base != 0 else None
        # 4. SGI -- Sales Growth Index.
        sgi = rev_cur / rev_prior
        # 5. DEPI -- Depreciation Index (>1 means depreciation rate SLOWED).
        dep_rate_cur = dep_cur / (dep_cur + ppe_cur) if (dep_cur + ppe_cur) != 0 else None
        dep_rate_prior = dep_prior / (dep_prior + ppe_prior) if (dep_prior + ppe_prior) != 0 else None
        depi = (dep_rate_prior / dep_rate_cur) if (dep_rate_cur not in (None, 0) and dep_rate_prior is not None) else None
        # 6. SGAI -- SG&A Index (Other Expenses used as the SG&A proxy).
        sgai = (sga_cur / rev_cur) / (sga_prior / rev_prior)
        # 7. TATA -- Total Accruals to Total Assets.
        tata = (pat_cur - ocf_cur) / ta_cur
        # 8. LVGI -- Leverage Index (simplified face-value Total Debt, Basis 1).
        def _debt_component(field):
            v = parsed.get(field)
            return (v[0] if v is not None and v[0] is not None else 0.0,
                    v[1] if v is not None and v[1] is not None else 0.0)
        lt_cur, lt_prior = _debt_component("lt_borrowings")
        st_cur, st_prior = _debt_component("st_borrowings")
        cm_cur, cm_prior = _debt_component("current_maturities")
        lease_nc_cur, lease_nc_prior = _debt_component("lease_liabilities_nc")
        lease_c_cur, lease_c_prior = _debt_component("lease_liabilities_cur")
        debt_cur = lt_cur + st_cur + cm_cur + lease_nc_cur + lease_c_cur
        debt_prior = lt_prior + st_prior + cm_prior + lease_nc_prior + lease_c_prior
        lvgi_cur_base = debt_cur / ta_cur
        lvgi_prior_base = debt_prior / ta_prior
        lvgi = lvgi_cur_base / lvgi_prior_base if lvgi_prior_base != 0 else None

        if gmi is None or aqi is None or depi is None or lvgi is None:
            out = {"applicable": False,
                   "reason": "One of the eight index variables (Gross Margin, Asset Quality, Depreciation, or "
                             "Leverage) is undefined for this company (a zero-value denominator in the prior "
                             "year) -- the M-Score cannot be computed.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        m_score = round(
            -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
            - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi, 3)

        equity_basis = parsed.get("equity_basis")
        pat_basis = parsed.get("pat_basis")
        ambiguous_nci = consolidated and (equity_basis != "owners" or pat_basis != "owners")
        confidence = 0.8 if ambiguous_nci else 1.0

        out = {
            "applicable": True,
            "value": m_score, "unit": "", "confidence": confidence,
            "estimated": ambiguous_nci,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "variables": {
                "DSRI": round(dsri, 3), "GMI": round(gmi, 3), "AQI": round(aqi, 3), "SGI": round(sgi, 3),
                "DEPI": round(depi, 3), "SGAI": round(sgai, 3), "TATA": round(tata, 3), "LVGI": round(lvgi, 3),
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report -- eight index variables (DSRI, GMI, AQI, SGI, DEPI, "
                    "SGAI, TATA, LVGI), each a current-year-vs-prior-year ratio, combined via Beneish's fixed "
                    "published coefficients. SG&A uses 'Other Expenses' as a proxy (Ind AS has no distinct "
                    "SG&A line); LVGI uses a simplified face-value Total Debt (Borrowings + Lease Liabilities, "
                    "Basis 1) computed consistently for both years, rather than the Notes-verified Sr No 20 "
                    "figure (no prior-year Notes cross-check is available). A flagged score is a prompt for "
                    "deeper forensic review, never proof of manipulation -- cross-check against OCF/Net Profit "
                    "(Sr No 41) for a corroborating earnings-quality signal.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
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


def _extract_bank_from_pdf(pdf_bytes, consolidated=True):
    """Extract Interest Earned/Interest Expended (P&L) and Advances/
    Investments (Balance Sheet) -- current + prior year each -- from a
    Bank/NBFC's own RBI-format Annual Report. Returns a dict or
    {'error': reason}. Never raises internally (caller wraps in try/except
    per the shared convention)."""
    try:
        import fitz
    except Exception as e:
        return {"error": f"pymupdf unavailable: {e}"}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return {"error": f"PDF read failed: {e}"}

    section = None
    want = "consolidated" if consolidated else "standalone"

    pl_idx, pl_text = None, None
    bs_idx, bs_text = None, None

    for i, page in enumerate(doc):
        if pl_idx is not None and bs_idx is not None:
            break
        try:
            t = _page_text(page)
        except Exception:
            continue
        tl = t.lower()

        # Narrow statement-caption anchors only -- mirrors the Schedule-III
        # extractor's own fix for TOC/Notes-page section-flip false
        # positives (never a bare "consolidated financial statements"
        # phrase, which also appears in the Table of Contents).
        if re.search(r"consolidated balance sheet\b", tl) or \
           re.search(r"consolidated profit and loss (account|statement)\b", tl):
            section = "consolidated"
        elif re.search(r"\bbalance sheet\b", tl) and "consolidated" not in tl[:200]:
            section = "standalone"
        elif re.search(r"profit and loss account\b", tl) and "consolidated" not in tl[:200]:
            section = "standalone"

        if section != want:
            continue

        if pl_idx is None and ("interest earned" in tl or "interest income" in tl) \
                and ("interest expended" in tl or "interest expense" in tl):
            pl_idx, pl_text = i, t

        if bs_idx is None and "advances" in tl and "investments" in tl \
                and ("capital and liabilities" in tl or "total assets" in tl or "total liabilities" in tl):
            bs_idx, bs_text = i, t

    if pl_text is None:
        return {"error": f"Could not find the {want} Profit and Loss Account (Interest Earned/Interest "
                          "Expended) in the Annual Report -- Bank/NBFC filings use the RBI-prescribed format, "
                          "which this parser is still being hardened against real-world layout variation."}
    if bs_text is None:
        return {"error": f"Could not find the {want} Balance Sheet (Advances/Investments) in the Annual "
                          "Report."}

    interest_income = _find_row_values(pl_text, _BANK_INTEREST_INCOME_LABELS)
    interest_expense = _find_row_values(pl_text, _BANK_INTEREST_EXPENSE_LABELS)
    advances = _find_row_values(bs_text, _BANK_ADVANCES_LABELS)
    investments = _find_row_values(bs_text, _BANK_INVESTMENTS_LABELS)
    total_deposits = _find_row_values(bs_text, _BANK_DEPOSITS_LABELS)
    # Cost-to-Income Ratio (Sr No 65) -- same P&L page as Interest Earned/
    # Expended, no separate forward scan needed.
    employee_cost = _find_row_values(pl_text, _BANK_EMPLOYEE_COST_LABELS)
    other_opex = _find_row_values(pl_text, _BANK_OTHER_OPEX_LABELS)
    other_income = _find_row_values(pl_text, _BANK_OTHER_INCOME_LABELS)

    # CASA Ratio (Sr No 59): Demand Deposits + Savings Bank Deposits live in
    # the Deposits Note/Schedule (RBI Schedule 3), not on the Balance Sheet
    # face itself -- a SEPARATE forward scan from the Balance Sheet page,
    # same "note lives pages later, not near bs_idx" pattern already used
    # for the Equity Share Capital note (Sr No 25). Bounded to the SAME
    # standalone/consolidated section as the Balance Sheet, re-tracked with
    # the same narrow caption anchors, so a Consolidated request never picks
    # up a Standalone-only Deposits Note (or a subsidiary's own).
    demand_deposits, savings_deposits = None, None
    dep_section = section  # section state as of the Balance Sheet page, continued forward
    for j in range(bs_idx, min(bs_idx + 200, len(doc))):
        try:
            pt = _page_text(doc[j])
        except Exception:
            continue
        ptl = pt.lower()
        if re.search(r"consolidated balance sheet\b", ptl) or \
           re.search(r"consolidated profit and loss (account|statement)\b", ptl):
            dep_section = "consolidated"
        elif re.search(r"\bbalance sheet\b", ptl) and "consolidated" not in ptl[:200]:
            dep_section = "standalone"
        if dep_section != want:
            continue
        if "demand deposits" in ptl and ("savings bank deposits" in ptl or "savings deposits" in ptl):
            demand_deposits = _find_row_values(pt, _BANK_DEMAND_DEPOSITS_LABELS)
            savings_deposits = _find_row_values(pt, _BANK_SAVINGS_DEPOSITS_LABELS)
            break

    # Gross NPA % (Sr No 60): the Asset Quality disclosure lives in Notes
    # to Accounts, mandated under RBI's IRAC norms -- another SEPARATE
    # forward scan from the Balance Sheet page, same pattern as the
    # Deposits Note above. Independent page from the Deposits Note, so
    # scanned separately rather than piggy-backing on that loop.
    gross_npa, net_npa, net_advances = None, None, None
    npa_section = section
    for k in range(bs_idx, min(bs_idx + 250, len(doc))):
        try:
            pt = _page_text(doc[k])
        except Exception:
            continue
        ptl = pt.lower()
        if re.search(r"consolidated balance sheet\b", ptl) or \
           re.search(r"consolidated profit and loss (account|statement)\b", ptl):
            npa_section = "consolidated"
        elif re.search(r"\bbalance sheet\b", ptl) and "consolidated" not in ptl[:200]:
            npa_section = "standalone"
        if npa_section != want:
            continue
        if any(lbl in ptl for lbl in _BANK_GROSS_NPA_LABELS):
            gross_npa = _find_row_values(pt, _BANK_GROSS_NPA_LABELS)
            if gross_npa is not None:
                # Net NPA (Sr No 61) is disclosed on the SAME Asset Quality
                # note page as Gross NPA in virtually every bank filing --
                # captured here, directly, rather than derived via a
                # Total-Provisions figure this parser doesn't separately
                # source (see the field's own docstring for the reasoning).
                net_npa = _find_row_values(pt, _BANK_NET_NPA_LABELS)
                net_advances = _find_row_values(pt, _BANK_NET_ADVANCES_LABELS)
                break

    # Capital Adequacy Ratio / CRAR (Sr No 63): the Basel III capital
    # disclosure lives in its own Notes-to-Accounts section -- another
    # SEPARATE forward scan from the Balance Sheet page.
    tier1_capital, tier2_capital, rwa, crar_direct = None, None, None, None
    crar_section = section
    for m in range(bs_idx, min(bs_idx + 250, len(doc))):
        try:
            pt = _page_text(doc[m])
        except Exception:
            continue
        ptl = pt.lower()
        if re.search(r"consolidated balance sheet\b", ptl) or \
           re.search(r"consolidated profit and loss (account|statement)\b", ptl):
            crar_section = "consolidated"
        elif re.search(r"\bbalance sheet\b", ptl) and "consolidated" not in ptl[:200]:
            crar_section = "standalone"
        if crar_section != want:
            continue
        has_tier = any(lbl in ptl for lbl in _BANK_TIER1_CAPITAL_LABELS) and \
            any(lbl in ptl for lbl in _BANK_RWA_LABELS)
        has_direct = any(lbl in ptl for lbl in _BANK_CRAR_DIRECT_LABELS)
        if has_tier or has_direct:
            tier1_capital = _find_row_values(pt, _BANK_TIER1_CAPITAL_LABELS)
            tier2_capital = _find_row_values(pt, _BANK_TIER2_CAPITAL_LABELS)
            rwa = _find_row_values(pt, _BANK_RWA_LABELS)
            crar_direct = _find_row_values(pt, _BANK_CRAR_DIRECT_LABELS)
            if tier1_capital is not None or crar_direct is not None:
                break

    return {
        "interest_income": interest_income,   # (cur, prior) or None, normalised to Rs Cr
        "interest_expense": interest_expense,  # (cur, prior) or None, normalised to Rs Cr
        # NOTE (flagged, unresolved): the RBI Schedule 9 Balance Sheet face
        # line "Advances" is CONVENTIONALLY presented net of provisions in
        # many bank filings, not gross -- this field's true basis (gross vs
        # net) has NOT been verified against a real filing yet. Sr No 61
        # deliberately does NOT reuse this field for its Net Advances
        # component (see `net_advances` below, searched directly instead)
        # to avoid compounding that ambiguity. Revisit once tested live.
        "advances": advances,                 # (cur, prior) or None, normalised to Rs Cr -- basis unverified
        "investments": investments,           # (cur, prior) or None, normalised to Rs Cr
        "total_deposits": total_deposits,     # (cur, prior) or None, normalised to Rs Cr -- Sr No 59 denominator
        "demand_deposits": demand_deposits,   # (cur, prior) or None, normalised to Rs Cr -- Sr No 59 numerator (a)
        "savings_deposits": savings_deposits,  # (cur, prior) or None, normalised to Rs Cr -- Sr No 59 numerator (b)
        "gross_npa": gross_npa,               # (cur, prior) or None, normalised to Rs Cr -- Sr No 60 numerator
        "net_npa": net_npa,                   # (cur, prior) or None, normalised to Rs Cr -- Sr No 61 numerator
        "net_advances": net_advances,         # (cur, prior) or None, normalised to Rs Cr -- Sr No 61 denominator
        "tier1_capital": tier1_capital,       # (cur, prior) or None, Rs Cr -- Sr No 63 numerator (a)
        "tier2_capital": tier2_capital,       # (cur, prior) or None, Rs Cr -- Sr No 63 numerator (b)
        "rwa": rwa,                           # (cur, prior) or None, Rs Cr -- Sr No 63 denominator
        "crar_direct": crar_direct,           # (cur, prior) or None, % -- Sr No 63 fallback (directly disclosed)
        "employee_cost": employee_cost,       # (cur, prior) or None, Rs Cr -- Sr No 65 numerator (a)
        "other_opex": other_opex,             # (cur, prior) or None, Rs Cr -- Sr No 65 numerator (b)
        "other_income": other_income,         # (cur, prior) or None, Rs Cr -- Sr No 65 denominator component
        "pl_page": pl_idx + 1, "bs_page": bs_idx + 1,
    }


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
    ckey = f"ar_bank_extract_v6_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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
    """
    Net Interest Margin (Sr No 58) = (Interest Income - Interest Expense) /
    Average Interest-Earning Assets (Advances + Investments, opening+
    closing average). The FIRST ratio in this suite sourced from a Bank/
    NBFC's own RBI-format Annual Report, via the new `_extract_bank_from_pdf`
    parser (see its own docstring for the "known first-pass limitation"
    note -- expect this to need hardening against a wider range of real
    bank filings, same as every Schedule-III ratio needed early on).

    Advances is used as GROSS Advances (before provisions), per spec.

    Per spec, N/A if Average Interest-Earning Assets = 0.

    Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_nim_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_bank_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        interest_income = parsed.get("interest_income")
        if interest_income is None:
            out = {"applicable": False, "reason": "Could not find an 'Interest Earned'/'Interest Income' row "
                                                    "on the Profit and Loss Account page.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        interest_expense = parsed.get("interest_expense")
        if interest_expense is None:
            out = {"applicable": False, "reason": "Could not find an 'Interest Expended'/'Interest Expense' "
                                                    "row on the Profit and Loss Account page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        advances = parsed.get("advances")
        investments = parsed.get("investments")
        if advances is None and investments is None:
            out = {"applicable": False, "reason": "Could not find 'Advances' or 'Investments' rows on the "
                                                    "Balance Sheet page.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ii_cur, _ii_prior = interest_income
        ie_cur, _ie_prior = interest_expense
        adv_cur = advances[0] if advances is not None else 0.0
        adv_prior = advances[1] if advances is not None else 0.0
        inv_cur = investments[0] if investments is not None else 0.0
        inv_prior = investments[1] if investments is not None else 0.0

        iea_cur = adv_cur + inv_cur
        iea_prior = adv_prior + inv_prior
        avg_iea = round((iea_cur + iea_prior) / 2, 2)

        if avg_iea == 0:
            out = {"applicable": False, "reason": "Average Interest-Earning Assets is zero.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        net_interest_income = round(ii_cur - ie_cur, 2)
        nim = round((net_interest_income / avg_iea) * 100, 2)

        confidence = 1.0 if (advances is not None and investments is not None) else 0.95

        out = {
            "applicable": True,
            "value": nim, "unit": "%",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Net Interest Income (Interest Earned - Interest Expended)",
                "value_cr": net_interest_income,
                "components": {
                    "Interest Earned": round(ii_cur, 2),
                    "less: Interest Expended": round(ie_cur, 2),
                },
            },
            "denominator": {
                "label": "Average Interest-Earning Assets (Advances + Investments)",
                "value_cr": avg_iea,
                "components": {
                    "Advances (Gross)": round(adv_cur, 2) if advances is not None else None,
                    "Investments": round(inv_cur, 2) if investments is not None else None,
                },
            },
            "sources": _page_sources(pdf_url, fiscal_year, parsed.get("pl_page"), parsed.get("bs_page")),
            "note": "From the company's own Annual Report (RBI-prescribed Bank/NBFC format) -- (Interest "
                    "Earned - Interest Expended) / Average Interest-Earning Assets (Gross Advances + "
                    "Investments, opening+closing average). Excludes Other/Fee Income from the numerator and "
                    "non-earning assets (fixed assets, cash reserves) from the denominator, per spec.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}



def fetch_casa_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    CASA Ratio (Sr No 59) = (Demand Deposits + Savings Bank Deposits) /
    Total Deposits -- a Bank-only ratio (per spec, NBFCs typically don't
    take retail deposits, so this is narrower than Net Interest Margin's
    Bank+NBFC applicability). Demand Deposits and Savings Bank Deposits
    come from the RBI Schedule 3 Deposits Note/breakup (found via a
    forward scan from the Balance Sheet page in `_extract_bank_from_pdf`);
    Total Deposits is the Balance Sheet face line itself.

    Per spec, Term Deposits are NEVER included in the numerator -- only
    the two genuinely low/no-cost components.

    Per spec, N/A if Total Deposits = 0.

    Reuses the SAME cached bank-statement extraction as Net Interest
    Margin (Sr No 58) -- no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_casa_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_bank_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        total_deposits = parsed.get("total_deposits")
        if total_deposits is None:
            out = {"applicable": False, "reason": "Could not find a 'Deposits' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        demand_deposits = parsed.get("demand_deposits")
        savings_deposits = parsed.get("savings_deposits")
        if demand_deposits is None and savings_deposits is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Demand Deposits'/'Savings Bank Deposits' in the Deposits Note "
                             "(RBI Schedule 3).",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        td_cur, _td_prior = total_deposits
        if td_cur == 0:
            out = {"applicable": False, "reason": "Total Deposits is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        dd_cur = demand_deposits[0] if demand_deposits is not None else 0.0
        sd_cur = savings_deposits[0] if savings_deposits is not None else 0.0
        casa_cur = round(dd_cur + sd_cur, 2)
        casa_ratio = round((casa_cur / td_cur) * 100, 2)

        confidence = 1.0 if (demand_deposits is not None and savings_deposits is not None) else 0.95

        casa_components = {}
        if demand_deposits is not None:
            casa_components["Demand Deposits (Current Account)"] = round(dd_cur, 2)
        if savings_deposits is not None:
            casa_components["Savings Bank Deposits"] = round(sd_cur, 2)

        out = {
            "applicable": True,
            "value": casa_ratio, "unit": "%",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "CASA (Demand Deposits + Savings Bank Deposits)",
                "value_cr": casa_cur,
                "components": casa_components,
            },
            "denominator": {"label": "Total Deposits", "value_cr": round(td_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report (RBI-prescribed Bank format, Schedule 3 Deposits "
                    "Note) -- (Demand Deposits + Savings Bank Deposits) / Total Deposits. Term Deposits are "
                    "NEVER included in the numerator -- they are the higher-cost complement, not part of "
                    "CASA. Cross-check the trend against Net Interest Margin (Sr No 58): a declining CASA "
                    "alongside compressing NIM is a consistent rising-funding-cost story.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}



def fetch_gross_npa_pct_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Gross NPA % (Sr No 60) = Gross Non-Performing Assets / Gross Advances.
    Gross NPA comes from the RBI IRAC-norms Asset Quality disclosure in
    Notes to Accounts (found via a forward scan from the Balance Sheet
    page in `_extract_bank_from_pdf`); Gross Advances reuses the SAME
    `advances` field already extracted for Net Interest Margin (Sr No 58)
    -- both are the pre-provision, gross figure, never Net Advances.

    Per spec, NEVER use Net NPA (Sr No 61, a distinct, always-lower,
    post-provision figure) in place of Gross NPA.

    Per spec, N/A if Gross Advances = 0.

    Reuses the SAME cached bank-statement extraction as Net Interest
    Margin/CASA Ratio -- no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_gnpa_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_bank_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        advances = parsed.get("advances")
        if advances is None:
            out = {"applicable": False, "reason": "Could not find a 'Advances'/'Gross Advances' row on the "
                                                    "Balance Sheet page.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        gross_npa = parsed.get("gross_npa")
        if gross_npa is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Gross Non-Performing Assets' row in the Asset Quality Notes "
                             "to Accounts.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        adv_cur, _adv_prior = advances
        if adv_cur == 0:
            out = {"applicable": False, "reason": "Gross Advances is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        gnpa_cur, _gnpa_prior = gross_npa
        gnpa_pct = round((gnpa_cur / adv_cur) * 100, 2)

        out = {
            "applicable": True,
            "value": gnpa_pct, "unit": "%",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Gross Non-Performing Assets", "value_cr": round(gnpa_cur, 2)},
            "denominator": {"label": "Gross Advances", "value_cr": round(adv_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report (RBI-prescribed Bank/NBFC format, Asset Quality "
                    "Notes to Accounts, IRAC norms) -- Gross Non-Performing Assets / Gross Advances (both "
                    "pre-provision). Never Net NPA (Sr No 61, a distinct, always-lower figure) or Net "
                    "Advances. Cross-check against Provision Coverage Ratio (Sr No 62) and Net NPA % (Sr No "
                    "61) -- a rising Gross NPA alongside a flat/falling PCR is a compounding risk signal.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}



def fetch_net_npa_pct_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Net NPA % (Sr No 61) = Net Non-Performing Assets / Net Advances.
    Both figures are read DIRECTLY from the Asset Quality Notes to
    Accounts (`net_npa`/`net_advances` fields, found on the SAME page as
    Gross NPA/Sr No 60 in `_extract_bank_from_pdf`), rather than derived
    via a "Total Provisions" subtraction -- bank filings virtually always
    disclose Net NPA and Net Advances as their own explicit lines in the
    Asset Quality table, so reading them directly avoids sourcing a
    Total-Provisions figure this parser doesn't separately extract.

    Per spec, NEVER use Gross NPA (Sr No 60) or the ambiguous Balance-
    Sheet-face `advances` field here.

    Per spec, N/A if Net Advances = 0.

    Reuses the SAME cached bank-statement extraction as Net Interest
    Margin/CASA Ratio/Gross NPA % -- no extra download. Cached 90 days.
    Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_nnpa_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_bank_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        net_advances = parsed.get("net_advances")
        if net_advances is None:
            out = {"applicable": False, "reason": "Could not find a 'Net Advances' row in the Asset Quality "
                                                    "Notes to Accounts.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        net_npa = parsed.get("net_npa")
        if net_npa is None:
            out = {"applicable": False,
                   "reason": "Could not find a 'Net Non-Performing Assets' row in the Asset Quality Notes to "
                             "Accounts.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        na_cur, _na_prior = net_advances
        if na_cur == 0:
            out = {"applicable": False, "reason": "Net Advances is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        nnpa_cur, _nnpa_prior = net_npa
        nnpa_pct = round((nnpa_cur / na_cur) * 100, 2)

        out = {
            "applicable": True,
            "value": nnpa_pct, "unit": "%",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {"label": "Net Non-Performing Assets", "value_cr": round(nnpa_cur, 2)},
            "denominator": {"label": "Net Advances", "value_cr": round(na_cur, 2)},
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report (RBI-prescribed Bank/NBFC format, Asset Quality "
                    "Notes to Accounts) -- Net Non-Performing Assets / Net Advances, both read directly as "
                    "their own disclosed lines (never derived by subtracting a separately-sourced Total "
                    "Provisions figure). A Net NPA % meaningfully lower than Gross NPA % (Sr No 60) indicates "
                    "conservative provisioning (high Provision Coverage Ratio, Sr No 62); a Net NPA % close "
                    "to Gross NPA % signals under-provisioning.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}



def fetch_capital_adequacy_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Capital Adequacy Ratio / CRAR (Sr No 63) = (Tier I Capital + Tier II
    Capital) / Total Risk-Weighted Assets (RWA) -- the Basel III capital
    adequacy disclosure in Notes to Accounts.

    PRIMARY basis: Tier I + Tier II Capital, computed directly against RWA
    (confidence 1.0). FALLBACK: many banks' Basel III Pillar 3 tables
    disclose the combined "CRAR (%)" figure directly without a clean
    Tier I/Tier II split visible to a face-value text scan -- when the two
    capital tiers aren't individually found, the directly-reported CRAR %
    is used as-is (confidence 0.95 -- the reported figure itself, not a
    recomputation, so still faithful, just without a numerator/denominator
    breakdown to show).

    Per spec, N/A if RWA = 0 (and no direct CRAR % fallback is available).

    Reuses the SAME cached bank-statement extraction as the other Bank/
    NBFC ratios -- no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_crar_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_bank_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tier1 = parsed.get("tier1_capital")
        tier2 = parsed.get("tier2_capital")
        rwa = parsed.get("rwa")

        if tier1 is not None and rwa is not None and rwa[0] != 0:
            t1_cur, _t1_prior = tier1
            t2_cur = tier2[0] if tier2 is not None else 0.0
            rwa_cur, _rwa_prior = rwa
            total_capital_cur = round(t1_cur + t2_cur, 2)
            crar = round((total_capital_cur / rwa_cur) * 100, 2)

            out = {
                "applicable": True,
                "value": crar, "unit": "%",
                "confidence": 1.0,
                "estimated": False,
                "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                "numerator": {
                    "label": "Tier I + Tier II Capital",
                    "value_cr": total_capital_cur,
                    "components": {
                        "Tier I Capital": round(t1_cur, 2),
                        "Tier II Capital": round(t2_cur, 2) if tier2 is not None else None,
                    },
                },
                "denominator": {"label": "Total Risk-Weighted Assets (RWA)", "value_cr": round(rwa_cur, 2)},
                "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                "note": "From the company's own Annual Report (RBI-prescribed Bank/NBFC format, Basel III "
                        "Capital Adequacy Notes to Accounts) -- (Tier I Capital + Tier II Capital) / Total "
                        "Risk-Weighted Assets, never gross Total Assets. Read alongside Credit-to-Deposit "
                        "Ratio -- rapid loan growth without corresponding capital raises will mechanically "
                        "compress CRAR. RBI's minimum requirement is periodically revised -- verify the "
                        "current applicable threshold rather than assuming a fixed historical one.",
            }
            _write_cache(ckey, out)
            return out

        crar_direct = parsed.get("crar_direct")
        if crar_direct is not None:
            crar_cur, _crar_prior = crar_direct
            out = {
                "applicable": True,
                "value": round(crar_cur, 2), "unit": "%",
                "confidence": 0.95,
                "estimated": True,
                "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                "numerator": {"label": "CRAR (directly disclosed, Tier I/II split not separately located)",
                              "value_cr": round(crar_cur, 2)},
                "denominator": None,
                "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                "note": "From the company's own Annual Report -- the directly-disclosed 'CRAR (%)'/'Capital "
                        "Adequacy Ratio (%)' figure from the Basel III Pillar 3 table, used as-is because the "
                        "individual Tier I/Tier II Capital and Risk-Weighted Assets figures could not be "
                        "separately located as clean line items -- this is the company's own reported "
                        "number, not a recomputation, but without a numerator/denominator breakdown.",
            }
            _write_cache(ckey, out)
            return out

        out = {"applicable": False,
               "reason": "Could not find Tier I/Tier II Capital and Risk-Weighted Assets, or a directly "
                         "disclosed CRAR %, in the Basel III Capital Adequacy Notes to Accounts.",
               "source_url": pdf_url}
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}



def fetch_cost_to_income_ratio_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Cost-to-Income Ratio (Sr No 65) = Operating Expenses (Employee Cost +
    Other Operating Expenses) / (Net Interest Income + Other Income).
    Net Interest Income reuses the SAME Interest Income/Interest Expense
    fields already extracted for Net Interest Margin (Sr No 58) --
    Interest Income minus Interest Expense, per that ratio's own basis.

    Per spec, Operating Expenses NEVER includes Provisions for NPAs or
    Tax -- only Employee Cost + Other Operating Expenses, the two lines
    the RBI Form B P&L discloses under "Operating Expenses".

    Per spec, N/A if (Net Interest Income + Other Income) <= 0.

    Reuses the SAME cached bank-statement extraction as the other Bank/
    NBFC ratios -- no extra download. Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_cir_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        parsed = _get_extracted_bank_financials(sym, name, fiscal_year, consolidated)
        pdf_url = parsed.get("source_url")
        if "error" in parsed:
            out = {"applicable": False, "reason": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        interest_income = parsed.get("interest_income")
        interest_expense = parsed.get("interest_expense")
        if interest_income is None or interest_expense is None:
            missing = "Interest Earned/Interest Income" if interest_income is None else \
                "Interest Expended/Interest Expense"
            out = {"applicable": False, "reason": f"Could not find '{missing}' on the Profit and Loss Account "
                                                    "page.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        employee_cost = parsed.get("employee_cost")
        other_opex = parsed.get("other_opex")
        if employee_cost is None and other_opex is None:
            out = {"applicable": False,
                   "reason": "Could not find 'Employees Cost'/'Other Operating Expenses' rows on the Profit "
                             "and Loss Account page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        other_income = parsed.get("other_income")

        ii_cur, _ii_prior = interest_income
        ie_cur, _ie_prior = interest_expense
        emp_cur = employee_cost[0] if employee_cost is not None else 0.0
        opex_cur = other_opex[0] if other_opex is not None else 0.0
        oi_cur = other_income[0] if other_income is not None else 0.0

        nii_cur = ii_cur - ie_cur
        income_base_cur = round(nii_cur + oi_cur, 2)
        operating_expenses_cur = round(emp_cur + opex_cur, 2)

        if income_base_cur <= 0:
            out = {"applicable": False,
                   "reason": "Net Interest Income plus Other Income is zero or negative -- Cost-to-Income "
                             "Ratio is not meaningful.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Operating Expenses", "value_cr": operating_expenses_cur},
                   "denominator": {"label": "Net Interest Income + Other Income", "value_cr": income_base_cur},
                   "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cir = round((operating_expenses_cur / income_base_cur) * 100, 2)
        confidence = 1.0 if (employee_cost is not None and other_opex is not None) else 0.95

        out = {
            "applicable": True,
            "value": cir, "unit": "%",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Operating Expenses (Employee Cost + Other Operating Expenses)",
                "value_cr": operating_expenses_cur,
                "components": {
                    "Employee Cost": round(emp_cur, 2) if employee_cost is not None else None,
                    "Other Operating Expenses": round(opex_cur, 2) if other_opex is not None else None,
                },
            },
            "denominator": {
                "label": "Net Interest Income + Other Income",
                "value_cr": income_base_cur,
                "components": {
                    "Net Interest Income (Interest Earned - Interest Expended)": round(nii_cur, 2),
                    "Other Income": round(oi_cur, 2) if other_income is not None else None,
                },
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report (RBI-prescribed Bank/NBFC format) -- Operating "
                    "Expenses (Employee Cost + Other Operating Expenses, NEVER Provisions or Tax) / (Net "
                    "Interest Income + Other Income). Cross-check the trend against Net Interest Margin (Sr "
                    "No 58) -- a bank improving Cost-to-Income while NIM compresses may be cutting costs to "
                    "offset margin pressure rather than genuinely improving efficiency.",
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[annual_report_financials] {ckey} failed: {e}")
        return {"applicable": False, "reason": "Something went wrong reading the Annual Report -- please try again."}
