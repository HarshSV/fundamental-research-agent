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

try:
    from tools import ssl_bootstrap  # noqa: F401
except Exception:
    pass

from tools.bse_scraper import _sess, _resolve_scrip_code, _read_cache, _write_cache

CACHE_TTL = 90 * 24 * 3600

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
    "attributable to owners of the company",
    "attributable to owners of the parent",
    "attributable to the owners of the company",
    "attributable to shareholders of the company",
]
_PAT_GENERIC_LABELS = [
    "profit for the year", "profit for the period", "profit after tax",
    "net profit for the year", "net profit for the period",
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
_PBT_LABELS = [
    "profit before exceptional items and tax", "profit before tax and exceptional items",
    "profit before tax", "profit before exceptional item and tax",
]
_FINANCE_COST_LABELS = [
    "finance costs", "finance cost", "interest expense", "interest and finance charges",
    "interest on borrowings",
]
# Total Debt (Sr No 20 numerator) = Long-term + Short-term borrowings +
# Current maturities of long-term debt — ALL interest-bearing, never Trade
# Payables/Provisions. Lease liabilities are deliberately NOT included by
# default (spec: "decide explicitly and flag which convention is used" —
# this reader doesn't attempt to distinguish lease-liability sub-notes from
# genuine borrowings, so it sticks to the conservative "borrowings only"
# reading rather than guess).
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
_CASH_LABELS = [
    "cash and cash equivalents", "cash and bank balances", "balances with banks",
    "cash on hand", "cash & cash equivalents",
]
# "Other Bank Balances" (e.g. fixed deposits with banks, margin money, unpaid
# dividend accounts, escrow balances) is a SEPARATE Balance Sheet line from
# Cash and Cash Equivalents. Per spec, only its UNRESTRICTED portion (e.g.
# freely-available bank deposits) belongs in the Cash Ratio numerator — the
# restricted portion (unpaid dividend/margin money/escrow) must be excluded.
# A Balance Sheet line total can't be split into restricted/unrestricted
# without reading its Notes-to-Accounts breakup, which this PDF-text parser
# doesn't attempt (too unreliable to guess at without real note-level
# extraction) — so this is surfaced as an informational figure only, never
# silently folded into the numerator.
_OTHER_BANK_BALANCES_LABELS = [
    "other bank balances", "bank balances other than cash and cash equivalents",
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
    if re.search(r"\bmillion\b", text, re.I):
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


def _find_row_values(text, canonical_names, after=None):
    """Find a row by any of its canonical label variants and return
    (current_year_value, prior_year_value) — the two trailing numbers on that
    logical line — or None. Case-insensitive, tries each synonym in order.

    `after`: an optional regex; if given, the search starts AFTER the first
    match of it. Used for Trade Receivables, which the Balance Sheet often
    lists twice (a small long-term portion under Non-Current Assets, then the
    real circulating balance under Current Assets) — without this, the first
    (wrong, non-current) occurrence would win."""
    search_text = text
    if after:
        m = re.search(after, text, re.I)
        if m:
            search_text = text[m.end():]
    for name in canonical_names:
        m = re.search(re.escape(name), search_text, re.I)
        if not m:
            continue
        window = search_text[m.end():m.end() + 250]
        nums = re.findall(_NUM_RE, window)
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


def _find_payables(text, after=None):
    """Trade Payables under Current Liabilities. Ind AS Schedule III requires
    the MSME/non-MSME split disclosed as separate sub-items (a)/(b), often
    plus (c) Acceptances, with NO single total row before the next item
    (typically '(iv) Derivative liabilities' or '(iv)/(v) Other financial
    liabilities') — sum every row in between instead."""
    return _sum_after_label(text, _PAYABLES_LABELS,
                             r"derivative\s+liabilities|other\s+financial\s+liabilities|\(iv\)",
                             after=after)


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
    """All fiscal years (as ints) BSE has an Annual Report for, newest first,
    deduplicated. Never raises."""
    try:
        code = _resolve_scrip_code(symbol, name)
        if not code:
            return []
        s = _sess()
        r = s.get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}", timeout=25)
        rows = json.loads(r.text).get("Table", []) or []
        years = sorted({int(row["Year"]) for row in rows if str(row.get("Year", "")).isdigit()}, reverse=True)
        return years
    except Exception as e:
        print(f"[annual_report_financials] year list failed for {symbol}: {e}")
        return []


def _find_annual_report_pdf(symbol, name, year):
    """BSE's AnnualReport_New API, filtered to the given fiscal year (e.g. 2024
    for FY ended March 2024). Returns the PDF URL or None."""
    try:
        code = _resolve_scrip_code(symbol, name)
        if not code:
            return None
        s = _sess()
        r = s.get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}", timeout=25)
        rows = json.loads(r.text).get("Table", []) or []
        for row in rows:
            if str(row.get("Year")) == str(year):
                url = row.get("PDFDownload")
                if url and url.startswith("http"):
                    return url
        return None
    except Exception as e:
        print(f"[annual_report_financials] lookup failed for {symbol} {year}: {e}")
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
            t = page.get_text() or ""
        except Exception:
            continue
        tl = t.lower()
        if "consolidated financial statements" in tl or "consolidated balance sheet" in tl \
           or "consolidated statement of profit" in tl:
            section = "consolidated"
        elif "standalone financial statements" in tl or "standalone balance sheet" in tl \
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
        if pl_cogs_idx is None:
            if all(_find_row_values(t, names) is not None for names in _COGS_LABELS.values()):
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
            elif pl_shape_idx is None and not is_cash_flow_page \
                    and "statement of profit and loss" in tl and _find_revenue(t) is not None \
                    and "other income" in tl \
                    and any(k in tl for k in ("employee benefit", "finance cost", "depreciation and amortisation")):
                pl_shape_idx, pl_shape_text = i, t
        if bs_inv_idx is None and not is_cash_flow_page:
            has_non_current_marker = "property, plant and equipment" in tl or "non-current assets" in tl
            if _find_row_values(t, _INVENTORY_LABELS) is not None and has_non_current_marker:
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
    # _OTHER_BANK_BALANCES_LABELS comment): its restricted/unrestricted split
    # isn't determinable from the statement page alone.
    other_bank_balances = _scale(_find_row_values(bs_text, _OTHER_BANK_BALANCES_LABELS,
                                                   after=r"\nCurrent Assets\b"), bs_factor)
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
            next_text = doc[bs_idx + 1].get_text() or ""
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
        avoids that misread; they never carry real data themselves."""
        return re.sub(r"\([IVXLCM]+(?:\s*[+\-]\s*[IVXLCM]+)+\)", "", text, flags=re.I)

    def _find_pl_row(labels, after=None):
        """Find a P&L row on the primary pl_text page, falling back to the
        immediately following page — the bottom-line Profit figure often sits
        on a SECOND page of the same statement (Revenue/expenses down to
        Profit Before Tax on page 1, Profit For The Year + OCI + EPS on page
        2), unlike the COGS/Revenue rows which are always on page 1."""
        raw = _find_row_values(_strip_formula_refs(pl_text), labels, after=after)
        factor = pl_factor
        if raw is None and pl_idx + 1 < doc.page_count:
            try:
                next_text = _strip_formula_refs(doc[pl_idx + 1].get_text() or "")
                raw = _find_row_values(next_text, labels, after=after)
                factor = _unit_factor(next_text)
            except Exception:
                pass
        return _scale(raw, factor)

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
    finance_costs = _find_pl_row(_FINANCE_COST_LABELS)

    def _find_bs_row(labels, after=None, subtotal_before=None):
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
            v = _find_row_values(text, labels, after=after)
            if v is None and subtotal_before:
                v = _find_subtotal_before(text, subtotal_before, after=after)
            return v
        raw = _try(bs_text)
        factor = bs_factor
        if raw is None and bs_idx + 1 < doc.page_count:
            try:
                next_text = doc[bs_idx + 1].get_text() or ""
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

    def _find_single_label_loose(segment, label):
        """Find ONE label's (current, prior) pair in `segment`, tolerating a
        BARE 1-3 digit value with no comma/decimal (e.g. "331") that `_NUM_RE`
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
        REGEX used to locate candidates was the problem)."""
        m = re.search(re.escape(label), segment, re.I)
        if not m:
            return None
        window = segment[m.end():m.end() + 250]
        lines = [ln.strip() for ln in window.split("\n") if ln.strip()]
        i = 0
        while i < len(lines) and re.fullmatch(r"\d{1,4}(-\d{1,4})?", lines[i]):
            i += 1
        if i + 1 < len(lines):
            a, b = _parse_num(lines[i]), _parse_num(lines[i + 1])
            if a is not None and b is not None:
                return (a, b)
        return _find_row_values(segment, [label])

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
                next_text = doc[bs_idx + 1].get_text() or ""
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

    # Total Equity (Sr No 18 denominator): owners-attributable portion tried
    # first (consolidated statements ALSO print a combined "Total equity"
    # including Non-Controlling Interest, which per spec must be excluded);
    # falls back to the generic "Total equity"/"Shareholders' funds" labels
    # for standalone reports with no NCI split, where that IS the owners'
    # figure.
    equity = _find_bs_row(_EQUITY_OWNERS_LABELS)
    equity_basis = "owners" if equity is not None else None
    if equity is None:
        equity = _find_bs_row(_EQUITY_GENERIC_LABELS)
        equity_basis = "generic" if equity is not None else None

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

    return {
        "components": components,    # {label: (cur, prior)} — may be partial/empty, normalised to ₹ Cr
        "inventory": inv,            # (cur, prior) or None, normalised to ₹ Cr
        "revenue": revenue,          # (cur, prior) or None, normalised to ₹ Cr
        "receivables": receivables,  # (cur, prior) or None
        "payables": payables,        # (cur, prior) or None
        "cash": cash,                # (cur, prior) or None, normalised to ₹ Cr
        "other_bank_balances": other_bank_balances,  # (cur, prior) or None — informational only, see comment above
        "employee_benefit_expense": employee_benefit_expense,  # (cur, prior) or None, normalised to ₹ Cr
        "other_expenses": other_expenses,  # (cur, prior) or None, normalised to ₹ Cr
        "pat": pat,  # (cur, prior) or None, normalised to ₹ Cr — owners-attributable Profit After Tax
        "pat_basis": pat_basis,  # "owners" (explicit attribution line found) or "generic" (no NCI split found)
        "pbt": pbt,  # (cur, prior) or None, normalised to ₹ Cr — Profit Before Tax
        "finance_costs": finance_costs,  # (cur, prior) or None, normalised to ₹ Cr
        "lt_borrowings": lt_borrowings,  # (cur, prior) or None, normalised to ₹ Cr
        "st_borrowings": st_borrowings,  # (cur, prior) or None, normalised to ₹ Cr
        "current_maturities": current_maturities,  # (cur, prior) or None, normalised to ₹ Cr
        "total_assets": total_assets,  # (cur, prior) or None, normalised to ₹ Cr
        "total_current_assets": total_current_assets,           # (cur, prior) or None, normalised to ₹ Cr
        "total_current_liabilities": total_current_liabilities,  # (cur, prior) or None, normalised to ₹ Cr
        "equity": equity,  # (cur, prior) or None, normalised to ₹ Cr — owners-attributable Total Equity
        "equity_basis": equity_basis,  # "owners" (explicit exclusion of NCI found) or "generic" (no NCI split found)
        "pl_page": pl_idx + 1, "bs_page": bs_idx + 1,
    }


def _get_extracted_financials(symbol, name, fiscal_year, consolidated=True):
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
    ckey = f"ar_extract_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached
    try:
        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            out = {"error": "Annual Report not found for this year."}
            _write_cache(ckey, out)
            return out

        # Retry the download itself (large PDFs, 10-30MB, occasionally hit a
        # transient network blip) before giving up.
        content = None
        last_exc = None
        for attempt in range(2):
            try:
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
        if "error" in parsed:
            out = {"error": parsed["error"], "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        parsed["source_url"] = pdf_url
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
    Operating Profit Margin (EBITDA-basis) = (Revenue − COGS − Employee
    Benefit Expense − Other Expenses) ÷ Revenue. Per spec this is the
    EBITDA-basis definition (Screener convention) — excludes Depreciation &
    Amortisation and Finance Costs, and per spec must NEVER include Other
    Income or Exceptional Items. COGS reuses the SAME (a+b+c) components
    validated for Inventory Turnover/Gross Profit Margin (Sr No 1/14); this
    additionally needs Employee Benefit Expense and Other Expenses, which
    Gross Profit Margin doesn't. Point-in-time (current year only, no
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
        if rev_cur == 0:
            out = {"applicable": False, "reason": "Revenue from operations is zero.", "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        cogs_cur = sum(v[0] for v in components.values())
        ebe_cur, _ebe_prior = ebe
        oe_cur, _oe_prior = oe
        operating_profit = rev_cur - cogs_cur - ebe_cur - oe_cur
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
                "label": "Operating Profit / EBITDA (Revenue − COGS − Employee Costs − Other Expenses)",
                "value_cr": round(operating_profit, 2),
                "components": {
                    "Revenue from Operations": round(rev_cur, 2),
                    **{f"less: {k}": round(v[0], 2) for k, v in components.items()},
                    "less: Employee Benefit Expense": round(ebe_cur, 2),
                    "less: Other Expenses": round(oe_cur, 2),
                },
            },
            "denominator": {
                "label": "Revenue from Operations",
                "value_cr": round(rev_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, pl_page=parsed.get("pl_page")),
            "note": "From the company's own Annual Report — EBITDA-basis Operating Profit (Screener convention): "
                    "Revenue from Operations minus all operating expense lines (COGS a+b+c + Employee Benefit "
                    "Expense + Other Expenses), excluding Depreciation, Finance Costs, Other Income and "
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

        pbt = parsed.get("pbt")
        finance_costs = parsed.get("finance_costs")
        if pbt is None:
            out = {"applicable": False, "reason": "Could not find a 'Profit before tax' row on the P&L page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out
        if finance_costs is None:
            out = {"applicable": False, "reason": "Could not find a 'Finance Costs' row on the P&L page.",
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

        pbt_cur, _pbt_prior = pbt
        fc_cur, _fc_prior = finance_costs
        ebit_cur = pbt_cur + fc_cur

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
                   "numerator": {"label": "EBIT (Profit Before Tax + Finance Costs)", "value_cr": round(ebit_cur, 2)},
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
                "label": "EBIT (Profit Before Tax + Finance Costs)",
                "value_cr": round(ebit_cur, 2),
                "components": {
                    "Profit Before Tax": round(pbt_cur, 2),
                    "+ Finance Costs": round(fc_cur, 2),
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


def fetch_debt_to_equity_from_annual_report(symbol, name, fiscal_year, consolidated=True):
    """
    Debt-to-Equity = Total Debt ÷ Total Equity (owners-attributable), BOTH at
    CLOSING balance — unlike ROE/ROCE, this is point-in-time (like Current
    Ratio), never averaged.

    Total Debt = Long-term Borrowings + Short-term Borrowings + Current
    Maturities of Long-term Debt — ALL interest-bearing, never Trade
    Payables/Provisions. Each component may be genuinely absent for a
    debt-free (or partially debt-free) company — summed individually rather
    than requiring all three, same "sum what's there" principle just applied
    to Inventory Turnover/Gross Profit Margin/Payables Turnover. Lease
    liabilities are deliberately EXCLUDED (per spec: "flag which convention
    is used" — this reader can't reliably separate a lease-liability
    sub-note from genuine borrowings, so it sticks to the conservative
    borrowings-only reading and says so in the note, rather than guess).

    Per spec, N/A if Total Equity is negative or zero (same rule as ROE) —
    never a spurious ratio. Reuses the SAME cached PDF extraction and the
    SAME owners/generic equity fields as ROE (Sr No 18) — no extra download.
    Cached 90 days. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"ar_de_{sym}_{fiscal_year}_{'C' if consolidated else 'S'}"
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

        lt = parsed.get("lt_borrowings")
        st = parsed.get("st_borrowings")
        cm = parsed.get("current_maturities")
        if lt is None and st is None and cm is None:
            out = {"applicable": False,
                   "reason": "Could not find any Borrowings line (Long-term / Short-term / Current "
                             "Maturities) on the Balance Sheet page.",
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

        lt_cur = lt[0] if lt is not None else 0.0
        st_cur = st[0] if st is not None else 0.0
        cm_cur = cm[0] if cm is not None else 0.0
        total_debt_cur = lt_cur + st_cur + cm_cur

        equity_cur, _equity_prior = equity
        equity_basis = parsed.get("equity_basis")

        if equity_cur <= 0:
            out = {"applicable": False,
                   "reason": f"Shareholders' Equity is {'negative' if equity_cur < 0 else 'zero'} "
                             f"(₹{equity_cur:,.2f} Cr) for this company — the ratio would be meaningless, so "
                             "it's flagged as N/A rather than reported, per spec.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Total Debt", "value_cr": round(total_debt_cur, 2)},
                   "denominator": {"label": "Total Equity", "value_cr": round(equity_cur, 2)},
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(total_debt_cur / equity_cur, 2)

        components_found = sum(1 for v in (lt, st, cm) if v is not None)
        # Per spec's tiers: Total Debt built from all 3 disclosed components
        # (or a genuinely debt-free company where none apply) = 1.0; fewer
        # components found alongside an explicit owners/NCI-split equity
        # figure is still "2-3 clearly disclosed line items" = 0.95;
        # generic-fallback equity (NCI ambiguity) caps it at 0.8, same as ROE.
        if consolidated and equity_basis != "owners":
            confidence = 0.8
        elif components_found < 3:
            confidence = 0.95
        else:
            confidence = 1.0

        equity_label = ("Total Equity Attributable to Owners of the Company"
                        if equity_basis == "owners" else "Total Equity")

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": confidence,
            "estimated": confidence < 1.0,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Total Debt (closing)",
                "value_cr": round(total_debt_cur, 2),
                "components": {
                    "Long-term Borrowings": round(lt_cur, 2),
                    "Short-term Borrowings": round(st_cur, 2),
                    "Current Maturities of Long-term Debt": round(cm_cur, 2),
                },
            },
            "denominator": {
                "label": f"{equity_label} (closing)",
                "value_cr": round(equity_cur, 2),
            },
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging. "
                    "Total Debt = interest-bearing Borrowings only (Long-term + Short-term + Current Maturities); "
                    "Lease Liabilities are excluded (a separate convention, flagged here rather than silently "
                    "folded in or dropped)."
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
        if inv is None:
            out = {"applicable": False, "reason": "Could not find 'Inventories' row on the Balance Sheet page.",
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        tca_cur, _tca_prior = tca
        tcl_cur, _tcl_prior = tcl
        inv_cur, _inv_prior = inv

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
    excluded. That split lives in the Notes-to-Accounts breakup of the line,
    which this PDF-text parser doesn't attempt to read (too unreliable to
    guess at without genuine note-level extraction). So the numerator here is
    Cash and Cash Equivalents ONLY (a conservative, never-overstated figure),
    and — when found — Other Bank Balances is surfaced as a separate,
    explicitly-flagged informational figure (`other_bank_balances_cr`) rather
    than silently folded in or silently dropped, per the spec's instruction to
    "flag the distinction". Same treatment for Current Investments: only
    included if explicitly disclosed as liquid/unrestricted, which this
    reader also can't verify, so they're excluded from the numerator too.

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

        if tcl_cur == 0:
            out = {"applicable": False, "reason": "Total Current Liabilities is zero — ratio would be undefined.",
                   "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
                   "numerator": {"label": "Cash and Cash Equivalents", "value_cr": round(cash_cur, 2)},
                   "denominator": {"label": "Total Current Liabilities", "value_cr": round(tcl_cur, 2)},
                   "other_bank_balances_cr": obb_cur,
                   "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
                   "source_url": pdf_url}
            _write_cache(ckey, out)
            return out

        ratio = round(cash_cur / tcl_cur, 2)

        out = {
            "applicable": True,
            "value": ratio, "unit": "x",
            "confidence": 1.0,
            "estimated": False,
            "period": f"FY{str(fiscal_year)[-2:]} ({'consolidated' if consolidated else 'standalone'})",
            "numerator": {
                "label": "Cash and Cash Equivalents (closing)",
                "value_cr": round(cash_cur, 2),
            },
            "denominator": {
                "label": "Total Current Liabilities (closing)",
                "value_cr": round(tcl_cur, 2),
            },
            "other_bank_balances_cr": obb_cur,
            "sources": _page_sources(pdf_url, fiscal_year, bs_page=parsed.get("bs_page")),
            "note": "From the company's own Annual Report — closing Balance Sheet subtotals, no averaging. "
                    "Excludes Current Investments (only added if explicitly disclosed as liquid/unrestricted, "
                    "which can't be verified from a PDF read).",
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
