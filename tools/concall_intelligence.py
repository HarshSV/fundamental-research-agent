"""
Concall Intelligence (#2/#5) — continuous earnings-call tracking.

For EVERY concall Screener lists (with a transcript), extract a compact structured
record (sentiment, guidance, commitments, positives, risks). Then do cross-call
analysis: sentiment trajectory over time + a "Walk the Talk" guidance-vs-outcome
table (promises delivered / missed / pending) synthesised against the company's
actual financial trajectory.

Runs as an on-demand/async enrichment (the core report doesn't wait for it).
Parallelised, heavily cached (per-URL extract + per-symbol result). Never raises.
"""

import os
import re
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "concall_intel")
RESULT_TTL = 7 * 24 * 3600      # per-symbol result cache: 7 days
EXTRACT_TTL = 30 * 24 * 3600    # per-transcript extract: 30 days (a past call never changes)
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_SENT_SCORE = {"positive": 2, "optimistic": 2, "neutral": 0, "cautious": -1,
               "mixed": -1, "negative": -2, "pessimistic": -2}
_lock = threading.Lock()


def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key, ttl):
    try:
        p = _cache_path(key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= ttl:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _write_cache(key, payload):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def _sort_key(date_str):
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", date_str or "")
    if m:
        return int(m.group(2)) * 100 + _MONTHS.get(m.group(1).lower(), 0)
    return 0


def _extract_one(date, url, api_key):
    """Download one transcript + LLM-extract a compact structured record. Cached
    per-URL (a past call never changes)."""
    import hashlib
    ckey = "ex_" + hashlib.md5((url or date).encode("utf-8")).hexdigest()
    cached = _read_cache(ckey, EXTRACT_TTL)
    if cached is not None:
        return cached
    try:
        from tools.screener_scraper import download_transcript
        text = download_transcript(url, max_chars=12000)
        if not text or len(text) < 800:
            return None
        from tools.groq_client import groq_chat, parse_json_loose
        prompt = (
            "You are an equity analyst. From this earnings-call transcript excerpt, extract a COMPACT "
            "JSON record. Base everything strictly on the transcript. Schema:\n"
            "{\n"
            '  "sentiment": "Positive | Neutral | Cautious | Negative",\n'
            '  "one_line": "one-sentence gist of the call",\n'
            '  "guidance": ["specific forward guidance WITH the number/metric, e.g. \'FY25 revenue growth 15-18%\'", "..."],\n'
            '  "commitments": ["specific promise/plan management made, e.g. \'commission new plant by Q3\'", "..."],\n'
            '  "positives": ["key positive with a number where stated", "..."],\n'
            '  "risks": ["key risk/concern raised", "..."],\n'
            '  "capital_allocation": "one line on capex/dividend/buyback/debt plans (or empty)"\n'
            "}\n"
            "Keep each list to the 3-5 MOST material points, each a short phrase. Return ONLY raw JSON."
        )
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You extract structured facts from earnings calls. Reply with strict JSON only."},
                {"role": "user", "content": f"{prompt}\n\n=== TRANSCRIPT ({date}) ===\n{text}"},
            ],
            max_tokens=900, temperature=0.1, api_key=api_key,
        )
        data = parse_json_loose(raw) or {}
        # normalise list fields (LLM sometimes returns a string/object)
        def _list(v):
            if isinstance(v, list):
                return [str(x) if not isinstance(x, dict) else " — ".join(str(t) for t in x.values() if t) for x in v if x][:5]
            return [str(v)] if v else []
        rec = {
            "date": date, "url": url,
            "sentiment": str(data.get("sentiment") or "Neutral").strip().title(),
            "one_line": str(data.get("one_line") or "").strip(),
            "guidance": _list(data.get("guidance")),
            "commitments": _list(data.get("commitments")),
            "positives": _list(data.get("positives")),
            "risks": _list(data.get("risks")),
            "capital_allocation": str(data.get("capital_allocation") or "").strip(),
        }
        _write_cache(ckey, rec)
        return rec
    except Exception as e:
        print(f"[concall_intel] extract failed for {date}: {e}")
        return None


def _walk_the_talk(records, financials_context, api_key):
    """One synthesis call: compare guidance across calls vs actual outcomes -> a
    compact 'walk the talk' table + how commentary evolved."""
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        # compact guidance history (oldest->newest) for the model
        hist = []
        for r in records:
            g = "; ".join(r.get("guidance") or [])
            if g:
                hist.append(f"{r['date']}: {g}")
        if not hist:
            return {}
        prompt = (
            "You are a portfolio manager checking if management 'walks the talk'. Below is a company's "
            "GUIDANCE history from its earnings calls (oldest to newest), plus its ACTUAL financial "
            "trajectory. Judge whether past guidance was delivered.\n\n"
            f"GUIDANCE HISTORY:\n" + "\n".join(hist) + "\n\n"
            f"ACTUAL FINANCIALS:\n{financials_context}\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "scorecard": [{"period":"FY24","guidance":"~15% revenue growth","outcome":"delivered ~17%","status":"delivered|partial|missed|pending"}],\n'
            '  "evolution": "2-3 short sentences on how management commentary/confidence evolved over these calls",\n'
            '  "credibility": "High | Medium | Low",\n'
            '  "credibility_reason": "one short line"\n'
            "}\n"
            "For status use: delivered (met/beat), partial (close), missed (fell short), pending (future/too early). "
            "Only include rows you can actually judge from the data. Keep it concise."
        )
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You assess management credibility. Reply with strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200, temperature=0.1, api_key=api_key,
        )
        data = parse_json_loose(raw) or {}
        sc = data.get("scorecard")
        if not isinstance(sc, list):
            sc = []
        clean = []
        for row in sc:
            if isinstance(row, dict):
                clean.append({
                    "period": str(row.get("period") or ""),
                    "guidance": str(row.get("guidance") or ""),
                    "outcome": str(row.get("outcome") or ""),
                    "status": str(row.get("status") or "pending").lower(),
                })
        return {
            "scorecard": clean[:8],
            "evolution": str(data.get("evolution") or "").strip(),
            "credibility": str(data.get("credibility") or "").strip(),
            "credibility_reason": str(data.get("credibility_reason") or "").strip(),
        }
    except Exception as e:
        print(f"[concall_intel] walk-the-talk failed: {e}")
        return {}


def build_concall_intelligence(symbol, name=None, financials_context="", max_workers=3):
    """Public entry. Returns the full concall-intelligence payload (cached per symbol)."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    rkey = f"ci_{sym}"
    cached = _read_cache(rkey, RESULT_TTL)
    if cached is not None:
        return cached

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key == "your_api_key_here":
        return {"available": False, "reason": "LLM not configured."}

    with _lock:
        cached = _read_cache(rkey, RESULT_TTL)
        if cached is not None:
            return cached
        try:
            from tools.screener_scraper import fetch_concall_list
            months = [m for m in (fetch_concall_list(sym, name) or []) if m.get("url")]
            if not months:
                return {"available": False, "reason": "No concall transcripts found."}

            # Extract every call (parallel, capped concurrency for LLM rate limits).
            records = []
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {ex.submit(_extract_one, m["date"], m["url"], api_key): m for m in months}
                for f in as_completed(futs):
                    r = f.result()
                    if r:
                        records.append(r)
            if not records:
                return {"available": False, "reason": "Transcripts could not be parsed."}

            records.sort(key=lambda r: _sort_key(r["date"]))  # oldest -> newest

            # Sentiment trajectory (deterministic).
            timeline = [{"date": r["date"], "sentiment": r["sentiment"],
                         "score": _SENT_SCORE.get(r["sentiment"].lower(), 0)} for r in records]

            # Walk-the-talk + evolution + credibility (one synthesis call).
            wtt = _walk_the_talk(records, financials_context, api_key)

            latest = records[-1]
            payload = {
                "available": True,
                "symbol": sym,
                "num_calls": len(records),
                "period_range": f"{records[0]['date']} – {records[-1]['date']}",
                "sentiment_timeline": timeline,
                "latest": latest,
                "calls": list(reversed(records)),   # newest first for the UI
                "walk_the_talk": wtt,
                "generated_at": time.strftime("%Y-%m-%d %H:%M"),
            }
            _write_cache(rkey, payload)
            print(f"[concall_intel] built for {sym}: {len(records)} calls, credibility={wtt.get('credibility')}")
            return payload
        except Exception as e:
            print(f"[concall_intel] build failed for {sym}: {e}")
            return {"available": False, "reason": f"Error: {e}"}
