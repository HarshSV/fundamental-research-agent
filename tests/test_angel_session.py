"""The shared Angel session: one login for all processes, replaced once when Angel says the token is invalid."""
import time

import pytest

from tools import angel_session as a


class FakeSC:
    logins = 0

    def __init__(self, api_key=None):
        self.access_token = self.refresh_token = self.feed_token = self.userId = None

    def generateSession(self, code, pw, totp):
        FakeSC.logins += 1
        self.access_token, self.refresh_token, self.feed_token, self.userId = f"jwt{FakeSC.logins}", "r", "f", code
        return {"status": True}

    def setAccessToken(self, t): self.access_token = t
    def setRefreshToken(self, t): self.refresh_token = t
    def setFeedToken(self, t): self.feed_token = t
    def setUserId(self, t): self.userId = t


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(a, "LOCK_PATH", str(tmp_path / "s.json.lock"))
    monkeypatch.setattr(a, "SmartConnect", FakeSC)
    for k, v in (("ANGEL_API_KEY", "k"), ("ANGEL_CLIENT_CODE", "C1"), ("ANGEL_PASSWORD", "p"), ("ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")):
        monkeypatch.setenv(k, v)
    FakeSC.logins = 0


def test_invalid_token_detection():
    assert a.is_invalid_token({"status": False, "message": "Invalid Token", "errorcode": "AG8001"})
    assert a.is_invalid_token({"status": False, "message": "Invalid Token"})
    assert not a.is_invalid_token({"status": True})
    assert not a.is_invalid_token({"status": False, "message": "rate limit", "errorcode": "AB1010"})
    assert not a.is_invalid_token(None)


def test_one_login_is_shared():
    sc1, ts1 = a.ensure()
    sc2, ts2 = a.ensure()
    assert FakeSC.logins == 1 and ts1 == ts2 and sc2.access_token == sc1.access_token == "jwt1"


def test_a_session_already_replaced_by_another_process_is_adopted():
    sc, ts = a.ensure()
    # another process refreshes the file after our token was issued
    a._write({"jwt": "newer", "refresh": "r", "feed": "f", "client": "C1", "ts": ts + 100})
    sc2, ts2 = a.ensure(bad_ts=ts)
    assert FakeSC.logins == 1 and sc2.access_token == "newer" and ts2 == ts + 100      # adopted, no new login


def test_an_invalid_session_is_replaced_once():
    sc, ts = a.ensure()
    a._write({"jwt": "old", "refresh": "r", "feed": "f", "client": "C1", "ts": time.time() - 3600})
    sc2, ts2 = a.ensure(bad_ts=time.time() - 3600)
    assert FakeSC.logins == 2 and sc2.access_token == "jwt2"
    sc3, _ = a.ensure(bad_ts=ts - 5000)                       # a second process that also saw the old token adopts the new one
    assert FakeSC.logins == 2 and sc3.access_token == "jwt2"


def test_a_just_issued_session_that_is_still_refused_is_not_replaced_again():
    sc, ts = a.ensure()
    assert a.ensure(bad_ts=ts) == (None, 0.0) and FakeSC.logins == 1


def test_missing_credentials_means_no_angel(monkeypatch):
    monkeypatch.setenv("ANGEL_PASSWORD", "")
    assert a.ensure() == (None, 0.0) and FakeSC.logins == 0
