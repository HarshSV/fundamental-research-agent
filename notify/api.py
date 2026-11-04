"""HTTP surface for alerts and the Telegram link. Mounted from app.py."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from . import store, telegram


def make_router(require_session):
    r = APIRouter()

    @r.get("/api/v1/alerts")
    def alerts(_: dict = Depends(require_session)):
        return {"alerts": [a for a in store.list_alerts() if not a.get("expired")], "telegram": telegram.status()}

    @r.post("/api/v1/alerts")
    def add_alerts(body: dict = Body(...), _: dict = Depends(require_session)):
        items = body.get("alerts")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="alerts must be a non-empty list")
        return {"added": store.add(items[:10])}

    @r.delete("/api/v1/alerts")
    def remove_alerts(id: str | None = None, symbol: str | None = None, _: dict = Depends(require_session)):
        if not id and not symbol:
            raise HTTPException(status_code=400, detail="id or symbol required")
        return {"removed": store.remove(id, symbol)}

    @r.post("/api/v1/telegram/connect")
    def connect(_: dict = Depends(require_session)):
        try:
            return telegram.connect()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/api/v1/telegram/test")
    def test(_: dict = Depends(require_session)):
        if not telegram.send("Navrist: test message. Alerts will arrive here."):
            raise HTTPException(status_code=400, detail="Telegram is not connected yet.")
        return {"sent": True}

    return r
