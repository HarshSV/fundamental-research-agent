"""Historical conditional outcomes of OBSERVED candlestick patterns (offline, reproducible, no look-ahead).

At every bar the detector sees only bars <= that bar; the outcome is the close h bars LATER inside the same
session (never across a session boundary, never an unverified session). Reported against the unconditional
base rate with Wilson intervals and split chronologically (earlier 70% of sessions vs later 30%) so a
pattern whose behaviour does not persist is visible. These describe observed patterns; they say nothing
about the probability that a model-implied future pattern forms.

  python -m forecast.pattern_stats --symbols RELIANCE TCS ... [--out data/forecast/pattern_stats.json]
"""
import argparse
import json
import math
import os

from . import candle_patterns as cp, config, store, timeutil

HORIZONS = config.HORIZONS
MIN_N = 200  # below this a pattern's statistics are not shown in the UI


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [(c - r) / d, (c + r) / d]


def session_bars(rows):
    """Group rows into sessions with ALL usable slots present and contiguous; others are dropped, not repaired."""
    by = {}
    for ts, o, h, l, c, v in rows:
        s = timeutil.slot_of(ts)
        if 0 <= s < config.USABLE_SLOTS:
            by.setdefault(timeutil.session_date(ts), {})[s] = {"time": ts, "open": o, "high": h, "low": l, "close": c}
    return {d: [m[i] for i in range(config.USABLE_SLOTS)] for d, m in sorted(by.items()) if len(m) == config.USABLE_SLOTS}


def collect(sessions, params=None):
    """-> list of (session_index, pattern, direction, {h: return}) and the unconditional {h: [up_flags]}."""
    obs, base = [], {h: [0, 0] for h in HORIZONS}
    for si, bars in enumerate(sessions):
        for i in range(len(bars)):
            for h in HORIZONS:
                if i + h < len(bars):
                    base[h][1] += 1
                    base[h][0] += bars[i + h]["close"] > bars[i]["close"]
            for d in cp.detect_at(bars, i, params):
                rets = {h: bars[i + h]["close"] / bars[i]["close"] - 1 for h in HORIZONS if i + h < len(bars)}
                obs.append((si, d["pattern"], d["direction"], rets))
    return obs, base


def summarize(obs, base, n_sessions, split=0.7):
    cut = int(n_sessions * split)
    out = {}
    for pat in cp.PATTERNS:
        direction = cp.PATTERNS[pat][0]
        rows = [o for o in obs if o[1] == pat]
        entry = {"direction": direction, "n": len(rows), "horizons": {}}
        for h in HORIZONS:
            rs = [(si, r[h]) for si, _, _, r in rows if h in r]
            n = len(rs)
            if n == 0:
                continue
            base_up = base[h][0] / base[h][1] if base[h][1] else None
            ups = sum(1 for _, r in rs if r > 0)
            hit = None
            if direction != "neutral":
                k = sum(1 for _, r in rs if (r > 0 if direction == "bullish" else r < 0))
                hit = {"rate": k / n, "ci95": wilson(k, n)}
            early = [r for si, r in rs if si < cut]
            late = [r for si, r in rs if si >= cut]
            entry["horizons"][str(h)] = {
                "n": n, "mean_return": sum(r for _, r in rs) / n, "p_up": ups / n, "p_up_ci95": wilson(ups, n),
                "base_p_up": base_up, "directional_hit": hit,
                "mean_return_early": sum(early) / len(early) if early else None, "n_early": len(early),
                "mean_return_late": sum(late) / len(late) if late else None, "n_late": len(late),
            }
        out[pat] = entry
    return out


def run(symbols, out_path=None, params=None):
    con = store.connect()
    sessions_all = []
    used = []
    for sym in symbols:
        s = session_bars(store.load_candles(con, sym))
        if s:
            used.append(sym)
            sessions_all.append(list(s.values()))
    # pooled across symbols; "session index" ordering is per symbol so early/late split is per-symbol chronological
    obs, base = [], {h: [0, 0] for h in HORIZONS}
    n_sess = 0
    for ss in sessions_all:
        o, b = collect(ss, params)
        obs.extend(o)
        for h in HORIZONS:
            base[h][0] += b[h][0]
            base[h][1] += b[h][1]
        n_sess = max(n_sess, len(ss))
    res = {"symbols": used, "horizons": list(HORIZONS), "min_n_for_display": MIN_N, "params": {**cp.DEFAULT_PARAMS, **(params or {})},
           "bars": "5m, first %d slots of fully present sessions; outcome = later close in the same session" % config.USABLE_SLOTS,
           "stats": summarize(obs, base, n_sess)}
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    return res


def load_stats(path=None):
    path = path or os.path.join(config.DATA_DIR, "pattern_stats.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def historical_for(pattern, stats):
    """Display payload for one OBSERVED pattern, or None when absent / too few observations."""
    e = (stats or {}).get("stats", {}).get(pattern)
    if not e or e["n"] < MIN_N:
        return None
    return {"n": e["n"], "horizons": e["horizons"], "symbols": len(stats["symbols"]), "kind": "observed_patterns_only"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--out", default=os.path.join(config.DATA_DIR, "pattern_stats.json"))
    a = ap.parse_args()
    r = run(a.symbols, a.out)
    for pat, e in r["stats"].items():
        h1 = e["horizons"].get("1", {})
        print(f"{pat:22s} n={e['n']:7d}  +1 mean={h1.get('mean_return')}  p_up={h1.get('p_up')} base={h1.get('base_p_up')}")
