"""Sector history: how each sector has behaved since about 1996, built from its member stocks' adjusted daily history.

How it is built
  * data/sector_history/monthly.json keeps, per stock, its month-end closes (split/bonus adjusted, from the price provider's full history).
    `refresh()` fills it in the background, a few stocks at a time, and is safe to stop and restart.
  * A sector's monthly return is the average of its members' returns that month (equal-weighted); the index is those returns compounded.
    A month counts only when at least MIN_MEMBERS members have a return for it, so a sector starts when it has enough stocks, not before.
  * "All stocks" (every scanned stock, same method) is the yardstick for relative strength.

Limits, stated on the page as well
  * Only stocks that exist today are included, so the past looks better than it really was (survivorship).
  * The scanned universe is about 750 stocks, not the whole market.
  * Nothing before the provider's own history (about 1996) can be built. A figure that cannot be computed is None, never 0."""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import scan

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sector_history")
STORE = os.path.join(ROOT, "monthly.json")
MIN_MEMBERS = 5
MARKET = "All stocks"
_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "started": None, "finished": None, "failed": 0}
_cache: dict = {}


# ------------------------------------------------------------------ the store
def _load() -> dict:
    try:
        with open(STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save(d: dict) -> None:
    os.makedirs(ROOT, exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.replace(tmp, STORE)


def _month_ends(candles: list[dict]) -> list[list]:
    """[[yyyymm, close]] for the last session of each month."""
    last: dict[int, float] = {}
    for c in candles:
        if not c.get("close"):
            continue
        d = datetime.fromtimestamp(c["time"], timezone.utc)
        last[d.year * 100 + d.month] = float(c["close"])
    return [[k, last[k]] for k in sorted(last)]


def _one(sym: str):
    from tools.live_chart_yf import get_candles
    cs = get_candles(sym, interval="1d", period="max")
    return sym, (_month_ends(cs) if cs else None)


def refresh(max_age_days: int = 7, workers: int = 4) -> dict:
    """Fill / update the store for every scanned stock whose entry is missing or older than max_age_days. Returns the state."""
    with _lock:
        if _state["running"]:
            return dict(_state)
        _state.update(running=True, done=0, failed=0, started=time.time(), finished=None)
    try:
        rows = scan._load_all()
        store = _load()
        now = time.time()
        todo = [s for s in rows if not store.get(s) or now - store[s].get("at", 0) > max_age_days * 86400]
        _state["total"] = len(todo)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (sym, me) in enumerate(pool.map(_one, todo), 1):
                if me:
                    store[sym] = {"at": now, "m": me}
                else:
                    _state["failed"] += 1
                _state["done"] = i
                if i % 40 == 0:
                    _save(store)
        _save(store)
    finally:
        _state.update(running=False, finished=time.time())
    return dict(_state)


def start_refresh_background() -> dict:
    if not _state["running"]:
        threading.Thread(target=refresh, daemon=True).start()
    return dict(_state)


def status() -> dict:
    store = _load()
    return {**_state, "stocks_stored": len(store)}


# ------------------------------------------------------------------ the maths
def _ym_index(ym: int) -> int:
    return (ym // 100) * 12 + (ym % 100) - 1


def _ym_label(i: int) -> str:
    return f"{i // 12}-{i % 12 + 1:02d}"


def _group_returns(members: list[list[list]]) -> dict[int, tuple[float, int]]:
    """{month index: (equal-weighted return, members counted)} for a group of stocks, each a list of [yyyymm, close]."""
    acc: dict[int, list[float]] = {}
    for m in members:
        prev = None
        for ym, c in m:
            i = _ym_index(ym)
            if prev is not None and i == prev[0] + 1 and prev[1] > 0:
                acc.setdefault(i, []).append(c / prev[1] - 1.0)
            prev = (i, c)
    return {i: (sum(v) / len(v), len(v)) for i, v in acc.items() if len(v) >= MIN_MEMBERS}


def _index_series(rets: dict[int, tuple[float, int]]) -> list[tuple[int, float, int]]:
    """[(month index, index level, members)] with the level starting at 100 the month before the first return. Contiguous months only."""
    if not rets:
        return []
    ks = sorted(rets)
    out, level = [], 100.0
    out.append((ks[0] - 1, level, rets[ks[0]][1]))
    last = ks[0] - 1
    for k in ks:
        if k != last + 1:                       # a gap in membership coverage: restart would mislead, so stop the series here
            break
        level *= 1.0 + rets[k][0]
        out.append((k, level, rets[k][1]))
        last = k
    return out


def _pct(a, b):
    return (a / b - 1.0) * 100.0 if a is not None and b else None


def _round(v, d=1):
    return None if v is None else round(v, d)


def _analyse(series: list[tuple[int, float, int]], bench: dict[int, float], start_i: int | None) -> dict:
    """All the history statistics for one index series, optionally from a later start month."""
    s = [x for x in series if start_i is None or x[0] >= start_i]
    if len(s) < 13:
        return {"available": False, "reason": "Fewer than 12 months of history in this window."}
    lv = {i: v for i, v, _ in s}
    first, last = s[0][0], s[-1][0]
    years_span = (last - first) / 12.0
    cagr = ((lv[last] / lv[first]) ** (1 / years_span) - 1.0) * 100.0 if years_span >= 1 else None

    # calendar years with a full set of months only (the first and last year are partial and are marked)
    yearly = []
    for y in range(first // 12, last // 12 + 1):
        a, b = y * 12 - 1, y * 12 + 11            # December of the year before, December of this year
        lo = max(a, first)
        hi = min(b, last)
        if hi <= lo or lo not in lv or hi not in lv:
            continue
        ret = _pct(lv[hi], lv[lo])
        bret = _pct(bench.get(hi), bench.get(lo)) if lo in bench and hi in bench else None
        yearly.append({"year": y, "return": _round(ret), "market": _round(bret), "partial": lo != a or hi != b,
                       "beat_market": None if ret is None or bret is None else ret > bret})
    full = [y for y in yearly if not y["partial"] and y["return"] is not None]
    best = max(full, key=lambda y: y["return"], default=None)
    worst = min(full, key=lambda y: y["return"], default=None)
    pos = sum(1 for y in full if y["return"] > 0)
    comp = [y for y in full if y["beat_market"] is not None]

    # deepest fall from a peak (monthly closes), with the date it was reached and when it was regained
    peak_i, peak_v, worst_dd = s[0][0], s[0][1], (0.0, s[0][0], s[0][0])
    for i, v, _ in s:
        if v > peak_v:
            peak_i, peak_v = i, v
        dd = v / peak_v - 1.0
        if dd < worst_dd[0]:
            worst_dd = (dd, peak_i, i)
    dd, p_i, t_i = worst_dd
    rec = next((i for i, v, _ in s if i > t_i and v >= lv[p_i]), None)
    drawdown = {"depth": _round(dd * 100), "peak": _ym_label(p_i), "trough": _ym_label(t_i),
                "recovered": _ym_label(rec) if rec is not None else None,
                "months_down": t_i - p_i, "months_to_recover": (rec - t_i) if rec is not None else None}
    now_dd = _round((s[-1][1] / max(v for _, v, _ in s) - 1.0) * 100)

    rolling = {}
    for yrs in (1, 3, 5, 10):
        n = yrs * 12
        outs = [((lv[i] / lv[i - n]) ** (1 / yrs) - 1.0) * 100.0 for i in lv if i - n in lv]
        if len(outs) >= 12:
            outs.sort()
            rolling[str(yrs)] = {"windows": len(outs), "worst": _round(outs[0]), "median": _round(statistics.median(outs)),
                                 "best": _round(outs[-1]), "positive_share": _round(sum(1 for x in outs if x > 0) / len(outs) * 100, 0)}

    months: dict[int, list[float]] = {m: [] for m in range(12)}
    for i, v, _ in s:
        if i - 1 in lv:
            months[i % 12].append((v / lv[i - 1] - 1.0) * 100.0)
    seasonal = [{"month": m + 1, "average": _round(statistics.mean(v)) if len(v) >= 5 else None,
                 "positive_share": _round(sum(1 for x in v if x > 0) / len(v) * 100, 0) if len(v) >= 5 else None, "months": len(v)}
                for m, v in months.items()]

    return {"available": True, "from": _ym_label(first), "to": _ym_label(last), "years": round(years_span, 1),
            "members_start": s[0][2], "members_now": s[-1][2], "cagr": _round(cagr), "total_return": _round(_pct(lv[last], lv[first]), 0),
            "yearly": yearly, "best_year": best, "worst_year": worst,
            "positive_years": {"count": pos, "of": len(full)} if full else None,
            "beat_market_years": {"count": sum(1 for y in comp if y["beat_market"]), "of": len(comp)} if comp else None,
            "max_drawdown": drawdown, "drawdown_now": now_dd, "rolling": rolling, "seasonal": seasonal,
            "curve": [{"m": _ym_label(i), "v": round(v, 2)} for i, v, _ in s[:: max(1, len(s) // 400)]] + ([{"m": _ym_label(s[-1][0]), "v": round(s[-1][1], 2)}] if (len(s) - 1) % max(1, len(s) // 400) else [])}


def build(window: str = "full") -> dict:
    """Every sector's history statistics. window "full" uses everything stored (about 1996 on); "5y" only the last 60 months."""
    store = _load()
    if not store:
        return {"ready": False, "note": "The sector history has not been built yet.", **status()}
    rows = scan._load_all()
    mt = os.path.getmtime(STORE)
    key = (mt, window)
    if key in _cache:
        return _cache[key]
    groups: dict[str, list[list[list]]] = {}
    allm: list[list[list]] = []
    for sym, rec in store.items():
        sec = (rows.get(sym) or {}).get("sector")
        if not sec or not rec.get("m"):
            continue
        groups.setdefault(sec, []).append(rec["m"])
        allm.append(rec["m"])
    mk = _index_series(_group_returns(allm))
    bench = {i: v for i, v, _ in mk}
    start_i = None
    if window == "5y" and mk:
        start_i = mk[-1][0] - 60
    out = []
    for sec, members in groups.items():
        series = _index_series(_group_returns(members))
        # A sector's headline figures start only once enough of its stocks have a price (half of them, at least 5 and at most 8):
        # an index of two or three survivors says little about the sector.
        need = max(MIN_MEMBERS, min(8, -(-len(members) // 2)))
        first_ok = next((i for i, _, m in series if m >= need), None)
        if len(members) < MIN_MEMBERS or first_ok is None:
            out.append({"sector": sec, "stocks_with_history": len(members), "available": False,
                        "reason": f"Only {len(members)} stocks with history; at least {MIN_MEMBERS} are needed."})
            continue
        a = _analyse(series, bench, max(first_ok, start_i) if start_i is not None else first_ok)
        out.append({"sector": sec, "stocks_with_history": len(members), "members_needed": need, **a})
    out.sort(key=lambda x: (-(x.get("cagr") if x.get("cagr") is not None else -1e9)))
    result = {"ready": True, "window": window, "market": {"name": MARKET, "stocks": len(allm), **_analyse(mk, bench, start_i)},
              "sectors": out,
              "limits": ["Only stocks listed today are included, so the past looks better than it was (survivorship).",
                         "Each sector is an equal-weighted average of its scanned stocks, not the official index.",
                         f"A sector's figures start once about half of its stocks (at least 5) have a price, so early years rest on few stocks.",
                         "Prices are adjusted for splits and bonuses by the provider; dividends are not included."],
              "as_of": _ym_label(mk[-1][0]) if mk else None}
    _cache.clear()
    _cache[key] = result
    return result

_levels_cache: dict = {}


def levels() -> dict | None:
    """{"market": {month index: level}, "sectors": {name: {month index: level}}} from each sector's first reliable month (same rule as
    build()), for the event studies. None when the history has not been built."""
    store = _load()
    if not store:
        return None
    key = os.path.getmtime(STORE)
    if _levels_cache.get("key") == key:
        return _levels_cache["v"]
    rows = scan._load_all()
    groups: dict[str, list] = {}
    allm = []
    for sym, rec in store.items():
        sec = (rows.get(sym) or {}).get("sector")
        if sec and rec.get("m"):
            groups.setdefault(sec, []).append(rec["m"])
            allm.append(rec["m"])
    mk = _index_series(_group_returns(allm))
    out = {}
    for sec, members in groups.items():
        series = _index_series(_group_returns(members))
        need = max(MIN_MEMBERS, min(8, -(-len(members) // 2)))
        first_ok = next((i for i, _, m in series if m >= need), None)
        if len(members) >= MIN_MEMBERS and first_ok is not None:
            out[sec] = {i: v for i, v, _ in series if i >= first_ok}
    v = {"market": {i: v for i, v, _ in mk}, "sectors": out, "members": {s: [m for m in groups[s]] and [sym for sym, rec in store.items() if (rows.get(sym) or {}).get("sector") == s] for s in out}}
    _levels_cache.clear()
    _levels_cache.update(key=key, v=v)
    return v
