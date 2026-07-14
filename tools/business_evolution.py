"""
Business Evolution (#4) — how the company changed over time.

Produces a structured then-vs-now view plus a categorized list/timeline of business
changes: old identity, acquisitions, divestitures/discontinued businesses, new
businesses, JVs & partnerships, geographic/capacity expansion, technology adoption,
and management/strategy shifts.

Grounded in the sources we already have: the company's business description + the
full concall corpus (which discusses M&A, JVs, launches, capex, leadership). One
synthesis LLM call over that context; the model may also add well-known public-record
milestones, but is instructed never to speculate. Async + cached. Never raises.
"""

import os
import json
import time
import threading

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "evolution")
TTL = 30 * 24 * 3600  # evolution changes slowly
_lock = threading.Lock()

# Category -> colour hint the UI uses for the timeline dots.
CATEGORIES = ["acquisition", "divestiture", "new_business", "jv_partnership",
              "expansion", "technology", "management", "strategy"]


def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key):
    try:
        p = _cache_path(key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= TTL:
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


def _list(v):
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                out.append(" — ".join(str(t) for t in x.values() if t))
            elif x:
                out.append(str(x))
        return out[:10]
    return [str(v)] if v else []


def _concall_digest(symbol, name):
    """Compact digest of the concall corpus (reuses the cached Concall Intelligence
    build) — commitments/positives here are where M&A, JVs, launches, capex show up."""
    try:
        from tools.concall_intelligence import build_concall_intelligence
        ci = build_concall_intelligence(symbol, name=name)
        if not ci.get("available"):
            return ""
        parts = []
        for c in (ci.get("calls") or [])[:10]:
            seg = f"{c.get('date')}: {c.get('one_line', '')}"
            extra = (c.get("commitments") or []) + (c.get("positives") or [])
            if extra:
                seg += " | " + "; ".join(str(x) for x in extra[:4])
            parts.append(seg)
        return "\n".join(parts)[:4000]
    except Exception as e:
        print(f"[evolution] concall digest failed: {e}")
        return ""


def build_business_evolution(symbol, name=None, description=""):
    """Public entry. Returns the structured evolution payload (cached per symbol)."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    ck = f"be_{sym}"
    cached = _read_cache(ck)
    if cached is not None:
        return cached

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key == "your_api_key_here":
        return {"available": False, "reason": "LLM not configured."}

    with _lock:
        cached = _read_cache(ck)
        if cached is not None:
            return cached
        try:
            digest = _concall_digest(sym, name)
            company = name or sym
            context = f"COMPANY: {company}\n"
            if description:
                context += f"\nCURRENT BUSINESS DESCRIPTION:\n{description[:2500]}\n"
            if digest:
                context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"

            prompt = (
                "You are an equity analyst mapping how a company's business has EVOLVED over time. "
                "Using the context below (and well-known public-record milestones for this company), "
                "produce a factual Business Evolution. NEVER speculate or invent — if unsure, omit. "
                "Prefer facts from the provided description/calls; you may add major, verifiable public "
                "milestones (founding identity, large acquisitions, demergers) even if not in the text.\n\n"
                "Return ONLY JSON:\n"
                "{\n"
                '  "then": "1-2 sentences: the company\'s ORIGINAL / older identity and business model",\n'
                '  "now": "1-2 sentences: what the company IS TODAY",\n'
                '  "summary": "2-3 sentences on the arc of how it transformed",\n'
                '  "timeline": [{"year":"2016","category":"acquisition|divestiture|new_business|jv_partnership|expansion|technology|management|strategy","event":"short factual description"}],\n'
                '  "acquisitions": ["name/year — what & why"],\n'
                '  "divestitures": ["businesses sold, exited or discontinued"],\n'
                '  "new_businesses": ["new segments/products the company entered"],\n'
                '  "partnerships_jvs": ["notable JVs / partnerships and the partner"],\n'
                '  "expansion": ["geographic or capacity expansion"],\n'
                '  "technology": ["technology / digital adoption"],\n'
                '  "management_changes": ["leadership or major strategy changes"]\n'
                "}\n"
                "Keep each item a short factual phrase, with a YEAR where known. Order the timeline oldest->newest. "
                "Leave a list empty if there is genuinely nothing to report.\n\n"
                f"=== CONTEXT ===\n{context}"
            )
            from tools.groq_client import groq_chat, parse_json_loose
            raw = groq_chat(
                messages=[
                    {"role": "system", "content": "You are a precise business historian. Reply with strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1800, temperature=0.2, api_key=api_key,
            )
            data = parse_json_loose(raw) or {}

            timeline = []
            for e in (data.get("timeline") or []):
                if isinstance(e, dict) and e.get("event"):
                    cat = str(e.get("category") or "strategy").lower().strip()
                    cat = next((c for c in CATEGORIES if c in cat), "strategy")
                    timeline.append({"year": str(e.get("year") or "").strip(),
                                     "category": cat, "event": str(e["event"]).strip()})
            # sort by year when parseable
            def _yr(t):
                import re
                m = re.search(r"(19|20)\d{2}", t.get("year") or "")
                return int(m.group(0)) if m else 0
            timeline.sort(key=_yr)

            payload = {
                "available": True,
                "symbol": sym,
                "then": str(data.get("then") or "").strip(),
                "now": str(data.get("now") or "").strip(),
                "summary": str(data.get("summary") or "").strip(),
                "timeline": timeline[:20],
                "acquisitions": _list(data.get("acquisitions")),
                "divestitures": _list(data.get("divestitures")),
                "new_businesses": _list(data.get("new_businesses")),
                "partnerships_jvs": _list(data.get("partnerships_jvs")),
                "expansion": _list(data.get("expansion")),
                "technology": _list(data.get("technology")),
                "management_changes": _list(data.get("management_changes")),
                "grounded": bool(digest),
                "generated_at": time.strftime("%Y-%m-%d %H:%M"),
            }
            # Only cache/keep if there's real content.
            has_content = payload["then"] or payload["timeline"] or any(
                payload[k] for k in ("acquisitions", "new_businesses", "partnerships_jvs", "expansion"))
            if not has_content:
                return {"available": False, "reason": "Not enough history to map an evolution."}
            _write_cache(ck, payload)
            print(f"[evolution] built for {sym}: {len(timeline)} timeline events, grounded={bool(digest)}")
            return payload
        except Exception as e:
            print(f"[evolution] build failed for {sym}: {e}")
            return {"available": False, "reason": f"Error: {e}"}
