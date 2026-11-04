"""Forecast: one complete, decisive read of a stock from every layer we have.

  outlook   up / flat / down odds for the rest of the session (or the next one), the next 5 and the next 20 sessions, from the
            stock's OWN history: its past days in the same trend state (above/below its 50- and 200-day averages, RSI zone)
  plan      one trade plan (entry, stop, targets) - or "No trade" with the numbers that say so
  replay    the Time Machine: 10,000 simulated continuations drawn from the stock's own bars, and the same rule run on every
            past session; both measured on the plan above
  evidence  trend, relative strength, quality, liquidity, segment - each with a plain good / bad / neutral tone

Everything is arithmetic on real bars; nothing is invented. Where the history is too short the answer says "no call" - never a
number made up to fill the space. No LLM is involved."""
from __future__ import annotations

import datetime as _dt
import statistics
from collections import defaultdict

import numpy as np

from . import engine
from .plan import plan_for

SIMS = 10_000
SEED = 19
MIN_HISTORY = 250           # daily bars needed before a daily-horizon call is made
MIN_STATE_SAMPLES = 30      # past days in the same state needed to use the state; else the stock's whole history
STRONG, MODERATE, EVEN = 0.25, 0.12, 0.03     # lead of the likelier side over the other (as a share): strong / moderate / slight; under EVEN it is even
HORIZONS = (("session", None), ("week", 5), ("month", 20))
SLOTS = 75                  # 5-minute bars in a session


def _sessions(bars: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for b in bars:
        m = engine._mins(b["time"])
        if engine.OPEN_MIN <= m < engine.CLOSE_MIN:
            by[engine._ist(b["time"]).strftime("%Y-%m-%d")].append(b)
    return {d: sorted(v, key=lambda x: x["time"]) for d, v in by.items()}


def _slot(t: int) -> int:
    return (engine._mins(t) - engine.OPEN_MIN) // 5


# ------------------------------------------------------------------ daily conditional outlook
def _rsi_zone(v):
    return None if v is None else (0 if v < 40 else 1 if v < 60 else 2)


def _states(daily: list[dict]):
    closes = [b["close"] for b in daily]
    r = engine.rsi(closes)
    out, cum = [], [0.0]
    for c in closes:
        cum.append(cum[-1] + c)
    for i, c in enumerate(closes):
        if i < 199:
            out.append(None)
            continue
        s50 = (cum[i + 1] - cum[i - 49]) / 50
        s200 = (cum[i + 1] - cum[i - 199]) / 200
        z = _rsi_zone(r[i])
        out.append(None if z is None else (c > s50, c > s200, z))
    return closes, out


def lean(up: float, down: float) -> dict:
    """The verdict: the likelier side, and how strongly (strong / moderate / slight by the gap between the two)."""
    gap = abs(up - down)
    if gap < EVEN:
        return {"call": "even", "conviction": None}
    return {"call": "up" if up > down else "down",
            "conviction": "strong" if gap >= STRONG else "moderate" if gap >= MODERATE else "slight"}


def horizon_outlook(daily: list[dict], h: int) -> dict:
    """Odds that the close h sessions ahead is clearly up / flat / clearly down, from this stock's own past days in the same
    state. 'Clearly' is a move of more than a quarter of the typical h-session swing."""
    if len(daily) < MIN_HISTORY:
        return {"call": None, "reason": f"Only {len(daily)} sessions of history; at least {MIN_HISTORY} are needed."}
    closes, states = _states(daily)
    n = len(closes)
    fwd = {i: closes[i + h] / closes[i] - 1.0 for i in range(n - h) if closes[i] > 0}
    allr = list(fwd.values())
    if len(allr) < 60:
        return {"call": None, "reason": "Not enough past days to measure."}
    band = 0.25 * statistics.pstdev(allr)
    today = states[-1]
    same = [fwd[i] for i in fwd if states[i] is not None and states[i] == today] if today is not None else []
    use, basis = (same, "state") if len(same) >= MIN_STATE_SAMPLES else (allr, "all")

    def pct(a, q):
        return float(np.percentile(a, q)) * 100.0
    up = sum(1 for x in use if x > band) / len(use)
    down = sum(1 for x in use if x < -band) / len(use)
    return {**lean(up, down), "up": round(up * 100), "flat": round((1 - up - down) * 100), "down": round(down * 100),
            "p10": round(pct(use, 10), 1), "median": round(pct(use, 50), 1), "p90": round(pct(use, 90), 1),
            "samples": len(use), "basis": basis, "flat_band_pct": round(band * 100, 2)}


# ------------------------------------------------------------------ the Time Machine
def _bar_ratios(bars: list[dict]) -> list[tuple[int, tuple[float, float, float]]]:
    """(slot, (high, low, close) as multiples of the previous bar's close) for the bars of one session."""
    out = []
    for prev, b in zip(bars, bars[1:]):
        if prev["close"] > 0:
            out.append((_slot(b["time"]), (b["high"] / prev["close"], b["low"] / prev["close"], b["close"] / prev["close"])))
    return out


def intraday_steps(sessions: dict[str, list[dict]], exclude: str | None, first_slot: int) -> list[np.ndarray]:
    """For each remaining slot, the stock's own (high, low, close) ratios from past sessions at that time of day."""
    per: dict[int, list] = defaultdict(list)
    for d, bars in sessions.items():
        if d == exclude or len(bars) < 70:
            continue
        for s, r in _bar_ratios(bars):
            per[s].append(r)
    steps = []
    for s in range(first_slot, SLOTS):
        a = list(per.get(s) or [])
        for off in (1, -1, 2, -2):                     # a slot missing in many sessions borrows its neighbours' moves
            if len(a) >= 15:
                break
            a += per.get(s + off) or []
        if len(a) < 15:
            return []
        steps.append(np.array(a))
    return steps


def daily_steps(daily: list[dict], n: int) -> list[np.ndarray]:
    w = daily[-501:]
    a = np.array([(b["high"] / p["close"], b["low"] / p["close"], b["close"] / p["close"])
                  for p, b in zip(w, w[1:]) if p["close"] > 0])
    return [a] * n if len(a) >= 100 else []


def simulate(side: str, entry: float, stop: float, target: float, p0: float, steps: list[np.ndarray], n: int = SIMS, seed: int = SEED) -> dict | None:
    """Continue the price n times, bar by bar, from the stock's own (high, low, close) moves. A trade starts when the entry
    price is touched; after that the first of target / stop touched ends it. A bar that touches both counts as the stop."""
    if not steps or p0 <= 0:
        return None
    rng = np.random.default_rng(seed)
    long = side == "long"
    price = np.full(n, p0)
    entered = np.zeros(n, bool)
    state = np.zeros(n, np.int8)               # 0 running, 1 target, 2 stop
    for arr in steps:
        k = rng.integers(0, len(arr), n)
        hi, lo, cl = price * arr[k, 0], price * arr[k, 1], price * arr[k, 2]
        live = entered & (state == 0)
        hit_stop = live & ((lo <= stop) if long else (hi >= stop))
        hit_tgt = live & ((hi >= target) if long else (lo <= target)) & ~hit_stop
        state[hit_stop] = 2
        state[hit_tgt] = 1
        new = ~entered & ((hi >= entry) if long else (lo <= entry))
        entered |= new
        price = cl
    e = int(entered.sum())
    if e < 100:
        return {"enters": round(e / n * 100), "target": None, "stop": None, "open": None, "paths": n}
    return {"enters": round(e / n * 100), "target": round(float((state[entered] == 1).mean()) * 100),
            "stop": round(float((state[entered] == 2).mean()) * 100),
            "open": round(float((state[entered] == 0).mean()) * 100), "paths": n}


def _walk(bars: list[dict], i: int, side: str, stop: float, target: float, high="high", low="low") -> str:
    for b in bars[i + 1:]:
        if side == "long":
            if b[low] <= stop:
                return "stop"
            if b[high] >= target:
                return "target"
        else:
            if b[high] >= stop:
                return "stop"
            if b[low] <= target:
                return "target"
    return "open"


def replay_orb(sessions: dict[str, list[dict]], exclude: str | None, side: str | None) -> dict:
    """The opening-range rule on every past session: how often the trade hit its target, its stop, or neither by the close."""
    c = {"target": 0, "stop": 0, "open": 0}
    days = 0
    for d, bars in sorted(sessions.items()):
        if d == exclude or len(bars) < 70:
            continue
        o = engine.orb(bars, None, d)
        if o["state"] not in ("triggered", "failed"):
            continue
        sd = "long" if o["direction"] == "bullish" else "short"
        if side and sd != side:
            continue
        plan = next(iter(plan_for({**o, "state": "triggered"}, [], None) or []), None)
        if not plan:
            continue
        i = next((k for k, b in enumerate(bars) if engine._hhmm(b["time"]) == o["trigger_time"]), None)
        if i is None:
            continue
        tgt = plan["targets"][0]["price"]
        c[_walk(bars, i, sd, plan["stop"], tgt)] += 1
        days += 1
    return {"sessions": len(sessions) - (1 if exclude in sessions else 0), "trades": days, **c}


def replay_daily(daily: list[dict], kind: str) -> dict | None:
    """Past occurrences of a daily setup and what the stock did over the next 10 sessions."""
    closes = [b["close"] for b in daily]
    rets = []
    if kind == "resistance":
        from patterns.features import resistance_trades
        rets = [t[5] for t in resistance_trades(daily) if t[5] is not None]
    elif kind == "oversold":
        r = engine.rsi(closes)
        last = -99
        for i in range(30, len(closes) - 10):
            window = [x for x in r[i - 3:i] if x is not None]
            if window and min(window) < 30 and closes[i] > daily[i - 1]["high"] and i - last > 10:
                rets.append((closes[i + 10] / closes[i] - 1.0) * 100.0)
                last = i
    if len(rets) < 5:
        return {"n": len(rets), "win": None, "median": None, "avg": None, "horizon": 10}
    return {"n": len(rets), "win": round(sum(1 for x in rets if x > 0) / len(rets) * 100), "median": round(statistics.median(rets), 1),
            "avg": round(sum(rets) / len(rets), 1), "horizon": 10}


# ------------------------------------------------------------------ evidence
def _tone(v, good, bad, higher_better=True):
    if v is None:
        return None
    if higher_better:
        return "good" if v >= good else "bad" if v <= bad else None
    return "good" if v <= good else "bad" if v >= bad else None


SEGMENT = {"large": "Large cap", "mid": "Mid cap", "small": "Small cap", "micro": "Micro cap"}


def evidence(daily: list[dict], row: dict | None, peers: list[dict], quarters: dict | None = None) -> tuple[list[dict], dict]:
    ev: list[dict] = []
    closes = [b["close"] for b in daily]
    if len(closes) >= 200:
        s50, s200 = sum(closes[-50:]) / 50, sum(closes[-200:]) / 200
        px = closes[-1]
        ev.append({"label": "Price vs 50-day average", "value": f"{(px / s50 - 1) * 100:+.1f}%", "tone": "good" if px > s50 else "bad"})
        ev.append({"label": "Price vs 200-day average", "value": f"{(px / s200 - 1) * 100:+.1f}%", "tone": "good" if px > s200 else "bad"})
    r = engine.rsi(closes)
    if r and r[-1] is not None:
        ev.append({"label": "RSI (14)", "value": f"{r[-1]:.0f}", "tone": "bad" if r[-1] < 30 else None})
    liq = {"turnover_cr": None, "max_position_inr": None}
    if row:
        seg = SEGMENT.get(row.get("index") or "", "Not in the large / mid / small / micro lists")
        ev.append({"label": "Segment", "value": seg, "tone": None})
        ev.append({"label": "Sector", "value": row.get("sector") or "—", "tone": None})
        if row.get("rs") is not None:
            ev.append({"label": "Relative strength (1–99)", "value": str(row["rs"]), "tone": _tone(row["rs"], 70, 30)})
        sec_pe = [p["pe"] for p in peers if p.get("pe")]
        pe = row.get("pe")
        if pe is not None:
            med = statistics.median(sec_pe) if len(sec_pe) >= 5 else None
            ev.append({"label": "P/E" + (f" (sector median {med:.1f})" if med else ""), "value": f"{pe:.1f}",
                       "tone": None if not med else "good" if pe < 0.8 * med else "bad" if pe > 1.5 * med else None})
        if row.get("eps_growth") is not None:
            ev.append({"label": "EPS growth (annual CAGR)", "value": f"{row['eps_growth']:+.1f}%", "tone": _tone(row["eps_growth"], 15, 0)})
        if row.get("debt_equity") is not None:
            ev.append({"label": "Debt / equity", "value": f"{row['debt_equity']:.2f}", "tone": _tone(row["debt_equity"], 0.5, 1.5, False)})
        if row.get("promoter") is not None:
            ev.append({"label": "Promoter holding", "value": f"{row['promoter']:.1f}%", "tone": _tone(row["promoter"], 50, 25)})
        t = row.get("turnover_30d_cr")
        if t:
            liq = {"turnover_cr": round(t, 2), "max_position_inr": round(t * 1e7 * 0.02)}
            ev.append({"label": "Average daily turnover", "value": f"₹{t:,.1f} Cr", "tone": "bad" if t < 1 else None})
    ev += quarter_rows(quarters)
    return ev, liq


def quarter_rows(quarters: dict | None) -> list[dict]:
    """The latest reported quarter against the same quarter a year earlier (Screener's quarterly results, oldest first).
    A comparison whose base is not positive is left out - a % change from a loss is not a meaningful number."""
    if not quarters:
        return []
    keys = sorted(k for k in quarters if isinstance(quarters[k], dict))
    if len(keys) < 5:
        return []
    cur, base = quarters[keys[-1]], quarters[keys[-5]]
    out = []
    for label, field in (("Latest quarter sales vs a year ago", "Total Revenue"), ("Latest quarter net profit vs a year ago", "Net Income")):
        a, b = cur.get(field), base.get(field)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > 0:
            g = (a / b - 1.0) * 100.0
            out.append({"label": label, "value": f"{g:+.1f}%", "tone": "good" if g >= 10 else "bad" if g < 0 else None})
    return out


# ------------------------------------------------------------------ the whole read
def _open_now(bars: list[dict], day: str | None) -> bool:
    if not bars or not day:
        return False
    now = _dt.datetime.now(engine.IST)
    last = engine._ist(bars[-1]["time"])
    return now.strftime("%Y-%m-%d") == day and (now - last).total_seconds() <= 15 * 60 and engine._mins(bars[-1]["time"]) < engine.CLOSE_MIN - 5


def _tp(plan: dict) -> float:
    """Price of the plan's first target."""
    return next(t["price"] for t in plan["targets"] if t["r"] == plan["first_target_r"])


def _edge(odds: dict | None, r: float) -> tuple[bool, str]:
    """A plan is only worth taking when, over the simulated paths, what the target pays beats what the stop costs:
    target% x R - stop% must be at least 0.05 of the risk."""
    if odds is None or odds.get("target") is None:
        return False, "Too few simulated paths reach the entry to measure the odds."
    if (odds["target"] * r - odds["stop"]) / 100.0 < 0.05:
        return False, f"The simulated target (first {odds['target']}%, paying {r:g}× the risk) does not clearly beat the stop (first {odds['stop']}%)."
    return True, ""


def _plan_view(plan: dict, state: str) -> dict:
    long = plan["side"] == "long"
    kind = "at" if state == "triggered" else ("above" if long else "below")
    return {**plan, "action": ("Buy" if long else "Sell short") + f" {kind}", "entry_kind": kind}


def build(symbol: str, intraday: list[dict] | None, daily: list[dict] | None, row: dict | None = None, peers: list[dict] | None = None, quarters: dict | None = None) -> dict:
    daily = daily or []
    intraday = intraday or []
    sessions = _sessions(intraday)
    day, bars = engine.session_bars(intraday, None)
    open_now = _open_now(bars, day)
    base = engine.analyse(symbol, intraday, daily, None)
    adr = base["adr20_pct"]
    price = (bars[-1]["close"] if bars else None) or (daily[-1]["close"] if daily else None)
    ev, liq = evidence(daily, row, peers or [], quarters)
    out = {"symbol": symbol, "price": round(price, 2) if price else None, "market_open": open_now, "session": day,
           "adr20_pct": adr, "evidence": ev, "liquidity": liq, "segment": SEGMENT.get((row or {}).get("index") or "")}

    # ---------------- outlook
    hs = []
    for hid, h in HORIZONS:
        if hid == "session":
            hs.append({"id": "session", "label": "Rest of today" if open_now else "Next session", **_session_outlook(daily, sessions, day, bars, open_now)})
        else:
            hs.append({"id": hid, "label": f"Next {h} sessions", "sessions": h, **horizon_outlook(daily, h)})
    out["outlook"] = hs

    # ---------------- trend state decides which side a waiting breakout is traded on
    trend = None
    if len(daily) >= 200:
        cl = [b["close"] for b in daily]
        a50, a200 = cl[-1] > sum(cl[-50:]) / 50, cl[-1] > sum(cl[-200:]) / 200
        trend = "long" if (a50 and a200) else "short" if (not a50 and not a200) else None

    # ---------------- intraday plan (only while the session is live and the 15-minute range exists)
    orb = next(s for s in base["setups"] if s["id"] == "orb")
    out["today"] = _today_block(orb, open_now, bars, sessions, day, daily, adr, trend, hs[0].get("call"), hs[1].get("call"))

    # ---------------- swing plan from the daily setups
    out["swing"] = _swing_block(base["setups"], daily, adr, hs[1], hs[2], trend)

    # ---------------- price ranges for each horizon, key levels, and a reference stop for sizing
    if price:
        for h in hs:
            if h.get("p10") is not None:
                h["price_low"], h["price_mid"], h["price_high"] = (round(price * (1 + h[k] / 100), 2) for k in ("p10", "median", "p90"))
    out["levels"] = key_levels(daily, price, hs[0])
    ref = _trend_plan(daily, len(daily) - 1, adr) if daily else None
    out["sizing"] = ({"entry": ref["entry"], "stop": ref["stop"], "risk_per_share": ref["risk_per_share"], "basis": ref["stop_basis"]} if ref else None)
    return out


def key_levels(daily: list[dict], price: float | None, session: dict) -> list[dict]:
    """The prices a trader watches: where the stock is expected to finish, the last session's range, the nearest swing high above
    and swing low below, the 52-week extremes. Resistance is shown red, support green."""
    rows: list[dict] = []
    if not daily or not price:
        return rows
    if session.get("price_low") is not None:
        rows.append({"label": session["label"] + ", likely range", "value": f"₹{session['price_low']:,.2f} to ₹{session['price_high']:,.2f}", "tone": None})
    last = daily[-1]
    rows.append({"label": "Last session's high and low", "value": f"₹{last['high']:,.2f} / ₹{last['low']:,.2f}", "tone": None})
    w = daily[-120:]
    hi = [b["high"] for b in w]
    pivots_hi = [hi[i] for i in range(3, len(w) - 3) if hi[i] == max(hi[i - 3:i + 4]) and hi[i] > price]
    lo = [b["low"] for b in w]
    pivots_lo = [lo[i] for i in range(3, len(w) - 3) if lo[i] == min(lo[i - 3:i + 4]) and lo[i] < price]
    if pivots_hi:
        r = min(pivots_hi)
        rows.append({"label": "Nearest resistance (recent swing high)", "value": f"₹{r:,.2f} ({(r / price - 1) * 100:+.1f}%)", "tone": "bad"})
    if pivots_lo:
        sup = max(pivots_lo)
        rows.append({"label": "Nearest support (recent swing low)", "value": f"₹{sup:,.2f} ({(sup / price - 1) * 100:+.1f}%)", "tone": "good"})
    year = daily[-252:]
    if len(year) >= 200:
        rows.append({"label": "52-week high / low", "value": f"₹{max(b['high'] for b in year):,.2f} / ₹{min(b['low'] for b in year):,.2f}", "tone": None})
    return rows


def _session_outlook(daily, sessions, day, bars, open_now) -> dict:
    """Odds for the session close vs the current price (live) or vs the last close (market shut), from the stock's own sessions."""
    if len(daily) < MIN_HISTORY:
        return {"call": None, "reason": "Not enough history."}
    h = horizon_outlook(daily, 1)
    if open_now and bars:
        first = len(bars)
        steps = intraday_steps(sessions, day, first)
        if steps:
            p0 = bars[-1]["close"]
            rng = np.random.default_rng(SEED)
            price = np.full(SIMS, p0)
            for arr in steps:
                price = price * arr[rng.integers(0, len(arr), SIMS), 2]
            band = h.get("flat_band_pct", 0) / 100
            up = float((price > p0 * (1 + band)).mean())
            down = float((price < p0 * (1 - band)).mean())
            r = (price / p0 - 1) * 100
            return {**lean(up, down), "up": round(up * 100), "flat": round((1 - up - down) * 100), "down": round(down * 100),
                    "p10": round(float(np.percentile(r, 10)), 1), "median": round(float(np.percentile(r, 50)), 1),
                    "p90": round(float(np.percentile(r, 90)), 1), "samples": len(sessions) - 1, "basis": "sessions",
                    "flat_band_pct": h.get("flat_band_pct")}
    return h


def _side_for(calls: list, trend: str | None, daily: list[dict]) -> str:
    """The side to trade: the first horizon that leans one way decides; if all are level, the trend; if there is none, the 200-day average."""
    for c in calls:
        if c == "up":
            return "long"
        if c == "down":
            return "short"
    if trend:
        return trend
    cl = [b["close"] for b in daily[-200:]]
    return "long" if cl and cl[-1] >= sum(cl) / len(cl) else "short"


def _edge_view(odds: dict | None, r: float, rep: dict | None = None) -> dict | None:
    """What the plan is worth per unit of risk: target% x reward - stop%, from the simulation and (when there are at least 10 past
    trades) from the replay. The lower of the two is reported, so a plan is never flattered by its better number."""
    vals = []
    if odds and odds.get("target") is not None:
        vals.append((odds["target"] * r - odds["stop"]) / 100.0)
    if rep:
        n = rep.get("trades") or rep.get("n") or 0
        if n >= 10 and rep.get("target") is not None and rep.get("stop") is not None:
            vals.append((rep["target"] * r - rep["stop"]) / n)
    if not vals:
        return None
    v = min(vals)
    return {"value": round(v, 2), "label": "favourable" if v >= 0.05 else "against" if v <= -0.05 else "even"}


def _session_plan(entry: float, adr: float, side: str) -> dict | None:
    """A same-session plan from the stock's own typical range: stop half a typical day away, targets at 1x and 2x that risk."""
    risk = entry * 0.5 * adr / 100.0
    if risk <= 0:
        return None
    sign = 1.0 if side == "long" else -1.0
    return {"side": side, "entry": round(entry, 2), "stop": round(entry - sign * risk, 2), "risk_per_share": round(risk, 2),
            "risk_pct": round(risk / entry * 100, 2),
            "targets": [{"r": 1.0, "price": round(entry + sign * risk, 2)}, {"r": 2.0, "price": round(entry + sign * 2 * risk, 2)}],
            "first_target_r": 1.0, "stop_basis": "half of the stock's typical daily range",
            "exit_rule": "Flat by 15:25 IST either way.", "warnings": []}


def _one_bar(b: dict, side: str, stop: float, target: float) -> str:
    if side == "long":
        return "stop" if b["low"] <= stop else "target" if b["high"] >= target else "open"
    return "stop" if b["high"] >= stop else "target" if b["low"] <= target else "open"


def replay_session(daily: list[dict], side: str, adr_fn) -> dict:
    """The same plan on every past day in today's trend state: bought at the previous close, did the day reach the target, the stop, or neither."""
    closes, states = _states(daily)
    today = states[-1]
    idx = [i for i in range(200, len(daily)) if states[i] is not None and (today is None or states[i] == today)]
    if len(idx) < MIN_STATE_SAMPLES:
        idx = list(range(200, len(daily)))
    c = {"target": 0, "stop": 0, "open": 0}
    n = 0
    for i in idx:
        a = adr_fn(daily[:i])
        p = _session_plan(daily[i - 1]["close"], a, side) if a else None
        if not p:
            continue
        c[_one_bar(daily[i], side, p["stop"], p["targets"][0]["price"])] += 1
        n += 1
    return {"sessions": n, "trades": n, "target": c["target"], "stop": c["stop"], "open": c["open"], "session_rule": True}


def _today_block(orb, open_now, bars, sessions, day, daily, adr, trend, session_call, week_call) -> dict:
    blk = {"setup": {k: orb.get(k) for k in ("state", "direction", "range_high", "range_low", "range_pct", "range_vs_adr",
                                               "trigger_price", "trigger_time", "trigger_volume_vs_avg", "last_price", "last_time", "reason")}}
    note = None
    if open_now and orb["state"] in ("waiting", "triggered"):
        plans = plan_for(orb, daily, adr) or []
        side = ("long" if orb["direction"] == "bullish" else "short") if orb["state"] == "triggered" else _side_for([session_call, week_call], trend, daily)
        plan = next((p for p in plans if p["side"] == side), None)
        px = bars[-1]["close"]
        if plan and not (orb["state"] == "triggered" and abs(px - plan["entry"]) > 0.5 * plan["risk_per_share"]):
            odds = simulate(side, plan["entry"], plan["stop"], _tp(plan), px, intraday_steps(sessions, day, len(bars)))
            rep = replay_orb(sessions, day, side)
            ok, why = _edge(odds, plan["first_target_r"])
            if ok and not (rep["trades"] >= 10 and rep["target"] * plan["first_target_r"] <= rep["stop"]):
                blk.update({"odds": odds, "replay": rep, "plan": _plan_view(plan, orb["state"]), "basis": "orb",
                            "edge": _edge_view(odds, plan["first_target_r"], rep)})
                blk["decision"] = {"action": blk["plan"]["action"], "reason": None}
                return blk
            note = "The opening-range breakout does not have the odds on its side, so this plan uses the stock's typical daily range."
        else:
            note = "The opening-range level is too far behind the price, so this plan uses the stock's typical daily range."
    elif open_now and orb["state"] == "failed":
        note = "The opening-range breakout closed back through its level, so this plan uses the stock's typical daily range."
    elif open_now and orb["state"] == "no_breakout":
        note = "Price stayed inside the opening range, so this plan uses the stock's typical daily range."
    elif open_now:
        note = "The opening range is still forming (09:15 to 09:30); this plan uses the stock's typical daily range."
    else:
        note = "The market is closed; this is the plan for the next session, from the last close."
    if len(daily) < MIN_HISTORY or not adr:
        blk["decision"] = {"action": "No trade", "reason": "There is not enough price history to set a stop and target for this stock."}
        return blk
    side = _side_for([session_call, week_call], trend, daily)
    px = bars[-1]["close"] if open_now and bars else daily[-1]["close"]
    plan = _session_plan(px, adr, side)
    steps = intraday_steps(sessions, day, len(bars)) if open_now and bars else daily_steps(daily, 1)
    odds = simulate(side, plan["entry"], plan["stop"], _tp(plan), px, steps)
    rep = replay_session(daily, side, engine.adr_pct)
    blk.update({"plan": _plan_view(plan, "triggered"), "odds": odds, "replay": rep,
                "basis": "range", "note": note, "edge": _edge_view(odds, plan["first_target_r"], rep)})
    blk["decision"] = {"action": blk["plan"]["action"], "reason": None}
    return blk


def _trend_plan(daily: list[dict], i: int, adr: float | None, target_r: float = 2.0, side: str = "long") -> dict | None:
    """Trade at the close of bar i: stop beyond the extreme of the last 5 sessions, kept between half a and one-and-a-half
    typical daily ranges so it is neither inside the noise nor reckless; first target at target_r times the risk."""
    if i < 5 or not adr:
        return None
    entry = daily[i]["close"]
    sign = 1.0 if side == "long" else -1.0
    swing = min(b["low"] for b in daily[i - 4:i + 1]) if side == "long" else max(b["high"] for b in daily[i - 4:i + 1])
    near, far = entry * (1 - sign * 0.5 * adr / 100), entry * (1 - sign * 1.5 * adr / 100)
    stop = min(max(swing, far), near) if side == "long" else max(min(swing, far), near)
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return {"side": side, "entry": round(entry, 2), "stop": round(stop, 2), "risk_per_share": round(risk, 2),
            "risk_pct": round(risk / entry * 100, 2),
            "targets": [{"r": 1.0, "price": round(entry + sign * risk, 2)}, {"r": target_r, "price": round(entry + sign * risk * target_r, 2)}],
            "first_target_r": target_r,
            "stop_basis": ("the lowest low" if side == "long" else "the highest high") + " of the last 5 sessions, kept within the stock's normal daily range",
            "exit_rule": "Out after 10 sessions if neither level is hit.", "warnings": []}


def replay_trend(daily: list[dict], adr_fn, side: str = "long") -> dict:
    """The same trend rule on this stock's past days in today's trend state: target, stop or neither in 10 sessions."""
    closes, states = _states(daily)
    today = states[-1]
    idx = [i for i in range(200, len(daily) - 10) if states[i] is not None and (today is None or states[i] == today)]
    if len(idx) < MIN_STATE_SAMPLES:
        idx = list(range(200, len(daily) - 10))
    c = {"target": 0, "stop": 0, "open": 0}
    n = 0
    for i in idx[::2]:                                   # every second day: neighbouring days overlap and would be counted twice
        p = _trend_plan(daily, i, adr_fn(daily[: i + 1]), side=side)
        if not p:
            continue
        r = _walk(daily, i, side, p["stop"], p["targets"][-1]["price"])
        c[r if r in c else "open"] += 1
        n += 1
    return {"n": n, "target": c["target"], "stop": c["stop"], "open": c["open"], "horizon": 10, "trend_rule": True}


def _swing_block(setups, daily, adr, week, month, trend) -> dict:
    blk: dict = {}
    if len(daily) < MIN_HISTORY or not adr:
        blk["decision"] = {"action": "No trade", "reason": "There is not enough price history to set a stop and target for this stock."}
        return blk
    side = _side_for([week.get("call"), month.get("call")], trend, daily)
    plan, state = None, "triggered"
    setup = {"id": "trend", "label": "Trend continuation" if side == "long" else "Trend continuation (short)"}
    if side == "long":
        cand = [s for s in setups if s["id"] in ("resistance", "oversold") and s["state"] in ("waiting", "triggered")]
        if cand:
            plan = next(iter(plan_for(cand[0], daily, adr) or []), None)
            if plan:
                setup = {k: cand[0].get(k) for k in ("id", "label", "state", "level", "touches", "distance_pct", "rsi", "reason")}
                state = cand[0]["state"]
    if plan:
        rep = replay_daily(daily, setup["id"])
    else:
        plan = _trend_plan(daily, len(daily) - 1, adr, side=side)
        if not plan:
            blk["decision"] = {"action": "No trade", "reason": "A stop and target could not be set from the recent range."}
            return blk
        rep = replay_trend(daily, engine.adr_pct, side)
    odds = simulate(side, plan["entry"], plan["stop"], _tp(plan), daily[-1]["close"], daily_steps(daily, 10))
    blk.update({"setup": setup, "odds": odds, "replay": rep, "plan": _plan_view(plan, state), "edge": _edge_view(odds, plan["first_target_r"], rep),
                "note": "A short held over several days needs futures." if side == "short" else None})
    blk["decision"] = {"action": blk["plan"]["action"], "reason": None}
    return blk
