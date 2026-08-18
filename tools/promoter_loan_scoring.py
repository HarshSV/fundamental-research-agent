"""
D.5.1-D.5.3 - Promoter loans to/from company or group entities; interest
rates and repayment terms. Deterministic (no-LLM) scorers over real Annual
Report text (Ind AS 24 Related Party Disclosures note - reuses
tools.annual_report_financials.fetch_rpt_evidence_from_annual_report, the
same real evidence source already built for C.3). Generic keyword/regex
logic, not ticker-specific.
"""

import re


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _band_score_pct(pct):
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
# Shared: locating real promoter/group loan sentences within the RPT note.
# ---------------------------------------------------------------------------

_LOAN_KEYWORD = re.compile(r"\bloans?\b|\badvances?\b|\bdeposits?\b(?!.{0,10}fixed)", re.I)
_PROMOTER_ADJACENT = re.compile(
    r"promoter(?:s)?(?:\s+group)?|key management personnel|\bkmp\b|"
    r"director(?:s)?(?:\s*'?s)?|subsidiar(?:y|ies)|associate(?:s)?(?:\s+compan(?:y|ies))?|"
    r"(?:wholly[- ]owned )?group compan(?:y|ies)|related part(?:y|ies)",
    re.I,
)
# Deliberately excludes ordinary trade/vendor advances and bank/customer
# deposits - only sentences naming BOTH a loan-type word AND a promoter/
# group/KMP-adjacent party are real candidates for this sub-point.
# Includes subsidiaries/associates/group companies alongside promoter/
# director/KMP - the spec covers "company or GROUP entities", and a
# dedicated Loans-to-Subsidiaries note (e.g. HINDUNILVR's Note 7) is a
# real, common disclosure of this exact direction.
_GROUP_PARTY = r"key management personnel|kmp|director(?:s)?|promoter(?:s)?(?:\s+group)?|subsidiar(?:y|ies)|associate(?:s)?(?:\s+compan(?:y|ies))?|(?:wholly[- ]owned )?group compan(?:y|ies)"
_TO_COMPANY_DIRECTION = re.compile(
    rf"loans? (?:granted|given|extended|provided|made) (?:by|from) (?:the )?(?:{_GROUP_PARTY})|"
    r"loans? (?:taken|obtained|availed|received) (?:from|by the company from)",
    re.I,
)
_FROM_COMPANY_DIRECTION = re.compile(
    rf"loans? (?:to|granted to|given to|extended to|provided to) (?:{_GROUP_PARTY})",
    re.I,
)
# A negation cue ("no loans...", "none", "not") within ~50 chars before a
# direction-phrase match means the sentence is DENYING that direction,
# not disclosing it - confirmed real false positive: HINDUNILVR's "There
# are no loans or advances in the nature of loans granted to promoters,
# Directors, KMPs..." literally contains the "loans granted to
# promoters" phrase the regex looks for, but as an explicit denial, not
# a disclosure - without this guard it was scored as if HUL disclosed a
# real Company -> Promoter/Group loan.
_NEGATION_CUE = re.compile(r"\b(?:no|not|none|nil|never)\b", re.I)
# Fallback for a common alternate disclosure layout: a table ROW LABEL
# ("Loans and advances given ... Loans and advances recovered ...")
# with counterparty names as COLUMN HEADERS elsewhere in the same
# sentence/window, rather than a "loans given TO <party>" prose phrase
# (confirmed real: TCS's Ind AS 24 note lists "Loans and advances given
# - 21 13 - 34" under Tata Sons/Subsidiaries/Associates column headers -
# the strict _FROM_COMPANY_DIRECTION phrase never matches this layout
# since no party name directly follows "given"). Only used as a
# fallback, on a sentence that has ALREADY passed _loan_sentences'
# promoter/group-adjacent-party + real-amount filter, so the party
# co-occurs somewhere in the same window even without direct adjacency.
_FROM_COMPANY_TABLE_FALLBACK = re.compile(r"loans?(?:\s+and\s+advances)?\s+(?:given|granted|extended|provided)\b", re.I)
_TO_COMPANY_TABLE_FALLBACK = re.compile(r"loans?(?:\s+and\s+advances)?\s+(?:taken|received|obtained|availed)\b", re.I)


def _has_unnegated_match(pattern, text):
    """True if `pattern` matches `text` at a position NOT preceded within
    50 chars by a negation cue - see _NEGATION_CUE docstring above."""
    for m in pattern.finditer(text):
        preceding = text[max(0, m.start() - 50):m.start()]
        if not _NEGATION_CUE.search(preceding):
            return True
    return False


_HAS_AMOUNT = re.compile(r"[\d,]+\.\d+|\d{2,}%|per annum|per cent", re.I)
_GOVERNANCE_BOILERPLATE = re.compile(
    r"review(?:ing)?\s+(?:and\s+approval\s+of\s+)?(?:the\s+)?related party|"
    r"terms of reference|committee\s+(?:shall|will|is responsible)|"
    r"refer note \d+ for terms", re.I,
)


def _loan_sentences(rpt_text):
    """Real sentences from the RPT/loans note that name both a loan-type
    word and a promoter/group/KMP-adjacent party, AND carry an actual
    number (an amount, rate, or "per annum") - confirmed real
    false-positive without this last check: Audit Committee charter
    boilerplate ("Review and approval of the Related Party Transactions
    including inter-corporate loans") and a bare "Refer note N for
    terms..." cross-reference both name a loan keyword and a
    related-party term without describing any actual loan, and were
    being scored as if a real (if underdocumented) loan existed.

    The amount check looks at a 2-sentence window (current + next), not
    just the matched sentence alone - confirmed real gap: a dedicated
    Loans-to-Subsidiaries note (e.g. HINDUNILVR's Note 7/43) commonly
    states the loan/subsidiary/amount in one sentence ("...Lakme Lever
    Private Limited...Loans given 30...") and its interest rate/term in
    the very next one ("It is repayable over a period of 5 years and
    carries...interest at 6.55% to 7.84%..."), split apart by the
    naive period-based sentence splitter - a same-sentence-only amount
    check silently discarded this real, fully-disclosed loan. When the
    window matches, BOTH sentences are returned so downstream regex
    extraction (interest rate, repayment term, balance) can still see
    the full text via " ".join(sentences).
    Returns a list of sentence strings, never a guess at ones that
    don't literally match all three."""
    sentences = _sentences(rpt_text)
    out = []
    seen_idx = set()
    for i, sent in enumerate(sentences):
        if _GOVERNANCE_BOILERPLATE.search(sent):
            continue
        if not (_LOAN_KEYWORD.search(sent) and _PROMOTER_ADJACENT.search(sent)):
            continue
        window = sent + (" " + sentences[i + 1] if i + 1 < len(sentences) else "")
        if not _HAS_AMOUNT.search(window):
            continue
        for j in (i, i + 1):
            if j < len(sentences) and j not in seen_idx:
                seen_idx.add(j)
                out.append(sentences[j])
    return out


# ---------------------------------------------------------------------------
# D.5.1 - Promoter/company loan direction.
# ---------------------------------------------------------------------------

def score_loan_direction(rpt_text):
    """D.5.1 - Direction classification: Company -> Promoter/Group,
    Promoter/Group -> Company, Both, or None - read from explicit
    direction language in the RPT note's own loan/advance sentences
    (e.g. "Loans to Key Management Personnel..." = Company -> Promoter/
    Group; "loans taken from the promoter" = Promoter/Group -> Company).
    Returns {'direction','evidence_sentences'} or all-None if no
    promoter/group-adjacent loan sentence was located at all."""
    if not rpt_text:
        return {"direction": None, "evidence_sentences": None}
    sentences = _loan_sentences(rpt_text)
    if not sentences:
        return {"direction": None, "evidence_sentences": None}
    to_company = any(_has_unnegated_match(_TO_COMPANY_DIRECTION, s) for s in sentences)
    from_company = any(_has_unnegated_match(_FROM_COMPANY_DIRECTION, s) for s in sentences)
    if not (to_company or from_company):
        # Fall back to the table-row-label layout - see
        # _FROM_COMPANY_TABLE_FALLBACK's docstring above.
        to_company = any(_has_unnegated_match(_TO_COMPANY_TABLE_FALLBACK, s) for s in sentences)
        from_company = any(_has_unnegated_match(_FROM_COMPANY_TABLE_FALLBACK, s) for s in sentences)
    if to_company and from_company:
        direction = "Both"
    elif to_company:
        direction = "Promoter/Group → Company"
    elif from_company:
        direction = "Company → Promoter/Group"
    else:
        # A loan/advance sentence naming a promoter/group party exists,
        # but no directional verb phrase matched - real evidence, just
        # not classifiable into a direction without guessing.
        direction = None
    return {"direction": direction, "evidence_sentences": sentences[:5]}


# ---------------------------------------------------------------------------
# D.5.2 - Interest rate and terms.
# ---------------------------------------------------------------------------

# Two real phrasings confirmed across filers: "interest rate(s) of X% [to
# Y%] per annum" (explicit "per annum" suffix) and "rate of interest at
# X% [to Y%]" (interest-rate table language, e.g. HINDUNILVR's Note 7 -
# "carries a range rate of interest at 6.55% to 7.84%" - no "per annum"
# stated at all, ordering reversed from the first phrasing). Both are
# accepted; "per annum" is optional, not required, since the % figure
# itself is the real disclosure either way.
_INTEREST_RATE = re.compile(
    r"interest (?:rate(?:s)? of|at)\s*([\d.]+)%?\s*(?:to\s*([\d.]+)\s*)?%(?:\s*per annum)?|"
    r"rate of interest at\s*([\d.]+)%?\s*(?:to\s*([\d.]+)\s*)?%",
    re.I,
)
# Two real phrasings confirmed across filers: a fixed maturity/expiry
# DATE ("repayable up to/between/by/on <date>") and a TENURE length
# ("repayable over a period of N years", e.g. HINDUNILVR's Note 7 loan
# to Lakme Lever) - both are a genuine, disclosed repayment term, not
# just the date form.
_REPAYMENT_TERM = re.compile(
    r"repayable (?:up to|between|by|on)\s*([A-Za-z]+\s*\d{1,2}?,?\s*\d{4}(?:\s*(?:to|-)\s*[A-Za-z]+\s*\d{1,2}?,?\s*\d{4})?)|"
    r"repayable over a period of\s*(\d+\s*years?)",
    re.I,
)
_ARMS_LENGTH = re.compile(r"arm'?s[- ]length", re.I)


def score_loan_terms(rpt_text):
    """D.5.2 - Terms Score (1-5): an arm's-length rate, a documented
    maturity/repayment date, both explicitly stated in the RPT note's
    own loan/advance sentences, scores higher than an unexplained or
    undocumented loan. Score: 5 = rate AND repayment term both stated
    (optionally +arm's-length confirmed), 3 = only one of rate/term
    stated, 1 = a loan sentence exists but neither rate nor term is
    stated. Returns {'interest_rate_pct','repayment_term',
    'arms_length_confirmed','terms_score'} or all-None if no promoter/
    group-adjacent loan sentence was located at all."""
    if not rpt_text:
        return {"interest_rate_pct": None, "repayment_term": None, "arms_length_confirmed": None, "terms_score": None}
    sentences = _loan_sentences(rpt_text)
    if not sentences:
        return {"interest_rate_pct": None, "repayment_term": None, "arms_length_confirmed": None, "terms_score": None}
    blob = " ".join(sentences)
    rate_m = _INTEREST_RATE.search(blob)
    term_m = _REPAYMENT_TERM.search(blob)
    arms_length = bool(_ARMS_LENGTH.search(blob))
    rate_pct = None
    if rate_m:
        try:
            groups = [g for g in rate_m.groups() if g]
            rate_pct = float(groups[-1])
        except (ValueError, TypeError, IndexError):
            rate_pct = None
    rate_disclosed = rate_pct is not None
    repayment_term = None
    if term_m:
        repayment_term = (term_m.group(1) or term_m.group(2) or "").strip()
    term_disclosed = bool(repayment_term)
    if rate_disclosed and term_disclosed:
        score = 5
    elif rate_disclosed or term_disclosed:
        score = 3
    else:
        score = 1
    return {
        "interest_rate_pct": rate_pct,
        "repayment_term": repayment_term or None,
        "arms_length_confirmed": arms_length,
        "terms_score": score,
    }


# ---------------------------------------------------------------------------
# D.5.3 - Outstanding balance / concentration.
# ---------------------------------------------------------------------------

# A loan-movement table (opening balance / loans given / loans repaid /
# closing balance) discloses the real OUTSTANDING balance under
# "Balance as at the end/close of the year", not under "Loans given"
# (which is the amount newly disbursed during the year, a different,
# smaller figure) - confirmed real gap on HINDUNILVR's Note 7 Loans-to-
# Subsidiaries table ("...Loans given 30 10 Loans repaid 25 40 Balance
# as at the end of the year 165 160..."), where a "Loans given"-only
# search picked up the disbursement figure (30) instead of the real
# closing balance (165). Tried first, in priority order.
_LOAN_BALANCE_ENDYEAR = re.compile(r"balance as at (?:the )?(?:end|close) of (?:the )?year\b[^.]{0,20}?([\d,]+(?:\.\d+)?)", re.I)
# Prefers a number immediately AFTER the standard Ind AS 24 transaction-
# type row label "Loan given"/"Loan taken" (the real label these tables
# use) over one appearing before it - confirmed real ambiguity: a
# preceding, unrelated table column (e.g. a "Performance guarantee" row
# in the same multi-column table dump) can sit right before "Loan given"
# in the extracted text, and a plain leftmost-match search picks up THAT
# number instead of the real loan figure that follows the label. Decimal
# point is optional - real disclosed balances are integer crore amounts
# just as often as decimal ones (confirmed: HINDUNILVR discloses whole
# numbers, SUZLON discloses one decimal place).
_LOAN_BALANCE_AFTER = re.compile(r"loan (?:given|taken)\b[^.]{0,20}?([\d,]+(?:\.\d+)?)", re.I)
_LOAN_BALANCE_BEFORE = re.compile(r"([\d,]+(?:\.\d+)?)[^.]{0,20}?\bloan (?:given|taken)\b", re.I)


def score_loan_concentration(rpt_text, net_worth_cr=None, total_assets_cr=None):
    """D.5.3 - Exposure % = Promoter/Group Loan Balance / Net Worth or
    Total Assets, using the most relevant disclosed denominator. Reads
    the loan balance (in ₹ crore, matching the Annual Report's own
    reporting unit) from a number appearing near a real loan/advance
    sentence; divides by `net_worth_cr` if given, else `total_assets_cr`
    - both real, already-computed figures from this company's own
    financial statements (never a third figure invented for this
    denominator). Returns {'loan_balance_cr','denominator_used',
    'exposure_pct','classification'} or all-None if no loan balance
    figure or usable denominator was found."""
    if not rpt_text:
        return {"loan_balance_cr": None, "denominator_used": None, "exposure_pct": None, "classification": None}
    sentences = _loan_sentences(rpt_text)
    if not sentences:
        return {"loan_balance_cr": None, "denominator_used": None, "exposure_pct": None, "classification": None}
    blob = " ".join(sentences)
    m = _LOAN_BALANCE_ENDYEAR.search(blob) or _LOAN_BALANCE_AFTER.search(blob) or _LOAN_BALANCE_BEFORE.search(blob)
    loan_balance = None
    if m:
        try:
            loan_balance = float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            loan_balance = None
    if loan_balance is None:
        return {"loan_balance_cr": None, "denominator_used": None, "exposure_pct": None, "classification": None}
    denominator, denom_label = None, None
    if net_worth_cr:
        denominator, denom_label = net_worth_cr, "Net Worth"
    elif total_assets_cr:
        denominator, denom_label = total_assets_cr, "Total Assets"
    if not denominator:
        return {"loan_balance_cr": loan_balance, "denominator_used": None, "exposure_pct": None, "classification": None}
    pct = round(100 * loan_balance / denominator, 2)
    if pct < 1:
        classification = "Low"
    elif pct <= 5:
        classification = "Moderate"
    else:
        classification = "High"
    return {
        "loan_balance_cr": loan_balance, "denominator_used": denom_label,
        "exposure_pct": pct, "classification": classification,
    }
