"""
A.2.D - Network effects moat: deterministic (no-LLM) 0-5 evidence scorer.

Per the sheet's row 2D: evidence that each ADDITIONAL user/customer
measurably increases value to EXISTING users - e.g. GMV or transaction-value
growth tracked AGAINST user-base growth on a platform/marketplace. The mere
PRESENCE of a platform/marketplace business model is explicitly NOT evidence
of a network effect by itself; the growth LINKAGE must be shown.

Deliberately does NOT call any LLM - same rationale as the other A.2.x
scorers (reproducible, auditable, avoids the shared Groq/OpenRouter quota).

IMPORTANT - this factor has a THIRD outcome besides a 0-5 score: "N/A". A
company with no platform/marketplace element in its business AT ALL is N/A,
never a low score - per the spec, a low score implies the evidence was
checked and found weak, which would be a false implication for a business
model (e.g. a cement manufacturer) where the question doesn't even apply.

Rubric (only reached once a platform/marketplace element is confirmed
present - see `has_platform_element` below):
  5 = actual growth-linkage data (a value metric like GMV/transaction value
      AND a user/seller/buyer-base metric, BOTH with growth figures, shown
      together) - e.g. "GMV grew 40% as active users grew 25%".
  4 = same kind of linkage evidence but a single data point, or stale (>2yr).
  3 = described as a platform/marketplace with NO data connecting user
      growth to value/engagement growth - presence only, no linkage.
  2 = only the company's own platform language, no independent
      corroboration (MANAGEMENT_CLAIM) - same "own words, no third-party
      support" distinction the other A.2.x factors use.
  1 = vague boilerplate only.
  N/A = no platform/marketplace element anywhere in the evidence at all.

Evidence categories (need >=1 keyword hit each to count as "covered"):
  platform_presence, growth_linkage
"""

import re

# Bare "platform"/"ecosystem"/"marketplace"/"online platform(s)" are
# deliberately excluded - confirmed false positives on generic corporate
# boilerplate, ordinary "the marketplace" = "the market" English usage, and
# a company merely SELLING THROUGH third-party platforms rather than owning
# one (see tools/annual_report_financials.py's matching anchor list - MUST
# stay in sync, since that fetcher supplies the text scored here).
_PLATFORM_PATTERNS = [
    r"\bnetwork effects?\b", r"\btwo[- ]sided market\b", r"\baggregator model\b",
    r"\bgig economy\b", r"\bmarketplace model\b", r"\bmarketplace business\b",
    r"\bmarketplace platform\b", r"\bour marketplace\b", r"\bdigital marketplace\b",
    r"\bonline marketplace\b", r"\be-?commerce platform\b", r"\b(?:our|the) platform connects\b",
    r"\bplatform business model\b", r"\bplatform-based business\b",
    r"\bbuyers and sellers\b", r"\bsellers and buyers\b",
    # v2: "network of merchants"/"merchant partners"/"merchant network" -
    # confirmed false negative on RELIANCE (JioMart Digital: "partners with
    # a large network of merchants nationwide for distribution") - MUST stay
    # in sync with tools/annual_report_financials.py's
    # _NETWORK_EFFECTS_PLATFORM_ANCHORS, which supplies this text.
    r"\bnetwork of merchants\b", r"\bmerchant partners\b", r"\bmerchant network\b",
]

_GROWTH_LINKAGE_PATTERNS = [
    r"\bgross merchandise value\b", r"\bgmv\b", r"\btransaction value\b",
]
_USER_METRIC_PATTERNS = [
    r"\bactive users?\b", r"\bmonthly active users?\b", r"\bregistered users?\b",
    r"\buser base\b", r"\bseller base\b", r"\bbuyer base\b",
    # v2: merchant-side growth vocabulary, same rationale/sync requirement as above.
    r"\bmerchant base\b", r"\bmerchant engagement\b",
    r"\bexpanding customer base\b", r"\bgrowing customer base\b",
]

_NUMERIC_ANCHOR = re.compile(r"\d+(?:\.\d+)?\s*%")

_GENERIC_BOILERPLATE = re.compile(
    r"\b(?:leading platform|leading marketplace|growing (?:platform|ecosystem)|"
    r"vibrant (?:platform|ecosystem|marketplace))\b", re.I
)


def _sentences(text):
    if not text:
        return []
    # PDF-extracted text routinely line-wraps MID-PHRASE (table/form layouts
    # splitting a two-word term across lines - confirmed on HDFCLIFE's
    # "Persistency"/"ratio") - splitting on every newline the way a
    # prose-sentence splitter would broke those phrases apart entirely, so
    # newlines are normalized to spaces first and only real sentence-ending
    # punctuation is treated as a boundary.
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _has_platform_element(*texts):
    """Gate for the N/A branch - True the moment ANY text carries platform/
    marketplace language anywhere (not sentence-scoped, unlike the rubric
    scoring below, since this is just an applicability check)."""
    for t in texts:
        low = (t or "").lower()
        if any(re.search(p, low, re.I) for p in _PLATFORM_PATTERNS):
            return True
    return False


def _growth_linkage_sentences(text):
    """Sentences that name BOTH a value-growth metric (GMV/transaction
    value) AND a user/seller/buyer-base metric - the actual linkage the
    rubric requires, not just platform existence."""
    out = []
    for sent in _sentences(text):
        low = sent.lower()
        has_value = any(re.search(p, low, re.I) for p in _GROWTH_LINKAGE_PATTERNS)
        has_user = any(re.search(p, low, re.I) for p in _USER_METRIC_PATTERNS)
        if has_value and has_user:
            out.append(sent)
    return out


def _platform_presence_sentences(text):
    return [s for s in _sentences(text) if any(re.search(p, s.lower(), re.I) for p in _PLATFORM_PATTERNS)]


def score_network_effects_moat(ar_mdna_text="", business_description="", industry_report_text=""):
    """
    Deterministic score for network-effects evidence, or "N/A" when the
    business has no platform/marketplace element at all.

    `ar_mdna_text` (real AR MD&A excerpts, see
    tools/annual_report_financials.fetch_network_effects_evidence_from_annual_report)
    is PRIMARY. `industry_report_text` (currently unwired - no industry-
    report source exists in this codebase yet) and `business_description`
    are SECONDARY/own-words, capped at 2/5 and tagged MANAGEMENT_CLAIM.

    Returns:
      {"score": 0-5|None, "applicable": bool, "categories_covered": [...],
       "evidence_quote": "...", "source": "...", "reasoning": "...",
       "numeric_anchor": bool}
    `applicable=False` is the N/A case - `score` is None but the caller must
    NOT read that as "Missing"/low evidence, only as "doesn't apply".
    """
    combined_for_gate = "\n".join(t for t in (ar_mdna_text, business_description, industry_report_text) if t)
    if not _has_platform_element(combined_for_gate):
        return {
            "score": None, "applicable": False, "categories_covered": [], "numeric_anchor": False,
            "evidence_quote": "", "source": "none",
            "reasoning": "No platform/marketplace element found in this company's business at all - "
                         "network effects is Not Applicable, not a low score.",
        }

    # PRIMARY: real AR MD&A growth-linkage evidence.
    ar_linkage = _growth_linkage_sentences(ar_mdna_text)
    if ar_linkage:
        has_anchor = any(_NUMERIC_ANCHOR.search(s) for s in ar_linkage)
        best = next((s for s in ar_linkage if _NUMERIC_ANCHOR.search(s)), ar_linkage[0])
        score = 5 if has_anchor else 4
        reasoning = (
            "Annual Report MD&A shows an actual growth-linkage figure connecting user/seller/buyer-base "
            "growth to value (GMV/transaction-value) growth." if has_anchor else
            "Annual Report MD&A mentions both a value metric and a user-base metric together, but without "
            "a clear numeric growth figure tying them - treated as linkage evidence with no anchor."
        )
        return {
            "score": score, "applicable": True, "categories_covered": ["platform_presence", "growth_linkage"],
            "numeric_anchor": has_anchor, "evidence_quote": best[:300], "source": "Annual Report MD&A",
            "reasoning": reasoning,
        }

    # No linkage anywhere - platform/marketplace is merely DESCRIBED. Per
    # the rubric, presence alone (whether from AR or the company's own
    # description) caps at 3, and only 3 if there's at least a genuine AR
    # mention (not just the yfinance blurb) - otherwise 2 (MANAGEMENT_CLAIM).
    ar_presence = _platform_presence_sentences(ar_mdna_text)
    if ar_presence:
        return {
            "score": 3, "applicable": True, "categories_covered": ["platform_presence"], "numeric_anchor": False,
            "evidence_quote": ar_presence[0][:300], "source": "Annual Report MD&A",
            "reasoning": "Annual Report MD&A describes the business as a platform/marketplace, but no data "
                         "connects user/seller/buyer growth to value or engagement growth - presence only.",
        }

    desc_presence = _platform_presence_sentences(business_description)
    if desc_presence:
        return {
            "score": 2, "applicable": True, "categories_covered": ["platform_presence"], "numeric_anchor": False,
            "evidence_quote": desc_presence[0][:300], "source": "MANAGEMENT_CLAIM",
            "reasoning": "Only the company's own description calls this a platform/marketplace, with no "
                         "independent AR MD&A corroboration and no growth-linkage data.",
        }

    if _GENERIC_BOILERPLATE.search(combined_for_gate):
        m = _GENERIC_BOILERPLATE.search(combined_for_gate)
        return {
            "score": 1, "applicable": True, "categories_covered": [], "numeric_anchor": False,
            "evidence_quote": combined_for_gate[max(0, m.start() - 40):m.end() + 40].strip(), "source": "MANAGEMENT_CLAIM",
            "reasoning": "Only generic platform/ecosystem boilerplate found, no specifics or growth-linkage data.",
        }

    # Reached only if `_has_platform_element` matched on the combined text
    # but neither of the more precise per-source checks above found it -
    # a residual edge case (e.g. the match was in industry_report_text,
    # which isn't wired to a real source yet). Still applicable, still
    # Missing-equivalent within "applicable", not N/A.
    return {
        "score": None, "applicable": True, "categories_covered": [], "numeric_anchor": False,
        "evidence_quote": "", "source": "none",
        "reasoning": "A platform/marketplace element was detected, but no specific, attributable evidence "
                     "was located in Annual Report MD&A or the company description.",
    }
