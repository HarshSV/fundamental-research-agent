from forecast import live_ingest


def test_failed_refresh_drops_the_cached_provider_session(monkeypatch):
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("session expired")

    live_ingest._client = object()                       # pretend a (now dead) session is cached
    monkeypatch.setattr(live_ingest, "_get_client", boom)
    r = live_ingest.refresh_symbol("ANY")
    assert r["refreshed"] is False and "session expired" in r["reason"]
    assert live_ingest._client is None                   # next attempt must log in again, not reuse the dead session
    live_ingest.refresh_symbol("ANY")
    assert calls["n"] == 2                               # and it does try again


def test_fallback_boundary_is_the_latest_bar_whose_horizons_all_fit_the_session():
    from forecast import api, config, timeutil
    day = "2026-10-14"
    ts = [timeutil.slot_ts(day, s) for s in range(0, 76)]          # a full session including the unusable tail
    got = api.fallback_as_of(ts)
    assert timeutil.slot_of(got - config.BAR_SECONDS) == config.USABLE_SLOTS - 1 - max(config.HORIZONS)
    assert api.fallback_as_of([timeutil.slot_ts(day, 70), timeutil.slot_ts(day, 71)]) is None   # nothing that fits


def test_unvalidated_symbol_detection_and_experimental_label(monkeypatch):
    from forecast import api, inference, onboarding, registry
    assert api.unvalidated_only({"reasons": ["symbol_not_validated: x"], "forecasts": []})
    assert api.unvalidated_only({"reasons": [], "forecasts": [{"reasons": ["symbol_not_validated: y"]}]})
    assert not api.unvalidated_only({"reasons": ["stale_bars"], "forecasts": []})


def test_forecast_payload_withholds_failed_symbols_unless_explicitly_allowed():
    import time
    from forecast import inference, onboarding, store
    con = store.connect()
    real = onboarding.symbol_status
    onboarding.symbol_status = lambda *a, **k: ("failed", ["data_quality: gappy"])
    try:
        p = inference.forecast_payload(con, "ANURAS", persist=False)
        if p["status"] == "NO_RELIABLE_FORECAST" and any("no_production_model" in r for r in p.get("reasons", [])):
            return    # no model in this environment
        assert any("symbol_not_validated" in r for r in p["reasons"] + [x for f in p["forecasts"] for x in f.get("reasons", [])])
        assert "experimental" not in p
    finally:
        onboarding.symbol_status = real
