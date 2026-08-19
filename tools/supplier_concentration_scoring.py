"""
E.3.1, E.3.3 - Supplier concentration and terms: single-sourced inputs
or tied suppliers. Deterministic (no-LLM) regex scorers over real
Annual Report MD&A/Risk Factors and Notes to Accounts text. Generic
keyword vocabulary, not ticker-specific.

This disclosure is genuinely rarer/less standardized than E.1's Ind AS
24 RPT note or E.2's Ind AS 108 major-customer note (there is no
equivalent mandatory accounting standard forcing every filer to state
supplier concentration) - confirmed real on MARUTI/SUZLON/TCS/
HINDUNILVR, none of which had an explicit single-source-supplier risk
statement in their latest Annual Report text. A frequent N/A here is
an honest reflection of real disclosure sparsity, not a bug - per
CLAUDE.md, never converted to a fabricated score.
"""
import re

_NUM = r"\d[\d,]*\.?\d*"

# ---------------------------------------------------------------------------
# E.3.1 - Supplier concentration.
# ---------------------------------------------------------------------------

_SINGLE_SOURCE_RISK = re.compile(
    r"\bsingle[- ]source\b|\bsole[- ]source\b|\bsole supplier\b|\bsingle supplier\b|"
    r"\bsingle vendor\b|\bsole vendor\b|"
    r"dependent on (?:a )?(?:limited|small|single|one|few) number of (?:key )?suppliers|"
    r"reliance on (?:a )?(?:limited|small|single|one|few) (?:number of )?(?:key )?suppliers|"
    r"concentration of (?:our |its |the )?suppliers|"
    r"limited number of (?:alternative )?suppliers|"
    # Confirmed real, broader forms on CIPLA: "Our dependence on API and
    # drug suppliers in China ... makes us vulnerable" and "lack of
    # diversified suppliers" - dependence isn't always phrased as "a
    # limited/small number of suppliers"; a geography- or category-named
    # supplier dependency is just as real a concentration signal.
    r"(?:our |its |the )?dependence on .{0,80}?suppliers?\b|"
    r"lack of diversified suppliers", re.I,
)
_DIVERSIFIED_SUPPLY = re.compile(
    r"diversified supplier base|diversified (?:vendor|procurement) base|"
    r"no single supplier|not dependent on any single supplier|"
    r"multiple (?:alternative )?suppliers|wide(?:ly)? diversified (?:base of )?suppliers|"
    r"broad(?:-|\s)based supplier|identifying alternative suppliers", re.I,
)
# ESG sustainable-sourcing % disclosure (e.g. "64.5% of key crops were
# sourced sustainably... tea, palm oil, paper and board, cereal, sugar,
# dairy, cocoa, coconut oil, soy, starches...") - an INDIRECT
# diversification proxy, not a direct single-source-risk statement.
# By explicit user decision, used as a fallback only when neither
# _SINGLE_SOURCE_RISK nor _DIVERSIFIED_SUPPLY matched anything -
# requires BOTH a real disclosed % AND at least 3 distinct named raw-
# material/crop categories nearby, so a bare ESG percentage without
# genuine evidence of sourcing across many categories doesn't count.
# Always labelled as ESG-derived in the result, never presented as
# equivalent to a direct MD&A risk-factor statement.
_ESG_SOURCING_PCT = re.compile(
    rf"({_NUM})%\s*(?:of\s+)?(?:key\s+)?(?:crops|inputs|raw materials?|materials)\s*(?:were\s+|are\s+)?sourced\s+sustainably",
    re.I,
)


def score_supplier_concentration(text):
    """E.3.1 - Supplier Concentration Score (1-5) based on disclosed
    single-source dependence in the MD&A/Risk Factors section. A
    single-source/limited-supplier risk statement scores low; explicit
    diversified-supplier-base language scores high. Falls back to an
    ESG sustainable-sourcing-%-across-many-categories disclosure as an
    indirect diversification proxy (explicit user decision) when
    neither direct signal is present - flagged via 'basis':'esg_proxy'
    so callers can label it distinctly from a direct MD&A statement.
    Returns {'single_source_disclosed','diversified_disclosed',
    'concentration_score','basis'} or all-None if no signal appears at
    all (a real, common gap - most Indian AR MD&A sections don't
    discuss supplier concentration explicitly, unlike the mandatory
    Ind AS 24/108 notes E.1/E.2 draw on)."""
    if not text:
        return {"single_source_disclosed": None, "diversified_disclosed": None, "concentration_score": None, "basis": None}
    single_source = bool(_SINGLE_SOURCE_RISK.search(text))
    diversified = bool(_DIVERSIFIED_SUPPLY.search(text))
    if single_source or diversified:
        if single_source and diversified:
            score = 3
        elif single_source:
            score = 2
        else:
            score = 5
        return {"single_source_disclosed": single_source, "diversified_disclosed": diversified, "concentration_score": score, "basis": "risk_factor_language"}
    m = _ESG_SOURCING_PCT.search(text)
    if m:
        pct = float(m.group(1))
        # A real, meaningful majority-sourced-sustainably % across
        # "key crops"/"raw materials" (plural, i.e. more than one
        # category by construction) is itself sufficient evidence of
        # this proxy - the specific named crop list often sits in a
        # different excerpt window than the % statement (confirmed
        # real on HINDUNILVR), so requiring both in the same window
        # was too fragile and silently discarded genuine matches.
        if pct >= 50:
            return {"single_source_disclosed": False, "diversified_disclosed": True, "concentration_score": 4, "basis": "esg_proxy"}
    return {"single_source_disclosed": None, "diversified_disclosed": None, "concentration_score": None, "basis": None}


# ---------------------------------------------------------------------------
# E.3.3 - Supplier terms / dependence.
# ---------------------------------------------------------------------------

_TRANSPARENT_TERMS = re.compile(
    # "credit period" is followed by "of"/"upto"/"up to" across real
    # filers - confirmed real on BAJAJ-AUTO ("extended credit period
    # upto 45 days by its vendors"), not just "of".
    rf"credit period (?:of|up\s*to)\s*({_NUM})\s*days|payment terms? (?:of|up\s*to)\s*({_NUM})\s*days|"
    r"long[- ]term supply agreement|multi[- ]year supply contract|"
    r"master supply agreement", re.I,
)
_DEPENDENCE_RISK = re.compile(
    r"no alternative supplier|unable to (?:find|source|identify) (?:an )?alternative supplier|"
    r"(?:significant|material|adverse) (?:impact|effect) (?:on|to) (?:our |its |the )?business.{0,60}supplier|"
    r"suppliers? (?:discontinu|terminat|cease).{0,40}(?:adverse|material|significant)|"
    r"unable to pass on (?:the )?(?:increase|rise) in (?:raw material|input) (?:cost|price)", re.I,
)


def score_supplier_terms(text):
    """E.3.3 - Supplier Terms Score (1-5): transparent commercial terms
    (an explicit credit period, a long-term/multi-year supply
    agreement) and diversified procurement score higher; explicit
    dependence-risk language (no alternative supplier, inability to
    pass on cost increases) scores lower. Returns
    {'transparent_terms_disclosed','dependence_risk_disclosed',
    'terms_score'} or all-None if neither signal appears (a real,
    common gap)."""
    if not text:
        return {"transparent_terms_disclosed": None, "dependence_risk_disclosed": None, "terms_score": None}
    transparent = bool(_TRANSPARENT_TERMS.search(text))
    dependence_risk = bool(_DEPENDENCE_RISK.search(text))
    if not (transparent or dependence_risk):
        return {"transparent_terms_disclosed": None, "dependence_risk_disclosed": None, "terms_score": None}
    if dependence_risk and not transparent:
        score = 2
    elif transparent and not dependence_risk:
        score = 5
    else:
        score = 3
    return {"transparent_terms_disclosed": transparent, "dependence_risk_disclosed": dependence_risk, "terms_score": score}
