"""
D.3.1-D.3.3 - Secondary transactions: placements, preferential allotments -
dilution concerns. Deterministic (no-LLM) scorers over real NSE Corporate
Announcements text (tools/nse_announcements.py) - specifically the formal
"Closure and Pricing" / outcome-of-issue intimation letters companies file
under SEBI LODR Reg. 29/30 for QIPs and preferential allotments, which
routinely state the issue price, floor price, discount, dilution % and
allottee class explicitly (a real, structured regulatory disclosure, not
free narrative). Generic keyword/regex logic, not ticker-specific.
"""

import re


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


# ---------------------------------------------------------------------------
# Shared: locating and classifying real dilutive-transaction announcements.
# ---------------------------------------------------------------------------

# Deliberately excludes ESOP/ESPS/employee-stock-option allotments (routine,
# not a dilution-concern secondary transaction the spec is about) and pure
# debt/NCD placements (not equity dilution).
_DILUTIVE_KEYWORD = re.compile(
    r"qualified institutions? placement|\bqip\b|preferential (?:issue|allotment|basis)|"
    r"private placement of equity shares|private placement of.{0,20}shares",
    re.I,
)
_EXCLUDE_KEYWORD = re.compile(r"\bESOP\b|\bESOS\b|\bESPS\b|employee stock option|stock option scheme", re.I)


def is_dilutive_announcement(desc, attchmnt_text):
    """True if a corporate-announcement's own desc/attachment-title names a
    real equity-dilution-type transaction (QIP/preferential/private
    placement of equity), not a routine ESOP/ESPS employee allotment."""
    blob = f"{desc or ''} {attchmnt_text or ''}"
    if _EXCLUDE_KEYWORD.search(blob):
        return False
    return bool(_DILUTIVE_KEYWORD.search(blob))


def classify_transaction_type(text):
    """D.3.1 - Transaction Type Score: classifies the real filing text as
    QIP / Preferential / Placement / Other. Returns a label or None if the
    text carries no classifiable keyword at all."""
    if not text:
        return None
    tl = text.lower()
    if "qualified institutions" in tl or re.search(r"\bqip\b", tl):
        return "QIP"
    if "preferential" in tl:
        return "Preferential"
    if "private placement" in tl:
        return "Placement"
    return "Other"


_ALLOTTEE_CLASS = re.compile(
    r"allotted to (?:the )?(eligible qualified institutional buyers|qualified institutional buyers|"
    r"promoter(?:s)?(?:\s+group)?|non-?promoter(?:s)?|(?:a )?non-?resident|"
    r"identified investors?|allottees?)", re.I,
)


def extract_recipient_class(text):
    """The real allottee/recipient class named in the filing's own text
    (e.g. 'eligible qualified institutional buyers', 'promoter group'),
    not inferred. Returns the matched phrase or None."""
    if not text:
        return None
    m = _ALLOTTEE_CLASS.search(text)
    return m.group(1).strip() if m else None


def score_transaction_type(text):
    """D.3.1 payload builder: classification + recipient class + a 1-5
    score purely on disclosure completeness (5 = type AND recipient class
    both explicitly named, 3 = type only, 1 = neither) - NOT a judgement
    on whether the transaction itself is good or bad, since a QIP or
    preferential issue is a normal, often value-accretive corporate
    action; only the disclosure's own completeness is scored here.
    Returns {'transaction_type','recipient_class','disclosure_score'} or
    all-None if no dilutive announcement was located."""
    if not text:
        return {"transaction_type": None, "recipient_class": None, "disclosure_score": None}
    ttype = classify_transaction_type(text)
    recipient = extract_recipient_class(text)
    if ttype is None:
        return {"transaction_type": None, "recipient_class": None, "disclosure_score": None}
    if ttype != "Other" and recipient:
        score = 5
    elif ttype != "Other" or recipient:
        score = 3
    else:
        score = 1
    return {"transaction_type": ttype, "recipient_class": recipient, "disclosure_score": score}


# ---------------------------------------------------------------------------
# D.3.2 - Dilution to existing shareholders.
# ---------------------------------------------------------------------------

_DILUTION_PCT = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*of the (?:(?:pre|post)-?issue )?(?:paid-?up )?share capital", re.I,
)
_SHARES_ISSUED = re.compile(
    r"(?:for the issuance of|allot(?:ment|ted) of|issue and allot(?:ment|ted) of)\s*"
    r"([\d,]+)\s*(?:equity )?shares", re.I,
)


def score_dilution(text):
    """D.3.2 - Dilution % = New Shares Issued / Post-Issue Shares x 100,
    read directly from the filing's own explicit "X% of the share
    capital" statement where disclosed (SEBI ICDR filings routinely state
    this exact figure themselves - a real disclosed number, not derived
    from possibly-mismatched pre/post share counts pulled from two
    different documents). Falls back to None (not derived) when the
    filing doesn't state the percentage explicitly. Returns
    {'dilution_pct','shares_issued','classification'} or all-None."""
    if not text:
        return {"dilution_pct": None, "shares_issued": None, "classification": None}
    m = _DILUTION_PCT.search(text)
    dilution_pct = float(m.group(1)) if m else None
    m2 = _SHARES_ISSUED.search(text)
    shares_issued = None
    if m2:
        try:
            shares_issued = int(m2.group(1).replace(",", ""))
        except ValueError:
            shares_issued = None
    if dilution_pct is None:
        return {"dilution_pct": None, "shares_issued": shares_issued, "classification": None}
    if dilution_pct < 5:
        classification = "Low"
    elif dilution_pct <= 15:
        classification = "Moderate"
    else:
        classification = "High"
    return {"dilution_pct": dilution_pct, "shares_issued": shares_issued, "classification": classification}


# ---------------------------------------------------------------------------
# D.3.3 - Pricing / discount and rationale.
# ---------------------------------------------------------------------------

_ISSUE_PRICE = re.compile(r"issue price of.{0,15}?([\d,]+\.?\d*)\s*per (?:equity )?share", re.I)
_FLOOR_PRICE = re.compile(r"floor price of.{0,15}?([\d,]+\.?\d*)\s*per (?:equity )?share", re.I)
_DISCOUNT_PCT = re.compile(r"discount of\s*([\d.]+)\s*%", re.I)
_PURPOSE_KEYWORD = re.compile(
    r"general corporate purposes|working capital|debt repayment|capital adequacy|"
    r"funding (?:the |its |our )?(?:growth|expansion|acquisition|capex)|strengthen(?:ing)? (?:the )?capital base",
    re.I,
)


def score_pricing_rationale(text):
    """D.3.3 - Pricing & Rationale Score (1-5), based purely on pricing
    transparency (issue price and/or floor price/discount explicitly
    stated) and purpose (a stated use-of-proceeds reason) actually found
    in the filing's own text - never inferred. Score: 5 = price AND
    purpose both stated, 3 = only one of the two, 1 = neither. Returns
    {'issue_price','floor_price','discount_pct','purpose_stated',
    'pricing_rationale_score'} or all-None if no dilutive announcement
    text was located at all."""
    if not text:
        return {"issue_price": None, "floor_price": None, "discount_pct": None,
                "purpose_stated": None, "pricing_rationale_score": None}
    price_m = _ISSUE_PRICE.search(text)
    floor_m = _FLOOR_PRICE.search(text)
    disc_m = _DISCOUNT_PCT.search(text)
    purpose_m = _PURPOSE_KEYWORD.search(text)
    price_disclosed = bool(price_m or floor_m)
    purpose_disclosed = bool(purpose_m)
    if price_disclosed and purpose_disclosed:
        score = 5
    elif price_disclosed or purpose_disclosed:
        score = 3
    else:
        score = 1
    return {
        "issue_price": float(price_m.group(1).replace(",", "")) if price_m else None,
        "floor_price": float(floor_m.group(1).replace(",", "")) if floor_m else None,
        "discount_pct": float(disc_m.group(1)) if disc_m else None,
        "purpose_stated": purpose_m.group(0) if purpose_m else None,
        "pricing_rationale_score": score,
    }
