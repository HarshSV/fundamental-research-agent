"""
A.5 (5A leg) - realisation-per-unit vs volume extraction from concall
transcripts. Standalone module (not folded into tools/concall_intelligence.py)
so this row's LLM calls stay isolated from the existing summarization
pipeline's own 30-day cache - this extraction has a materially higher
fabrication-risk profile (an LLM producing a specific realisation/volume
NUMBER looks exactly as confident whether it's real or hallucinated) and
needs its own guardrail and its own cache key, not shared with
concall_intelligence.py's per-URL qualitative-bullet cache.

Reuses tools/screener_scraper.py's `fetch_concall_list` / `download_transcript`
directly for the actual transcript text - the SAME source
tools/qualitative_engine.py's `_concall_digest` ultimately depends on via
concall_intelligence.py, not a second scrape of a different source.

FABRICATION-RISK GUARDRAIL (mandatory, do not weaken):
  The LLM must return each number ALONGSIDE a literal quoted source
  sentence (`realisation_quote` / `volume_quote`). A number is only
  accepted if it can be found as a real digit anchor actually present in
  its own quoted sentence, AND that quoted sentence is itself a real
  substring of the transcript text (not just plausible-looking - actually
  present). Any number failing either check is rejected and that quarter's
  corresponding field is dropped (None), never guessed. This mirrors the
  same "numeric anchor must appear in quoted evidence" discipline already
  proven in A.2.E (switching costs) and A.3 (revenue model quality).
"""

import os
import re
import json
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Own cache namespace - deliberately NOT sharing concall_intelligence.py's
# cache dir/keys (different extraction logic + guardrail; a bug fix here
# must never accidentally serve/pollute the other pipeline's cache) nor
# crisil_scraper's (semantically unrelated source).
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "pricing_realisation")
_EXTRACT_TTL = 30 * 24 * 3600  # a past quarter's transcript never changes; long TTL like concall_intelligence's own


def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(_CACHE_DIR, f"{safe}.json")


def _read_cache(key):
    try:
        p = _cache_path(key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= _EXTRACT_TTL:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _write_cache(key, payload):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def _numeric_anchors(text):
    """All numeric substrings in `text` (digits, optionally with a decimal
    point/comma/percent/x-multiplier) - used to check a claimed number is
    actually present in its quoted sentence, not just semantically implied."""
    if not text:
        return set()
    return set(re.findall(r"\d[\d,]*\.?\d*", text))


def _number_anchored_in_quote(value, quote):
    """True only if some numeric token inside `value` (as a string) also
    appears as a numeric token inside `quote`. Compares the numeric digits
    themselves (stripping commas/formatting) so '12,345' in the quote still
    matches a parsed value of 12345.0 - but a value with NO matching digit
    anchor anywhere in the quote is rejected, per the guardrail."""
    if value is None or not quote:
        return False
    value_str = str(value).replace(",", "")
    # normalize the numeric value into a comparable core string, e.g. "12.5" and "12.50" both -> "12.5"
    try:
        value_norm = ("%g" % float(value_str))
    except Exception:
        value_norm = value_str
    quote_anchors = _numeric_anchors(quote)
    for anchor in quote_anchors:
        anchor_clean = anchor.replace(",", "")
        try:
            anchor_norm = ("%g" % float(anchor_clean))
        except Exception:
            anchor_norm = anchor_clean
        if anchor_norm == value_norm or anchor_clean == value_str:
            return True
    return False


def _normalize_ws(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _quote_verbatim_in_transcript(quote, transcript_text):
    """Whitespace-normalized FULL-substring check - the entire quote, not
    just a prefix, must genuinely appear in the transcript. An earlier
    version of this guardrail only checked the quote's first 40 characters
    for long quotes (to tolerate PDF-extraction whitespace irregularities),
    which left a real gap: a quote could have a genuine real prefix with a
    FABRICATED number appended after it, and still pass. Normalizing
    whitespace on both sides (the same technique used for AR text scanning
    elsewhere in this codebase) closes that gap without needing to fall back
    to a truncated/partial check - the whole quote, including wherever the
    number sits, must be a real, whitespace-tolerant substring of the
    source."""
    q = _normalize_ws(quote)
    t = _normalize_ws(transcript_text)
    return bool(q) and q in t


def _validate_quarter_record(rec, transcript_text):
    """Applies the numeric-anchor-in-quote guardrail to one raw LLM-extracted
    quarter record. Returns a cleaned record where any field failing the
    guardrail is set to None (never a guessed pass-through), plus per-field
    validity flags for auditability/testing."""
    out = {
        "quarter": str(rec.get("quarter") or "").strip() or None,
        "realisation_per_unit": None, "realisation_unit": None, "realisation_quote": None,
        "volume": None, "volume_unit": None, "volume_quote": None,
        "realisation_rejected_reason": None, "volume_rejected_reason": None,
    }

    r_val = rec.get("realisation_per_unit")
    r_quote = str(rec.get("realisation_quote") or "").strip()
    if r_val is not None and r_quote:
        if not _quote_verbatim_in_transcript(r_quote, transcript_text):
            out["realisation_rejected_reason"] = "Quoted sentence not found verbatim in the source transcript."
        elif not _number_anchored_in_quote(r_val, r_quote):
            out["realisation_rejected_reason"] = f"Claimed realisation value {r_val!r} has no matching numeric anchor in its own quote."
        else:
            out["realisation_per_unit"] = float(r_val)
            out["realisation_unit"] = str(rec.get("realisation_unit") or "").strip() or None
            out["realisation_quote"] = r_quote
    elif r_val is not None:
        out["realisation_rejected_reason"] = "No quote supplied alongside the claimed realisation value - rejected, never trust a bare number."

    v_val = rec.get("volume")
    v_quote = str(rec.get("volume_quote") or "").strip()
    if v_val is not None and v_quote:
        if not _quote_verbatim_in_transcript(v_quote, transcript_text):
            out["volume_rejected_reason"] = "Quoted sentence not found verbatim in the source transcript."
        elif not _number_anchored_in_quote(v_val, v_quote):
            out["volume_rejected_reason"] = f"Claimed volume value {v_val!r} has no matching numeric anchor in its own quote."
        else:
            out["volume"] = float(v_val)
            out["volume_unit"] = str(rec.get("volume_unit") or "").strip() or None
            out["volume_quote"] = v_quote
    elif v_val is not None:
        out["volume_rejected_reason"] = "No quote supplied alongside the claimed volume value - rejected, never trust a bare number."

    return out


def _extract_realisation_volume_one(date, url, api_key=None):
    """Download one transcript + LLM-extract realisation/volume with the
    anchor guardrail applied. Cached per-URL (same convention as
    concall_intelligence._extract_one), but under this module's OWN cache
    namespace so a bug/behavior change here never silently reuses the other
    pipeline's cached records (and vice versa)."""
    import hashlib
    # v2: _quote_verbatim_in_transcript now does a whitespace-normalized FULL
    # substring check instead of a first-40-chars prefix check - closes a
    # real gap where a fabricated number could be appended after a genuine
    # quote prefix. Bumped so any v1-cached record (validated under the
    # weaker check) is never served as if it passed today's guardrail.
    ckey = "pricing_ex_v2_" + hashlib.md5((url or date).encode("utf-8")).hexdigest()
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    try:
        from tools.screener_scraper import download_transcript
        text = download_transcript(url, max_chars=12000)
        if not text or len(text) < 800:
            return None

        from tools.groq_client import groq_chat, parse_json_loose
        prompt = (
            "You are an equity analyst extracting REALISATION (average selling price per unit) and VOLUME "
            "(units/tonnes/quantity sold) trend data from this earnings-call transcript excerpt. Base EVERYTHING "
            "strictly on the transcript - never estimate or infer a number that isn't explicitly stated.\n\n"
            "For EACH number you report, you MUST quote the EXACT sentence from the transcript that contains it, "
            "verbatim (do not paraphrase the quote). If no explicit realisation or volume number is stated for "
            "this quarter, leave that field null and its quote null - do NOT invent a plausible-sounding figure.\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "quarter": "e.g. Q1FY25 or the reporting period as stated",\n'
            '  "realisation_per_unit": <number or null>,\n'
            '  "realisation_unit": "e.g. Rs/kg, Rs/tonne, Rs per unit (or null)",\n'
            '  "realisation_quote": "<verbatim transcript sentence containing the realisation number, or null>",\n'
            '  "volume": <number or null>,\n'
            '  "volume_unit": "e.g. tonnes, MT, units sold (or null)",\n'
            '  "volume_quote": "<verbatim transcript sentence containing the volume number, or null>"\n'
            "}\n"
        )
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You extract structured numeric facts from earnings calls. Reply with strict JSON only. Never fabricate a number without a verbatim quote."},
                {"role": "user", "content": f"{prompt}\n\n=== TRANSCRIPT ({date}) ===\n{text}"},
            ],
            max_tokens=700, temperature=0.1, api_key=api_key,
        )
        data = parse_json_loose(raw)
        if not isinstance(data, dict):
            return None

        validated = _validate_quarter_record(data, text)
        validated["date"] = date
        validated["url"] = url
        if not validated.get("quarter"):
            validated["quarter"] = date
        _write_cache(ckey, validated)
        return validated
    except Exception as e:
        print(f"[pricing_realisation_extractor] extract failed for {date}: {e}")
        return None


def extract_realisation_volume_series(symbol, name=None, max_quarters=6):
    """Public entry. Fetches the last `max_quarters` concall transcripts (via
    tools.screener_scraper, same source _concall_digest depends on) and
    extracts a validated realisation/volume record per quarter, oldest
    first (so callers can compute a trend). Every accepted number carries
    its own verbatim source quote - nothing here is a bare LLM assertion.

    Returns {"status": "OK"|"NOT_DISCLOSED", "quarters": [...], "reason": ...}
      quarters entries: {"quarter","date","url","realisation_per_unit",
      "realisation_unit","realisation_quote","volume","volume_unit",
      "volume_quote", "realisation_rejected_reason","volume_rejected_reason"}
      - a quarter with everything rejected still appears in the list (for
      auditability) but contributes nothing to any downstream trend
      calculation, since pricing_power_scoring filters on non-None values.
    Never raises.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    try:
        from tools.screener_scraper import fetch_concall_list
        calls = [c for c in (fetch_concall_list(sym, name) or []) if c.get("url")]
    except Exception as e:
        return {"status": "NOT_DISCLOSED", "quarters": [], "reason": f"Concall list fetch failed: {e}"}

    if not calls:
        return {"status": "NOT_DISCLOSED", "quarters": [], "reason": "No concall transcripts found for this company."}

    calls = calls[:max_quarters]  # newest-first as returned by fetch_concall_list
    quarters = []
    for c in calls:
        rec = _extract_realisation_volume_one(c.get("date"), c.get("url"))
        if rec is not None:
            quarters.append(rec)

    if not quarters:
        return {"status": "NOT_DISCLOSED", "quarters": [], "reason": "No transcript could be downloaded/extracted for any recent quarter."}

    quarters.sort(key=lambda r: r.get("date") or "")  # oldest first for trend computation
    return {"status": "OK", "quarters": quarters}


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "TATASTEEL"
    print(f"=== extract_realisation_volume_series({sym}) ===")
    res = extract_realisation_volume_series(sym)
    print("status:", res["status"], res.get("reason"))
    for q in res["quarters"]:
        print(f"\n-- {q.get('quarter')} ({q.get('date')}) --")
        print(f"  realisation: {q.get('realisation_per_unit')} {q.get('realisation_unit')}")
        if q.get("realisation_quote"):
            print(f"    quote: {q['realisation_quote']!r}")
        if q.get("realisation_rejected_reason"):
            print(f"    REJECTED: {q['realisation_rejected_reason']}")
        print(f"  volume: {q.get('volume')} {q.get('volume_unit')}")
        if q.get("volume_quote"):
            print(f"    quote: {q['volume_quote']!r}")
        if q.get("volume_rejected_reason"):
            print(f"    REJECTED: {q['volume_rejected_reason']}")
