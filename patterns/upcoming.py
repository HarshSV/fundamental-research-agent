"""Scheduled events ahead, for the sector outlook. Only events with a published date are listed; nothing is guessed.

Sources (each read when first needed and kept for a few hours; a source that cannot be read is reported, never replaced by a guess):
  * US Federal Reserve policy meetings        federalreserve.gov/monetarypolicy/fomccalendars.htm (two-day meetings; single-day lines are minutes)
  * NSE trading holidays                       nseindia.com holiday-master
  * Company actions with ex-dates ahead        nseindia.com corporates-corporateActions (dividends, bonus, splits, buy-backs, rights), grouped by sector
  * Results and board meetings                 the NSE event calendar already read by patterns/exchange_data.py
  * Dates kept by hand                         patterns/upcoming_events.json (for example the Union Budget, or an RBI policy date), only when they carry a date
  * RBI policy dates                           RBI does not publish them in a form we can read reliably, so the page links to current headlines about the schedule instead
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests

from . import exchange_data as ex
from . import scan

MANUAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upcoming_events.json")
UA = {"User-Agent": "Mozilla/5.0"}
TTL = 6 * 3600
_cache: dict = {}
MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}
ACTION_WORDS = ("dividend", "bonus", "split", "sub-division", "buy back", "buyback", "rights")


def _cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        val = {"ok": True, "items": fn()}
    except Exception as e:
        val = {"ok": False, "items": [], "error": str(e)[:120]}
    _cache[key] = (time.time(), val)
    return val


def _fomc() -> list[dict]:
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", requests.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", headers=UA, timeout=30).text))
    out = []
    for y in (date.today().year, date.today().year + 1):
        i = t.find(f"{y} FOMC Meetings")
        if i < 0:
            continue
        m2 = re.search(r"\d{4} FOMC Meetings", t[i + 20:])
        seg = t[i: i + 20 + m2.start()] if m2 else t[i: i + 1500]
        last_month = 0
        for mon, a, b in re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})-(\d{1,2})", seg):
            if MONTHS[mon] < last_month:            # the months run January to December within a year; a drop means the next year's table began
                break
            last_month = MONTHS[mon]
            try:
                end = date(y, MONTHS[mon], int(b))
            except ValueError:
                continue
            out.append({"date": end.isoformat(), "title": f"US Federal Reserve policy decision ({mon} {a}-{b})", "scope": "market", "source": "federalreserve.gov"})
    return out


def _holidays() -> list[dict]:
    s = ex._session()
    rows = s.get("https://www.nseindia.com/api/holiday-master?type=trading", timeout=30).json().get("CM", [])
    out = []
    for r in rows:
        try:
            d = datetime.strptime(r["tradingDate"], "%d-%b-%Y").date()
        except Exception:
            continue
        out.append({"date": d.isoformat(), "title": f"NSE closed: {r['description'].strip('* ')}", "scope": "market", "source": "nseindia.com"})
    return out


def _actions(days: int = 30) -> list[dict]:
    s = ex._session()
    a, b = date.today(), date.today() + timedelta(days=days)
    rows = s.get(f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={a:%d-%m-%Y}&to_date={b:%d-%m-%Y}", timeout=30).json()
    out = []
    for r in rows if isinstance(rows, list) else []:
        subj = (r.get("subject") or "")
        if not any(w in subj.lower() for w in ACTION_WORDS):
            continue
        try:
            d = datetime.strptime(r["exDate"], "%d-%b-%Y").date()
        except Exception:
            continue
        out.append({"date": d.isoformat(), "symbol": r.get("symbol"), "name": r.get("comp"), "subject": subj})
    return out


def _manual() -> list[dict]:
    try:
        with open(MANUAL, encoding="utf-8") as fh:
            ev = json.load(fh).get("events", [])
    except Exception:
        return []
    return [e for e in ev if e.get("date") and e.get("title")]


def _rbi_headlines() -> list[dict]:
    import xml.etree.ElementTree as ET
    r = requests.get("https://news.google.com/rss/search?q=" + quote("RBI MPC meeting schedule FY27 dates") + "&hl=en-IN&gl=IN&ceid=IN:en", headers=UA, timeout=20)
    out = []
    for it in ET.fromstring(r.text).iter("item"):
        t = (it.findtext("title") or "").strip()
        if re.search(r"schedule|calendar|dates", t, re.I) and re.search(r"MPC|monetary", t, re.I):
            out.append({"title": t, "link": it.findtext("link"), "date": (it.findtext("pubDate") or "")[5:16]})
    return out[:3]


def market(days: int = 60) -> dict:
    """Events ahead that affect every sector, soonest first, with a note for each source that could not be read."""
    today = date.today().isoformat()
    end = (date.today() + timedelta(days=days)).isoformat()
    srcs = {"fed": _cached("fomc", _fomc), "holidays": _cached("hol", _holidays), "manual": _cached("man", _manual)}
    items = []
    for k, v in srcs.items():
        for e in v["items"]:
            if today <= e["date"] <= end:
                items.append({"date": e["date"], "title": e["title"], "scope": e.get("scope", "market"), "source": e.get("source") or "kept by hand",
                              "expected": bool(e.get("expected"))})
    items.sort(key=lambda x: x["date"])
    problems = [f"{k}: {v.get('error')}" for k, v in srcs.items() if not v["ok"]]
    rbi = _cached("rbi", _rbi_headlines)
    return {"events": items, "unreadable": problems, "rbi_headlines": rbi["items"],
            "note": "Only events with a published date are listed. RBI policy dates are not listed, because no source we can read reliably gives them; see the linked headlines."}


def sector_actions(sector: str) -> dict:
    """Company actions with ex-dates in the next 30 days among the sector's stocks."""
    rows = scan._load_all()
    syms = {s for s, r in rows.items() if r.get("sector") == sector}
    got = _cached("actions", _actions)
    mine = [a for a in got["items"] if a.get("symbol") in syms]
    mine.sort(key=lambda a: a["date"])
    kinds = {"dividend": 0, "bonus": 0, "split": 0, "buyback": 0, "rights": 0}
    for a in mine:
        s = a["subject"].lower()
        for k, words in (("dividend", ("dividend",)), ("bonus", ("bonus",)), ("split", ("split", "sub-division")), ("buyback", ("buy back", "buyback")), ("rights", ("rights",))):
            if any(w in s for w in words):
                kinds[k] += 1
    return {"ok": got["ok"], "count": len(mine), "kinds": {k: v for k, v in kinds.items() if v}, "items": mine[:6], "error": got.get("error")}
