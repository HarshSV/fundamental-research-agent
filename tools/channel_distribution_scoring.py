"""
Section G - Customers, channels & distribution. Deterministic (no-LLM)
scorers over real Annual Report MD&A / Business Model / Distribution
Network / Related Party Disclosures text, mirroring the established
dimension-counting pattern used for F.1.3/F.2.1 (tools/entry_barrier_
scoring.py) - generic keyword/regex logic, not ticker-specific, per
CLAUDE.md.

G1.1 Channel mix, G1.2 Channel control, G2.1 Group-channel overlap,
G3.1 Contract duration/renewal, G3.2 Customer churn/retention,
G4.1 Distribution reach, G4.2 Peer distribution advantage.

The framework's stated formulas (e.g. G1.1's "Channel Mix % = Revenue by
Channel / Total Revenue where disclosed") describe an ideal numeric
extraction that Indian AR MD&A prose essentially never supports as a
clean per-channel revenue table (same documented limitation already
noted for A.1.2/A.3's segment-revenue text) - these scorers therefore
count named, evidenced disclosure dimensions rather than fabricate a
percentage the source text doesn't actually contain, consistent with the
1-5 "specificity of real evidence" convention already used throughout
the A.2.x/F.1.x/F.2.1 sub-points.
"""
import re

_CHANNEL_TYPES = {
    "direct": re.compile(r"\bdirect\s+(?:sales?|channel|distribution)\b|direct-to-consumer|\bd2c\b", re.I),
    "retail": re.compile(r"\bretail\s+(?:store|outlet|channel|network)s?\b|company[\s-]owned\s+stores?", re.I),
    "distributor_dealer": re.compile(r"\bdistributors?\b|\bdealers?\b|\bwholesalers?\b|\bstockists?\b", re.I),
    "ecommerce": re.compile(r"\be-?commerce\b|online\s+(?:channel|platform|sales)|digital\s+channel", re.I),
    "exports_international": re.compile(r"\bexports?\b|international\s+(?:channel|markets?|distribution)", re.I),
    "franchisee": re.compile(r"\bfranchisee?s?\b|franchise\s+(?:model|network|store)", re.I),
}

_OWNED_CONTROL_RE = re.compile(
    r"company[\s-]owned\s+(?:stores?|outlets?|showrooms?)|own(?:ed)?\s+retail\s+network|"
    r"captive\s+(?:distribution|channel)|wholly[\s-]owned\s+distribution",
    re.I,
)
_THIRDPARTY_CONTROL_RE = re.compile(
    r"third[\s-]party\s+distributors?|independent\s+distributors?|"
    r"rely(?:ing|s)?\s+on\s+(?:third[\s-]party|independent)\s+distributors?|"
    r"appointed\s+distributors?|franchise[ed]*\s+model",
    re.I,
)

# Requires a group/related-party ENTITY mention to co-occur with actual
# distribution/channel-relevant language nearby - a bare "related party"
# hit anywhere in a company's RPT note (present in virtually every listed
# company's financial statements, for equity investments, service fees,
# loans, etc.) is not evidence of a CHANNEL conflict specifically.
# Confirmed real over-triggering: RELIANCE/TATASTEEL/SUZLON/TCS all
# scored identically off unrelated RPT-table boilerplate before this fix.
_GROUP_ENTITY_BARE_RE = re.compile(
    r"group\s+compan(?:y|ies)|related\s+part(?:y|ies)|promoter\s+group\s+entit(?:y|ies)|"
    r"associate\s+compan(?:y|ies)|subsidiary\s+distributor",
    re.I,
)
_DISTRIBUTION_CONTEXT_RE = re.compile(
    r"distribut|dealer|retail|channel|stockist|wholesal|sales?\s+agent|franchise",
    re.I,
)


def _group_entity_with_distribution_context(text, window=150):
    for m in _GROUP_ENTITY_BARE_RE.finditer(text):
        ctx = text[max(0, m.start() - window):m.end() + window]
        if _DISTRIBUTION_CONTEXT_RE.search(ctx):
            return True
    return False
_GOVERNANCE_CONTROL_RE = re.compile(
    r"arm's[\s-]length|audit\s+committee\s+approv|no\s+conflict\s+of\s+interest|"
    r"independent\s+(?:valuation|pricing)|competitive\s+bidding",
    re.I,
)

_CONTRACT_TERM_RE = re.compile(
    r"(\d{1,3})[\s-]?(?:year|yr)s?\s+contract|contract\s+(?:period|term|duration)\s+of\s+(\d{1,3})|"
    r"long[\s-]term\s+(?:agreements?|contracts?)|multi[\s-]year\s+(?:agreements?|contracts?)",
    re.I,
)
_RENEWAL_RE = re.compile(
    r"renewal\s+rate|contracts?\s+renewed|order\s+book|repeat\s+(?:orders?|business|customers?)",
    re.I,
)

_RETENTION_METRIC_RE = re.compile(
    r"(?:customer\s+)?retention\s+rate\s+of\s+(\d{1,3})|churn\s+rate\s+of\s+(\d{1,3})|"
    r"(\d{1,3})\s*%\s*(?:customer\s+)?retention",
    re.I,
)
_RETENTION_LANGUAGE_RE = re.compile(
    r"customer\s+retention|churn\s+rate|repeat\s+customers?|customer\s+attrition|repeat\s+purchase",
    re.I,
)

_REACH_NUMERIC_RE = re.compile(
    r"(\d[\d,]{1,7})\s*\+?\s*(?:dealers?|distributors?|retail\s+outlets?|stores?|touch\s*points?|"
    r"service\s+centers?|service\s+centres?)",
    re.I,
)
_REACH_QUALITATIVE_RE = re.compile(
    r"pan[\s-]india\s+(?:network|presence|reach)|nationwide\s+(?:network|presence)|"
    r"across\s+\d{1,3}\s*(?:states|cities|districts|countries)",
    re.I,
)

_PEER_COMPARISON_RE = re.compile(
    r"(?:largest|widest|wider|broader|deepest|deeper)\s+(?:distribution\s+)?(?:network|reach|presence)"
    r"(?:\s+(?:than|compared\s+to|among|in)\s+(?:its\s+)?(?:peers?|competitors?|industry))?|"
    r"(?:compared\s+to|versus|among)\s+(?:its\s+)?(?:peers?|competitors?).{0,60}?(?:network|reach|presence|distribution)",
    re.I,
)


def score_channel_mix(text):
    """G1.1 - Channel mix. Counts distinct named channel TYPES
    (direct/retail/distributor/e-commerce/exports/franchisee) actually
    disclosed. Returns {'channels_identified', 'channel_mix_score'} or
    all-None if no channel is named."""
    if not text:
        return {"channels_identified": None, "channel_mix_score": None}
    found = [k for k, pat in _CHANNEL_TYPES.items() if pat.search(text)]
    if not found:
        return {"channels_identified": None, "channel_mix_score": None}
    score = {1: 2, 2: 3}.get(len(found), 5 if len(found) >= 4 else 4)
    return {"channels_identified": found, "channel_mix_score": score}


def score_channel_control(text):
    """G1.2 - Channel control. Owned-network language scores higher than
    third-party-only language; both present scores a balanced middle;
    neither found returns None (genuinely not discussed)."""
    if not text:
        return {"control_basis": None, "channel_control_score": None}
    owned = bool(_OWNED_CONTROL_RE.search(text))
    third_party = bool(_THIRDPARTY_CONTROL_RE.search(text))
    if not owned and not third_party:
        return {"control_basis": None, "channel_control_score": None}
    if owned and third_party:
        basis, score = "mixed", 3
    elif owned:
        basis, score = "owned", 5
    else:
        basis, score = "third_party", 2
    return {"control_basis": basis, "channel_control_score": score}


def score_channel_conflict(text):
    """G2.1 - Group-channel overlap. A disclosed group/related-party
    channel entity WITHOUT any documented governance control (arm's-
    length, audit-committee approval, competitive bidding) scores low;
    the same overlap WITH documented governance controls scores high;
    no group-entity overlap disclosed at all returns None (genuinely not
    applicable/not found, never fabricated as a clean score)."""
    if not text:
        return {"group_overlap_found": None, "governance_controls_found": None, "channel_conflict_score": None}
    overlap = _group_entity_with_distribution_context(text)
    if not overlap:
        return {"group_overlap_found": None, "governance_controls_found": None, "channel_conflict_score": None}
    governed = bool(_GOVERNANCE_CONTROL_RE.search(text))
    score = 4 if governed else 2
    return {"group_overlap_found": True, "governance_controls_found": governed, "channel_conflict_score": score}


def score_contract_quality(text):
    """G3.1 - Contract duration / renewal. A specific contract-term
    disclosure (years) scores higher than generic renewal/order-book
    language alone; neither returns None."""
    if not text:
        return {"specific_term_disclosed": None, "renewal_language_found": None, "contract_quality_score": None}
    term_match = _CONTRACT_TERM_RE.search(text)
    renewal = bool(_RENEWAL_RE.search(text))
    if not term_match and not renewal:
        return {"specific_term_disclosed": None, "renewal_language_found": None, "contract_quality_score": None}
    if term_match:
        score = 5 if renewal else 4
    else:
        score = 3
    return {"specific_term_disclosed": bool(term_match), "renewal_language_found": renewal, "contract_quality_score": score}


def score_customer_retention(text):
    """G3.2 - Customer churn / retention. A disclosed numeric retention/
    churn % scores highest; qualitative retention language without a
    number scores mid; nothing found returns NOT_DISCLOSED (per the
    framework's own explicit instruction: "mark NOT_DISCLOSED if no
    metric exists")."""
    if not text:
        return {"retention_pct": None, "retention_score": None, "status": "NOT_DISCLOSED"}
    m = _RETENTION_METRIC_RE.search(text)
    if m:
        pct = next((g for g in m.groups() if g), None)
        return {"retention_pct": float(pct) if pct else None, "retention_score": 5, "status": "FOUND"}
    if _RETENTION_LANGUAGE_RE.search(text):
        return {"retention_pct": None, "retention_score": 3, "status": "FOUND"}
    return {"retention_pct": None, "retention_score": None, "status": "NOT_DISCLOSED"}


def score_distribution_reach(text):
    """G4.1 - Distribution reach. A specific numeric network count
    (e.g. "12,000 dealers") scores highest; qualitative pan-India/
    nationwide language without a number scores mid; neither returns
    None."""
    if not text:
        return {"reach_count": None, "reach_score": None}
    m = _REACH_NUMERIC_RE.search(text)
    if m:
        try:
            count = int(m.group(1).replace(",", ""))
        except Exception:
            count = None
        return {"reach_count": count, "reach_score": 5}
    if _REACH_QUALITATIVE_RE.search(text):
        return {"reach_count": None, "reach_score": 3}
    return {"reach_count": None, "reach_score": None}


def score_peer_distribution_advantage(text):
    """G4.2 - Peer distribution advantage. Requires EXPLICIT comparison
    language to peers/competitors/industry (not just this company's own
    reach numbers) - a company merely describing its own network is not
    evidence of a peer-relative claim, so this is intentionally stricter
    than G4.1."""
    if not text:
        return {"peer_comparison_found": None, "peer_distribution_score": None}
    if _PEER_COMPARISON_RE.search(text):
        return {"peer_comparison_found": True, "peer_distribution_score": 4}
    return {"peer_comparison_found": None, "peer_distribution_score": None}
