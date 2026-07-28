"""
Shared LLM chat helper with a cross-provider fallback chain.

Groq free-tier rate limits are PER MODEL (tokens per day / per minute). When the
primary 70b model exhausts its daily quota (HTTP 429), every AI feature used to
fail at once — empty Business Model Canvas, "Summary generation failed" concall
months. The chain now tries three free OpenRouter models (each on its own
account/key, so none share a quota) before ever touching Groq, and only falls
back to the Groq 70b->8b pair as the last resort. A single exhausted provider
can no longer take the whole pipeline down.

The Groq fallback model has a small tokens-per-MINUTE cap (6k), so oversized
inputs (full concall transcripts) are trimmed head+tail to fit before the retry.
"""

import os
import re

try:
    # Some Windows setups (e.g. Norton/antivirus TLS scanning) install their
    # own root CA into the OS trust store but not into Python's certifi
    # bundle, causing SSL_CERTIFICATE_VERIFY_FAILED on every HTTPS call. This
    # makes Python trust whatever the OS already trusts. No-op if the OS trust
    # store already matches certifi (e.g. on Linux/prod).
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

# Free OpenRouter models tried in order, each with its own API key (separate
# free-tier quota per key/account). model_id is the OpenRouter slug.
# can_disable_reasoning: False for models that reject `reasoning: {enabled:
# false}` outright (e.g. gpt-oss-20b requires reasoning mode) — for those we
# simply omit the reasoning param instead of forcing it off.
OPENROUTER_CHAIN = [
    ("nvidia/nemotron-3-super-120b-a12b:free", "OPENROUTER_API_KEY_1", True),
    ("openai/gpt-oss-20b:free", "OPENROUTER_API_KEY_2", False),
    ("nvidia/nemotron-3-nano-30b-a3b:free", "OPENROUTER_API_KEY_3", True),
]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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
    t3 = _escape_raw_control_chars_in_strings(t2)
    try:
        return json.loads(t3)
    except Exception:
        pass
    return json.loads(_escape_unescaped_inner_quotes(t3))


def _escape_raw_control_chars_in_strings(t):
    """
    Repairs 'Unterminated string' / 'Invalid control character' failures: the
    model sometimes quotes a chunk of source text (e.g. a concall excerpt)
    verbatim, embedding a literal newline/tab/carriage-return inside a JSON
    string. The JSON spec requires those be escaped as \\n/\\t/\\r; a raw one
    makes json.loads think the string ended at the line break. Escape any
    literal control character found while inside a string, leave everything
    outside strings untouched.
    """
    out, i, n = [], 0, len(t)
    in_str, esc = False, False
    while i < n:
        ch = t[i]
        if in_str and not esc and ch in ("\n", "\r", "\t"):
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            i += 1
            continue
        out.append(ch)
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        i += 1
    return "".join(out)


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


def _try_openrouter(messages, temperature, max_tokens):
    """
    Try each free OpenRouter model in OPENROUTER_CHAIN, each under its own API
    key (separate free-tier quota, so one account running dry doesn't block the
    others). Returns the response text, or None if every entry failed/was
    unconfigured — callers fall through to the Groq chain in that case.
    """
    from openai import OpenAI

    for model, key_env, can_disable_reasoning in OPENROUTER_CHAIN:
        key = os.getenv(key_env, "").strip()
        if not key:
            continue
        try:
            # timeout=15: a free-tier provider queued behind other users can
            # hang far longer than it's worth waiting — better to fail fast
            # and let the next model in the chain pick it up.
            client = OpenAI(api_key=key, base_url=OPENROUTER_BASE_URL, max_retries=0, timeout=15.0)
            kwargs = {"model": model, "messages": messages}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            # Reasoning models (e.g. Nemotron) otherwise spend the entire
            # token budget on invisible "thinking" and return an empty or
            # truncated answer. Some models (e.g. gpt-oss-20b) instead REJECT
            # an explicit reasoning:false with a 400 ("reasoning is mandatory
            # for this endpoint") — for those we omit the param entirely
            # rather than force it, accepting their normal (slower) behavior.
            if can_disable_reasoning:
                kwargs["extra_body"] = {"reasoning": {"enabled": False}}
            completion = client.chat.completions.create(**kwargs)
            choice = completion.choices[0]
            text = choice.message.content
            # A response cut off by the token budget is usually invalid/
            # truncated JSON — treat it as a failure of this model rather
            # than returning garbage the caller's JSON parser will choke on.
            if choice.finish_reason == "length":
                print(f"[groq_chat] OpenRouter {model} truncated (finish_reason=length); trying next...")
                continue
            if text and text.strip():
                if model != OPENROUTER_CHAIN[0][0]:
                    print(f"[groq_chat] served by OpenRouter fallback model {model}")
                return text
        except Exception as e:
            print(f"[groq_chat] OpenRouter {model} failed ({str(e)[:160]}); trying next...")
            continue
    return None


def groq_chat(messages, temperature=None, max_tokens=None, api_key=None):
    """
    Run a chat completion. Tries the free OpenRouter chain first (three models,
    each on its own key/quota), then falls back to the Groq MODEL_CHAIN below.
    Returns the response text. Raises the LAST error only if every model fails.
    """
    or_text = _try_openrouter(messages, temperature, max_tokens)
    if or_text is not None:
        return or_text

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
        # Groq is reached only after the whole OpenRouter chain has already
        # failed, and a mock-data fallback exists above this — so fail FAST
        # here rather than waiting out rate limits. One short retry for a
        # genuine network blip only; a rate limit or anything else moves
        # straight to the next model/gives up. (Previously this waited up to
        # 60s x 3 attempts x 2 models — up to 6 minutes of pure sleep(), which
        # is what made a hung request look like it was stuck for 8 minutes.)
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                completion = client.chat.completions.create(**kwargs, timeout=15.0)
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
                print(f"[groq_chat] {model} failed ({str(e)[:160]}); trying next model...")
                break
    if last_err is not None:
        summary = " | ".join(f"{m}: {e}" for m, e in errors_by_model.items())
        raise RuntimeError(f"All models in chain failed. {summary}") from last_err
    raise last_err
