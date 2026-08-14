"""
B.2.1-B.2.4 — Management incentives: deterministic (no-LLM) scorers.

Same design as tools/founder_track_record_scoring.py (B.1) and
tools/moat_brand_scoring.py (A.2.A): regex/keyword pattern matching against
real Annual Report text only, no LLM call. Every number traces to a
literal matched figure in the source text - a value is only ever computed
from a real disclosed figure, never guessed or interpolated.
"""

import re

_NUM = r"\d[\d,]*\.?\d*"


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _band_score_pct(pct):
    """Shared 0-100% -> 1-5 banding (>=80=5, 65-79=4, 50-64=3, 30-49=2,
    <30=1), same thresholds as B.1's spec-given bands - used here as a
    reasonable default where the B.2 spec asks for a 1-5 score but doesn't
    give explicit thresholds of its own."""
    if pct is None:
        return None
    if pct >= 80:
        return 5
    if pct >= 65:
        return 4
    if pct >= 50:
        return 3
    if pct >= 30:
        return 2
    return 1


# ---------------------------------------------------------------------------
# B.2.1 - Pay structure: Fixed vs Variable Compensation Mix
# ---------------------------------------------------------------------------

_FIXED_LABEL = re.compile(r"\bfixed\b[^.\n]{0,40}?\b(?:commission|pay|salary|remuneration|compensation)\b", re.I)
_VARIABLE_LABEL = re.compile(r"\b(?:variable|performance[- ]linked)\b[^.\n]{0,40}?\b(?:commission|pay|bonus|remuneration|incentive|compensation)\b", re.I)
_NUM_NEAR = re.compile(_NUM)


def _first_number_after(text, pos, max_chars=150):
    """Returns (value, absolute_start_pos) for the first number found, or
    None. The absolute position lets the caller dedupe two labels that
    both happen to point at the SAME figure (e.g. a column header "Fixed
    Commission" immediately followed by a row label "Base Fixed Commission
    ... 25.00" - both match the label pattern but there's only one real
    number between them, which must not be counted twice)."""
    window = text[pos:pos + max_chars]
    m = _NUM_NEAR.search(window)
    if not m:
        return None
    # Reject a "N." immediately followed by a newline+capital letter - a
    # numbered-list marker (e.g. "1.\nNext Item"), not a real amount. A
    # genuine amount is never followed by a fresh capitalized line right
    # after its own decimal point with nothing else on that line.
    tail = window[m.end():m.end() + 3]
    if re.match(r"\.\s*\n[A-Z]", tail) or re.match(r"\.\s*\n[A-Z]", window[m.end() - 1:m.end() + 3]):
        return None
    v = _to_float(m.group(0))
    if v is None:
        return None
    return v, pos + m.start()


def extract_pay_mix(text):
    """Finds every explicit "Fixed <Commission/Pay/Salary>" and "Variable/
    Performance-linked <Commission/Pay/Bonus>" label in `text` and takes the
    first real amount figure following each (a label sits on its own line
    in PDF-linearized tables, with the number a short distance below/after
    it - not necessarily the same sentence). Sums each bucket separately.
    Returns {'fixed_amount','variable_amount','fixed_pct'} or all-None if
    no explicit fixed/variable component amount was found."""
    if not text:
        return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    fixed_total, variable_total = 0.0, 0.0
    fixed_found, variable_found = False, False
    seen_positions = set()
    for m in _FIXED_LABEL.finditer(text):
        r = _first_number_after(text, m.end())
        if r is not None and r[1] not in seen_positions:
            fixed_total += r[0]
            fixed_found = True
            seen_positions.add(r[1])
    for m in _VARIABLE_LABEL.finditer(text):
        r = _first_number_after(text, m.end())
        if r is not None and r[1] not in seen_positions:
            variable_total += r[0]
            variable_found = True
            seen_positions.add(r[1])
    if not (fixed_found and variable_found):
        return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    total = fixed_total + variable_total
    if total <= 0:
        return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    return {
        "fixed_amount": round(fixed_total, 2), "variable_amount": round(variable_total, 2),
        "fixed_pct": round(100 * fixed_total / total, 1),
    }


# ---------------------------------------------------------------------------
# B.2.2 - Equity ownership: Management Ownership Score
# ---------------------------------------------------------------------------

# A row naming a Director/KMP with an explicit "% of total shares"/"% of
# paid-up capital" figure nearby - summed across all such rows found.
_PCT_OF_SHARES = re.compile(rf"({_NUM})\s*%\s*(?:of\s+(?:total|paid[- ]up)\s+(?:shares|equity|capital))", re.I)
_DIRECTOR_KMP_ROLE = re.compile(r"\b(?:Director|KMP|Key Managerial Personnel|Chief Executive|Chief Financial|Managing Director|Executive Director|Company Secretary)\b", re.I)


def score_equity_ownership(shareholding_text):
    """Sums every explicit "X% of total/paid-up shares" figure that appears
    within 200 chars of a Director/KMP role mention in `shareholding_text`
    - a promoter-group holding table (parent company, unrelated to
    individual directors) is NOT what this counts; only rows tied to a
    named director/KMP role. Management Ownership Score (1-5) bands the
    summed % using this codebase's own thresholds (no explicit band given
    in the spec for this sub-point): >=5%=5, 2-5%=4, 1-2%=3, 0.1-1%=2,
    <0.1%=1. Returns {'management_ownership_pct','ownership_score'} or
    all-None if no such figure was found."""
    if not shareholding_text:
        return {"management_ownership_pct": None, "ownership_score": None}
    total_pct = 0.0
    found = False
    for m in _PCT_OF_SHARES.finditer(shareholding_text):
        window = shareholding_text[max(0, m.start() - 200):m.start()]
        if _DIRECTOR_KMP_ROLE.search(window):
            v = _to_float(m.group(1))
            if v is not None and 0 <= v <= 100:
                total_pct += v
                found = True
    if not found:
        return {"management_ownership_pct": None, "ownership_score": None}
    total_pct = round(min(total_pct, 100.0), 2)
    score = 5 if total_pct >= 5 else 4 if total_pct >= 2 else 3 if total_pct >= 1 else 2 if total_pct >= 0.1 else 1
    return {"management_ownership_pct": total_pct, "ownership_score": score}


# STRUCTURAL variant - each director's Corporate Governance profile in a
# standard AR carries a "Number of Equity Shares held in the Company"
# field with an absolute share COUNT (not a %) - confirmed real, common,
# and far more reliably disclosed than an explicit "X% of total shares"
# figure (which many companies simply never state for individual
# directors/KMP, per live testing). Divides the summed count by the
# company's own total shares outstanding (tools.nse_xbrl.
# fetch_shares_outstanding, already used elsewhere in this codebase for
# market cap) to get the same % this sub-point needs.
_SHARES_HELD_LABEL = re.compile(r"number\s+of\s+equity\s+shares\s+held", re.I)
_DIRECTOR_NAME_LABEL = re.compile(r"name\s+of\s+the\s+director", re.I)


def score_equity_ownership_from_tables(tables, total_shares_outstanding):
    """`tables`: list of small 2-column [label, value] director-profile
    tables (from tools.ar_table_extractor.extract_tables_near_anchors).
    Sums each table's "Number of Equity Shares held" value (0 counted
    explicitly if the cell states none/nil - a director profile that
    exists but discloses zero holding is real information, not a gap).
    Returns {'management_ownership_pct','ownership_score',
    'director_share_count'} or all-None if no such field was found or
    total_shares_outstanding isn't available."""
    if not tables or not total_shares_outstanding:
        return {"management_ownership_pct": None, "ownership_score": None, "director_share_count": None}
    total_shares_held = 0.0
    found = False
    for table in tables:
        for row in table or []:
            cells = [(c or "").strip() for c in row]
            if len(cells) < 2 or not cells[0]:
                continue
            if _SHARES_HELD_LABEL.search(cells[0]):
                v = parse_cell_number(cells[1]) if cells[1] and cells[1].strip().lower() not in ("nil", "none", "-") else 0.0
                if v is not None:
                    total_shares_held += v
                    found = True
    if not found:
        return {"management_ownership_pct": None, "ownership_score": None, "director_share_count": None}
    pct = round(min(100.0, 100 * total_shares_held / total_shares_outstanding), 4)
    score = 5 if pct >= 5 else 4 if pct >= 2 else 3 if pct >= 1 else 2 if pct >= 0.1 else 1
    return {"management_ownership_pct": pct, "ownership_score": score, "director_share_count": round(total_shares_held)}


def parse_cell_number(cell):
    """Local re-export (avoids a circular import with ar_table_extractor
    at module load time) - identical to ar_table_extractor.parse_cell_number."""
    if not cell:
        return None
    m = re.search(_NUM, cell.replace("₹", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# B.2.3 - Vesting structure: Long-term Incentive Score
# ---------------------------------------------------------------------------

_VESTED_LABEL = re.compile(r"\b(?:already\s+)?vested\b(?!\s+in)", re.I)
_UNVESTED_LABEL = re.compile(r"\b(?:un[- ]?vested|yet\s+to\s+vest|not\s+yet\s+vested)\b", re.I)


def _first_count_after(text, pos, max_chars=100):
    window = text[pos:pos + max_chars]
    m = _NUM_NEAR.search(window)
    if not m:
        return None
    v = _to_float(m.group(0))
    return v if v is not None and v >= 1 else None


def score_vesting_structure(esop_text):
    """Finds every explicit "vested"/"unvested" option-COUNT figure in
    `esop_text` (a label sits near its count in an ESOP disclosure table).
    Long-term Incentive Score (1-5) is banded on the UNVESTED share of
    total options found - a higher unvested proportion means more of the
    incentive still depends on future service/performance, i.e. more
    forward-looking retention pull (this scoring DIRECTION is this
    engine's own documented interpretation - the spec doesn't state one).
    Returns {'vested_count','unvested_count','unvested_pct',
    'vesting_score'} or all-None if no explicit vested/unvested count was
    found."""
    if not esop_text:
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    vested_total, unvested_total = 0.0, 0.0
    vested_found, unvested_found = False, False
    for m in _UNVESTED_LABEL.finditer(esop_text):
        v = _first_count_after(esop_text, m.end())
        if v is not None:
            unvested_total += v
            unvested_found = True
    for m in _VESTED_LABEL.finditer(esop_text):
        # Skip a match that's actually part of an "unvested" token (the
        # unvested pattern already consumed those; this guards the rare
        # case the two patterns' spans could otherwise double-count).
        if esop_text[max(0, m.start() - 3):m.start()].lower().endswith(("un", "un-", "un ")):
            continue
        v = _first_count_after(esop_text, m.end())
        if v is not None:
            vested_total += v
            vested_found = True
    if not (vested_found and unvested_found):
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    total = vested_total + unvested_total
    if total <= 0:
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    unvested_pct = round(100 * unvested_total / total, 1)
    return {
        "vested_count": round(vested_total), "unvested_count": round(unvested_total),
        "unvested_pct": unvested_pct, "vesting_score": _band_score_pct(unvested_pct),
    }


# ---------------------------------------------------------------------------
# B.2.4 - Long-term orientation: Long-term vs Short-term Incentives
# ---------------------------------------------------------------------------

_LONG_TERM_KEYWORDS = re.compile(
    r"\blong[- ]term incentive\b|\bLTIP\b|\bstock option\b|\bESOP\b|\bperformance share\b|"
    r"\bdeferred (?:bonus|pay|compensation)\b|\bmulti[- ]year vesting\b|\brestricted stock\b", re.I
)
_SHORT_TERM_KEYWORDS = re.compile(
    r"\bshort[- ]term incentive\b|\bSTI\b|\bannual bonus\b|\bcash bonus\b|"
    r"\bannual performance (?:pay|bonus)\b|\bannual incentive\b", re.I
)


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def score_long_term_orientation(policy_text):
    """Classifies each sentence of `policy_text` (Remuneration Policy)
    mentioning a long-term-incentive keyword (LTIP/ESOP/stock options/
    deferred pay/performance shares) vs a short-term-incentive keyword
    (annual bonus/STI/cash bonus) - a sentence naming both is counted in
    both buckets (deliberately, since the policy is genuinely describing
    a mix in that sentence). Long-term Alignment Score (1-5) bands the
    long-term share of total tagged sentences. Returns
    {'long_term_count','short_term_count','long_term_pct',
    'alignment_score'} or all-None if the policy text names neither."""
    if not policy_text:
        return {"long_term_count": None, "short_term_count": None, "long_term_pct": None, "alignment_score": None}
    long_n, short_n = 0, 0
    for sent in _sentences(policy_text):
        if _LONG_TERM_KEYWORDS.search(sent):
            long_n += 1
        if _SHORT_TERM_KEYWORDS.search(sent):
            short_n += 1
    total = long_n + short_n
    if total == 0:
        return {"long_term_count": None, "short_term_count": None, "long_term_pct": None, "alignment_score": None}
    pct = round(100 * long_n / total, 1)
    return {
        "long_term_count": long_n, "short_term_count": short_n,
        "long_term_pct": pct, "alignment_score": _band_score_pct(pct),
    }


# ---------------------------------------------------------------------------
# STRUCTURAL variants (pdfplumber table-based) - per updated sourcing
# direction: use remuneration disclosures (salary/perquisites/commission/
# bonus/ESOP), promoter/director/KMP shareholding tables, and ESOP grant
# date/vesting schedule/exercise period/option life, rather than searching
# for exact phrasing like "Fixed"/"Variable" or "vested"/"unvested" that
# many companies simply never use verbatim. Each reads a REAL detected
# table (tools.ar_table_extractor.extract_tables_near_anchors) by column
# header keyword, so it generalizes across companies that disclose the
# same information under different column titles.
# ---------------------------------------------------------------------------

_FIXED_COL_KEYWORDS = ["salary", "basic", "perquisite", "retiral", "fixed"]
_VARIABLE_COL_KEYWORDS = ["bonus", "commission", "incentive", "esop", "stock option", "variable", "esar"]


def extract_pay_mix_from_tables(tables):
    """A KMP/Director remuneration table's OWN column headers routinely
    name the pay components directly (e.g. ITC: "Basic/Consolidated
    Salary" | "Perquisites/Other Benefits" | "Performance Bonus/Long Term
    Incentives/Commission") - classifies each column as fixed or variable
    by header keyword and sums every named individual's row (skips a
    "Total" row to avoid double-counting). Returns
    {'fixed_amount','variable_amount','fixed_pct'} or all-None if no
    table has both a fixed-type and a variable-type column."""
    from tools.ar_table_extractor import find_column, parse_cell_number
    for table in tables or []:
        if not table or len(table) < 2:
            continue
        header = table[0]
        fixed_cols = [i for i, c in enumerate(header) if any(kw in (c or "").lower() for kw in _FIXED_COL_KEYWORDS)]
        variable_cols = [i for i, c in enumerate(header) if any(kw in (c or "").lower() for kw in _VARIABLE_COL_KEYWORDS)]
        if not fixed_cols or not variable_cols:
            continue
        fixed_total, variable_total = 0.0, 0.0
        any_row = False
        for row in table[1:]:
            if not row or not (row[0] or "").strip() or (row[0] or "").strip().lower() in ("total", "grand total"):
                continue
            row_has_value = False
            for i in fixed_cols:
                if i < len(row):
                    v = parse_cell_number(row[i])
                    if v is not None:
                        fixed_total += v
                        row_has_value = True
            for i in variable_cols:
                if i < len(row):
                    v = parse_cell_number(row[i])
                    if v is not None:
                        variable_total += v
                        row_has_value = True
            any_row = any_row or row_has_value
        total = fixed_total + variable_total
        if any_row and total > 0:
            return {"fixed_amount": round(fixed_total, 2), "variable_amount": round(variable_total, 2), "fixed_pct": round(100 * fixed_total / total, 1)}
    return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}


_OUTSTANDING_LABEL = re.compile(r"outstanding\s+at\s+the\s+end\s+of\s+the\s+year", re.I)
_EXERCISABLE_LABEL = re.compile(r"exercisable\s+at\s+the\s+end\s+of\s+the\s+year", re.I)


def score_vesting_structure_from_tables(tables):
    """A standard Ind AS 102 ESOP reconciliation table states "Options
    Outstanding at the end of the year" (total) and, when disclosed,
    "Options exercisable at the end of the year" (already vested) - the
    difference is the unvested balance. Far more reliably disclosed,
    company-to-company, than a literal "vested"/"unvested" label pair
    (confirmed real: ITC states "exercisable", not "vested"). Returns
    {'vested_count','unvested_count','unvested_pct','vesting_score'} or
    all-None if no table states both figures."""
    from tools.ar_table_extractor import parse_cell_number
    for table in tables or []:
        outstanding, exercisable = None, None
        for row in table or []:
            if not row or not row[0]:
                continue
            label = row[0]
            value = None
            for cell in row[1:]:
                v = parse_cell_number(cell)
                if v is not None and v > 0:
                    value = v
                    break
            if value is None:
                continue
            if _OUTSTANDING_LABEL.search(label):
                outstanding = value
            elif _EXERCISABLE_LABEL.search(label):
                exercisable = value
        if outstanding is not None and exercisable is not None and outstanding >= exercisable:
            unvested = outstanding - exercisable
            unvested_pct = round(100 * unvested / outstanding, 1) if outstanding > 0 else None
            if unvested_pct is None:
                continue
            return {
                "vested_count": round(exercisable), "unvested_count": round(unvested),
                "unvested_pct": unvested_pct, "vesting_score": _band_score_pct(unvested_pct),
            }
    return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}


_VESTING_MONTHS = re.compile(r"completion\s+of\s+(\d+)\s+months?|over\s+a\s+period\s+of\s+(\d+)\s+years?|(\d+)\s+years?\s+from\s+the\s+date\s+of\s+grant", re.I)
_PERFORMANCE_LINKED_CTX = re.compile(r"performance[- ]linked|performance condition|subject to (?:the )?performance|performance criteria", re.I)


def score_long_term_orientation_from_esop_text(vesting_schedule_text):
    """Infers long-term orientation from the ESOP's own disclosed vesting
    HORIZON (the longest "completion of N months/years from grant" figure
    in its Vesting Schedule note) plus whether vesting is explicitly
    performance-linked - this engine's own interpretation of "Infer from
    ESOP duration, vesting horizon, and performance-linked incentives"
    (the spec doesn't give an exact formula for this signal). Longer
    horizon = more long-term retention pull; performance-linking adds a
    point (capped at 5). Bands: >=3y=5, 2-3y=4, 1-2y=3, <1y=2 (before any
    performance-linked bonus). Returns {'vesting_horizon_years',
    'performance_linked','alignment_score'} or all-None if no vesting
    horizon is stated at all."""
    if not vesting_schedule_text:
        return {"vesting_horizon_years": None, "performance_linked": None, "alignment_score": None}
    months = []
    for m in _VESTING_MONTHS.finditer(vesting_schedule_text):
        if m.group(1):
            months.append(int(m.group(1)))
        elif m.group(2):
            months.append(int(m.group(2)) * 12)
        elif m.group(3):
            months.append(int(m.group(3)) * 12)
    if not months:
        return {"vesting_horizon_years": None, "performance_linked": None, "alignment_score": None}
    horizon_years = round(max(months) / 12, 1)
    performance_linked = bool(_PERFORMANCE_LINKED_CTX.search(vesting_schedule_text))
    score = 5 if horizon_years >= 3 else 4 if horizon_years >= 2 else 3 if horizon_years >= 1 else 2
    if performance_linked:
        score = min(5, score + 1)
    return {"vesting_horizon_years": horizon_years, "performance_linked": performance_linked, "alignment_score": score}


# ---------------------------------------------------------------------------
# ESOP GRANT SCHEDULE (raw-text) - for a table with real column structure
# (Date of Grant / Options Granted / Vesting Conditions / Exercise Period)
# but no ruled/visible cell lines, so pdfplumber's geometry-based table
# detector finds nothing at all (confirmed real: HINDUNILVR). Parses the
# raw page text directly by regex instead of relying on table geometry -
# feeds BOTH B.2.3 (vested/unvested, inferred from elapsed time since
# grant vs the stated vesting period) and B.2.4 (vesting horizon +
# performance-linkage) from the SAME underlying grant tranches, per the
# updated sourcing direction ("use ESOP grant date, vesting schedule,
# exercise period, and option life" / "infer from ESOP duration, vesting
# horizon, and performance-linked incentives").
# ---------------------------------------------------------------------------

_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_MONTHS = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
_GRANT_DATE = re.compile(
    rf"\b\d{{1,2}}[-\s](?:{_MONTHS})[a-z]*[-\s](\d{{2,4}})\b", re.I
)
_VESTING_AFTER = re.compile(
    r"after\s+(" + "|".join(_WORD_NUM) + r"|\d+)\s+years?\s+from\s+(?:the\s+)?date\s+of\s+grant", re.I
)
_GRANTED_COUNT_NEAR = re.compile(r"\b(\d[\d,]{2,})\*?\b")
_PERFORMANCE_CONDITION_CTX = re.compile(r"performance\s+condition|performance[- ]linked|meeting\s+performance", re.I)


def extract_esop_grant_schedule(text, fiscal_year):
    """Finds every "Date of Grant ... Options Granted ... After <N> years
    from date of grant" tranche in raw page text (a real table column
    layout, just not one pdfplumber can detect geometrically). Returns a
    list of {'grant_year','options_granted','vesting_years',
    'performance_linked'} - empty if the text names no such tranche.
    Never guesses a vesting period that isn't explicitly stated."""
    if not text or not fiscal_year:
        return []
    tranches = []
    seen = set()
    for m in _GRANT_DATE.finditer(text):
        yr = int(m.group(1))
        if yr < 100:
            yr += 2000
        if not (1990 <= yr <= fiscal_year):
            continue
        window = text[m.end():m.end() + 350]
        count_m = _GRANTED_COUNT_NEAR.search(window[:80])
        granted = _to_float(count_m.group(1)) if count_m else None
        if granted is None or granted < 10:
            continue
        vest_m = _VESTING_AFTER.search(window)
        if not vest_m:
            continue
        raw = vest_m.group(1).lower()
        vesting_years = int(raw) if raw.isdigit() else _WORD_NUM.get(raw)
        if not vesting_years:
            continue
        performance_linked = bool(_PERFORMANCE_CONDITION_CTX.search(window[:250]))
        # De-dup: the same tranche can legitimately be found twice when
        # two different anchor phrases both matched the page/text region
        # containing it (confirmed real: "vesting schedule" and "date of
        # grant" both hit the same table) - a (year, count) pair is a
        # reliable fingerprint for "the same disclosed tranche".
        key = (yr, round(granted))
        if key in seen:
            continue
        seen.add(key)
        tranches.append({
            "grant_year": yr, "options_granted": granted,
            "vesting_years": vesting_years, "performance_linked": performance_linked,
        })
    return tranches[:20]


def score_vesting_structure_from_grant_schedule(tranches, fiscal_year):
    """Vested/unvested inferred from elapsed time since each tranche's
    grant vs its own stated vesting period - a tranche is "vested" once
    (fiscal_year - grant_year) >= vesting_years, "unvested" otherwise.
    Returns the same shape as score_vesting_structure_from_tables, or
    all-None if `tranches` is empty."""
    if not tranches or not fiscal_year:
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    vested, unvested = 0.0, 0.0
    for t in tranches:
        elapsed = fiscal_year - t["grant_year"]
        if elapsed >= t["vesting_years"]:
            vested += t["options_granted"]
        else:
            unvested += t["options_granted"]
    total = vested + unvested
    if total <= 0:
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    unvested_pct = round(100 * unvested / total, 1)
    return {
        "vested_count": round(vested), "unvested_count": round(unvested),
        "unvested_pct": unvested_pct, "vesting_score": _band_score_pct(unvested_pct),
    }


def score_long_term_orientation_from_grant_schedule(tranches):
    """Same scoring logic as score_long_term_orientation_from_esop_text
    (longest stated vesting horizon + performance-linkage bonus), sourced
    from real grant tranches instead of a single Vesting Schedule
    sentence. Returns all-None if `tranches` is empty."""
    if not tranches:
        return {"vesting_horizon_years": None, "performance_linked": None, "alignment_score": None}
    horizon_years = float(max(t["vesting_years"] for t in tranches))
    performance_linked = any(t["performance_linked"] for t in tranches)
    score = 5 if horizon_years >= 3 else 4 if horizon_years >= 2 else 3 if horizon_years >= 1 else 2
    if performance_linked:
        score = min(5, score + 1)
    return {"vesting_horizon_years": horizon_years, "performance_linked": performance_linked, "alignment_score": score}
