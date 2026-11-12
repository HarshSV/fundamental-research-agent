"""HTTP surface for the pattern agent. Mounted from app.py the same way as the forecast router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from . import service
from .core import DETECTOR_VERSION, STATUSES
from .registry import catalogue


def make_router(resolve_symbol, require_session, fetch_candles):
    r = APIRouter()

    @r.get("/api/v1/patterns/evidence")
    def pattern_evidence(_: dict = Depends(require_session)):
        """What the evidence study (research/pattern_study.py) found for each pattern after 20 sessions: events, average gain over the
        median stock (after costs), the share of trades that beat it, and whether the effect is real. Empty when the study has not been run."""
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "research", "pattern_study.json")
        try:
            with open(path, encoding="utf-8") as fh:
                st = json.load(fh)
        except Exception:
            return {"available": False, "patterns": {}}
        out = {}
        for r in st.get("results", []):
            if r.get("horizon") == 20 and r.get("all"):
                a = r["all"]
                out[f"{r['pattern']}|{r['direction']}"] = {"events": a["events"], "mean_excess_pct": a["mean_excess_pct"], "median_excess_pct": a["median_excess_pct"],
                                                           "win_pct": a["win_pct"], "real_effect": r.get("real_effect", False), "reverse_effect": r.get("reverse_effect", False)}
        return {"available": True, "events_total": st.get("events_total"), "period": st.get("period"), "cost_pct": st.get("cost_pct"), "patterns": out}

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
