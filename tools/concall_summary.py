"""
Standalone concall-transcript summarizer.

Given a single transcript PDF URL (one month's earnings call), download it, extract
the text, and produce a detailed, structured, Screener-style summary via Groq —
grounded strictly in that transcript. Used by the per-month Concalls tabs.

Cached per URL (so re-opening a month is instant). Never raises.
"""

import os
import json
import hashlib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from tools.screener_scraper import download_transcript, _read_cache, _write_cache


def _to_text(x):
    """Models sometimes emit list items as objects — flatten to readable text."""
    if isinstance(x, dict):
        return " — ".join(str(v) for v in x.values() if v)
    return str(x) if x is not None else ""


def _bullets(items):
    return "\n".join([f"•  {_to_text(x)}" for x in (items or []) if x]) or "•  (not specified)"


def _format_summary(f14):
    return (
        f"{f14.get('summary', '')}\n"
        f"Management Tone: {f14.get('tone', '—')}\n\n"
        f"FINANCIAL HIGHLIGHTS\n{_bullets(f14.get('financial_highlights'))}\n\n"
        f"GROWTH DRIVERS\n{_bullets(f14.get('growth_drivers'))}\n\n"
        f"BUSINESS WINS / EXECUTION\n{_bullets(f14.get('business_wins'))}\n\n"
        f"RISKS (with management response)\n{_bullets(f14.get('risks'))}\n\n"
        f"GUIDANCE / OUTLOOK\n{f14.get('guidance', '—')}\n\n"
        f"WHAT MATTERS FOR INVESTORS\n{_bullets(f14.get('what_matters'))}"
    )


_SYS = (
    "You are an expert equity research analyst. Summarize the earnings-call transcript "
    "below into a DETAILED, QUANTIFIED, structured JSON. Cite exact figures, %s, order "
    "sizes and guidance FROM THE TRANSCRIPT. Give 4-7 items in each list. Base everything "
    "STRICTLY on the transcript; do not invent.\n"
    "Return ONLY raw JSON matching:\n"
    "{\n"
    '  "summary": "3-4 sentence overview",\n'
    '  "tone": "Positive | Cautious | Negative",\n'
    '  "financial_highlights": ["Revenue Rs X cr (+Y%)", "EBITDA margin Z%", "..."],\n'
    '  "growth_drivers": ["...", "..."],\n'
    '  "business_wins": ["orders/launches/share wins with numbers", "..."],\n'
    '  "risks": ["risk WITH management response", "..."],\n'
    '  "guidance": "forward guidance, capex %, outlook (quote numbers)",\n'
    '  "what_matters": ["most actionable takeaways", "..."]\n'
    "}\n"
    "No markdown fences, no preamble."
)


def summarize_concall(symbol, url, date=""):
    """
    Returns {available: bool, date, url, summary_text, ...fields} for one month's
    concall. Cached per URL. Never raises.
    """
    if not url:
        return {"available": False, "date": date, "url": None, "reason": "No transcript published for this month yet."}

    ckey = "ccsum_" + hashlib.md5(url.encode("utf-8")).hexdigest()
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    text = download_transcript(url)
    if not text:
        out = {"available": False, "date": date, "url": url, "reason": "Transcript could not be read."}
        return out

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key in ("", "your_api_key_here"):
        out = {"available": False, "date": date, "url": url, "reason": "AI summariser not configured."}
        return out

    try:
        from tools.groq_client import groq_chat
        raw = groq_chat(
            messages=[
                {"role": "system", "content": _SYS},
                {"role": "user", "content": f"Company: {symbol}. Concall period: {date}.\n\nTRANSCRIPT:\n{text}"},
            ],
            temperature=0.3,
            api_key=api_key,
        ).strip()
        from tools.groq_client import parse_json_loose
        f14 = parse_json_loose(raw)
        out = {
            "available": True,
            "date": date,
            "url": url,
            "tone": f14.get("tone", "—"),
            "summary_text": _format_summary(f14),
            **f14,
        }
        _write_cache(ckey, out)
        print(f"[concall_summary] Summarised {symbol} {date} ({len(text)} chars).")
        return out
    except Exception as e:
        print(f"[concall_summary] failed for {symbol} {date}: {e}")
        return {"available": False, "date": date, "url": url, "reason": "Summary generation failed."}


if __name__ == "__main__":
    import sys
    from tools.screener_scraper import fetch_concall_list
    sym = sys.argv[1] if len(sys.argv) > 1 else "TMCV"
    lst = fetch_concall_list(sym)
    print("concalls:", [(x["date"], bool(x["url"])) for x in lst])
    if lst and lst[0]["url"] or (len(lst) > 1 and lst[1]["url"]):
        item = next(x for x in lst if x["url"])
        r = summarize_concall(sym, item["url"], item["date"])
        print("available:", r["available"])
        print((r.get("summary_text") or r.get("reason"))[:400])
