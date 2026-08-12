"""
A.2.C — Cost leadership moat: deterministic (no-LLM) 0-5 evidence scorer.

Per the sheet's row 2C, this is the only A.2.x factor with TWO legs:
  - QUANT proxy: operating margin vs the peer set (identical Peer Set
    Protocol as the main Moat row — same NSE sector code, 0.4x-2.5x
    market-cap band), computed from real Screener data via
    tools/moat_peer_scoring.score_quant_pillars's `opm_level` pillar. Never
    text-scanned or estimated here.
  - QUALITATIVE confirmation: CRISIL/ICRA rationale or AR MD&A must NAME the
    SOURCE of the cost advantage (scale, captive raw material, proprietary
    process/technology) — a margin lead with no stated reason is quant-only
    evidence and scores lower, per the rubric below.

Deliberately does NOT call any LLM for the qualitative leg — same rationale
as tools/moat_brand_scoring.py / tools/moat_distribution_scoring.py.

Rubric:
  5 = a named cost-advantage source (AR or CRISIL) WITH a numeric/dated
      anchor — e.g. "captive limestone mine reduces cost per tonne by X%".
  4 = a named source with no anchor, or the same kind of evidence from a
      source >2 years stale.
  3 = operating margin is above the peer-set average (quant proxy only) but
      no source names WHY — a margin lead with no explained cause.
  2 = only generic company language ("cost efficient operations") with no
      margin data or explanation — MANAGEMENT_CLAIM.
  1 = only generic boilerplate phrasing, no specifics from any source.
  None (Missing) = no cost-structure commentary found AND no peer margin
      comparison available (quant leg also came back empty/insufficient).

Evidence categories (need >=1 keyword hit each to count as "covered"):
  scale_economies, captive_input, proprietary_technology
"""

import re

_CATEGORY_PATTERNS = {
    "scale_economies": [
        r"\beconomies of scale\b", r"\bscale advantage\b", r"\bscale efficienc\w*\b",
        r"\bcost per (?:unit|tonne)\b", r"\blowest cost producer\b", r"\blow[- ]cost producer\b",
        r"\bcost leadership\b",
    ],
    "captive_input": [
        r"\bcaptive mine\b", r"\bcaptive raw material\b", r"\bcaptive power\b",
        r"\bbackward integrat\w*\b", r"\bvertically integrated\b",
    ],
    "proprietary_technology": [
        r"\bproprietary technology\b", r"\bproprietary process\b", r"\bin-?house technology\b",
        r"\bpatented process\b",
    ],
}

_NUMERIC_ANCHOR = re.compile(
    r"\d+(?:\.\d+)?\s*%|"
    r"\bsince\s+\d{4}\b|"
    r"\bvs\.?\s+peers?\b|"
    r"\bcompared to peers?\b|"
    r"\blower than (?:the )?(?:industry|peers?|competitors?)\b|"
    r"\bover\s+\d+\s*years?\b"
)

_GENERIC_BOILERPLATE = re.compile(
    r"\b(?:cost efficient operations|cost-efficient operations|cost effective operations|"
    r"cost-effective operations|operational efficienc\w*)\b", re.I
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
    out = {}
    for sent in _sentences(text):
        low = sent.lower()
        for cat, patterns in _CATEGORY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, low, re.I):
                    out.setdefault(cat, []).append(sent)
                    break
    return out


def score_cost_leadership_moat(ar_mdna_text="", crisil_text="", business_description="",
                                opm_percentile=None):
    """
    Deterministic 0-5 cost-leadership score, combining the qualitative
    named-driver search (AR primary, CRISIL secondary — same ordering as
    Distribution, since a named cost-advantage source in the AR is treated
    as verifiable, not marketing prose) with the quant `opm_percentile`
    (0-100, from tools/moat_peer_scoring.score_quant_pillars's `opm_level`
    pillar — pass None if the peer set itself was unavailable).

    Returns:
      {"score": 0-5|None, "categories_covered": [...], "evidence_quote": "...",
       "source": "Annual Report MD&A"|"CRISIL rationale"|"MANAGEMENT_CLAIM"|
                  "peer margin comparison (quant only)"|"none",
       "reasoning": "...", "numeric_anchor": bool, "opm_percentile": ...}
    Never raises, never fabricates.
    """
    ar_matches = _matches_in(ar_mdna_text)
    crisil_matches = _matches_in(crisil_text)
    desc_matches = _matches_in(business_description)

    def _score_named(matches, source_label):
        categories = list(matches.keys())
        all_sentences = [s for sents in matches.values() for s in sents]
        has_anchor = any(_NUMERIC_ANCHOR.search(s) for s in all_sentences)
        best_sentence = next((s for s in all_sentences if _NUMERIC_ANCHOR.search(s)), all_sentences[0])
        if has_anchor:
            score = 5
            reasoning = f"{source_label} names a specific cost-advantage source ({', '.join(categories)}) with a numeric/comparative anchor."
        elif len(categories) >= 2:
            score = 4
            reasoning = f"{source_label} names cost-advantage sources across {len(categories)} categories ({', '.join(categories)}), but no numeric anchor."
        else:
            score = 3
            reasoning = f"{source_label} names a cost-advantage source ({categories[0]}), no numeric/comparative anchor."
        return {
            "score": score, "categories_covered": categories, "numeric_anchor": has_anchor,
            "evidence_quote": best_sentence[:300], "source": source_label, "reasoning": reasoning,
            "opm_percentile": opm_percentile,
        }

    # A NAMED source (AR primary, CRISIL secondary) always outranks a bare
    # margin lead — per the rubric, the "why" matters more than the number.
    if ar_matches:
        return _score_named(ar_matches, "Annual Report MD&A")
    if crisil_matches:
        return _score_named(crisil_matches, "CRISIL rationale")

    # No named source anywhere — fall back to the quant-only margin-lead
    # tier (3/5) if the peer comparison shows a real lead, per the rubric's
    # explicit "3/5 = margin lead, no explained cause" example.
    if opm_percentile is not None and opm_percentile > 50:
        return {
            "score": 3, "categories_covered": [], "numeric_anchor": False,
            "evidence_quote": "", "source": "peer margin comparison (quant only)",
            "reasoning": f"Operating margin ranks in the {opm_percentile}th percentile of its peer set "
                         f"(above average), but no CRISIL/ICRA rationale or AR MD&A names a reason why — "
                         f"a margin lead alone, not a confirmed structural cost advantage.",
            "opm_percentile": opm_percentile,
        }

    if desc_matches:
        categories = list(desc_matches.keys())
        all_sentences = [s for sents in desc_matches.values() for s in sents]
        return {
            "score": 2, "categories_covered": categories, "numeric_anchor": False,
            "evidence_quote": all_sentences[0][:300], "source": "MANAGEMENT_CLAIM",
            "reasoning": f"Cost-structure language ({', '.join(categories)}) found only in the company's own "
                         f"description, with no margin data or independent corroboration.",
            "opm_percentile": opm_percentile,
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
                    "reasoning": "Only generic cost-efficiency boilerplate found, no specifics or margin data in any evidence category.",
                    "opm_percentile": opm_percentile,
                }

    if opm_percentile is None:
        margin_note = "no peer margin comparison was available (peer set insufficient or operating-margin data missing)"
    else:
        margin_note = (f"the peer margin comparison shows only the {opm_percentile}th percentile "
                        f"(not an above-average lead)")
    return {
        "score": None, "categories_covered": [], "numeric_anchor": False,
        "evidence_quote": "", "source": "none",
        "reasoning": f"No named cost-advantage source found in Annual Report MD&A, CRISIL rationale, or company "
                     f"description, AND {margin_note}.",
        "opm_percentile": opm_percentile,
    }
