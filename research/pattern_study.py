"""Do the chart patterns the agent confirms actually lead to anything? An event study on the stored pattern history.

For every daily pattern that was EVER confirmed in data/patterns/patterns.db (about 140,000, from December 2021 on, 757 stocks). The selection
is on the confirmation itself, never on what the pattern's status is today: a pattern that was confirmed and later invalidated (price came back through
its stop level) stays in. A first version of this study kept only patterns still "confirmed" today, which silently dropped every one that failed
afterwards and made the order-block and pocket-pivot results look far too good; this version does not.
  * entry: the OPEN of the first session after the confirmation bar (the signal is known only at that bar's close);
  * exit: the CLOSE of the h-th session held, for h = 1, 5, 10 and 20;
  * excess return: that return minus the return of the MEDIAN stock among all stocks entering on the same day (so a rising market, or a lucky month,
    is not credited to the pattern);
  * signed: bullish patterns count as they are, bearish patterns count with the sign flipped (a fall after a bearish pattern is a "win");
  * de-duplicated: one event per stock, pattern and direction in any 10 sessions (a pattern that keeps re-confirming is one idea);
  * cost: 0.25% of the position, charged to every event (brokerage, taxes and slippage on a round trip; an assumption, stated);
  * significance: events are grouped by the month they were confirmed (events in the same month share the market's mood and are not
    independent); the t-test is across those months. With 100+ combinations tested, p-values are corrected with Benjamini-Hochberg
    and only combinations that survive, in BOTH halves of the period, are called a real effect;
  * halves: confirmations before 2024-07-01 and from then on are reported separately, so a result that only exists in one half is visible.

Limits: only stocks listed today (survivorship flatters bullish returns, but the same-day all-stock baseline carries the same bias); the pattern
detectors have not been tuned (that is the point of the first run); prices adjusted by the provider; no position sizing or portfolio effects.

Run:  python -m research.pattern_study [--refresh-prices]
Writes data/research/pattern_study.json and prints a table."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "research")
PRICES = os.path.join(OUT, "daily_ohlc.pkl")
DB = os.path.join(ROOT, "data", "patterns", "patterns.db")
HORIZONS = (1, 5, 10, 20)
COST = 0.0025
COOLDOWN = 10
SPLIT = "2024-07-01"
IST = timezone(timedelta(hours=5, minutes=30))


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ prices
def load_prices(refresh: bool = False, since: str = "2021-06-01") -> dict:
    """{symbol: DataFrame(index = date string, columns open, close)} from the provider's adjusted daily history; cached on disk."""
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(PRICES) and not refresh:
        return pd.read_pickle(PRICES)
    from patterns import scan
    from tools.live_chart_yf import get_candles
    syms = sorted(scan._load_all())

    def one(s):
        cs = get_candles(s, interval="1d", period="max")
        if not cs:
            return s, None
        df = pd.DataFrame({"open": [c["open"] for c in cs], "close": [c["close"] for c in cs]}, index=[_day(c["time"]) for c in cs])
        df = df[~df.index.duplicated(keep="last")]
        return s, df[df.index >= since]

    out, t0 = {}, time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (s, df) in enumerate(pool.map(one, syms), 1):
            if df is not None and len(df) > 60:
                out[s] = df
            if i % 100 == 0:
                print(f"prices {i}/{len(syms)} {time.time() - t0:.0f}s", flush=True)
    pd.to_pickle(out, PRICES)
    return out


# ------------------------------------------------------------------ the study
def events() -> pd.DataFrame:
    con = sqlite3.connect(DB)
    q = ("select symbol, pattern, direction, confirmed_ts from pattern_occurrences "
         "where timeframe='1d' and confirmed_ts is not null and direction in ('bullish','bearish')")      # EVER confirmed, whatever happened after
    df = pd.read_sql_query(q, con)
    con.close()
    df["day"] = df["confirmed_ts"].map(_day)
    return df.drop_duplicates(["symbol", "pattern", "direction", "day"])


def forward_table(prices: dict) -> tuple[pd.DataFrame, dict]:
    """For every stock and entry day: the return of entering at the open and exiting at the close of the h-th session; plus the all-stock
    average of the same for each entry day."""
    cols = {}
    for h in HORIZONS:
        parts = {}
        for s, df in prices.items():
            o, c = df["open"].to_numpy(), df["close"].to_numpy()
            r = np.full(len(df), np.nan)
            if len(df) > h:
                r[: len(df) - h + 1] = c[h - 1:] / o[: len(df) - h + 1] - 1.0
            parts[s] = pd.Series(r, index=df.index)
        wide = pd.DataFrame(parts)
        cols[h] = wide
    # the MEDIAN stock of the day, not the mean: returns are skewed, so the mean sits above the typical stock and would make every pattern look weak
    mean = {h: cols[h].median(axis=1) for h in HORIZONS}
    return cols, mean


def run(refresh: bool = False, delay: int = 0) -> dict:
    """delay = extra sessions waited after the first session following the signal (0 = enter at the next open)."""
    prices = load_prices(refresh)
    ev = events()
    ev = ev[ev["symbol"].isin(prices)]
    wide, mkt = forward_table(prices)
    # the entry day is the session after the confirmation bar, taken from that stock's own calendar
    nxt, rows = {}, []
    for s, df in prices.items():
        idx = df.index
        step = 1 + delay
        nxt[s] = dict(zip(idx[:-step], idx[step:]))
    ev = ev.assign(entry=[nxt.get(s, {}).get(d) for s, d in zip(ev["symbol"], ev["day"])]).dropna(subset=["entry"])
    ev = ev.sort_values(["symbol", "pattern", "direction", "entry"])
    keep = []
    for _, g in ev.groupby(["symbol", "pattern", "direction"], sort=False):
        last = None
        for i, e in zip(g.index, g["entry"]):
            ed = datetime.strptime(e, "%Y-%m-%d")
            if last is None or (ed - last).days > COOLDOWN * 7 / 5:
                keep.append(i)
                last = ed
    ev = ev.loc[keep]
    ev["sign"] = np.where(ev["direction"] == "bullish", 1.0, -1.0)
    for h in HORIZONS:
        raw = np.array([wide[h][s].get(e, np.nan) if s in wide[h] else np.nan for s, e in zip(ev["symbol"], ev["entry"])], dtype=float)
        base = ev["entry"].map(mkt[h]).to_numpy(dtype=float)
        ev[f"x{h}"] = ev["sign"].to_numpy() * (raw - base) - COST          # signed excess return, after cost
        ev[f"r{h}"] = ev["sign"].to_numpy() * raw
    ev["month"] = ev["day"].str[:7]
    ev["half"] = np.where(ev["day"] < SPLIT, "first", "second")

    results = []
    for (pat, d), g in ev.groupby(["pattern", "direction"]):
        for h in HORIZONS:
            col = g[f"x{h}"].dropna()
            if len(col) < 30:
                continue
            row = {"pattern": pat, "direction": d, "horizon": h, "events": int(len(col)), "stocks": int(g.loc[col.index, "symbol"].nunique())}
            for tag, sub in (("all", g), ("first", g[g["half"] == "first"]), ("second", g[g["half"] == "second"])):
                v = sub[f"x{h}"].dropna()
                if len(v) < 20:
                    row[tag] = None
                    continue
                by_month = sub.loc[v.index].groupby("month")[f"x{h}"].mean()
                t, p = (stats.ttest_1samp(by_month, 0.0) if len(by_month) >= 6 else (np.nan, np.nan))
                row[tag] = {"events": int(len(v)), "months": int(len(by_month)), "mean_excess_pct": round(float(v.mean()) * 100, 2),
                            "median_excess_pct": round(float(v.median()) * 100, 2), "gross_excess_pct": round((float(v.mean()) + COST) * 100, 2), "win_pct": round(float((v > 0).mean()) * 100, 1),
                            "raw_signed_pct": round(float(sub.loc[v.index, f"r{h}"].mean()) * 100, 2),
                            "t": None if np.isnan(t) else round(float(t), 2), "p": None if np.isnan(p) else float(p)}
            results.append(row)
    # Benjamini-Hochberg over all combinations, on the full-period p-value
    ps = [(i, r["all"]["p"]) for i, r in enumerate(results) if r.get("all") and r["all"]["p"] is not None]
    ps.sort(key=lambda x: x[1])
    for (i, _), q in zip(ps, bh([p for _, p in ps])):
        results[i]["all"]["q"] = round(q, 4)
    for r in results:
        a, f, s = r.get("all"), r.get("first"), r.get("second")
        same_sign = bool(f and s and f["mean_excess_pct"] * s["mean_excess_pct"] > 0)
        r["real_effect"] = bool(a and a.get("q") is not None and a["q"] < 0.05 and a["mean_excess_pct"] > 0 and same_sign and f["mean_excess_pct"] > 0)
        r["reverse_effect"] = bool(a and a.get("q") is not None and a["q"] < 0.05 and a["mean_excess_pct"] < 0 and same_sign and f["mean_excess_pct"] < 0)
    out = {"made": datetime.now().isoformat(timespec="seconds"), "events_total": int(len(ev)), "stocks": int(ev["symbol"].nunique()),
           "period": [ev["day"].min(), ev["day"].max()], "split": SPLIT, "cost_pct": COST * 100, "cooldown_sessions": COOLDOWN,
           "tests": len(results), "results": results}
    os.makedirs(OUT, exist_ok=True)
    out["delay"] = delay
    with open(os.path.join(OUT, "pattern_study.json" if delay == 0 else f"pattern_study_delay{delay}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return out


def bh(sorted_p: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q) for p-values sorted ascending: q_k = min over j >= k of p_j * m / j, capped at 1."""
    m = len(sorted_p)
    qs = [min(1.0, p * m / rank) for rank, p in enumerate(sorted_p, 1)]
    for k in range(m - 2, -1, -1):                                   # the corrected value never exceeds a later one
        qs[k] = min(qs[k], qs[k + 1])
    return qs


def table(out: dict, horizon: int = 10) -> str:
    rows = [r for r in out["results"] if r["horizon"] == horizon and r.get("all")]
    rows.sort(key=lambda r: -r["all"]["mean_excess_pct"])
    lines = [f"{'pattern':27} {'dir':8} {'events':>7} {'excess%':>8} {'win%':>6} {'q':>6} {'1st half':>9} {'2nd half':>9}  verdict"]
    for r in rows:
        a, f, s = r["all"], r.get("first"), r.get("second")
        v = "REAL EFFECT" if r["real_effect"] else "REVERSE" if r["reverse_effect"] else ""
        lines.append(f"{r['pattern']:27} {r['direction']:8} {a['events']:7d} {a['mean_excess_pct']:8.2f} {a['win_pct']:6.1f} {a.get('q', float('nan')):6.3f} "
                     f"{(f or {}).get('mean_excess_pct', float('nan')):9.2f} {(s or {}).get('mean_excess_pct', float('nan')):9.2f}  {v}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-prices", action="store_true")
    ap.add_argument("--horizon", type=int, default=10)
    ap.add_argument("--delay", type=int, default=0)
    a = ap.parse_args()
    res = run(a.refresh_prices, a.delay)
    print(f"{res['events_total']:,} events, {res['stocks']} stocks, {res['period'][0]} to {res['period'][1]}, {res['tests']} tests, cost {res['cost_pct']}%")
    for h in HORIZONS:
        print(f"\n=== {h} sessions held ===")
        print(table(res, h))
