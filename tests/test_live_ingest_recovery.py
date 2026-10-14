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
