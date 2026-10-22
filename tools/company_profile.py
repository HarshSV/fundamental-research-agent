"""Company profile for the stock page's About section: the descriptive paragraphs, headquarters, year of incorporation,
MD / CEO, website, and a link to the latest Annual Report.

Sources, in order:
  * NSE Market Lens public API (the exchange's own company-profile record) - description, headquarters, founded year,
    MD / CEO, website. Cached on disk for a week.
  * Yahoo Finance profile (our price provider) - fallback for any field NSE does not return (or when NSE is unreachable).
  * BSE / NSE Annual Report filing list - the latest Annual Report PDF link.
A field no source provides is None - never a placeholder."""
from __future__ import annotations

import html
import json
import os
import re
import time

import requests

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "profile")
_PROFILE_TTL = 7 * 86400
_AR_TTL = 86400
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://marketlens.nseindia.com/", "Accept": "application/json"}


def _cache_get(key: str, ttl: float):
    try:
        p = os.path.join(_CACHE_DIR, key + ".json")
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _cache_put(key: str, value) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(os.path.join(_CACHE_DIR, key + ".json"), "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
    except Exception:
        pass


def _paragraphs(raw: str | None) -> list[str]:
    """NSE's description is small HTML (<br/><br/> between paragraphs, an <a> for the e-mail): plain-text paragraphs."""
    if not raw:
        return []
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    out = []
    for block in re.split(r"\n\s*\n|\n{2,}", text.replace("\r", "")):
        block = re.sub(r"[ \t]+", " ", block.replace("\n", " ")).strip()
        if block:
            out.append(block)
    return out


def _from_nse(sym: str) -> dict | None:
    try:
        r = requests.get(f"https://marketlens.nseindia.com/api/stocks/{sym}", headers=_UA, timeout=20)
        d = (r.json() or {}).get("data") if r.status_code == 200 else None
    except Exception:
        return None
    if not d:
        return None
    founded = d.get("foundedYear")
    return {
        "paragraphs": _paragraphs(d.get("description")),
        "headquarters": (d.get("headquarters") or None),
        "incorporation_year": int(founded) if isinstance(founded, (int, float)) and founded else None,
        "leader": ({"name": d["ceoName"], "title": "MD / CEO"} if d.get("ceoName") else None),
        "website": (d.get("website") or None),
        "source": "nse",
    }


def _from_yahoo(sym: str) -> dict | None:
    try:
        import yfinance as yf
        info = yf.Ticker(f"{sym}.NS").info or {}
    except Exception:
        return None
    if not info:
        return None
    hq = ", ".join(x for x in (info.get("city"), info.get("state")) if x) or None
    leader = None
    for o in info.get("companyOfficers") or []:
        title = (o.get("title") or "")
        if re.search(r"\b(ceo|managing director|md)\b", title, re.I):
            nm = re.sub(r"^(Mr|Ms|Mrs|Dr)\.?\s+", "", o.get("name") or "")
            nm = re.split(r"\s+(?:B\.|M\.|Ph\.?D\b|CA\b|MBA\b|BE\b|BTech\b|MTech\b)", nm)[0]   # drop trailing degrees
            leader = {"name": re.sub(r"\s+", " ", nm).strip(), "title": "MD / CEO"}
            break
    site = info.get("website")
    return {
        "paragraphs": _paragraphs(info.get("longBusinessSummary")),
        "headquarters": hq,
        "incorporation_year": None,
        "leader": leader,
        "website": re.sub(r"^https?://", "", site).rstrip("/") if site else None,
        "source": "yahoo",
    }


def latest_annual_report(symbol: str, name: str | None) -> dict | None:
    """{year, url} of the newest Annual Report filing (BSE first, NSE as fallback), or None."""
    key = f"ar_{symbol}"
    hit = _cache_get(key, _AR_TTL)
    if hit is not None:
        return hit or None
    out = None
    try:
        from tools.annual_report_financials import _resolve_scrip_code, _sess
        code = _resolve_scrip_code(symbol, name)
        if code:
            r = _sess().get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}", timeout=25)
            rows = [x for x in (json.loads(r.text).get("Table") or []) if str(x.get("Year", "")).isdigit() and x.get("PDFDownload")]
            if rows:
                best = max(rows, key=lambda x: int(x["Year"]))
                out = {"year": int(best["Year"]), "url": best["PDFDownload"], "source": "bse"}
    except Exception as e:
        print(f"[company_profile] BSE annual report lookup failed for {symbol}: {e}")
    if out is None:
        try:
            from tools.nse_annual_reports import nse_annual_reports
            links = nse_annual_reports(symbol)
            if links:
                y = max(links)
                out = {"year": y, "url": links[y], "source": "nse"}
        except Exception as e:
            print(f"[company_profile] NSE annual report lookup failed for {symbol}: {e}")
    _cache_put(key, out or {})
    return out


def get_profile(symbol: str, name: str | None = None) -> dict:
    sym = symbol.strip().upper()
    base = _cache_get(f"p_{sym}", _PROFILE_TTL)
    if base is None:
        nse = _from_nse(sym)
        yh = None
        need = (not nse) or not all(nse.get(k) for k in ("paragraphs", "headquarters", "leader", "website"))
        if need:
            yh = _from_yahoo(sym)
        base = {"paragraphs": [], "headquarters": None, "incorporation_year": None, "leader": None, "website": None, "source": None}
        for src in (nse, yh):  # NSE wins; Yahoo only fills what is still missing
            if not src:
                continue
            for k in ("paragraphs", "headquarters", "incorporation_year", "leader", "website"):
                if not base[k] and src.get(k):
                    base[k] = src[k]
        if any(base[k] for k in ("paragraphs", "headquarters", "incorporation_year", "leader", "website")):
            base["source"] = (nse or {}).get("source") if nse else (yh or {}).get("source")
            _cache_put(f"p_{sym}", base)
    return {**base, "annual_report": latest_annual_report(sym, name)}
