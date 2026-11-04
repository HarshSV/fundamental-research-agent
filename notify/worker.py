"""Background worker: checks every pending alert against the live price every 30 seconds and sends Telegram messages."""
from __future__ import annotations

import datetime as _dt
import time

from . import store, telegram

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def check_once(price_fn, now: _dt.datetime | None = None) -> list[dict]:
    """Fire what has been reached. Returns the alerts fired in this pass (already saved and sent)."""
    now = now or _dt.datetime.now(IST)
    rows = [a for a in store.list_alerts() if not a.get("fired")]
    if not rows:
        return []
    weekday = now.weekday() < 5
    mins = now.hour * 60 + now.minute
    prices: dict[str, float | None] = {}
    for sym in {a["sym"] for a in rows if a["kind"] != "exit"}:
        try:
            prices[sym] = price_fn(sym)
        except Exception:
            prices[sym] = None
    fired, changed = [], []
    ts = int(now.timestamp())
    for a in rows:
        hit = False
        if a["kind"] == "exit":
            created = _dt.datetime.fromtimestamp(a["created"], IST)
            window = weekday and 15 * 60 + 25 <= mins < 15 * 60 + 40
            hit = window and created.date() == now.date() and created.hour * 60 + created.minute < 15 * 60 + 25
            if not hit and ts - a["created"] > 12 * 3600:
                changed.append({"id": a["id"], "fired": ts, "sent": None, "expired": True})    # the day is over; retire it quietly
                continue
        else:
            p = prices.get(a["sym"])
            hit = p is not None and (p >= a["price"] if a["dir"] == "above" else p <= a["price"])
        if hit:
            sent = telegram.send(f"Navrist alert\n{a['message']}")
            changed.append({"id": a["id"], "fired": ts, "sent": ts if sent else None})
            fired.append({**a, "fired": ts})
    if changed:
        store.update(changed)
    return fired


def loop(price_fn, every: int = 30) -> None:
    time.sleep(45)
    while True:
        try:
            check_once(price_fn)
        except Exception as e:
            print(f"[alerts] worker: {e}")
        time.sleep(every)
