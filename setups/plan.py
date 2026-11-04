"""Plan layer: for a setup, where to get in, where to be wrong, where to take profit - set BEFORE entering.

Every distance is tied to something on the chart (the opening range, a swing low, the resistance level) and judged against
the stock's own typical daily range (ADR), so a micro cap's 4% range and a large cap's 1% range are each treated by their own
yardstick. The plan is arithmetic on the setup, not a forecast: the odds of reaching the target come from the Time Machine.

A plan is None when the numbers it needs are not there - never a guess."""
from __future__ import annotations

PLAN_VERSION = 1
TARGET_R = {"orb": 1.0, "oversold": 1.5, "resistance": 2.0}      # reward / risk used for the first target
TIGHT = 0.30       # stop closer than 30% of the typical daily range is inside normal noise
WIDE = 1.50        # ... and wider than 150% of it risks more than a normal day's move
SESSION_END = "15:25"


def _r(v: float) -> float:
    return round(v, 2)


def _build(side: str, entry: float, stop: float, target_r: float, adr: float | None, how: str, exit_rule: str, conditional: bool) -> dict | None:
    risk = abs(entry - stop)
    if entry <= 0 or risk <= 0 or (side == "long" and stop >= entry) or (side == "short" and stop <= entry):
        return None
    sign = 1.0 if side == "long" else -1.0
    risk_pct = risk / entry * 100.0
    warnings = []
    if adr:
        if risk_pct < TIGHT * adr:
            warnings.append(f"The stop is only {risk_pct:.2f}% away, inside this stock's normal noise (typical daily range {adr:.2f}%): expect to be stopped out by chance.")
        elif risk_pct > WIDE * adr:
            warnings.append(f"The stop is {risk_pct:.2f}% away, more than a typical day's range ({adr:.2f}%): the risk per share is large.")
    return {
        "version": PLAN_VERSION, "side": side, "conditional": conditional,
        "entry": _r(entry), "stop": _r(stop), "risk_per_share": _r(risk), "risk_pct": _r(risk_pct),
        "targets": [{"r": r, "price": _r(entry + sign * risk * r)} for r in sorted({1.0, target_r, 2.0})],
        "first_target_r": target_r, "reward_risk": target_r,
        "stop_basis": how, "exit_rule": exit_rule, "warnings": warnings,
    }


def plan_for(setup: dict, daily: list[dict], adr: float | None) -> dict | list | None:
    """The plan(s) for one setup, or None. A waiting opening-range setup has two (long above the range, short below it)."""
    sid, state = setup.get("id"), setup.get("state")
    if state not in ("waiting", "triggered"):
        return None
    if sid == "orb":
        hi, lo = setup.get("range_high"), setup.get("range_low")
        if hi is None or lo is None or hi <= lo:
            return None
        mid = (hi + lo) / 2.0
        how = "the middle of the opening range"
        rule = f"Flat by {SESSION_END} IST either way; a close back through the range level cancels it."
        if state == "triggered":
            side = "long" if setup.get("direction") == "bullish" else "short"
            entry = setup.get("trigger_price")
            p = _build(side, entry, mid, TARGET_R["orb"], adr, how, rule, False) if entry else None
            return [p] if p else None
        plans = [_build("long", hi, mid, TARGET_R["orb"], adr, how, rule, True),
                 _build("short", lo, mid, TARGET_R["orb"], adr, how, rule, True)]
        return [p for p in plans if p] or None
    if sid == "oversold":
        entry = setup.get("trigger_price")
        recent = daily[-4:]
        if not entry or len(recent) < 3:
            return None
        stop = min(b["low"] for b in recent)
        p = _build("long", entry, stop, TARGET_R["oversold"], adr, "the lowest low of the last 4 sessions",
                   "Out after 5 sessions if neither level is hit; exit if it closes below the stop.", state == "waiting")
        return [p] if p else None
    if sid == "resistance":
        level = setup.get("level")
        if not level or not adr:
            return None
        entry = level if state == "waiting" else (daily[-1]["close"] if daily else None)
        stop = level * (1.0 - 0.25 * adr / 100.0)
        if not entry:
            return None
        p = _build("long", entry, stop, TARGET_R["resistance"], adr, "a quarter of the typical daily range under the level",
                   "Needs a daily close above the level to count; out after 10 sessions if it goes nowhere.", state == "waiting")
        return [p] if p else None
    return None
