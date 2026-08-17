"""
C.4.1-C.4.4 - Use of complex group entities: off-balance-sheet vehicles,
SPVs, subsidiaries abroad, group structure complexity. Deterministic
(no-LLM) regex/structural scorers over real Annual Report text (Notes to
Accounts - Contingent Liabilities & Commitments, Related Party
Disclosures' subsidiary listing), same design as
tools/rpt_disclosure_scoring.py. Generic keyword sets and Ind AS 24/
Companies Act vocabulary, not ticker-specific.
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
# C.4.1 - Off-balance-sheet vehicles (Contingent Liabilities & Commitments).
# ---------------------------------------------------------------------------

_OFFBALANCE_KEYWORD = re.compile(
    r"contingent liabilit|capital commitment|corporate guarantee|letter of credit|"
    r"lease commitment|off[- ]balance|capital account|estimated value of contracts", re.I
)
_QUANTIFIED_MARKER = re.compile(
    r"\d+(?:\.\d+)?\s*%|₹\s*\d|\$\s*\d|\bcrore\b|\bmillion\b|\bbillion\b|\b\d{2,}\b", re.I
)
_UNQUANTIFIABLE_MARKER = re.compile(
    r"amount (?:cannot|not) be (?:reliably )?estimated|amount is not ascertainable|"
    r"no reliable estimate|cannot be (?:reasonably|reliably) (?:ascertained|estimated|quantified)", re.I
)


def score_offbalance_sheet_risk(contingent_text):
    """An off-balance-sheet-keyword sentence (contingent liability,
    capital commitment, guarantee, letter of credit, lease commitment)
    is "Disclosed" (transparent) if it names a quantified figure in the
    same sentence, "Opaque" if it explicitly states the amount cannot be
    estimated/ascertained. Spec: 5 = no material opaque arrangements
    identified. Returns {'disclosed_count','opaque_count',
    'transparency_pct','offbalance_risk_score'} or all-None if no such
    sentence carries either signal."""
    if not contingent_text:
        return {"disclosed_count": None, "opaque_count": None, "transparency_pct": None, "offbalance_risk_score": None}
    disclosed = opaque = 0
    for sent in _sentences(contingent_text):
        if not _OFFBALANCE_KEYWORD.search(sent):
            continue
        if _UNQUANTIFIABLE_MARKER.search(sent):
            opaque += 1
        elif _QUANTIFIED_MARKER.search(sent):
            disclosed += 1
    total = disclosed + opaque
    if total == 0:
        return {"disclosed_count": None, "opaque_count": None, "transparency_pct": None, "offbalance_risk_score": None}
    pct = round(100 * disclosed / total, 1)
    return {"disclosed_count": disclosed, "opaque_count": opaque, "transparency_pct": pct, "offbalance_risk_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# Shared entity extraction (C.4.2/C.4.3/C.4.4) - the Related Party
# Disclosures note's own "Subsidiaries (Extent of holding)" listing.
# ---------------------------------------------------------------------------

_ENTITY_WITH_PCT = re.compile(
    r"([A-Z][\w&'\.\-]+(?:\s+[A-Z][\w&'\.\-]+){0,6}\s+(?:Limited|Ltd\.?|Pte Ltd|Inc\.?|LLC|LLP|"
    r"Foundation|Trust|B\.V\.?|AG|GmbH))\s*\((\d+(?:\.\d+)?)%", re.I
)
_FOREIGN_COUNTRY_HINT = re.compile(
    r"\b(?:Nepal|Indonesia|Pakistan|Sri Lanka|Bangladesh|Kenya|Thai(?:land)?|Ireland|"
    r"Philippines|Vietnam|Singapore|Malaysia|China)\b", re.I
)
_FOREIGN_SUFFIX = re.compile(r"\bPte\.?\s?Ltd\b|\bInc\.?\b|\bLLC\b|\bB\.V\.?\b|\bAG\b|\bGmbH\b", re.I)
_TRUST_HINT = re.compile(r"\bTrust\b|\bFoundation\b|\bFund\b", re.I)


def extract_group_entities(text):
    """Parses the Related Party Disclosures note's own "Subsidiaries
    (Extent of holding)" listing - "EntityName (NN%)" - into structured
    rows. Dedups by entity name (case-insensitive). Returns
    [{'name','ownership_pct','is_trust','is_overseas'}, ...] or [] if no
    such listing is present. Never raises."""
    if not text:
        return []
    seen = {}
    for m in _ENTITY_WITH_PCT.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        key = name.lower()
        if key in seen:
            continue
        try:
            pct = float(m.group(2))
        except (ValueError, TypeError):
            pct = None
        is_overseas = bool(_FOREIGN_COUNTRY_HINT.search(name) or _FOREIGN_SUFFIX.search(name))
        is_trust = bool(_TRUST_HINT.search(name))
        seen[key] = {"name": name, "ownership_pct": pct, "is_trust": is_trust, "is_overseas": is_overseas}
    return list(seen.values())


# ---------------------------------------------------------------------------
# C.4.2 - Special purpose vehicles (Trusts/Foundations vs operating entities).
# ---------------------------------------------------------------------------

def score_spv_complexity(entities):
    """Classifies each named group entity as an "Operating Entity" or an
    SPV-like vehicle (Trust/Foundation/Fund - holding/benefit structures,
    not an operating business). More operating entities relative to SPVs
    bands higher (lower complexity). Returns {'operating_count',
    'spv_count','operating_pct','spv_complexity_score'} or all-None if no
    entities were extracted."""
    if not entities:
        return {"operating_count": None, "spv_count": None, "operating_pct": None, "spv_complexity_score": None}
    spv = sum(1 for e in entities if e.get("is_trust"))
    operating = len(entities) - spv
    pct_operating = round(100 * operating / len(entities), 1)
    return {"operating_count": operating, "spv_count": spv, "operating_pct": pct_operating, "spv_complexity_score": _band_score_pct(pct_operating)}


# ---------------------------------------------------------------------------
# C.4.3 - Subsidiaries abroad (domestic vs overseas concentration).
# ---------------------------------------------------------------------------

def score_offshore_structure(entities):
    """Classifies each named group entity as domestic or overseas (by
    country-name hint or a distinctly non-Indian corporate suffix -
    Pte Ltd/Inc/LLC/B.V./AG/GmbH). A higher domestic concentration bands
    higher (lower cross-border complexity/disclosure burden). Returns
    {'domestic_count','overseas_count','domestic_pct',
    'offshore_structure_score'} or all-None if no entities were
    extracted."""
    if not entities:
        return {"domestic_count": None, "overseas_count": None, "domestic_pct": None, "offshore_structure_score": None}
    overseas = sum(1 for e in entities if e.get("is_overseas"))
    domestic = len(entities) - overseas
    pct_domestic = round(100 * domestic / len(entities), 1)
    return {"domestic_count": domestic, "overseas_count": overseas, "domestic_pct": pct_domestic, "offshore_structure_score": _band_score_pct(pct_domestic)}


# ---------------------------------------------------------------------------
# C.4.4 - Complexity / transparency of group structure (entity count).
# ---------------------------------------------------------------------------

def score_group_complexity(entities):
    """Bands Group Structure Complexity Score on total distinct named
    group entity count (fewer entities = simpler, less complex
    structure = higher score) - a real, generic proxy; entity purpose/
    layering nuance beyond count isn't assessed here. Returns
    {'entity_count','domestic_count','overseas_count','trust_count',
    'group_complexity_score'} or all-None if no entities were
    extracted."""
    if not entities:
        return {"entity_count": None, "domestic_count": None, "overseas_count": None, "trust_count": None, "group_complexity_score": None}
    n = len(entities)
    overseas = sum(1 for e in entities if e.get("is_overseas"))
    trusts = sum(1 for e in entities if e.get("is_trust"))
    domestic = n - overseas
    if n <= 5:
        score = 5
    elif n <= 10:
        score = 4
    elif n <= 20:
        score = 3
    elif n <= 35:
        score = 2
    else:
        score = 1
    return {"entity_count": n, "domestic_count": domestic, "overseas_count": overseas, "trust_count": trusts, "group_complexity_score": score}
