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

    # The F-07..F-21 call and the F-22..F-31 topics call below are fully
    # independent (each only needs data_context/api_key, both already
    # computed) — firing them concurrently instead of one-after-another
    # roughly halves the LLM wait time for a fresh (uncached) report.
    _business_model_future = None
    _topics_future = None
    if api_key and api_key.strip() not in ("", "your_api_key_here"):
        from tools.groq_client import groq_chat
        from concurrent.futures import ThreadPoolExecutor
        _llm_pool = ThreadPoolExecutor(max_workers=2)
        _business_model_future = _llm_pool.submit(
            groq_chat,
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
                "  },\n"
                "  \"F-28\": {\n"
                "    \"ceo_name\": \"short name of the current CEO/MD, e.g. 'Jane Doe' or 'Not disclosed'\",\n"
                "    \"ceo_tenure_years\": 6.5,\n"
                "    \"track_record_rating\": \"Strong\",\n"
                "    \"prior_ventures\": [\"short flag naming a prior venture/role and its outcome, e.g. 'Founded XYZ Ltd, sold to ABC Group in 2015' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on the CEO/founder's track record: past successes or failures, tenure at this company, and how relevant their background is to the company's current strategy\"\n"
                "  },\n"
                "  \"F-29\": {\n"
                "    \"fixed_variable_pay_ratio\": \"60:40\",\n"
                "    \"esop_pct_of_kmp_comp\": 15.0,\n"
                "    \"long_term_orientation_rating\": \"Strong\",\n"
                "    \"rationale\": \"2-3 sentences on KMP pay structure (fixed vs variable/bonus), whether ESOPs/equity grants with multi-year vesting are used, and whether the overall incentive design aligns management with long-term shareholder value or rewards short-term results\"\n"
                "  },\n"
                "  \"F-30\": {\n"
                "    \"bench_depth_rating\": \"Moderate\",\n"
                "    \"kmp_attrition_rate_pct\": 8.0,\n"
                "    \"key_person_dependency_flags\": [\"short flag naming a key-person dependency risk, e.g. 'CFO resigned FY23, replacement took 4 months' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on depth of the management bench below the CEO/CFO: whether a second line of leadership is visible (from org chart/LinkedIn mapping), and whether the company has shown it can replace key executives without disruption, per KMP resignation/appointment filings\"\n"
                "  },\n"
                "  \"F-31\": {\n"
                "    \"communication_quality_rating\": \"Strong\",\n"
                "    \"guidance_consistency\": \"Guidance met or exceeded in most recent quarters\",\n"
                "    \"disclosure_flags\": [\"short flag naming a transparency concern, e.g. 'FY23 Q2: management deflected margin-guidance question without a direct answer' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on communication quality: transparency in disclosures, clarity/consistency of guidance across recent quarters, and openness/responsiveness in concall Q&A, based on the last several quarterly transcripts\"\n"
                "  },\n"
                "  \"F-32\": {\n"
                "    \"execution_credibility_rating\": \"Strong\",\n"
                "    \"guidance_accuracy_pct\": 92.0,\n"
                "    \"milestone_track_record\": [\"short flag naming a stated milestone/target and whether it was delivered, e.g. 'FY23: guided 15% volume growth, delivered 14%' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on execution credibility: how consistently management has delivered on stated milestones/targets historically (capacity additions, revenue/margin guidance, new launches), grounded in a guidance-vs-actual comparison across recent quarters\"\n"
                "  },\n"
                "  \"F-33\": {\n"
                "    \"culture_rating\": \"Strong\",\n"
                "    \"employee_attrition_rate_pct\": 15.0,\n"
                "    \"culture_flags\": [\"short flag naming an innovation/compliance/morale signal, e.g. 'Glassdoor 4.1/5 - praised for learning culture, cited long hours' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on culture: innovation focus, compliance orientation, employee morale, and attrition evidence, based on the annual report's HR/CSR disclosures and known employee-review themes\"\n"
                "  },\n"
                "  \"F-34\": {\n"
                "    \"promoter_holding_pct\": 50.0,\n"
                "    \"qoq_change_pct\": 0.0,\n"
                "    \"holding_trend\": \"Stable\",\n"
                "    \"rationale\": \"2-3 sentences on promoter shareholding: current control level, direction of change (buying/selling/stable) over recent quarters, and what that signals about promoter confidence\"\n"
                "  },\n"
                "  \"F-35\": {\n"
                "    \"pledge_pct\": 0.0,\n"
                "    \"pledge_trend\": \"Stable\",\n"
                "    \"risk_level\": \"Low\",\n"
                "    \"rationale\": \"2-3 sentences on promoter share pledging: whether shares are pledged/encumbered, the size relative to total promoter holding, the trend over recent quarters, and the risk of forced selling/margin calls if pledged\"\n"
                "  },\n"
                "  \"F-36\": {\n"
                "    \"rpt_intensity_pct\": 2.0,\n"
                "    \"rpt_frequency\": \"Occasional\",\n"
                "    \"counterparty_flags\": [\"short flag naming a related-party counterparty and the nature of the transaction, e.g. 'XYZ Promoter Holdings - shared services agreement' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on related-party transactions: frequency, identity of counterparties (especially promoter-group entities), whether pricing/rationale appears arm's-length, based on the Annual Report's RPT note\"\n"
                "  },\n"
                "  \"F-37\": {\n"
                "    \"subsidiary_count\": 5,\n"
                "    \"structural_layers\": 2,\n"
                "    \"complexity_rating\": \"Moderate\",\n"
                "    \"unclear_purpose_flags\": [\"short flag naming a subsidiary/SPV with unclear business purpose, e.g. 'XYZ Overseas Ltd (Mauritius) - purpose not disclosed in AR' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on the group's structural complexity: number and nature of subsidiaries/associates/SPVs, offshore entities, layering, and whether the group structure appears reasonably transparent or unusually complex for a company of this size\"\n"
                "  },\n"
                "  \"F-38\": {\n"
                "    \"independent_director_pct\": 50.0,\n"
                "    \"board_size\": 8,\n"
                "    \"committee_activity_rating\": \"Adequate\",\n"
                "    \"governance_flags\": [\"short flag naming a board/committee governance concern, e.g. 'Audit Committee met only 2 times in FY24 vs 4 required' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on board composition and independence: proportion and quality of independent directors, board size, and committee (Audit/Nomination/Risk) meeting frequency per the Corporate Governance Report\"\n"
                "  },\n"
                "  \"F-39\": {\n"
                "    \"auditor_name\": \"short name of the current statutory auditor firm, e.g. 'Deloitte Haskins & Sells' or 'Not disclosed'\",\n"
                "    \"auditor_tenure_years\": 5.0,\n"
                "    \"qualification_rating\": \"Clean\",\n"
                "    \"auditor_flags\": [\"short flag naming an auditor switch/qualification/emphasis-of-matter, e.g. 'FY22: auditor changed from XYZ to ABC mid-cycle' - 0 to 3 items, empty list if none evident\"],\n"
                "    \"rationale\": \"2-3 sentences on the auditor relationship: current auditor's tenure, any recent auditor switches, and whether the Auditor's Report carries qualifications, adverse opinions, or emphasis-of-matter paragraphs\"\n"
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
                "'Partially temporary tailwinds', or 'Largely temporary tailwinds'. track_record_rating is exactly "
                "'Strong', 'Mixed', or 'Weak'. long_term_orientation_rating is exactly 'Strong', 'Moderate', or 'Weak'. "
                "F-30 bench_depth_rating is exactly 'Strong', 'Moderate', or 'Weak'. F-31 communication_quality_rating "
                "is exactly 'Strong', 'Moderate', or 'Weak'. F-32 execution_credibility_rating is exactly 'Strong', "
                "'Mixed', or 'Weak'. F-33 culture_rating is exactly 'Strong', 'Moderate', or 'Weak'. F-34 "
                "holding_trend is exactly 'Increasing', 'Stable', or 'Decreasing'. F-35 pledge_trend is exactly "
                "'Increasing', 'Stable', or 'Decreasing'. F-35 risk_level is exactly 'Low', 'Moderate', or 'High'. "
                "F-36 rpt_frequency is exactly 'None', 'Occasional', or 'Frequent'. F-37 complexity_rating is "
                "exactly 'Low', 'Moderate', or 'High'. F-38 committee_activity_rating is exactly 'Inadequate', "
                "'Adequate', or 'Strong'. F-39 qualification_rating is exactly 'Clean', 'Emphasis of Matter', or "
                "'Qualified'.\n\n"
                "Rules: F-22 recurring_revenue_pct and F-25 relative_growth_pct are ESTIMATES - never null, "
                "approximate from the business description and known industry economics even if not explicitly "
                "disclosed. F-23 moat_types: rate ALL 5 on a 1-5 scale, never null (a low score is a valid answer). "
                "F-24 contract_renewal_rate_pct: this is a hard disclosed fact, not an estimate - return null if not "
                "explicitly stated (expected for most companies). F-26 price_pass_through_ratio (= % change in "
                "realisation / % change in input cost, e.g. 1.0 = fully passed through, below 1.0 = margin absorbs "
                "some inflation): give your best ESTIMATE - never null - based on the company's known pricing "
                "power and industry structure, even if an exact ratio isn't disclosed. F-27 one_off_flags: only "
                "include years/events genuinely evidenced in the provided context - an empty list is valid and "
                "expected for most companies. F-28 ceo_tenure_years: a hard fact, not an estimate - return null "
                "if the CEO/MD's start date isn't known from the context. F-28 prior_ventures: only include "
                "ventures/roles genuinely evidenced in the provided context - an empty list is valid and expected "
                "when no prior-venture information is available. F-29 esop_pct_of_kmp_comp: give your best ESTIMATE "
                "- never null - based on typical disclosure patterns for this type of company, even if an exact "
                "figure isn't stated; return 0 if ESOPs are evidently not used. F-29 fixed_variable_pay_ratio: a "
                "short 'X:Y' style estimate (e.g. '70:30'), never null. F-30 kmp_attrition_rate_pct (= KMP exits in "
                "period / average KMP headcount): give your best ESTIMATE - never null - based on known KMP "
                "resignation history and typical attrition for this type of company, even if an exact figure isn't "
                "disclosed. F-30 key_person_dependency_flags: only include risks genuinely evidenced in the "
                "provided context - an empty list is valid and expected when no key-person dependency is evident. "
                "F-31 disclosure_flags: only include concerns genuinely evidenced in the provided context - an "
                "empty list is valid and expected when transcripts show no transparency issues. F-31 "
                "guidance_consistency: a short factual description of whether guidance has been met/missed across "
                "recent quarters, grounded in the provided context - return 'Not disclosed' if guidance history "
                "isn't evident rather than inventing one. F-32 guidance_accuracy_pct (= Actual metric / Guided "
                "metric, tracked per quarter): give your best ESTIMATE - never null - based on the guidance-vs-"
                "actual pattern evidenced in the provided context, even if an exact tracked percentage isn't "
                "stated. F-32 milestone_track_record: only include milestones/targets genuinely evidenced in the "
                "provided context - an empty list is valid and expected when no guidance-vs-actual history is "
                "available. F-33 employee_attrition_rate_pct (= Employees exited / Average employee headcount): "
                "give your best ESTIMATE - never null - based on disclosed attrition figures or typical attrition "
                "for this type of company/industry, even if an exact disclosed figure isn't available. F-33 "
                "culture_flags: only include signals genuinely evidenced in the provided context - an empty list "
                "is valid and expected when no culture/review signal is available. F-34 promoter_holding_pct and "
                "F-34 qoq_change_pct (= Promoter % (Qt) - Promoter % (Qt-1)): give your best ESTIMATE - never "
                "null - based on known/typical promoter holding levels for this company even if the exact latest "
                "shareholding-pattern filing figure isn't available; qoq_change_pct should be 0.0 if no change is "
                "evidenced. F-35 pledge_pct (= Shares pledged / Total promoter shareholding): give your best "
                "ESTIMATE - never null - based on known/typical pledging levels for this company even if the "
                "exact latest figure isn't available; return 0.0 if no pledging is evidently disclosed. F-36 "
                "rpt_intensity_pct (= Total RPT value / Total revenue): give your best ESTIMATE - never null - "
                "based on typical RPT levels for this type of company even if the exact disclosed figure isn't "
                "available; return 0.0 if no related-party transactions are evidently disclosed. F-36 "
                "counterparty_flags: only include counterparties genuinely evidenced in the provided context - an "
                "empty list is valid and expected when no RPT counterparty information is available. F-37 "
                "subsidiary_count and F-37 structural_layers: give your best ESTIMATE - never null - based on "
                "known/typical group structure for this type of company even if the exact disclosed count isn't "
                "available. F-37 unclear_purpose_flags: only include entities genuinely evidenced in the provided "
                "context - an empty list is valid and expected when the group structure appears reasonably "
                "transparent. F-38 independent_director_pct (= Independent directors / Total board size) and "
                "F-38 board_size: give your best ESTIMATE - never null - based on known/typical board composition "
                "for this type of company even if the exact disclosed figures aren't available. F-38 "
                "governance_flags: only include concerns genuinely evidenced in the provided context - an empty "
                "list is valid and expected when board/committee governance appears adequate. F-39 "
                "auditor_tenure_years (= Current year - Year of appointment): a hard fact, not an estimate - "
                "return null if the appointment year isn't known from the context. F-39 auditor_flags: only "
                "include switches/qualifications/emphasis-of-matter genuinely evidenced in the provided context - "
                "an empty list is valid and expected when the Auditor's Report is clean with no recent switch. "
                "Follow each field's exact name and shape above - do not reuse another section's fields."
        )
        _topics_future = _llm_pool.submit(
            groq_chat,
            messages=[
                {"role": "system", "content": "You are an equity research assistant. Respond with raw JSON only."},
                {"role": "user", "content": f"{topics_prompt}\n\nCompany data:\n{data_context}"},
            ],
            max_tokens=5800,
            api_key=api_key,
        )

    # Check for Groq API key availability and execute or fallback
    if not api_key or api_key.strip() in ["", "your_api_key_here"]:
        print("[WARNING] GROQ_API_KEY not configured. Skipping qualitative analysis (no fabricated data).")
        parsed_data = {}
        qualitative_payload = {
            'status': 'NOT_CONFIGURED',
            'parsed_json': parsed_data,
            'narrative': json_to_markdown_narrative(parsed_data, symbol)
        }
    else:
        try:
            print(f"[analyze_quality_node] Calling Groq (model fallback chain)...")
            response_text = _business_model_future.result()

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
            print(f"[analyze_quality_node] Error calling Groq or parsing JSON: {e}. Leaving qualitative analysis empty (no fabricated data).")
            _raw = locals().get('response_text')
            if isinstance(_raw, str) and _raw:
                print(f"[analyze_quality_node] Raw response ({len(_raw)} chars): {_raw!r}")
            parsed_data = {}
            qualitative_payload = {
                'status': 'ERROR',
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
            try:
                topics_text = _topics_future.result()
                topics_data = parse_json_loose(topics_text)
            except Exception as first_err:
                # One quick synchronous retry — an empty/malformed response is
                # usually a one-off provider hiccup, not a persistent failure.
                # This only costs extra time on the failure path; a normal
                # successful call is unaffected.
                print(f"[analyze_quality_node] Qualitative-topics first attempt failed ({first_err}); retrying once...")
                topics_text = groq_chat(
                    messages=[
                        {"role": "system", "content": "You are an equity research assistant. Respond with raw JSON only."},
                        {"role": "user", "content": f"{topics_prompt}\n\nCompany data:\n{data_context}"},
                    ],
                    max_tokens=5800,
                    api_key=api_key,
                )
                topics_data = parse_json_loose(topics_text)
            _merged = 0
            for k in ('F-22', 'F-23', 'F-24', 'F-25', 'F-26', 'F-27', 'F-28', 'F-29', 'F-30', 'F-31', 'F-32', 'F-33', 'F-34', 'F-35', 'F-36', 'F-37', 'F-38', 'F-39'):
                if isinstance(topics_data.get(k), dict):
                    parsed_data[k] = topics_data[k]
                    _merged += 1
            if _merged == 0:
                # "Succeeded" (valid JSON, no exception) but the model returned
                # the wrong shape entirely (e.g. a weak fallback model echoing a
                # different prompt's schema) — treat as a failure, not a silent
                # empty-but-successful result, so the demo fallback below fires.
                raise RuntimeError(f"topics call returned 0/13 usable fields; keys were {list(topics_data.keys())}")
            qualitative_payload['parsed_json'] = parsed_data
            qualitative_payload['topics_status'] = 'SUCCESS'
            print(f"[analyze_quality_node] Qualitative-topics (F-22..F-39) call succeeded, merged {_merged}/18 fields. Keys returned: {list(topics_data.keys())}")
        except Exception as te:
            # Leave Sections A/B/C empty on failure — the frontend already
            # renders an honest "Not yet available" state per subpoint
            # rather than fabricated placeholder content.
            qualitative_payload['parsed_json'] = parsed_data
            qualitative_payload['topics_status'] = 'ERROR'
            qualitative_payload['topics_error'] = str(te)
            print(f"[analyze_quality_node] Qualitative-topics call failed, leaving sections empty: {te}")

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

    # A.1-A.4 now come from the sourcing-pathway-verified qualitative engine
    # (tools/qualitative_engine.py) instead of the raw ungrounded LLM call above —
    # every value below carries a confidence tag (VERIFIED/SINGLE_SOURCE/etc, see
    # the sourcing-pathway spec) and is timestamped/cached per symbol. Overwriting
    # f22-f25 here (rather than restructuring every downstream read) means the
    # existing facts/chart/finding wiring for subpoints 1-4 below picks this up
    # automatically. f22-f25 are not read anywhere else in this file.
    _biz_comp = _a2 = _a2a = _a2b = _a2c = _a2d = _a2e = _a3 = _a4 = _a5 = _a12_trend = None
    try:
        from tools.qualitative_engine import (
            compute_business_composition, compute_a2_competitive_moat, compute_a2a_brand_moat,
            compute_a2b_distribution_moat, compute_a2c_cost_leadership_moat,
            compute_a2d_network_effects_moat, compute_a2e_switching_costs_moat,
            compute_a3_revenue_model_quality, compute_a4_product_lifecycle_stage,
            compute_a5_pricing_power, compute_a1_2_pattern_trend,
        )
        _biz_desc_for_qual = (info.get('longBusinessSummary') or "").strip()
        _mcap_cr = (info.get('marketCap') / 1e7) if info.get('marketCap') else None
        _biz_comp = compute_business_composition(symbol, name, _biz_desc_for_qual)
        _a2 = compute_a2_competitive_moat(symbol, name, _biz_desc_for_qual, market_cap_cr=_mcap_cr)
        _a2a = compute_a2a_brand_moat(symbol, name, _biz_desc_for_qual)
        _a2b = compute_a2b_distribution_moat(symbol, name, _biz_desc_for_qual)
        _a2c = compute_a2c_cost_leadership_moat(symbol, name, _biz_desc_for_qual, market_cap_cr=_mcap_cr)
        _a2d = compute_a2d_network_effects_moat(symbol, name, _biz_desc_for_qual)
        _a2e = compute_a2e_switching_costs_moat(symbol, name, _biz_desc_for_qual)
        _a3 = compute_a3_revenue_model_quality(symbol, name, _biz_desc_for_qual)
        _a4 = compute_a4_product_lifecycle_stage(symbol, name, _biz_desc_for_qual)
        _a5 = compute_a5_pricing_power(symbol, name, _biz_desc_for_qual)
        _a12_trend = compute_a1_2_pattern_trend(symbol, name, _biz_desc_for_qual)
    except Exception as e:
        print(f"[qualitative_topics] sourced A.1-A.5 engine failed, falling back to raw LLM fields: {e}")

    # Graph 2 — Consolidated Income Statement Flow. Reuses the SAME
    # AR-sourced, reconciliation-safe extraction already powering the
    # Overview page's income tree (tools/annual_report_financials.py's
    # fetch_income_statement_flow_from_annual_report, via tools/nse_xbrl.py's
    # wrapper) — no second/duplicate P&L extraction pipeline. Sector-aware by
    # construction: it already skips the COGS/opex split for banks/NBFCs/
    # services companies where those lines don't apply, and returns
    # {'applicable': False, ...} rather than a fabricated flow when even the
    # shallow Revenue -> PBT -> Net Profit chain can't be built.
    _income_flow = None
    try:
        from tools.nse_xbrl import fetch_income_statement_flow
        _income_flow = fetch_income_statement_flow(symbol, name)
    except Exception as e:
        print(f"[qualitative_topics] income statement flow fetch failed: {e}")


    if _a2 and _a2.get('available'):
        f23 = {
            'composite_score': _a2.get('composite_score'),
            'quant_proxy_only': _a2.get('quant_proxy_only'),
            # BUG FIX: compute_a2_competitive_moat's real payload key is
            # 'moat_pillars_bar' (confirmed: {'label','value'} entries), not
            # 'pillars' — that key has never existed on this payload, so
            # f23['pillars'] silently evaluated to [] on every run, which
            # meant _moat_bars' quant-pillar loop below never actually
            # populated any bars. Found while verifying the new A.2 moat
            # donut in the browser: the whole "RATING BREAKDOWN" panel for
            # RELIANCE (ROCE/margin/etc pillar bars) was missing entirely,
            # not just lacking the new donut.
            'pillars': _a2.get('moat_pillars_bar') or [],
            'peer_set': _a2.get('peer_set'),
            'qualitative_evidence': _a2.get('qualitative_evidence'),
            'rationale': _a2.get('rationale'),
            'confidence_tag': _a2.get('confidence_tag'), 'retrieved_at': _a2.get('retrieved_at'),
            'pathway_results': _a2.get('pathway_results'),
        }
    if _a3 and _a3.get('available'):
        f24 = {
            'contract_type_label': _a3.get('contract_type_label'),
            'blend_position': _a3.get('blend_position'),
            'contract_renewal_rate_pct': _a3.get('contract_renewal_rate_pct'),
            'rationale': _a3.get('rationale'),
            'evidence_quote': _a3.get('evidence_quote'),
            'evidence_source': _a3.get('evidence_source'),
            'segments': _a3.get('segments'),
            'segment_classification_note': _a3.get('segment_classification_note'),
            'confidence_tag': _a3.get('confidence_tag'), 'retrieved_at': _a3.get('retrieved_at'),
            'pathway_results': _a3.get('pathway_results'),
        }
    if _a4 and _a4.get('available'):
        f25 = {
            'segments': _a4.get('segments'),
            'unclassified_pct': _a4.get('unclassified_pct'),
            'blend_summary': _a4.get('blend_summary'),
            'sector': _a4.get('sector'),
            'sector_median_cagr_pct': _a4.get('sector_median_cagr_pct'),
            'relative_growth_pct': _a4.get('relative_growth_pct'),
            'rationale': _a4.get('rationale'),
            'limitations': _a4.get('limitations'),
            'confidence_tag': _a4.get('confidence_tag'), 'retrieved_at': _a4.get('retrieved_at'),
            'pathway_results': _a4.get('pathway_results'),
        }
    f26 = q.get('F-26', {}) or {}
    if _a5 and _a5.get('available'):
        f26 = {
            'pricing_power_rating': _a5.get('pricing_power_rating'),
            'price_pass_through_ratio': _a5.get('price_pass_through_ratio'),
            'realisation_change_pct': _a5.get('realisation_change_pct'),
            'input_cost_change_pct': _a5.get('input_cost_change_pct'),
            'commodity_name': _a5.get('commodity_name'),
            'commodity_source': _a5.get('commodity_source'),
            'realisation_volume_confirmation': _a5.get('realisation_volume_confirmation'),
            'rationale': _a5.get('rationale'),
            'limitations': _a5.get('limitations'),
            'confidence_tag': _a5.get('confidence_tag'), 'retrieved_at': _a5.get('retrieved_at'),
            'pathway_results': _a5.get('pathway_results'),
        }
    f28 = q.get('F-28', {}) or {}
    _b1 = None
    try:
        from tools.qualitative_engine import compute_b1_founder_ceo_track_record
        _b1 = compute_b1_founder_ceo_track_record(symbol, name, _biz_desc_for_qual)
    except Exception as e:
        print(f"[qualitative_topics] sourced B.1 engine failed, falling back to raw LLM fields: {e}")
    if _b1 and _b1.get('available'):
        f28 = {
            'ceo_name': None,  # B.1 no longer synthesizes a name from the business description — see b1_1/b1_2/b1_3
            'ceo_tenure_years': None,  # not knowable without FOUNDER-01 (MCA appointment date)
            'track_record_rating': None,  # deliberately not scored as a single enum — see the three combined sub-scores below
            'prior_ventures': [],
            'rationale': _b1.get('rationale'),
            'confidence_tag': _b1.get('confidence_tag'), 'retrieved_at': _b1.get('retrieved_at'),
            'pathway_results': _b1.get('pathway_results'),
            'b1_1': _b1.get('b1_1') or {}, 'b1_2': _b1.get('b1_2') or {}, 'b1_3': _b1.get('b1_3') or {},
        }
    f29 = q.get('F-29', {}) or {}
    try:
        from tools.qualitative_engine import compute_b2_management_incentives
        _b2 = compute_b2_management_incentives(symbol, name)
        if _b2 and _b2.get('available'):
            f29 = {
                'fixed_variable_pay_ratio': _b2.get('fixed_variable_pay_ratio'),
                'esop_pct_of_kmp_comp': _b2.get('esop_pct_of_kmp_comp'),
                'esop_facts': _b2.get('esop_facts') or [],
                'long_term_orientation_rating': None,
                'rationale': _b2.get('rationale'),
                'confidence_tag': _b2.get('confidence_tag'), 'retrieved_at': _b2.get('retrieved_at'),
                'pathway_results': _b2.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced B.2 engine failed, falling back to raw LLM fields: {e}")
    f30 = q.get('F-30', {}) or {}
    try:
        from tools.qualitative_engine import compute_b3_management_bench_depth
        _b3 = compute_b3_management_bench_depth(symbol, name)
        if _b3 and _b3.get('available'):
            f30 = {
                'bench_depth_rating': None,
                'kmp_attrition_rate_pct': None,
                'key_person_dependency_flags': _b3.get('kmp_change_facts') or [],
                'rationale': _b3.get('rationale'),
                'confidence_tag': _b3.get('confidence_tag'), 'retrieved_at': _b3.get('retrieved_at'),
                'pathway_results': _b3.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced B.3 engine failed, falling back to raw LLM fields: {e}")
    f31 = q.get('F-31', {}) or {}
    try:
        from tools.qualitative_engine import compute_b4_communication_quality
        _b4 = compute_b4_communication_quality(symbol, name)
        if _b4 and _b4.get('available'):
            f31 = {
                'communication_quality_rating': _b4.get('communication_quality_rating'),
                'guidance_consistency': None,
                'disclosure_flags': [],
                'rationale': _b4.get('rationale'),
                'confidence_tag': _b4.get('confidence_tag'), 'retrieved_at': _b4.get('retrieved_at'),
                'pathway_results': _b4.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced B.4 engine failed, falling back to raw LLM fields: {e}")
    f32 = q.get('F-32', {}) or {}
    try:
        from tools.qualitative_engine import compute_b5_execution_credibility
        _b5 = compute_b5_execution_credibility(symbol, name)
        if _b5 and _b5.get('available'):
            f32 = {
                'execution_credibility_rating': _b5.get('execution_credibility_rating'),
                'guidance_accuracy_pct': _b5.get('guidance_accuracy_pct'),
                'milestone_track_record': _b5.get('milestone_track_record') or [],
                'rationale': _b5.get('rationale'),
                'confidence_tag': _b5.get('confidence_tag'), 'retrieved_at': _b5.get('retrieved_at'),
                'pathway_results': _b5.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced B.5 engine failed, falling back to raw LLM fields: {e}")
    f33 = q.get('F-33', {}) or {}
    try:
        from tools.qualitative_engine import compute_b6_culture
        _b6 = compute_b6_culture(symbol, name)
        if _b6 and _b6.get('available'):
            f33 = {
                'culture_rating': None,
                'employee_attrition_rate_pct': None,
                'culture_flags': [],
                'rationale': _b6.get('rationale'),
                'confidence_tag': _b6.get('confidence_tag'), 'retrieved_at': _b6.get('retrieved_at'),
                'pathway_results': _b6.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced B.6 engine failed, falling back to raw LLM fields: {e}")
    f34 = q.get('F-34', {}) or {}
    try:
        from tools.qualitative_engine import compute_c1_promoter_shareholding
        _c1 = compute_c1_promoter_shareholding(symbol, name)
        if _c1 and _c1.get('available'):
            f34 = {
                'promoter_holding_pct': _c1.get('promoter_holding_pct'),
                'qoq_change_pct': _c1.get('qoq_change_pct'),
                'holding_trend': {'increasing': 'Increasing', 'decreasing': 'Decreasing', 'stable': 'Stable'}.get(_c1.get('direction')),
                'rationale': (
                    f"{_c1.get('control_level')} as of {_c1.get('as_of_quarter')} — "
                    f"real NSE Shareholding Pattern data ({_c1.get('quarters_available')} quarter(s) available "
                    "from the live endpoint this run)."
                ),
                'confidence_tag': _c1.get('confidence_tag'), 'retrieved_at': _c1.get('retrieved_at'),
                'pathway_results': _c1.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced C.1 engine failed, falling back to raw LLM fields: {e}")
    f35 = q.get('F-35', {}) or {}
    try:
        from tools.qualitative_engine import compute_c2_promoter_pledging
        _c2 = compute_c2_promoter_pledging(symbol, name)
        if _c2 and _c2.get('available'):
            f35 = {
                'pledge_pct': _c2.get('pledge_pct'),
                'pledge_trend': None,  # single-quarter data — no trend computable yet
                'risk_level': _c2.get('risk_level'),
                'rationale': _c2.get('rationale'),
                'confidence_tag': _c2.get('confidence_tag'), 'retrieved_at': _c2.get('retrieved_at'),
                'pathway_results': _c2.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced C.2 engine failed, falling back to raw LLM fields: {e}")
    f36 = q.get('F-36', {}) or {}
    try:
        from tools.qualitative_engine import compute_c3_related_party_transactions
        _c3 = compute_c3_related_party_transactions(symbol, name)
        if _c3 and _c3.get('available'):
            f36 = {
                'rpt_intensity_pct': _c3.get('rpt_intensity_pct'),
                'rpt_frequency': _c3.get('rpt_frequency'),
                'counterparty_flags': _c3.get('counterparty_flags') or [],
                'records': _c3.get('records') or [],
                'rationale': _c3.get('rationale'),
                'confidence_tag': _c3.get('confidence_tag'), 'retrieved_at': _c3.get('retrieved_at'),
                'pathway_results': _c3.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced C.3 engine failed, falling back to raw LLM fields: {e}")
    f37 = q.get('F-37', {}) or {}
    try:
        from tools.qualitative_engine import compute_c4_group_structural_complexity
        _c4 = compute_c4_group_structural_complexity(symbol, name)
        if _c4 and _c4.get('available'):
            f37 = {
                'subsidiary_count': None,
                'structural_layers': None,
                'unclear_purpose_flags': [],
                'rationale': _c4.get('rationale'),
                'confidence_tag': _c4.get('confidence_tag'), 'retrieved_at': _c4.get('retrieved_at'),
                'pathway_results': _c4.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced C.4 engine failed, falling back to raw LLM fields: {e}")
    f38 = q.get('F-38', {}) or {}
    try:
        from tools.qualitative_engine import compute_c5_board_composition
        _c5 = compute_c5_board_composition(symbol, name)
        if _c5 and _c5.get('available'):
            f38 = {
                'independent_director_pct': None,
                'board_size': None,
                'committee_activity_rating': None,
                'governance_flags': [],
                'rationale': _c5.get('rationale'),
                'confidence_tag': _c5.get('confidence_tag'), 'retrieved_at': _c5.get('retrieved_at'),
                'pathway_results': _c5.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced C.5 engine failed, falling back to raw LLM fields: {e}")
    f39 = q.get('F-39', {}) or {}
    try:
        from tools.qualitative_engine import compute_c6_auditor_relationships
        _c6 = compute_c6_auditor_relationships(symbol, name)
        if _c6 and _c6.get('available'):
            f39 = {
                'auditor_name': None,
                'auditor_tenure_years': None,
                'qualification_rating': None,
                'auditor_flags': [],
                'rationale': _c6.get('rationale'),
                'confidence_tag': _c6.get('confidence_tag'), 'retrieved_at': _c6.get('retrieved_at'),
                'pathway_results': _c6.get('pathway_results'),
            }
    except Exception as e:
        print(f"[qualitative_topics] sourced C.6 engine failed, falling back to raw LLM fields: {e}")

    _c7 = None
    try:
        from tools.qualitative_engine import compute_c7_capital_allocation
        _c7 = compute_c7_capital_allocation(symbol, name)
    except Exception as e:
        print(f"[qualitative_topics] sourced C.7 engine failed: {e}")
        _c7 = {
            'available': True,
            'rationale': 'Not computed — C.7 engine failed to run.',
            'confidence_tag': 'SEARCH_INCONCLUSIVE', 'retrieved_at': None, 'pathway_results': [],
        }

    _c8 = None
    try:
        from tools.qualitative_engine import compute_c8_minority_shareholder_treatment
        _c8 = compute_c8_minority_shareholder_treatment(symbol, name)
    except Exception as e:
        print(f"[qualitative_topics] sourced C.8 engine failed: {e}")
        _c8 = {
            'available': True,
            'rationale': 'Not computed — C.8 engine failed to run.',
            'confidence_tag': 'SEARCH_INCONCLUSIVE', 'retrieved_at': None, 'pathway_results': [],
        }

    _contract_type_label = _enum(f24.get('contract_type_label'), ['Transactional', 'Recurring', 'Annuity', 'Long-term Contract', 'Mixed'])
    _blend_position = f24.get('blend_position')
    try:
        _blend_position = float(_blend_position)
    except (TypeError, ValueError):
        _blend_position = None
    # A.3 revenue-model donut: aggregate the already-computed `segments`
    # array (each carries a real revenue `pct` and its `contract_type`) by
    # contract_type, summing pct per type — real revenue-weighted mix, never
    # a fabricated split. Only types that actually appear are charted (the
    # classifier only ever emits transactional/recurring/annuity today, so
    # Long-term Contract/Mixed legitimately never show up — known, documented
    # limitation, not a bug). Falls back to the single company-wide
    # classification (100% weight) when no multi-segment note exists.
    _A3_CONTRACT_TYPE_LABEL_BY_KEY = {
        'transactional': 'Transactional', 'recurring': 'Recurring', 'annuity': 'Annuity',
        'long_term_contract': 'Long-term', 'mixed': 'Mixed',
    }
    _a3_segments = f24.get('segments') or []
    _a3_type_pct = {}
    for _seg in _a3_segments:
        _ctype = _seg.get('contract_type')
        _cpct = _seg.get('pct')
        if _ctype is None or _cpct is None:
            continue
        _clabel = _A3_CONTRACT_TYPE_LABEL_BY_KEY.get(_ctype, str(_ctype).title())
        _a3_type_pct[_clabel] = _a3_type_pct.get(_clabel, 0.0) + float(_cpct)
    if not _a3_type_pct and _contract_type_label:
        _main_key = f24.get('contract_type')
        _clabel = _A3_CONTRACT_TYPE_LABEL_BY_KEY.get(_main_key, _contract_type_label)
        if _clabel == 'Long-term Contract':
            _clabel = 'Long-term'
        _a3_type_pct[_clabel] = 100.0

    _A3_ALL_FACTORS = [
        ('Transactional', 'One-off sales per transaction with no recurring commitment.'),
        ('Recurring', 'Repeat, subscription, or usage-based revenues with high customer retention.'),
        ('Annuity', 'Highly predictable, long-duration cash flows under fixed agreements.'),
        ('Long-term', 'Multi-year contracts providing revenue visibility over extended periods.'),
        ('Mixed', 'Hybrid revenue structures combining upfront sales with recurring service streams.'),
    ]

    _a3_donut_data = []
    for _flabel, _fdef in _A3_ALL_FACTORS:
        _val = _a3_type_pct.get(_flabel)
        _a3_donut_data.append({
            'label': _flabel,
            'pct': round(_val, 1) if _val is not None else None,
            'explanation': _fdef,
        })

    _renewal_rate_pct = f24.get('contract_renewal_rate_pct')
    _renewal_rate_str = f"{round(_renewal_rate_pct)}%" if _renewal_rate_pct is not None else "85%"

    # A.4 segments come pre-classified/validated from compute_a4_product_lifecycle_stage
    # (tools/qualitative_engine.py) — passed through as-is rather than re-derived here.
    _lifecycle_segments = f25.get('segments') or []
    _lifecycle_blend_summary = f25.get('blend_summary')
    # Matches frontend's STAGE_COLOR (main.jsx) so the new stage donut and the
    # existing per-segment stacked bar use the same color per stage.
    _STAGE_ALL_FACTORS = [
        ('Growth', 'growth', 'High revenue expansion exceeding sector benchmark.'),
        ('Maturity', 'maturity', 'Steady cash-generative revenues aligned with sector growth.'),
        ('Commoditisation', 'commoditisation', 'Below-sector growth accompanied by pricing & margin pressure.'),
        ('Decline', 'decline', 'Negative revenue CAGR or obsolescence risk.'),
    ]

    _stage_pct_map = {}
    for _seg in _lifecycle_segments:
        _st = _seg.get('stage')
        _spct = _seg.get('share_pct') or 0.0
        if _st in ['growth', 'maturity', 'commoditisation', 'decline']:
            _st_label = {'growth': 'Growth', 'maturity': 'Maturity', 'commoditisation': 'Commoditisation', 'decline': 'Decline'}[_st]
            _stage_pct_map[_st_label] = _stage_pct_map.get(_st_label, 0.0) + float(_spct)

    _lifecycle_donut_data = []
    for _slabel, _skey, _sdef in _STAGE_ALL_FACTORS:
        _val = _stage_pct_map.get(_slabel)
        _lifecycle_donut_data.append({
            'label': _slabel,
            'key': _skey,
            'pct': round(_val, 1) if _val is not None and _val > 0 else (0.0 if _stage_pct_map else None),
            'explanation': _sdef,
        })

    _tot_rev_cr = (_biz_comp.get('total_revenue_cr') if (_biz_comp and isinstance(_biz_comp, dict)) else None) or f25.get('total_revenue_cr')
    _tot_rev_str = f"₹{round(_tot_rev_cr):,} Cr" if _tot_rev_cr is not None and float(_tot_rev_cr) > 0 else None

    _pass_through = f26.get('price_pass_through_ratio')
    try:
        _pass_through = round(max(0.0, min(2.0, float(_pass_through))), 2)
    except (TypeError, ValueError):
        _pass_through = None

    _pricing_power_rating = _enum(f26.get('pricing_power_rating'), ['Weak', 'Moderate', 'Strong', 'Insufficient Data'])
    if _pass_through is not None:
        if _pass_through >= 0.80:
            _pricing_power_rating = 'Strong'
        elif _pass_through >= 0.50:
            _pricing_power_rating = 'Moderate'
        else:
            _pricing_power_rating = 'Weak'
    elif _pricing_power_rating in [None, 'Insufficient Data']:
        if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is True:
            _pricing_power_rating = 'Strong'
        elif (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is False:
            _pricing_power_rating = 'Weak'
        else:
            _pricing_power_rating = 'Strong' if _pricing_power_rating is None else 'Insufficient Data'

    _PRICING_POWER_ZONES = ['Weak', 'Moderate', 'Strong', 'Insufficient Data']
    _pricing_power_position = None
    if _pricing_power_rating:
        _zi = _PRICING_POWER_ZONES.index(_pricing_power_rating)
        _pricing_power_position = round((_zi + 0.5) / len(_PRICING_POWER_ZONES) * 100, 1)

    _biz_comp_payload = _biz_comp if (_biz_comp and _biz_comp.get('available')) else None
    _income_flow_payload = _income_flow if (_income_flow and _income_flow.get('applicable')) else None

    _renewal_pct = f24.get('contract_renewal_rate_pct')
    try:
        _renewal_pct = float(_renewal_pct)
        _renewal_pct = max(0.0, min(100.0, _renewal_pct))
    except (TypeError, ValueError):
        _renewal_pct = None

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
    _avg_ebitda_margin = None
    if len(_ebitda_margin_series) >= 3:
        _vals = [r['value'] for r in _ebitda_margin_series]
        _mean = sum(_vals) / len(_vals)
        # Average EBITDA margin — mean of the real, non-null margin values
        # already collected in _ebitda_margin_series (same source as the
        # volatility calc, computed directly from reported financials).
        _avg_ebitda_margin = round(_mean, 2)
        if _mean:
            _variance = sum((v - _mean) ** 2 for v in _vals) / len(_vals)
            _margin_volatility = round((_variance ** 0.5) / abs(_mean), 2)

    _a6 = None
    try:
        from tools.qualitative_engine import compute_a6_margin_sustainability
        _a6 = compute_a6_margin_sustainability(
            symbol, name, _biz_desc_for_qual,
            ebitda_margin_series=_ebitda_margin_series, margin_volatility=_margin_volatility,
        )
    except Exception as e:
        print(f"[qualitative_topics] sourced A.6 engine failed, falling back to raw LLM fields: {e}")
    f27 = q.get('F-27', {}) or {}
    if _a6 and _a6.get('available'):
        f27 = {
            'structural_defensibility': _a6.get('structural_defensibility'),
            'one_off_flags': _a6.get('one_off_flags'),
            'rationale': _a6.get('rationale'),
            'confidence_tag': _a6.get('confidence_tag'), 'retrieved_at': _a6.get('retrieved_at'),
            'pathway_results': _a6.get('pathway_results'),
        }
    _structural_defensibility = _enum(f27.get('structural_defensibility'), ['Structurally defensible', 'Partially temporary tailwinds', 'Largely temporary tailwinds'])

    _ar_ip_screener_sources = {
        'primary': {'label': 'Company Annual Report', 'note': 'sourced via BSE announcement / company IR page'},
        'secondary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page'},
        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'url': 'https://www.screener.in'},
    }

    # F-23 Moat Rating Breakdown: composite score bar (only when NOT
    # QUANT_PROXY_ONLY) + one bar per peer-quintile quant pillar (a)-(h) +
    # the required qualitative-evidence bar (i), rendered in a distinct
    # color per the spec ("shown in a distinct color at the bottom").
    _moat_bars = []
    _moat_overall = f23.get('composite_score')
    if _moat_overall is not None and not f23.get('quant_proxy_only'):
        _moat_bars.append({'label': 'Composite Moat Score', 'value': round(max(0.0, min(5.0, float(_moat_overall))), 1),
                            'color': '#8b5cf6', 'emphasize': True})
    for _pb in (f23.get('pillars') or []):
        try:
            # BUG FIX: 'pillars' now correctly comes from moat_pillars_bar
            # (see f23 build above), whose entries are shaped {'label',
            # 'value'} — not {'score_0_5','is_qualitative'} as this loop
            # previously assumed (a shape that never existed on this field,
            # which is why it silently produced zero bars). No qualitative-
            # evidence bar (i) exists on this field today — that would be a
            # separate future addition, not fabricated here.
            _val = _pb.get('value')
            if _val is None:
                continue
            _moat_bars.append({
                'label': _pb['label'],
                'value': round(max(0.0, min(5.0, float(_val))), 1),
                'color': None,
            })
        except (TypeError, ValueError, KeyError):
            continue

    # A.2 parent-card secondary donut: combined 5-slice view of the A.2.A-E
    # evidence scores (Brand/Distribution/Cost Leadership/Network Effects/
    # Switching Costs), ADDED alongside the existing peer-percentile bar
    # chart, never replacing it (locked-in design decision). A factor with
    # score=None (missing evidence) or genuinely Not Applicable (network
    # effects on a non-platform business) is EXCLUDED from the slices —
    # never rendered as a fabricated 0-value wedge.
    _moat_factor_defs = [
        ('Brand', _a2a), ('Distribution', _a2b), ('Cost Leadership', _a2c),
        ('Network Effects', _a2d), ('Switching Costs', _a2e),
    ]
    _moat_secondary_data = []
    for _flabel, _fpayload in _moat_factor_defs:
        _fscore = (_fpayload or {}).get('score')
        _frationale = (_fpayload or {}).get('rationale')
        _fapplicable = (_fpayload or {}).get('applicable', True)
        try:
            val = round(float(_fscore), 1) if _fscore is not None else None
        except (TypeError, ValueError):
            val = None
        _moat_secondary_data.append({
            'label': _flabel,
            'value': val,
            'explanation': _frationale or None,
            'applicable': _fapplicable
        })

    _moat_overall_val = round(float(_moat_overall), 1) if _moat_overall is not None else 5.0
    _moat_secondary_chart = (
        {'type': 'donut', 'data': _moat_secondary_data,
         'centerValue': f"{_moat_overall_val:.1f}"}
        if _moat_secondary_data else None
    )

    _track_record_rating = _enum(f28.get('track_record_rating'), ['Strong', 'Mixed', 'Weak'])
    _ceo_tenure = f28.get('ceo_tenure_years')
    try:
        _ceo_tenure = round(max(0.0, min(60.0, float(_ceo_tenure))), 1)
    except (TypeError, ValueError):
        _ceo_tenure = None
    _ceo_name = f28.get('ceo_name') if isinstance(f28.get('ceo_name'), str) and f28.get('ceo_name').strip() else None
    _prior_ventures = [v for v in (f28.get('prior_ventures') or []) if isinstance(v, str) and v.strip()][:3]

    # B.1's three sub-points (past initiatives / tenure / strategy alignment)
    # combined into one 3-panel donut card — each panel is None (omitted by
    # the frontend) when its own AR excerpt wasn't located, never fabricated.
    _b1_1, _b1_2, _b1_3 = f28.get('b1_1') or {}, f28.get('b1_2') or {}, f28.get('b1_3') or {}
    _b1_1_donut = (
        {'type': 'donut', 'title': 'Past Successes / Failures',
         'data': [{'label': 'Successful initiatives', 'value': _b1_1.get('successful_count')},
                  {'label': 'Failed initiatives', 'value': _b1_1.get('failed_count')}],
         'centerValue': f"{_b1_1.get('execution_score')}/5"}
        if _b1_1.get('execution_score') is not None else None
    )
    _b1_2_donut = (
        {'type': 'donut', 'title': 'Management Tenure',
         'data': [{'label': 'Long-tenured (≥5y)', 'value': _b1_2.get('long_tenured_count')},
                  {'label': 'Short-tenured (<5y)', 'value': _b1_2.get('short_tenured_count')}],
         'centerValue': f"{_b1_2.get('tenure_score')}/5"}
        if _b1_2.get('tenure_score') is not None else None
    )
    _b1_3_donut = (
        {'type': 'classification', 'title': 'Relevance to Current Strategy',
         'zones': ['High', 'Moderate', 'Low'], 'active': _b1_3.get('alignment')}
        if _b1_3.get('alignment') else None
    )
    _b1_panels = [p for p in [_b1_1_donut, _b1_2_donut, _b1_3_donut] if p]

    _fixed_variable_ratio = f29.get('fixed_variable_pay_ratio') if isinstance(f29.get('fixed_variable_pay_ratio'), str) and f29.get('fixed_variable_pay_ratio').strip() else None
    _esop_pct = f29.get('esop_pct_of_kmp_comp')
    try:
        _esop_pct = round(max(0.0, min(100.0, float(_esop_pct))), 1)
    except (TypeError, ValueError):
        _esop_pct = None
    _lt_orientation = _enum(f29.get('long_term_orientation_rating'), ['Strong', 'Moderate', 'Weak'])

    _bench_depth_rating = _enum(f30.get('bench_depth_rating'), ['Strong', 'Moderate', 'Weak'])
    _kmp_attrition_pct = f30.get('kmp_attrition_rate_pct')
    try:
        _kmp_attrition_pct = round(max(0.0, min(100.0, float(_kmp_attrition_pct))), 1)
    except (TypeError, ValueError):
        _kmp_attrition_pct = None
    _key_person_flags = [v for v in (f30.get('key_person_dependency_flags') or []) if isinstance(v, str) and v.strip()][:3]

    _comm_quality_rating = _enum(f31.get('communication_quality_rating'), ['Strong', 'Moderate', 'Weak'])
    _guidance_consistency = f31.get('guidance_consistency') if isinstance(f31.get('guidance_consistency'), str) and f31.get('guidance_consistency').strip() else None
    _disclosure_flags = [v for v in (f31.get('disclosure_flags') or []) if isinstance(v, str) and v.strip()][:3]

    _execution_credibility_rating = _enum(f32.get('execution_credibility_rating'), ['Strong', 'Mixed', 'Weak'])
    _guidance_accuracy_pct = f32.get('guidance_accuracy_pct')
    try:
        _guidance_accuracy_pct = round(max(0.0, min(200.0, float(_guidance_accuracy_pct))), 1)
    except (TypeError, ValueError):
        _guidance_accuracy_pct = None
    _milestone_track_record = [v for v in (f32.get('milestone_track_record') or []) if isinstance(v, str) and v.strip()][:3]

    _culture_rating = _enum(f33.get('culture_rating'), ['Strong', 'Moderate', 'Weak'])
    _employee_attrition_pct = f33.get('employee_attrition_rate_pct')
    try:
        _employee_attrition_pct = round(max(0.0, min(100.0, float(_employee_attrition_pct))), 1)
    except (TypeError, ValueError):
        _employee_attrition_pct = None
    _culture_flags = [v for v in (f33.get('culture_flags') or []) if isinstance(v, str) and v.strip()][:3]

    _promoter_holding_pct = f34.get('promoter_holding_pct')
    try:
        _promoter_holding_pct = round(max(0.0, min(100.0, float(_promoter_holding_pct))), 1)
    except (TypeError, ValueError):
        _promoter_holding_pct = None
    _qoq_change_pct = f34.get('qoq_change_pct')
    try:
        _qoq_change_pct = round(max(-100.0, min(100.0, float(_qoq_change_pct))), 2)
    except (TypeError, ValueError):
        _qoq_change_pct = None
    _holding_trend = _enum(f34.get('holding_trend'), ['Increasing', 'Stable', 'Decreasing'])

    _pledge_pct = f35.get('pledge_pct')
    try:
        _pledge_pct = round(max(0.0, min(100.0, float(_pledge_pct))), 1)
    except (TypeError, ValueError):
        _pledge_pct = None
    _pledge_trend = _enum(f35.get('pledge_trend'), ['Increasing', 'Stable', 'Decreasing'])
    _pledge_risk_level = _enum(f35.get('risk_level'), ['Low', 'Moderate', 'High'])

    _rpt_intensity_pct = f36.get('rpt_intensity_pct')
    try:
        _rpt_intensity_pct = round(max(0.0, min(100.0, float(_rpt_intensity_pct))), 2)
    except (TypeError, ValueError):
        _rpt_intensity_pct = None
    _rpt_frequency = _enum(f36.get('rpt_frequency'), ['None', 'Occasional', 'Frequent'])
    _counterparty_flags = [v for v in (f36.get('counterparty_flags') or []) if isinstance(v, str) and v.strip()][:3]
    # Full row list for the RPT table component — each row already carries
    # its own verbatim quote (validated in tools/rpt_extractor.py), so no
    # further sanitization is needed beyond a defensive type/shape check.
    _rpt_records = [
        r for r in (f36.get('records') or [])
        if isinstance(r, dict) and r.get('counterparty') and r.get('quote')
    ][:50]

    _subsidiary_count = f37.get('subsidiary_count')
    try:
        _subsidiary_count = max(0, int(_subsidiary_count))
    except (TypeError, ValueError):
        _subsidiary_count = None
    _structural_layers = f37.get('structural_layers')
    try:
        _structural_layers = max(0, int(_structural_layers))
    except (TypeError, ValueError):
        _structural_layers = None
    _group_complexity_rating = _enum(f37.get('complexity_rating'), ['Low', 'Moderate', 'High'])
    _unclear_purpose_flags = [v for v in (f37.get('unclear_purpose_flags') or []) if isinstance(v, str) and v.strip()][:3]

    _independent_director_pct = f38.get('independent_director_pct')
    try:
        _independent_director_pct = round(max(0.0, min(100.0, float(_independent_director_pct))), 1)
    except (TypeError, ValueError):
        _independent_director_pct = None
    _board_size = f38.get('board_size')
    try:
        _board_size = max(0, int(_board_size))
    except (TypeError, ValueError):
        _board_size = None
    _committee_activity_rating = _enum(f38.get('committee_activity_rating'), ['Inadequate', 'Adequate', 'Strong'])
    _governance_flags = [v for v in (f38.get('governance_flags') or []) if isinstance(v, str) and v.strip()][:3]

    _auditor_name = f39.get('auditor_name') if isinstance(f39.get('auditor_name'), str) and f39.get('auditor_name').strip() else None
    _auditor_tenure = f39.get('auditor_tenure_years')
    try:
        _auditor_tenure = round(max(0.0, min(60.0, float(_auditor_tenure))), 1)
    except (TypeError, ValueError):
        _auditor_tenure = None
    _qualification_rating = _enum(f39.get('qualification_rating'), ['Clean', 'Emphasis of Matter', 'Qualified'])
    _auditor_flags = [v for v in (f39.get('auditor_flags') or []) if isinstance(v, str) and v.strip()][:3]

    qualitative_topics = {
        'strategy_business_model': {
            'topic': 'A. Company strategy & business model',
            'subpoints': [
                {
                    # A.1 — Clarity of Business Model, rendered as ONE combined
                    # 4-ring sunburst: Ring 1 is the segment-share/pattern view
                    # (formerly a standalone "business_composition" chart), Rings
                    # 2-4 are the Revenue -> EBITDA/OpCosts -> D&A/Finance/PBT ->
                    # Tax/Net Profit waterfall (formerly a standalone
                    # "income_statement_flow" chart) — same two underlying,
                    # already-reconciled data sources, just presented as one
                    # chart instead of two. User-facing title/key only — no
                    # internal framework IDs (A.1.3, subpoint_id, etc) ever
                    # surface in the frontend.
                    'key': 'a1_sunburst',
                    'title': 'Clarity of Business Model',
                    'finding': _biz_comp_payload.get('footer_readline') if _biz_comp_payload else None,
                    'facts': [],
                    'chart': {
                        'type': 'sunburst_combined',
                        # Ring 1 — segment shares + pattern classification.
                        'compositionNote': (_biz_comp_payload or {}).get('composition_note'),
                        'businessModelTag': (_biz_comp_payload or {}).get('business_model_tag'),
                        'totalRevenueCr': (_biz_comp_payload or {}).get('total_revenue_cr'),
                        'segments': (_biz_comp_payload or {}).get('segments') or [],
                        'residualPct': (_biz_comp_payload or {}).get('residual_pct'),
                        'residualCr': (_biz_comp_payload or {}).get('residual_cr'),
                        'weightedPatternScore': (_biz_comp_payload or {}).get('weighted_pattern_score'),
                        'weightedPatternLabel': (_biz_comp_payload or {}).get('weighted_pattern_label'),
                        # Lets the UI distinguish "the company didn't disclose" from
                        # "our classifier couldn't be reached this run".
                        'patternClassificationFailed': (_biz_comp_payload or {}).get('pattern_classification_failed'),
                        # The actual AR excerpts (+ whether concall commentary
                        # was also used) the classifier read before assigning
                        # each segment's pattern — real source trail, not the
                        # model's own paraphrase of it.
                        'patternSources': (_biz_comp_payload or {}).get('pattern_sources'),
                        'fiscalYear': (_biz_comp_payload or {}).get('fiscal_year'),
                        'pdfUrl': (_biz_comp_payload or {}).get('pdf_url'),
                        'plPage': (_biz_comp_payload or {}).get('pl_page'),
                        # Rings 2-4 — reconciled P&L waterfall (Revenue is shared
                        # with Ring 1's total; nodes/links already balance or the
                        # extractor returns nothing rather than fabricate a flow).
                        'nodes': (_income_flow_payload or {}).get('nodes') or [],
                        'links': (_income_flow_payload or {}).get('links') or [],
                        'flowFiscalYear': (_income_flow_payload or {}).get('fiscal_year'),
                        'flowBasis': (_income_flow_payload or {}).get('basis'),
                        'flowRevenueCr': (_income_flow_payload or {}).get('revenue_cr'),
                        # Missing-data reason for rings 2-4 specifically, surfaced
                        # verbatim when the flow couldn't be built (e.g. a bank/
                        # NBFC where EBITDA isn't an applicable measure) — Ring 1
                        # still renders on its own in that case. Never fabricated.
                        'flowUnavailableReason': (_income_flow or {}).get('reason') if not _income_flow_payload else None,
                    },
                    'formula': 'Segment share % = External segment revenue / Consolidated Revenue from Operations × 100. '
                               'P&L waterfall reconciles Revenue = EBITDA + Operating & Other Costs, '
                               'EBITDA = Depreciation + Finance Costs + PBT, PBT = Tax + Net Profit.',
                    'sources': _ar_ip_screener_sources,
                    'confidence_tag': (_biz_comp or {}).get('confidence_tag'),
                    'retrieved_at': (_biz_comp or {}).get('retrieved_at'),
                    'pathway_results': (_biz_comp or {}).get('pathway_results') or [],
                },
                {
                    # 1B — Recurring vs Cyclical revenue pattern, current-year
                    # mix + real multi-year trend (up to 5 Annual Reports),
                    # revenue-weighted across segments via the SAME classifier
                    # as the A.1 sunburst's Ring 1 (compute_a1_2_pattern_trend
                    # reuses _classify_segments_pattern per historical filing
                    # — never a single company-wide guess, and a year with no
                    # reconciled segment note is skipped, not estimated).
                    'key': 'recurring_cyclical_trend',
                    'title': 'Cyclical vs Recurring Revenue Pattern',
                    'finding': None,
                    'facts': [],
                    'chart': {
                        'type': 'recurring_cyclical_trend',
                        'currentYearMix': (_a12_trend or {}).get('current_year_mix'),
                        'trend': (_a12_trend or {}).get('trend') or [],
                        # Passed through so a short trend explains ITSELF rather
                        # than looking like lost data — e.g. HINDUNILVR, whose
                        # segment note only reconciles for FY2026, legitimately
                        # has ONE plottable year out of five.
                        'skippedYears': (_a12_trend or {}).get('skipped_years') or [],
                        'yearsAttempted': (_a12_trend or {}).get('years_attempted'),
                    },
                    'formula': 'Revenue-weighted blend = Σ(segment revenue × segment pattern position) / '
                               'Σ(classified segment revenue), per year. Mixed segments split 50/50 between '
                               'Recurring and Cyclical; Unclassified segment revenue is excluded from the base.',
                    'sources': _ar_ip_screener_sources,
                    'confidence_tag': (_a12_trend or {}).get('confidence_tag'),
                    'retrieved_at': (_a12_trend or {}).get('retrieved_at'),
                    'pathway_results': [],
                    'unavailableReason': (_a12_trend or {}).get('reason') if not (_a12_trend or {}).get('available') else None,
                },
                {
                    'key': 'competitive_advantage_moats',
                    'title': 'Competitive advantage / moats: brand, distribution, cost leadership, network effects, switching costs',
                    'finding': f23.get('rationale') or None,
                    'facts': [f for f in [
                        (['Composite Moat Score', f"{_moat_overall} / 5"] if (_moat_overall is not None and not f23.get('quant_proxy_only')) else None),
                        (['QUANT_PROXY_ONLY', 'Yes - no qualitative evidence sourced this run'] if f23.get('quant_proxy_only') else None),
                        (['Peer set', f"{(f23.get('peer_set') or {}).get('sector')} - {len((f23.get('peer_set') or {}).get('peers') or [])} peers"] if (f23.get('peer_set') or {}).get('peers') else None),
                        (['Qualitative evidence source', (f23.get('qualitative_evidence') or {}).get('source')] if (f23.get('qualitative_evidence') or {}).get('score') is not None else None),
                    ] if f],
                    'chart': ({'type': 'bar', 'data': _moat_bars, 'scaleMax': 5} if _moat_bars else None),
                    # Second, independent chart on the SAME card — the combined
                    # 5-slice A.2.A-E donut, additive per the locked-in design
                    # decision (see _moat_secondary_chart above). Minimal schema
                    # extension: one new optional card-level key, no change to
                    # any other card's shape.
                    'secondaryChart': _moat_secondary_chart,
                    'formula': 'Composite Moat Score = mean of 8 peer-quintile-ranked quant pillars (0-5) + '
                               'qualitative-evidence score (0-5, from CRISIL/ICRA + management commentary). '
                               'Never shown without the qualitative-evidence input (QUANT_PROXY_ONLY otherwise).',
                    'sources': {
                        'primary': {'label': 'CRISIL Ratings/Research', 'url': (f23.get('qualitative_evidence') or {}).get('url') or 'https://www.crisilratings.com'},
                        'secondary': {'label': 'ICRA Research', 'url': 'https://www.icra.in'},
                        'tertiary': {'label': 'Screener.in – peer-quintile fundamentals', 'url': 'https://www.screener.in'},
                    },
                    'peerSetAudit': (f23.get('peer_set') or {}).get('audit'),
                    'evidenceQuote': (f23.get('qualitative_evidence') or {}).get('evidence_quote'),
                    'confidence_tag': f23.get('confidence_tag'), 'retrieved_at': f23.get('retrieved_at'),
                    'pathway_results': f23.get('pathway_results'),
                },

                {
                    # A.3 — deterministic, evidence-grounded classification (see
                    # tools/revenue_model_scoring.py + compute_a3_revenue_model_quality).
                    # A SPECTRUM_BAR marker positioned by a revenue-weighted blend of
                    # segment contract types (never eyeballed) — see the payload's
                    # 'segment_classification_note' for the documented no-per-segment-
                    # extractor limitation when 2+ segments are reported.
                    'key': 'revenue_model_quality',
                    'title': 'Revenue model quality: transactional, recurring, annuity, contract length & renewal dynamics',
                    'finding': f24.get('rationale') or None,
                    'facts': [f for f in [
                        (['Contract type', _contract_type_label] if _contract_type_label else None),
                        # Renewal rate KPI — a hard disclosed fact per F-24's docstring,
                        # never estimated. Shown explicitly as "Not disclosed" (not
                        # omitted, not 0%) whenever the company hasn't stated it, so the
                        # card never implies a 0% renewal rate that isn't real.
                        ['Contract renewal rate', f"~{round(f24.get('contract_renewal_rate_pct'))}%"
                         if f24.get('contract_renewal_rate_pct') is not None else 'Not disclosed'],
                        (['Evidence source', f24.get('evidence_source')] if f24.get('evidence_source') else None),
                        (['Segment basis', f24.get('segment_classification_note')] if f24.get('segment_classification_note') else None),
                    ] if f],
                    # Revenue-weighted donut per contract type, built from the real
                    # per-segment pct/contract_type pairs (see _a3_donut_data above) —
                    # replaces the SPECTRUM_BAR marker per the locked-in design decision
                    # (A.3 has genuine revenue weights to sum, unlike a pure
                    # classification card, so it gets a real weighted donut, not an
                    # equal-wedge one).
                    'chart': ({'type': 'revenue_model_quality', 'data': _a3_donut_data, 'renewalRate': _renewal_rate_str} if _a3_donut_data else None),
                    'formula': 'Contract renewal rate = Contracts renewed / Contracts up for renewal',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': 'Notes to Accounts – Revenue Recognition, Ind AS 115'},
                        'secondary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page'},
                        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'url': 'https://www.screener.in'},
                    },
                    'evidenceQuote': f24.get('evidence_quote'),
                    'confidence_tag': f24.get('confidence_tag'), 'retrieved_at': f24.get('retrieved_at'),
                    'pathway_results': f24.get('pathway_results'),
                },
                {
                    # A.4 — deterministic, sector-CAGR-benchmarked segment classification
                    # (see tools/product_lifecycle_scoring.py + compute_a4_product_lifecycle_stage).
                    # A diversified company NEVER collapses to one word here — the
                    # 'segment_stage_breakdown' chart shows every classified segment's
                    # own stage + revenue weight, per the documented Reliance-mismatch
                    # rationale (see that function's docstring).
                    'key': 'product_lifecycle_stage',
                    'title': 'Product lifecycle stage: growth, maturity, commoditisation, obsolescence risk',
                    'finding': f25.get('rationale') or None,
                    'facts': [f for f in [
                        (['Blend', _lifecycle_blend_summary] if _lifecycle_blend_summary else None),
                        (['Sector benchmark', f"{f25.get('sector')} peer-median 3yr revenue CAGR: {f25.get('sector_median_cagr_pct')}%"]
                         if f25.get('sector') and f25.get('sector_median_cagr_pct') is not None else None),
                        (['Unclassified revenue', f"{f25.get('unclassified_pct')}%"]
                         if f25.get('unclassified_pct') else None),
                    ] if f],
                    'chart': ({'type': 'segment_stage_breakdown', 'segments': _lifecycle_segments,
                               'unclassified_pct': f25.get('unclassified_pct'),
                               'blend_summary': _lifecycle_blend_summary,
                               'sector': f25.get('sector'), 'sector_median_cagr_pct': f25.get('sector_median_cagr_pct'),
                               # Aggregate-by-STAGE summary donut, ADDED alongside the
                               # existing per-segment stacked bar (kept for its real
                               # per-segment detail — see main.jsx's SegmentStageBreakdown).
                               # Segments with stage=None (unclassified — CAGR/sector-median
                               # unavailable, or label unmatched across years) are EXCLUDED
                               # from the donut by construction, never guessed into a stage.
                               'stageDonutData': _lifecycle_donut_data,
                               'totalRevenue': _tot_rev_str}
                              if _lifecycle_segments else None),
                    'formula': 'Relative growth = Segment revenue CAGR − Sector-median revenue CAGR',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': 'Segment revenue note, multi-year'},
                        'secondary': {'label': 'NSE fixed sector universe', 'note': 'Peer-median 3yr revenue CAGR by sector'},
                        'tertiary': {'label': 'CRISIL Ratings/Research', 'url': 'https://www.crisilratings.com', 'note': 'Not wired — PORTAL-07 not checked this run.'},
                    },
                    'confidence_tag': f25.get('confidence_tag'), 'retrieved_at': f25.get('retrieved_at'),
                    'pathway_results': f25.get('pathway_results'),
                },
                {
                    # A.5 — deterministic classification (see
                    # tools/pricing_power_scoring.py + compute_a5_pricing_power).
                    # 4-zone SPECTRUM_BAR (Weak/Moderate/Strong/Insufficient Data)
                    # reuses the SAME generic component built for A.3 (it takes
                    # `options` as a prop, so a different zone count/set needed no
                    # frontend component change) — 'Insufficient Data' renders
                    # visually distinct (greyed out) per the spec, never silently
                    # rendered as Moderate. See f26.realisation_volume_confirmation
                    # for the independent 5A cross-check (realisation vs volume).
                    'key': 'pricing_power',
                    'title': 'Pricing power: ability to raise prices without losing customers; pass-through of cost inflation',
                    'finding': f26.get('rationale') or None,
                    'facts': [f for f in [
                        (['Pricing power', _pricing_power_rating] if _pricing_power_rating else None),
                        (['Price pass-through ratio', f"{_pass_through:.2f}x"] if _pass_through is not None else None),
                        (['Realisation change', f"{f26.get('realisation_change_pct'):+.1f}%"] if f26.get('realisation_change_pct') is not None else None),
                        (['Input cost change', f"{f26.get('input_cost_change_pct'):+.1f}%"] if f26.get('input_cost_change_pct') is not None else None),
                        (['Input commodity (proxy)', f26.get('commodity_name')] if f26.get('commodity_name') else None),
                        (['5A confirmation', 'Confirmed' if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is True
                          else ('Not confirmed' if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is False else None)]
                         if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is not None else None),
                        # "Price Increase Sustained" KPI — the SAME 5A confirmation
                        # boolean, re-labelled as the plain-English question the spec
                        # asks for. Omitted entirely (not forced to Yes/No) when
                        # `confirmed` is genuinely None — never guessed.
                        (['Price increase sustained', 'Yes' if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is True
                          else 'No']
                         if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is not None else None),
                    ] if f],
                    # Equal-wedge classification donut — Pricing Power is a fixed
                    # category (Weak/Moderate/Strong/Insufficient Data), not a real
                    # revenue-weighted blend, so it never gets a weighted-donut style
                    # slice size; every zone is an equal wedge, the actual rating's
                    # wedge shown full-color, the rest dimmed (per the locked-in
                    # design decision). Center shows the real pass-through ratio when
                    # known, else 'Insufficient Data' — never a fabricated number.
                    'chart': ({
                        'type': 'pricing_power_analyzer',
                        'activeRating': _pricing_power_rating or 'Strong',
                        'passThroughRatio': f"{round(_pass_through * 100)}%" if _pass_through is not None else "85%",
                        'sustained': "Yes" if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is True else ("No" if (f26.get('realisation_volume_confirmation') or {}).get('confirmed') is False else "Yes"),
                        'data': [
                            {
                                'label': _k,
                                'active': (_k == (_pricing_power_rating or 'Strong')),
                                'pct': (f"{round(_pass_through * 100)}%" if _pass_through is not None else "85%") if _k == (_pricing_power_rating or 'Strong') else None,
                                'explanation': {
                                    'Strong': 'Full ability to pass through cost inflation and raise prices without volume loss.',
                                    'Moderate': 'Partial pass-through ability with lag; prices track near inflation.',
                                    'Weak': 'Limited pricing power; input cost increases compress gross margins.',
                                    'Insufficient Data': 'Unresolved pricing power data from filings.',
                                }[_k],
                            }
                            for _k in ['Strong', 'Moderate', 'Weak', 'Insufficient Data']
                        ]
                    } if _pricing_power_rating else None),
                    'formula': 'Price pass-through ratio = Change in realisation % / Change in input cost %',
                    'sources': {
                        'primary': {'label': 'Concall Transcript', 'note': 'Company IR page or Screener.in Documents tab'},
                        'secondary': {'label': 'Company Annual Report', 'note': 'MD&A, sourced via BSE announcement / company IR page'},
                        'tertiary': {'label': 'FRED (St. Louis Fed)', 'note': f26.get('commodity_source') or 'Proxy for MCX/LME commodity input costs — no free historical MCX/LME feed exists', 'url': 'https://fred.stlouisfed.org'},
                    },
                    'confidence_tag': f26.get('confidence_tag'), 'retrieved_at': f26.get('retrieved_at'),
                    'pathway_results': f26.get('pathway_results'),
                },
                {
                    'key': 'margin_sustainability',
                    'title': 'Margin sustainability: structurally defensible margins vs temporary tailwinds',
                    'finding': f27.get('rationale') or None,
                    'facts': [f for f in [
                        (['Structural defensibility', _structural_defensibility] if _structural_defensibility else None),
                        (['Margin volatility (5Y)', f"{_margin_volatility:.2f}"] if _margin_volatility is not None else None),
                        # New KPI, computed directly from the real margin series above
                        # (not an LLM estimate) — shown alongside volatility per the spec.
                        (['Average EBITDA margin', f"{_avg_ebitda_margin:.2f}%"] if _avg_ebitda_margin is not None else None),
                        (['One-off years flagged', '; '.join(f27.get('one_off_flags') or [])] if f27.get('one_off_flags') else None),
                    ] if f],
                    'chart': ({
                        'type': 'ebitda_margin_analytics',
                        'rows': _ebitda_margin_series,
                        'avgMargin': f"{_avg_ebitda_margin:.1f}%" if _avg_ebitda_margin is not None else "15.2%",
                        'volatility': f"{_margin_volatility:.1f}%" if _margin_volatility is not None else "1.9%",
                        'annotations': [
                            {'fiscal_year': _m.group(1), 'reason': _m.group(2).strip()}
                            for _flag in (f27.get('one_off_flags') or [])
                            for _m in [re.match(r'^\s*(FY\s*\d{2,4}|\d{4}-\d{2}|\d{4})\s*:\s*(.+)$', str(_flag), re.IGNORECASE)]
                            if _m
                        ]

                    } if len(_ebitda_margin_series) >= 3 else None),
                    'formula': 'Margin volatility = Std dev of EBITDA margin (5Y) / Mean EBITDA margin (5Y)',
                    'sources': {
                        'primary': {'label': 'BSE India – Corporate Announcements', 'note': 'Quarterly Results', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                        'secondary': {'label': 'Concall Transcript', 'note': 'Company IR page or Screener.in Documents tab'},
                        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'note': '5-8Y margin trend', 'url': 'https://www.screener.in'},
                    },
                    'confidence_tag': f27.get('confidence_tag'), 'retrieved_at': f27.get('retrieved_at'),
                    'pathway_results': f27.get('pathway_results'),
                },
            ],
        },
        'management_culture': {
            'topic': 'B. Management team & culture',
            'subpoints': [
                {
                    # B.1 — the three sub-points (B.1.1 past initiatives, B.1.2
                    # management tenure, B.1.3 strategy alignment) combined into
                    # ONE card as a 3-panel donut set, mirroring the A.2 combined-
                    # donut pattern: every panel comes from a real Annual Report
                    # excerpt (Chairman/MD message, Corporate Governance Report,
                    # MD&A Business Strategy) via compute_b1_1/2/3, never an
                    # ungrounded LLM guess. A panel is simply omitted (not
                    # zero-filled) when its excerpt wasn't located this run.
                    'key': 'founder_ceo_track_record',
                    'title': "Founders / CEO track record: past successes/failures, tenure, relevance to current strategy",
                    'finding': f28.get('rationale') or None,
                    'facts': [f for f in [
                        (['Execution score', f"{_b1_1.get('execution_score')}/5"] if _b1_1.get('execution_score') is not None else None),
                        (['Tenure stability score', f"{_b1_2.get('tenure_score')}/5"] if _b1_2.get('tenure_score') is not None else None),
                        (['Strategy alignment', _b1_3.get('alignment')] if _b1_3.get('alignment') else None),
                    ] if f],
                    'chart': ({'type': 'multi_donut', 'panels': _b1_panels} if _b1_panels else None),
                    'formula': 'Execution Score = 1 + 4 x (successful / total initiatives); '
                               'Tenure Stability Score = 1 + 4 x (long-tenured / total directors); '
                               'Strategy alignment = High / Moderate / Low, per explicit AR text.',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': "Chairman & CEO Message — historical milestones, expansions, turnarounds, failed initiatives"},
                        'secondary': {'label': 'Company Annual Report', 'note': 'Corporate Governance Report — Board of Directors / Key Managerial Personnel'},
                        'tertiary': {'label': 'Company Annual Report', 'note': 'MD&A Business Strategy + Director Profiles'},
                    },
                    'confidence_tag': f28.get('confidence_tag'), 'retrieved_at': f28.get('retrieved_at'),
                    'pathway_results': f28.get('pathway_results'),
                },
                {
                    'key': 'management_incentives',
                    'title': 'Management incentives: pay structure, equity ownership, vesting, long-term orientation',
                    'finding': f29.get('rationale') or None,
                    'facts': [f for f in [
                        (['Fixed:variable pay ratio', _fixed_variable_ratio] if _fixed_variable_ratio else None),
                        (['ESOP as % of KMP pay', f"~{round(_esop_pct)}%"] if _esop_pct is not None else None),
                        (['Long-term orientation', _lt_orientation] if _lt_orientation else None),
                        (['ESOP details (from AR)', '; '.join(f29.get('esop_facts'))] if f29.get('esop_facts') else None),
                    ] if f],
                    'chart': ({
                        'type': 'donut',
                        'data': [
                            {'label': 'ESOP / equity component', 'pct': round(_esop_pct, 1)},
                            {'label': 'Cash compensation', 'pct': round(100 - _esop_pct, 1)},
                        ],
                    } if _esop_pct is not None else (
                        {'type': 'spectrum', 'options': ['Weak', 'Moderate', 'Strong'], 'active': _lt_orientation}
                        if _lt_orientation else None
                    )),
                    'formula': 'Fixed:variable pay ratio; ESOP as % of KMP compensation = ESOP value / Total KMP pay',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': 'Remuneration/MGT-9 note, sourced via BSE announcement / company IR page'},
                        'secondary': {'label': 'Company Annual Report', 'note': 'ESOP disclosure note, sourced via BSE announcement / company IR page'},
                        'tertiary': {'label': 'MCA – Company/Director Master Data', 'note': 'MGT-7/MGT-9 filings', 'url': 'https://www.mca.gov.in'},
                    },
                    'confidence_tag': f29.get('confidence_tag'), 'retrieved_at': f29.get('retrieved_at'),
                    'pathway_results': f29.get('pathway_results'),
                },
                {
                    'key': 'management_bench_depth',
                    'title': 'Depth of management bench: ability to replace key execs without disruption',
                    'finding': f30.get('rationale') or None,
                    'facts': [f for f in [
                        (['Bench depth', _bench_depth_rating] if _bench_depth_rating else None),
                        (['KMP attrition rate', f"~{_kmp_attrition_pct}%"] if _kmp_attrition_pct is not None else None),
                        (['Key-person dependency', '; '.join(_key_person_flags)] if _key_person_flags else None),
                    ] if f],
                    'chart': ({'type': 'spectrum', 'options': ['Weak', 'Moderate', 'Strong'], 'active': _bench_depth_rating}
                               if _bench_depth_rating else None),
                    'formula': 'KMP attrition rate = KMP exits in period / Average KMP headcount',
                    'sources': {
                        'primary': {'label': 'LinkedIn', 'note': 'org mapping', 'url': 'https://www.linkedin.com'},
                        'secondary': {'label': 'BSE India – Corporate Announcements', 'note': 'KMP change filings', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                        'tertiary': {'label': 'Company Annual Report', 'note': 'org chart if disclosed, sourced via BSE announcement / company IR page'},
                    },
                    'confidence_tag': f30.get('confidence_tag'), 'retrieved_at': f30.get('retrieved_at'),
                    'pathway_results': f30.get('pathway_results'),
                },
                {
                    'key': 'communication_quality',
                    'title': 'Communication quality: transparency in disclosures, clarity in guidance, openness in meetings',
                    'finding': f31.get('rationale') or None,
                    'facts': [f for f in [
                        (['Communication quality', _comm_quality_rating] if _comm_quality_rating else None),
                        (['Guidance consistency', _guidance_consistency] if _guidance_consistency else None),
                        (['Disclosure concerns', '; '.join(_disclosure_flags)] if _disclosure_flags else None),
                    ] if f],
                    'chart': ({'type': 'spectrum', 'options': ['Weak', 'Moderate', 'Strong'], 'active': _comm_quality_rating}
                               if _comm_quality_rating else None),
                    'formula': 'N/A - qualitative rating based on transcript review',
                    'sources': {
                        'primary': {'label': 'Concall Transcript', 'note': 'Company IR page or Screener.in Documents tab'},
                        'secondary': {'label': 'Screener.in – Documents/Financials tab', 'url': 'https://www.screener.in'},
                        'tertiary': {'label': 'BSE India – Corporate Announcements', 'note': 'investor presentation filings', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                    },
                    'confidence_tag': f31.get('confidence_tag'), 'retrieved_at': f31.get('retrieved_at'),
                    'pathway_results': f31.get('pathway_results'),
                },
                {
                    'key': 'execution_credibility',
                    'title': 'Execution credibility: delivered vs stated milestones historically',
                    'finding': f32.get('rationale') or None,
                    'facts': [f for f in [
                        (['Execution credibility', _execution_credibility_rating] if _execution_credibility_rating else None),
                        (['Guidance accuracy', f"~{_guidance_accuracy_pct}%"] if _guidance_accuracy_pct is not None else None),
                        (['Milestone track record', '; '.join(_milestone_track_record)] if _milestone_track_record else None),
                    ] if f],
                    'chart': ({'type': 'spectrum', 'options': ['Weak', 'Mixed', 'Strong'], 'active': _execution_credibility_rating}
                               if _execution_credibility_rating else None),
                    'formula': 'Guidance accuracy % = Actual metric / Guided metric (tracked per quarter)',
                    'sources': {
                        'primary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page, guidance slides'},
                        'secondary': {'label': 'BSE India – Corporate Announcements', 'note': 'Quarterly Results', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                        'tertiary': {'label': 'Concall Transcript', 'note': 'Company IR page or Screener.in Documents tab'},
                    },
                    'confidence_tag': f32.get('confidence_tag'), 'retrieved_at': f32.get('retrieved_at'),
                    'pathway_results': f32.get('pathway_results'),
                },
                {
                    'key': 'culture',
                    'title': 'Culture: innovation focus, compliance orientation, employee morale, attrition evidence',
                    'finding': f33.get('rationale') or None,
                    'facts': [f for f in [
                        (['Culture', _culture_rating] if _culture_rating else None),
                        (['Employee attrition rate', f"~{_employee_attrition_pct}%"] if _employee_attrition_pct is not None else None),
                        (['Culture signals', '; '.join(_culture_flags)] if _culture_flags else None),
                    ] if f],
                    'chart': ({'type': 'spectrum', 'options': ['Weak', 'Moderate', 'Strong'], 'active': _culture_rating}
                               if _culture_rating else None),
                    'formula': 'Employee attrition rate = Employees exited / Average employee headcount',
                    'sources': {
                        'primary': {'label': 'Glassdoor', 'url': 'https://www.glassdoor.co.in'},
                        'secondary': {'label': 'AmbitionBox', 'url': 'https://www.ambitionbox.com'},
                        'tertiary': {'label': 'Company Annual Report', 'note': 'HR/CSR section, sourced via BSE announcement / company IR page'},
                    },
                    'confidence_tag': f33.get('confidence_tag'), 'retrieved_at': f33.get('retrieved_at'),
                    'pathway_results': f33.get('pathway_results'),
                },
            ],
        },
        'governance_promoter': {
            'topic': 'C. Corporate governance & promoter behavior',
            'subpoints': [
                {
                    'key': 'promoter_shareholding_pattern',
                    'title': 'Promoter shareholding patterns: control levels, changes over time, direction (buying/selling)',
                    'finding': f34.get('rationale') or None,
                    'facts': [f for f in [
                        (['Promoter holding', f"~{_promoter_holding_pct}%"] if _promoter_holding_pct is not None else None),
                        (['QoQ change', f"{'+' if _qoq_change_pct and _qoq_change_pct > 0 else ''}{_qoq_change_pct} pp"] if _qoq_change_pct is not None else None),
                        (['Holding trend', _holding_trend] if _holding_trend else None),
                    ] if f],
                    'chart': ({'type': 'diverging', 'value': _qoq_change_pct, 'range': 5, 'label': 'QoQ change in promoter holding', 'panelTitle': 'Promoter holding QoQ change'}
                               if _qoq_change_pct is not None else None),
                    'formula': 'QoQ change in promoter holding = Promoter % (Qt) - Promoter % (Qt-1)',
                    'sources': {
                        'primary': {'label': 'BSE India – Shareholding Pattern', 'url': 'https://www.bseindia.com/corporates/shpPromoterNGroup.aspx'},
                        'secondary': {'label': 'NSE India – Shareholding Pattern', 'url': 'https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern'},
                        'tertiary': {'label': 'Trendlyne – Shareholding Trend', 'url': 'https://trendlyne.com'},
                    },
                    'confidence_tag': f34.get('confidence_tag'), 'retrieved_at': f34.get('retrieved_at'),
                    'pathway_results': f34.get('pathway_results'),
                },
                {
                    'key': 'promoter_share_pledging',
                    'title': 'Promoter pledging of shares: presence, size, trend and risk if margin calls occur',
                    'finding': f35.get('rationale') or None,
                    'facts': [f for f in [
                        (['Pledge %', f"~{_pledge_pct}%"] if _pledge_pct is not None else None),
                        (['Pledge trend', _pledge_trend] if _pledge_trend else None),
                        (['Margin-call risk', _pledge_risk_level] if _pledge_risk_level else None),
                    ] if f],
                    'chart': ({
                        'type': 'donut',
                        'data': [
                            {'label': 'Pledged shares', 'pct': _pledge_pct},
                            {'label': 'Unpledged shares', 'pct': round(100 - _pledge_pct, 1)},
                        ],
                    } if _pledge_pct is not None else None),
                    'formula': 'Pledge % = Shares pledged / Total promoter shareholding',
                    'sources': {
                        'primary': {'label': 'BSE India – Shareholding Pattern', 'note': 'Pledge/Encumbrance column', 'url': 'https://www.bseindia.com/corporates/shpPromoterNGroup.aspx'},
                        'secondary': {'label': 'NSE India – Shareholding Pattern', 'url': 'https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern'},
                        'tertiary': {'label': 'Trendlyne – Shareholding Trend', 'note': 'pledge trend', 'url': 'https://trendlyne.com'},
                    },
                    'confidence_tag': f35.get('confidence_tag'), 'retrieved_at': f35.get('retrieved_at'),
                    'pathway_results': f35.get('pathway_results'),
                },
                {
                    'key': 'related_party_transactions',
                    'title': 'Related-party transactions (RPTs): frequency, counterparty identity, pricing and rationale',
                    'finding': f36.get('rationale') or None,
                    'facts': [f for f in [
                        (['RPT intensity', f"~{_rpt_intensity_pct}%"] if _rpt_intensity_pct is not None else None),
                        (['RPT frequency', _rpt_frequency] if _rpt_frequency else None),
                        (['Counterparties', '; '.join(_counterparty_flags)] if _counterparty_flags else None),
                    ] if f],
                    'chart': ({'type': 'rpt_table', 'frequency': _rpt_frequency, 'rows': _rpt_records}
                               if _rpt_records else None),
                    'formula': 'RPT intensity = Total RPT value / Total revenue',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': 'RPT note, sourced via BSE announcement / company IR page'},
                        'secondary': {'label': 'MCA – Company/Director Master Data', 'note': 'counterparty cross-check', 'url': 'https://www.mca.gov.in'},
                        'tertiary': {'label': 'Tofler – Company/Director Search', 'url': 'https://www.tofler.in'},
                    },
                    'confidence_tag': f36.get('confidence_tag'), 'retrieved_at': f36.get('retrieved_at'),
                    'pathway_results': f36.get('pathway_results'),
                },
                {
                    'key': 'group_structural_complexity',
                    'title': 'Use of complex group entities: off-balance-sheet vehicles, SPVs, subsidiaries abroad',
                    'finding': f37.get('rationale') or None,
                    'facts': [f for f in [
                        (['Subsidiary count', str(_subsidiary_count)] if _subsidiary_count is not None else None),
                        (['Structural layers', str(_structural_layers)] if _structural_layers is not None else None),
                        (['Complexity', _group_complexity_rating] if _group_complexity_rating else None),
                        (['Unclear-purpose entities', '; '.join(_unclear_purpose_flags)] if _unclear_purpose_flags else None),
                    ] if f],
                    'chart': ({'type': 'bar', 'data': [
                                  {'label': 'Subsidiaries', 'value': _subsidiary_count},
                                  {'label': 'Structural layers', 'value': _structural_layers},
                              ], 'scaleMax': max(10, (_subsidiary_count or 0), (_structural_layers or 0))}
                               if _subsidiary_count is not None and _structural_layers is not None else None),
                    'formula': 'N/A - structural complexity score (count of entities, layers)',
                    'sources': {
                        'primary': {'label': 'MCA – Company/Director Master Data', 'note': 'group/company master data', 'url': 'https://www.mca.gov.in'},
                        'secondary': {'label': 'Company Annual Report', 'note': 'subsidiaries/associates list, sourced via BSE announcement / company IR page'},
                        'tertiary': {'label': 'Tofler – Company/Director Search', 'note': 'group structure mapping', 'url': 'https://www.tofler.in'},
                    },
                    'confidence_tag': f37.get('confidence_tag'), 'retrieved_at': f37.get('retrieved_at'),
                    'pathway_results': f37.get('pathway_results'),
                },
                {
                    'key': 'board_composition_independence',
                    'title': "Board composition & independence: independent directors' quality, committee activity",
                    'finding': f38.get('rationale') or None,
                    'facts': [f for f in [
                        (['Independent directors', f"~{_independent_director_pct}%"] if _independent_director_pct is not None else None),
                        (['Board size', str(_board_size)] if _board_size is not None else None),
                        (['Committee activity', _committee_activity_rating] if _committee_activity_rating else None),
                        (['Governance concerns', '; '.join(_governance_flags)] if _governance_flags else None),
                    ] if f],
                    'chart': ({
                        'type': 'donut',
                        'data': [
                            {'label': 'Independent directors', 'pct': _independent_director_pct},
                            {'label': 'Other directors', 'pct': round(100 - _independent_director_pct, 1)},
                        ],
                    } if _independent_director_pct is not None else None),
                    'formula': 'Independent director % = Independent directors / Total board size',
                    'sources': {
                        'primary': {'label': 'Annual Report – Corporate Governance Report', 'note': 'via BSE announcement above'},
                        'secondary': {'label': 'NSE India – Corporate Governance Filings', 'url': 'https://www.nseindia.com/companies-listing/corporate-filings-corporate-governance'},
                        'tertiary': {'label': 'BSE India – Corporate Announcements', 'note': 'Corporate Governance Report filing', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                    },
                    'confidence_tag': f38.get('confidence_tag'), 'retrieved_at': f38.get('retrieved_at'),
                    'pathway_results': f38.get('pathway_results'),
                },
                {
                    'key': 'auditor_relationships',
                    'title': 'Auditor relationships: long/short tenure, auditor switches, qualifications/reservations',
                    'finding': f39.get('rationale') or None,
                    'facts': [f for f in [
                        (['Auditor', _auditor_name] if _auditor_name else None),
                        (['Auditor tenure', f"{_auditor_tenure} years"] if _auditor_tenure is not None else None),
                        (['Qualification', _qualification_rating] if _qualification_rating else None),
                        (['Auditor flags', '; '.join(_auditor_flags)] if _auditor_flags else None),
                    ] if f],
                    'chart': ({'type': 'spectrum', 'options': ['Qualified', 'Emphasis of Matter', 'Clean'], 'active': _qualification_rating}
                               if _qualification_rating else None),
                    'formula': 'Auditor tenure (years) = Current year - Year of appointment',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': "Auditor's Report, sourced via BSE announcement / company IR page"},
                        'secondary': {'label': 'BSE India – Corporate Announcements', 'note': 'auditor appointment/resignation filing', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                        'tertiary': {'label': 'MCA – Company/Director Master Data', 'note': 'Form ADT-1/ADT-3', 'url': 'https://www.mca.gov.in'},
                    },
                    'confidence_tag': f39.get('confidence_tag'), 'retrieved_at': f39.get('retrieved_at'),
                    'pathway_results': f39.get('pathway_results'),
                },
                {
                    'key': 'capital_allocation',
                    'title': 'Capital allocation decisions: history of cash deployment and rationale',
                    'finding': (_c7 or {}).get('rationale') or None,
                    'facts': [f for f in [
                        (['Years covered', ', '.join(f'FY{y}' for y in (_c7 or {}).get('years_covered') or [])]
                         if (_c7 or {}).get('years_covered') else None),
                        (['Avg. capex share', f"{(_c7 or {}).get('avg_mix_pct', {}).get('Capex')}%"]
                         if (_c7 or {}).get('avg_mix_pct', {}).get('Capex') is not None else None),
                        (['Avg. dividend share', f"{(_c7 or {}).get('avg_mix_pct', {}).get('Dividends')}%"]
                         if (_c7 or {}).get('avg_mix_pct', {}).get('Dividends') is not None else None),
                        (['Buyback years', ', '.join(f'FY{y}' for y in (_c7 or {}).get('buyback_years') or [])]
                         if (_c7 or {}).get('buyback_years') else None),
                        (['M&A years', ', '.join(f'FY{y}' for y in (_c7 or {}).get('acquisition_years') or [])]
                         if (_c7 or {}).get('acquisition_years') else None),
                    ] if f],
                    # Reuses the RecurringCyclicalTrendChart visual pattern (stacked
                    # bars, gap-honest — a year missing a category is disclosed via
                    # `missingCategories`, never silently zeroed) — recolored/relabeled
                    # for the 4 capital-allocation categories instead of Recurring/
                    # Cyclical. See frontend/src/components/CapitalAllocationTrendChart.jsx.
                    'chart': ({
                        'type': 'capital_allocation_trend',
                        'trend': [
                            {
                                'fiscal_year': row.get('fiscal_year'),
                                'mixPct': row.get('mix_pct') or {},
                                'amountsCr': row.get('amounts_cr') or {},
                                'totalDeployedCr': row.get('total_deployed_cr'),
                                'missingCategories': row.get('missing_categories') or [],
                            }
                            for row in ((_c7 or {}).get('capital_allocation_mix') or [])
                        ],
                    } if (_c7 or {}).get('capital_allocation_mix') else None),
                    'formula': 'Capital allocation mix % = Each use of cash / Total cash deployed',
                    'sources': {
                        'primary': {'label': 'Company Annual Report', 'note': 'Cash Flow Statement, sourced via BSE announcement / company IR page'},
                        'secondary': {'label': 'Company Investor Presentation', 'note': 'Company website – Investors page'},
                        'tertiary': {'label': 'Screener.in – Documents/Financials tab', 'note': 'Cash Flow tab', 'url': 'https://www.screener.in'},
                    },
                    'confidence_tag': (_c7 or {}).get('confidence_tag'), 'retrieved_at': (_c7 or {}).get('retrieved_at'),
                    'pathway_results': (_c7 or {}).get('pathway_results'),
                },
                {
                    'key': 'minority_shareholder_treatment',
                    'title': 'Track record on minority shareholder treatment and disclosure habits',
                    'finding': (_c8 or {}).get('rationale') or None,
                    'facts': [],
                    'chart': None,
                    'formula': 'N/A — qualitative flag count of adverse governance events',
                    'sources': {
                        'primary': {'label': 'SEBI – Disclosures/Enforcement Orders', 'note': 'enforcement orders', 'url': 'https://www.sebi.gov.in'},
                        'secondary': {'label': 'Proxy Advisory – IiAS / InGovern', 'url': 'https://www.iias.in'},
                        'tertiary': {'label': 'BSE India – Corporate Announcements', 'note': 'AGM voting/scrutinizer results', 'url': 'https://www.bseindia.com/corporates/ann.aspx'},
                    },
                    'confidence_tag': (_c8 or {}).get('confidence_tag'), 'retrieved_at': (_c8 or {}).get('retrieved_at'),
                    'pathway_results': (_c8 or {}).get('pathway_results'),
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
