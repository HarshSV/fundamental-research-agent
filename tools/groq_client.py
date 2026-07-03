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

# (model, approx input char budget, completion-token cap). ~4 chars/token; the
# 8b model's 6k TPM cap counts input + requested completion tokens, so trim the
# input to ~2.2k tokens (9k chars) and cap the completion at 2k.
MODEL_CHAIN = [
    ("llama-3.3-70b-versatile", None, None),
    ("llama-3.1-8b-instant", 9000, 2000),
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
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        t = t[i:j + 1]
    try:
        return json.loads(t)
    except Exception:
        pass
    t2 = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', t)   # escape stray backslashes
    t2 = re.sub(r",\s*([}\]])", r"\1", t2)            # drop trailing commas
    return json.loads(t2)


def groq_chat(messages, temperature=None, max_tokens=None, api_key=None):
    """
    Run a chat completion, trying each model in MODEL_CHAIN until one succeeds.
    Returns the response text. Raises the LAST error only if every model fails.
    """
    from groq import Groq

    key = (api_key or os.getenv("GROQ_API_KEY", "")).strip()
    if not key or key == "your_api_key_here":
        raise RuntimeError("GROQ_API_KEY not configured")

    client = Groq(api_key=key)
    last_err = None
    for model, budget, tok_cap in MODEL_CHAIN:
        try:
            kwargs = {"model": model, "messages": _fit_messages(messages, budget)}
            if temperature is not None:
                kwargs["temperature"] = temperature
            mt = max_tokens
            if tok_cap is not None:
                mt = min(mt, tok_cap) if mt else tok_cap
            if mt is not None:
                kwargs["max_tokens"] = mt
            completion = client.chat.completions.create(**kwargs)
            text = completion.choices[0].message.content
            if model != MODEL_CHAIN[0][0]:
                print(f"[groq_chat] served by fallback model {model}")
            return text
        except Exception as e:
            print(f"[groq_chat] {model} failed ({str(e)[:160]}); trying next model...")
            last_err = e
    raise last_err
