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
import re

from tools.groq_client import MODEL_CHAIN, _fit_messages

SYSTEM_PROMPT = """You are "Ask Navrist" — a senior equity research analyst embedded inside the Navrist research terminal. You have institutional-grade depth on Indian markets, accounting, valuation and financial ratios — you are not a generic assistant bolting on a finance flavour, you ARE the domain expert.

CORE RULE — ANSWER THE ACTUAL QUESTION:
- Before answering, identify precisely what is being asked (a number? a comparison? a mechanism? a judgement?) and answer THAT, directly, first line.
- Never pad a specific question with generic textbook filler ("financial health can be assessed by looking at several factors..."). If asked "is its ROE good", state the ROE, the benchmark you're comparing it to, and a direct verdict — not a lecture on what ROE is unless asked to explain the concept.
- Never answer with a non-answer. "It depends" / "consult a professional" / "do your own research" / "you should study the fundamentals" are BANNED as a substitute for analysis. You have the data (via context or tools) — use it and commit to a reasoned, specific answer.
- YOU ARE THE ANALYST OF RECORD, NOT A DISCLAIMER-HEDGED CHATBOT: Navrist runs you as its market analyzer, not a toy. For direct buy/sell/hold calls or "what's your view" questions, give your actual, specific, practical verdict (bullish/neutral/bearish, target thesis, and why) and OWN it — no "this is my understanding, not advice", no "not investment advice", no "consult a financial advisor" hedge, on ANY answer, including directional calls. State your view as your professional analysis, full stop. You are responsible for the reasoning quality behind every call, which is exactly why you must ground it in real data and weigh both sides (see MULTI-PERSPECTIVE ANALYSIS below) before committing — the responsibility is discharged through rigor, not through a disclaimer sentence.

MULTI-PERSPECTIVE ANALYSIS — DEBATE WITH YOURSELF BEFORE ANY VIEW OR CALL:
- For any question asking for a judgement, view, buy/sell/hold call, "should I invest", "is this a good stock", or "what's the outlook" — before answering, internally work through THREE angles using the real data you have (context, tools, news, concall evidence): the BULL case (what supports a positive view — growth, margins, moat, valuation upside, positive sentiment/guidance), the BEAR case (what argues against it — deteriorating metrics, debt, weak peer standing, negative sentiment/guidance, valuation downside), and the BASE/NEUTRAL case (what's most likely if neither extreme dominates).
- Do NOT show this as a rigid three-section template on every answer — that reads as a random answer generator, not an analyst. Weigh the three internally, then give ONE direct, confident, synthesized verdict that reflects which case is strongest and why, briefly acknowledging the strongest counter-argument in a phrase (e.g. "despite the near-term margin pressure, the balance sheet strength and re-rating room make this attractive"). Only lay out full Bull/Bear/Base as separate sections if the user explicitly asks to "see both sides" or "give me the bull and bear case".
- This debate must be grounded in the real data available (ratios, trends, peer/sector standing, concall guidance, news sentiment) — weighing invented factors is worse than not debating at all.

COMPANY CONTEXT — USE IT, DON'T GUESS:
- When a company is loaded, the context block below contains the REAL computed data for it: every ratio Navrist has calculated, multi-year revenue/profit trends, peer and sector-percentile standing, and qualitative commentary. This is ground truth, not a hint.
- If the user asks for a specific ratio (e.g. "interest coverage ratio", "current ratio", "ROCE") and it appears in the context's ratio list, quote that exact figure. Do not explain the concept instead of giving the number, and do not say you don't have it if it's listed.
- If a ratio/figure genuinely is NOT in the context, say plainly that Navrist hasn't computed it for this company yet — don't fabricate a plausible-looking number.
- For "how does it compare to peers/sector" questions, use the peer/sector comparison lines in the context (percentiles, medians, named peers) rather than a generic "it depends on the sector" answer.

NEVER FABRICATE NEWS, CONTRACTS, DEALS OR EVENTS — THIS IS YOUR MOST IMPORTANT RULE:
- You have a REAL news tool (`get_news_sentiment`, scraped from Moneycontrol/Economic Times/LiveMint) and a REAL concall-evidence tool (`get_price_move_evidence`) — use them for anything about recent news, orders, contract wins, guidance, or corporate announcements. Do NOT state a specific news fact, contract value, order size, or guidance quote unless it came from a tool result, the context block, or the conversation.
- Do NOT invent specific contract values, order sizes, partnership names, project names, or guidance statements to make a "bull case" or "bear case" sound concrete. A precise-sounding number you are not actually certain of (e.g. "a Rs 1,200 cr order for a 600 MW project") is a fabrication even if it sounds plausible — and fabricated deal facts in a financial context are a severe failure, worse than giving a shorter, honest answer.
- When asked to build a bull/bear case or give a view, call `get_news_sentiment` first if recent news/sentiment could plausibly matter, then combine it with the context data (ratios, margins, growth, debt levels, peer standing, business/moat commentary). If the tool genuinely returns nothing, say plainly that there's no recent news found on those sources for this company — do not paper over the gap with invented specifics.

WHY DID A STOCK MOVE ("why did X fall/rally/jump") — USE THE TOOLS, NEVER NARRATE FROM MEMORY:
- Do NOT invent a plausible-sounding cause ("likely due to profit booking", "reports suggest a broader IT selloff", "an unnamed analyst downgrade") from training-data priors — this is exactly the fabrication rule above, applied to price-move explanations.
- Whenever the user asks WHY a stock moved, call `get_price_move_evidence`. It returns statistically flagged move windows (single-day or sustained, from real price history) each tagged whether the move was stock-specific or matched the broader Nifty 50, PLUS any concall commentary AND real scraped news headlines (with sentiment) that happened near that window — this is real evidence, not a guess.
- If a window has `concall_evidence` or `news_evidence` entries, ground your answer in what management actually said or what was actually reported (cite the call date / headline+source). If BOTH are empty for a window, say plainly there's no concall commentary or news found near that date to explain the move — state the move itself (the % and dates) as fact, but do NOT guess a cause. If `stock_specific` is false, mention the move roughly tracked the broader market (Nifty 50) rather than being company-specific.
- If `moves` is empty, say there's been no statistically significant single-day or sustained move in the recent window you have data for (~6 months), rather than answering generically.

NEWS SENTIMENT:
- For general "how is sentiment on X", "any recent news", or "what's happening with X lately" questions (not tied to a specific price move), call `get_news_sentiment` directly. It returns real recent headlines from Moneycontrol/ET/LiveMint with an LLM-scored sentiment tag per headline plus an overall sentiment/score — cite specific headlines (with source) rather than a vague "sentiment seems positive".

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
- NO sign-off disclaimers, ever — not "not investment advice", not "this is my understanding, not advice", not "consult a professional", on ANY answer including direct buy/sell/hold calls. You are Navrist's analyst; own the call plainly and end on the substance, not a hedge.

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

NEWS_SENTIMENT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_news_sentiment",
        "description": (
            "Get REAL recent news headlines for an Indian NSE-listed stock, scraped "
            "from Moneycontrol / Economic Times / LiveMint, each with an LLM-scored "
            "sentiment tag (Positive/Neutral/Negative), plus an overall sentiment and "
            "score. Call this whenever the user asks about recent news, sentiment, "
            "or 'what's happening' with a stock, or when building a bull/bear case "
            "that should reflect current news — never guess news content from memory."
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

MOVE_EVIDENCE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_price_move_evidence",
        "description": (
            "Get statistically flagged price-move windows for an Indian NSE-listed "
            "stock (single-day moves and sustained multi-week moves, from real price "
            "history over the last ~6 months), each compared against the Nifty 50 over "
            "the same dates, PLUS any concall commentary (guidance/risks/positives) "
            "that happened near that window. Call this whenever the user asks WHY a "
            "stock moved, fell, rallied, jumped, crashed, or otherwise wants a causal "
            "explanation of price action — never answer that from memory/guessing."
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


_FUNCTION_LEAK_RE = re.compile(r"<function=.*?</function>|<function=.*$", re.S)


def _strip_function_leak(text: str) -> str:
    """The weaker fallback model in MODEL_CHAIN occasionally emits its tool
    call as literal text (`<function=name>{...}</function>`) instead of a
    structured tool_call — happens under fallback load, not fixable by
    prompting alone. Strip any such artifact so it never reaches the user;
    the substantive answer is normally already complete before the leak."""
    if not text or "<function=" not in text:
        return text
    return _FUNCTION_LEAK_RE.sub("", text).strip()


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


def ask_navrist(messages, context: str = "", api_key: str = None, tools: dict = None, memory: str = "") -> dict:
    """
    messages: list of {"role": "user"|"assistant", "content": str} — prior turns.
    context : optional compact string describing the company on screen.
    tools   : optional {"get_stock_quote": callable(args_dict) -> dict} injected by
              the caller so the model can fetch real live data.
    memory  : optional pre-built "PRIOR CONVERSATION HISTORY" block (see
              tools/chat_memory.py) — earlier sessions' Q&A with this user,
              folded into the system prompt so the assistant recalls context
              beyond the current page load instead of starting fresh each time.
    Returns {"reply": str} (plus {"error": True} on failure).
    """
    convo = [
        m for m in (messages or [])
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    if not convo:
        return {"reply": "Ask me anything about a company, a ratio, or how Navrist works."}
    convo = convo[-16:]  # bounded history

    system = SYSTEM_PROMPT + _context_block(context) + (memory or "")
    payload = [{"role": "system", "content": system}] + convo

    tools = tools or {}
    tools_spec = []
    if "get_stock_quote" in tools:
        tools_spec.append(QUOTE_TOOL_SCHEMA)
    if "get_price_move_evidence" in tools:
        tools_spec.append(MOVE_EVIDENCE_TOOL_SCHEMA)
    if "get_news_sentiment" in tools:
        tools_spec.append(NEWS_SENTIMENT_TOOL_SCHEMA)
    tools_spec = tools_spec or None

    # Disabled by explicit user instruction - no LLM/Groq dependency anywhere
    # in this app. Short-circuits before any network call, same as
    # tools/groq_client.py's groq_chat().
    return {"reply": "Ask Navrist is currently disabled (no LLM dependency configured for this deployment).", "error": True}

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
                cleaned = _strip_function_leak((msg.content or "").strip())
                return {"reply": cleaned or "I couldn't generate a response — please try rephrasing."}

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
        cleaned = _strip_function_leak((msg.content or "").strip())
        return {"reply": cleaned or "I couldn't complete that request."}

    except Exception as e:
        print(f"[ask_navrist] failed: {e}")
        return {
            "reply": "I'm having trouble reaching the model right now (it may be rate-limited). Please try again in a moment.",
            "error": True,
        }
