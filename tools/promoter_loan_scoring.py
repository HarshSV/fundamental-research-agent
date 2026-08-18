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
_TO_COMPANY_DIRECTION = re.compile(
    r"loans? (?:granted|given|extended|provided|made) (?:by|from) (?:the )?(?:promoter|director|kmp|key management)|"
    r"loans? (?:taken|obtained|availed|received) (?:from|by the company from)",
    re.I,
)
_FROM_COMPANY_DIRECTION = re.compile(
    r"loans? (?:to|granted to|given to|extended to|provided to) (?:key management personnel|kmp|"
    r"director(?:s)?|promoter(?:s)?(?:\s+group)?)",
    re.I,
)


_HAS_AMOUNT = re.compile(r"[\d,]+\.\d+|\d{2,}%|per annum|per cent", re.I)
_GOVERNANCE_BOILERPLATE = re.compile(
    r"review(?:ing)?\s+(?:and\s+approval\s+of\s+)?(?:the\s+)?related party|"
    r"terms of reference|committee\s+(?:shall|will|is responsible)|"
    r"refer note \d+ for terms", re.I,
)


def _loan_sentences(rpt_text):
    """Real sentences from the RPT note that name both a loan-type word and
    a promoter/group/KMP-adjacent party, AND carry an actual number (an
    amount, rate, or "per annum") - confirmed real false-positive without
    this last check: Audit Committee charter boilerplate ("Review and
    approval of the Related Party Transactions including inter-corporate
    loans") and a bare "Refer note N for terms..." cross-reference both
    name a loan keyword and a related-party term without describing any
    actual loan, and were being scored as if a real (if underdocumented)
    loan existed. Returns a list of sentence strings, never a guess at
    ones that don't literally match all three."""
    out = []
    for sent in _sentences(rpt_text):
        if _GOVERNANCE_BOILERPLATE.search(sent):
            continue
        if _LOAN_KEYWORD.search(sent) and _PROMOTER_ADJACENT.search(sent) and _HAS_AMOUNT.search(sent):
            out.append(sent)
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
    to_company = any(_TO_COMPANY_DIRECTION.search(s) for s in sentences)
    from_company = any(_FROM_COMPANY_DIRECTION.search(s) for s in sentences)
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

_INTEREST_RATE = re.compile(r"interest (?:rate(?:s)? of|at)\s*([\d.]+)%?\s*(?:to\s*([\d.]+)\s*)?%\s*per annum", re.I)
_REPAYMENT_TERM = re.compile(
    r"repayable (?:up to|between|by|on)\s*([A-Za-z]+\s*\d{1,2}?,?\s*\d{4}(?:\s*(?:to|-)\s*[A-Za-z]+\s*\d{1,2}?,?\s*\d{4})?)",
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
            rate_pct = float(rate_m.group(2) or rate_m.group(1))
        except (ValueError, TypeError):
            rate_pct = None
    rate_disclosed = rate_pct is not None
    term_disclosed = bool(term_m)
    if rate_disclosed and term_disclosed:
        score = 5
    elif rate_disclosed or term_disclosed:
        score = 3
    else:
        score = 1
    return {
        "interest_rate_pct": rate_pct,
        "repayment_term": term_m.group(1).strip() if term_m else None,
        "arms_length_confirmed": arms_length,
        "terms_score": score,
    }


# ---------------------------------------------------------------------------
# D.5.3 - Outstanding balance / concentration.
# ---------------------------------------------------------------------------

# Prefers a number immediately AFTER the standard Ind AS 24 transaction-
# type row label "Loan given"/"Loan taken" (the real label these tables
# use) over one appearing before it - confirmed real ambiguity: a
# preceding, unrelated table column (e.g. a "Performance guarantee" row
# in the same multi-column table dump) can sit right before "Loan given"
# in the extracted text, and a plain leftmost-match search picks up THAT
# number instead of the real loan figure that follows the label.
_LOAN_BALANCE_AFTER = re.compile(r"loan (?:given|taken)\b[^.]{0,20}?([\d,]+\.\d+)", re.I)
_LOAN_BALANCE_BEFORE = re.compile(r"([\d,]+\.\d+)[^.]{0,20}?\bloan (?:given|taken)\b", re.I)


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
    m = _LOAN_BALANCE_AFTER.search(blob) or _LOAN_BALANCE_BEFORE.search(blob)
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
