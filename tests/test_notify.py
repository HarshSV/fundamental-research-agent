"""Server-side alerts: storage, the worker that fires them, and the Telegram link (no network)."""
import datetime as dt

import pytest

from notify import store, telegram, worker

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setattr(telegram, "CHAT_FILE", str(tmp_path / "telegram.json"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


def _a(kind, price, d, sym="ABC", msg="m"):
    return {"sym": sym, "name": sym, "kind": kind, "price": price, "dir": d, "message": msg}


def test_add_validates_and_replaces_pending_alerts_of_the_same_kind():
    out = store.add([_a("stop", 95, "below"), _a("target", 110, "above"), _a("bogus", 1, "above"), _a("stop", -1, "below"), _a("stop", 5, "sideways")])
    assert [a["kind"] for a in out] == ["stop", "target"]
    store.add([_a("stop", 90, "below")])
    stops = [a for a in store.list_alerts() if a["kind"] == "stop"]
    assert len(stops) == 1 and stops[0]["price"] == 90.0
    assert any(a["kind"] == "target" for a in store.list_alerts())


def test_remove_by_id_and_by_symbol():
    first = store.add([_a("stop", 95, "below"), _a("target", 110, "above", sym="XYZ")])
    assert store.remove(first[0]["id"]) == 1
    assert store.remove(sym="xyz") == 1 and store.list_alerts() == []


def test_worker_fires_a_price_alert_once_and_sends_telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, "send", lambda t: sent.append(t) or True)
    store.add([_a("target", 110, "above", msg="ABC target hit"), _a("stop", 95, "below")])
    now = dt.datetime(2026, 11, 4, 11, 0, tzinfo=IST)
    assert worker.check_once(lambda s: 100.0, now) == []                    # between stop and target: nothing
    fired = worker.check_once(lambda s: 111.0, now)
    assert [f["kind"] for f in fired] == ["target"] and "ABC target hit" in sent[0]
    assert worker.check_once(lambda s: 112.0, now) == []                    # never twice
    pending = [a for a in store.list_alerts() if not a["fired"]]
    assert [a["kind"] for a in pending] == ["stop"]


def test_worker_below_direction_and_unknown_price_does_not_fire(monkeypatch):
    monkeypatch.setattr(telegram, "send", lambda t: True)
    store.add([_a("stop", 95, "below")])
    now = dt.datetime(2026, 11, 4, 11, 0, tzinfo=IST)
    assert worker.check_once(lambda s: None, now) == []
    assert [f["kind"] for f in worker.check_once(lambda s: 94.5, now)] == ["stop"]


def test_exit_alert_fires_in_the_1525_window_only_on_the_day_it_was_set(monkeypatch):
    monkeypatch.setattr(telegram, "send", lambda t: True)
    created = dt.datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    monkeypatch.setattr(store.time, "time", lambda: created.timestamp())
    store.add([_a("exit", None, None, msg="close the trade")])
    assert worker.check_once(lambda s: 1.0, dt.datetime(2026, 11, 4, 14, 0, tzinfo=IST)) == []
    assert [f["kind"] for f in worker.check_once(lambda s: 1.0, dt.datetime(2026, 11, 4, 15, 26, tzinfo=IST))] == ["exit"]
    store.add([_a("exit", None, None)])
    assert worker.check_once(lambda s: 1.0, dt.datetime(2026, 11, 7, 15, 26, tzinfo=IST)) == []     # a Saturday: not a trading day


def test_telegram_is_not_configured_without_a_token_and_never_sends():
    assert telegram.status() == {"configured": False, "connected": False, "bot": None}
    assert telegram.send("x") is False


def test_telegram_connect_links_the_chat_that_pressed_start(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    calls = []

    def fake_api(method, **p):
        calls.append(method)
        if method == "getUpdates":
            return [{"message": {"text": "hello", "chat": {"id": 1}}}, {"message": {"text": "/start", "chat": {"id": 777}}}]
        return {"username": "navrist_bot"} if method == "getMe" else {}

    monkeypatch.setattr(telegram, "_api", fake_api)
    assert telegram.chat_id() is None
    assert telegram.connect() == {"connected": True} and telegram.chat_id() == "777"
    assert telegram.status() == {"configured": True, "connected": True, "bot": "navrist_bot"}
    monkeypatch.setattr(telegram, "_api", lambda m, **p: [] if m == "getUpdates" else {})
    monkeypatch.setattr(telegram, "CHAT_FILE", telegram.CHAT_FILE + ".none")
    assert telegram.connect()["connected"] is False
