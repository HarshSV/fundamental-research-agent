"""
News sentiment — real news evidence for the chatbot's event-grounded reasoning
and general "how is sentiment on X" questions (see memory
"event-grounded-reasoning-scope"). User's pick: scrape Indian financial news
(Moneycontrol / Economic Times / LiveMint) rather than a paid news API.

Implementation note: instead of scraping each site's own search page (fragile,
breaks on redesign, several have anti-bot/paywall friction), this fetches
Google News' public RSS search restricted to exactly those three domains
(`site:moneycontrol.com OR site:economictimes.indiatimes.com OR
site:livemint.com`) — same source publishers the user picked, one stable feed
format (RSS/XML) instead of three fragile HTML scrapers. Free, no API key.

Sentiment is scored per-headline by Groq (headlines only — full article scrape
is unnecessary for a sentiment tag and would blow up latency/cost), batched
into one call. Disk-cached (headlines 2h, since news moves fast; sentiment
alongside them). Never raises.
"""

import os
import re
import json
import time
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

try:
    from tools import ssl_bootstrap  # noqa: F401
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from curl_cffi import requests as _http
    _HAVE_CFFI = True
except Exception:  # pragma: no cover
    import requests as _http
    _HAVE_CFFI = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "news_sentiment")
NEWS_TTL = 2 * 3600
SITES = ("moneycontrol.com", "economictimes.indiatimes.com", "livemint.com")
MAX_ITEMS = 12
_lock = threading.Lock()

# Corporate suffixes stripped before building the title-match tokens — the
# registry name is typically "X Limited"/"X Ltd" but headlines almost never
# include the suffix, so requiring it in an ALL-tokens match silently
# filtered out every real headline (found live on "Tata Steel Limited").
_SUFFIX_RE = re.compile(r"\b(limited|ltd\.?|inc\.?|corp\.?|corporation|company|co\.?|plc)\b", re.I)


def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key, ttl=NEWS_TTL):
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
            json.dump(payload, fh, default=str)
    except Exception:
        pass


def _fetch(url, timeout=12):
    if _HAVE_CFFI:
        return _http.get(url, timeout=timeout, impersonate="chrome")
    return _http.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})


def fetch_news(symbol: str, name: str = None) -> list:
    """Returns up to MAX_ITEMS recent headlines for `symbol`/`name` from the
    three named Indian financial-news domains, newest first:
    [{title, url, source, published}]. Cached 2h. Never raises."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    label = (name or sym).strip()
    ckey = "news_" + hashlib.md5(f"{sym}|{label}".encode("utf-8")).hexdigest()
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    # One query PER site: an OR'd site: filter combined with a quoted phrase
    # confuses Google News' query parser and silently falls back to generic
    # top-stories for that site (verified empirically) — per-site queries stay
    # on-topic. Client-side we also require the company name/symbol to appear
    # in the title, since even a single-site query returns a few unrelated
    # "top of page" items (ticker tape numbers, unrelated site headlines).
    cutoff = datetime.now(timezone.utc) - timedelta(days=120)
    # ALL tokens (word-boundary match) must appear — an ANY-token or substring
    # match let unrelated group-company headlines through (e.g. "Tata Power",
    # or "Ben Steele" matching a bare "steel" substring).
    core_name = _SUFFIX_RE.sub("", label).strip()
    name_tokens = [t.lower() for t in re.split(r"\s+", core_name) if len(t) > 2]
    name_patterns = [re.compile(r"\b" + re.escape(tok) + r"\b") for tok in name_tokens]
    sym_pattern = re.compile(r"\b" + re.escape(sym.lower()) + r"\b") if sym else None
    items = []
    seen_titles = set()

    for site in SITES:
        query = f'"{core_name}" site:{site}'
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            resp = _fetch(url)
            if resp.status_code != 200:
                continue
            for m in re.finditer(r"<item>(.*?)</item>", resp.text, re.S):
                block = m.group(1)
                title_m = re.search(r"<title>(.*?)</title>", block, re.S)
                link_m = re.search(r"<link>(.*?)</link>", block, re.S)
                date_m = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
                source_m = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
                if not title_m:
                    continue
                title = re.sub(r"<!\[CDATA\[|\]\]>", "", title_m.group(1)).strip()
                title_low = title.lower()
                if not title or title_low in seen_titles:
                    continue
                on_topic = (name_patterns and all(p.search(title_low) for p in name_patterns)) or \
                           (sym_pattern and sym_pattern.search(title_low))
                if not on_topic:
                    continue  # off-topic item that slipped past the site query
                pub_raw = date_m.group(1).strip() if date_m else ""
                try:
                    pub_dt = parsedate_to_datetime(pub_raw)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pub_dt = None
                if pub_dt is not None and pub_dt < cutoff:
                    continue  # stale article — skip, don't let old news masquerade as recent
                seen_titles.add(title_low)
                items.append({
                    "title": title,
                    "url": (link_m.group(1).strip() if link_m else ""),
                    "source": (re.sub(r"<!\[CDATA\[|\]\]>", "", source_m.group(1)).strip() if source_m else ""),
                    "published": pub_raw,
                    "_sort": pub_dt or datetime.min.replace(tzinfo=timezone.utc),
                })
        except Exception as e:
            print(f"[news_sentiment] fetch failed for {sym} ({site}): {e}")
            continue

    items.sort(key=lambda x: x["_sort"], reverse=True)
    items = items[:MAX_ITEMS]
    for it in items:
        it.pop("_sort", None)

    _write_cache(ckey, items)
    return items


_SENT_SYS = (
    "You are a financial news analyst. For EACH headline below, classify its sentiment "
    "for the stock as Positive, Neutral, or Negative, based STRICTLY on what the headline "
    "says (not general knowledge about the company). Return ONLY raw JSON:\n"
    "{\n"
    '  "items": [{"i": 0, "sentiment": "Positive|Neutral|Negative"}],\n'
    '  "overall_sentiment": "Positive|Neutral|Negative|Mixed",\n'
    '  "score": -1.0 to 1.0,\n'
    '  "reason": "one short sentence on why, citing the most material headline(s)"\n'
    "}\n"
    "No markdown fences, no preamble."
)


def score_sentiment(symbol: str, headlines: list) -> dict:
    """LLM-scores a list of {title,...} headlines. Returns
    {available, overall_sentiment, score, reason, items:[{title,...,sentiment}]}.
    Never raises."""
    if not headlines:
        return {"available": False, "reason": "No headlines to score."}

    ckey = "sent_" + hashlib.md5(
        (symbol + "|" + "|".join(h["title"] for h in headlines)).encode("utf-8")
    ).hexdigest()
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key in ("", "your_api_key_here"):
        return {"available": False, "reason": "AI sentiment scorer not configured."}

    try:
        from tools.groq_client import groq_chat, parse_json_loose
        listing = "\n".join(f"{i}. {h['title']}" for i, h in enumerate(headlines))
        raw = groq_chat(
            messages=[
                {"role": "system", "content": _SENT_SYS},
                {"role": "user", "content": f"Stock: {symbol}\n\nHEADLINES:\n{listing}"},
            ],
            temperature=0.1, max_tokens=900, api_key=api_key,
        )
        data = parse_json_loose(raw) or {}
        by_i = {}
        for it in (data.get("items") or []):
            if isinstance(it, dict) and "i" in it:
                by_i[int(it["i"])] = str(it.get("sentiment") or "Neutral").strip().title()
        enriched = []
        for i, h in enumerate(headlines):
            enriched.append({**h, "sentiment": by_i.get(i, "Neutral")})
        out = {
            "available": True,
            "overall_sentiment": str(data.get("overall_sentiment") or "Neutral").strip().title(),
            "score": data.get("score"),
            "reason": str(data.get("reason") or "").strip(),
            "items": enriched,
        }
        _write_cache(ckey, out)
        return out
    except Exception as e:
        print(f"[news_sentiment] scoring failed for {symbol}: {e}")
        return {"available": False, "reason": f"Sentiment scoring failed: {e}"}


def get_news_sentiment(symbol: str, name: str = None) -> dict:
    """Public entry: fetch + score in one call. Never raises."""
    headlines = fetch_news(symbol, name)
    if not headlines:
        return {"available": False, "reason": "No recent news found on Moneycontrol/ET/LiveMint for this company.", "headlines": []}
    scored = score_sentiment(symbol, headlines)
    if not scored.get("available"):
        return {"available": False, "reason": scored.get("reason", "Sentiment scoring unavailable."), "headlines": headlines}
    return {
        "available": True,
        "overall_sentiment": scored["overall_sentiment"],
        "score": scored.get("score"),
        "reason": scored.get("reason"),
        "headlines": scored["items"],
    }


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "TATASTEEL"
    print(json.dumps(get_news_sentiment(sym), indent=2, default=str))
