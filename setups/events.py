"""Events layer: what the company has filed or what is being reported about it, newest first.

Sources (each independent; one failing never blocks the others, and the answer says which ones were read):
  NSE   corporate announcements and the board-meeting calendar (official, www.nseindia.com)
  BSE   corporate announcements (official, api.bseindia.com) - only for companies with a BSE scrip code
  News  Google News headlines for the company (headline, outlet and link only; no summary, no sentiment)

Nothing here is interpreted: no sentiment score, no "good / bad news" call. The reader sees the headline and decides."""
from __future__ import annotations

import datetime as _dt
import html
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

# Imported here, not inside the worker threads: two threads importing urllib3's ssl module for the first time deadlock.
import requests  # noqa: E402,F401
try:
    from curl_cffi import requests as _curl  # noqa: F401
except Exception:  # pragma: no cover
    _curl = None

CACHE_SECONDS = 20 * 60
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _clean(t: str | None, n: int = 170) -> str:
    t = re.sub(r"\s+", " ", html.unescape(t or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ------------------------------------------------------------------ NSE
def parse_nse_announcements(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        try:
            d = _dt.datetime.strptime((r.get("an_dt") or "")[:20].strip(), "%d-%b-%Y %H:%M:%S")
        except ValueError:
            continue
        out.append({"ts": d.isoformat(), "source": "NSE", "category": _clean(r.get("desc"), 60),
                    "title": _clean(r.get("attchmntText") or r.get("desc")), "link": r.get("attchmntFile") or None})
    return out


def parse_nse_calendar(rows: list[dict], today: _dt.date) -> list[dict]:
    """Board meetings scheduled from today on."""
    out = []
    for r in rows or []:
        try:
            d = _dt.datetime.strptime(r.get("date") or "", "%d-%b-%Y").date()
        except ValueError:
            continue
        if d >= today:
            out.append({"date": d.isoformat(), "purpose": _clean(r.get("purpose"), 80), "detail": _clean(r.get("bm_desc"), 200)})
    return sorted(out, key=lambda x: x["date"])


def nse(symbol: str, days: int = 30) -> tuple[list[dict], list[dict]]:
    from curl_cffi import requests as http
    s = http.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements", timeout=20)
    s.headers.update({"Referer": "https://www.nseindia.com/", "Accept": "application/json, text/plain, */*"})
    to = _dt.date.today()
    frm = to - _dt.timedelta(days=days)
    sym = symbol.upper().replace("&", "%26")
    ann = s.get(f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}&from_date={frm:%d-%m-%Y}&to_date={to:%d-%m-%Y}", timeout=25)
    cal = s.get(f"https://www.nseindia.com/api/event-calendar?index=equities&symbol={sym}", timeout=25)
    items = parse_nse_announcements(json.loads(ann.text)) if ann.status_code == 200 and ann.text.strip().startswith("[") else None
    upcoming = parse_nse_calendar(json.loads(cal.text), to) if cal.status_code == 200 and cal.text.strip().startswith("[") else []
    if items is None:
        raise RuntimeError(f"NSE announcements returned {ann.status_code}")
    return items, upcoming


# ------------------------------------------------------------------ BSE
def parse_bse(payload: dict, days: int | None = None) -> list[dict]:
    out = []
    for r in (payload or {}).get("Table", []) or []:
        try:
            d = _dt.datetime.fromisoformat((r.get("NEWS_DT") or r.get("DissemDT") or "")[:19])
        except ValueError:
            continue
        att = r.get("ATTACHMENTNAME")
        out.append({"ts": d.isoformat(), "source": "BSE", "category": _clean(r.get("CATEGORYNAME"), 60),
                    "title": _clean(r.get("NEWSSUB") or r.get("HEADLINE")),
                    "link": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else None})
    return out


def bse(symbol: str, name: str | None, days: int = 30) -> list[dict]:
    from tools import bse_scraper as b
    code = b._resolve_scrip_code(symbol, name)
    if not code:
        return []
    to = time.strftime("%Y%m%d")
    frm = time.strftime("%Y%m%d", time.localtime(time.time() - days * 86400))
    r = b._sess().get("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
                      f"pageno=1&strCat=-1&subcategory=-1&strPrevDate={frm}&strToDate={to}&strSearch=P&strscrip={code}&strType=C", timeout=25)
    if r.status_code != 200 or not r.text.strip().startswith("{"):
        raise RuntimeError(f"BSE announcements returned {r.status_code}")
    return parse_bse(json.loads(r.text))


# ------------------------------------------------------------------ Google News
_LEGAL = re.compile(r"\b(limited|ltd|pvt|private|india|industries|corporation|corp|company|co|the)\b\.?", re.I)


def _name_key(name: str | None, symbol: str) -> str:
    """The distinctive word of the company name a headline must contain to be about this company."""
    words = [w for w in re.findall(r"[A-Za-z0-9&]+", _LEGAL.sub(" ", name or symbol)) if len(w) > 2]
    # two distinctive words when the name has them ("Panorama Studios"), so a headline about another "Panorama" is dropped
    return " ".join(words[:2]).lower() if words else symbol.lower()


def parse_google_news(xml_text: str, key: str, now: _dt.datetime | None = None, days: int = 14) -> list[dict]:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter("item"):
        title = html.unescape(it.findtext("title") or "")
        src = html.unescape(it.findtext("source") or "")
        if src and title.endswith(f" - {src}"):
            title = title[: -(len(src) + 3)]
        if not all(w in title.lower() for w in key.split()):                     # a name collision (a different company) is dropped, not guessed at
            continue
        try:
            d = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if (now - d).days > days:
            continue
        out.append({"ts": d.astimezone(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).replace(tzinfo=None).isoformat(),
                    "source": "News", "category": src or "News", "title": _clean(title), "link": it.findtext("link") or None})
    return out


def google_news(symbol: str, name: str | None, days: int = 14) -> list[dict]:
    from urllib.parse import quote
    base = _LEGAL.sub(" ", name or symbol).strip() or symbol
    q = quote(f'"{base}" share OR stock OR results when:{days}d')
    r = requests.get(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        raise RuntimeError(f"Google News returned {r.status_code}")
    return parse_google_news(r.text, _name_key(name, symbol), days=days)


# ------------------------------------------------------------------ all of it
def collect(symbol: str, name: str | None, bse_listed: bool = True) -> dict:
    """{items (newest first), upcoming (board meetings), sources {name: 'ok' | 'unavailable'}}. Cached for 20 minutes."""
    key = symbol.upper()
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    if bse_listed:
        import tools.bse_scraper  # noqa: F401  (loaded before the threads start)
    jobs = {"NSE": lambda: nse(symbol), "News": lambda: google_news(symbol, name)}
    if bse_listed:
        jobs["BSE"] = lambda: bse(symbol, name)
    res: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {k: ex.submit(f) for k, f in jobs.items()}
        for k, f in futs.items():
            try:
                res[k] = f.result(timeout=30)
            except Exception:
                res[k] = None
    items: list[dict] = []
    upcoming: list[dict] = []
    sources = {}
    for k, v in res.items():
        sources[k] = "unavailable" if v is None else "ok"
        if v is None:
            continue
        if k == "NSE":
            items += v[0]
            upcoming = v[1]
        else:
            items += v
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        sig = re.sub(r"\W+", "", it["title"].lower())[:60]
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(it)
    # a busy filing stream must not push every headline out (or the other way round): at most 7 of each kind, newest first
    filings = [i for i in uniq if i["source"] != "News"][:7]
    news = [i for i in uniq if i["source"] == "News"][:7]
    out = {"items": sorted(filings + news, key=lambda x: x["ts"], reverse=True), "upcoming": upcoming[:3], "sources": sources}
    ttl = CACHE_SECONDS if all(v == "ok" for v in sources.values()) else 3 * 60     # a partial answer is retried soon
    if any(v == "ok" for v in sources.values()):         # do not cache a total failure: try again on the next view
        with _lock:
            _cache[key] = (time.time() + ttl - CACHE_SECONDS, out)
    return out
