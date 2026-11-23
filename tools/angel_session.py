"""One shared Angel One login for every Navrist process (API, worker, forecast collector).

Angel keeps ONE active session per client code: a new login invalidates the token of every earlier one, so two processes that each
logged in (the API and the worker both do, and the forecast collector too) kept killing each other's token and every live quote came back
"Invalid Token" - the site then silently fell back to Yahoo Finance.

Now the session lives in data/angel_session.json (git-ignored, holds tokens). A process that needs Angel reads it; it logs in only when
there is no fresh session, or when Angel has told it that the token it holds is invalid AND nobody has refreshed the file since. A file lock
makes the check-and-login one step across processes, so a dead session is replaced once, not once per process.

Secrets are never printed.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time

try:
    from SmartApi import SmartConnect
except Exception:  # pragma: no cover - the package is optional in some environments
    SmartConnect = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.environ.get("ANGEL_SESSION_FILE") or os.path.join(ROOT, "data", "angel_session.json")
LOCK_PATH = PATH + ".lock"
TTL = 8 * 3600            # a session older than this is replaced even if Angel has not complained
MIN_RELOGIN = 30          # a session issued less than this long ago that is already "invalid" is not replaced again (it would not help)
INVALID_CODES = {"AG8001", "AG8002", "AG8003"}

_mem = threading.RLock()


def is_invalid_token(resp) -> bool:
    """True when an Angel reply says the session token is no good (dead or replaced by a newer login)."""
    if not isinstance(resp, dict) or resp.get("status") is not False:
        return False
    if str(resp.get("errorcode", "")).upper() in INVALID_CODES:
        return True
    msg = str(resp.get("message", "")).lower()
    return "invalid token" in msg or "token expired" in msg or ("session" in msg and "expired" in msg)


def _creds() -> dict | None:
    c = {k: (os.getenv(k) or "").strip() for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET")}
    if not all(c.values()) or any(p in c["ANGEL_API_KEY"] for p in ("your_copied", "dummy", "here")):
        return None
    return c


def _read() -> dict | None:
    try:
        with open(PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) and d.get("jwt") and d.get("ts") else None
    except Exception:
        return None


def _write(d: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.replace(tmp, PATH)


@contextlib.contextmanager
def _file_lock(timeout: float = 60.0):
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    fh = open(LOCK_PATH, "a+b")
    start = time.time()
    try:
        while True:
            try:
                fh.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() - start > timeout:
                    raise TimeoutError("could not lock the Angel session file")
                time.sleep(0.2)
        yield
    finally:
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_UN)
        except Exception:
            pass
        fh.close()


def _client_from(s: dict):
    sc = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    sc.setAccessToken(s["jwt"])
    sc.setRefreshToken(s.get("refresh"))
    sc.setFeedToken(s.get("feed"))
    sc.setUserId(s.get("client"))
    return sc


def _login_new():
    import pyotp
    c = _creds()
    sc = SmartConnect(api_key=c["ANGEL_API_KEY"])
    r = sc.generateSession(c["ANGEL_CLIENT_CODE"], c["ANGEL_PASSWORD"], pyotp.TOTP(c["ANGEL_TOTP_SECRET"]).now())
    if not (isinstance(r, dict) and r.get("status") is True):
        print(f"[angel_session] login refused: {(r or {}).get('message') if isinstance(r, dict) else r}", flush=True)
        return None
    s = {"jwt": sc.access_token, "refresh": getattr(sc, "refresh_token", None), "feed": getattr(sc, "feed_token", None),
         "client": getattr(sc, "userId", None), "ts": time.time(), "pid": os.getpid()}
    _write(s)
    print("[angel_session] new Angel session established and shared", flush=True)
    return sc, s["ts"]


def ensure(bad_ts: float | None = None):
    """(SmartConnect, issued_at) for a usable session, or (None, 0.0) when Angel cannot be used.

    bad_ts: the issue time of the session the caller just found invalid. A session newer than that (another process already replaced it)
    is adopted instead of logging in again."""
    if SmartConnect is None or _creds() is None:
        return None, 0.0
    try:
        with _mem, _file_lock():
            s = _read()
            now = time.time()
            usable = s and now - s["ts"] < TTL and (bad_ts is None or s["ts"] > bad_ts)
            if usable:
                return _client_from(s), s["ts"]
            if bad_ts is not None and s and s["ts"] <= bad_ts and now - s["ts"] < MIN_RELOGIN:
                return None, 0.0                      # just issued and still refused: another login is fighting us; do not pile on
            got = _login_new()
            return got if got else (None, 0.0)
    except Exception as e:
        print(f"[angel_session] could not get a session: {e}", flush=True)
        return None, 0.0
