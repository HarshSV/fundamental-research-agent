"""Sector and screen endpoints (mounted from app.py like the forecast and pattern routers)."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException

from . import universe
from .definitions import BY_ID, GROUPS, SCREENS


def make_router(require_session, fetch_candles):
    r = APIRouter()

    # Resume an unfinished universe build shortly after startup (the build is resumable and idempotent,
    # so a restart or a Screener outage just continues where it left off).
    def _resume():
        import time
        time.sleep(90)
        try:
            st = universe.status()
            if st["have"] < st["universe"]:
                universe.build(fetch_candles)
        except Exception as e:  # pragma: no cover
            print(f"[screens] resume skipped: {e}")

    import threading
    threading.Thread(target=_resume, daemon=True, name="screens-resume").start()

    def _name(sym: str) -> str:
        return universe._names().get(sym, sym)

    @r.get("/api/v1/sectors")
    def sectors(_: dict = Depends(require_session)):
        from tools.nse_sector_map import all_symbols_by_sector
        return sorted(({"name": k, "count": len(v)} for k, v in all_symbols_by_sector().items()), key=lambda x: -x["count"])

    @r.get("/api/v1/sectors/{name:path}")
    def sector_members(name: str, _: dict = Depends(require_session)):
        from tools.nse_sector_map import all_symbols_by_sector
        syms = all_symbols_by_sector().get(name)
        if syms is None:
            raise HTTPException(status_code=404, detail="Unknown sector.")
        data = universe.load()
        rows = []
        for s in syms:
            m = data.get(s) or {}
            rows.append({"symbol": s, "name": m.get("name") or _name(s), "price": m.get("price"),
                         "market_cap_cr": m.get("market_cap_cr"), "pe": m.get("pe"), "eps": m.get("eps"),
                         "ret_1y": m.get("ret_1y")})
        rows.sort(key=lambda x: (-(x["market_cap_cr"] or 0), x["name"]))
        return {"name": name, "count": len(rows), "stocks": rows, "universe": universe.status()}

    @r.get("/api/v1/screens")
    def screens(_: dict = Depends(require_session)):
        st = universe.status()
        have = st["have"] > 0
        cnt = universe.counts() if have else {}
        return {
            "groups": GROUPS,
            "universe": st,
            "screens": [
                {"id": s[0], "group": s[1], "title": s[2], "description": s[3],
                 "criteria": universe.criteria_text(s[0]), "count": cnt.get(s[0]) if have else None}
                for s in SCREENS
            ],
        }

    @r.get("/api/v1/screens/{screen_id}")
    def screen(screen_id: str, _: dict = Depends(require_session)):
        if screen_id not in BY_ID:
            raise HTTPException(status_code=404, detail="Unknown screen.")
        s = BY_ID[screen_id]
        return {"id": s[0], "group": s[1], "title": s[2], "description": s[3],
                "criteria": universe.criteria_text(screen_id), "universe": universe.status(),
                "stocks": universe.evaluate(screen_id)}

    @r.post("/api/v1/screens/build")
    def build(force: bool = False, _: dict = Depends(require_session)):
        started = universe.build(fetch_candles, force=force)
        return {"started": started, "universe": universe.status()}

    return r
