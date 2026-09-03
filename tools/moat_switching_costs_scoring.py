"""
A.2.E - Switching costs moat: deterministic (no-LLM) 0-5 evidence scorer.

Per the sheet's row 2E: evidence a customer faces real friction (financial,
operational, contractual, or regulatory) to switch to a competitor - not
just that customers "seem loyal."

Deliberately does NOT call any LLM - same rationale as the other A.2.x
scorers (reproducible, auditable, avoids the shared Groq/OpenRouter quota).

Rubric - note the 5/5 tier specifically requires BOTH a contract-term
length AND a renewal-rate percentage cited TOGETHER, not just one:
  5 = a contract-term length (e.g. "5-year contract") AND a renewal-rate %
      (e.g. "92% renewal rate") both cited, in the same evidence pool.
  4 = the same kind of evidence but only ONE of the two (a term length OR a
      renewal rate, with an actual number), or a regulatory/certification
      switching barrier named specifically - or the same as 5/5 but stale
      (>2yr, not distinguished here since this codebase doesn't track filing
      recency at the sentence level; treated as 4 conservatively when only
      one metric is present).
  3 = "sticky customer base"/"long-standing relationships" claimed with NO
      contract-term or renewal-rate data.
  2 = only the company's own words (MANAGEMENT_CLAIM), no AR/CRISIL
      corroboration.
  1 = vague boilerplate only.
  None (Missing) = no data at all on contract length, renewal, or switching
      friction found in any source.

Evidence categories (need >=1 keyword hit each to count as "covered"):
  contract_term, renewal_rate, regulatory_barrier, generic_stickiness
"""

import re

_CATEGORY_PATTERNS = {
    "contract_term": [
        r"\bcontract term\b", r"\baverage contract term\b", r"\bcontract lock-?in\b",
        r"\block-?in period\b", r"\blong-?term contract\b", r"\btake-?or-?pay\b",
    ],
    "renewal_rate": [
        r"\brenewal rate\b", r"\bcustomer retention rate\b", r"\bcontract renewal\b",
        r"\brenewed at\b",
        # Insurance-sector renewal-equivalent term of art - confirmed
        # (HDFCLIFE) "renewal rate" alone misses real, disclosed data here.
        # \s+ (not a literal space) since PDF text extraction routinely
        # inserts irregular whitespace/line-breaks between words.
        r"\bpersistency\s+ratio\b",
    ],
    "regulatory_barrier": [
        r"\bvendor qualification\b", r"\bcustomer qualification\b", r"\bswitching cost\b",
        r"\bregulatory approval requirement\b", r"\bcertification requirement\b",
        r"\bremaining performance obligations\b", r"\bunsatisfied performance obligations\b",
    ],
    "generic_stickiness": [
        r"\bsticky customer\b", r"\blong-?standing relationship\b",
    ],
}

# A contract-term length needs a number-of-years anchor; a renewal rate
# needs a %. Tracked separately so the 5/5 rule (BOTH present) can be
# checked precisely, not just "any anchor found somewhere".
_TERM_LENGTH_ANCHOR = re.compile(r"\b\d+(?:\.\d+)?\s*[-–]?\s*years?\b", re.I)
_PERCENT_ANCHOR = re.compile(r"\d+(?:\.\d+)?\s*%")

_GENERIC_BOILERPLATE = re.compile(
    r"\b(?:strong customer relationships|loyal customer base|high customer satisfaction)\b", re.I
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


def score_switching_costs_moat(ar_mdna_text="", crisil_text="", business_description=""):
    """
    Deterministic 0-5 switching-costs score. `ar_mdna_text` (real AR MD&A +
    Ind-AS-115-note-adjacent excerpts) and `crisil_text` are both treated as
    PRIMARY per spec (CRISIL/ICRA rationale, AR MD&A) - whichever has the
    stronger evidence wins; `business_description` is the own-words/
    MANAGEMENT_CLAIM tier, same convention as the other A.2.x factors.

    Returns:
      {"score": 0-5|None, "categories_covered": [...], "evidence_quote": "...",
       "source": "Annual Report MD&A"|"CRISIL rationale"|"MANAGEMENT_CLAIM"|"none",
       "reasoning": "...", "numeric_anchor": bool}
    Never raises, never fabricates.
    """
    def _term_hit(matches):
        sents = matches.get("contract_term") or []
        return any(_TERM_LENGTH_ANCHOR.search(s) for s in sents)

    def _renewal_hit(matches):
        sents = matches.get("renewal_rate") or []
        return any(_PERCENT_ANCHOR.search(s) for s in sents)

    def _evaluate(matches, source_label):
        if not matches:
            return None
        categories = list(matches.keys())
        all_sentences = [s for sents in matches.values() for s in sents]
        has_term = _term_hit(matches)
        has_renewal = _renewal_hit(matches)
        has_reg = bool(matches.get("regulatory_barrier"))
        has_generic_only = set(categories) <= {"generic_stickiness"}

        if has_term and has_renewal:
            score = 5
            best = next((s for s in (matches.get("contract_term") or []) if _TERM_LENGTH_ANCHOR.search(s)),
                        next((s for s in (matches.get("renewal_rate") or []) if _PERCENT_ANCHOR.search(s)), all_sentences[0]))
            reasoning = f"{source_label} cites BOTH a contract-term length AND a renewal-rate percentage - specific, verifiable switching-cost evidence."
            return {"score": score, "categories_covered": categories, "numeric_anchor": True,
                    "evidence_quote": best[:300], "source": source_label, "reasoning": reasoning}

        if has_term or has_renewal or has_reg:
            score = 4
            metric_sents = (matches.get("contract_term") or []) + (matches.get("renewal_rate") or []) + (matches.get("regulatory_barrier") or [])
            best = next((s for s in metric_sents if _TERM_LENGTH_ANCHOR.search(s) or _PERCENT_ANCHOR.search(s)), metric_sents[0])
            reasoning = f"{source_label} cites a specific switching-cost metric ({', '.join(c for c in categories if c != 'generic_stickiness')}), but not both a contract term AND a renewal rate together."
            return {"score": score, "categories_covered": categories, "numeric_anchor": has_term or has_renewal,
                    "evidence_quote": best[:300], "source": source_label, "reasoning": reasoning}

        if has_generic_only:
            score = 3
            reasoning = f"{source_label} claims a 'sticky'/'long-standing' customer base with NO contract-term or renewal-rate data to back it."
            return {"score": score, "categories_covered": categories, "numeric_anchor": False,
                    "evidence_quote": all_sentences[0][:300], "source": source_label, "reasoning": reasoning}

        return None

    ar_matches = _matches_in(ar_mdna_text)
    crisil_matches = _matches_in(crisil_text)

    # PRIMARY: whichever of AR/CRISIL has the stronger evidence wins - both
    # are PRIMARY per spec, so compare rather than strictly order one first.
    ar_result = _evaluate(ar_matches, "Annual Report MD&A")
    crisil_result = _evaluate(crisil_matches, "CRISIL rationale")
    candidates = [r for r in (ar_result, crisil_result) if r is not None]
    if candidates:
        return max(candidates, key=lambda r: r["score"])

    # SECONDARY (own words): capped at 2, MANAGEMENT_CLAIM.
    desc_matches = _matches_in(business_description)
    if desc_matches:
        categories = list(desc_matches.keys())
        all_sentences = [s for sents in desc_matches.values() for s in sents]
        return {
            "score": 2, "categories_covered": categories, "numeric_anchor": False,
            "evidence_quote": all_sentences[0][:300], "source": "MANAGEMENT_CLAIM",
            "reasoning": f"Switching-cost language ({', '.join(categories)}) found only in the company's own "
                         f"description - no AR/CRISIL corroboration.",
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
                    "evidence_quote": src_text[max(0, m.start() - 40):m.end() + 40].strip(), "source": label,
                    "reasoning": "Only generic customer-relationship boilerplate found, no contract-term or renewal-rate data.",
                }

    return {
        "score": None, "categories_covered": [], "numeric_anchor": False,
        "evidence_quote": "", "source": "none",
        "reasoning": "No data on contract length, renewal rate, or switching friction found in Annual Report "
                     "MD&A, CRISIL rationale, or company description.",
    }
