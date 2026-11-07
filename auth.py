"""
Authentication layer for the Navrist Research Terminal.

Single shared access password: anyone who enters the correct SITE_PASSWORD is
granted a short-lived JWT session token. The token is then required on every
data endpoint, so the backend stays protected (not just the frontend UI).

Configure the password and token lifetime in the .env file:
    SITE_PASSWORD=<a long random passphrase; never put the real value in code or comments>
    JWT_SECRET_KEY=<random secret>
    ACCESS_TOKEN_EXPIRE_HOURS=12
"""

import hmac
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt  # PyJWT
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Ensure variables from .env are available before we read them.
load_dotenv()

# --- Configuration -----------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "12"))
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "")


# --- Password check ----------------------------------------------------------
def verify_site_password(password: str) -> bool:
    """Constant-time comparison of the submitted password against SITE_PASSWORD."""
    if not SITE_PASSWORD:
        # Fail closed: if no password is configured, nobody gets in.
        return False
    return hmac.compare_digest(
        (password or "").encode("utf-8"), SITE_PASSWORD.encode("utf-8")
    )


# --- JWT session tokens ------------------------------------------------------
def create_access_token() -> str:
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Add it to your .env file before issuing tokens."
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "navrist-internal",
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


_bearer_scheme = HTTPBearer(auto_error=False)


def require_session(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency: validates the Bearer session token.

    Add `_: dict = Depends(require_session)` to any endpoint to require login.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    if not JWT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Server authentication is not configured (JWT_SECRET_KEY missing).",
        )
    try:
        payload = jwt.decode(
            credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise unauthorized
    return {"session": payload.get("sub", "navrist-internal")}


# --- Login throttling --------------------------------------------------------
# The site is reachable from the internet, so wrong-password attempts are limited per client address:
# after MAX_FAILURES wrong passwords inside WINDOW_SECONDS, further attempts are refused until the oldest
# failure ages out. In memory only (resets on restart), which is enough to stop online password guessing.
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
_failures: "defaultdict[str, deque]" = defaultdict(deque)
_failures_lock = threading.Lock()


def client_key(request) -> str:
    """The caller's address: the Cloudflare header when the request came through the tunnel, else the socket."""
    h = request.headers
    return (h.get("cf-connecting-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def login_retry_after(key: str) -> int:
    """Seconds the caller must wait before another attempt, or 0 when attempts are allowed."""
    now = time.time()
    with _failures_lock:
        q = _failures[key]
        while q and now - q[0] > LOGIN_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= LOGIN_MAX_FAILURES:
            return max(1, int(LOGIN_WINDOW_SECONDS - (now - q[0])))
    return 0


def record_login_failure(key: str) -> None:
    with _failures_lock:
        _failures[key].append(time.time())


def clear_login_failures(key: str) -> None:
    with _failures_lock:
        _failures.pop(key, None)
