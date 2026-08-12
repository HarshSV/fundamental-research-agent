"""
A.2.B — Distribution moat: deterministic (no-LLM) 0-5 evidence scorer.

Per the sheet's row 2B: score 0-5 from AR MD&A/investor presentation
(PRIMARY) and CRISIL/ICRA rationale (SECONDARY), on distribution network
reach, exclusivity, and channel depth vs named competitors.

Deliberately does NOT call any LLM — same rationale as
tools/moat_brand_scoring.py (reproducible, auditable, avoids the shared
Groq/OpenRouter quota for a 2,409-company bulk run).

IMPORTANT source-hierarchy difference from Brand (2A): for Distribution, a
SPECIFIC, NUMERIC, DATED claim in the Annual Report itself ("18,000 outlets
across 22 states, per FY24 AR") is PRIMARY evidence and can reach 5/5 on its
own — it is NOT capped at MANAGEMENT_CLAIM the way Brand's own-words
evidence is, because operational distribution stats disclosed in a
regulated Annual Report filing are treated as verifiable facts, not
marketing prose. Only UNQUANTIFIED company language ("pan-India presence",
"wide network", no numbers) is capped at 2/5 and tagged MANAGEMENT_CLAIM.

Rubric:
  5 = a specific claim (AR or CRISIL) with a numeric/named/dated anchor —
      exclusivity term, dealer/outlet count, state count, "as of FY24".
  4 = a specific claim with no anchor, or the same kind of evidence from a
      source >2 years stale.
  3 = a claim touching only ONE evidence category, no anchor.
  2 = only generic, unquantified company language anywhere ("pan-India
      presence") with no count/exclusivity/date — MANAGEMENT_CLAIM.
  1 = only generic boilerplate phrasing, no specifics from any source.
  None (Missing) = no distribution-evidence keyword found in ANY source text.

Evidence categories (need >=1 keyword hit each to count as "covered"):
  exclusivity, network_reach, competitive_depth
"""

import re

_CATEGORY_PATTERNS = {
    "exclusivity": [
        r"\bexclusive distribut\w*\b", r"\bexclusive dealer\w*\b", r"\bexclusive agreement\b",
        r"\bsole distributor\b", r"\bsole dealer\b",
    ],
    "network_reach": [
        r"\bdistribution network\b", r"\bdealer network\b", r"\bdistributor network\b",
        r"\bdealers? across\b", r"\bdistributors? across\b", r"\bretail outlets?\b",
        r"\bsales outlets?\b", r"\bfranchise\w*\b", r"\bchannel partners?\b",
        r"\bsales network\b", r"\btouchpoints?\b", r"\bstates and union territories\b",
        r"\bnetwork of (?:dealers|distributors)\b",
    ],
    "competitive_depth": [
        r"\bwider (?:network|reach|distribution)\b", r"\bdeeper (?:network|reach|penetration)\b",
        r"\bbroader (?:network|reach|distribution)\b", r"\bmarket penetration\b",
    ],
}

# Broader than Brand's numeric anchor — a dealer/outlet/state COUNT or a
# fiscal-year/"as of" date is exactly the kind of concrete anchor this
# rubric's 5/5 tier requires.
_NUMERIC_ANCHOR = re.compile(
    r"\d+(?:,\d{3})*\s*(?:dealers?|distributors?|outlets?|states?|touchpoints?|franchisees?)|"
    r"\d+(?:\.\d+)?\s*%|"
    r"\bsince\s+\d{4}\b|"
    r"\bthrough\s+fy\s?\d{2,4}\b|"
    r"\bas of\s+(?:fy\s?\d{2,4}|march\s+\d{4}|\d{4})\b|"
    r"\bover\s+\d+\s*years?\b|"
    r"\bexclusive\b"
)

_GENERIC_BOILERPLATE = re.compile(
    r"\b(?:pan[- ]india presence|wide(?:spread)? (?:distribution|network)|strong (?:distribution|network)|"
    r"extensive network|robust (?:distribution|network))\b", re.I
)


def _sentences(text):
    if not text:
        return []
    # PDF-extracted text routinely line-wraps MID-PHRASE (table/form layouts
    # splitting a two-word term across lines — confirmed on HDFCLIFE's
    # "Persistency"/"ratio") — splitting on every newline the way a
    # prose-sentence splitter would broke those phrases apart entirely, so
    # newlines are normalized to spaces first and only real sentence-ending
    # punctuation is treated as a boundary.
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _matches_in(text):
    """Returns {category: [matched sentences]} for the given text."""
    out = {}
    for sent in _sentences(text):
        low = sent.lower()
        for cat, patterns in _CATEGORY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, low, re.I):
                    out.setdefault(cat, []).append(sent)
                    break
    return out


def score_distribution_moat(ar_mdna_text="", crisil_text="", business_description=""):
    """
    Deterministic 0-5 distribution-moat score.

    `ar_mdna_text` (real Annual Report MD&A/Business Overview excerpts, see
    tools/annual_report_financials.fetch_distribution_evidence_from_annual_report)
    is PRIMARY — a specific+numeric AR claim can reach 5/5 on its own.
    `crisil_text` is SECONDARY, scored the same way when AR has nothing.
    `business_description` (yfinance blurb) is capped at 2/5/MANAGEMENT_CLAIM
    — treated the same as Brand's own-words tier, since it's the company's
    own unaudited marketing summary, not a regulated AR disclosure.

    Returns:
      {"score": 0-5|None, "categories_covered": [...], "evidence_quote": "...",
       "source": "Annual Report MD&A"|"CRISIL rationale"|"MANAGEMENT_CLAIM"|"none",
       "reasoning": "...", "numeric_anchor": bool}
    Never raises, never fabricates.
    """
    ar_matches = _matches_in(ar_mdna_text)
    crisil_matches = _matches_in(crisil_text)
    desc_matches = _matches_in(business_description)

    def _score_specific(matches, source_label):
        categories = list(matches.keys())
        all_sentences = [s for sents in matches.values() for s in sents]
        has_anchor = any(_NUMERIC_ANCHOR.search(s) for s in all_sentences)
        best_sentence = next((s for s in all_sentences if _NUMERIC_ANCHOR.search(s)), all_sentences[0])
        if has_anchor:
            score = 5
            reasoning = f"{source_label} carries specific, verifiable distribution evidence ({', '.join(categories)}) with a numeric/dated anchor."
        elif len(categories) >= 2:
            score = 4
            reasoning = f"{source_label} carries specific distribution evidence across {len(categories)} categories ({', '.join(categories)}), but no numeric/dated anchor."
        else:
            score = 3
            reasoning = f"{source_label} touches only one distribution-evidence category ({categories[0]}), no numeric/dated anchor."
        return {
            "score": score, "categories_covered": categories, "numeric_anchor": has_anchor,
            "evidence_quote": best_sentence[:300], "source": source_label, "reasoning": reasoning,
        }

    # PRIMARY: Annual Report MD&A / investor presentation proxy.
    if ar_matches:
        return _score_specific(ar_matches, "Annual Report MD&A")

    # SECONDARY: CRISIL/ICRA rationale, same tiering.
    if crisil_matches:
        return _score_specific(crisil_matches, "CRISIL rationale")

    # Neither primary nor secondary found anything specific — check for
    # generic, unquantified company language (own words, capped at 2) or
    # bare boilerplate (1), else Missing.
    if desc_matches:
        categories = list(desc_matches.keys())
        all_sentences = [s for sents in desc_matches.values() for s in sents]
        return {
            "score": 2, "categories_covered": categories, "numeric_anchor": False,
            "evidence_quote": all_sentences[0][:300], "source": "MANAGEMENT_CLAIM",
            "reasoning": f"Distribution-evidence language ({', '.join(categories)}) found only in the company's own "
                         f"description — no count, exclusivity term, or date; no AR/CRISIL corroboration.",
        }

    has_boilerplate = bool(_GENERIC_BOILERPLATE.search(ar_mdna_text or "") or
                            _GENERIC_BOILERPLATE.search(crisil_text or "") or
                            _GENERIC_BOILERPLATE.search(business_description or ""))
    if has_boilerplate:
        for src_text, label in ((ar_mdna_text, "Annual Report MD&A"), (crisil_text, "CRISIL rationale"),
                                 (business_description, "MANAGEMENT_CLAIM")):
            m = _GENERIC_BOILERPLATE.search(src_text or "")
            if m:
                return {
                    "score": 1, "categories_covered": [], "numeric_anchor": False,
                    "evidence_quote": src_text[max(0, m.start() - 40):m.end() + 40].strip(),
                    "source": label,
                    "reasoning": "Only generic boilerplate distribution language found, no specifics in any evidence category.",
                }

    return {
        "score": None, "categories_covered": [], "numeric_anchor": False,
        "evidence_quote": "", "source": "none",
        "reasoning": "No distribution-evidence keywords found in Annual Report MD&A, CRISIL rationale, or company description.",
    }
