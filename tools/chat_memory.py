"""
Ask Navrist persistent memory - stores chat turns in Supabase (db/003_chat_memory.sql)
so the assistant can recall earlier questions across page reloads / browser
sessions, not just the current in-memory 16-message window. There's no real
per-user login here (single shared SITE_PASSWORD, see auth.py), so history is
keyed by a client-generated anonymous `session_id` the frontend stores in
localStorage and sends with every request.

Never raises - if Supabase isn't configured (or the table doesn't exist yet),
memory silently becomes a no-op rather than breaking the chat.
"""

import os

RECENT_LIMIT = 40          # rows fetched for the raw fallback
SUMMARY_TURNS = 8          # how many recent user/assistant pairs feed the memory block


def _client():
    try:
        from tools.supabase_client import get_client
        return get_client()
    except Exception:
        return None


def save_message(session_id: str, role: str, content: str, symbol: str = None) -> None:
    if not session_id or not content:
        return
    client = _client()
    if client is None:
        return
    try:
        client.table("chat_messages").insert({
            "session_id": session_id, "role": role, "content": content[:4000],
            "symbol": symbol,
        }).execute()
    except Exception as e:
        print(f"[chat_memory] save failed: {e}")


def _recent_rows(session_id: str, limit: int = RECENT_LIMIT) -> list:
    client = _client()
    if client is None or not session_id:
        return []
    try:
        resp = (
            client.table("chat_messages")
            .select("role,content,symbol,created_at")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        rows.reverse()  # oldest -> newest
        return rows
    except Exception as e:
        print(f"[chat_memory] fetch failed: {e}")
        return []


def memory_block(session_id: str, exclude_last_n: int = 0) -> str:
    """Compact text block of the user's recent question history across past
    sessions, for the system prompt. `exclude_last_n` drops the most recent N
    rows (the current request's own turns, which the caller already includes
    verbatim in the conversation) to avoid duplicating them. Empty string if
    there's no prior history or memory isn't configured."""
    rows = _recent_rows(session_id)
    if exclude_last_n:
        rows = rows[:-exclude_last_n] if exclude_last_n < len(rows) else []
    # Keep only user questions + a trimmed version of the assistant's answer,
    # most recent SUMMARY_TURNS pairs - enough to notice recurring interests
    # or follow-up threads without bloating the prompt.
    user_qs = [r for r in rows if r.get("role") == "user"]
    if not user_qs:
        return ""
    tail = rows[-(SUMMARY_TURNS * 2):]
    lines = []
    for r in tail:
        tag = "User asked" if r.get("role") == "user" else "You answered"
        sym = f" [{r['symbol']}]" if r.get("symbol") else ""
        text = (r.get("content") or "").strip().replace("\n", " ")
        if len(text) > 220:
            text = text[:220] + "…"
        lines.append(f"- {tag}{sym}: {text}")
    if not lines:
        return ""
    return (
        "\n\nPRIOR CONVERSATION HISTORY (earlier sessions with this user - use it to "
        "avoid repeating yourself, notice recurring interests, and answer follow-ups "
        "consistently with what you said before; do not re-greet them):\n" + "\n".join(lines)
    )


if __name__ == "__main__":
    import sys
    sid = sys.argv[1] if len(sys.argv) > 1 else "test-session"
    save_message(sid, "user", "What's the ROE of Tata Steel?", symbol="TATASTEEL")
    save_message(sid, "assistant", "Tata Steel's ROE is 11.3%.", symbol="TATASTEEL")
    print(memory_block(sid))
