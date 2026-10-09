"""The forecast API must never answer with an opaque 500: failures become a structured, logged error."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forecast import api, config, inference  # noqa: E402


def test_api_returns_a_structured_error_not_a_bare_500(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "e.db"))

    def boom(*a, **k):
        raise OSError("model file missing")

    monkeypatch.setattr(inference, "forecast_payload", boom)
    app = FastAPI()
    app.include_router(api.make_router(lambda s: s.upper(), lambda: {"ok": 1}))
    r = TestClient(app).get("/api/chart/aaa/forecast")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ERROR" and "OSError: model file missing" in j["error"] and j["forecast"] is None
    assert "model file missing" in open(tmp_path / "api_errors.log", encoding="utf-8").read()   # traceback logged
