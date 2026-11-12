"""Market analytics computed from the stored market scan (patterns/scan.py): market breadth, sector strength and rotation.

Everything is equal-weighted across the scanned stocks and uses only stored candles/closes, so it is instant. A value that
cannot be computed is None (never 0); a stock with too little history simply does not count in that statistic."""
from __future__ import annotations

from datetime import datetime, timezone

from . import scan
from .screen_engine import IST, DAY, rrg_quadrants

BREADTH_DAYS = 90        # sessions of history returned for the breadth charts
SMA_FAST, SMA_SLOW = 50, 200


def _num(v) -> bool:
    return isinstance(v, (int, float)) and v == v


def _iso(day: int) -> str:
    return datetime.fromtimestamp(day * DAY, timezone.utc).strftime("%Y-%m-%d")


def _pct(a, b):
    return (a / b - 1.0) * 100.0 if a is not None and b else None


def _avg(vals):
    vals = [v for v in vals if _num(v)]
    return sum(vals) / len(vals) if vals else None


def _share(count: int, total: int):
    return round(count / total * 100.0, 1) if total else None


def _change(closes, bars):
    return _pct(closes[-1][1], closes[-1 - bars][1]) if len(closes) > bars and closes[-1 - bars][1] else None


def _latest_rows(rows: dict):
    latest = max((r.get("as_of") or 0) for r in rows.values())
    return latest, [r for r in rows.values() if r.get("as_of") == latest]


def breadth() -> dict:
    """How many stocks take part in the market's move: today's advance/decline, share above the 20/50/200-day averages, new 52-week
    highs and lows, plus a history of the share above the 50/200-day averages and of advancing stocks."""
    rows = scan._load_all()
    if not rows:
        return {"stocks": 0}
    latest, group = _latest_rows(rows)
    adv = dec = flat = 0
    above = {20: [0, 0], 50: [0, 0], 200: [0, 0]}
    highs = lows = 0
    for r in group:
        cl = r.get("closes") or []
        if len(cl) >= 2:
            d = cl[-1][1] - cl[-2][1]
            adv, dec, flat = adv + (d > 0), dec + (d < 0), flat + (d == 0)
        for n, c in above.items():
            ma = (r.get("sma") or {}).get(str(n))
            if _num(ma) and _num(r.get("price")):
                c[1] += 1
                c[0] += r["price"] > ma
        if r.get("new_high_days") == 0:
            highs += 1
        if _num(r.get("pct_from_52w_low")) and r["pct_from_52w_low"] <= 0.5:
            lows += 1
    # history, aligned by calendar day, from each stock's stored closes (prefix sums give every day's moving average cheaply)
    per_day: dict = {}
    extra: dict = {}                      # day -> [up 4.5%, down 4.5%, new 52w high (close), new 52w low (close), volume above 20d avg, volume counted]
    for r in group:
        cl = r.get("closes") or []
        # extra breadth series from the stored closes and candles (the candles hold volume for about the last 160 sessions)
        vol_by_day = {}
        bars = [c for c in (r.get("candles") or []) if len(c) >= 6 and _num(c[5])]
        for k in range(20, len(bars)):
            avg = sum(b[5] for b in bars[k - 20:k]) / 20
            if avg > 0:
                vol_by_day[(bars[k][0] + IST) // DAY] = bars[k][5] > avg
        for i in range(max(1, len(cl) - BREADTH_DAYS), len(cl)):
            d = (cl[i][0] + IST) // DAY
            e = extra.setdefault(d, [0, 0, 0, 0, 0, 0])
            ch = _pct(cl[i][1], cl[i - 1][1])
            if ch is not None:
                e[0] += ch >= 4.5
                e[1] += ch <= -4.5
            if i >= 252:
                win = [c for _, c in cl[i - 252:i]]
                e[2] += cl[i][1] > max(win)
                e[3] += cl[i][1] < min(win)
            if d in vol_by_day:
                e[4] += vol_by_day[d]
                e[5] += 1
        if len(cl) < SMA_SLOW + 2:
            continue
        pref = [0.0]
        for _, c in cl:
            pref.append(pref[-1] + c)
        for i in range(max(SMA_SLOW, len(cl) - BREADTH_DAYS), len(cl)):
            d = (cl[i][0] + IST) // DAY
            b = per_day.setdefault(d, [0, 0, 0, 0, 0, 0])
            ma50 = (pref[i + 1] - pref[i + 1 - SMA_FAST]) / SMA_FAST
            ma200 = (pref[i + 1] - pref[i + 1 - SMA_SLOW]) / SMA_SLOW
            b[0] += 1
            b[1] += cl[i][1] > ma50
            b[2] += cl[i][1] > ma200
            b[3] += cl[i][1] > cl[i - 1][1]
    history = [{"date": _iso(d), "above_50": _share(v[1], v[0]), "above_200": _share(v[2], v[0]), "advancing": _share(v[3], v[0]),
                "advances": v[3], "declines": v[0] - v[3],
                "up_4_5": extra.get(d, [None] * 6)[0], "down_4_5": extra.get(d, [None] * 6)[1],
                "highs_52w": extra.get(d, [None] * 6)[2], "lows_52w": extra.get(d, [None] * 6)[3],
                "vol_above_20d": extra.get(d, [None] * 6)[4] if (extra.get(d) and extra[d][5] >= 50) else None}
               for d, v in sorted(per_day.items()) if v[0] >= 50]
    n = len(group)
    return {
        "as_of": _iso((latest + IST) // DAY), "stocks": n, "universe": len(rows),
        "today": {"advancing": adv, "declining": dec, "unchanged": flat,
                  "advancing_pct": _share(adv, n), "new_52w_highs": highs, "new_52w_lows": lows,
                  "above_20": _share(*above[20]), "above_50": _share(*above[50]), "above_200": _share(*above[200])},
        "history": history,
    }


def sectors() -> dict:
    """Each sector (equal-weighted average of its stocks): returns over several periods against the Nifty 500, share of stocks above
    their 50/200-day averages, average RS rating and the rotation quadrant."""
    rows = scan._load_all()
    if not rows:
        return {"sectors": []}
    _, group = _latest_rows(rows)
    bench = scan.benchmarks().get("nifty500") or []
    bret = {k: _change(bench, n) if bench else None for k, n in (("1w", 5), ("1m", 21), ("3m", 63))}
    quad = rrg_quadrants(rows, "weekly", "nifty500") if bench else {}
    by: dict = {}
    for r in group:
        if not r.get("sector") and r.get("exchange") == "BSE":      # BSE-only stocks have no NSE sector: not lumped into a made-up one
            continue
        by.setdefault(r.get("sector") or "Unclassified", []).append(r)
    out = []
    for name, rs in by.items():
        d1 = [_change(r.get("closes") or [], 1) for r in rs]
        w1 = [_change(r.get("closes") or [], 5) for r in rs]
        a50 = [(r["price"] > r["sma"]["50"]) for r in rs if _num(r.get("price")) and _num((r.get("sma") or {}).get("50"))]
        a200 = [(r["price"] > r["sma"]["200"]) for r in rs if _num(r.get("price")) and _num((r.get("sma") or {}).get("200"))]
        row = {"name": name, "stocks": len(rs), "ret_1d": _avg(d1), "ret_1w": _avg(w1), "ret_1m": _avg([r.get("ret_1m") for r in rs]),
               "ret_3m": _avg([r.get("ret_3m") for r in rs]), "ret_6m": _avg([r.get("ret_6m") for r in rs]),
               "ret_1y": _avg([r.get("ret_1y") for r in rs]), "above_50": _share(sum(a50), len(a50)),
               "above_200": _share(sum(a200), len(a200)), "rs": _avg([r.get("rs") for r in rs]),
               "quadrant": (quad.get(name) or {}).get("quadrant")}
        row["vs_1m"] = row["ret_1m"] - bret["1m"] if _num(row["ret_1m"]) and _num(bret["1m"]) else None
        out.append(row)
    out.sort(key=lambda x: (x["ret_1m"] is None, -(x["ret_1m"] or 0)))
    return {"stocks": len(group), "benchmark": "Nifty 500", "benchmark_returns": bret, "sectors": out}


def rrg(timeframe: str = "weekly", benchmark: str = "nifty50", trail: int = 8) -> dict:
    """Sector rotation graph data: each sector's current quadrant, RS-Ratio and RS-Momentum, and its recent path."""
    rows = scan._load_all()
    quad = rrg_quadrants(rows, timeframe, benchmark, trail=trail) if rows else {}
    return {"timeframe": timeframe, "benchmark": benchmark, "trail": trail,
            "sectors": [{"name": k, **v} for k, v in sorted(quad.items())],
            "available": bool(quad)}


def industries(weighting: str = "equal") -> dict:
    """Each Screener industry (3rd level of its classification): 1W / 1M / 3M performance (equal- or market-cap-weighted), the rank of each,
    stock count, group market cap and the daily rotation quadrant against the Nifty 50. Stocks without a classification are left out."""
    from . import market_lists
    rows = scan._load_all()
    if not rows:
        return {"industries": []}
    market_lists.annotate(rows)
    _, group = _latest_rows(rows)
    quad = rrg_quadrants(rows, "daily", "nifty50", group="industry") if scan.benchmarks().get("nifty50") else {}
    by: dict = {}
    for r in group:
        if r.get("industry"):
            by.setdefault(r["industry"], []).append(r)
    out = []
    for name, rs in by.items():
        def wavg(vals):
            pairs = [(v, r.get("market_cap_cr")) for v, r in vals if _num(v)]
            if not pairs:
                return None
            if weighting == "cap":
                tot = sum(c for _, c in pairs if _num(c))
                return sum(v * c for v, c in pairs if _num(c)) / tot if tot else None
            return sum(v for v, _ in pairs) / len(pairs)
        w1 = [(_change(r.get("closes") or [], 5), r) for r in rs]
        out.append({"name": name, "stocks": len(rs), "ret_1w": wavg(w1), "ret_1m": wavg([(r.get("ret_1m"), r) for r in rs]),
                    "ret_3m": wavg([(r.get("ret_3m"), r) for r in rs]), "market_cap_cr": sum(r["market_cap_cr"] for r in rs if _num(r.get("market_cap_cr"))) or None,
                    "sector": rs[0].get("sector_cls"), "quadrant": (quad.get(name) or {}).get("quadrant")})
    for k in ("ret_1w", "ret_1m", "ret_3m"):
        order = sorted((x for x in out if x[k] is not None), key=lambda x: -x[k])
        for n, x in enumerate(order):
            x["rank_" + k[4:]] = n + 1
    out.sort(key=lambda x: (x["ret_1m"] is None, -(x["ret_1m"] or 0)))
    return {"stocks": len(group), "weighting": weighting, "industries": out}
