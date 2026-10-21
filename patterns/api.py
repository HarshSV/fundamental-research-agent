"""HTTP surface for the pattern agent. Mounted from app.py the same way as the forecast router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from . import service
from .core import DETECTOR_VERSION, STATUSES
from .registry import catalogue


def make_router(resolve_symbol, require_session, fetch_candles):
    r = APIRouter()

    @r.get("/api/v1/patterns/catalogue")
    def pattern_catalogue(_: dict = Depends(require_session)):
        return {"version": DETECTOR_VERSION, "statuses": list(STATUSES), "patterns": catalogue()}

    @r.get("/api/v1/patterns/{symbol}")
    def stock_patterns(symbol: str, timeframe: str = "1d", status: str | None = None, pattern: str | None = None,
                       refresh: bool = False, _: dict = Depends(require_session)):
        sym = resolve_symbol(symbol)
        if not sym:
            raise HTTPException(status_code=400, detail="Symbol required.")
        if status and status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {list(STATUSES)}")
        try:
            return service.get_patterns(sym, timeframe, fetch_candles, status=status, pattern=pattern, refresh=refresh)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return r
