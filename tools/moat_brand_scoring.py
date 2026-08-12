"""
A.2.A — Brand moat: deterministic (no-LLM) 0-5 evidence scorer.

Per the sheet's row 2A: score 0-5 from CRISIL/ICRA rating rationale, AR MD&A,
and earnings-call commentary, on pricing power / customer preference /
premium positioning / repeat business / market-share evidence.

This deliberately does NOT call any LLM — regex/keyword pattern matching
against real source text only. Chosen over an LLM read specifically to
avoid touching the shared Groq/OpenRouter quota for a 2,409-company bulk
run. Cruder than an LLM's nuance, but fully reproducible and auditable:
every score traces to the literal matched sentence(s), never a paraphrase.

Rubric (mirrors the LLM qualitative-evidence rubric's spirit, made
deterministic):
  5 = a CRISIL/ICRA sentence carries a brand-evidence keyword AND a
      concrete anchor (a number, %, "since <year>", or a named exclusive
      arrangement) — specific, third-party, verifiable.
  4 = a CRISIL/ICRA sentence carries a brand-evidence keyword with no
      numeric/named anchor — specific claim, but generic phrasing.
  3 = a CRISIL/ICRA sentence exists but only touches ONE evidence
      category (see below) — narrower coverage than 4/5.
  2 = brand-evidence keywords found ONLY in the company's own
      description/MD&A text (not corroborated by CRISIL/ICRA) —
      management's own claim, no third-party corroboration.
  1 = only generic boilerplate phrasing anywhere ("strong brand",
      "leading player") with no specifics from any source.
  None (Missing) = no brand-evidence keyword found in ANY source text —
      flags QUANT_PROXY_ONLY for this sub-point, never silently scored 1.

Evidence categories (need >=1 keyword hit each to count as "covered"):
  pricing_power, customer_preference, premium_positioning,
  repeat_business, market_share
"""

import re

_CATEGORY_PATTERNS = {
    "pricing_power": [
        r"\bpricing power\b", r"\bpremium pricing\b", r"\bable to pass on\b",
        r"\bprice increases?\b(?!.{0,20}\b(?:raw material|input|cost)\b)",
        r"\bpass(?:ing)? on (?:cost|price) increases?\b",
    ],
    "customer_preference": [
        r"\bbrand loyalty\b", r"\bconsumer preference\b", r"\bcustomer preference\b",
        r"\btrusted brand\b", r"\bpreferred (?:brand|choice)\b", r"\bbrand recall\b",
        r"\bbrand equity\b", r"\bstrong brand\b",
    ],
    "premium_positioning": [
        r"\bpremium(?:isation| segment| product| positioning)\b",
        r"\bflagship brand\b", r"\bleadership position\b", r"\bmarket leader\b",
        r"\bleading (?:player|position|brand)\b",
    ],
    "repeat_business": [
        r"\brepeat (?:purchase|business|customers?)\b", r"\bcustomer retention\b",
        r"\brecurring (?:customers?|revenue|business)\b", r"\bsustained market share\b",
    ],
    "market_share": [
        r"\bmarket share\b", r"\bshare of (?:the )?market\b",
        r"\bdominant position\b",
    ],
}

_NUMERIC_ANCHOR = re.compile(
    r"\d+(?:\.\d+)?\s*%|"
    r"\bsince\s+\d{4}\b|"
    r"\bover\s+\d+\s*years?\b|"
    r"\bexclusive\b|"
    r"\bpatent(?:ed)?\b"
)

_GENERIC_BOILERPLATE = re.compile(
    r"\b(?:strong brand|leading player|well[- ]known brand|established brand)\b", re.I
)


def _sentences(text):
    if not text:
        return []
    # Simple sentence split — good enough for keyword/anchor proximity checks,
    # not meant to be a real NLP sentence tokenizer.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


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


def score_brand_moat(crisil_text="", business_description="", ar_mdna_text=""):
    """
    Deterministic 0-5 brand-moat score. `business_description` (yfinance
    blurb) and `ar_mdna_text` (real Annual Report MD&A/Business Overview
    excerpts, see tools/annual_report_financials.fetch_brand_evidence_from_annual_report)
    are both "the company's own words" per the rubric's tier (2) — neither is
    independent third-party corroboration the way a CRISIL/ICRA rationale is,
    so both are capped at 2/5 and tagged MANAGEMENT_CLAIM, combined into one
    search so a category can be found in either without double-counting.

    Returns:
      {"score": 0-5|None, "categories_covered": [...], "evidence_quote": "...",
       "source": "CRISIL rationale"|"MANAGEMENT_CLAIM"|"none",
       "reasoning": "...", "numeric_anchor": bool}
    Never raises, never fabricates — a score of 1 vs None is meaningfully
    different (boilerplate found vs nothing found at all), per the
    DON'T/DO INSTEAD guardrails.
    """
    crisil_matches = _matches_in(crisil_text)
    # Company's own words, from either source — merged since both sit at the
    # SAME evidence tier (MANAGEMENT_CLAIM), not independently corroborating.
    own_words_text = "\n".join(t for t in (business_description, ar_mdna_text) if t)
    desc_matches = _matches_in(own_words_text)

    if not crisil_matches and not desc_matches:
        has_boilerplate = bool(_GENERIC_BOILERPLATE.search(crisil_text or "") or
                                _GENERIC_BOILERPLATE.search(own_words_text or ""))
        if has_boilerplate:
            src_text = crisil_text if _GENERIC_BOILERPLATE.search(crisil_text or "") else own_words_text
            m = _GENERIC_BOILERPLATE.search(src_text)
            return {
                "score": 1, "categories_covered": [], "numeric_anchor": False,
                "evidence_quote": src_text[max(0, m.start() - 40):m.end() + 40].strip(),
                "source": "CRISIL rationale" if src_text is crisil_text else "MANAGEMENT_CLAIM",
                "reasoning": "Only generic boilerplate brand language found, no specifics in any evidence category.",
            }
        return {
            "score": None, "categories_covered": [], "numeric_anchor": False,
            "evidence_quote": "", "source": "none",
            "reasoning": "No brand-evidence keywords found in CRISIL rationale, Annual Report MD&A, or company description.",
        }

    if crisil_matches:
        categories = list(crisil_matches.keys())
        all_sentences = [s for sents in crisil_matches.values() for s in sents]
        has_anchor = any(_NUMERIC_ANCHOR.search(s) for s in all_sentences)
        best_sentence = next((s for s in all_sentences if _NUMERIC_ANCHOR.search(s)), all_sentences[0])
        if has_anchor:
            score = 5
            reasoning = f"CRISIL rationale carries specific, verifiable brand evidence ({', '.join(categories)}) with a numeric/named anchor."
        elif len(categories) >= 2:
            score = 4
            reasoning = f"CRISIL rationale carries specific brand evidence across {len(categories)} categories ({', '.join(categories)}), but no numeric anchor."
        else:
            score = 3
            reasoning = f"CRISIL rationale touches only one brand-evidence category ({categories[0]}), no numeric anchor."
        return {
            "score": score, "categories_covered": categories, "numeric_anchor": has_anchor,
            "evidence_quote": best_sentence[:300], "source": "CRISIL rationale", "reasoning": reasoning,
        }

    # Only the company's own words (business description and/or its own
    # Annual Report MD&A) mention brand evidence — no third-party (CRISIL)
    # corroboration, capped at 2 per the rubric and tagged MANAGEMENT_CLAIM.
    categories = list(desc_matches.keys())
    all_sentences = [s for sents in desc_matches.values() for s in sents]
    return {
        "score": 2, "categories_covered": categories, "numeric_anchor": False,
        "evidence_quote": all_sentences[0][:300], "source": "MANAGEMENT_CLAIM",
        "reasoning": f"Brand-evidence language ({', '.join(categories)}) found only in the company's own "
                     f"description/Annual Report MD&A — no independent CRISIL/ICRA corroboration.",
    }
