"""
"Ask Navrist" — the conversational assistant behind the floating chat widget.

Uses the Groq client with a TOOL-CALLING loop so the model can fetch REAL data
(live stock quotes) at query time instead of hallucinating prices. A raw LLM has
no market access — asked "price of Tata Steel" it can only wave you at NSE/BSE.
Here the model instead calls `get_stock_quote`, we run the app's own live-quote
scraper, hand back the actual LTP, and the model answers with the real number.

Inherits the same 70b -> 8b rate-limit fallback every other AI feature relies on
(both models support tool calling on Groq).

Two other behaviours:
  1. Company awareness — the frontend passes a compact `context` blob for the
     company on screen, folded into the system prompt.
  2. Chart protocol — the model MAY emit a ```chart JSON block; the frontend
     renders it as a real graph. Everything else is plain markdown.
"""

import json
import os

from tools.groq_client import MODEL_CHAIN, _fit_messages

SYSTEM_PROMPT = """You are "Ask Navrist" — a senior equity research analyst embedded inside the Navrist research terminal. You have institutional-grade depth on Indian markets, accounting, valuation and financial ratios — you are not a generic assistant bolting on a finance flavour, you ARE the domain expert.

CORE RULE — ANSWER THE ACTUAL QUESTION:
- Before answering, identify precisely what is being asked (a number? a comparison? a mechanism? a judgement?) and answer THAT, directly, first line.
- Never pad a specific question with generic textbook filler ("financial health can be assessed by looking at several factors..."). If asked "is its ROE good", state the ROE, the benchmark you're comparing it to, and a direct verdict — not a lecture on what ROE is unless asked to explain the concept.
- Never answer with a non-answer. "It depends" / "consult a professional" / "do your own research" / "you should study the fundamentals" are BANNED as a substitute for analysis. You have the data (via context or tools) — use it and commit to a reasoned, specific answer.
- For direct buy/sell/hold calls: give your actual reasoned view (bullish/neutral/bearish, and why, with the specific metrics driving that view) — do not refuse or deflect. End with a brief, natural one-liner in your own words that this is your analysis, not a personal recommendation (vary the phrasing, don't repeat a stock disclaimer sentence verbatim every time). Skip this line entirely on factual, ratio, or explanatory questions — it belongs only on an actual directional call.

COMPANY CONTEXT — USE IT, DON'T GUESS:
- When a company is loaded, the context block below contains the REAL computed data for it: every ratio Navrist has calculated, multi-year revenue/profit trends, peer and sector-percentile standing, and qualitative commentary. This is ground truth, not a hint.
- If the user asks for a specific ratio (e.g. "interest coverage ratio", "current ratio", "ROCE") and it appears in the context's ratio list, quote that exact figure. Do not explain the concept instead of giving the number, and do not say you don't have it if it's listed.
- If a ratio/figure genuinely is NOT in the context, say plainly that Navrist hasn't computed it for this company yet — don't fabricate a plausible-looking number.
- For "how does it compare to peers/sector" questions, use the peer/sector comparison lines in the context (percentiles, medians, named peers) rather than a generic "it depends on the sector" answer.

NEVER FABRICATE NEWS, CONTRACTS, DEALS OR EVENTS — THIS IS YOUR MOST IMPORTANT RULE:
- You have NO feed of recent news, orders, contract wins, management guidance quotes, or corporate announcements unless such a fact is explicitly present in the context block or conversation. You do NOT know what LT (or any company) actually announced last week, last quarter, or ever, beyond widely-known public history you are highly confident about.
- Do NOT invent specific contract values, order sizes, partnership names, project names, or guidance statements to make a "bull case" or "bear case" sound concrete. A precise-sounding number you are not actually certain of (e.g. "a Rs 1,200 cr order for a 600 MW project") is a fabrication even if it sounds plausible — and fabricated deal facts in a financial context are a severe failure, worse than giving a shorter, honest answer.
- When asked to build a bull/bear case, base it ONLY on what's in the context (ratios, margins, growth, debt levels, peer standing, business/moat commentary if present) and clearly qualify anything you're not certain of as general/sector-level reasoning, not a company-specific claimed fact. If the user wants recent news/order-book detail and you don't have it, say plainly that Navrist doesn't have live news/deal-flow data loaded for this company — do not paper over the gap with invented specifics.

REAL-TIME DATA:
- You have a live market-data tool, `get_stock_quote`. Whenever the user asks about a stock's current/live/latest price, quote, day range, or how it's trading, call it and answer from the returned value. Never say you lack real-time access, never guess a price.
- Report the number plainly (last price, change, %, day range). Do NOT append boilerplate about data delays or "check the NSE website" — state the figure as fact, once, with the source named only if the user asks where it's from or the data is stale/estimated.
- If the tool says data is unavailable, say so in one line and stop — don't pad it with disclaimers.

COMPANY NAME — NEVER GUESS FROM AN NSE TICKER:
- Thousands of NSE tickers are thinly-traded, renamed, or obscure, and your training data on which ticker maps to which company is frequently WRONG (e.g. you might associate "MWL" with an unrelated company from memory when it actually maps to a completely different, real NSE-listed company).
- If a `company_name` is supplied — either in the tool result or in the company context block — use that exact name and nothing else. Never substitute a name you recall from training.
- If you are not given a company_name for a ticker (tool returned none, no context loaded), do NOT state a company name at all. Refer to it by its ticker only, and say the full name isn't confirmed — do not fill the gap with a guess. Getting a company's identity wrong is a critical failure, worse than not answering.

STYLE:
- Lead with the answer in the first sentence. Then, only if useful, a short "why" with the specific numbers behind it.
- Markdown when it clarifies (bold key figures, tables for comparisons, bullets for lists) — never markdown for its own sake on a one-line answer.
- Show the actual calculation when a number is derived, not just the result.
- No sign-off disclaimers on ordinary analytical/factual answers. Only the "not personalised advice" line for direct buy/sell/hold recommendation questions, and only once, at the end, one line.

CHARTS:
When a trend or comparison would be clearer as a graph, emit a fenced code block tagged `chart` containing ONLY compact JSON of this exact shape:
```chart
{"type":"bar","title":"Revenue (Cr)","x_label":"Year","y_label":"Rs Cr","series":[{"name":"Revenue","points":[{"x":"FY22","y":965},{"x":"FY23","y":1024}]}]}
```
Chart rules: `type` is "bar" or "line" only; use only real numbers you have (from a tool, the company context, or the conversation) — never invent precise figures; a sentence of explanation before/after the block is fine."""

# Tool the model can call. The actual implementation is injected by the caller
# (app.py owns the live scraper + symbol registry), so this module stays free of
# scraper/registry coupling and remains unit-testable.
QUOTE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_stock_quote",
        "description": (
            "Get the REAL-TIME last traded price (LTP), previous close, absolute and "
            "percent change, and day high/low for an Indian NSE-listed stock, PLUS the "
            "verbatim registry company_name for that ticker. Call this whenever the user "
            "asks about a company's current/live/latest price, quote, or how it is trading "
            "right now, or whenever you need to confirm which company an unfamiliar/short "
            "ticker actually refers to — company_name is authoritative, your own training "
            "data on obscure NSE tickers is not."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE ticker or company name, e.g. 'TATASTEEL', 'Tata Steel', 'RELIANCE', 'Infosys'.",
                }
            },
            "required": ["symbol"],
        },
    },
}


def _context_block(context: str) -> str:
    context = (context or "").strip()
    if not context:
        return ""
    # The frontend now sends the FULL computed picture for the company on screen
    # (every ratio, multi-year statement trend, peer/sector percentiles,
    # qualitative commentary) instead of a 10-line summary, so "what's its X
    # ratio" or "how does it compare to peers" has real data to answer from.
    # 24k chars (~6k tokens) comfortably fits the 70b model's context window
    # alongside the system prompt and conversation history.
    if len(context) > 24000:
        context = context[:24000] + "\n...[context truncated]..."
    return (
        "\n\nThe user currently has this company loaded on screen. Use it to answer "
        'company-specific questions ("it", "this company", "its margins"):\n'
        "----- COMPANY CONTEXT -----\n" + context + "\n----- END CONTEXT -----"
    )


def _create_completion(client, model, messages, tools_spec, temperature, max_tokens):
    """One Groq call. Tools passed only when available."""
    kwargs = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if tools_spec:
        kwargs["tools"] = tools_spec
        kwargs["tool_choice"] = "auto"
    return client.chat.completions.create(**kwargs)


def _call_model(client, messages, tools_spec, temperature, max_tokens):
    """Try each model in the fallback chain until one answers; return its message."""
    last_err = None
    for model, budget, tok_cap in MODEL_CHAIN:
        mt = max_tokens
        if tok_cap is not None:
            mt = min(mt, tok_cap) if mt else tok_cap
        try:
            completion = _create_completion(
                client, model, _fit_messages(messages, budget), tools_spec, temperature, mt
            )
            if model != MODEL_CHAIN[0][0]:
                print(f"[ask_navrist] served by fallback model {model}")
            return completion.choices[0].message
        except Exception as e:
            last_err = e
            print(f"[ask_navrist] {model} failed ({str(e)[:140]}); trying next model...")
            continue
    raise last_err


def ask_navrist(messages, context: str = "", api_key: str = None, tools: dict = None) -> dict:
    """
    messages: list of {"role": "user"|"assistant", "content": str} — prior turns.
    context : optional compact string describing the company on screen.
    tools   : optional {"get_stock_quote": callable(args_dict) -> dict} injected by
              the caller so the model can fetch real live data.
    Returns {"reply": str} (plus {"error": True} on failure).
    """
    convo = [
        m for m in (messages or [])
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    if not convo:
        return {"reply": "Ask me anything about a company, a ratio, or how Navrist works."}
    convo = convo[-16:]  # bounded history

    system = SYSTEM_PROMPT + _context_block(context)
    payload = [{"role": "system", "content": system}] + convo

    tools = tools or {}
    tools_spec = [QUOTE_TOOL_SCHEMA] if "get_stock_quote" in tools else None

    key = (api_key or os.getenv("GROQ_API_KEY", "")).strip()
    if not key or key == "your_api_key_here":
        return {"reply": "The AI model isn't configured (missing GROQ_API_KEY).", "error": True}

    try:
        from groq import Groq
        # max_retries=0: the Groq SDK's default is to retry a failing call itself
        # (with backoff) BEFORE raising — so on a 429 from the primary 70b model,
        # every single call was silently burning ~15-30s in the SDK's own retry
        # loop before our MODEL_CHAIN fallback ever got a chance to try the 8b
        # model. That hidden delay, multiplied across the 2+ calls in the tool
        # loop, was the actual root cause of multi-minute replies whenever the
        # 70b model was rate-limited (very common on the free tier under load).
        # We already have our own fallback chain, so let 429/5xx fail immediately.
        client = Groq(api_key=key, max_retries=0)

        # Tool-calling loop: allow a few round-trips so the model can call
        # get_stock_quote, read the result, then compose its answer.
        for _ in range(4):
            msg = _call_model(client, payload, tools_spec, temperature=0.4, max_tokens=1400)
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return {"reply": (msg.content or "").strip() or "I couldn't generate a response — please try rephrasing."}

            # Record the assistant's tool-call turn, then each tool result.
            payload.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                fn = tools.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                try:
                    result = fn(args) if fn else {"error": f"Unknown tool {tc.function.name}"}
                except Exception as e:
                    result = {"error": f"Tool failed: {e}"}
                payload.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                })

        # Ran out of tool round-trips — make one final no-tools call for prose.
        msg = _call_model(client, payload, None, temperature=0.4, max_tokens=1400)
        return {"reply": (msg.content or "").strip() or "I couldn't complete that request."}

    except Exception as e:
        print(f"[ask_navrist] failed: {e}")
        return {
            "reply": "I'm having trouble reaching the model right now (it may be rate-limited). Please try again in a moment.",
            "error": True,
        }
