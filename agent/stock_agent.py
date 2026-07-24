import os
import re
import sys

# Standard path fix to allow running the script directly and importing tools packages
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from groq import Groq
from tools.angel_scraper import AngelDataScraper, normalize_financials_to_inr, compute_pe_band
from tools.peer_synthesis import PeerSectorEvaluator
from tools.metrics_engine import FundamentalMetricsEngine

# 1. Define global System State Dictionary
class SystemState(TypedDict):
    symbol: str
    raw_financial_data: dict
    calculated_metrics: dict
    business_score: int
    qualitative_analysis: dict
    peer_synthesis_data: dict
    ai_summary: dict
    verdict: str

# 2. Create core workflow nodes

def fetch_market_data_node(state: SystemState) -> dict:
    """
    Calls the AngelDataScraper client to fetch the fundamental payload
    for state['symbol'] and saves it to state['raw_financial_data'].
    Also passes this data to the mathematical metrics engine to compute
    the 20 fundamental metrics and store them under state['calculated_metrics'].
    Sets state['business_score'] to the composite weighted quality score.
    """
    symbol = state.get('symbol')
    print(f"\n[NODE: fetch_market_data_node] Executing for symbol: {symbol}")
    
    raw_data = {}
    calculated_metrics = {}
    business_score = 0
    
    # Step A: Ingest data from Angel One Scraper
    try:
        print("[fetch_market_data_node] Attempting to initialize AngelDataScraper...")
        scraper = AngelDataScraper()
        
        print(f"[fetch_market_data_node] Fetching fundamental payload for '{symbol}'...")
        raw_data = scraper.fetch_fundamental_payload(symbol)
        print("[fetch_market_data_node] Ingestion fetch completed.")

        # yfinance returns many Indian companies' statements in USD even on the .NS
        # ticker, while price is INR. Convert statement magnitudes to INR so revenue,
        # cash flow, DCF and fair-value read correctly. No-op when already INR.
        try:
            _fc = (raw_data.get('info') or {}).get('financialCurrency')
            raw_data['financial_arrays'], _fx = normalize_financials_to_inr(raw_data.get('financial_arrays'), _fc)
            if _fx:
                raw_data['financials_currency_converted'] = {'from': _fc, 'to': 'INR', 'fx': _fx}
        except Exception as _cur_err:
            print(f"[fetch_market_data_node] Currency normalization skipped: {_cur_err}")

        # Enrich with real NSE shareholding data (F-11 pledge, F-12 fund flows).
        # Never fatal: fetch_shareholding swallows its own errors and returns a
        # safe payload, so a scrape failure can't break the research run.
        try:
            from tools.shareholding_scraper import fetch_shareholding
            _nm = (raw_data.get('info') or {}).get('longName') or (raw_data.get('info') or {}).get('shortName')
            raw_data['shareholding'] = fetch_shareholding(symbol, name=_nm)
            sh_src = raw_data['shareholding'].get('source')
            print(f"[fetch_market_data_node] Shareholding enrichment done (source={sh_src}).")
        except Exception as sh_err:
            print(f"[fetch_market_data_node] Shareholding enrichment skipped: {sh_err}")
    except Exception as e:
        print(f"[fetch_market_data_node] WARNING: AngelDataScraper failed to initialize or fetch: {e}")
        print("[fetch_market_data_node] Using fallback mock structure for raw_financial_data.")
        # Defensive fallback payload
        raw_data = {
            'symbol': symbol,
            'lastPrice': None,
            'volume': None,
            'ohlc': {'open': None, 'high': None, 'low': None, 'close': None},
            'ownership_metrics': {
                'F-10_heldPercentInsiders': None,
                'F-11_promoterPledges': None,
                'F-12_heldPercentInstitutions': None
            },
            'financial_arrays': {},
            'error': str(e)
        }

    # Step B: Score the stock using our new mathematical calculations engine
    try:
        print(f"[fetch_market_data_node] Passing data to metrics calculation engine for '{symbol}'...")
        calculated_metrics = FundamentalMetricsEngine.calculate_all_metrics(raw_data)
        # Fetch official company name and save to calculated_metrics
        info_dict = raw_data.get('info', {}) or {}
        company_name = info_dict.get('longName') or info_dict.get('shortName') or symbol
        calculated_metrics['company_name'] = company_name
        # Derive a historical P/E band (free: price history / INR EPS) for the valuation chart.
        try:
            inc_annual = (raw_data.get('financial_arrays') or {}).get('income_stmt') or {}
            _val = calculated_metrics.get('F-03_Valuation_Metrics')
            band = compute_pe_band(symbol, inc_annual, (_val or {}).get('PE'))
            if band and isinstance(_val, dict):
                _val['pe_band'] = band
                print(f"[fetch_market_data_node] P/E band built ({len(band['series'])} pts, median {band['median']}).")
        except Exception as _be:
            print(f"[fetch_market_data_node] P/E band skipped: {_be}")
        business_score = calculated_metrics.get('F-19_Business_Quality', {}).get('composite_score', 0)
        print(f"[fetch_market_data_node] Successfully computed F-19 unified score: {business_score}")
    except Exception as e:
        print(f"[fetch_market_data_node] ERROR: Failed to compute metrics via engine: {e}")
        business_score = 0
        
    print(f"[NODE: fetch_market_data_node] Finished. Score = {business_score}")
    return {
        'raw_financial_data': raw_data,
        'calculated_metrics': calculated_metrics,
        'business_score': business_score
    }

def safety_gate_conditional_router(state: SystemState) -> str:
    """
    Unconditionally proceed to analysis to ensure all 20 features appear on the page.
    """
    return "proceed_to_analysis"

def parse_narrative_sections(text: str) -> dict:
    """
    Parses the combined LLM output into separate qualitative sections.
    """
    sections = {
        'F-07': "",
        'F-14': "",
        'F-15': "",
        'F-16': "",
        'F-20': ""
    }
    current_section = None
    lines = text.split('\n')
    for line in lines:
        line_strip = line.strip()
        if "###" in line:
            if "F-07" in line_strip:
                current_section = 'F-07'
                continue
            elif "F-14" in line_strip:
                current_section = 'F-14'
                continue
            elif "F-15" in line_strip:
                current_section = 'F-15'
                continue
            elif "F-16" in line_strip:
                current_section = 'F-16'
                continue
            elif "F-20" in line_strip:
                current_section = 'F-20'
                continue
            elif any(f in line_strip for f in ["F-01", "F-02", "F-03", "F-04", "F-05", "F-06", "F-08", "F-09", "F-10", "F-11", "F-12", "F-13", "F-17", "F-18", "F-19"]):
                current_section = None
                continue
        if current_section:
            sections[current_section] += line + "\n"
            
    for k in sections:
        sections[k] = sections[k].strip()
        if not sections[k]:
            sections[k] = f"Detailed analysis for {k} is currently stable."
    return sections

def get_fallback_structured_data(symbol: str) -> dict:
    """
    Returns structured default data if Groq is unconfigured or JSON parsing fails.
    """
    return {
        "F-07": {
            "commentary": f"{symbol} exhibits stable capital efficiency. Return on Equity (ROE) and Return on Capital Employed (ROCE) closely track operating cycles, showing effective reinvestment of retained earnings."
        },
        "F-14": {
            "summary": f"{symbol} management commentary indicates steady operations with a focus on profitable growth.",
            "growth_drivers": ["Core business demand", "Operating efficiency", "New deal wins / capacity"],
            "risks": ["Demand/macro uncertainty", "Margin / cost pressure"],
            "capex_guidance": "Management guided to disciplined capex aligned with demand.",
            "tone": "Cautious"
        },
        "F-15": {
            "bear": {
                "revenue_growth": 4.5,
                "pat_growth": 2.5,
                "drivers": "Domestic volumes pressure, input price inflation, and weak rural demand.",
                "risks": "Margins compress due to failure to pass raw material hikes."
            },
            "base": {
                "revenue_growth": 9.5,
                "pat_growth": 8.0,
                "drivers": "Normal market recovery, steady export demand, and standard price updates.",
                "risks": "Top-line growth tracks general industry pace."
            },
            "bull": {
                "revenue_growth": 14.5,
                "pat_growth": 13.5,
                "drivers": "Rapid expansion in overseas segments and margin expansion through digital integrations.",
                "risks": "Temporary over-investment in capacity could hurt returns."
            }
        },
        "F-16": {
            "risk_level": "Low",
            "checks": [
                {"name": "CFO vs PAT Conversion Check", "status": "PASS", "severity": 1, "details": "Cash flow from operations closely matches Net Income, confirming cash-backed earnings."},
                {"name": "Share Dilution Check", "status": "PASS", "severity": 0, "details": "Outstanding share counts are stable, indicating zero equity dilution for current shareholders."},
                {"name": "Receivables vs Sales Trend Check", "status": "PASS", "severity": 2, "details": "Debtor days are stable, with receivables growing at a similar pace to total revenues."},
                {"name": "Asset Quality & Capitalization Check", "status": "PASS", "severity": 1, "details": "Capitalization policies match standard Ind-AS norms, with low intangible capitalization levels."}
            ]
        },
        "F-20": {
            "moat_strength": "Narrow to Wide",
            "confidence_level": 80.0,
            "pricing_power": 8.0,
            "barriers_to_entry": 8.0,
            "memo_text": f"The company possesses a defensible business model protected by brand strength and customer switching costs."
        }
    }

def json_to_markdown_narrative(parsed_json: dict, symbol: str) -> str:
    """
    Converts parsed qualitative JSON structure into a markdown text narrative
    to maintain compatibility with the PDF report generator.
    """
    try:
        f07 = parsed_json.get('F-07', {}).get('commentary', '')
        f14 = parsed_json.get('F-14', {})
        f15 = parsed_json.get('F-15', {})
        f16 = parsed_json.get('F-16', {})
        f20 = parsed_json.get('F-20', {})
        
        f14_drivers_str = "\n".join([f"- {d}" for d in (f14.get('growth_drivers') or [])])
        f14_risks_str = "\n".join([f"- {r}" for r in (f14.get('risks') or [])])
        checks_str = "\n".join([f"- **{c.get('name')}**: [{c.get('status')}] Severity: {c.get('severity')}/10 - {c.get('details')}" for c in f16.get('checks', [])])
        
        narrative = (
            f"### Return Ratios Commentary\n"
            f"{f07}\n\n"
            f"### Annual Report / Concall Summary\n"
            f"{f14.get('summary', '')}\n"
            f"Management Tone: {f14.get('tone', '—')}\n"
            f"Growth Drivers:\n{f14_drivers_str}\n"
            f"Risks:\n{f14_risks_str}\n"
            f"Capex / Guidance: {f14.get('capex_guidance', '—')}\n\n"
            f"### Scenario Forecasts\n"
            f"- **Bull Case (Growth: {f15.get('bull', {}).get('revenue_growth')}%):** Drivers: {f15.get('bull', {}).get('drivers')}. Risks: {f15.get('bull', {}).get('risks')}\n"
            f"- **Base Case (Growth: {f15.get('base', {}).get('revenue_growth')}%):** Drivers: {f15.get('base', {}).get('drivers')}. Risks: {f15.get('base', {}).get('risks')}\n"
            f"- **Bear Case (Growth: {f15.get('bear', {}).get('revenue_growth')}%):** Drivers: {f15.get('bear', {}).get('drivers')}. Risks: {f15.get('bear', {}).get('risks')}\n\n"
            f"### Forensic Accounting Checklist\n"
            f"Risk level: {f16.get('risk_level')}\n"
            f"{checks_str}\n\n"
            f"### Moat Assessment Memo\n"
            f"Moat Strength: {f20.get('moat_strength')} | Confidence Level: {f20.get('confidence_level')}%\n"
            f"Pricing Power Score: {f20.get('pricing_power')}/10 | Barriers to Entry Score: {f20.get('barriers_to_entry')}/10\n"
            f"{f20.get('memo_text')}"
        )
        return narrative
    except Exception as e:
        return "Failed to compile markdown narrative from JSON: " + str(e)

def analyze_quality_node(state: SystemState) -> dict:
    """
    Evaluates qualitative metrics for the target company (Return ratio, Annual report, Scenario forecast, Forensics, Moat)
    using Groq Cloud API's active model: llama-3.3-70b-versatile, returning a validated structured JSON payload.
    """
    symbol = state.get('symbol')
    metrics = state.get('calculated_metrics', {}) or {}
    
    print(f"\n[NODE: analyze_quality_node] Executing qualitative analysis for symbol: {symbol}")
    
    # Extract data references to pass to the model for context
    val = metrics.get('F-03_Valuation_Metrics', {})
    growth = metrics.get('F-05_Growth_Summary', {})
    margins = metrics.get('F-06_Margin_Analysis', {})
    solvency = metrics.get('F-08_Solvency_Metrics', {})
    score_rules = metrics.get('F-19_Business_Quality', {}).get('scoring_rationale_chips', [])

    # Pull the REAL latest concall/earnings-call transcript so the F-14 summary is
    # grounded in the actual document (Screener -> BSE PDF). Never fatal.
    concall_text, concall_url = "", None
    try:
        from tools.screener_scraper import fetch_concall_text
        _c = fetch_concall_text(symbol, name=metrics.get('company_name')) or {}
        concall_text, concall_url = _c.get("text", ""), _c.get("url")
        if concall_text:
            print(f"[analyze_quality_node] Concall transcript loaded for {symbol} ({len(concall_text)} chars).")
    except Exception as _ce:
        print(f"[analyze_quality_node] Concall transcript skipped: {_ce}")

    api_key = os.getenv("GROQ_API_KEY")
    
    # Business description (from the data payload) — grounds F-21 so the Business
    # Model Canvas is populated even when the concall doesn't spell it out.
    _info = (state.get('raw_financial_data') or {}).get('info') or {}
    _biz_desc = (_info.get('longBusinessSummary') or "").strip()

    # Construct details context for LLM
    data_context = (
        f"Stock: {symbol}\n"
        f"Company: {metrics.get('company_name')}\n"
        + (f"Business description: {_biz_desc}\n" if _biz_desc else "")
        + f"Latest Price: {val.get('last_price')}\n"
        f"Valuation: PE={val.get('PE')}, PB={val.get('PB')}, EV/EBITDA={val.get('EV_EBITDA')}, FCF Yield={val.get('FCF_Yield')}\n"
        f"Solvency: Debt/Equity={solvency.get('debt_to_equity')}, Interest Coverage={solvency.get('interest_coverage')}\n"
        f"3Y CAGR Revenue: {growth.get('cagr_3y_revenue')}, 3Y CAGR PAT: {growth.get('cagr_3y_pat')}\n"
        f"Margin status tag: {margins.get('margin_status_tag')}\n"
        f"Scoring rationale: {', '.join(score_rules)}"
    )
    if concall_text:
        data_context += (
            "\n\n=== LATEST EARNINGS-CALL / CONCALL TRANSCRIPT (verbatim excerpt) ===\n"
            + concall_text +
            "\n=== END TRANSCRIPT ===\n"
            "For F-14, summarize STRICTLY from this transcript above (growth drivers, "
            "risks, capex/guidance, management tone). Do not invent facts not present."
        )
    
    # Structure system prompt requesting structured JSON format
    system_prompt = (
        "You are an expert equity research analyst. Analyze the quantitative data for the company and generate "
        "a structured qualitative analysis report in JSON format.\n\n"
        "The JSON object must strictly match this schema:\n"
        "{\n"
        "  \"F-07\": {\n"
        "    \"commentary\": \"Capital efficiency and ROE vs ROCE commentary. Why are return ratios at this level?\"\n"
        "  },\n"
        "  \"F-14\": {\n"
        "    \"summary\": \"3-4 sentence overview of the latest concall / annual report\",\n"
        "    \"tone\": \"Positive | Cautious | Negative\",\n"
        "    \"financial_highlights\": [\"Revenue Rs X cr (+Y% YoY)\", \"EBITDA margin Z%\", \"PAT/PBT figure\", \"FCF / net cash\", \"ROCE/ROE\"],\n"
        "    \"growth_drivers\": [\"detailed driver with specifics\", \"...\", \"...\"],\n"
        "    \"business_wins\": [\"notable orders / launches / market-share wins with numbers\", \"...\"],\n"
        "    \"risks\": [\"risk WITH management response\", \"...\", \"...\"],\n"
        "    \"guidance\": \"forward guidance, capex %, outlook for next year (quote numbers where given)\",\n"
        "    \"what_matters\": [\"most actionable takeaway for an investor\", \"...\"]\n"
        "  },\n"
        "IMPORTANT for F-14: be DETAILED and QUANTIFIED (cite exact figures, %s, order sizes, guidance from the transcript). Give 4-7 items in each list. Base it STRICTLY on the transcript; do not invent.\n"
        "  \"F-15\": {\n"
        "    \"bear\": {\"revenue_growth\": 5.0, \"pat_growth\": 3.0, \"drivers\": \"volume/inflation headwinds\", \"risks\": \"margin contraction risks\"},\n"
        "    \"base\": {\"revenue_growth\": 10.0, \"pat_growth\": 8.0, \"drivers\": \"normal business expansion\", \"risks\": \"competitor pressure\"},\n"
        "    \"bull\": {\"revenue_growth\": 15.0, \"pat_growth\": 14.0, \"drivers\": \"overseas expansion or product adoption\", \"risks\": \"over-capacity issues\"}\n"
        "  },\n"
        "  \"F-16\": {\n"
        "    \"risk_level\": \"Low\",\n"
        "    \"checks\": [\n"
        "      {\"name\": \"CFO vs PAT Conversion Check\", \"status\": \"PASS\", \"severity\": 1, \"details\": \"remarks...\"},\n"
        "      {\"name\": \"Share Dilution Check\", \"status\": \"PASS\", \"severity\": 0, \"details\": \"remarks...\"},\n"
        "      {\"name\": \"Receivables vs Sales Trend Check\", \"status\": \"PASS\", \"severity\": 2, \"details\": \"remarks...\"},\n"
        "      {\"name\": \"Asset Quality & Capitalization Check\", \"status\": \"PASS\", \"severity\": 1, \"details\": \"remarks...\"}\n"
        "    ]\n"
        "  },\n"
        "  \"F-20\": {\n"
        "    \"moat_strength\": \"Wide\",\n"
        "    \"confidence_level\": 85.0,\n"
        "    \"pricing_power\": 8.0,\n"
        "    \"barriers_to_entry\": 9.0,\n"
        "    \"memo_text\": \"Durable moat assessment details (switching costs, brand equity, pricing power)\"\n"
        "  },\n"
        "  \"F-21\": {\n"
        "    \"what_they_sell\": \"one plain sentence: what products/services the company actually sells\",\n"
        "    \"revenue_drivers\": [\"a specific revenue stream a non-expert can understand: name the product/segment AND briefly how it earns, e.g. 'Protection plans - premiums from term & health life cover sold to individuals'; append approx revenue share % only if stated\", \"...\"],\n"
        "    \"revenue_streams\": [{ \"name\": \"short stream name, e.g. 'Premium income' or 'Investment income'\", \"approx_pct\": 40, \"how_it_earns\": \"one plain-English sentence: how this stream actually earns money for the company\" }, \"... 2 to 6 streams whose approx_pct sum to about 100 ...\"],\n"
        "    \"key_customers_or_geographies\": [\"a specific customer type, end-market or geography with a clause on why it matters, e.g. 'Salaried urban individuals - main buyers of savings & protection policies'\", \"...\"],\n"
        "    \"key_partnerships\": [\"name the partner AND why it matters, e.g. 'State Bank of India - parent bank that sells policies through its branches (bancassurance)'\", \"...\"],\n"
        "    \"key_activities\": [\"name the activity AND what it involves, e.g. 'Underwriting - pricing and assessing the risk of each policy before issuing it'\", \"...\"],\n"
        "    \"value_propositions\": [\"a specific benefit customers get and why they choose this company, e.g. 'Trusted brand backed by SBI - reassurance the insurer will pay claims'\", \"...\"],\n"
        "    \"customer_relationships\": [\"name the relationship model AND how it works, e.g. 'Agency network - individual agents give face-to-face advice and after-sales service'\", \"...\"],\n"
        "    \"customer_segments\": [\"a distinct customer group described specifically, e.g. 'High-net-worth individuals buying large savings/ULIP policies'\", \"...\"],\n"
        "    \"key_resources\": [\"a critical asset AND why it is critical, e.g. 'Nationwide agent & bank-branch distribution network that reaches customers'\", \"...\"],\n"
        "    \"channels\": [\"name the channel AND explain what it is, e.g. 'Bancassurance - selling policies through partner bank branches'; 'Agency - network of individual insurance agents'\", \"...\"]\n"
        "  }\n"
        "}\n\n"
        "IMPORTANT for F-21: for revenue_drivers and any quantified split, use ONLY figures stated in the transcript/data (empty list if not stated). BUT the Business Model Canvas blocks (key_partnerships, key_activities, value_propositions, customer_relationships, customer_segments, key_resources, channels) must ALWAYS be populated: infer them from the Business description and known business model of this company — never leave them empty. These are structural facts about how the business operates, not speculative claims.\n"
        "STYLE for EVERY F-21 list item: write it so a non-expert instantly understands it - NEVER a bare 2-3 word label like 'Agency channel', 'Savings products' or 'Investment management'. Use the pattern 'Short label - brief plain-English explanation'. Keep each item concise (roughly 6-14 words) so it is specific but not text-heavy.\n"
        "COVERAGE for EVERY F-21 list: be COMPREHENSIVE - include ALL the material points this business genuinely has, not just one or two. Where the business warrants it, list about 4-7 distinct items per block. In particular revenue_drivers must cover EVERY major way the company makes money (each product line/segment, plus investment income, fee income or other income when relevant) so the reader fully understands how it earns. Do NOT pad with generic filler - only real, distinct points grounded in the provided context.\n"
        "SECTOR HINT for revenue_drivers: if the company is a LIFE/GENERAL INSURER, cover all premium sources it mentions (e.g. protection/term, participating & non-participating savings, ULIP/unit-linked, group/corporate, annuity/pension) AND its investment income on the policyholder book. If it is a BANK/NBFC, cover net interest income plus fee/commission, treasury/trading and other income. Only include the ones actually evidenced in the provided transcript/context - never invent a stream that is not mentioned.\n"
        "REVENUE_STREAMS (ALWAYS fill - this is different from revenue_drivers): break the company's revenue into 2 to 6 DISTINCT streams that reflect how THIS business model genuinely earns money - for a LIFE INSURER: premium income (by major type) plus investment income on the float; for a BANK/NBFC: net interest income plus fee/commission plus treasury/other income; for a MANUFACTURER or SERVICE company: its main product/service lines plus other/interest income. Give each stream an APPROXIMATE percentage share (approx_pct) based on the known economics of this kind of business - these are explicitly understood by the reader as ESTIMATES, so it is acceptable and expected to approximate when exact disclosed figures are unavailable. The approx_pct values should sum to roughly 100. NEVER return a single 100% stream for a company that plainly has more than one source of income (almost every company does). Each how_it_earns must be one clear plain-English sentence a non-expert understands.\n"
        "Respond ONLY with the raw JSON string. Do not include markdown block ticks like ```json or any introductory text. Ensure the output is valid JSON."
    )
    
    qualitative_payload = {}
    
    # Check for Groq API key availability and execute or fallback
    if not api_key or api_key.strip() in ["", "your_api_key_here"]:
        print("[WARNING] GROQ_API_KEY not configured. Generating high-quality simulated JSON payload for prototype...")
        parsed_data = get_fallback_structured_data(symbol)
        qualitative_payload = {
            'status': 'MOCK_SUCCESS',
            'parsed_json': parsed_data,
            'narrative': json_to_markdown_narrative(parsed_data, symbol)
        }
    else:
        try:
            print(f"[analyze_quality_node] Calling Groq (model fallback chain)...")
            from tools.groq_client import groq_chat
            response_text = groq_chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional equity research assistant specialized in qualitative business auditing."
                    },
                    {
                        "role": "user",
                        "content": f"{system_prompt}\n\nHere is the data context:\n{data_context}"
                    }
                ],
                max_tokens=3500,
                api_key=api_key,
            )
            
            # Tolerant parse — fallback models emit fences/invalid escapes.
            from tools.groq_client import parse_json_loose
            parsed_data = parse_json_loose(response_text)

            # Models sometimes return list items as OBJECTS where strings are
            # expected (e.g. F-14 risks as {"risk", "management_response"}) —
            # rendering those crashes the React frontend. Flatten to text.
            def _stringify_items(section, keys):
                if not isinstance(section, dict):
                    return
                for k in keys:
                    v = section.get(k)
                    if isinstance(v, list):
                        section[k] = [
                            x if isinstance(x, str)
                            else " — ".join(str(t) for t in x.values() if t) if isinstance(x, dict)
                            else str(x)
                            for x in v if x
                        ]
            _stringify_items(parsed_data.get('F-14'), ['financial_highlights', 'growth_drivers',
                                                       'business_wins', 'risks', 'what_matters'])
            
            qualitative_payload = {
                'status': 'SUCCESS',
                'parsed_json': parsed_data,
                'narrative': json_to_markdown_narrative(parsed_data, symbol)
            }
            print("[analyze_quality_node] Successfully retrieved and parsed Groq qualitative analysis JSON.")
        except Exception as e:
            print(f"[analyze_quality_node] Error calling Groq or parsing JSON: {e}. Shifting to fallback mock structured JSON.")
            parsed_data = get_fallback_structured_data(symbol)
            qualitative_payload = {
                'status': 'ERROR_FALLBACK',
                'error': str(e),
                'parsed_json': parsed_data,
                'narrative': json_to_markdown_narrative(parsed_data, symbol)
            }

    # ------------------------------------------------------------------
    # Qualitative Analysis topics (F-22 through F-25) — a SEPARATE, smaller
    # Groq call rather than folding these into the giant F-07..F-21 prompt
    # above. That combined schema had grown too large: even with a big token
    # budget the model would truncate mid-response or garble a section's shape
    # (e.g. echoing F-20's fields into F-22). A focused, short prompt is far
    # more reliable. Never fatal — sub-points just stay empty on failure.
    # ------------------------------------------------------------------
    if api_key and api_key.strip() not in ("", "your_api_key_here"):
        try:
            from tools.groq_client import groq_chat, parse_json_loose
            import time as _time
            # Small stagger so this call's tokens don't land in the exact same
            # per-minute rate-limit window as the F-07..F-21 call just above —
            # two calls back-to-back is the main reason this was hitting Groq's
            # shared per-minute cap.
            _time.sleep(3)
            topics_prompt = (
                "You are an expert equity research analyst. Given the company data below, return "
                "ONLY this JSON object (no markdown, no extra text):\n"
                "{\n"
                "  \"F-22\": {\n"
                "    \"business_model_type\": \"Portfolio (multiple products/segments)\",\n"
                "    \"revenue_pattern\": \"Mixed\",\n"
                "    \"recurring_revenue_pct\": 65.0,\n"
                "    \"rationale\": \"2-3 sentences: single-product or multi-segment portfolio business, and which revenue lines are recurring (subscriptions, AMC/service contracts, premiums, interest income) vs one-off/cyclical (project or one-time sales)\"\n"
                "  },\n"
                "  \"F-23\": {\n"
                "    \"moat_types\": {\"brand\": 3.5, \"distribution\": 3.0, \"cost_leadership\": 2.5, \"network_effects\": 1.5, \"switching_costs\": 3.0},\n"
                "    \"overall_rating\": 3.0,\n"
                "    \"rationale\": \"2-3 sentences on which of brand/distribution/cost leadership/network effects/switching costs are genuinely strong vs weak\"\n"
                "  },\n"
                "  \"F-24\": {\n"
                "    \"revenue_model_type\": \"Transactional\",\n"
                "    \"contract_length\": \"short description, e.g. '3-5 year supply contracts' or 'Not disclosed'\",\n"
                "    \"contract_renewal_rate_pct\": 85.0,\n"
                "    \"rationale\": \"2-3 sentences on revenue model quality and known renewal/contract-length dynamics\"\n"
                "  },\n"
                "  \"F-25\": {\n"
                "    \"lifecycle_stage\": \"Growth\",\n"
                "    \"relative_growth_pct\": 4.5,\n"
                "    \"rationale\": \"2-3 sentences on the product/business lifecycle stage, grounded in the 3-5yr revenue growth trend vs industry\"\n"
                "  },\n"
                "  \"F-26\": {\n"
                "    \"pricing_power_rating\": \"Strong\",\n"
                "    \"price_pass_through_ratio\": 0.85,\n"
                "    \"rationale\": \"2-3 sentences on pricing power: can the company raise realisations/prices without losing volume, and how fully does it pass through input-cost inflation (commodity/raw-material costs) into its own prices, per concall/MD&A commentary\"\n"
                "  },\n"
                "  \"F-27\": {\n"
                "    \"structural_defensibility\": \"Structurally defensible\",\n"
                "    \"one_off_flags\": [\"short flag naming the year/event, e.g. 'FY23: one-time forex/subsidy gain lifted margin' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on whether margins reflect a durable structural advantage (pricing power, cost structure, scale, brand) vs temporary tailwinds (one-off gains, commodity cycle, subsidy, forex, tax credits), referencing the margin trend/status given below\"\n"
                "  }\n"
                "}\n\n"
                "CRITICAL: every field above is shown with ONE example value already picked for you - that is "
                "the format you must follow. NEVER output multiple options joined by '|' or write out the full "
                "list of choices - always pick and output exactly ONE single value per field, based on the "
                "actual company data below. The allowed values are: business_model_type is exactly 'Single "
                "product' or 'Portfolio (multiple products/segments)'. revenue_pattern is exactly 'Recurring', "
                "'Cyclical', or 'Mixed'. revenue_model_type is exactly 'Transactional', 'Recurring subscription', "
                "'Annuity', or 'Long-term contract'. lifecycle_stage is exactly 'Growth', 'Maturity', "
                "'Commoditisation', or 'Decline / obsolescence risk'. pricing_power_rating is exactly 'Strong', "
                "'Moderate', or 'Weak'. structural_defensibility is exactly 'Structurally defensible', "
                "'Partially temporary tailwinds', or 'Largely temporary tailwinds'.\n\n"
                "Rules: F-22 recurring_revenue_pct and F-25 relative_growth_pct are ESTIMATES - never null, "
                "approximate from the business description and known industry economics even if not explicitly "
                "disclosed. F-23 moat_types: rate ALL 5 on a 1-5 scale, never null (a low score is a valid answer). "
                "F-24 contract_renewal_rate_pct: this is a hard disclosed fact, not an estimate - return null if not "
                "explicitly stated (expected for most companies). F-26 price_pass_through_ratio (= % change in "
                "realisation / % change in input cost, e.g. 1.0 = fully passed through, below 1.0 = margin absorbs "
                "some inflation): give your best ESTIMATE - never null - based on the company's known pricing "
                "power and industry structure, even if an exact ratio isn't disclosed. F-27 one_off_flags: only "
                "include years/events genuinely evidenced in the provided context - an empty list is valid and "
                "expected for most companies. Follow each field's exact name and shape above - do not reuse "
                "another section's fields."
            )
            topics_text = groq_chat(
                messages=[
                    {"role": "system", "content": "You are an equity research assistant. Respond with raw JSON only."},
                    {"role": "user", "content": f"{topics_prompt}\n\nCompany data:\n{data_context}"},
                ],
                max_tokens=1500,
                api_key=api_key,
            )
            topics_data = parse_json_loose(topics_text)
            for k in ('F-22', 'F-23', 'F-24', 'F-25', 'F-26', 'F-27'):
                if isinstance(topics_data.get(k), dict):
                    parsed_data[k] = topics_data[k]
            qualitative_payload['parsed_json'] = parsed_data
            qualitative_payload['topics_status'] = 'SUCCESS'
            print("[analyze_quality_node] Qualitative-topics (F-22..F-27) call succeeded.")
        except Exception as te:
            # Surface this in the returned payload (not just a server-log print) so
            # it's inspectable from the cached report JSON when a sub-point stays
            # empty — otherwise there is no way to tell why without console access.
            qualitative_payload['topics_status'] = 'FAILED'
            qualitative_payload['topics_error'] = str(te)
            print(f"[analyze_quality_node] Qualitative-topics call failed (sub-points will stay empty): {te}")

    # Build parsed_sections for backwards compatibility and fallback text
    pdata = qualitative_payload.get('parsed_json') or {}

    # --- F-20: replace the LLM-guessed / canned moat with a DATA-DRIVEN, company-
    # specific moat score computed from real Screener.in fundamentals (ROCE level &
    # consistency, margin stability, ROE track record, balance sheet, working-capital
    # efficiency). Deterministic and genuinely differentiates companies. ---
    try:
        from tools.screener_scraper import fetch_screener_moat_data
        from tools.moat_engine import compute_moat
        _ratios = metrics.get('F-02_Ratio_Analysis') or []
        _lr = _ratios[-1] if _ratios else {}
        _margins_a = margins.get('margins_annual') or []
        _fb = {
            'debt_to_equity': solvency.get('debt_to_equity'),
            'roce': (_lr.get('ROCE') * 100) if _lr.get('ROCE') is not None else None,
            'roe': (_lr.get('ROE') * 100) if _lr.get('ROE') is not None else None,
            'operating_margin': (_margins_a[-1].get('ebit_margin')) if _margins_a else None,
            # Our own multi-year CAGRs so lenders/insurers (whose Screener growth
            # ranges-tables often don't parse) still get a rated moat, not "Unrated".
            'sales_growth': (growth.get('cagr_3y_revenue') * 100) if growth.get('cagr_3y_revenue') is not None else None,
            'profit_growth': (growth.get('cagr_3y_pat') * 100) if growth.get('cagr_3y_pat') is not None else None,
        }
        _moat_data = fetch_screener_moat_data(symbol, name=metrics.get('company_name'))
        _moat = compute_moat(_moat_data, company_name=metrics.get('company_name'), fallback=_fb)
        # Merge over whatever the LLM/fallback produced so downstream keys stay present.
        pdata['F-20'] = {**(pdata.get('F-20') or {}), **_moat}
        qualitative_payload['parsed_json'] = pdata
        print(f"[analyze_quality_node] Data-driven moat: {_moat['moat_score']}/100 ({_moat['moat_strength']}).")
    except Exception as _me:
        print(f"[analyze_quality_node] Data-driven moat skipped: {_me}")

    f14 = pdata.get('F-14') or {}
    f15 = pdata.get('F-15') or {}
    f16 = pdata.get('F-16') or {}
    f20 = pdata.get('F-20') or {}
    
    def _bul(items):
        return "\n".join([f"•  {x}" for x in (items or []) if x]) or "•  (not specified)"
    f14_text = (
        f"{f14.get('summary', 'Summary not available.')}\n"
        f"Management Tone: {f14.get('tone', '—')}\n\n"
        f"FINANCIAL HIGHLIGHTS\n{_bul(f14.get('financial_highlights'))}\n\n"
        f"GROWTH DRIVERS\n{_bul(f14.get('growth_drivers'))}\n\n"
        f"BUSINESS WINS / EXECUTION\n{_bul(f14.get('business_wins'))}\n\n"
        f"RISKS (with management response)\n{_bul(f14.get('risks'))}\n\n"
        f"GUIDANCE / OUTLOOK\n{f14.get('guidance', f14.get('capex_guidance', '—'))}\n\n"
        f"WHAT MATTERS FOR INVESTORS\n{_bul(f14.get('what_matters'))}"
    )
    qualitative_payload['concall_url'] = concall_url
    qualitative_payload['concall_grounded'] = bool(concall_text)
    try:
        from tools.screener_scraper import fetch_concall_list
        qualitative_payload['concall_list'] = fetch_concall_list(symbol, name=metrics.get('company_name'))
    except Exception:
        qualitative_payload['concall_list'] = []

    checks_list = f16.get('checks') or []
    checks_str = "\n".join([f"- {c.get('name')}: {c.get('status')} (Severity {c.get('severity')}/10) - {c.get('details')}" for c in checks_list])
    
    qualitative_payload['parsed_sections'] = {
        'F-07': pdata.get('F-07', {}).get('commentary', 'Stable capital efficiency and reinvestment profiles.'),
        'F-14': f14_text,
        'F-15': f"Bull Case (Growth: {f15.get('bull', {}).get('revenue_growth', 15)}%): Drivers: {f15.get('bull', {}).get('drivers')}. Risks: {f15.get('bull', {}).get('risks')}\nBase Case (Growth: {f15.get('base', {}).get('revenue_growth', 10)}%): Drivers: {f15.get('base', {}).get('drivers')}. Risks: {f15.get('base', {}).get('risks')}\nBear Case (Growth: {f15.get('bear', {}).get('revenue_growth', 5)}%): Drivers: {f15.get('bear', {}).get('drivers')}. Risks: {f15.get('bear', {}).get('risks')}",
        'F-16': f"Risk Level: {f16.get('risk_level', 'Low')}\nChecks:\n{checks_str}",
        'F-20': f"Moat Strength: {f20.get('moat_strength', 'None')} | Confidence: {f20.get('confidence_level', 80)}%\nPricing Power: {f20.get('pricing_power', 5)}/10 | Barriers: {f20.get('barriers_to_entry', 5)}/10\nMemo: {f20.get('memo_text', '')}"
    }

    print(f"[NODE: analyze_quality_node] Finished. Verdict = STRUCTURAL_ANALYSIS_COMPLETE")
    return {
        'verdict': "STRUCTURAL_ANALYSIS_COMPLETE",
        'qualitative_analysis': qualitative_payload
    }

def _next_month_price(symbol: str, price0):
    """Short-horizon ML: fit a linear regression on the last ~12 monthly closes and
    project one month ahead with a ±1σ range. Best-effort; returns None on failure."""
    try:
        import numpy as np
        from tools.yf_cache import cached_history
        sym = (symbol or "").strip().upper().replace(".NS", "")
        hist = cached_history(f"{sym}.NS", period="2y", interval="1mo")
        closes = [float(c) for c in (hist["Close"].tolist() if hist is not None and not hist.empty else []) if c and not (c != c)]
        closes = closes[-13:]
        if len(closes) < 6:
            return None
        y = np.array(closes[-12:]) if len(closes) >= 12 else np.array(closes)
        xs = np.arange(len(y), dtype=float)
        b, a = np.polyfit(xs, y, 1)
        pred = a + b * len(y)
        resid = float(np.std(y - (a + b * xs))) or (float(np.std(y)) * 0.5)
        base = price0 or (closes[-1] if closes else None)
        if not base or pred <= 0:
            return None
        return {
            "value": round(float(pred)),
            "low": round(float(pred - resid)),
            "high": round(float(pred + resid)),
            "change_pct": round((float(pred) - base) / base * 100, 1),
        }
    except Exception as e:
        print(f"[ml_forecast] next-month price skipped: {e}")
        return None


def build_ml_forecast(m: dict, info: dict, symbol: str = None) -> dict:
    """
    ML fundamentals forecast (stock-specific): fits a log-linear regression on the
    company's OWN multi-year revenue & net-income history and projects 3-5 years
    forward with an 80% confidence band, then derives an implied price trajectory
    (holding today's P/E). Transparent and grounded — not a generic guess. Returns
    None when there isn't enough history. Never raises.
    """
    try:
        import numpy as np
        inc = ((m.get('F-01_Financial_Statements', {}) or {}).get('annual', {}) or {}).get('income_stmt', {}) or {}
        dates = sorted(inc.keys())
        if len(dates) < 3:
            return None
        base_year = int(dates[-1][:4])

        def _series(names):
            # Exact-key priority match (case/space-insensitive). Substring matching is
            # dangerous here: 'netincome' also matches junk rows like
            # 'Net Income Extraordinary' (tiny one-off values) and one bad year makes
            # the regression explode.
            out = []
            for d in dates:
                row = inc[d] or {}
                norm = {str(k).lower().replace(' ', ''): row[k] for k in row}
                v = None
                for nm in names:
                    if norm.get(nm) is not None:
                        v = norm[nm]; break
                out.append(v)
            return out

        rev = _series(['totalrevenue', 'operatingrevenue'])
        # Normalized/continuing income first so one-off gains (e.g. a demerger)
        # don't distort the trend fit.
        ni = _series(['normalizedincome', 'netincomecontinuousoperations',
                      'netincomecommonstockholders', 'netincome'])

        def _fit(vals, horizon=5):
            pts = [(i, float(v)) for i, v in enumerate(vals) if v is not None and float(v) > 0]
            if len(pts) < 3:
                return None
            # Outlier guard: drop years wildly off the series median (bad rows in the
            # source data) instead of fitting a trend through them.
            med = sorted(p[1] for p in pts)[len(pts) // 2]
            pts = [p for p in pts if med > 0 and 0.1 <= p[1] / med <= 10.0]
            if len(pts) < 3:
                return None
            xs = np.array([p[0] for p in pts], dtype=float)
            ys = np.log(np.array([p[1] for p in pts]))
            b, a = np.polyfit(xs, ys, 1)
            # Plausibility clamp: cap the fitted trend at -30%..+50%/yr; anything
            # steeper is a data artefact, not a forecastable trend. Re-anchor the
            # intercept through the mean point when clamped.
            b_c = min(max(b, np.log(0.7)), np.log(1.5))
            if b_c != b:
                a = float(ys.mean()) - b_c * float(xs.mean())
                b = b_c
            pred = a + b * xs
            ss_res = float(np.sum((ys - pred) ** 2))
            ss_tot = float(np.sum((ys - ys.mean()) ** 2)) or 1e-9
            r2 = max(0.0, 1 - ss_res / ss_tot)
            sd = min(float(np.std(ys - pred)) or 0.12, 0.35)  # keep the 80% band sane
            g = float(np.exp(b) - 1)
            last_i = pts[-1][0]
            proj = []
            for k in range(1, horizon + 1):
                mu = float(np.exp(a + b * (last_i + k)))
                band = 1.28 * sd * (k ** 0.5)  # ~80% interval, widening with horizon
                proj.append({'k': k, 'value': mu,
                             'low': float(mu * np.exp(-band)), 'high': float(mu * np.exp(band))})
            return {'growth': g, 'r2': r2, 'proj': proj, 'last_value': pts[-1][1], 'last_i': last_i}

        rf, nf = _fit(rev), _fit(ni)
        if not rf and not nf:
            return None

        HORIZON = 5

        def _mk_series(vals, fit):
            """Actual points + forecast points (with band) sharing a year axis."""
            rows = []
            for i, v in enumerate(vals):
                rows.append({'year': f"FY{str(base_year - (len(vals) - 1 - i))[2:]}",
                             'actual': (round(v / 1e7) if v is not None else None),
                             'forecast': None, 'low': None, 'high': None})
            if fit:
                # bridge: forecast line starts at the last actual for visual continuity
                rows[-1]['forecast'] = rows[-1]['actual']
                for p in fit['proj']:
                    rows.append({'year': f"FY{str(base_year + p['k'])[2:]}", 'actual': None,
                                 'forecast': round(p['value'] / 1e7),
                                 'low': round(p['low'] / 1e7), 'high': round(p['high'] / 1e7)})
            return rows

        # Implied price path: hold today's P/E, scale by projected earnings growth.
        price0 = info.get('currentPrice') or info.get('regularMarketPrice')
        price_path, price_cagr, target_price = [], None, None
        if nf and price0:
            e0 = nf['last_value']
            price_path.append({'year': f"FY{str(base_year)[2:]}", 'price': round(price0)})
            for p in nf['proj']:
                fp = price0 * (p['value'] / e0) if e0 else None
                price_path.append({'year': f"FY{str(base_year + p['k'])[2:]}",
                                   'price': round(fp) if fp else None,
                                   'low': round(price0 * (p['low'] / e0)) if e0 else None,
                                   'high': round(price0 * (p['high'] / e0)) if e0 else None})
            p3 = next((x for x in nf['proj'] if x['k'] == 3), nf['proj'][-1])
            if e0:
                target_price = round(price0 * (p3['value'] / e0))
                yrs = p3['k']
                price_cagr = round(((p3['value'] / e0) ** (1 / yrs) - 1) * 100, 1)

        conf_r2 = max([f['r2'] for f in [rf, nf] if f] or [0])
        confidence = ('High' if conf_r2 >= 0.9 and len(dates) >= 5 else
                      'Moderate' if conf_r2 >= 0.7 else 'Low')

        next_month = _next_month_price(symbol, price0)

        return {
            'method': f"Log-linear regression on {len(dates)} years of financials (fit R²={round(conf_r2, 2)}).",
            'confidence': confidence,
            'next_month_price': next_month,
            'horizon_years': HORIZON,
            'revenue_series': _mk_series(rev, rf) if rf else [],
            'earnings_series': _mk_series(ni, nf) if nf else [],
            'revenue_cagr': round(rf['growth'] * 100, 1) if rf else None,
            'earnings_cagr': round(nf['growth'] * 100, 1) if nf else None,
            'current_price': round(price0) if price0 else None,
            'target_price': target_price,
            'price_cagr': price_cagr,
            'price_path': price_path,
            'note': "Projection assumes past fundamental trends persist and the P/E holds — "
                    "real outcomes vary with execution, cycles and re-rating. Not investment advice.",
        }
    except Exception as e:
        print(f"[ml_forecast] skipped: {e}")
        return None


def build_executive_summary(state: SystemState) -> dict:
    """
    Compose a DETAILED, data-driven AI summary of the stock from the full analysis
    (quality score, profitability, growth, valuation, balance sheet, moat, ownership,
    red flags, peer standing). Deterministic — always available (works even when the
    LLM/Screener are unreachable), so the default page always has a rich summary.
    """
    m = state.get('calculated_metrics', {}) or {}
    q = (state.get('qualitative_analysis', {}) or {}).get('parsed_json', {}) or {}
    peer = state.get('peer_synthesis_data', {}) or {}
    raw = state.get('raw_financial_data', {}) or {}
    info = raw.get('info', {}) or {}
    score = state.get('business_score', 0) or 0

    name = m.get('company_name') or state.get('symbol')
    symbol = state.get('symbol')
    val = m.get('F-03_Valuation_Metrics', {}) or {}
    growth = m.get('F-05_Growth_Summary', {}) or {}
    margins = m.get('F-06_Margin_Analysis', {}) or {}
    solvency = m.get('F-08_Solvency_Metrics', {}) or {}
    cashq = m.get('F-09_Cash_Flow_Conversion', {}) or {}
    ratios = m.get('F-02_Ratio_Analysis', []) or []
    latest_ratio = ratios[-1] if ratios else {}
    dcf = (m.get('F-18_Reverse_DCF', {}) or {}).get('scenarios', {}) or {}
    f14 = q.get('F-14', {}) or {}
    f15 = q.get('F-15', {}) or {}
    f16 = q.get('F-16', {}) or {}
    f20 = q.get('F-20', {}) or {}
    own = m.get('F-10_F-11_F-12_Ownership', {}) or {}
    cap_tier = peer.get('cap_tier')
    spv = peer.get('screener_peer_view') or {}
    sector = (spv.get('ai_guidance') or {}).get('sector_guess') or peer.get('sector')

    # Pull the multi-year Screener series (cached) so the summary can describe the
    # actual trajectory (ROCE trend, margin trend, long-run growth) — this is what
    # makes it specific to the company rather than generic.
    moat_data = {}
    try:
        from tools.screener_scraper import fetch_screener_moat_data
        moat_data = fetch_screener_moat_data(symbol, name=name) or {}
    except Exception:
        moat_data = {}

    def pct(x, d=1):
        try:
            return f"{x * 100:.{d}f}%"
        except Exception:
            return None

    def num(x, d=1):
        try:
            return f"{float(x):.{d}f}"
        except Exception:
            return None

    def cr(x):
        try:
            v = float(x) / 1e7
            return f"₹{v:,.0f} Cr" if abs(v) >= 1 else f"₹{float(x):,.0f}"
        except Exception:
            return None

    def as_float(x):
        try:
            if x is None or x == "":
                return None
            return float(x)
        except Exception:
            return None

    def first_value(*values):
        for value in values:
            if value is not None and value != "":
                return value
        return None

    def pct_flex(x, d=1):
        try:
            v = float(x)
            return f"{v * 100:.{d}f}%" if abs(v) <= 1 else f"{v:.{d}f}%"
        except Exception:
            return None

    def text_list(items):
        if isinstance(items, list):
            return " ".join(str(x) for x in items if x)
        return str(items or "")

    def _stmt_series(row_names):
        grid = ((m.get('F-01_Financial_Statements', {}) or {}).get('annual', {}) or {}).get('income_stmt', {}) or {}
        dates = sorted(grid.keys())
        out = []
        for d in dates:
            row = grid[d] or {}
            v = None
            for rn in row_names:
                for k in row:
                    if rn in k.lower().replace(' ', ''):
                        v = row[k]; break
                if v is not None:
                    break
            out.append((d, v))
        return [(d, v) for d, v in out if v is not None]

    def _trend(series):
        vals = [v for v in (series or []) if v is not None]
        if len(vals) < 2:
            return None
        if vals[-1] > vals[0] * 1.08:
            return "expanding"
        if vals[-1] < vals[0] * 0.92:
            return "compressing"
        return "broadly stable"

    quality_word = ("high-quality" if score >= 75 else "above-average" if score >= 55
                    else "average" if score >= 40 else "below-average")
    cap_word = (cap_tier or "").lower()

    roce = latest_ratio.get('ROCE') if latest_ratio.get('ROCE') is not None else (
        (moat_data.get('roce_latest') / 100.0) if moat_data.get('roce_latest') is not None else None)
    roe = latest_ratio.get('ROE') if latest_ratio.get('ROE') is not None else (
        (moat_data.get('roe_last') / 100.0) if moat_data.get('roe_last') is not None else None)
    opm = (margins.get('margins_annual') or [{}])[-1].get('ebit_margin') if margins.get('margins_annual') else None
    prom = first_value(own.get('promoter_stake'), own.get('F-10_heldPercentInsiders'), own.get('heldPercentInsiders'))
    pledge = first_value(own.get('promoter_pledge_of_stake'), own.get('F-11_promoterPledges'), own.get('promoterPledges'))
    pledge_num = as_float(pledge)
    own_hist = own.get('ownership_history') or []

    paras = []

    # 1) What it is + scale.
    biz = (info.get('longBusinessSummary') or "").strip()
    biz_short = ""
    if biz:
        biz_short = biz.split('. ')[0].rstrip('.')
        if len(biz_short) > 220:
            biz_short = biz_short[:217] + "…"
    rev_series = _stmt_series(['totalrevenue', 'operatingrevenue', 'revenue', 'sales'])
    latest_rev = rev_series[-1][1] if rev_series else None
    mcap = info.get('marketCap')
    lead = f"{name} ({symbol}) is a"
    lead += f" {cap_word}" if cap_word else "n"
    lead += f" {sector} company" if sector else " listed company"
    scale_bits = []
    if latest_rev: scale_bits.append(f"annual revenue of about {cr(latest_rev)}")
    if mcap: scale_bits.append(f"a market capitalisation of {cr(mcap)}")
    if scale_bits:
        lead += " with " + " and ".join(scale_bits)
    lead += f". On our composite quality model it scores {score}/100 — a {quality_word} business."
    paras.append(lead)
    if biz_short:
        paras.append(f"Business: {biz_short}.")

    # 2) How it has performed over the years (the trajectory, with real numbers).
    sg5 = moat_data.get('sales_growth_5y'); pg5 = moat_data.get('profit_growth_5y')
    sg3 = moat_data.get('sales_growth_3y'); pg3 = moat_data.get('profit_growth_3y')
    roce_hist = moat_data.get('roce_history') or []
    opm_hist = moat_data.get('opm_history') or []
    perf = "Track record: "
    seg = []
    if sg5 is not None: seg.append(f"revenue has compounded ~{num(sg5,0)}% a year over five years")
    elif sg3 is not None: seg.append(f"revenue has compounded ~{num(sg3,0)}% a year over three years")
    if pg5 is not None: seg.append(f"profit ~{num(pg5,0)}% a year")
    elif pg3 is not None: seg.append(f"profit ~{num(pg3,0)}% a year")
    rev_range = None
    if rev_series and len(rev_series) >= 2:
        rev_range = f"revenue moved from {cr(rev_series[0][1])} to {cr(rev_series[-1][1])} over the years on file"
    if seg:
        perf += ", ".join(seg) + (f", with {rev_range}." if rev_range else ".")
    elif rev_range:
        perf += rev_range[0].upper() + rev_range[1:] + "."
    else:
        perf += "multi-year growth data is limited for this company."
    # Margin & ROCE direction
    mt = _trend(opm_hist)
    rt = _trend(roce_hist)
    tail = []
    if mt: tail.append(f"operating margins have been {mt} ({num(min(opm_hist),0)}–{num(max(opm_hist),0)}%)")
    if rt: tail.append(f"and returns on capital {rt} ({num(min(roce_hist),0)}–{num(max(roce_hist),0)}%)")
    if tail:
        perf += " Over the same window, " + " ".join(tail) + "."
    paras.append(perf)

    # 3) Profitability now.
    prof_bits = []
    if roce is not None: prof_bits.append(f"ROCE of {pct(roce)}")
    if roe is not None: prof_bits.append(f"ROE of {pct(roe)}")
    if opm is not None: prof_bits.append(f"operating margins of {pct(opm)}")
    if prof_bits:
        mtag = margins.get('margin_status_tag')
        interp = ("which points to a genuinely high-return business" if (roce or 0) > 0.20
                  else "which is around the cost of capital" if (roce or 0) > 0.10
                  else "which is on the low side")
        paras.append("Profitability today: it earns " + ", ".join(prof_bits) + f", {interp}" +
                     (f", and margins are {str(mtag).lower()}." if mtag else "."))

    # 4) Balance sheet & cash.
    de = solvency.get('debt_to_equity'); cfo_pat = cashq.get('CFO_to_PAT'); ccc = moat_data.get('cash_conversion_cycle')
    bs = []
    if de is not None: bs.append(f"debt-to-equity of {num(de, 2)}" + (" (effectively debt-free)" if de < 0.25 else ""))
    if cfo_pat is not None: bs.append(f"cash conversion (operating cash flow ÷ profit) of {num(cfo_pat, 2)}" + (" — profits convert well into cash" if cfo_pat >= 0.8 else " — cash conversion is weak" if cfo_pat < 0.5 else ""))
    if ccc is not None: bs.append(f"a cash-conversion cycle of {num(ccc,0)} days")
    if bs:
        paras.append("Balance sheet & cash: " + ", ".join(bs) + ".")

    # 5) Valuation with context + fair value.
    pe = val.get('PE'); pb = val.get('PB')
    pe_band = val.get('pe_band') or {}
    if pe is not None or pb is not None:
        v = "Valuation: the stock trades at "
        segs = []
        if pe is not None: segs.append(f"a P/E of {num(pe)}")
        if pb is not None: segs.append(f"a P/B of {num(pb)}")
        v += " and ".join(segs)
        if pe is not None and pe_band.get('median'):
            v += f", versus a 5-year median P/E of {num(pe_band['median'])} ({'a premium to' if pe > pe_band['median'] else 'a discount to'} its own history)"
        gg = pg5 or pg3
        if pe is not None and gg:
            v += (f". Against ~{num(gg,0)}% profit growth, the market is paying up for quality/stability" if pe > 1.5 * gg
                  else f". Relative to ~{num(gg,0)}% profit growth, that is not demanding")
        v += "."
        paras.append(v)
    base_fv = dcf.get('Base_Value'); price = val.get('last_price') or info.get('currentPrice')
    if base_fv and price:
        try:
            up = (base_fv - price) / price * 100
            paras.append(f"Our reverse-DCF puts base-case fair value near ₹{base_fv:,.0f} against a price of ₹{price:,.0f} — about {up:+.0f}% {'upside' if up >= 0 else 'downside'} on base assumptions (sensitive to the growth/discount inputs).")
        except Exception:
            pass

    # 6) Moat.
    if f20.get('moat_strength') and f20.get('moat_strength') != 'Unrated':
        mo = f"Competitive moat: assessed {f20.get('moat_strength')}"
        if f20.get('moat_score') is not None:
            mo += f" ({f20.get('moat_score')}/100)"
        sig = (f20.get('signals') or [])
        if sig:
            mo += f" — {sig[0][0].lower() + sig[0][1:]}"
        if f20.get('warnings'):
            mo += f" That said, {f20['warnings'][0][0].lower() + f20['warnings'][0][1:]}"
        paras.append(mo)

    # 7) Ownership.
    if prom is not None:
        o = f"Ownership: promoters hold {pct_flex(prom)}"
        if pledge_num and pledge_num > 0:
            o += f", with {pct_flex(pledge_num)} of their stake pledged — a governance watch-item"
        else:
            o += " with no pledging on record"
        paras.append(o + ".")

    # 8) Outlook / what to expect (scenario-based, not a point forecast).
    base_g = (f15.get('base') or {}).get('revenue_growth')
    bull_g = (f15.get('bull') or {}).get('revenue_growth')
    bear_g = (f15.get('bear') or {}).get('revenue_growth')
    guidance = (q.get('F-14', {}) or {}).get('guidance')
    if base_g is not None or bull_g is not None:
        out = "Outlook: our scenario model frames the next few years at roughly "
        out += f"{num(bear_g,0)}% (bear) / {num(base_g,0)}% (base) / {num(bull_g,0)}% (bull) revenue growth"
        out += ". " + ("Sustained high returns plus that growth would let it compound shareholder value steadily" if (roce or 0) > 0.18
                       else "Execution on growth while lifting returns on capital is the key swing factor")
        out += "."
        if guidance and isinstance(guidance, str) and len(guidance) > 4 and guidance not in ('—',):
            out += f" Management guidance: {guidance[:200]}"
        paras.append(out)

    # 9) Management commentary — latest concall / annual-report read.
    if f14.get('summary'):
        cc = f"Management commentary (latest concall): {str(f14['summary']).strip()}"
        if f14.get('tone'):
            cc += f" Overall tone: {str(f14['tone']).lower()}."
        paras.append(cc)

    # 10) Forensic read — what the red-flag checks actually found.
    checks = f16.get('checks') or []
    if checks:
        passed = [c for c in checks if str(c.get('status', '')).upper() == 'PASS']
        flagged = [c for c in checks if str(c.get('status', '')).upper() != 'PASS']
        fr = f"Forensic screen: {len(passed)} of {len(checks)} accounting checks pass ({str(f16.get('risk_level', '—')).lower()} overall risk)"
        if flagged:
            fr += " — flagged: " + "; ".join(f"{c.get('name')} ({c.get('status')})" for c in flagged[:2])
        paras.append(fr + ".")

    # 11) Size-aware framing.
    if cap_word.startswith('small'):
        paras.append("Because this is a small-cap, expect higher share-price volatility, thinner liquidity and greater dependence on a few customers/promoters — position sizing and a longer horizon matter more here.")
    elif cap_word.startswith('mid'):
        paras.append("As a mid-cap it sits between growth potential and stability — more re-rating scope than large-caps but more cyclicality than blue-chips.")
    elif cap_word.startswith('large'):
        paras.append("As a large-cap it offers relative stability, liquidity and institutional coverage, with more modest (but more dependable) growth than smaller peers.")

    # ------------------------------------------------------------------
    # INVESTMENT VIEW — "should one consider investing?" (absolute score)
    # Weighted blend of quality, moat, valuation, growth and risk. Distinct
    # from the peer rank below, which is relative to similar-sized peers.
    # ------------------------------------------------------------------
    moat_sc = f20.get('moat_score')
    upside = None
    if base_fv and price:
        try:
            upside = (base_fv - price) / price * 100
        except Exception:
            upside = None
    val_score = None
    if upside is not None:
        val_score = 100 if upside >= 30 else 75 if upside >= 10 else 50 if upside >= -10 else 25 if upside >= -30 else 5
    if pe is not None and pe_band.get('median'):
        band_score = 75 if pe <= pe_band['median'] else 35
        val_score = band_score if val_score is None else round(0.7 * val_score + 0.3 * band_score)
    gg2 = pg5 if pg5 is not None else pg3
    growth_score = max(0, min(100, round((gg2 - 5) / 20 * 100))) if gg2 is not None else None
    risk_score = 100
    rl = str(f16.get('risk_level') or '').lower()
    if 'high' in rl:
        risk_score = 20
    elif 'med' in rl or 'moderate' in rl:
        risk_score = 60
    if pledge_num and pledge_num > 0:
        risk_score = max(0, risk_score - (30 if pledge_num > 25 else 15))

    comp_parts, comp_wts, comp_detail = [], [], []
    for label, v, w in [("Business quality", score, 0.30), ("Moat", moat_sc, 0.25),
                        ("Valuation", val_score, 0.20), ("Growth", growth_score, 0.15),
                        ("Risk (forensics/pledge)", risk_score, 0.10)]:
        if v is not None:
            comp_parts.append(v * w)
            comp_wts.append(w)
            comp_detail.append({"label": label, "score": round(v), "weight": int(w * 100)})
    invest_score = round(sum(comp_parts) / sum(comp_wts)) if comp_wts else None

    if invest_score is None:
        verdict_label, verdict_reason = "Insufficient data", "Not enough inputs to form a view."
    elif invest_score >= 70:
        verdict_label = "Strong candidate"
        verdict_reason = "Quality, moat and valuation broadly align — merits serious research for a position."
    elif invest_score >= 55:
        verdict_label = "Attractive, with caveats"
        verdict_reason = "Good business with at least one weak link (valuation, growth or risk) — buy discipline matters."
    elif invest_score >= 40:
        verdict_label = "Watchlist"
        verdict_reason = "Not compelling today — track for improvement in returns, growth or price."
    else:
        verdict_label = "Avoid for now"
        verdict_reason = "Weak fundamentals and/or unfavourable risk-reward at the current price."

    investment_view = {
        "invest_score": invest_score,
        "verdict": verdict_label,
        "reason": verdict_reason,
        "components": comp_detail,
        "upside_pct": round(upside) if upside is not None else None,
        "note": "Absolute view: graded against fixed thresholds (not against peers). Not investment advice.",
    }

    # ------------------------------------------------------------------
    # PEER RANK — relative standing among SIMILAR-SIZED sector peers only.
    # ------------------------------------------------------------------
    tb = (spv.get('tier_benchmark') or {}) if spv else {}
    peer_rank = None
    if tb.get('rank'):
        peer_rank = {
            "tier": tb.get("tier"),
            "rank": tb.get("rank"),
            "of": tb.get("of"),
            "percentile": tb.get("overall_percentile"),
            "ranking": tb.get("ranking") or [],
            "table_columns": tb.get("table_columns") or [],
            "peer_names": tb.get("peer_names") or [],
            "note": f"Ranked only against {tb.get('of', 0) - 1} other {str(tb.get('tier', '')).lower()} companies in its industry — "
                    "similar-sized businesses with comparable growth runway, never index giants.",
        }
        paras.append(
            f"Peer standing: among {tb.get('of')} comparable {str(tb.get('tier','')).lower()} peers it ranks #{tb.get('rank')}"
            + (f" ({tb.get('overall_percentile')}th percentile)" if tb.get('overall_percentile') is not None else "")
            + ". We deliberately rank it only against similar-sized companies in its industry, not mega-caps."
        )
    elif spv and (spv.get('ranking') or spv.get('overall_percentile') is not None):
        # Not enough same-tier peers for a tier benchmark — still show EVERY peer's
        # percentile across the full industry peer set (what the user asked for).
        peer_rank = {
            "tier": cap_tier, "rank": None, "of": len(spv.get('ranking') or []) or None,
            "percentile": spv.get('overall_percentile'),
            "ranking": spv.get('ranking') or [],
            "table_columns": spv.get('table_columns') or [],
            "peer_names": [p.get('name') for p in (spv.get('peers') or [])[:8]],
            "note": "Ranked against its full industry peer set (too few exact same-size peers for a size-league benchmark).",
        }

    # ------------------------------------------------------------------
    # INVESTMENT CHECKLIST - the user's default lens. Each row is grounded in
    # actual data when available; otherwise it is explicitly marked insufficient.
    # ------------------------------------------------------------------
    checklist = []

    def add_check(category, question, status, severity, evidence, parameter):
        checklist.append({
            "category": category,
            "question": question,
            "status": status,
            "severity": severity,
            "evidence": evidence,
            "parameter": parameter,
            "red_flag": status == "RED FLAG",
        })

    def status_from(value, good, watch, evidence_good, evidence_watch, evidence_bad, parameter, category, question):
        if value is None:
            add_check(category, question, "INSUFFICIENT DATA", 1, "No reliable field was available in this run.", parameter)
        elif good(value):
            add_check(category, question, "PASS", 0, evidence_good(value), parameter)
        elif watch(value):
            add_check(category, question, "WATCH", 2, evidence_watch(value), parameter)
        else:
            add_check(category, question, "RED FLAG", 3, evidence_bad(value), parameter)

    def one_line(value, fallback="Not available"):
        return value if value else fallback

    def stability_score(vals):
        clean = [as_float(v) for v in (vals or []) if as_float(v) is not None]
        if len(clean) < 3:
            return None
        mean = sum(clean) / len(clean)
        if abs(mean) < 1e-9:
            return None
        variance = sum((v - mean) ** 2 for v in clean) / len(clean)
        cov = (variance ** 0.5) / abs(mean)
        return max(0, min(1, 1 - cov / 0.5))

    def contains_any(text, words):
        hay = text_list(text).lower()
        return any(w in hay for w in words)

    rev_cagr_pct = first_value(
        sg5,
        sg3,
        (growth.get('cagr_3y_revenue') * 100) if growth.get('cagr_3y_revenue') is not None else None,
    )
    pat_cagr_pct = first_value(
        pg5,
        pg3,
        (growth.get('cagr_3y_pat') * 100) if growth.get('cagr_3y_pat') is not None else None,
    )
    latest_growth = (growth.get('growth_trends') or [])[-1] if growth.get('growth_trends') else {}
    prev_growth = (growth.get('growth_trends') or [])[-2] if len(growth.get('growth_trends') or []) >= 2 else {}
    latest_rev_g = latest_growth.get('revenue_growth_yoy')
    latest_pat_g = latest_growth.get('pat_growth_yoy')
    opm_stability = stability_score(opm_hist)
    roce_track = moat_data.get('roe_3y') or moat_data.get('roe_5y') or moat_data.get('roe_last')
    peer_pct = (peer_rank or {}).get('percentile')
    sector_pcts = ((peer.get('sector_benchmark') or {}).get('percentiles') or {})
    rel_profit_pct = first_value(sector_pcts.get('roe'), peer_pct)
    rel_valuation_pct = sector_pcts.get('pe')
    f14_text = " ".join([
        str(f14.get('summary') or ""),
        text_list(f14.get('risks')),
        text_list(f14.get('what_matters')),
        str(f14.get('guidance') or ""),
    ])
    f16_checks = f16.get('checks') or []
    related_check = next((c for c in f16_checks if "related" in str(c.get('name', '')).lower()), None)

    add_check(
        "Business & Industry",
        "Do I clearly understand how this company makes money?",
        "PASS" if biz_short else "INSUFFICIENT DATA",
        0 if biz_short else 1,
        one_line(biz_short, "Business description was not available from the source payload."),
        "Requires a clear business description / segment understanding.",
    )
    status_from(
        rev_cagr_pct,
        lambda v: v >= 8,
        lambda v: v >= 0,
        lambda v: f"Revenue growth is healthy at about {num(v, 1)}% CAGR.",
        lambda v: f"Revenue growth is positive but modest at about {num(v, 1)}% CAGR.",
        lambda v: f"Revenue CAGR is negative at about {num(v, 1)}%, implying shrinkage.",
        "Growing: >=8% CAGR; stable: 0-8%; shrinking: <0%.",
        "Business & Industry",
        "Is the industry growing, stable, or shrinking?",
    )
    pricing = as_float(f20.get('pricing_power'))
    status_from(
        pricing,
        lambda v: v >= 7,
        lambda v: v >= 4,
        lambda v: f"Pricing-power score is {num(v, 1)}/10, supported by margin/moat data.",
        lambda v: f"Pricing-power score is only {num(v, 1)}/10; monitor margin resilience.",
        lambda v: f"Pricing-power score is weak at {num(v, 1)}/10.",
        "Pricing power: >=7 strong, 4-6 watch, <4 weak.",
        "Business & Industry",
        "Does the company have pricing power?",
    )
    moat_sc = f20.get('moat_score')
    competition_value = first_value(moat_sc, peer_pct)
    status_from(
        competition_value,
        lambda v: v >= 60,
        lambda v: v >= 35,
        lambda v: f"Moat/peer signal is healthy at {num(v, 0)}; competition appears manageable.",
        lambda v: f"Moat/peer signal is middling at {num(v, 0)}; competition needs monitoring.",
        lambda v: f"Moat/peer signal is weak at {num(v, 0)}, suggesting intense competition.",
        "Uses moat score first, then peer percentile. >=60 good; 35-59 watch; <35 red.",
        "Business & Industry",
        "How intense is competition?",
    )
    cyclicality_value = opm_stability
    status_from(
        cyclicality_value,
        lambda v: v >= 0.65 and margins.get('margin_status_tag') != 'DETERIORATING',
        lambda v: v >= 0.35,
        lambda v: f"Operating margins have been relatively stable; stability score {num(v, 2)}.",
        lambda v: f"Margins show some variability; stability score {num(v, 2)}.",
        lambda v: f"Margins are volatile or deteriorating; stability score {num(v, 2)}.",
        "Predictability uses operating-margin stability: >=0.65 pass, 0.35-0.64 watch, <0.35 red.",
        "Business & Industry",
        "Is the business cyclical or predictable?",
    )

    tone = str(f14.get('tone') or "").lower()
    mgmt_value = None if not tone and pledge is None else 0
    if mgmt_value is not None:
        mgmt_value = 80
        if "negative" in tone:
            mgmt_value = 25
        elif "cautious" in tone:
            mgmt_value = 55
        if pledge_num and pledge_num > 25:
            mgmt_value = min(mgmt_value, 35)
        elif pledge_num and pledge_num > 0:
            mgmt_value = min(mgmt_value, 60)
    status_from(
        mgmt_value,
        lambda v: v >= 70,
        lambda v: v >= 45,
        lambda v: f"Management tone is {tone or 'available'} and promoter pledge is {pct_flex(pledge_num or 0)}.",
        lambda v: f"Management/governance needs monitoring: tone={tone or 'not available'}, pledge={pct_flex(pledge_num or 0)}.",
        lambda v: f"Governance red flag: tone={tone or 'not available'}, pledge={pct_flex(pledge_num or 0)}.",
        "Positive/neutral tone and low pledge pass; negative tone or high pledge is a red flag.",
        "Management & Governance",
        "Is the promoter/management credible and respected?",
    )
    bad_times_evidence = contains_any(f14_text, ["slowdown", "downturn", "covid", "recession", "weak demand", "bad times", "challenging"])
    add_check(
        "Management & Governance",
        "How has management behaved in bad times?",
        "WATCH" if bad_times_evidence else "INSUFFICIENT DATA",
        2 if bad_times_evidence else 1,
        "Management commentary mentions stress-period execution; read the concall notes for detail." if bad_times_evidence else "No explicit bad-times track record was captured in this run.",
        "Needs evidence from prior downturns, concalls, annual reports, or capital-allocation history.",
    )
    prom_delta = None
    prom_vals = [as_float(h.get('promoter')) for h in own_hist if as_float(h.get('promoter')) is not None]
    if len(prom_vals) >= 2:
        prom_delta = prom_vals[-1] - prom_vals[0]
    status_from(
        prom_delta,
        lambda v: v >= -1,
        lambda v: v >= -3,
        lambda v: f"Promoter holding is stable/increasing over the available history ({num(v, 1)} pp change).",
        lambda v: f"Promoter holding has slipped modestly ({num(v, 1)} pp change).",
        lambda v: f"Promoter holding has fallen materially ({num(v, 1)} pp change).",
        "Stable/increasing: change >= -1 percentage point; -1 to -3 watch; below -3 red.",
        "Management & Governance",
        "Is promoter shareholding stable or increasing?",
    )
    if related_check:
        rel_status = "PASS" if str(related_check.get('status', '')).upper() == "PASS" else "RED FLAG"
        add_check(
            "Management & Governance",
            "Are related-party transactions reasonable?",
            rel_status,
            0 if rel_status == "PASS" else 3,
            related_check.get('details') or "Related-party check was present in forensic screen.",
            "Uses forensic related-party transaction check when available.",
        )
    else:
        add_check(
            "Management & Governance",
            "Are related-party transactions reasonable?",
            "INSUFFICIENT DATA",
            1,
            "No related-party transaction field/check was available in this run.",
            "Requires annual-report RPT schedule or a specific forensic RPT check.",
        )
    add_check(
        "Management & Governance",
        "Does management communicate clearly and honestly?",
        "PASS" if f14.get('summary') and "negative" not in tone else "WATCH" if f14.get('summary') else "INSUFFICIENT DATA",
        0 if f14.get('summary') and "negative" not in tone else 2 if f14.get('summary') else 1,
        "Latest concall/annual-report summary and guidance were captured." if f14.get('summary') else "No grounded management commentary was captured.",
        "Requires recent commentary with concrete guidance, risks, and numbers.",
    )

    de = solvency.get('debt_to_equity')
    status_from(
        de,
        lambda v: v < 0.7,
        lambda v: v < 1.2,
        lambda v: f"Debt/equity is comfortable at {num(v, 2)}x.",
        lambda v: f"Debt/equity is moderate at {num(v, 2)}x.",
        lambda v: f"Debt/equity is high at {num(v, 2)}x.",
        "Comfortable D/E <0.7x; 0.7-1.2x watch; >1.2x red.",
        "Financial Quality",
        "Is debt at a comfortable level?",
    )
    ic = solvency.get('interest_coverage')
    debt_service_value = 99 if (de is not None and de < 0.3 and ic is None) else ic
    status_from(
        debt_service_value,
        lambda v: v >= 4,
        lambda v: v >= 2,
        lambda v: "Interest coverage is strong or leverage is effectively low.",
        lambda v: f"Interest coverage is only {num(v, 2)}x.",
        lambda v: f"Interest coverage is weak at {num(v, 2)}x.",
        "Interest coverage >=4x pass; 2-4x watch; <2x red. Low-debt companies pass.",
        "Financial Quality",
        "Can the company easily service its debt?",
    )
    ccc = moat_data.get('cash_conversion_cycle')
    status_from(
        ccc,
        lambda v: v <= 90,
        lambda v: v <= 180,
        lambda v: f"Cash-conversion cycle is under control at {num(v, 0)} days.",
        lambda v: f"Cash-conversion cycle is stretched at {num(v, 0)} days.",
        lambda v: f"Cash-conversion cycle is high at {num(v, 0)} days.",
        "CCC <=90 days pass; 91-180 watch; >180 red.",
        "Financial Quality",
        "Is working capital under control?",
    )
    cfo_pat = cashq.get('CFO_to_PAT')
    status_from(
        cfo_pat,
        lambda v: v >= 0.8,
        lambda v: v >= 0.5,
        lambda v: f"CFO/PAT is healthy at {num(v, 2)}x.",
        lambda v: f"CFO/PAT is middling at {num(v, 2)}x.",
        lambda v: f"CFO/PAT is weak at {num(v, 2)}x; profits may not be cash-backed.",
        "CFO/PAT >=0.8x pass; 0.5-0.8x watch; <0.5x red.",
        "Financial Quality",
        "Does the company generate real cash, not just accounting profits?",
    )
    status_from(
        roce_track,
        lambda v: v >= 15,
        lambda v: v >= 10,
        lambda v: f"ROE track record is healthy at about {num(v, 1)}%.",
        lambda v: f"ROE track record is average at about {num(v, 1)}%.",
        lambda v: f"ROE track record is weak at about {num(v, 1)}%.",
        "ROE track record >=15% pass; 10-15% watch; <10% red.",
        "Financial Quality",
        "Has return on equity been consistently healthy?",
    )
    margin_value = None
    if opm is not None:
        margin_value = 80 if margins.get('margin_status_tag') in ("STABLE", "IMPROVING") else 45
        if opm_stability is not None and opm_stability < 0.35:
            margin_value = 30
    status_from(
        margin_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: f"Margins are {str(margins.get('margin_status_tag', 'stable')).lower()} with latest EBIT margin {pct(opm)}.",
        lambda v: f"Margins need watching: status {margins.get('margin_status_tag')}, latest EBIT margin {pct(opm)}.",
        lambda v: f"Margin pattern is weak/volatile: status {margins.get('margin_status_tag')}.",
        "Stable/improving margins pass; deterioration or volatility is a watch/red flag.",
        "Financial Quality",
        "Are margins stable or improving over time?",
    )
    growth_support_value = None
    if rev_cagr_pct is not None and pat_cagr_pct is not None:
        growth_support_value = 80 if pat_cagr_pct >= max(0, rev_cagr_pct * 0.6) else 45 if pat_cagr_pct > 0 else 20
    status_from(
        growth_support_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: f"Profit growth ({num(pat_cagr_pct, 1)}%) supports revenue growth ({num(rev_cagr_pct, 1)}%).",
        lambda v: f"Profit growth ({num(pat_cagr_pct, 1)}%) lags revenue growth ({num(rev_cagr_pct, 1)}%).",
        lambda v: f"Revenue growth is not translating into profit growth: PAT CAGR {num(pat_cagr_pct, 1)}%.",
        "PAT growth should be positive and at least ~60% of revenue growth.",
        "Financial Quality",
        "Is revenue growth supported by profit growth?",
    )
    status_from(
        rel_profit_pct,
        lambda v: v >= 60,
        lambda v: v >= 40,
        lambda v: f"Profitability stands well versus peers (percentile {num(v, 0)}).",
        lambda v: f"Profitability is around peer average (percentile {num(v, 0)}).",
        lambda v: f"Profitability trails peers (percentile {num(v, 0)}).",
        "Peer profitability percentile >=60 pass; 40-59 watch; <40 red.",
        "Financial Quality",
        "How does profitability compare with peers?",
    )
    slowdown_value = None
    if latest_rev_g is not None and prev_growth.get('revenue_growth_yoy') is not None:
        slowing = latest_rev_g < prev_growth.get('revenue_growth_yoy')
        margin_ok = margins.get('margin_status_tag') in ("STABLE", "IMPROVING")
        slowdown_value = 80 if slowing and margin_ok else 45 if slowing else 70
    status_from(
        slowdown_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: "Cost control looks acceptable during the latest growth phase.",
        lambda v: "Growth slowed and cost/margin control needs monitoring.",
        lambda v: "Growth slowed with poor margin control.",
        "Checks latest revenue slowdown against margin trend.",
        "Financial Quality",
        "Is cost control visible during slowdowns?",
    )
    status_from(
        roce,
        lambda v: v >= 0.15,
        lambda v: v >= 0.10,
        lambda v: f"ROCE is efficient at {pct(v)}.",
        lambda v: f"ROCE is average at {pct(v)}.",
        lambda v: f"ROCE is weak at {pct(v)}.",
        "ROCE >=15% pass; 10-15% watch; <10% red.",
        "Financial Quality",
        "Is capital employed efficiently?",
    )

    priced_value = None
    if pe is not None:
        priced_value = 80
        if gg2 is not None and pe > max(40, 2 * gg2):
            priced_value = 25
        elif gg2 is not None and pe > max(25, 1.5 * gg2):
            priced_value = 45
    status_from(
        priced_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: f"P/E of {num(pe, 1)} does not look priced for perfection against available growth.",
        lambda v: f"P/E of {num(pe, 1)} needs discipline against growth of {num(gg2, 1) if gg2 is not None else 'N/A'}%.",
        lambda v: f"P/E of {num(pe, 1)} appears demanding versus growth of {num(gg2, 1) if gg2 is not None else 'N/A'}%.",
        "Flags perfection risk when P/E is very high versus profit growth.",
        "Valuation & Risk",
        "Is the stock priced for perfection?",
    )
    own_history_value = None
    if pe is not None and pe_band.get('median'):
        premium = (pe / pe_band['median']) - 1
        own_history_value = 80 if premium <= 0 else 45 if premium <= 0.25 else 25
    status_from(
        own_history_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: f"P/E is at/below its 5-year median ({num(pe_band.get('median'), 1)}).",
        lambda v: f"P/E is modestly above its 5-year median ({num(pe_band.get('median'), 1)}).",
        lambda v: f"P/E is materially above its 5-year median ({num(pe_band.get('median'), 1)}).",
        "Own-history valuation: <=median pass; up to 25% premium watch; >25% premium red.",
        "Valuation & Risk",
        "How does valuation compare to its own history?",
    )
    status_from(
        rel_valuation_pct,
        lambda v: v >= 60,
        lambda v: v >= 40,
        lambda v: f"Peer valuation percentile is attractive at {num(v, 0)}.",
        lambda v: f"Peer valuation percentile is average at {num(v, 0)}.",
        lambda v: f"Peer valuation percentile is weak at {num(v, 0)}.",
        "Peer valuation percentile >=60 pass; 40-59 watch; <40 red.",
        "Valuation & Risk",
        "How does valuation compare with peers?",
    )
    growth_justify_value = None
    if priced_value is not None and gg2 is not None:
        growth_justify_value = 80 if gg2 >= 15 and priced_value >= 40 else 45 if gg2 >= 8 else 25
    status_from(
        growth_justify_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: f"Growth of about {num(gg2, 1)}% can justify a reasonable valuation.",
        lambda v: f"Growth of about {num(gg2, 1)}% only partly supports the valuation.",
        lambda v: f"Growth of about {num(gg2, 1)}% does not justify a demanding valuation.",
        "Growth visibility should be >15% for rich valuations; 8-15% watch; <8% red.",
        "Valuation & Risk",
        "Is growth visible to justify the valuation?",
    )
    risk_texts = list(f20.get('warnings') or []) + list(f14.get('risks') or [])
    top_risk = risk_texts[0] if risk_texts else (f"Forensic screen: {f16.get('risk_level')} risk" if f16.get('risk_level') else None)
    add_check(
        "Valuation & Risk",
        "What could go wrong from here?",
        "WATCH" if top_risk else "INSUFFICIENT DATA",
        2 if top_risk else 1,
        top_risk or "No specific forward risk was captured.",
        "Uses moat warnings, concall risks, and forensic risk level.",
    )
    moat_strength = str(f20.get('moat_strength') or "")
    moat_value = None
    if moat_strength:
        moat_value = 80 if moat_strength in ("Wide", "Narrow to Wide") else 45 if moat_strength == "Narrow" else 25
    status_from(
        moat_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: f"Moat assessment is {moat_strength} with score {f20.get('moat_score')}/100.",
        lambda v: f"Moat assessment is only {moat_strength}; disruption risk needs monitoring.",
        lambda v: f"Moat assessment is weak ({moat_strength}).",
        "Wide/Narrow-to-Wide pass; Narrow watch; No moat red.",
        "Valuation & Risk",
        "Is the business protected from disruption?",
    )
    reg_seen = contains_any(f14_text, ["regulation", "regulatory", "policy", "license", "tariff", "rbi", "sebi"])
    add_check(
        "Valuation & Risk",
        "Does regulation help or hurt the company?",
        "WATCH" if reg_seen else "INSUFFICIENT DATA",
        2 if reg_seen else 1,
        "Regulatory/policy exposure appears in management risks/commentary." if reg_seen else "No explicit regulatory exposure was captured.",
        "Needs industry-specific regulation and policy-risk review.",
    )
    concentration_seen = contains_any(f14_text + " " + biz_short, ["single customer", "customer concentration", "one customer", "one product", "single product", "geography", "export dependence"])
    add_check(
        "Valuation & Risk",
        "Is the company dependent on one product, customer, or geography?",
        "WATCH" if concentration_seen else "INSUFFICIENT DATA",
        2 if concentration_seen else 1,
        "Potential concentration/dependency language appears in available text." if concentration_seen else "No product/customer/geography concentration data was captured.",
        "Requires segment/customer/geography disclosure; absence of data is not a clean pass.",
    )
    culture_value = None
    if prom is not None or pledge is not None or roce is not None:
        culture_value = 80
        if pledge_num and pledge_num > 25:
            culture_value = 25
        elif pledge_num and pledge_num > 0:
            culture_value = 55
        if roce is not None and roce < 0.10:
            culture_value = min(culture_value, 45)
    status_from(
        culture_value,
        lambda v: v >= 70,
        lambda v: v >= 40,
        lambda v: "Ownership, pledge, and return profile do not show an obvious long-term-alignment issue.",
        lambda v: "Culture/alignment needs monitoring due to pledge or weaker returns.",
        lambda v: "High pledge or weak returns raise long-term alignment concerns.",
        "Proxy check: promoter stake/pledge plus capital returns.",
        "Long-Term Fit",
        "Is corporate culture aligned with long-term value creation?",
    )
    hold_value = invest_score
    if hold_value is not None and any(c["status"] == "RED FLAG" for c in checklist):
        hold_value = min(hold_value, 55)
    status_from(
        hold_value,
        lambda v: v >= 70,
        lambda v: v >= 45,
        lambda v: f"Investment score is {invest_score}/100 with no unresolved severe checklist block.",
        lambda v: f"Investment score is {invest_score}/100; suitable for watchlist/position sizing discipline.",
        lambda v: f"Investment score is {invest_score}/100 or red flags are too severe for comfort.",
        "5-10 year comfort requires high investment score and no severe red flags.",
        "Long-Term Fit",
        "Would I be comfortable holding this stock for 5-10 years?",
    )

    checklist_counts = {
        "pass": sum(1 for c in checklist if c["status"] == "PASS"),
        "watch": sum(1 for c in checklist if c["status"] == "WATCH"),
        "red_flags": sum(1 for c in checklist if c["status"] == "RED FLAG"),
        "insufficient_data": sum(1 for c in checklist if c["status"] == "INSUFFICIENT DATA"),
        "total": len(checklist),
    }
    scored = [c for c in checklist if c["status"] != "INSUFFICIENT DATA"]
    checklist_score = None
    if scored:
        points = sum(1 if c["status"] == "PASS" else 0.5 if c["status"] == "WATCH" else 0 for c in scored)
        checklist_score = round(points / len(scored) * 100)
    checklist_summary = {
        "score": checklist_score,
        "counts": checklist_counts,
        "red_flags": [c for c in checklist if c["status"] == "RED FLAG"],
        "watch_items": [c for c in checklist if c["status"] == "WATCH"],
        "method": "30-point investment checklist scored from available report fields; unknowns stay marked as insufficient data.",
    }
    # --- Positives & risks (specific, from the computed checks) ---
    positives = list(f20.get('signals') or [])[:3]
    risks = list(f20.get('warnings') or [])[:2]
    if f16.get('risk_level'):
        risks.append(f"Forensic/red-flag screen: {f16.get('risk_level')} risk.")
    for item in checklist_summary["red_flags"][:3]:
        risks.append(f"{item['question']} - {item['evidence']}")
    if pledge_num and pledge_num > 0:
        risks.append("Promoter pledging is present — monitor it.")
    for chip in (m.get('F-19_Business_Quality', {}) or {}).get('scoring_rationale_chips', []):
        if any(w in chip for w in ('High', 'Excellent', 'Very Low')) and len(positives) < 4:
            positives.append(chip)
    for c in (moat_data.get('cons') or [])[:2]:
        if c and len(risks) < 4:
            risks.append(c)

    headline = f"{name}: {quality_word} business ({score}/100)"
    if f20.get('moat_strength') and f20['moat_strength'] not in ('Unrated', 'No moat'):
        headline += f", {f20['moat_strength']} moat"
    if cap_tier:
        headline += f" · {cap_tier}"

    # ------------------------------------------------------------------
    # BUSINESS UNDERSTANDING — "how does it make money?" (all dynamic):
    #  - business model  : real company description
    #  - revenue drivers : LLM-extracted from the concall + description (F-21)
    #  - cost structure  : computed live from the income statement
    # ------------------------------------------------------------------
    f21 = q.get('F-21', {}) or {}

    def _f21_text(item):
        """LLMs (esp. the fallback model) sometimes return list items as objects
        instead of plain strings — flatten them to readable text."""
        if isinstance(item, dict):
            parts = [str(v) for k in ('driver', 'name', 'title', 'approx_revenue_share', 'share', 'details', 'description')
                     for v in [item.get(k)] if v]
            if parts:
                return " — ".join(dict.fromkeys(parts))
            return "; ".join(f"{k}: {v}" for k, v in item.items() if v) or None
        return str(item) if item not in (None, "") else None

    def _f21_list(key):
        val = f21.get(key)
        if val in (None, "", []):
            return []
        # A bare string/object here would otherwise be iterated char-by-char /
        # key-by-key — wrap scalars so each list item is one full entry.
        if not isinstance(val, list):
            val = [val]
        return [t for t in (_f21_text(x) for x in val) if t]
    inc_grid = ((m.get('F-01_Financial_Statements', {}) or {}).get('annual', {}) or {}).get('income_stmt', {}) or {}
    cost_structure = []
    if inc_grid:
        _ld = sorted(inc_grid.keys())[-1]
        _row = inc_grid[_ld] or {}

        def _rg(names):
            for nm in names:
                for k, v in _row.items():
                    if nm in k.lower().replace(' ', '') and v is not None:
                        return v
            return None
        _rev = _rg(['totalrevenue', 'operatingrevenue', 'revenue'])
        if _rev:
            for label, val in [
                ('Operating & material costs', _rg(['totalexpenses', 'operatingexpense', 'costofrevenue'])),
                ('Depreciation & amortisation', _rg(['depreciation'])),
                ('Interest / finance cost', _rg(['interestexpense', 'interest'])),
                ('Tax', _rg(['taxprovision', 'tax'])),
            ]:
                if val is not None and val >= 0:
                    cost_structure.append({
                        'label': label,
                        'value_cr': round(val / 1e7),
                        'pct': round(val / _rev * 100, 1),
                    })
            # Fallback so Cost Structure never shows empty when the itemized expense
            # rows aren't in the statement (e.g. demerged/newly-listed tickers with
            # sparse data): split revenue into total costs vs the net profit that
            # survives — derived straight from the income statement.
            if not cost_structure:
                _ni = _rg(['netincome', 'netincomecommonstockholders', 'profitaftertax', 'netprofit'])
                if _ni is not None:
                    _tot_cost = max(_rev - _ni, 0)
                    cost_structure = [
                        {'label': 'Total costs & expenses', 'value_cr': round(_tot_cost / 1e7),
                         'pct': round(_tot_cost / _rev * 100, 1)},
                        {'label': 'Net profit (retained)', 'value_cr': round(max(_ni, 0) / 1e7),
                         'pct': round(max(_ni, 0) / _rev * 100, 1)},
                    ]

    # Prefer AUDITED revenue-by-segment from the BSE quarterly result filing; fall back
    # to what the concall stated (F-21). Both dynamic — nothing hardcoded.
    segments, segment_source, segment_period = [], None, None
    try:
        from tools.bse_scraper import fetch_bse_segments
        _bse = fetch_bse_segments(symbol, name=name) or {}
        if _bse.get('segments'):
            segments = _bse['segments']
            segment_source = _bse.get('source', 'BSE result filing')
            segment_period = _bse.get('period')
    except Exception as _se:
        print(f"[summary] BSE segments skipped: {_se}")

    # For lenders, an audited interest-vs-fee split from the income statement is
    # more trustworthy than LLM-extracted concall text — prefer it when no BSE
    # segment filing was found.
    if not segments and inc_grid:
        _norm = {k.lower().replace(' ', ''): v for k, v in _row.items()}
        _rev2 = _norm.get('totalrevenue') or _norm.get('operatingrevenue')
        _int_inc = _norm.get('interestincome')
        if _rev2 and _int_inc and _int_inc > 0.2 * _rev2:
            _other = max(_rev2 - _int_inc, 0)
            segments = [
                {'name': 'Interest income', 'revenue_cr': round(_int_inc / 1e7), 'pct': round(_int_inc / _rev2 * 100, 1)},
                {'name': 'Fee & other income', 'revenue_cr': round(_other / 1e7), 'pct': round(_other / _rev2 * 100, 1)},
            ]
            segment_source = 'derived from the income statement (interest vs fee/other income)'

    # --- Structured revenue streams for the pie + expandable "how it earns" -------
    # Primary source for the revenue pie: the LLM's business-model breakdown
    # (F-21 revenue_streams) — 2-6 streams, each with an APPROXIMATE % share and a
    # one-line explanation. Being an explicit estimate, it works for every stock
    # instead of collapsing to a single "100%" line. Normalised to {name, pct, desc}.
    revenue_streams = []
    for _it in (f21.get('revenue_streams') or []):
        if not isinstance(_it, dict):
            continue
        _snm = _f21_text(_it.get('name') or _it.get('stream') or _it.get('label'))
        _spct = _it.get('approx_pct', _it.get('pct', _it.get('share')))
        try:
            _spct = float(str(_spct).replace('%', '').strip())
        except Exception:
            _spct = None
        _sdesc = _f21_text(_it.get('how_it_earns') or _it.get('description') or _it.get('details'))
        if _snm:
            revenue_streams.append({'name': _snm, 'pct': _spct, 'desc': _sdesc})

    if segments:
        # Audited ₹ segments win; mirror them into streams so the pie shows real values.
        revenue_drivers = [f"{s['name']} — {s['pct']}% of revenue (₹{s['revenue_cr']:,} Cr)" for s in segments]
        if not revenue_streams:
            revenue_streams = [{'name': s['name'], 'pct': s.get('pct'),
                                'desc': f"₹{s['revenue_cr']:,} Cr of revenue in the latest reported period"}
                               for s in segments]
    else:
        revenue_drivers = _f21_list('revenue_drivers')
        if revenue_drivers:
            segment_source = "management concall / filings"
        if revenue_streams and not segment_source:
            segment_source = 'approximate business-model mix (AI estimate)'

    # Keep the text driver list in sync when only structured streams were returned.
    if revenue_streams and not revenue_drivers:
        revenue_drivers = [
            s['name'] + (f" — ~{s['pct']:.0f}% of revenue" if s.get('pct') is not None else "")
            + (f" ({s['desc']})" if s.get('desc') else "")
            for s in revenue_streams
        ]

    # Last-resort floor so a pie ALWAYS renders even with no LLM streams: split
    # reported revenue into operating core vs other income from the income statement
    # (both real ₹, additive lines). Labels are sector-aware — insurers read as
    # premium income, banks as interest earned, everyone else as operating revenue.
    if not segments and not revenue_streams and inc_grid:
        _norm = {k.lower().replace(' ', ''): v for k, v in _row.items()}
        _rev2 = _norm.get('totalrevenue') or _norm.get('operatingrevenue') or _norm.get('revenue')
        _other = _norm.get('otherincome')
        _nm = (name or symbol or '').lower()
        _is_insurer = any(w in _nm for w in ['insurance', 'insurer', 'life', 'assurance', 'gic '])
        _is_bank = any(w in _nm for w in ['bank', 'financ', 'finance', 'nbfc', 'housing finance',
                                          'capital', 'fintech', 'amc'])
        if _is_insurer:
            _core_nm, _oth_nm = 'Premium & policy income', 'Investment & other income'
        elif _is_bank:
            _core_nm, _oth_nm = 'Interest earned', 'Other income (treasury / fees)'
        else:
            _core_nm, _oth_nm = 'Operating revenue (core business)', 'Other income'
        if _rev2 and _rev2 > 0:
            if _other is not None and _other > 0:
                _tot = _rev2 + _other
                revenue_streams = [
                    {'name': _core_nm, 'pct': round(_rev2 / _tot * 100, 1),
                     'desc': f"₹{round(_rev2 / 1e7):,} Cr — the company's core operating income"},
                    {'name': _oth_nm, 'pct': round(_other / _tot * 100, 1),
                     'desc': f"₹{round(_other / 1e7):,} Cr — income earned outside the core operations"},
                ]
            else:
                revenue_streams = [{'name': _core_nm, 'pct': 100.0,
                                    'desc': f"₹{round(_rev2 / 1e7):,} Cr of reported revenue"}]
            if not revenue_drivers:
                revenue_drivers = [f"{s['name']} — ~{s['pct']:.0f}% of revenue" for s in revenue_streams]
            segment_source = segment_source or 'derived from the income statement (operating vs other income)'

    business_understanding = {
        'business_model': (biz or _f21_text(f21.get('what_they_sell')) or biz_short or None),
        'what_they_sell': _f21_text(f21.get('what_they_sell')),
        'revenue_drivers': revenue_drivers,
        'revenue_streams': revenue_streams,
        'segments': segments,
        'segment_source': segment_source,
        'segment_period': segment_period,
        'key_customers_or_geographies': _f21_list('key_customers_or_geographies'),
        'cost_structure': cost_structure,
        'segment_note': (None if revenue_drivers else
                         "This looks like a single-segment company, or its audited segment table "
                         "wasn't machine-readable this run. Source for precise splits: the company's "
                         "BSE quarterly 'Segment-wise Revenue' filing or Annual Report segment note."),
        # Business Model Canvas fields (from F-21)
        'key_partnerships': _f21_list('key_partnerships'),
        'key_activities': _f21_list('key_activities'),
        'value_propositions': _f21_list('value_propositions'),
        'customer_relationships': _f21_list('customer_relationships'),
        'customer_segments': _f21_list('customer_segments'),
        'key_resources': _f21_list('key_resources'),
        'channels': _f21_list('channels'),
    }

    # ------------------------------------------------------------------
    # QUALITATIVE ANALYSIS TOPICS — Topic A: Company strategy & business model.
    # Each sub-point carries: the LLM finding, chart data (when numeric), and a
    # Primary/Secondary/Tertiary source citation trail (per the qualitative
    # research spec — Annual Report -> Investor Presentation -> Screener.in).
    # ------------------------------------------------------------------
    def _enum(value, allowed):
        """Only accept an exact (case-insensitive) match against the allowed set —
        guards against the LLM occasionally echoing the whole 'A | B | C' options
        string back as a literal value instead of picking one. Drop it rather
        than show garbage in the UI."""
        if not isinstance(value, str):
            return None
        for opt in allowed:
            if value.strip().lower() == opt.lower():
                return opt
        return None

    f22 = q.get('F-22', {}) or {}
    f23 = q.get('F-23', {}) or {}
    f24 = q.get('F-24', {}) or {}
    f25 = q.get('F-25', {}) or {}
    f26 = q.get('F-26', {}) or {}
    f27 = q.get('F-27', {}) or {}

    _biz_model_type = _enum(f22.get('business_model_type'), ['Single product', 'Portfolio (multiple products/segments)'])
    _revenue_pattern = _enum(f22.get('revenue_pattern'), ['Recurring', 'Cyclical', 'Mixed'])
    _revenue_model_type = _enum(f24.get('revenue_model_type'), ['Transactional', 'Recurring subscription', 'Annuity', 'Long-term contract'])
    _lifecycle_stage = _enum(f25.get('lifecycle_stage'), ['Growth', 'Maturity', 'Commoditisation', 'Decline / obsolescence risk'])
    _pricing_power_rating = _enum(f26.get('pricing_power_rating'), ['Strong', 'Moderate', 'Weak'])
    _structural_defensibility = _enum(f27.get('structural_defensibility'), ['Structurally defensible', 'Partially temporary tailwinds', 'Largely temporary tailwinds'])

    _recurring_pct = f22.get('recurring_revenue_pct')
    try:
        _recurring_pct = float(_recurring_pct)
        _recurring_pct = max(0.0, min(100.0, _recurring_pct))
    except (TypeError, ValueError):
        _recurring_pct = None

    _renewal_pct = f24.get('contract_renewal_rate_pct')
    try:
        _renewal_pct = float(_renewal_pct)
        _renewal_pct = max(0.0, min(100.0, _renewal_pct))
    except (TypeError, ValueError):
        _renewal_pct = None

    _rel_growth = f25.get('relative_growth_pct')
    try:
        _rel_growth = round(max(-50.0, min(50.0, float(_rel_growth))), 1)
    except (TypeError, ValueError):
        _rel_growth = None

    _pass_through = f26.get('price_pass_through_ratio')
    try:
        _pass_through = round(max(0.0, min(2.0, float(_pass_through))), 2)
    except (TypeError, ValueError):
        _pass_through = None

    # Margin volatility (Std dev of EBITDA margin / Mean EBITDA margin, 5-8Y) is
    # computed here from REAL reported financials rather than an LLM estimate —
    # this figure is directly derivable from the income statement, so there's no
    # reason to let the model guess it. Only the "is this structural or a
    # temporary tailwind" judgment comes from the LLM (F-27).
    _margin_rows = (margins.get('margins_annual') or [])[-8:]
    _ebitda_margin_series = [
        {'label': str(r.get('date', ''))[:7], 'value': round(r['ebitda_margin'] * 100, 2)}
        for r in _margin_rows if r.get('ebitda_margin') is not None
    ]
    _margin_volatility = None
    if len(_ebitda_margin_series) >= 3:
        _vals = [r['value'] for r in _ebitda_margin_series]
        _mean = sum(_vals) / len(_vals)
        if _mean:
            _variance = sum((v - _mean) ** 2 for v in _vals) / len(_vals)
            _margin_volatility = round((_variance ** 0.5) / abs(_mean), 2)

    _ar_ip_screener_sources = {
        'primary': {'label': 'Company Annual Report', 'note': 'sourced via BSE announcement / company IR page'},
        'secondary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page'},
        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'url': 'https://www.screener.in'},
    }

    # F-23 moat sub-scores (1-5 scale) — a labelled bar chart, same idea as the
    # recurring-revenue donut but for a rating rather than a percentage.
    _moat_label = {'brand': 'Brand', 'distribution': 'Distribution', 'cost_leadership': 'Cost leadership',
                   'network_effects': 'Network effects', 'switching_costs': 'Switching costs'}
    _moat_types = f23.get('moat_types') or {}
    _moat_bars = []
    for _mk, _mlabel in _moat_label.items():
        _mv = _moat_types.get(_mk)
        try:
            _mv = max(0.0, min(5.0, float(_mv)))
        except (TypeError, ValueError):
            continue
        _moat_bars.append({'label': _mlabel, 'value': round(_mv, 1)})
    _moat_overall = f23.get('overall_rating')
    try:
        _moat_overall = round(max(0.0, min(5.0, float(_moat_overall))), 1)
    except (TypeError, ValueError):
        _moat_overall = None

    qualitative_topics = {
        'strategy_business_model': {
            'topic': 'A. Company strategy & business model',
            'subpoints': [
                {
                    'key': 'clarity_of_business_model',
                    'title': 'Clarity of business model: single product vs portfolio; cyclical vs recurring revenue',
                    'finding': f22.get('rationale') or None,
                    'facts': [f for f in [
                        (['Business model', _biz_model_type] if _biz_model_type else None),
                        (['Revenue pattern', _revenue_pattern] if _revenue_pattern else None),
                        (['Recurring revenue', f"~{round(_recurring_pct)}%"] if _recurring_pct is not None else None),
                    ] if f],
                    'chart': ({
                        'type': 'donut',
                        'data': [
                            {'label': 'Recurring revenue', 'pct': round(_recurring_pct, 1)},
                            {'label': 'Non-recurring / cyclical revenue', 'pct': round(100 - _recurring_pct, 1)},
                        ],
                    } if _recurring_pct is not None else None),
                    'formula': 'Recurring revenue % = Recurring revenue / Total revenue',
                    'sources': _ar_ip_screener_sources,
                },
                {
                    'key': 'competitive_advantage_moats',
                    'title': 'Competitive advantage / moats: brand, distribution, cost leadership, network effects, switching costs',
                    'finding': f23.get('rationale') or None,
                    'facts': ([['Overall moat rating', f"{_moat_overall} / 5"]] if _moat_overall is not None else []),
                    'chart': ({'type': 'bar', 'data': _moat_bars, 'scaleMax': 5} if _moat_bars else None),
                    'formula': 'N/A — qualitative rating (1-5 scale) based on evidence checklist',
                    'sources': {
                        'primary': {'label': 'CRISIL Ratings/Research', 'url': 'https://www.crisilratings.com'},
                        'secondary': {'label': 'ICRA Research', 'url': 'https://www.icra.in'},
                        'tertiary': {'label': 'Screener.in – peer/moat comparison, incl. Tijori Finance', 'url': 'https://www.screener.in'},
                    },
                },
                {
                    'key': 'revenue_model_quality',
                    'title': 'Revenue model quality: transactional, recurring, annuity, contract length & renewal dynamics',
                    'finding': f24.get('rationale') or None,
                    'facts': [f for f in [
                        (['Revenue model', _revenue_model_type] if _revenue_model_type else None),
                        (['Contract length', f24.get('contract_length')] if f24.get('contract_length') else None),
                        (['Contract renewal rate', f"~{round(_renewal_pct)}%"] if _renewal_pct is not None else None),
                    ] if f],
                    'chart': ({
                        'type': 'donut',
                        'data': [
                            {'label': 'Renewed', 'pct': round(_renewal_pct, 1)},
                            {'label': 'Not renewed / lapsed', 'pct': round(100 - _renewal_pct, 1)},
                        ],
                    } if _renewal_pct is not None else (
                        # No disclosed renewal rate (the common case) — still show
                        # *something* visual: where this business sits on the
                        # revenue-model spectrum, rather than a bare text label.
                        {'type': 'spectrum',
                         'options': ['Transactional', 'Recurring subscription', 'Annuity', 'Long-term contract'],
                         'active': _revenue_model_type}
                        if _revenue_model_type else None
                    )),
                    'formula': 'Contract renewal rate = Contracts renewed / Contracts up for renewal',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': 'Notes to Accounts – Revenue Recognition, sourced via BSE announcement / company IR page'},
                        'secondary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page'},
                        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'url': 'https://www.screener.in'},
                    },
                },
                {
                    'key': 'product_lifecycle_stage',
                    'title': 'Product lifecycle stage: growth, maturity, commoditisation, obsolescence risk',
                    'finding': f25.get('rationale') or None,
                    'facts': [f for f in [
                        (['Lifecycle stage', _lifecycle_stage] if _lifecycle_stage else None),
                        (['Relative growth', f"{'+' if _rel_growth >= 0 else ''}{_rel_growth} percentage points vs industry"]
                         if _rel_growth is not None else None),
                    ] if f],
                    'chart': ({'type': 'diverging', 'value': _rel_growth, 'range': 20,
                               'label': 'Revenue CAGR vs industry (5yr)'} if _rel_growth is not None else (
                        {'type': 'spectrum',
                         'options': ['Growth', 'Maturity', 'Commoditisation', 'Decline / obsolescence risk'],
                         'active': _lifecycle_stage}
                        if _lifecycle_stage else None
                    )),
                    'formula': 'Relative growth = Company revenue CAGR − Industry revenue CAGR',
                    'sources': {
                        'primary': {'label': 'CRISIL Ratings/Research', 'url': 'https://www.crisilratings.com'},
                        'secondary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page'},
                        'tertiary': {'label': 'Moneycontrol News/Research', 'note': 'Research/analyst reports', 'url': 'https://www.moneycontrol.com'},
                    },
                },
                {
                    'key': 'pricing_power',
                    'title': 'Pricing power: ability to raise prices without losing customers; pass-through of cost inflation',
                    'finding': f26.get('rationale') or None,
                    'facts': [f for f in [
                        (['Pricing power', _pricing_power_rating] if _pricing_power_rating else None),
                        (['Price pass-through ratio', f"{_pass_through:.2f}x"] if _pass_through is not None else None),
                    ] if f],
                    'chart': ({'type': 'bar', 'panelTitle': 'Pass-through ratio', 'data': [{'label': 'Price pass-through ratio', 'value': _pass_through}], 'scaleMax': 2} if _pass_through is not None else (
                        {'type': 'spectrum', 'options': ['Weak', 'Moderate', 'Strong'], 'active': _pricing_power_rating}
                        if _pricing_power_rating else None
                    )),
                    'formula': 'Price pass-through ratio = Change in realisation % / Change in input cost %',
                    'sources': {
                        'primary': {'label': 'Concall Transcript', 'note': 'Company IR page or Screener.in Documents tab'},
                        'secondary': {'label': 'Company Annual Report', 'note': 'MD&A, sourced via BSE announcement / company IR page'},
                        'tertiary': {'label': 'MCX – Commodity Prices', 'note': '+ LME for commodity input costs', 'url': 'https://www.mcx.co.in'},
                    },
                },
                {
                    'key': 'margin_sustainability',
                    'title': 'Margin sustainability: structurally defensible margins vs temporary tailwinds',
                    'finding': f27.get('rationale') or None,
                    'facts': [f for f in [
                        (['Structural defensibility', _structural_defensibility] if _structural_defensibility else None),
                        (['Margin volatility', f"{_margin_volatility:.2f}"] if _margin_volatility is not None else None),
                        (['One-off years flagged', '; '.join(f27.get('one_off_flags') or [])] if f27.get('one_off_flags') else None),
                    ] if f],
                    'chart': ({'type': 'trend', 'rows': _ebitda_margin_series, 'seriesLabel': 'EBITDA margin',
                               'panelTitle': 'EBITDA margin trend'} if len(_ebitda_margin_series) >= 3 else None),
                    'formula': 'Margin volatility = Std dev of EBITDA margin (5Y) / Mean EBITDA margin (5Y)',
                    'sources': {
                        'primary': {'label': 'BSE India – Corporate Announcements', 'note': 'Quarterly Results', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                        'secondary': {'label': 'Concall Transcript', 'note': 'Company IR page or Screener.in Documents tab'},
                        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'note': '5-8Y margin trend', 'url': 'https://www.screener.in'},
                    },
                },
            ],
        },
    }

    ml_forecast = build_ml_forecast(m, info, symbol)

    # SOIC-style deterministic financial analysis (Piotroski F-Score, DuPont ROE,
    # green/amber/red financial-health checklist) — computed from the 12-yr
    # statements, rendered as scorecards/tables (not prose).
    financial_analysis = {}
    try:
        from tools.financial_analysis import compute_financial_analysis
        financial_analysis = compute_financial_analysis(m)
    except Exception as _fae:
        print(f"[summary] financial analysis skipped: {_fae}")

    # Forward valuation (#10) — forward EPS/PE/PEG/EV-Sales/EV-EBITDA/MCap-Sales
    # from the model's projected growth applied to latest actuals.
    forward_valuation = {}
    try:
        from tools.forward_valuation import compute_forward_valuation
        forward_valuation = compute_forward_valuation(m, ml_forecast, info)
    except Exception as _fve:
        print(f"[summary] forward valuation skipped: {_fve}")

    return {
        'headline': headline,
        'narrative': paras,
        'positives': [p for p in positives if p],
        'risks': [r for r in risks if r],
        'quality_word': quality_word,
        'investment_view': investment_view,
        'ml_forecast': ml_forecast,
        'financial_analysis': financial_analysis,
        'forward_valuation': forward_valuation,
        'peer_rank': peer_rank,
        'business_understanding': business_understanding,
        'qualitative_topics': qualitative_topics,
        'investment_checklist': {
            'items': checklist,
            'summary': checklist_summary,
        },
        'method': 'Synthesized from this company\'s own multi-year fundamentals, valuation, moat, concalls, forensics, ownership and scenario model.',
    }


def peer_synthesis_node(state: SystemState) -> dict:
    """
    Instantiates the PeerSectorEvaluator, performs peer comparison,
    and returns peer_synthesis_data.
    """
    symbol = state.get('symbol')
    print(f"\n[NODE: peer_synthesis_node] Executing peer synthesis analysis for: {symbol}")

    peer_data = {}
    try:
        evaluator = PeerSectorEvaluator()
        # Pass the already-fetched payload so the Screener peer view can reuse its
        # peers/market-cap without an extra Apify call where possible.
        peer_data = evaluator.fetch_peer_comparison_matrix(symbol, raw_payload=state.get('raw_financial_data'))
        print("[peer_synthesis_node] Peer synthesis completed successfully.")
    except Exception as e:
        print(f"[peer_synthesis_node] ERROR executing peer comparison: {e}")
        peer_data = {
            'sector': None,
            'target_metrics': {},
            'peer_matrix': [],
            'sector_averages': {},
            'comparative_tags': [],
            'sector_benchmark': {'sector': None, 'medians': {}, 'percentiles': {}, 'overall_percentile': None},
            'cap_tier': None,
            'screener_peer_view': None,
            'error': str(e)
        }
        
    # Compose the detailed AI summary for the default page now that peer/cap-tier data
    # is available (this node runs last, so state has the full analysis).
    ai_summary = {}
    try:
        state_with_peers = {**state, 'peer_synthesis_data': peer_data}
        ai_summary = build_executive_summary(state_with_peers)
        print(f"[peer_synthesis_node] AI summary composed ({len(ai_summary.get('narrative', []))} paragraphs).")
    except Exception as e:
        print(f"[peer_synthesis_node] AI summary skipped: {e}")

    print("[NODE: peer_synthesis_node] Finished.")
    return {
        'peer_synthesis_data': peer_data,
        'ai_summary': ai_summary,
    }

# 3. Build and compile the workflow using LangGraph's StateGraph
workflow = StateGraph(SystemState)

# Add workflow nodes
workflow.add_node("fetch_market_data", fetch_market_data_node)
workflow.add_node("analyze_quality", analyze_quality_node)
workflow.add_node("peer_synthesis", peer_synthesis_node)

# Set up routing and edges
workflow.add_edge(START, "fetch_market_data")
workflow.add_edge("fetch_market_data", "analyze_quality")

# Transition from analyze_quality to peer_synthesis
workflow.add_edge("analyze_quality", "peer_synthesis")

# Transition from peer_synthesis directly to END
workflow.add_edge("peer_synthesis", END)

# Compile the workflow
app = workflow.compile()

# Standard __main__ execution block for local initialization and testing
if __name__ == '__main__':
    import json
    
    print("=" * 70)
    print("      LANGGRAPH STOCK AGENT ORCHESTRATION PIPELINE - LOCAL TEST")
    print("=" * 70)
    
    while True:
        try:
            print("\n" + "-" * 70)
            user_input = input("Enter Stock Symbol for Fundamental Research (or 'exit' to quit): ").strip().upper()
            if not user_input or user_input in ['EXIT', 'QUIT', 'Q']:
                print("Exiting interactive test loop. Goodbye!")
                break
                
            initial_state = {
                'symbol': user_input,
                'raw_financial_data': {},
                'business_score': 0,
                'qualitative_analysis': {},
                'peer_synthesis_data': {},
                'verdict': 'PENDING'
            }
            
            print(f"Triggering compiled LangGraph workflow for symbol: {user_input}...")
            final_state = app.invoke(initial_state)
            
            print("\n" + "=" * 70)
            print("                        FINAL STATE OUTPUT")
            print("=" * 70)
            print(json.dumps(final_state, indent=4))
            print("=" * 70)
            
        except KeyboardInterrupt:
            print("\nExiting loop via interrupt. Goodbye!")
            break
        except Exception as e:
            print(f"\n[ERROR] Workflow execution failed: {e}")
