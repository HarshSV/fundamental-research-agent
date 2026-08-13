"""
C.3 — Related-party transactions (RPTs): LLM-assisted structured-row
extraction from the Annual Report's Ind AS 24 "Related Party Disclosures"
note, with the same mandatory fabrication-risk guardrail used by
tools/pricing_realisation_extractor.py (A.5's 5A leg).

WHY a separate module (not folded into qualitative_engine.py directly):
same reasoning as pricing_realisation_extractor.py — an LLM producing a
specific counterparty name + amount looks exactly as confident whether it's
real or hallucinated, so this extraction step gets its own cache namespace
and its own guardrail, isolated from every other LLM call in this codebase.

FABRICATION-RISK GUARDRAIL (mandatory, do not weaken — mirrors
pricing_realisation_extractor.py's _validate_quarter_record / v2 fix):
  Every extracted row MUST come with a verbatim quoted source sentence/
  table-row-text (`quote`). A row is only accepted if:
    (a) the quote is a real, whitespace-normalized FULL substring of the
        actual AR evidence text (not a truncated-prefix check — the
        already-fixed full-match approach, not the weaker prefix-check bug
        found and fixed once this session in pricing_realisation_extractor.py).
    (b) the claimed amount (if any) is a real digit anchor present in that
        same quote.
  A row failing either check is REJECTED, not silently guessed/defaulted.
  Per CLAUDE.md: unknown/not-disclosed values are never converted to a
  fabricated guess.

Architecture split mirrors A.5's pricing power scoring: deterministic
classification/aggregation lives in tools/qualitative_engine.py, this module
does ONLY the row extraction + guardrail (LLM touches raw AR text here and
nowhere downstream).
"""

import os
import re
import json
import time
import hashlib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Own cache namespace — deliberately not sharing any other module's cache
# dir/keys, same reasoning as pricing_realisation_extractor.py's own cache.
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "rpt_extractor")
_EXTRACT_TTL = 90 * 24 * 3600  # a past fiscal year's AR note never changes; matches other AR-evidence caches' 90-day TTL


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


def _normalize_ws(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _quote_verbatim_in_text(quote, source_text):
    """Whitespace-normalized FULL-substring check — same fix as
    pricing_realisation_extractor.py's _quote_verbatim_in_transcript (v2):
    the entire quote, not just a prefix, must genuinely appear in the
    source. Closes the gap where a real quote prefix could have a
    fabricated number/name appended after it and still pass a truncated
    check."""
    q = _normalize_ws(quote)
    t = _normalize_ws(source_text)
    return bool(q) and q in t


def _numeric_anchors(text):
    if not text:
        return set()
    return set(re.findall(r"\d[\d,]*\.?\d*", text))


def _amount_anchored_in_quote(amount, quote):
    """True only if some numeric token of `amount` also appears as a
    numeric token inside `quote` — same digit-anchor comparison as
    pricing_realisation_extractor._number_anchored_in_quote."""
    if amount is None or not quote:
        return False
    try:
        amount_norm = ("%g" % float(str(amount).replace(",", "")))
    except Exception:
        amount_norm = str(amount).replace(",", "")
    for anchor in _numeric_anchors(quote):
        anchor_clean = anchor.replace(",", "")
        try:
            anchor_norm = ("%g" % float(anchor_clean))
        except Exception:
            anchor_norm = anchor_clean
        if anchor_norm == amount_norm or anchor_clean == str(amount).replace(",", ""):
            return True
    return False


def _validate_row(rec, source_text):
    """Applies the quote-verbatim + numeric-anchor guardrail to one raw
    LLM-extracted RPT row. A row missing a usable quote, or whose quote
    isn't a real substring of the source text, is rejected outright
    (returns None) — never defaulted to a guessed record. A row with a
    quote but NO amount is still accepted (counterparty/relationship rows
    without a disclosed amount are legitimate — e.g. "guarantees given",
    qualitative-only disclosures), but its amount stays None rather than
    being fabricated."""
    quote = str(rec.get("quote") or "").strip()
    counterparty = str(rec.get("counterparty") or "").strip()
    if not quote or not counterparty:
        return None, "Missing counterparty name or quote — rejected, never trust a bare row."
    if not _quote_verbatim_in_text(quote, source_text):
        return None, "Quoted text not found verbatim in the source Annual Report evidence."

    amount_cr = rec.get("amount_cr")
    if amount_cr is not None:
        if not _amount_anchored_in_quote(amount_cr, quote):
            # Amount claimed but not anchored in its own quote — drop ONLY
            # the amount (per CLAUDE.md: never convert to zero/guess), keep
            # the row if counterparty/relationship/quote are still valid.
            amount_cr = None
        else:
            try:
                amount_cr = float(amount_cr)
            except Exception:
                amount_cr = None

    out = {
        "counterparty": counterparty,
        "relationship_type": str(rec.get("relationship_type") or "").strip() or None,
        "transaction_type": str(rec.get("transaction_type") or "").strip() or None,
        "amount_cr": amount_cr,
        "quote": quote,
        "fiscal_year": rec.get("fiscal_year"),
    }
    return out, None


def _extract_rows_llm(evidence_text, fiscal_year, api_key=None):
    """One LLM call over the concatenated RPT-note evidence text, asking for
    structured rows with mandatory verbatim quotes. Returns the raw parsed
    list (unvalidated) or [] on any failure. Never raises."""
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        prompt = (
            "You are an equity analyst extracting RELATED-PARTY TRANSACTION (RPT) rows from this Annual Report "
            "excerpt (Ind AS 24 'Related Party Disclosures' note). Base EVERYTHING strictly on the text below — "
            "never estimate, infer, or invent a counterparty, amount, or relationship that isn't explicitly stated.\n\n"
            "For EACH row you report, you MUST quote the EXACT sentence or table-row text from the excerpt that "
            "contains it, verbatim (copy it exactly, do not paraphrase or reformat numbers). If an amount is not "
            "explicitly stated for a row, leave amount_cr null — do NOT invent a plausible-sounding figure. If there "
            "are no related-party transaction rows at all in this excerpt, return an empty list.\n\n"
            "If there are more than 15 distinct rows, report only the 15 with the LARGEST disclosed amounts "
            "(and any qualitative-only rows with no amount, up to 15 total) — do not truncate a row's own text, "
            "only limit the row COUNT, to keep the response complete rather than cut off.\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "rows": [\n'
            "    {\n"
            '      "counterparty": "<entity/person name exactly as stated>",\n'
            '      "relationship_type": "<e.g. Subsidiary, Associate, Promoter, Key Management Personnel, '
            'Relative of KMP, Enterprise controlled by KMP, Joint Venture — exactly as characterized in the text>",\n'
            '      "transaction_type": "<e.g. Sale of goods, Purchase of goods, Rent paid, Remuneration, '
            'Loan given, Guarantee given, Investment>",\n'
            '      "amount_cr": <number in Rs. crore, or null if not explicitly stated or units unclear>,\n'
            '      "quote": "<verbatim excerpt sentence/table-row containing this row>"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You extract structured related-party-transaction facts from Annual Report text. Reply with strict JSON only. Never fabricate a counterparty, amount, or relationship without a verbatim quote."},
                {"role": "user", "content": f"{prompt}\n\n=== ANNUAL REPORT EXCERPT (FY{fiscal_year}) ===\n{evidence_text}"},
            ],
            max_tokens=4000, temperature=0.1, api_key=api_key,
        )
        data = parse_json_loose(raw)
        rows = data.get("rows") if isinstance(data, dict) else None
        return (rows if isinstance(rows, list) else []), None
    except Exception as e:
        print(f"[rpt_extractor] LLM row extraction failed: {e}")
        return [], str(e)


def extract_rpt_records(symbol, name=None, fiscal_year=None):
    """Public entry. Fetches the AR's RPT-note evidence excerpts (via
    tools.annual_report_financials.fetch_rpt_evidence_from_annual_report),
    LLM-extracts candidate rows, and validates every row against the
    verbatim-quote + numeric-anchor guardrail. Rows failing validation are
    dropped, never guessed.

    Returns {"status": "OK"|"NOT_DISCLOSED", "records": [...], "pdf_url":
    ..., "fiscal_year": ..., "rejected_count": int, "reason": ...}
      records entries: {"counterparty","relationship_type",
      "transaction_type","amount_cr","quote","fiscal_year"}
    Never raises."""
    sym = (symbol or "").strip().upper().replace(".NS", "")

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        evidence = fetch_rpt_evidence_from_annual_report(sym, name, fiscal_year=fiscal_year)
    except Exception as e:
        return {"status": "NOT_DISCLOSED", "records": [], "reason": f"RPT evidence fetch failed: {e}"}

    if not isinstance(evidence, dict) or evidence.get("error"):
        return {"status": "NOT_DISCLOSED", "records": [], "reason": (evidence or {}).get("error", "RPT evidence fetch failed.")}

    excerpts = evidence.get("excerpts") or []
    if not excerpts:
        return {"status": "NOT_DISCLOSED", "records": [], "reason": "No Related Party Disclosures note text located in the Annual Report."}

    fy = evidence.get("fiscal_year") or fiscal_year
    pdf_url = evidence.get("pdf_url")

    # Dedup excerpt windows by text. Kept as individual (page, text) pairs
    # (not joined yet) so they can be prioritized by information density
    # before capping — see the BUG FIX note below.
    seen = set()
    uniq = []
    for ex in excerpts:
        t = ex.get("text") or ""
        key = _normalize_ws(t)
        if key and key not in seen:
            seen.add(key)
            uniq.append(ex)

    # BUG FIX (found during real-company testing on TATASTEEL): the AR-04
    # fetcher's generic Ind AS 24 anchors legitimately also match AGM-notice
    # procedural text ("To approve Material Related Party Transactions...")
    # elsewhere in the same PDF, which piles extra low-value text onto the
    # blob without adding real rows. On a large-conglomerate AR (700+ pages,
    # dozens of anchor hits) the resulting >20k-char blob pushed the LLM's
    # JSON response past the free-tier fallback model's ~4000-completion-
    # token cap, truncating mid-string and making every row unparseable
    # (confirmed: "Unterminated string..." from parse_json_loose, 0 rows
    # recovered even though real RPT-note text — with actual counterparty
    # names and Rs. crore amounts — was genuinely present in the excerpts).
    # Fix: prioritize excerpts by DIGIT DENSITY (the real Ind AS 24 table
    # rows are digit-heavy; AGM procedural boilerplate is not) and cap the
    # total blob so the response can complete, instead of naively taking
    # the first N pages (which could just as easily cut the real note out).
    # The guardrail still independently rejects anything not verbatim in
    # this exact (possibly capped) blob, so capping can only ever reduce
    # recall, never let a fabricated row through.
    _MAX_EVIDENCE_CHARS = 9000
    uniq.sort(key=lambda ex: -sum(c.isdigit() for c in (ex.get("text") or "")))
    kept = []
    running = 0
    for ex in uniq:
        t = ex.get("text") or ""
        if running + len(t) > _MAX_EVIDENCE_CHARS and kept:
            continue
        kept.append(ex)
        running += len(t)
    kept.sort(key=lambda ex: ex.get("page") or 0)  # restore document order for coherent reading

    evidence_text = "\n\n".join(ex.get("text") or "" for ex in kept)
    if len(evidence_text) < 100:
        return {"status": "NOT_DISCLOSED", "records": [], "reason": "Related Party Disclosures excerpt text too short to extract from."}

    # v2: de-dup identical (counterparty, transaction_type, quote) rows with
    # conflicting column-attributed amounts (see de-dup comment below) —
    # bumped so a v1-cached record (built before the fix) isn't served as
    # if it were already de-duplicated.
    ckey = "rpt_ex_v2_" + hashlib.md5(f"{sym}_{fy}_{evidence_text[:2000]}".encode("utf-8")).hexdigest()
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    raw_rows, llm_error = _extract_rows_llm(evidence_text, fy)
    records = []
    rejected = 0
    seen_row_keys = {}
    for rec in raw_rows:
        if not isinstance(rec, dict):
            rejected += 1
            continue
        if rec.get("fiscal_year") is None:
            rec["fiscal_year"] = fy
        validated, reject_reason = _validate_row(rec, evidence_text)
        if validated is None:
            rejected += 1
            continue
        # De-dup: a flattened multi-column AR table (e.g. Subsidiaries /
        # Associates / Joint Ventures / Tata Sons side-by-side on one text
        # line) legitimately contains SEVERAL numeric anchors in the same
        # quoted row-text. The LLM sometimes re-emits the same
        # (counterparty, transaction_type, quote) with a DIFFERENT column's
        # number attributed to it across repeated calls/samples — each
        # individually passes the numeric-anchor guardrail (the number IS
        # really in the quote), but presenting all of them as separate rows
        # would show the same fact 3-4x with conflicting amounts. Keep only
        # the first validated occurrence per (counterparty, transaction_type,
        # quote) — never averaged/merged/guessed, just de-duplicated.
        row_key = (validated["counterparty"], validated["transaction_type"], validated["quote"])
        if row_key in seen_row_keys:
            rejected += 1
            continue
        seen_row_keys[row_key] = True
        records.append(validated)

    out = {
        "status": "OK" if records else "NOT_DISCLOSED",
        "records": records,
        "pdf_url": pdf_url,
        "fiscal_year": fy,
        "rejected_count": rejected,
        "reason": (None if records else
                   (f"LLM extraction call failed (likely a transient rate limit): {llm_error}" if llm_error else
                    "Related Party Disclosures note text was located, but no row could be extracted and verified against a verbatim quote.")),
    }
    # BUG FIX (found during real-company testing): a transient LLM failure
    # (rate limit, timeout) previously produced the exact same empty-records
    # payload as a genuine "note located, nothing extractable" result, and
    # BOTH got cached for the full 90-day TTL — a temporary quota exhaustion
    # would have silently looked like a confirmed absence of RPTs for three
    # months. Only cache when the LLM call actually completed (mirrors
    # `_get_extracted_financials_impl`'s documented convention: transient
    # network/IO failures are never persisted the same as a real result).
    if llm_error is None:
        _write_cache(ckey, out)
    return out


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "TATASTEEL"
    print(f"=== extract_rpt_records({sym}) ===")
    res = extract_rpt_records(sym)
    print("status:", res["status"], "| rejected:", res.get("rejected_count"), "| reason:", res.get("reason"))
    for r in res["records"]:
        print(f"\n-- {r['counterparty']} ({r['relationship_type']}) --")
        print(f"  transaction: {r['transaction_type']} | amount_cr: {r['amount_cr']}")
        print(f"  quote: {r['quote'][:200]!r}")
