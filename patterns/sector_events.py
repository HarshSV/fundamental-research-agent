"""What moved a sector: its biggest months set against the market, lined up with dated events, plus how it reacted to each event, and
what is happening now among its companies.

Nothing here is written by a model. Every number is computed from the stored prices (patterns/sector_history.py) and from the exchange feeds
(patterns/exchange_data.py); the event names and months come from patterns/sector_events.json, an editorial list. An event next to a move is
shown as "around then", never as its cause. A value that cannot be computed is None."""
from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests

from . import exchange_data as ex
from . import scan, sector_history

CATALOGUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_events.json")
TOP_MOVES = 6
_news_cache: dict = {}


def _catalogue() -> list[dict]:
    try:
        with open(CATALOGUE, encoding="utf-8") as fh:
            return json.load(fh)["events"]
    except Exception:
        return []


def _idx(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def _label(i: int) -> str:
    return f"{i // 12}-{i % 12 + 1:02d}"


def _ret(lv: dict, a: int, b: int):
    return (lv[b] / lv[a] - 1.0) * 100.0 if a in lv and b in lv and lv[a] else None


def _r(v, d=1):
    return None if v is None else round(v, d)


def _applies(ev: dict, sector: str) -> bool:
    return ev.get("scope") == "market" or sector in (ev.get("sectors") or [])


def analyse(sector: str) -> dict:
    lv = sector_history.levels()
    if lv is None:
        return {"ready": False, "note": "The sector history has not been built yet."}
    sl = lv["sectors"].get(sector)
    if not sl:
        return {"ready": True, "sector": sector, "available": False, "reason": "This sector has too few stocks with history."}
    mk = lv["market"]
    months = sorted(sl)
    first = months[0]
    events = [e for e in _catalogue() if _applies(e, sector)]

    # ---- the biggest months, split into the part that moved with the market and the part specific to the sector
    rows = []
    for i in months[1:]:
        s1, m1 = _ret(sl, i - 1, i), _ret(mk, i - 1, i)
        if s1 is None or m1 is None:
            continue
        rows.append({"i": i, "sector": s1, "market": m1, "excess": s1 - m1})
    ups = sorted(rows, key=lambda r: -r["excess"])[:TOP_MOVES]
    downs = sorted(rows, key=lambda r: r["excess"])[:TOP_MOVES]

    def near(i: int):
        return [{"month": e["month"], "title": e["title"], "scope": e["scope"]} for e in events if abs(_idx(e["month"]) - i) <= 1]

    def view(r):
        kind = "moved with the market" if abs(r["excess"]) < 0.5 * abs(r["market"]) or abs(r["excess"]) < 3 else "specific to this sector"
        return {"month": _label(r["i"]), "sector_return": _r(r["sector"]), "market_return": _r(r["market"]), "excess": _r(r["excess"]),
                "kind": kind, "events": near(r["i"])}
    out_moves = {"outperformed": [view(r) for r in sorted(ups, key=lambda r: r["i"])],
                 "underperformed": [view(r) for r in sorted(downs, key=lambda r: r["i"])]}

    # ---- how it reacted to each event: the month of the event, and the three months after, against the market
    study = []
    for e in events:
        i = _idx(e["month"])
        if i - 1 < first or i not in sl:
            continue
        s0, m0 = _ret(sl, i - 1, i), _ret(mk, i - 1, i)
        s3, m3 = _ret(sl, i, i + 3), _ret(mk, i, i + 3)
        study.append({"month": e["month"], "title": e["title"], "scope": e["scope"], "sector_month": _r(s0), "market_month": _r(m0),
                      "sector_after_3m": _r(s3), "market_after_3m": _r(m3),
                      "excess_month": _r(s0 - m0) if s0 is not None and m0 is not None else None})
    study.sort(key=lambda x: x["month"])

    # ---- sensitivity to the market, over all months
    pairs = [(r["sector"], r["market"]) for r in rows]
    beta = down_cap = up_cap = None
    if len(pairs) >= 24:
        sx, mx = [p[0] for p in pairs], [p[1] for p in pairs]
        var = statistics.pvariance(mx)
        if var:
            mean_s, mean_m = statistics.mean(sx), statistics.mean(mx)
            beta = sum((a - mean_s) * (b - mean_m) for a, b in pairs) / len(pairs) / var
        up = [(a, b) for a, b in pairs if b > 0]
        dn = [(a, b) for a, b in pairs if b < 0]
        if up and sum(b for _, b in up):
            up_cap = sum(a for a, _ in up) / sum(b for _, b in up) * 100
        if dn and sum(b for _, b in dn):
            down_cap = sum(a for a, _ in dn) / sum(b for _, b in dn) * 100
    corr = None
    if len(pairs) >= 24:
        try:
            corr = statistics.correlation([p[0] for p in pairs], [p[1] for p in pairs])
        except Exception:
            corr = None
    return {"ready": True, "sector": sector, "available": True, "from": _label(first), "to": _label(months[-1]),
            "beta": _r(beta, 2), "correlation": _r(corr, 2), "up_capture": _r(up_cap, 0), "down_capture": _r(down_cap, 0),
            "moves": out_moves, "reactions": study,
            "events_known": len(events),
            "note": "Events are an editorial list (patterns/sector_events.json). 'Around then' is not 'because of': prices move for many reasons at once."}


# ------------------------------------------------------------------ headlines for a past month (on demand)
_STOP = re.compile(r"\b(india|indian|sensex|nifty|rbi|market|markets|stocks?|shares?|economy)\b", re.I)


def headlines(sector: str, month: str, limit: int = 8) -> dict:
    """Google News headlines for the sector in one past month. They are searched by the sector's name and kept only when the title
    mentions India or the market; some can still be loosely related, so the page says so."""
    key = (sector, month)
    hit = _news_cache.get(key)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    word = re.sub(r"\(.*?\)", "", sector).replace("&", "and").strip()
    q = quote(f'India {word} sector stocks after:{start.isoformat()} before:{end.isoformat()}')
    items = []
    try:
        r = requests.get(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            import xml.etree.ElementTree as ET
            from email.utils import parsedate_to_datetime
            for it in ET.fromstring(r.text).iter("item"):
                title = (it.findtext("title") or "").strip()
                src = (it.findtext("source") or "").strip()
                if src and title.endswith(f" - {src}"):
                    title = title[: -(len(src) + 3)]
                if not _STOP.search(title):
                    continue
                try:
                    d = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
                except Exception:
                    d = None
                items.append({"date": d, "title": title, "source": src or None, "link": it.findtext("link") or None})
        ok = r.status_code == 200
    except Exception:
        ok = False
    res = {"sector": sector, "month": month, "ok": ok, "items": items[:limit]}
    _news_cache[key] = (time.time(), res)
    return res


# ------------------------------------------------------------------ what is happening among its companies now
def recent(sector: str) -> dict:
    rows = scan._load_all()
    syms = {s for s, r in rows.items() if r.get("sector") == sector}
    if not syms:
        return {"sector": sector, "stocks": 0}
    names = {s: rows[s].get("name") for s in syms}
    today = date.today()
    out: dict = {"sector": sector, "stocks": len(syms), "as_of": today.isoformat()}

    orders = ex.load("orders") or []
    out["orders"] = [{"time": o.get("time"), "symbol": o["symbol"], "name": names.get(o["symbol"]), "subject": o.get("subject"), "link": o.get("file")}
                     for o in orders if o.get("symbol") in syms][:8]
    out["orders_count"] = sum(1 for o in orders if o.get("symbol") in syms)

    deals = ex.load("deals") or {}
    cutoff = (today - timedelta(days=30)).isoformat()
    dl = []
    for kind in ("bulk", "block"):
        for d in deals.get(kind, []):
            if d.get("symbol") in syms and (d.get("date") or "") >= cutoff and d.get("qty") and d.get("price"):
                dl.append({"date": d["date"], "kind": kind, "symbol": d["symbol"], "name": names.get(d["symbol"]), "client": d.get("client"),
                           "side": d.get("side"), "value_cr": round(d["qty"] * d["price"] / 1e7, 1)})
    dl.sort(key=lambda x: -x["value_cr"])
    out["deals"] = dl[:8]
    out["deals_count"] = len(dl)
    out["deals_buy_cr"] = round(sum(x["value_cr"] for x in dl if (x["side"] or "").upper().startswith("B")), 1)
    out["deals_sell_cr"] = round(sum(x["value_cr"] for x in dl if (x["side"] or "").upper().startswith("S")), 1)

    cal = ex.load("calendar") or []
    horizon = (today + timedelta(days=21)).isoformat()
    up = [{"date": c["date"], "symbol": c["symbol"], "name": names.get(c["symbol"]) or c.get("name"), "purpose": c.get("purpose")}
          for c in cal if c.get("symbol") in syms and today.isoformat() <= (c.get("date") or "") <= horizon]
    up.sort(key=lambda x: x["date"])
    out["upcoming"] = up[:12]
    out["upcoming_count"] = len(up)
    return out
