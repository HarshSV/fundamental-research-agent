"""
Shared Groq chat helper with a model fallback chain.

Groq free-tier rate limits are PER MODEL (tokens per day / per minute). When the
primary 70b model exhausts its daily quota (HTTP 429), every AI feature used to
fail at once — empty Business Model Canvas, "Summary generation failed" concall
months. Falling back to the smaller instant model (separate quota) keeps those
features alive with slightly lower quality instead of failing outright.

The fallback model has a small tokens-per-MINUTE cap (6k), so oversized inputs
(full concall transcripts) are trimmed head+tail to fit before the retry.
"""

import os
import re

# (model, approx input char budget, completion-token cap). ~4 chars/token; the
# 8b model's 6k TPM cap counts input + requested completion tokens. The
# qualitative-analysis schema (F-07 through F-25) needs ~4k+ completion tokens
# to come back complete rather than silently truncated, so the input budget is
# trimmed tighter (6.5k chars ~= 1.6k tokens) to leave room for a 4k completion
# cap while staying under the 6k TPM ceiling.
MODEL_CHAIN = [
    ("llama-3.3-70b-versatile", None, None),
    ("llama-3.1-8b-instant", 6500, 4000),
]


def _fit_messages(messages, budget):
    """Trim the longest message content (head + tail kept) to fit a char budget."""
    if not budget:
        return messages
    total = sum(len(m.get("content") or "") for m in messages)
    if total <= budget:
        return messages
    msgs = [dict(m) for m in messages]
    longest = max(msgs, key=lambda m: len(m.get("content") or ""))
    others = total - len(longest["content"])
    room = max(budget - others, 2000)
    c = longest["content"]
    head = int(room * 0.7)
    tail = room - head
    longest["content"] = c[:head] + "\n...[transcript trimmed to fit model context]...\n" + c[-tail:]
    return msgs


def parse_json_loose(text):
    """
    Parse LLM JSON output tolerantly. Smaller fallback models emit sloppy JSON —
    markdown fences, prose around the object, invalid escapes (\\₹, \\%), and
    trailing commas — which strict json.loads rejects, silently degrading whole
    features to mock data. Repairs those before giving up.
    """
    import json
    import re

    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)

    # Slice to the first BALANCED {...} object rather than first-{ to last-}.
    # On long prompts the fallback model sometimes emits the JSON object followed
    # by leftover/duplicate text that also contains braces (e.g. echoing part of
    # the schema again) — a naive rfind("}") then swallows that too and json.loads
    # fails with "Extra data" even though the real object was well-formed.
    i = t.find("{")
    if i >= 0:
        depth, in_str, esc, end = 0, False, False, None
        for k in range(i, len(t)):
            ch = t[k]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = k
                    break
        if end is not None:
            t = t[i:end + 1]
    try:
        return json.loads(t)
    except Exception:
        pass
    t2 = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', t)   # escape stray backslashes
    t2 = re.sub(r",\s*([}\]])", r"\1", t2)            # drop trailing commas
    try:
        return json.loads(t2)
    except Exception:
        pass
    return json.loads(_escape_unescaped_inner_quotes(t2))


def _escape_unescaped_inner_quotes(t):
    """
    Repairs the single most common LLM JSON failure: a string value containing
    an unescaped literal quote (e.g. the company's "flagship" plant), which makes
    json.loads think the string ended early and then fail with "Expecting ','
    delimiter" a few tokens later. A `"` only legitimately CLOSES a string if the
    next non-whitespace character is a JSON structural one (, : } ] or end of
    text) — any other `"` inside a string is escaped instead of trusted.
    """
    out, i, n = [], 0, len(t)
    in_str, esc = False, False
    while i < n:
        ch = t[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if esc:
            out.append(ch)
            esc = False
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            esc = True
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and t[j] in " \t\r\n":
                j += 1
            if j >= n or t[j] in ",:}]":
                out.append(ch)
                in_str = False
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def groq_chat(messages, temperature=None, max_tokens=None, api_key=None):
    """
    Run a chat completion, trying each model in MODEL_CHAIN until one succeeds.
    Returns the response text. Raises the LAST error only if every model fails.
    """
    from groq import Groq

    key = (api_key or os.getenv("GROQ_API_KEY", "")).strip()
    if not key or key == "your_api_key_here":
        raise RuntimeError("GROQ_API_KEY not configured")

    import time as _time

    # max_retries=0: the SDK's own retry+backoff on a 429/5xx from the primary
    # model would otherwise silently burn many seconds BEFORE our MODEL_CHAIN
    # fallback below ever gets a chance to try the next model — defeating the
    # whole point of having a fast fallback. We handle retries ourselves.
    client = Groq(api_key=key, max_retries=0)
    last_err = None
    # Every model's failure reason, not just the last one — otherwise, when the
    # primary model fails for reason A and the fallback then fails for reason B,
    # only B is ever visible, making it impossible to tell WHY the fallback was
    # even needed (e.g. was the 70b model rate-limited, or a different error?).
    errors_by_model = {}
    for model, budget, tok_cap in MODEL_CHAIN:
        kwargs = {"model": model, "messages": _fit_messages(messages, budget)}
        if temperature is not None:
            kwargs["temperature"] = temperature
        mt = max_tokens
        if tok_cap is not None:
            mt = min(mt, tok_cap) if mt else tok_cap
        if mt is not None:
            kwargs["max_tokens"] = mt
        # Retry transient network blips AND per-minute rate limits before falling
        # through to the next model. A per-minute TPM limit genuinely clears on
        # its own within ~60s — one retry can still land in a not-yet-reset
        # window (e.g. a 32s wait plus a slow-starting request), so this allows
        # up to 3 waits (the API tells us exactly how long each time).
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                completion = client.chat.completions.create(**kwargs)
                text = completion.choices[0].message.content
                if model != MODEL_CHAIN[0][0]:
                    print(f"[groq_chat] served by fallback model {model}")
                return text
            except Exception as e:
                last_err = e
                errors_by_model[model] = str(e)[:300]
                msg = str(e).lower()
                transient = any(w in msg for w in ("connection", "timeout", "timed out", "temporarily", "503", "502"))
                if transient and attempt < max_attempts - 1:
                    print(f"[groq_chat] {model} transient error ({str(e)[:80]}); retrying...")
                    _time.sleep(1.5)
                    continue
                # A per-MINUTE token-rate-limit (as opposed to a daily/quota 429)
                # tells us exactly how long until it resets — e.g. "Please try
                # again in 32.13s". Worth waiting out (up to a few times) rather
                # than immediately giving up on this model, since on the last
                # model in the chain that means the whole call fails outright.
                wait_match = re.search(r"try again in (\d+(?:\.\d+)?)s", msg)
                if wait_match and attempt < max_attempts - 1:
                    wait_s = min(float(wait_match.group(1)) + 1, 60)
                    print(f"[groq_chat] {model} per-minute rate limit; waiting {wait_s:.0f}s before retrying (attempt {attempt + 1}/{max_attempts})...")
                    _time.sleep(wait_s)
                    continue
                print(f"[groq_chat] {model} failed ({str(e)[:160]}); trying next model...")
                break
    if last_err is not None:
        summary = " | ".join(f"{m}: {e}" for m, e in errors_by_model.items())
        raise RuntimeError(f"All models in chain failed. {summary}") from last_err
    raise last_err
