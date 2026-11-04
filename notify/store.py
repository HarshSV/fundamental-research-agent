"""Alert storage: one JSON file, written atomically, safe across the worker thread and the request threads."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "alerts.json")
_lock = threading.Lock()
KINDS = ("entry", "stop", "target", "exit")


def _read() -> list[dict]:
    try:
        with open(PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _write(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    os.replace(tmp, PATH)


def list_alerts() -> list[dict]:
    with _lock:
        return _read()


def add(items: list[dict]) -> list[dict]:
    """Add alerts (validated). A new set for a symbol replaces that symbol's pending alerts of the same kinds."""
    clean = []
    for it in items:
        kind, sym = it.get("kind"), str(it.get("sym") or "").strip().upper()
        price = it.get("price")
        direction = it.get("dir")
        if kind not in KINDS or not sym:
            continue
        if kind == "exit":
            price, direction = None, None
        elif not isinstance(price, (int, float)) or price <= 0 or direction not in ("above", "below"):
            continue
        clean.append({"id": uuid.uuid4().hex[:12], "sym": sym, "name": str(it.get("name") or sym)[:80], "kind": kind,
                      "price": float(price) if price is not None else None, "dir": direction,
                      "message": str(it.get("message") or "")[:200], "created": int(time.time()), "fired": None, "sent": None})
    with _lock:
        rows = _read()
        replace = {(a["sym"], a["kind"]) for a in clean}
        rows = [r for r in rows if r.get("fired") or (r["sym"], r["kind"]) not in replace]
        rows += clean
        _write(rows[-500:])
    return clean


def remove(alert_id: str | None = None, sym: str | None = None) -> int:
    with _lock:
        rows = _read()
        keep = [r for r in rows if not ((alert_id and r["id"] == alert_id) or (sym and r["sym"] == sym.upper()))]
        _write(keep)
        return len(rows) - len(keep)


def update(rows_changed: list[dict]) -> None:
    with _lock:
        rows = _read()
        by = {r["id"]: r for r in rows}
        for c in rows_changed:
            if c["id"] in by:
                by[c["id"]].update(c)
        _write(list(by.values()))
