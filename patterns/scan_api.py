"""HTTP surface for the pattern scanner (see patterns/scan.py). Mounted from app.py next to the pattern agent router."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from . import scan
from .registry import BY_NAME


def make_router(require_session):
    r = APIRouter()

    @r.get("/api/v1/pattern-scan/options")
    def scan_options(_: dict = Depends(require_session)):
        """What the filter popup offers: index list, sectors, MA periods, statuses and the market-cap bounds."""
        return scan.options()

    @r.get("/api/v1/pattern-scan/status")
    def scan_status(_: dict = Depends(require_session)):
        return scan.status()

    @r.post("/api/v1/pattern-scan/build")
    def scan_build(force: bool = False, _: dict = Depends(require_session)):
        """Start (or report an already running) background scan of the whole universe."""
        started = scan.build(force=force)
        return {"started": started, **scan.status()}

    @r.post("/api/v1/pattern-scan/{pattern}/search")
    def scan_search(pattern: str, include_candles: bool = False, filters: dict = Body(default_factory=dict),
                    _: dict = Depends(require_session)):
        """Stocks currently showing `pattern`, narrowed by the filters:
        indices / sectors / status: {values: [...]} (a stock matches when it has at least one ticked option);
        mcap: {min, max} in Rs crore; ema / dma: {periods: [...], side: "above"|"below"}; q: name or ticker text;
        page, page_size, sort ("status" | "market_cap" | "name")."""
        if pattern not in BY_NAME:
            raise HTTPException(status_code=404, detail=f"Unknown pattern {pattern!r}.")
        return scan.search(pattern, filters, include_candles=include_candles)

    return r
