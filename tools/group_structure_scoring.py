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

# SEBI's LODR (Sixth Amendment) Regulations, 2021 (as further amended,
# effective November 2025) MANDATE that every material related-party
# transaction disclosure include a per-counterparty annexure captioned
# "ANNEXURE-<letter> (Transaction with <Entity Name>)" - this is a
# regulatory-mandated, generic caption format used across ANY NSE/BSE-
# listed company making such disclosures, not a company-specific
# phrasing. Confirmed real gap on Prime Fresh Limited: its RPT note names
# real subsidiaries/associates ONLY via this annexure-caption format (no
# entity is ever printed as "Name (NN%)" inline) - the primary
# `_ENTITY_WITH_PCT` pattern found nothing despite ~200+ "subsidiary"
# mentions on the page, because the entity names live in this different,
# equally standard disclosure shape instead.
_ANNEXURE_ENTITY_RE = re.compile(
    # Anchored to the boilerplate "Pursuant to the SEBI Circular" phrase
    # that immediately follows this caption in EVERY such disclosure
    # (mandated wording, not company-specific) rather than the first ")" -
    # the caption itself commonly contains a nested parenthetical (e.g.
    # "(Formerly Known as ...)") whose own closing ")" would otherwise
    # truncate the capture early.
    r"ANNEXURE[-\s]?[A-Z]\s*\(Transaction with\s+(.+?)\)\s*Pursuant to the SEBI Circular", re.I
)
# Only Ind AS 24/Companies Act CORPORATE relationship types belong in
# C.4.x's group-structure entity count - an individual related party
# (promoter/director/relative, also disclosed via this SAME annexure
# caption format) is a person, not a group entity, and must not be
# counted as a subsidiary/SPV/JV.
_INDIVIDUAL_PARTY_RE = re.compile(r"^(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s|\(DIN\s*:", re.I)
# The relationship type for an annexure-named entity is usually stated in
# the SAME or a nearby "Nature of Relationship"-labelled row/sentence
# (e.g. "Subsidiary Company", "Associate Concern", "Joint Venture") -
# checked in a window around each match, generic Ind AS 24/Companies Act
# relationship vocabulary, not company-specific.
_RELATIONSHIP_TYPE_RE = re.compile(
    r"\b(Subsidiary(?:\s+Company)?|Wholly[- ]Owned\s+Subsidiary|Associate(?:\s+Concern)?|"
    r"Joint\s+Venture|Step[- ]Down\s+Subsidiary)\b", re.I
)

# Form AOC-1 (Companies Act 2013, Section 129(3)/Rule 5) - "Statement
# containing salient features of the financial statement of
# subsidiaries/associate companies/joint ventures" - a THIRD, separately
# UNIVERSALLY MANDATED disclosure format (every Indian company with
# subsidiaries must file this exact statement), structurally different
# again from both `_ENTITY_WITH_PCT` and `_ANNEXURE_ENTITY_RE`: numbered
# rows of "S.No  Entity Name  Date of acquisition/incorporation
# Country..." with no inline percentage and no per-entity caption -
# anchored on the DATE that always immediately follows the entity name
# (DD-Mon-YY/YYYY, e.g. "8-Jun-10"), the one reliably-placed, non-
# company-specific landmark in this row shape. Confirmed real gap on
# Bharti Airtel: its 100+ subsidiaries are named ONLY in this AOC-1
# statement, never inline with a percentage nor via the SEBI RPT-
# annexure caption format.
_AOC1_ROW_RE = re.compile(
    r"\b\d{1,3}\s+([A-Z][\w&.'\-\(\)$ ]{2,80}?)\s+\d{1,2}[-\s][A-Za-z]{3}[-\s]\d{2,4}\b"
)


def extract_group_entities(text):
    """Parses the Related Party Disclosures note's own "Subsidiaries
    (Extent of holding)" listing - "EntityName (NN%)" - into structured
    rows. Dedups by entity name (case-insensitive). Returns
    [{'name','ownership_pct','is_trust','is_overseas','relationship'},
    ...] or [] if no such listing is present. Never raises.

    Falls back to the SEBI-mandated "ANNEXURE-X (Transaction with Entity
    Name)" caption format (see `_ANNEXURE_ENTITY_RE`'s comment) when the
    primary inline-percentage format isn't found at all - a genuinely
    different, equally standard RPT disclosure shape, not a company-
    specific pattern."""
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
        seen[key] = {"name": name, "ownership_pct": pct, "is_trust": is_trust, "is_overseas": is_overseas,
                     "relationship": None}
    if seen:
        return list(seen.values())

    for m in _ANNEXURE_ENTITY_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".,")
        if _INDIVIDUAL_PARTY_RE.search(name):
            continue  # a person (promoter/director/relative), not a group entity
        # "Formerly Known as ..." qualifiers are a name-change footnote,
        # not part of the operating entity's current legal name. The
        # capture group above stops right where this parenthetical's own
        # closing ")" would be (consumed by the outer pattern's literal
        # `\)\s*Pursuant`), so it's always unbalanced/open here - strip
        # from the opening "(Formerly Known as" to the end, not a
        # balanced-parens match.
        name = re.sub(r"\s*\(Formerly\s+Known\s+as.*$", "", name, flags=re.I).strip()
        key = name.lower()
        if key in seen or not name:
            continue
        window = text[m.end():m.end() + 500]
        rel_m = _RELATIONSHIP_TYPE_RE.search(window)
        is_overseas = bool(_FOREIGN_COUNTRY_HINT.search(name) or _FOREIGN_SUFFIX.search(name))
        is_trust = bool(_TRUST_HINT.search(name))
        seen[key] = {"name": name, "ownership_pct": None, "is_trust": is_trust, "is_overseas": is_overseas,
                     "relationship": rel_m.group(1) if rel_m else None}
    if seen:
        return list(seen.values())

    # Third fallback: Form AOC-1's numbered-row table (see
    # `_AOC1_ROW_RE`'s comment). A stray trailing note-marker (e.g. a
    # dangling "$" footnote reference, confirmed real on Bharti Airtel's
    # "Channel Sea Management Company (Mauritius) Limited $") is stripped
    # the same way a page/note reference is trimmed elsewhere in this
    # codebase - it's punctuation, never part of the legal name.
    for m in _AOC1_ROW_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip().rstrip("$*#").strip()
        if _INDIVIDUAL_PARTY_RE.search(name) or not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        is_overseas = bool(_FOREIGN_COUNTRY_HINT.search(name) or _FOREIGN_SUFFIX.search(name))
        is_trust = bool(_TRUST_HINT.search(name))
        seen[key] = {"name": name, "ownership_pct": None, "is_trust": is_trust, "is_overseas": is_overseas,
                     "relationship": None}
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
