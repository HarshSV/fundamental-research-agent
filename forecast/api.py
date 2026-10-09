"""Forecast HTTP API. ML stays in the backend: the frontend only renders this payload.

  GET /api/chart/{symbol}/forecast[?refresh=true]  -> actualCandles[], forecastCandles[], forecast{}
  GET /api/forecast/monitoring[?symbol=]           -> realised live performance (internal monitoring)
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from . import config, inference, store, tracking


def forecast_candles(payload):
    """forecastCandles[]: only horizons that carry a full predicted candle. Range-only/withheld horizons
    contribute an `envelope` entry (no candle body) when an interval is available."""
    candles, envelope = [], []
    for f in payload["forecasts"]:
        t = f["forecast_timestamp"]
        if f.get("close") is not None:
            candles.append({"time": t, "open": f["open"], "high": f["high"], "low": f["low"], "close": f["close"],
                            "horizon": f["horizon"], "confidence": f["confidence"], "direction_probability": f.get("direction_probability"),
                            "isForecast": True})
        if f.get("intervals"):
            envelope.append({"time": t, "horizon": f["horizon"], "intervals": f["intervals"]})
    return candles, envelope


def build_response(con, payload, n_actual=150):
    cc = payload.get("current_candle")
    actual = []
    if cc:
        rows = store.load_candles(con, payload["symbol"], config.INTERVAL, cc["time"] - n_actual * config.BAR_SECONDS * 2, cc["time"])
        actual = [{"time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5], "isForecast": False} for r in rows][-n_actual:]
    candles, envelope = forecast_candles(payload)
    return {"symbol": payload["symbol"], "timeframe": payload["timeframe"], "as_of": payload["as_of_ts"], "status": payload["status"],
            "actualCandles": actual, "forecastCandles": candles, "forecastEnvelope": envelope, "forecast": payload}


def _log_error(symbol, exc):
    """Append the full traceback to data/forecast/api_errors.log (and stdout) so a failing forecast is diagnosable."""
    import os
    import time
    import traceback
    tb = traceback.format_exc()
    print(f"[forecast api] {symbol}: {type(exc).__name__}: {exc}\n{tb}")
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(os.path.join(config.DATA_DIR, "api_errors.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {symbol}\n{tb}\n")
    except Exception:
        pass


def make_router(resolve_symbol, require_session):
    r = APIRouter()

    @r.get("/api/chart/{symbol}/forecast")
    async def chart_forecast(symbol: str, refresh: bool = False, _: dict = Depends(require_session)):
        sym = resolve_symbol(symbol)
        if not sym:
            raise HTTPException(status_code=400, detail="Symbol required.")

        def work():
            refreshing = False
            if refresh:
                from . import live_ingest
                live_ingest.refresh_async(sym)            # never blocks on the provider
                refreshing = live_ingest.is_refreshing(sym)
            con = store.connect()
            as_of = inference.last_complete_boundary(__import__("time").time())
            prod = __import__("forecast.registry", fromlist=["x"]).production_model(con)
            onboarding_running = False
            if prod is not None:
                from . import onboarding
                art = inference._load_artifact(prod)
                state, _ = onboarding.symbol_status(con, sym, prod, art["meta"])
                if state == "unknown":
                    onboarding.onboard_async(sym)          # first-time validation (fetch + forward test), off-thread
                onboarding_running = onboarding.is_running(sym)
            ver = prod["model_version"] if prod else None
            existing = con.execute("SELECT forecast_id FROM forecasts WHERE symbol=? AND timeframe=? AND as_of_ts=? AND model_version IS ? LIMIT 1",
                                   (sym, config.INTERVAL, as_of, ver)).fetchone()
            payload = inference.forecast_payload(con, sym, as_of, persist=existing is None)
            if existing is not None:
                payload["forecast_id"] = existing[0]
            tracking.evaluate_pending(con, sym)
            resp = build_response(con, payload)
            resp["refreshing"] = bool(refreshing or onboarding_running)
            return resp

        try:
            return await asyncio.to_thread(work)
        except HTTPException:
            raise
        except Exception as e:                                  # surface the REAL cause instead of an opaque 500
            _log_error(sym, e)
            return {"symbol": sym, "timeframe": config.INTERVAL, "status": "ERROR", "error": f"{type(e).__name__}: {str(e)[:160]}",
                    "refreshing": False, "actualCandles": [], "forecastCandles": [], "forecastEnvelope": [], "forecast": None}

    @r.get("/api/forecast/coverage")
    async def coverage(_: dict = Depends(require_session)):
        def work():
            from . import onboarding, registry
            con = store.connect()
            prod = registry.production_model(con)
            if prod is None:
                return {"model_version": None, "pilot": 0, "validated": 0, "failed": 0}
            meta = inference._load_artifact(prod)["meta"]
            c = onboarding.coverage(con, prod["model_version"])
            fails = con.execute("SELECT symbol, reasons_json FROM symbol_validation WHERE model_version=? AND status='failed' ORDER BY validated_at DESC LIMIT 25", (prod["model_version"],)).fetchall()
            return {"model_version": prod["model_version"], "pilot_symbols": meta["validated_symbols"], "validated": c.get("validated", 0),
                    "failed": c.get("failed", 0), "pending": c.get("pending", 0), "recent_failures": [{"symbol": s, "reasons": __import__("json").loads(r)} for s, r in fails]}
        return await asyncio.to_thread(work)

    @r.get("/api/forecast/monitoring")
    async def monitoring(symbol: str | None = None, _: dict = Depends(require_session)):
        def work():
            con = store.connect()
            tracking.evaluate_pending(con, symbol)
            return tracking.monitoring_stats(con, symbol)
        return await asyncio.to_thread(work)

    return r
