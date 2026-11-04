"""Telegram delivery through the Bot API. The bot token lives only in the server's .env (TELEGRAM_BOT_TOKEN); it is never
sent to the browser, logged or committed. The chat id is learned when the user presses Start on the bot."""
from __future__ import annotations

import json
import os
import threading

import requests

from .store import ROOT

CHAT_FILE = os.path.join(ROOT, "data", "telegram.json")
_lock = threading.Lock()


def token() -> str | None:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() or None


def _api(method: str, **params):
    t = token()
    if not t:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    r = requests.post(f"https://api.telegram.org/bot{t}/{method}", json=params, timeout=15)
    d = r.json()
    if not d.get("ok"):
        raise RuntimeError(d.get("description") or f"Telegram {method} failed")
    return d["result"]


def chat_id() -> str | None:
    env = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if env:
        return env
    try:
        with open(CHAT_FILE, encoding="utf-8") as fh:
            return str(json.load(fh).get("chat_id") or "") or None
    except Exception:
        return None


def status() -> dict:
    """{configured, connected, bot}: configured = token present, connected = a chat is linked."""
    if not token():
        return {"configured": False, "connected": False, "bot": None}
    try:
        bot = _api("getMe").get("username")
    except Exception:
        return {"configured": True, "connected": bool(chat_id()), "bot": None, "error": "Telegram did not accept the bot token."}
    return {"configured": True, "connected": bool(chat_id()), "bot": bot}


def send(text: str) -> bool:
    cid = chat_id()
    if not cid or not token():
        return False
    try:
        _api("sendMessage", chat_id=cid, text=text[:3500])
        return True
    except Exception as e:
        print(f"[telegram] send failed: {e}")
        return False


def connect() -> dict:
    """Find the chat of whoever pressed Start on the bot most recently and keep it as the alert destination."""
    updates = _api("getUpdates", limit=50, timeout=0)
    for u in reversed(updates):
        m = u.get("message") or {}
        if str(m.get("text", "")).startswith("/start") and (m.get("chat") or {}).get("id"):
            cid = str(m["chat"]["id"])
            with _lock:
                os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
                with open(CHAT_FILE, "w", encoding="utf-8") as fh:
                    json.dump({"chat_id": cid}, fh)
            send("Navrist alerts are connected. You will get a message here when a stop, target or entry level is reached.")
            return {"connected": True}
    return {"connected": False, "reason": "No message found yet. Open the bot in Telegram, press Start, then check again."}
