# Navrist AI Qualitative Analysis Framework

> Source: `Navrist_Qualitative.xlsx`. This file is the authoritative
> qualitative-analysis task catalogue and visualization guide.

## Critical implementation rule

-   The framework is **company-independent**. Every task must be
    executable for every company in the NSE universe supplied by the
    application's NSE scraper.
-   A task must never be hard-wired to the company currently open in the
    frontend.
-   `company_id` / NSE symbol is an explicit input to every research,
    retrieval, scoring, caching, and persistence operation.
-   Missing evidence must be returned as `INSUFFICIENT_DATA` or
    `NOT_APPLICABLE`, never silently converted to Neutral.
-   Evidence must retain source URL, document/announcement date,
    reporting period, and a short supporting excerpt or structured
    datapoint.

## Workbook columns

  -----------------------------------------------------------------------
  Column                              Meaning
  ----------------------------------- -----------------------------------
  Sr. No.                             Task/question identifier

  Title                               Research question or sub-task

  Primary Source (NSE Link + Filing   Preferred retrieval path/source
  Path)                               

  Formula / Matrix                    Classification/scoring rule

  How to Show (Graph)                 Frontend visualization rule
  -----------------------------------------------------------------------

## A-U task catalogue

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  ID                Title                   Primary Source / Filing Path                                                         Formula / Matrix                           Frontend Display
  ----------------- ----------------------- ------------------------------------------------------------------------------------ ------------------------------------------ -----------------------
  A. Company                                                                                                                                                                
  strategy &                                                                                                                                                                
  business model                                                                                                                                                            

  1                 Clarity of business                                                                                                                                     
                    model: single product                                                                                                                                   
                    vs portfolio; cyclical                                                                                                                                  
                    vs recurring revenue                                                                                                                                    

  1A                Single product vs       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  1 segment OR one segment ≥90% of revenue = Donut chart: Single
                    Portfolio/Diversified   Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Single Product; otherwise =                product vs
                    (segment count          select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      Portfolio/Diversified.                     Portfolio/Diversified
                    classification)         Segment Information (Ind AS 108) → count reported segments and capture each                                                     (segment count
                                            segment's external revenue.                                                                                                     classification) \|
                                                                                                                                                                            Colors: Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  1B                Cyclical vs Recurring   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Revenue-weighted blend of segment          Donut chart: Cyclical
                    revenue pattern         Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → classifications: Recurring =               vs Recurring revenue
                    (revenue-weighted blend select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      subscription/annuity/long-term serviced    pattern
                    across segments)        Segment Information (Ind AS 108) → read each segment's own business description in   contracts; Cyclical =                      (revenue-weighted blend
                                            MD&A / Business Overview.                                                            commodity/order-book/discretionary-spend   across segments) \|
                                                                                                                                 linked; Mixed only where a genuine blend   Colors: Positive=Green,
                                                                                                                                 is evidenced.                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  2                 Competitive advantage /                                                                                                                                 
                    moats: brand,                                                                                                                                           
                    distribution, cost                                                                                                                                      
                    leadership, network                                                                                                                                     
                    effects, switching                                                                                                                                      
                    costs                                                                                                                                                   

  2A                Brand                   CRISIL Ratings → https://www.crisilratings.com/ → Ratings / Research → search issuer 5 = specific named and dated evidence; 4 = KPI Card: Brand \|
                                            → latest Rating Rationale → Key Rating Drivers / Business Risk Profile → capture     specific but limited/older; 3 = generic    Colors: Positive=Green,
                                            specific brand / market-position evidence; cross-check NSE Annual Report → MD&A /    relevant evidence; 2 = management claim    Neutral=Blue,
                                            Business Overview.                                                                   only; 1 = vague boilerplate; Missing = no  Negative=Red,
                                                                                                                                 usable evidence.                           Insufficient/N/A=Grey

  2B                Distribution            NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Same 1--5 evidence rubric. Specific reach, KPI Card: Distribution
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → exclusivity or dated network depth scores  \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A / Distribution /    higher than generic 'wide network'         Positive=Green,
                                            Network → dated outlet/dealer counts, reach or exclusivity; cross-check CRISIL/ICRA  language.                                  Neutral=Blue,
                                            rationale.                                                                                                                      Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  2C                Cost leadership         CRISIL Ratings → https://www.crisilratings.com/ → Ratings / Research → search issuer 1--5 evidence score. A margin lead without KPI Card: Cost
                                            → latest Rating Rationale → Key Rating Drivers / Business Risk Profile → identify    a disclosed structural reason is not full  leadership \| Colors:
                                            named structural cost advantage; cross-check NSE Annual Report → MD&A → scale,       cost-leadership evidence.                  Positive=Green,
                                            efficiency, captive integration, technology.                                                                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  2D                Network effects         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  1--5 only where measurable network linkage KPI Card: Network
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → is shown; if genuinely not applicable,     effects \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A / Business Overview mark N/A rather than forcing a low score.  Positive=Green,
                                            / Platform / Ecosystem → measurable linkage between user/customer growth and value                                              Neutral=Blue,
                                            to existing users.                                                                                                              Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  2E                Switching costs         CRISIL Ratings → https://www.crisilratings.com/ → Ratings / Research → search issuer 1--5 evidence score. Strong evidence       KPI Card: Switching
                                            → latest Rating Rationale → Key Rating Drivers → contract terms, renewal rates or    requires a specific term, actual renewal   costs \| Colors:
                                            regulatory/certification barriers; cross-check NSE Annual Report → Notes to Accounts evidence or a clear switching barrier.     Positive=Green,
                                            → Revenue from Contracts with Customers (Ind AS 115).                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  3                 Revenue model quality:                                                                                                                                  
                    transactional,                                                                                                                                          
                    recurring, annuity,                                                                                                                                     
                    contract length &                                                                                                                                       
                    renewal dynamics                                                                                                                                        

  3A                Transactional           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Classify only when the segment's own Ind   KPI Card: Transactional
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → AS 115 policy supports a one-time          \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      point-in-time sale.                        Positive=Green,
                                            Revenue from Contracts with Customers / Revenue Recognition (Ind AS 115) → read each                                            Neutral=Blue,
                                            segment's own policy → point-in-time recognition with no ongoing service obligation.                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  3B                Recurring               NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Recurring when revenue repeats over time   Line chart: Recurring
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → and has no defined end-of-term; a stated   \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      duration moves it to Annuity.              Positive=Green,
                                            Revenue from Contracts with Customers / Revenue Recognition (Ind AS 115) →                                                      Neutral=Blue,
                                            repeat/subscription revenue recognised over time without a defined term.                                                        Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  3C                Annuity                 NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Annuity only when periodic payments have a KPI Card: Annuity \|
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → defined contract term.                     Colors: Positive=Green,
                                            select reporting year → open Annual Report attachment/PDF → Revenue Recognition (Ind                                            Neutral=Blue,
                                            AS 115) → periodic payments over a defined contractual term.                                                                    Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  3D                Contract length &       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Renewal Rate = Contracts Renewed ÷         KPI Card: Contract
                    renewal dynamics        Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Contracts Up for Renewal. If either figure length & renewal
                                            select reporting year → open Annual Report attachment/PDF → MD&A / contract          is unavailable = NOT_DISCLOSED.            dynamics \| Colors:
                                            disclosures → renewal, retention and contract-term evidence; cross-check company                                                Positive=Green,
                                            Investor Presentation.                                                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  4                 Product lifecycle                                                                                                                                       
                    stage: growth,                                                                                                                                          
                    maturity,                                                                                                                                               
                    commoditisation,                                                                                                                                        
                    obsolescence risk                                                                                                                                       

  4A                Growth                  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Growth when segment CAGR is materially     Donut chart: Growth \|
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → above its own sector median.               Colors: Positive=Green,
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →                                                 Neutral=Blue,
                                            Segment Information → calculate segment 3--5Y CAGR → compare with identical NSE                                                 Negative=Red,
                                            sector/sub-sector peer median.                                                                                                  Insufficient/N/A=Grey

  4B                Maturity                NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Maturity when segment CAGR is roughly in   Donut chart: Maturity
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → line with its sector CAGR.                 \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Segment Information →                                               Positive=Green,
                                            calculate segment CAGR → compare with sector median.                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  4C                Commoditisation         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Commoditisation only when segment CAGR is  Donut chart:
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → persistently below sector CAGR AND segment Commoditisation \|
                                            select reporting year → open Annual Report attachment/PDF → Segment Information →    margin is compressing.                     Colors: Positive=Green,
                                            segment CAGR + segment margin trend → compare with sector median.                                                               Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  4D                Obsolescence risk       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Decline when segment revenue CAGR is       Donut chart:
                    (Decline)               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → negative over the measurement window; do   Obsolescence risk
                                            select reporting year → open Annual Report attachment/PDF → Segment Information →    not use a single weak quarter.             (Decline) \| Colors:
                                            actual multi-year revenue history with ≥3 comparable points.                                                                    Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  5                 Pricing power: ability                                                                                                                                  
                    to raise prices without                                                                                                                                 
                    losing customers;                                                                                                                                       
                    pass-through of cost                                                                                                                                    
                    inflation                                                                                                                                               

  5A                Ability to raise prices Company Investor Relations → Investors → Earnings / Results → Concall Transcript →   Pricing power confirmed when realisation   KPI Card: Ability to
                    without losing          realisation-per-unit trend + same-period volume trend; cross-check NSE Annual Report rises while volume holds or grows. Rising  raise prices without
                    customers               → MD&A / operating KPIs.                                                             realisation with materially falling volume losing customers \|
                                                                                                                                 is not confirmed pricing power.            Colors: Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  5B                Pass-through of cost    Company Investor Relations → Concall Transcript / MD&A → realisation trend → MCX /   Pass-through Ratio = % Change in           KPI Card: Pass-through
                    inflation               LME → historical matching input-cost series for the same rolling quarters.           Realisation ÷ % Change in Input Cost.      of cost inflation \|
                                                                                                                                 Missing either required series =           Colors: Positive=Green,
                                                                                                                                 INSUFFICIENT_DATA.                         Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  6                 Margin sustainability:                                                                                                                                  
                    structurally defensible                                                                                                                                 
                    margins vs temporary                                                                                                                                    
                    tailwinds                                                                                                                                               

  6A                Structurally defensible NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Margin Volatility = Std Dev of EBITDA      Line chart:
                    margins                 → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → Margin (5Y) ÷ Mean EBITDA Margin (5Y).     Structurally defensible
                                            Period Ended → select period → Search By → open Financial Results Detail / XBRL;     Defensible only when volatility is low AND margins \| Colors:
                                            calculate EBITDA margin for 5--8FY + TTM and volatility.                             margin is flat/rising.                     Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  6B                Temporary tailwinds     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  For every flagged outlier, cite the exact  Line chart: Temporary
                    (one-off / exceptional  Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → disclosed one-off item. If none is         tailwinds (one-off /
                    items)                  select reporting year → open Annual Report attachment/PDF → Statement of Profit &    disclosed, state 'Unexplained by disclosed exceptional items) \|
                                            Loss → Exceptional Items → supporting note for each flagged year.                    exceptional items' and do not invent a     Colors: Positive=Green,
                                                                                                                                 reason.                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B. Management                                                                                                                                                             
  team & culture                                                                                                                                                            

  B1                                                                                                                                                                        

  B1.1              Past successes /        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Initiative Success Rate = (Successfully    Donut chart: Past
                    failures                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Completed Strategic Initiatives ÷ Total    successes / failures \|
                                            select reporting year → open Annual Report attachment/PDF→ Board's Report → MD&A →   Major Strategic Initiatives Announced in   Colors: Positive=Green,
                                            Chairman & CEO Message; AND NSE →                                                    Last 5 Years) × 100. Score: ≥80%=5,        Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →         65--79%=4, 50--64%=3, 30--49%=2, \<30%=1.  Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment                                               

  B1.2              Management tenure       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Average Leadership Tenure = (CEO Tenure +  Donut chart: Management
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → CFO Tenure + Executive Director Tenure) ÷  tenure \| Colors:
                                            select reporting year → open Annual Report attachment/PDF→ Corporate Governance      Number of Key Executives. Score: \>10      Positive=Green,
                                            Report → Board of Directors → Key Managerial Personnel; AND NSE →                    years=5, 7--10=4, 4--7=3, 2--4=2, \<2=1.   Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment                                               

  B1.3              Relevance to current    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Strategy Alignment Score = (Leadership     Donut chart: Relevance
                    strategy                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Experience Areas Matching Current          to current strategy \|
                                            select reporting year → open Annual Report attachment/PDF→ MD&A → Business Strategy  Strategic Priorities ÷ Total Current       Colors: Positive=Green,
                                            → Chairman & CEO Message → Director Profiles; AND NSE →                              Strategic Priorities) × 100. Score:        Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →         ≥80%=5, 65--79%=4, 50--64%=3, 30--49%=2,   Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      \<30%=1.                                   Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment                                               

  B2                Management incentives                                                                                                                                   

  B2.1              Pay structure           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Use remuneration disclosures, commission,  KPI Card: Pay structure
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → bonus, incentives, ESOPs, and stock-based  \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance     compensation                               Positive=Green,
                                            Report → Remuneration to Directors/KMP.                                                                                         Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B2.2              Equity ownership        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Use promoter holding, director holdings,   Donut chart: Equity
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → and KMP holdings from shareholding tables  ownership \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance                                                Positive=Green,
                                            Report → Shareholding of Directors and KMP.                                                                                     Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B2.3              Vesting structure       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Use ESOP grant date, vesting schedule,     Donut chart: Vesting
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → exercise period, and option life           structure \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance                                                Positive=Green,
                                            Report → ESOP / Stock Option Scheme → Vesting Schedule.                                                                         Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B2.4              Long-term orientation   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Infer from ESOP duration, vesting horizon, KPI Card: Long-term
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → and performance-linked incentives          orientation \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Remuneration Policy →                                               Positive=Green,
                                            Performance-linked Long-term Incentives.                                                                                        Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B3                Depth of management                                                                                                                                     
                    bench                                                                                                                                                   

  B3.1              Leadership depth        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Leadership Depth Score (1--5).             KPI Card: Leadership
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            depth \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Senior Management                                                   Positive=Green,
                                            Personnel → Executive Leadership Team.                                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B3.2              Succession readiness    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Succession Readiness Score (1--5).         KPI Card: Succession
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            readiness \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Nomination &                                                        Positive=Green,
                                            Remuneration Committee Report → Succession Planning.                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B3.3              Key executive           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Key-person Dependency Score (1--5).        KPI Card: Key executive
                    dependency              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            dependency \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance                                                Positive=Green,
                                            Report → Management Structure.                                                                                                  Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B4                Communication quality                                                                                                                                   

  B4.1              Transparency in         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Disclosure Transparency Score (1--5).      KPI Card: Transparency
                    disclosures             Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            in disclosures \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Notes to Accounts                                            Colors: Positive=Green,
                                            → Risk Disclosures.                                                                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B4.2                                                                                                                                                                      

  B4.3              Openness in investor    NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Investor Communication Score (1--5).       KPI Card: Openness in
                    communication           Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 investor communication
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment                                               Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B5                Execution credibility                                                                                                                                   

  B5.1              Delivered vs stated     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Execution Ratio = Achieved ÷ Announced.    KPI Card: Delivered vs
                    milestones              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            stated milestones \|
                                            select reporting year → open Annual Report attachment/PDF→ MD&A → compare announced                                             Colors: Positive=Green,
                                            milestones with actual outcomes.                                                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B5.2              Capital allocation      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Capital Execution Score (1--5).            KPI Card: Capital
                    execution               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            allocation execution \|
                                            select reporting year → open Annual Report attachment/PDF→ Board's Report → Capex &                                             Colors: Positive=Green,
                                            Acquisition Updates.                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B5.3              Strategic execution     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Consistency Score (1--5).                  Line chart: Strategic
                    consistency             Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            execution consistency
                                            select reporting year → open Annual Report attachment/PDF→ MD&A → compare strategy                                              \| Colors:
                                            statements across years.                                                                                                        Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B6                Culture                                                                                                                                                 

  B6.1              Innovation focus        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Innovation Score (1--5).                   KPI Card: Innovation
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            focus \| Colors:
                                            select reporting year → open Annual Report attachment/PDF                                                                       Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B6.2              Compliance orientation  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Compliance Score (1--5).                   KPI Card: Compliance
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            orientation \| Colors:
                                            select reporting year → open Annual Report attachment/PDF→ Corporate Governance                                                 Positive=Green,
                                            Report → Vigil Mechanism → Internal Controls.                                                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B6.3              Employee morale         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Employee Engagement Score (1--5).          KPI Card: Employee
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            morale \| Colors:
                                            select reporting year → open Annual Report attachment/PDF→ Human Resources section →                                            Positive=Green,
                                            employee engagement initiatives.                                                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  B6.4              Attrition evidence      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Attrition Stability Score (1--5).          KPI Card: Attrition
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            evidence \| Colors:
                                            select reporting year → open Annual Report attachment/PDF→ Human Resources section →                                            Positive=Green,
                                            attrition / retention disclosures.                                                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C. Corporate                                                                                                                                                              
  governance &                                                                                                                                                              
  promoter behavior                                                                                                                                                         

  C1                Promoter shareholding                                                                                                                                   
                    patterns                                                                                                                                                

  C1.1              Control levels          NSE →                                                                                Promoter Control Score (1--5).             Donut chart: Control
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             levels \| Colors:
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C1.2              Changes over time       NSE →                                                                                Promoter Trend Score (1--5).               Line chart: Changes
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             over time \| Colors:
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C1.3              Direction (buying /     NSE →                                                                                Buying/Selling Direction Score (1--5).     Donut chart: Direction
                    selling)                https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             (buying / selling) \|
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Colors: Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C2                Promoter pledging of                                                                                                                                    
                    shares                                                                                                                                                  

  C2.1              Presence of pledging    NSE →                                                                                Pledge Presence Score (1--5).              KPI Card: Presence of
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             pledging \| Colors:
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C2.2              Size of pledged shares  NSE →                                                                                Pledge Size Score (1--5).                  KPI Card: Size of
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             pledged shares \|
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Colors: Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C2.3              Trend in pledging       NSE →                                                                                Pledge Trend Score (1--5).                 Line chart: Trend in
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             pledging \| Colors:
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C2.4              Margin-call risk        NSE →                                                                                Margin-call Risk Score (1--5).             KPI Card: Margin-call
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             risk \| Colors:
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C3                Related-party                                                                                                                                           
                    transactions (RPTs)                                                                                                                                     

  C3.1              Frequency of RPTs       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  RPT Frequency Score (1--5).                KPI Card: Frequency of
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            RPTs \| Colors:
                                            select reporting year → open Annual Report attachment/PDF→ Notes to Accounts →                                                  Positive=Green,
                                            Related Party Disclosures (Ind AS 24).                                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C3.2              Counterparty identity   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Counterparty Risk Score (1--5).            KPI Card: Counterparty
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            identity \| Colors:
                                            select reporting year → open Annual Report attachment/PDF                                                                       Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C3.3                                                                                                                                                                      

  C3.4              Disclosure quality of   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  RPT Disclosure Score (1--5).               KPI Card: Disclosure
                    RPTs                    Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            quality of RPTs \|
                                            select reporting year → open Annual Report attachment/PDF                                                                       Colors: Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C4                                                                                                                                                                        

  C4.1              Off-balance-sheet       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Off-balance-sheet Risk Score (1--5): 5 =   Donut chart:
                    vehicles                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → no material opaque arrangements            Off-balance-sheet
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      identified; lower scores for material,     vehicles \| Colors:
                                            Consolidated Financial Statements → Subsidiaries / Associates / Joint Ventures →     complex or poorly explained exposures.     Positive=Green,
                                            Investments / Guarantees / Commitments / Contingent Liabilities; compare disclosures                                            Neutral=Blue,
                                            for entities or arrangements not fully reflected on the balance sheet.                                                          Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C4.2              Special purpose         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  SPV Complexity Score (1--5): based on      Donut chart: Special
                    vehicles (SPVs)         Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → number, purpose transparency, ownership    purpose vehicles (SPVs)
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts → List structure and materiality of SPVs.         \| Colors:
                                            of Subsidiaries / Associates / Joint Ventures → Related Party Disclosures → identify                                            Positive=Green,
                                            SPV / special-purpose entities and their ownership, purpose and transactions.                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C4.3              Subsidiaries abroad     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Offshore Structure Score (1--5): assess    Donut chart:
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → geographic concentration, business purpose Subsidiaries abroad \|
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts → List and disclosure quality of foreign          Colors: Positive=Green,
                                            of Subsidiaries / Associates / Joint Ventures → identify foreign subsidiaries,       subsidiaries.                              Neutral=Blue,
                                            country of incorporation, ownership and principal activity.                                                                     Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C4.4              Complexity /            NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Group Structure Complexity Score (1--5):   KPI Card: Complexity /
                    transparency of group   Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → entity count, layered ownership, dormant   transparency of group
                    structure               select reporting year → open Annual Report attachment/PDF → Corporate Information →  entities, offshore entities and clarity of structure \| Colors:
                                            Notes to Accounts → Group Structure / Subsidiaries / Associates / JVs.               stated business purpose.                   Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C5                Board composition &     https://www.nseindia.com/companies-listing/corporate-filings-insider-trading                                                    
                    independence                                                                                                                                            

  C5.1              Independent directors'  NSE → https://www.nseindia.com/companies-listing/corporate-filings-governance →      Independent Director Quality Score (1--5): KPI Card: Independent
                    quality                 Corporate Governance → Company \[Input: Company Name or Symbol\] → enter NSE symbol  qualifications, relevant experience,       directors' quality \|
                                            → select quarter → open Corporate Governance Detail → Composition of Board of        tenure, external independence and          Colors: Positive=Green,
                                            Directors; cross-check NSE →                                                         committee expertise.                       Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Negative=Red,
                                            Report → Corporate Governance Report → Board Profiles → qualifications, experience,                                             Insufficient/N/A=Grey
                                            other listed-company directorships and committee roles.                                                                         

  C5.2              Audit committee         NSE → https://www.nseindia.com/companies-listing/corporate-filings-governance →      Audit Committee Effectiveness Score        Donut chart: Audit
                    activity                Corporate Governance → Company \[Input: Company Name or Symbol\] → enter NSE symbol  (1--5): meeting frequency, attendance,     committee activity \|
                                            → select quarter → open Corporate Governance Detail → Audit Committee; cross-check   independence, financial expertise and      Colors: Positive=Green,
                                            Annual Report → Corporate Governance Report → Audit Committee → meetings,            disclosed oversight activity.              Neutral=Blue,
                                            attendance, composition and responsibilities.                                                                                   Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C5.3              Nomination &            NSE → https://www.nseindia.com/companies-listing/corporate-filings-governance →      NRC Effectiveness Score (1--5): meetings,  Donut chart: Nomination
                    remuneration committee  Corporate Governance → Company \[Input: Company Name or Symbol\] → enter NSE symbol  attendance, independence and disclosed     & remuneration
                    activity                → select quarter → open Corporate Governance Detail → Nomination and Remuneration    succession / remuneration oversight.       committee activity \|
                                            Committee; cross-check Annual Report → Corporate Governance Report → NRC.                                                       Colors: Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C5.4              Board attendance and    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Board Participation Score = meetings       KPI Card: Board
                    committee participation Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → attended ÷ meetings held, with committee   attendance and
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance     participation considered separately.       committee participation
                                            Report → Board Meetings / Committee Meetings / Attendance.                                                                      \| Colors:
                                                                                                                                                                            Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C6                Auditor relationships                                                                                                                                   

  C6.1              Auditor tenure          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Auditor Tenure = continuous years of       Donut chart: Auditor
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → current statutory auditor engagement;      tenure \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Independent Auditor's    classify Long / Moderate / Short using     Positive=Green,
                                            Report → Auditor name; cross-check AGM Notice / Corporate Governance Report →        disclosed appointment history.             Neutral=Blue,
                                            appointment and reappointment history.                                                                                          Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C6.2              Auditor switches        NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Auditor Switch Frequency = number of       KPI Card: Auditor
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      statutory auditor changes over 10 years;   switches \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → search Change in            assess timing and stated reason.           Positive=Green,
                                            Directors/KMP/SMP/Auditor/RTA and auditor-related subjects → From / To date → GO →                                              Neutral=Blue,
                                            open Details / Attachment; cross-check Annual Reports and AGM Notices.                                                          Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C6.3              Qualifications in audit NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Audit Qualification Score (1--5):          KPI Card:
                    reports                 Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → unmodified opinion = highest; material     Qualifications in audit
                                            select reporting year → open Annual Report attachment/PDF → Independent Auditor's    qualifications reduce score according to   reports \| Colors:
                                            Report → Opinion → Basis for Opinion → Qualified Opinion / Modified Opinion.         severity and recurrence.                   Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C6.4              Reservations / emphasis NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Audit Observation Score (1--5): frequency, KPI Card: Reservations
                    of matter               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → materiality and recurrence of emphasis /   / emphasis of matter \|
                                            select reporting year → open Annual Report attachment/PDF → Independent Auditor's    reservation matters.                       Colors: Positive=Green,
                                            Report → Emphasis of Matter / Material Uncertainty / Key Audit Matters → assess                                                 Neutral=Blue,
                                            recurring concerns.                                                                                                             Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C7                Capital allocation      https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    decisions                                                                                                                                               

  C7.1              Capital expenditure     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Capex Execution Score (1--5): compare      KPI Card: Capital
                    (capex)                 Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → stated capex plans with actual deployment  expenditure (capex) \|
                                            select reporting year → open Annual Report attachment/PDF → Cash Flow Statement →    and disclosed strategic rationale.         Colors: Positive=Green,
                                            Property, Plant & Equipment / Capital Work-in-Progress → Board's Report / MD&A →                                                Neutral=Blue,
                                            capex plans and rationale.                                                                                                      Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C7.2              Acquisitions            NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Acquisition Discipline Score (1--5):       KPI Card: Acquisitions
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      strategic fit, purchase rationale,         \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → search Acquisition /        integration evidence and related-party     Positive=Green,
                                            Agreement to acquire / Business Transfer → From / To date → GO → open Details /      involvement.                               Neutral=Blue,
                                            Attachment; cross-check Annual Report → Business Combination / Acquisition Note.                                                Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C7.3              Buybacks                NSE → https://www.nseindia.com/companies-listing/corporate-filings-actions →         Buyback Policy Score (1--5): rationale,    Donut chart: Buybacks
                                            Corporate Actions → Company \[Input: Company Name or Symbol\] → enter NSE symbol →   execution consistency, pricing discipline  \| Colors:
                                            Purpose \[Input: Search by Keyword\] → search Buyback → select date range → open     and shareholder impact.                    Positive=Green,
                                            relevant corporate action / attachment; cross-check Annual Report → Equity / Buyback                                            Neutral=Blue,
                                            disclosures.                                                                                                                    Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C7.4              Dividends               NSE → https://www.nseindia.com/companies-listing/corporate-filings-actions →         Dividend Consistency Score (1--5):         KPI Card: Dividends \|
                                            Corporate Actions → Company \[Input: Company Name or Symbol\] → enter NSE symbol →   continuity, payout rationale and           Colors: Positive=Green,
                                            Purpose \[Input: Search by Keyword\] → search Dividend → select date range → open    consistency with stated capital allocation Neutral=Blue,
                                            relevant corporate action; cross-check Annual Report → Board's Report → Dividend /   policy.                                    Negative=Red,
                                            Dividend Policy.                                                                                                                Insufficient/N/A=Grey

  C7.5              Capital allocation      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Capital Allocation Quality Score (1--5):   Donut chart: Capital
                    rationale               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → clarity of rationale, consistency with     allocation rationale \|
                                            select reporting year → open Annual Report attachment/PDF → Board's Report → MD&A →  strategy and evidence of disciplined       Colors: Positive=Green,
                                            Capital Allocation / Dividend / Expansion / Acquisition commentary; cross-check NSE  deployment.                                Neutral=Blue,
                                            Corporate Announcements for major actions.                                                                                      Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C8                Track record on                                                                                                                                         
                    minority shareholder                                                                                                                                    
                    treatment and                                                                                                                                           
                    disclosure habits                                                                                                                                       

  C8.1              Disclosure quality      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Disclosure Quality Score (1--5):           KPI Card: Disclosure
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → completeness, specificity, timeliness and  quality \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance     consistency of material disclosures.       Positive=Green,
                                            Report → Board / Committee disclosures → Notes to Accounts → Related Party                                                      Neutral=Blue,
                                            Transactions / Contingent Liabilities / Commitments; cross-check NSE Corporate                                                  Negative=Red,
                                            Announcements for timely material disclosures.                                                                                  Insufficient/N/A=Grey

  C8.2              Minority shareholder    NSE →                                                                                Minority Treatment Score (1--5): assess    KPI Card: Minority
                    voting and treatment    https://www.nseindia.com/companies-listing/corporate-filings-shareholders-meetings → contested resolutions, voting outcomes and shareholder voting and
                                            Shareholders' Meetings → Company \[Input: Company Name or Symbol\] → enter NSE       treatment of non-promoter shareholders.    treatment \| Colors:
                                            symbol → select meeting/date → open Notice / Voting Results / Scrutinizer Report →                                              Positive=Green,
                                            review resolutions, votes in favour/against and minority-sensitive matters.                                                     Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  C8.3                                                                                                                                                                      

  C8.4              Disclosure consistency  NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Disclosure Timeliness Score (1--5):        Line chart: Disclosure
                    and timeliness          Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      promptness, consistency and absence of     consistency and
                                            symbol → From / To date → review material event announcements and their timing;      unexplained disclosure gaps.               timeliness \| Colors:
                                            cross-check Annual Reports → Board's Report / Corporate Governance Report → compare                                             Positive=Green,
                                            event disclosure with subsequent detailed disclosure.                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D. Promoter /                                                                                                                                                             
  insider activity                                                                                                                                                          
  & market                                                                                                                                                                  
  signalling                                                                                                                                                                

  D1                                                                                                                                                                        

  D1.1              Frequency of insider    NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Frequency = number of insider sale events  Line chart: Frequency
                    selling                 Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      per 8 quarters; score 5=none/rare, 4=low,  of insider selling \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      3=moderate, 2=high, 1=frequent/repeated.   Colors: Positive=Green,
                                            Regulation 7(2) disclosures → compile all promoter/director/KMP sale disclosures                                                Neutral=Blue,
                                            over the last 8 quarters.                                                                                                       Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D1.2              Timing of insider       NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Timing Risk Score (1--5): assess whether   Line chart: Timing of
                    selling                 Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      sales cluster around sensitive periods or  insider selling \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      follow major price-moving events; do not   Colors: Positive=Green,
                                            Regulation 7(2) disclosures → compare sale dates with results, major announcements   infer intent without evidence.             Neutral=Blue,
                                            and corporate actions from NSE →                                                                                                Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Insufficient/N/A=Grey
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            relevant period.                                                                                                                

  D1.3              Size of insider selling NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Insider Sale Size % = Shares Sold ÷        KPI Card: Size of
                                            Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      Insider Holding Before Sale × 100;         insider selling \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      classify Low / Moderate / High relative to Colors: Positive=Green,
                                            Regulation 7(2) disclosures → extract shares sold and transaction value where        holding.                                   Neutral=Blue,
                                            disclosed.                                                                                                                      Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D1.4              Rationale for insider   NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Rationale Score (1--5): documented         KPI Card: Rationale for
                    selling                 Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      liquidity/tax/diversification rationale    insider selling \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      scores higher than unexplained or repeated Colors: Positive=Green,
                                            Regulation 7(2) disclosure attachment → transaction remarks/reason; cross-check NSE  sales.                                     Neutral=Blue,
                                            → https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                  Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            company statements if available.                                                                                                

  D2                Insider buying: sign of                                                                                                                                 
                    conviction                                                                                                                                              

  D2.1              Frequency of insider    NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Buying Frequency Score (1--5) based on     KPI Card: Frequency of
                    buying                  Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      number and consistency of insider          insider buying \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      purchases.                                 Colors: Positive=Green,
                                            Regulation 7(2) disclosures → filter acquisition/purchase transactions → compile 8                                              Neutral=Blue,
                                            quarters.                                                                                                                       Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D2.2              Size of insider buying  NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Buying Size % = Shares Acquired ÷ Insider  Donut chart: Size of
                                            Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      Holding Before Purchase × 100 where data   insider buying \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      permits.                                   Colors: Positive=Green,
                                            Regulation 7(2) disclosures → extract shares acquired and value.                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D2.3              Repeat buying /         NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Conviction Score (1--5): repeated          KPI Card: Repeat buying
                    conviction pattern      Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      open-market buying by relevant insiders    / conviction pattern \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      scores higher than isolated/nominal        Colors: Positive=Green,
                                            Regulation 7(2) disclosures → identify repeated purchases across quarters.           purchases.                                 Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D3                Secondary transactions:                                                                                                                                 
                    placements,                                                                                                                                             
                    preferential allotments                                                                                                                                 
                    --- dilution concerns                                                                                                                                   

  D3.1              Placements /            NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Transaction Type Score: classify as QIP /  KPI Card: Placements /
                    preferential allotments Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      preferential / placement / other and       preferential allotments
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      identify recipient class.                  \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Positive=Green,
                                            search subjects such as Preferential Issue, QIP, Placement, Allotment → open offer                                              Neutral=Blue,
                                            document/board/shareholder outcome; cross-check NSE →                                                                           Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-actions → Corporate                                                Insufficient/N/A=Grey
                                            Actions → Company \[Input: Company Name or Symbol\] → enter NSE symbol → Purpose                                                
                                            \[Input: Search by Keyword\] → enter relevant action → Meeting \[Select if                                                      
                                            applicable\] → select date range → open matching corporate action → Purpose.                                                    

  D3.2              Dilution to existing    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Dilution % = New Shares Issued ÷           Donut chart: Dilution
                    shareholders            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Post-Issue Shares × 100.                   to existing
                                            select reporting year → open Annual Report attachment/PDF → Notes to Equity / Share                                             shareholders \| Colors:
                                            Capital → compare pre- and post-issue shares; NSE →                                                                             Positive=Green,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Neutral=Blue,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Negative=Red,
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Insufficient/N/A=Grey
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            issue terms and allotment.                                                                                                      

  D3.3              Pricing / discount and  NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Pricing & Rationale Score (1--5) based on  KPI Card: Pricing /
                    rationale               Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      pricing transparency, purpose and investor discount and rationale
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      class.                                     \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Positive=Green,
                                            issue announcement → price, floor/premium, purpose and allottee details →                                                       Neutral=Blue,
                                            shareholder approval attachment.                                                                                                Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D4                Lock-in expiries or                                                                                                                                     
                    block share releases:                                                                                                                                   
                    large scheduled                                                                                                                                         
                    sellable holdings                                                                                                                                       

  D4.1              Lock-in expiry date     NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Lock-in Status = Upcoming / Expired / Not  Donut chart: Lock-in
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      Applicable; record exact date when         expiry date \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      disclosed.                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            search lock-in, release, listing/allotment, preferential issue or IPO-related                                                   Negative=Red,
                                            announcements → open filing.                                                                                                    Insufficient/N/A=Grey

  D4.2              Potential sellable      NSE →                                                                                Potential Release % = Shares Becoming      Donut chart: Potential
                    block size              https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →  Saleable ÷ Total Shares Outstanding × 100. sellable block size \|
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            Colors: Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL →                                                    Neutral=Blue,
                                            Promoter/Public Shareholder tables → compare locked/encumbered/available holdings                                               Negative=Red,
                                            where disclosed; NSE →                                                                                                          Insufficient/N/A=Grey
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            release details.                                                                                                                

  D5                Promoter loans to/from  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    company or group                                                                                                                                        
                    entities; interest                                                                                                                                      
                    rates and repayment                                                                                                                                     
                    terms                                                                                                                                                   

  D5.1              Promoter/company loan   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Direction classification: Company →        Donut chart:
                    direction               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Promoter/Group, Promoter/Group → Company,  Promoter/company loan
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      Both, or None.                             direction \| Colors:
                                            Loans / Advances / Other Receivables → Related Party Disclosures (Ind AS 24).                                                   Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D5.2              Interest rate and terms NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Terms Score (1--5): arm's-length rate,     KPI Card: Interest rate
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → documented maturity and repayment terms    and terms \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Related Party            score higher.                              Positive=Green,
                                            Disclosures → loans/advances → interest rate, maturity and repayment terms.                                                     Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D5.3              Outstanding balance /   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Exposure % = Promoter/Group Loan Balance ÷ Donut chart:
                    concentration           Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Net Worth or Total Assets, using the most  Outstanding balance /
                                            select reporting year → open Annual Report attachment/PDF → Balance Sheet / Notes →  relevant disclosed denominator.            concentration \|
                                            related-party receivables, loans and advances.                                                                                  Colors: Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  D6                                                                                                                                                                        

  D6.1              Pledge release /        NSE →                                                                                Pledge Unwinding = Previous Pledged % −    Line chart: Pledge
                    unwinding               https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →  Current Pledged %; positive decline is     release / unwinding \|
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol release, but do not assume reason.         Colors: Positive=Green,
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL →                                                    Neutral=Blue,
                                            Promoter & Promoter Group → Pledged / Encumbered Shares → compare quarterly pledge                                              Negative=Red,
                                            percentage.                                                                                                                     Insufficient/N/A=Grey

  D6.2              Forced-sale /           NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Risk classification: No evidence /         Donut chart:
                    invocation signals      Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      Possible / Confirmed based only on         Forced-sale /
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      disclosed evidence.                        invocation signals \|
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Colors: Positive=Green,
                                            search pledge invocation, sale, lender invocation, default or promoter sale                                                     Neutral=Blue,
                                            disclosures; cross-check NSE →                                                                                                  Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern →                                             Insufficient/N/A=Grey
                                            Shareholding Patterns → Company \[Input: Company Name or Symbol\] → enter NSE symbol                                            
                                            → select As on Date / date range → open Shareholding Pattern Detail / XBRL and NSE →                                            
                                            https://www.nseindia.com/companies-listing/corporate-filings-insider-trading →                                                  
                                            Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →                                                 
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL.                                                  

  E. Business                                                                                                                                                               
  integrity &                                                                                                                                                               
  "leakage" signals                                                                                                                                                         

  E1                Unexpected              https://www.nseindia.com/companies-listing/corporate-filings-financial-results                                                  
                    related-party payments                                                                                                                                  
                    to opaque vendors or                                                                                                                                    
                    consultants                                                                                                                                             

  E1.1              Related-party payment   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Frequency Score (1--5) based on recurring  KPI Card: Related-party
                    frequency               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → nature and number of material              payment frequency \|
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      counterparties.                            Colors: Positive=Green,
                                            Related Party Disclosures → transactions with promoter/group entities.                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E1.2                                                                                                                                                                      

  E1.3              Payment rationale /     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Rationale Score (1--5): documented         KPI Card: Payment
                    arm's-length basis      Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → commercial purpose and arm's-length basis  rationale /
                                            select reporting year → open Annual Report attachment/PDF → Related Party            score higher.                              arm's-length basis \|
                                            Disclosures → nature, terms, pricing basis and Audit Committee approval.                                                        Colors: Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E2                Customer concentration: https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    top customers                                                                                                                                           
                    percentage & dependency                                                                                                                                 

  E2.1              Top customer revenue    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Top Customer Concentration % = Revenue     KPI Card: Top customer
                    concentration           Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → from Largest Customer(s) ÷ Total Revenue × revenue concentration
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      100 where disclosed.                       \| Colors:
                                            Revenue from Customers / Segment Information / Major Customer disclosures → extract                                             Positive=Green,
                                            concentration where disclosed.                                                                                                  Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E2.2              Customer dependency     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Dependency Score (1--5): diversified       KPI Card: Customer
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → recurring customer base scores higher than dependency \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → customer          reliance on one/few customers.             Positive=Green,
                                            concentration, contract dependence, major customer commentary.                                                                  Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E3                Supplier concentration                                                                                                                                  
                    and terms:                                                                                                                                              
                    single-sourced inputs                                                                                                                                   
                    or tied suppliers                                                                                                                                       

  E3.1              Supplier concentration  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Supplier Concentration Score (1--5) based  KPI Card: Supplier
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → on disclosed single-source dependence.     concentration \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Risk Factors /                                               Colors: Positive=Green,
                                            Supply Chain → major suppliers, single-source dependencies and concentration                                                    Neutral=Blue,
                                            disclosures.                                                                                                                    Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E3.2                                                                                                                                                                      

  E3.3              Supplier terms /        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Supplier Terms Score (1--5): transparent   KPI Card: Supplier
                    dependence              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → commercial terms and diversified           terms / dependence \|
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      procurement score higher.                  Colors: Positive=Green,
                                            trade payables / commitments; MD&A → procurement terms and supply contracts.                                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E4                High or growing         https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    receivables with                                                                                                                                        
                    limited disclosure ---                                                                                                                                  
                    revenue recognition                                                                                                                                     
                    risk                                                                                                                                                    

  E4.1              Receivables growth      NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Receivables Growth = Current Trade         Line chart: Receivables
                                            → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → Receivables ÷ Prior-period Trade           growth \| Colors:
                                            Period Ended → select period → Search By → select applicable result type → open      Receivables − 1.                           Positive=Green,
                                            Financial Results Detail → open XBRL / attachment → Integrated Financials → Balance                                             Neutral=Blue,
                                            Sheet → Trade Receivables; compare 8 quarters.                                                                                  Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E4.2              Receivables aging /     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Overdue Concentration = Overdue            KPI Card: Receivables
                    overdue quality         Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Receivables ÷ Total Trade Receivables ×    aging / overdue quality
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      100.                                       \| Colors:
                                            Trade Receivables Ageing / Expected Credit Loss.                                                                                Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E4.3              Revenue-recognition     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Revenue Recognition Risk Score (1--5)      KPI Card:
                    disclosure risk         Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → based on complexity and disclosure         Revenue-recognition
                                            select reporting year → open Annual Report attachment/PDF → Significant Accounting   clarity.                                   disclosure risk \|
                                            Policies → Revenue Recognition (Ind AS 115) → contract assets / unbilled revenue /                                              Colors: Positive=Green,
                                            variable consideration.                                                                                                         Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E5                Inventory build vs      https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    demand: potential                                                                                                                                       
                    channel stuffing or                                                                                                                                     
                    obsolete inventory                                                                                                                                      

  E5.1              Inventory trend         NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Inventory Growth = Current Inventory ÷     Line chart: Inventory
                                            → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → Prior Inventory − 1.                       trend \| Colors:
                                            Period Ended → select period → Search By → select applicable result type → open                                                 Positive=Green,
                                            Financial Results Detail → open XBRL / attachment → Integrated Financials → Balance                                             Neutral=Blue,
                                            Sheet → Inventories → compare 8 quarters.                                                                                       Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E5.2              Inventory vs demand     NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Inventory-Demand Divergence = Inventory    Donut chart: Inventory
                                            → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → Growth − Revenue Growth.                   vs demand \| Colors:
                                            Period Ended → select period → Search By → select applicable result type → open                                                 Positive=Green,
                                            Financial Results Detail → open XBRL / attachment → Financial Results → Revenue /                                               Neutral=Blue,
                                            Sales; compare inventory growth with revenue growth.                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E5.3              Obsolete / slow-moving  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Obsolescence Risk Score (1--5) based on    KPI Card: Obsolete /
                    inventory               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → write-downs, ageing and management         slow-moving inventory
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      commentary.                                \| Colors:
                                            Inventories → write-down / provision / NRV disclosures.                                                                         Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E6                Off-market                                                                                                                                              
                    transactions, non-arm's                                                                                                                                 
                    length contracts,                                                                                                                                       
                    side-letters or                                                                                                                                         
                    sweetheart deals                                                                                                                                        

  E6.1              Off-market transactions NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Transaction Risk Score (1--5) based on     KPI Card: Off-market
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      disclosure, counterparty and commercial    transactions \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      rationale.                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            search off-market, transfer, sale, acquisition, related-party or preferential                                                   Negative=Red,
                                            transaction disclosures; NSE →                                                                                                  Insufficient/N/A=Grey
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Notes to Accounts.                                                         

  E6.2              Non-arm's-length        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Arm's-length Evidence Score (1--5).        KPI Card:
                    contracts               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            Non-arm's-length
                                            select reporting year → open Annual Report attachment/PDF → Related Party                                                       contracts \| Colors:
                                            Disclosures → contractual terms, pricing basis and approval.                                                                    Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E6.3                                                                                                                                                                      

  E7                Unusual accounting                                                                                                                                      
                    policies or frequent                                                                                                                                    
                    changes in accounting                                                                                                                                   
                    estimates                                                                                                                                               

  E7.1              Accounting policy       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Policy Change Count = material policy      KPI Card: Accounting
                    changes                 Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → changes over review period.                policy changes \|
                                            select reporting year → open Annual Report attachment/PDF → Significant Accounting                                              Colors: Positive=Green,
                                            Policies → Changes in Accounting Policies / estimates → compare last 5 years.                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E7.2              Changes in accounting   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Estimate Change Score (1--5) based on      KPI Card: Changes in
                    estimates               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → frequency, magnitude and explanation.      accounting estimates \|
                                            select reporting year → open Annual Report attachment/PDF → Significant Accounting                                              Colors: Positive=Green,
                                            Judgements / Estimates → compare last 5 years.                                                                                  Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E7.3              One-off adjustments /   NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Recurring One-off Flag = count of repeated KPI Card: One-off
                    special items           → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → exceptional/special items over review      adjustments / special
                                            Period Ended → select period → Search By → select applicable result type → open      period.                                    items \| Colors:
                                            Financial Results Detail → open XBRL / attachment → Statement of Profit & Loss →                                                Positive=Green,
                                            exceptional items / other income / other expenses; compare 5 years.                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  E7.4              Earnings smoothing      NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Smoothing Risk Score (1--5) based on       KPI Card: Earnings
                    signals                 → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → repeated adjustments that materially       smoothing signals \|
                                            Period Ended → select period → Search By → select applicable result type → open      change reported earnings.                  Colors: Positive=Green,
                                            Financial Results Detail → open XBRL / attachment → Financial Results → compare                                                 Neutral=Blue,
                                            operating profit, exceptional items and other income across periods; NSE →                                                      Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → accounting policy notes.                                                   

  F. Market &                                                                                                                                                               
  competition                                                                                                                                                               

  F1                Competitive landscape:                                                                                                                                  
                    number and strength of                                                                                                                                  
                    competitors, market                                                                                                                                     
                    shares                                                                                                                                                  

  F1.1              Number of material      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Competitor Count = number of material      KPI Card: Number of
                    competitors             Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → named competitors identified from filings. material competitors \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Industry                                                     Colors: Positive=Green,
                                            Structure / Competition → identify named competitors; NSE →                                                                     Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            investor presentations for market context.                                                                                      

  F1.2              Relative market         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Market Position Score (1--5) from          KPI Card: Relative
                    position                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → disclosed market share/rank; do not        market position \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Industry Overview estimate when not disclosed.               Colors: Positive=Green,
                                            / Market Share → extract disclosed market share or ranking.                                                                     Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  F1.3              Competitor strength     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Competitive Strength Score (1--5) based on KPI Card: Competitor
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → disclosed peer advantages.                 strength \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → competitive                                                  Positive=Green,
                                            advantages / peer comparison → assess scale, distribution, technology and cost                                                  Neutral=Blue,
                                            position.                                                                                                                       Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  F2                Threat from new         https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    entrants or substitute                                                                                                                                  
                    technologies                                                                                                                                            

  F2.1              Entry barriers          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Entry Barrier Score (1--5).                Donut chart: Entry
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            barriers \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Industry                                                     Positive=Green,
                                            Structure / Risk Factors → licences, capital intensity, distribution, technology or                                             Neutral=Blue,
                                            scale barriers.                                                                                                                 Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  F2.2                                                                                                                                                                      

  F3                Pricing dynamics in                                                                                                                                     
                    sector: margin pressure                                                                                                                                 
                    or price wars                                                                                                                                           

  F3.1                                                                                                                                                                      

  F3.2              Price-war evidence      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Margin Pressure = Current Margin −         Line chart: Price-war
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Prior-period Margin; interpret alongside   evidence \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → margins /         management commentary.                     Positive=Green,
                                            competition; NSE →                                                                                                              Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-financial-results →                                                Negative=Red,
                                            Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol →                                              Insufficient/N/A=Grey
                                            Period Ended → select period → Search By → select applicable result type → open                                                 
                                            Financial Results Detail → open XBRL / attachment → gross/operating margin trend.                                               

  F4                Regulatory or trade                                                                                                                                     
                    barriers protecting or                                                                                                                                  
                    exposing the company                                                                                                                                    

  F4.1              Regulatory barriers     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Barrier Score (1--5): strength and         KPI Card: Regulatory
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → durability of regulatory barriers.         barriers \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Regulation /                                                 Positive=Green,
                                            Licensing / Industry Structure → identify licences, quotas, approvals or standards.                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  F4.2              Trade barriers          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Trade Barrier Exposure Score (1--5).       KPI Card: Trade
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            barriers \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → imports/exports,                                             Positive=Green,
                                            tariffs and duties; DGFT → https://www.dgft.gov.in/ → Regulatory Updates / Foreign                                              Neutral=Blue,
                                            Trade Policy / ITC(HS) → search relevant product or policy → Foreign Trade Policy /                                             Negative=Red,
                                            ITC(HS) → relevant product policy.                                                                                              Insufficient/N/A=Grey

  F5                Foreign competitors:                                                                                                                                    
                    ability of global                                                                                                                                       
                    players to enter India                                                                                                                                  
                    or export competition                                                                                                                                   

  F5.1              Foreign competitor      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Foreign Competition Score (1--5).          KPI Card: Foreign
                    presence                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            competitor presence \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Competition /                                                Colors: Positive=Green,
                                            Industry Overview → named international competitors and imports.                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  F5.2              Import competition      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Import Competition Score (1--5).           KPI Card: Import
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            competition \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → imports / raw                                                Positive=Green,
                                            materials / competition; DGFT → https://www.dgft.gov.in/ → Regulatory Updates /                                                 Neutral=Blue,
                                            Foreign Trade Policy / ITC(HS) → search relevant product or policy → ITC(HS) import                                             Negative=Red,
                                            policy.                                                                                                                         Insufficient/N/A=Grey

  F6                Customer switching                                                                                                                                      
                    costs and network                                                                                                                                       
                    effects that lock                                                                                                                                       
                    customers in                                                                                                                                            

  F6.1              Switching costs         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Switching Cost Score (1--5).               Donut chart: Switching
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            costs \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Business Model /                                             Positive=Green,
                                            Customer Relationships / Contracts → identify implementation, integration or                                                    Neutral=Blue,
                                            contractual switching costs.                                                                                                    Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  F6.2              Network effects         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Network Effect Score (1--5).               Donut chart: Network
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            effects \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Business Model /                                             Positive=Green,
                                            Platform / Ecosystem → identify direct or indirect network effects.                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  G. Customers,                                                                                                                                                             
  channels &                                                                                                                                                                
  distribution                                                                                                                                                              

  G1                Channel mix: direct,                                                                                                                                    
                    retail, distributors,                                                                                                                                   
                    e-commerce; control                                                                                                                                     
                    over channel                                                                                                                                            

  G1.1              Channel mix             NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Channel Mix % = Revenue by Channel ÷ Total Donut chart: Channel
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Revenue where disclosed.                   mix \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Business Model /                                             Positive=Green,
                                            Distribution → identify direct, distributor, retail, e-commerce and other channels.                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  G1.2              Channel control         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Channel Control Score (1--5).              KPI Card: Channel
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            control \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Distribution                                                 Positive=Green,
                                            Network / Business Model → assess owned vs third-party channel dependence.                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  G2                Channel conflicts:      https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    overlap between company                                                                                                                                 
                    distributors and other                                                                                                                                  
                    group companies                                                                                                                                         

  G2.1              Group-channel overlap   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Channel Conflict Score (1--5) based on     KPI Card: Group-channel
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → disclosed overlap and governance controls. overlap \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Related Party                                                       Positive=Green,
                                            Disclosures → group entities; MD&A → distribution network; NSE →                                                                Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            material group arrangements.                                                                                                    

  G2.2                                                                                                                                                                      

  G3                Quality of customer     https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    relationships:                                                                                                                                          
                    contracts, long-term                                                                                                                                    
                    agreements, churn                                                                                                                                       
                    metrics                                                                                                                                                 

  G3.1              Contract duration /     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Contract Quality Score (1--5).             KPI Card: Contract
                    renewal                 Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            duration / renewal \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → customer                                                     Colors: Positive=Green,
                                            contracts / order book / renewal commentary.                                                                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  G3.2              Customer churn /        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Retention Score (1--5); mark NOT_DISCLOSED KPI Card: Customer
                    retention               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → if no metric exists.                       churn / retention \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A / ESG / Business                                               Colors: Positive=Green,
                                            Review → churn, retention or repeat-customer disclosures where applicable.                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  G4                Distribution reach vs   https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    peers --- advantaged or                                                                                                                                 
                    constrained                                                                                                                                             

  G4.1              Distribution reach      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Reach Score (1--5) using disclosed network KPI Card: Distribution
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → scale and coverage.                        reach \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Distribution                                                 Positive=Green,
                                            Network → stores, dealers, distributors, service points or geographic reach.                                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  G4.2              Peer distribution       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Relative Distribution Score (1--5).        KPI Card: Peer
                    advantage               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            distribution advantage
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Industry /                                                   \| Colors:
                                            Competition → compare disclosed network reach with peers.                                                                       Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  H. Product, IP &                                                                                                                                                          
  technology                                                                                                                                                                

  H1                Ownership of IP /       https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    patents / trademarks;                                                                                                                                   
                    expiry profile                                                                                                                                          

  H1.1                                                                                                                                                                      

  H1.2              Patent / trademark      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Expiry Risk Score (1--5) based on          KPI Card: Patent /
                    expiry                  Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → concentration of material rights           trademark expiry \|
                                            select reporting year → open Annual Report attachment/PDF → Intangible Assets /      approaching expiry.                        Colors: Positive=Green,
                                            Intellectual Property → expiry/renewal disclosures where available.                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  H2                R&D pipeline quality    https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    and time to market for                                                                                                                                  
                    new products                                                                                                                                            

  H2.1              R&D pipeline depth      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Pipeline Strength Score (1--5).            KPI Card: R&D pipeline
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            depth \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → R&D / Innovation                                             Positive=Green,
                                            → projects, products in development and launch pipeline.                                                                        Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  H2.2                                                                                                                                                                      

  H3                Technology dependence:  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    legacy systems vs                                                                                                                                       
                    modern stack;                                                                                                                                           
                    cybersecurity posture                                                                                                                                   

  H3.1              Legacy technology       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Legacy Dependence Score (1--5), with       Donut chart: Legacy
                    dependence              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → higher score meaning lower legacy risk.    technology dependence
                                            select reporting year → open Annual Report attachment/PDF → MD&A → IT / Digital                                                 \| Colors:
                                            Transformation / Technology Risk → legacy-system dependencies.                                                                  Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  H3.2              Cybersecurity posture   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Cybersecurity Maturity Score (1--5) based  Donut chart:
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → on disclosed governance and controls.      Cybersecurity posture
                                            select reporting year → open Annual Report attachment/PDF → Corporate Governance /                                              \| Colors:
                                            Risk Management / Business Responsibility & Sustainability Report → cybersecurity,                                              Positive=Green,
                                            incidents, controls and training.                                                                                               Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  H4                Licensing arrangements  https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    and dependency on                                                                                                                                       
                    third-party tech                                                                                                                                        

  H4.1              Third-party technology  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Third-party Dependency Score (1--5).       KPI Card: Third-party
                    dependence              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            technology dependence
                                            select reporting year → open Annual Report attachment/PDF → Notes / Intangibles /                                               \| Colors:
                                            Technology Risk → material licences, cloud/platform dependencies and key vendors.                                               Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  H4.2              License continuity risk NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  License Risk Score (1--5).                 KPI Card: License
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            continuity risk \|
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts /                                                 Colors: Positive=Green,
                                            Contracts / Risk Factors → renewal terms, termination and material licence                                                      Neutral=Blue,
                                            dependence.                                                                                                                     Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I. Supply chain &                                                                                                                                                         
  operations                                                                                                                                                                

  I1                Supply chain            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    resilience:                                                                                                                                             
                    single-source                                                                                                                                           
                    suppliers, geographic                                                                                                                                   
                    concentration (China                                                                                                                                    
                    risk), inventory                                                                                                                                        
                    buffers                                                                                                                                                 

  I1.1              Single-source suppliers NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Single-source Risk Score (1--5).           KPI Card: Single-source
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            suppliers \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Supply Chain /                                               Positive=Green,
                                            Risk Factors → identify sole-source or critical supplier dependencies.                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I1.2              Geographic              NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Geographic Concentration Score (1--5).     KPI Card: Geographic
                    concentration / China   Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            concentration / China
                    exposure                select reporting year → open Annual Report attachment/PDF → MD&A → Procurement /                                                exposure \| Colors:
                                            Imports / Risk Factors → country concentration; DGFT → https://www.dgft.gov.in/ →                                               Positive=Green,
                                            Regulatory Updates / Foreign Trade Policy / ITC(HS) → search relevant product or                                                Neutral=Blue,
                                            policy → import policy for relevant goods.                                                                                      Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I1.3              Inventory buffers       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Inventory Buffer Score (1--5).             KPI Card: Inventory
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            buffers \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A / Inventory Notes →                                            Positive=Green,
                                            inventory policy, safety stock and buffer commentary.                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I2                Manufacturing capacity  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    vs demand:                                                                                                                                              
                    over-capacity or                                                                                                                                        
                    capital constraints to                                                                                                                                  
                    scale                                                                                                                                                   

  I2.1                                                                                                                                                                      

  I2.2              Capacity vs demand      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Capacity-Demand Balance Score (1--5).      Donut chart: Capacity
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            vs demand \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Demand Outlook /                                             Positive=Green,
                                            Order Book / Capacity Expansion.                                                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I2.3              Capital constraints to  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Scale Constraint Score (1--5).             KPI Card: Capital
                    scale                   Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            constraints to scale \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Capex Plans /                                                Colors: Positive=Green,
                                            Funding / Capacity Expansion; NSE →                                                                                             Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-financial-results →                                                Negative=Red,
                                            Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol →                                              Insufficient/N/A=Grey
                                            Period Ended → select period → Search By → select applicable result type → open                                                 
                                            Financial Results Detail → open XBRL / attachment → cash flow and financing.                                                    

  I3                Contractual terms with  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    suppliers and                                                                                                                                           
                    customers: price                                                                                                                                        
                    protections, currency                                                                                                                                   
                    clauses                                                                                                                                                 

  I3.1              Price protection        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Price Protection Score (1--5).             KPI Card: Price
                    clauses                 Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            protection clauses \|
                                            select reporting year → open Annual Report attachment/PDF → Notes / Risk Management                                             Colors: Positive=Green,
                                            / Contracts → price escalation, pass-through or fixed-price terms.                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I3.2              Currency clauses        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Currency Protection Score (1--5).          Donut chart: Currency
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            clauses \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Risk Management /                                                   Positive=Green,
                                            Foreign Currency Risk → customer/supplier contracts and hedging policy.                                                         Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I4                Operational KPIs: lead  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    times, throughput,                                                                                                                                      
                    quality defects,                                                                                                                                        
                    warranty claims                                                                                                                                         

  I4.1              Lead time / throughput  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Operational Efficiency Score (1--5).       KPI Card: Lead time /
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            throughput \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Operational KPIs                                             Positive=Green,
                                            / Business Review → lead time, production or throughput metrics.                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  I4.2              Quality defects /       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Quality Risk Score (1--5) based on         Line chart: Quality
                    warranty claims         Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → defects, complaints and warranty trend.    defects / warranty
                                            select reporting year → open Annual Report attachment/PDF → Notes / Provisions /                                                claims \| Colors:
                                            Warranty Claims → warranty provision and claims; MD&A → quality metrics.                                                        Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J. Regulatory,                                                                                                                                                            
  legal &                                                                                                                                                                   
  compliance                                                                                                                                                                

  J1                Industry regulation:                                                                                                                                    
                    licensing, approvals,                                                                                                                                   
                    periodic renewals,                                                                                                                                      
                    compliance load                                                                                                                                         

  J1.1                                                                                                                                                                      

  J1.2              Renewal burden          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Renewal Burden Score (1--5).               KPI Card: Renewal
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            burden \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Risk Factors /                                                      Positive=Green,
                                            Regulatory Compliance → renewal periods and compliance requirements.                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J2                                                                                                                                                                        

  J2.1              Litigation count and    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Litigation Materiality Score (1--5) based  KPI Card: Litigation
                    materiality             Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → on disclosed number, nature and financial  count and materiality
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      significance.                              \| Colors:
                                            Contingent Liabilities / Legal Proceedings → list material cases.                                                               Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J2.2              Probability /           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Outcome Risk Score (1--5); do not assign   Donut chart:
                    management assessment   Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → probability if the company does not        Probability /
                                            select reporting year → open Annual Report attachment/PDF → Contingent Liabilities → disclose one.                              management assessment
                                            management assessment of outcome where disclosed.                                                                               \| Colors:
                                                                                                                                                                            Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J3                Antitrust/competition   https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    probes or                                                                                                                                               
                    investigations                                                                                                                                          

  J3.1              Competition             NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Investigation Status = None / Inquiry /    Donut chart:
                    investigations          Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      Investigation / Order / Closed.            Competition
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 investigations \|
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Colors: Positive=Green,
                                            search Competition Commission / investigation / antitrust / notice → open filing;                                               Neutral=Blue,
                                            CCI → https://www.cci.gov.in/antitrust/orders → Antitrust → Orders → Case Type /                                                Negative=Red,
                                            Order Date / Parties / Sectionwise / Free Text → enter company / transaction → open                                             Insufficient/N/A=Grey
                                            matching order.                                                                                                                 

  J3.2              Potential financial /   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Impact Score (1--5) based on disclosed     KPI Card: Potential
                    operational impact      Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → penalty, remedy or operational             financial / operational
                                            select reporting year → open Annual Report attachment/PDF → Contingent Liabilities / restriction.                               impact \| Colors:
                                            Risk Factors → quantify or describe exposure; CCI →                                                                             Positive=Green,
                                            https://www.cci.gov.in/antitrust/orders → Antitrust → Orders → Case Type / Order                                                Neutral=Blue,
                                            Date / Parties / Sectionwise / Free Text → enter company / transaction → open                                                   Negative=Red,
                                            matching order / search transaction or company → review approval, modification or                                               Insufficient/N/A=Grey
                                            order → relevant order.                                                                                                         

  J4                Tax disputes, historic  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    tax exposures or                                                                                                                                        
                    ongoing audits                                                                                                                                          

  J4.1              Tax disputes            NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Tax Dispute Exposure Score (1--5).         Donut chart: Tax
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            disputes \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes → Income Tax / GST                                            Positive=Green,
                                            / Other Tax Contingencies → outstanding demands and appeals.                                                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J4.2              Historic tax exposures  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Historic Tax Risk Score (1--5).            KPI Card: Historic tax
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            exposures \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Contingent Liabilities /                                            Positive=Green,
                                            tax proceedings → compare 3--5 years.                                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J4.3              Ongoing tax audits /    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Audit Status = None / Ongoing / Resolved;  KPI Card: Ongoing tax
                    assessments             Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → score only where evidence exists.          audits / assessments \|
                                            select reporting year → open Annual Report attachment/PDF → Tax Notes / Contingent                                              Colors: Positive=Green,
                                            Liabilities → ongoing assessments/audits.                                                                                       Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J5                Exposure to                                                                                                                                             
                    policy/regulatory                                                                                                                                       
                    shifts: subsidies                                                                                                                                       
                    removal, environmental                                                                                                                                  
                    norms                                                                                                                                                   

  J5.1              Subsidy dependence      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Subsidy Dependence % = Subsidy/Grant       Donut chart: Subsidy
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Income ÷ Relevant Revenue or Profit where  dependence \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Government        meaningful.                                Positive=Green,
                                            incentives / subsidies → identify material support and conditions.                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  J5.2              Environmental           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Regulatory Shift Risk Score (1--5).        KPI Card: Environmental
                    regulation exposure     Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            regulation exposure \|
                                            select reporting year → open Annual Report attachment/PDF → Risk Factors / ESG →                                                Colors: Positive=Green,
                                            regulatory changes; PARIVESH → https://parivesh.nic.in/ → Track Your Proposal /                                                 Neutral=Blue,
                                            Environmental Clearance / Forest Clearance / Wildlife Clearance / CRZ Clearance →                                               Negative=Red,
                                            search project/company → environmental/forest/wildlife/CRZ clearances where                                                     Insufficient/N/A=Grey
                                            relevant.                                                                                                                       

  K. Macro &                                                                                                                                                                
  external                                                                                                                                                                  
  exposures                                                                                                                                                                 
  (qualitative)                                                                                                                                                             

  K1                Dependency on commodity                                                                                                                                 
                    prices (oil, metals)                                                                                                                                    
                    and pass-through                                                                                                                                        
                    ability                                                                                                                                                 

  K1.1              Commodity input         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Commodity Dependency Score (1--5).         KPI Card: Commodity
                    dependence              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            input dependence \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Raw Materials /                                              Colors: Positive=Green,
                                            Cost Structure / Risk Factors → identify key commodities.                                                                       Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  K1.2                                                                                                                                                                      

  K2                Export/import exposure  https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    and geopolitical trade                                                                                                                                  
                    risk                                                                                                                                                    

  K2.1              Export/import           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  External Trade Exposure % = Export Revenue Donut chart:
                    dependence              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → or Import-dependent Inputs ÷ Relevant      Export/import
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Geography /       Total.                                     dependence \| Colors:
                                            Revenue / Procurement → export revenue and imported inputs.                                                                     Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  K2.2              Geopolitical trade risk NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Geopolitical Trade Risk Score (1--5).      KPI Card: Geopolitical
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            trade risk \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Risk Factors →                                                      Positive=Green,
                                            sanctions, tariffs, shipping routes and geopolitical dependencies; DGFT →                                                       Neutral=Blue,
                                            https://www.dgft.gov.in/ → Regulatory Updates / Foreign Trade Policy / ITC(HS) →                                                Negative=Red,
                                            search relevant product or policy → relevant trade policy.                                                                      Insufficient/N/A=Grey

  K3                Sensitivity to interest https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    rates & economic                                                                                                                                        
                    cycles: cyclical vs                                                                                                                                     
                    defensive business                                                                                                                                      

  K3.1              Interest-rate           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Interest Rate Exposure = Floating-rate     Donut chart:
                    sensitivity             Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Debt ÷ Total Debt × 100 where disclosed.   Interest-rate
                                            select reporting year → open Annual Report attachment/PDF → Financial Risk                                                      sensitivity \| Colors:
                                            Management → Borrowings → floating-rate debt and sensitivity disclosures.                                                       Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  K3.2              Economic cyclicality    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Cyclicality Score (1--5).                  Donut chart: Economic
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            cyclicality \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Industry Outlook                                             Positive=Green,
                                            / Demand Sensitivity → classify demand as cyclical or defensive.                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  K4                Foreign currency        https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    mismatches: revenues vs                                                                                                                                 
                    costs denominated in                                                                                                                                    
                    different currencies                                                                                                                                    

  K4.1                                                                                                                                                                      

  K4.2              Hedging protection      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Hedge Coverage % = Hedged Foreign Currency Donut chart: Hedging
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Exposure ÷ Total Relevant Exposure × 100   protection \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Financial Risk           where disclosed.                           Positive=Green,
                                            Management → Derivative / Hedging disclosures → hedge coverage.                                                                 Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  L. Financial                                                                                                                                                              
  policy & capital                                                                                                                                                          
  structure                                                                                                                                                                 
  behavior                                                                                                                                                                  

  L1                                                                                                                                                                        

  L1.1              Leverage policy         NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Leverage Trend Score (1--5) based on       Line chart: Leverage
                                            → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → consistency of debt policy and management  policy \| Colors:
                                            Period Ended → select period → Search By → select applicable result type → open      commentary.                                Positive=Green,
                                            Financial Results Detail → open XBRL / attachment → Balance Sheet / Cash Flow →                                                 Neutral=Blue,
                                            Borrowings; NSE →                                                                                                               Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Financial Risk Management →                                                
                                            borrowing policy.                                                                                                               

  L1.2              Covenant management     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Covenant Score (1--5): compliant with      KPI Card: Covenant
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → headroom scores higher than                management \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Borrowings / Financial   breaches/waivers.                          Positive=Green,
                                            Risk Management → covenant disclosures and compliance.                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  L2                History of refinancing  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    or covenant breaches                                                                                                                                    
                    and remedies used                                                                                                                                       

  L2.1              Refinancing history     NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Refinancing Frequency = material           KPI Card: Refinancing
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      refinancing events over 5 years.           history \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            search refinancing, debt restructuring, maturity extension, rating action; NSE →                                                Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → borrowings note.                                                           

  L2.2              Covenant breaches /     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Breach Status = None / Historical /        KPI Card: Covenant
                    remedies                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Recent; score based on severity and        breaches / remedies \|
                                            select reporting year → open Annual Report attachment/PDF → Borrowings / Covenant    remedy.                                    Colors: Positive=Green,
                                            Compliance → breach, waiver or renegotiation disclosures.                                                                       Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  L3                Dividend policy         https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    consistency and                                                                                                                                         
                    rationale for changes                                                                                                                                   

  L3.1              Dividend consistency    NSE → https://www.nseindia.com/companies-listing/corporate-filings-actions →         Dividend Consistency Score (1--5) based on Line chart: Dividend
                                            Corporate Actions → Company \[Input: Company Name or Symbol\] → enter NSE symbol →   continuity and rationale.                  consistency \| Colors:
                                            Purpose \[Input: Search by Keyword\] → enter relevant action → Meeting \[Select if                                              Positive=Green,
                                            applicable\] → select date range → open matching corporate action → Purpose =                                                   Neutral=Blue,
                                            Dividend → compile 5-year history; NSE →                                                                                        Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Dividend section.                                                          

  L3.2              Rationale for changes   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Policy Rationale Score (1--5).             Donut chart: Rationale
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            for changes \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Board's Report →                                                    Positive=Green,
                                            Dividend Recommendation / Dividend Policy → rationale for changes.                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  L4                Use of off-balance      https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    sheet financing,                                                                                                                                        
                    leasing, or structured                                                                                                                                  
                    instruments                                                                                                                                             

  L4.1              Lease commitments       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Lease Exposure = Lease Liabilities ÷ Total Donut chart: Lease
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Debt or relevant asset base.               commitments \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →                                                 Positive=Green,
                                            Leases (Ind AS 116) → lease liabilities, commitments and right-of-use assets.                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  L4.2              Structured /            NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Off-balance-sheet Risk Score (1--5); flag  Donut chart: Structured
                    off-balance-sheet       Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → only disclosed structures.                 / off-balance-sheet
                    arrangements            select reporting year → open Annual Report attachment/PDF → Notes → commitments,                                                arrangements \| Colors:
                                            guarantees, special-purpose arrangements, securitisation or other structured                                                    Positive=Green,
                                            financing.                                                                                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  M. M&A &                                                                                                                                                                  
  inorganic growth                                                                                                                                                          
  behaviour                                                                                                                                                                 

  M1                Historical M&A record:  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    disciplined or                                                                                                                                          
                    acquisitive; success in                                                                                                                                 
                    integration                                                                                                                                             

  M1.1              M&A frequency           NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   M&A Frequency = number of material         KPI Card: M&A frequency
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      acquisitions over 5 years.                 \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            search Acquisition / Agreement to acquire / Business Transfer / Scheme → compile                                                Negative=Red,
                                            last 5 years; NSE →                                                                                                             Insufficient/N/A=Grey
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Business Combination notes.                                                

  M1.2                                                                                                                                                                      

  M1.3              Acquisitive vs          NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   M&A Discipline Score (1--5).               KPI Card: Acquisitive
                    disciplined pattern     Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 vs disciplined pattern
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment +                                             Positive=Green,
                                            NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →                                             Neutral=Blue,
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            Negative=Red,
                                            select reporting year → open Annual Report attachment/PDF → compare acquisition                                                 Insufficient/N/A=Grey
                                            frequency, rationale, size and funding across 5 years.                                                                          

  M2                Acquisitions from       https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    related parties or                                                                                                                                      
                    assets sold to                                                                                                                                          
                    affiliates                                                                                                                                              

  M2.1              Related-party           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Related-party M&A Flag = None / Present;   KPI Card: Related-party
                    acquisitions            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → if present assess frequency and            acquisitions \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Related Party            materiality.                               Positive=Green,
                                            Disclosures → acquisitions/purchases from promoter/group entities; NSE →                                                        Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            transaction announcement.                                                                                                       

  M2.2              Assets sold to          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Affiliate Disposal Exposure Score (1--5).  KPI Card: Assets sold
                    affiliates              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            to affiliates \|
                                            select reporting year → open Annual Report attachment/PDF → Related Party                                                       Colors: Positive=Green,
                                            Disclosures / PPE disposal / business transfer notes.                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  M3                Size of M&A pipeline    https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    and rationale ---                                                                                                                                       
                    value-creating or                                                                                                                                       
                    empire-building?                                                                                                                                        

  M3.1              M&A pipeline            NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Pipeline Count = material announced but    KPI Card: M&A pipeline
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      not completed transactions.                \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            investor presentations / acquisition announcements → identify announced pending                                                 Negative=Red,
                                            transactions; NSE →                                                                                                             Insufficient/N/A=Grey
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → commitments / subsequent                                                   
                                            events.                                                                                                                         

  M3.2              Value-creation          NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Value Creation Score (1--5).               KPI Card:
                    rationale               Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Value-creation
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 rationale \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Positive=Green,
                                            acquisition rationale / strategic fit; NSE →                                                                                    Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Negative=Red,
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            Insufficient/N/A=Grey
                                            reporting year → open Annual Report attachment/PDF → Business Combination →                                                     
                                            goodwill, synergies and integration commentary.                                                                                 

  N. ESG, social                                                                                                                                                            
  license &                                                                                                                                                                 
  sustainability                                                                                                                                                            
  (qualitative)                                                                                                                                                             

  N1                Company's ESG ambition  https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    vs actual                                                                                                                                               
                    implementations:                                                                                                                                        
                    targets, roadmaps                                                                                                                                       

  N1.1              ESG targets             NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Target Coverage Score (1--5).              KPI Card: ESG targets
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Business Responsibility                                             Positive=Green,
                                            & Sustainability Report (BRSR) → ESG targets / KPIs / commitments.                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N1.2                                                                                                                                                                      

  N2                                                                                                                                                                        

  N2.1              Community impact        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Community Impact Score (1--5).             KPI Card: Community
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            impact \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → BRSR / CSR Report →                                                 Positive=Green,
                                            community engagement, affected communities and grievance mechanisms.                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N2.2              Displacement /          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Displacement Risk = None / Low / Moderate  KPI Card: Displacement
                    resettlement            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → / High based on disclosed project impact.  / resettlement \|
                                            select reporting year → open Annual Report attachment/PDF → BRSR / CSR / Project                                                Colors: Positive=Green,
                                            Risk → land acquisition, resettlement and rehabilitation disclosures; PARIVESH →                                                Neutral=Blue,
                                            https://parivesh.nic.in/ → Track Your Proposal / Environmental Clearance / Forest                                               Negative=Red,
                                            Clearance / Wildlife Clearance / CRZ Clearance → search project/company → project                                               Insufficient/N/A=Grey
                                            clearances where applicable.                                                                                                    

  N3                Environmental risks:                                                                                                                                    
                    pollution, hazardous                                                                                                                                    
                    waste, pending                                                                                                                                          
                    environmental                                                                                                                                           
                    clearances                                                                                                                                              

  N3.1              Pollution /             NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Environmental Incident Score (1--5).       KPI Card: Pollution /
                    environmental incidents Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            environmental incidents
                                            select reporting year → open Annual Report attachment/PDF → BRSR → environmental                                                \| Colors:
                                            performance / incidents / fines; PARIVESH → https://parivesh.nic.in/ → Track Your                                               Positive=Green,
                                            Proposal / Environmental Clearance / Forest Clearance / Wildlife Clearance / CRZ                                                Neutral=Blue,
                                            Clearance → search project/company → project/environment clearance records.                                                     Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N3.2              Hazardous waste         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Hazardous Waste Management Score (1--5).   KPI Card: Hazardous
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            waste \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → BRSR → waste management                                             Positive=Green,
                                            → hazardous waste generated, recycled, treated and disposed.                                                                    Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N3.3              Pending clearances      PARIVESH → https://parivesh.nic.in/ → Track Your Proposal → Proposal Search → select Clearance Status = Cleared / Pending /     KPI Card: Pending
                                            clearance type (Environmental / Forest / Wildlife / CRZ) → enter project/company     Under Process / Not Applicable.            clearances \| Colors:
                                            details → open proposal → review status and documents → search project/company →                                                Positive=Green,
                                            Environmental / Forest / Wildlife / CRZ Clearance status; cross-check NSE →                                                     Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Negative=Red,
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            Insufficient/N/A=Grey
                                            reporting year → open Annual Report attachment/PDF → commitments.                                                               

  N4                Labour relations:       https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    unions, strikes,                                                                                                                                        
                    employee grievances                                                                                                                                     

  N4.1              Union / collective      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Labour Relations Score (1--5).             KPI Card: Union /
                    bargaining exposure     Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            collective bargaining
                                            select reporting year → open Annual Report attachment/PDF → BRSR / Human Resources →                                            exposure \| Colors:
                                            unionisation and employee relations disclosures.                                                                                Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N4.2              Strikes / disputes      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Labour Disruption Score (1--5).            KPI Card: Strikes /
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            disputes \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → BRSR / Risk Factors →                                               Positive=Green,
                                            strikes, lockouts, labour disputes.                                                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N4.3              Employee grievances     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Grievance Resolution Rate = Resolved       KPI Card: Employee
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Complaints ÷ Total Complaints × 100 where  grievances \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → BRSR → grievance         disclosed.                                 Positive=Green,
                                            redressal / POSH / complaints and resolution.                                                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N5                Supply-chain human      https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    rights risk:                                                                                                                                            
                    forced/child labour in                                                                                                                                  
                    sourcing                                                                                                                                                

  N5.1              Human-rights policy /   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Human Rights Supply-chain Score (1--5).    KPI Card: Human-rights
                    supplier screening      Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            policy / supplier
                                            select reporting year → open Annual Report attachment/PDF → BRSR → human rights                                                 screening \| Colors:
                                            policy, supplier assessment and due diligence.                                                                                  Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  N5.2              Forced/child labour     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Incident Status = None disclosed /         KPI Card: Forced/child
                    incidents               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Incidents / Corrective Action.             labour incidents \|
                                            select reporting year → open Annual Report attachment/PDF → BRSR → incidents /                                                  Colors: Positive=Green,
                                            corrective actions / supplier audits.                                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  O. Reputational &                                                                                                                                                         
  media signals                                                                                                                                                             

  O1                Recent media                                                                                                                                            
                    controversies, social                                                                                                                                   
                    media sentiment,                                                                                                                                        
                    analyst/stakeholder                                                                                                                                     
                    complaints                                                                                                                                              

  O1.1              Material controversies  NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Controversy Score (1--5) based on          KPI Card: Material
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      materiality, duration and disclosed        controversies \|
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      impact.                                    Colors: Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            company responses / clarifications; NSE →                                                                                       Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Risk Factors / legal and                                                   
                                            reputation disclosures → identify material controversies.                                                                       

  O1.2              Stakeholder complaints  NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Complaint Resolution Score (1--5).         KPI Card: Stakeholder
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            complaints \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → BRSR →                                                              Positive=Green,
                                            customer/employee/investor complaints and grievance mechanisms; NSE →                                                           Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            company clarifications.                                                                                                         

  O2                Brand health                                                                                                                                            
                    indicators: negative                                                                                                                                    
                    campaigns, product                                                                                                                                      
                    recalls, safety                                                                                                                                         
                    incidents                                                                                                                                               

  O2.1                                                                                                                                                                      

  O2.2              Safety incidents        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Safety Incident Score (1--5).              KPI Card: Safety
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            incidents \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → BRSR / Risk Factors /                                               Positive=Green,
                                            Contingent Liabilities → material safety incidents.                                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  O2.3              Negative campaigns /    NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Reputation Response Score (1--5) based on  KPI Card: Negative
                    reputation response     Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      evidence of timely disclosure and          campaigns / reputation
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      remediation.                               response \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Positive=Green,
                                            company responses / clarifications; NSE →                                                                                       Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Negative=Red,
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            Insufficient/N/A=Grey
                                            reporting year → open Annual Report attachment/PDF → reputation risk disclosures.                                               

  O3                Regulatory fines or     https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    public investigations                                                                                                                                   
                    that damage reputation                                                                                                                                  

  O3.1              Regulatory fines        NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Fine Frequency = material fines over 5     KPI Card: Regulatory
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      years; score by severity.                  fines \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            search penalty/fine/order/SEBI/stock exchange/regulator; NSE →                                                                  Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → contingent liabilities /                                                   
                                            regulatory matters.                                                                                                             

  O3.2              Public investigations   NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Investigation Status = None / Inquiry /    Donut chart: Public
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      Investigation / Order.                     investigations \|
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Colors: Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            investigation/probe/show-cause/notice; SEBI → https://www.sebi.gov.in/ → Legal /                                                Negative=Red,
                                            Regulations / Orders / search company or subject → retrieve applicable                                                          Insufficient/N/A=Grey
                                            disclosure/order → Orders / Legal; CCI → https://www.cci.gov.in/antitrust/orders →                                              
                                            Antitrust → Orders → Case Type / Order Date / Parties / Sectionwise / Free Text →                                               
                                            enter company / transaction → open matching order / search transaction or company →                                             
                                            review approval, modification or order → Orders where relevant.                                                                 

  P. Accounting,                                                                                                                                                            
  disclosure &                                                                                                                                                              
  audit quality                                                                                                                                                             
  (qualitative)                                                                                                                                                             

  P1                                                                                                                                                                        

  P1.1              Disclosure detail       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Disclosure Quality Score (1--5).           KPI Card: Disclosure
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            detail \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts / MD&A                                            Positive=Green,
                                            / BRSR → assess completeness and specificity.                                                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P1.2              Timeliness / frequency  NSE → https://www.nseindia.com/companies-listing/corporate-filings-financial-results Timeliness = Filing Date − Period End      Line chart: Timeliness
                                            → Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol → Date; compare across periods.              / frequency \| Colors:
                                            Period Ended → select period → Search By → select applicable result type → open                                                 Positive=Green,
                                            Financial Results Detail → open XBRL / attachment → compare reporting dates and                                                 Neutral=Blue,
                                            period-end dates across quarters; NSE →                                                                                         Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Insufficient/N/A=Grey
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            results announcements.                                                                                                          

  P2                Quality of notes: RPTs  https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    fully disclosed and                                                                                                                                     
                    explained                                                                                                                                               

  P2.1              RPT completeness        NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  RPT Disclosure Completeness Score (1--5).  KPI Card: RPT
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            completeness \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →                                                 Positive=Green,
                                            Related Party Disclosures (Ind AS 24) → transaction type, balance and relationship.                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P2.2              RPT explanation quality NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  RPT Explanation Score (1--5).              KPI Card: RPT
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            explanation quality \|
                                            select reporting year → open Annual Report attachment/PDF → Related Party                                                       Colors: Positive=Green,
                                            Disclosures → nature, terms, purpose and approval.                                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P3                Auditor statements:     https://www.nseindia.com/companies-listing/corporate-filings-insider-trading                                                    
                    qualified opinions,                                                                                                                                     
                    emphasis of matter,                                                                                                                                     
                    frequent restatements                                                                                                                                   

  P3.1              Audit opinion           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Audit Opinion Status = Unmodified /        KPI Card: Audit opinion
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Qualified / Adverse / Disclaimer.          \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Independent Auditor's                                               Positive=Green,
                                            Report → Opinion / Basis for Opinion.                                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P3.2              Emphasis of matter /    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Audit Attention Score (1--5) based on      KPI Card: Emphasis of
                    key audit matters       Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → materiality and recurrence.                matter / key audit
                                            select reporting year → open Annual Report attachment/PDF → Independent Auditor's                                               matters \| Colors:
                                            Report → Emphasis of Matter / Key Audit Matters.                                                                                Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P3.3              Restatements            NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Restatement Count = material restatements  KPI Card: Restatements
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → over review period.                        \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Restated comparative                                                Positive=Green,
                                            figures / prior-period errors; compare last 5 years.                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P4                Complexity of financial                                                                                                                                 
                    statements: many                                                                                                                                        
                    schedules, multiple                                                                                                                                     
                    currencies, many                                                                                                                                        
                    subsidiaries                                                                                                                                            

  P4.1              Financial statement     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Complexity Score (1--5) based on disclosed KPI Card: Financial
                    complexity              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → structural complexity, not size alone.     statement complexity \|
                                            select reporting year → open Annual Report attachment/PDF → Notes → segment,                                                    Colors: Positive=Green,
                                            subsidiary, financial instrument and accounting policy sections.                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P4.2              Multiple currencies     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Currency Complexity = Number of material   Donut chart: Multiple
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → functional/presentation currencies         currencies \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Financial Risk           disclosed.                                 Positive=Green,
                                            Management → Foreign Currency Risk / functional currencies.                                                                     Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  P4.3              Subsidiary complexity   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Entity Complexity = Total Subsidiaries +   Donut chart: Subsidiary
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Associates + JVs; interpret with structure complexity \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes → List of          map.                                       Positive=Green,
                                            Subsidiaries / Associates / JVs → count and jurisdictions.                                                                      Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  Q. Financial                                                                                                                                                              
  statement quality                                                                                                                                                         
  & structural red                                                                                                                                                          
  flags                                                                                                                                                                     
  (non-numeric                                                                                                                                                              
  cues)                                                                                                                                                                     

  Q1                Frequent changes in     https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    auditors or CFO /                                                                                                                                       
                    finance team churn                                                                                                                                      

  Q1.1                                                                                                                                                                      

  Q1.2              CFO / finance           NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Finance Leadership Churn = number of       KPI Card: CFO / finance
                    leadership churn        Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      CFO/finance-head changes over 5 years.     leadership churn \|
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Colors: Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            Change in Management / Cessation / Appointment → CFO/KMP; compare 5 years.                                                      Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  Q2                Management defensive    https://www.nseindia.com/companies-listing/corporate-filings-announcements                                                      
                    answers to basic                                                                                                                                        
                    accounting questions                                                                                                                                    

  Q2.1                                                                                                                                                                      

  Q3                Complex or opaque group                                                                                                                                 
                    structures, many                                                                                                                                        
                    dormant entities                                                                                                                                        

  Q3.1              Group structure opacity NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Structure Opacity Score (1--5).            KPI Card: Group
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            structure opacity \|
                                            select reporting year → open Annual Report attachment/PDF → Notes → List of                                                     Colors: Positive=Green,
                                            Subsidiaries, Associates and JVs → identify layered ownership and business purpose.                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  Q3.2              Dormant / non-operating NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Dormant Entity Ratio =                     Donut chart: Dormant /
                    entities                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Dormant/Non-operating Entities ÷ Total     non-operating entities
                                            select reporting year → open Annual Report attachment/PDF → subsidiary list /        Group Entities × 100 where identifiable.   \| Colors:
                                            financial information of subsidiaries → identify entities with minimal/no operations                                            Positive=Green,
                                            where disclosed.                                                                                                                Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  Q4                Unexplained             https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    transactions close to                                                                                                                                   
                    reporting dates or                                                                                                                                      
                    fiscal year-end                                                                                                                                         

  Q4.1              Year-end transaction    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Year-end Concentration Score (1--5) based  KPI Card: Year-end
                    concentration           Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → on unusual material transactions near      transaction
                                            select reporting year → open Annual Report attachment/PDF → Notes to Accounts →      reporting date.                            concentration \|
                                            material transactions / subsequent events / related parties; compare transaction                                                Colors: Positive=Green,
                                            dates around year-end.                                                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  Q4.2              Explanation quality     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Explanation Score (1--5).                  KPI Card: Explanation
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            quality \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Notes / Board's Report /                                            Positive=Green,
                                            RPT disclosures → rationale for material year-end transactions.                                                                 Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  R. Early-warning                                                                                                                                                          
  behavioural red                                                                                                                                                           
  flags                                                                                                                                                                     

  R1                Sudden top-management   https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    departures without                                                                                                                                      
                    clear succession                                                                                                                                        

  R1.1              Sudden departures       NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Departure Risk Score (1--5) based on       KPI Card: Sudden
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      abruptness, role criticality and disclosed departures \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      reason.                                    Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            Change in Management / Cessation → CEO/CFO/Executive Director/SMP departures;                                                   Negative=Red,
                                            compare stated reasons.                                                                                                         Insufficient/N/A=Grey

  R1.2              Succession response     NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Succession Coverage = Key Departures with  KPI Card: Succession
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      Named Successor ÷ Key Departures × 100     response \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      where countable.                           Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            Appointment / Change in Management; NSE →                                                                                       Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Nomination & Remuneration                                                  
                                            Committee / succession planning.                                                                                                

  R2                Rapid, unexplained                                                                                                                                      
                    insider selling or                                                                                                                                      
                    concentrated block                                                                                                                                      
                    sales                                                                                                                                                   

  R2.1              Rapid insider selling   NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Rapid Selling Flag = repeated material     Line chart: Rapid
                                            Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      sales within a short window; use evidence, insider selling \|
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →      not intent inference.                      Colors: Positive=Green,
                                            Regulation 7(2) → compile sale events over 3--8 quarters.                                                                       Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  R2.2              Concentrated block      NSE → https://www.nseindia.com/companies-listing/corporate-filings-insider-trading → Block Sale Concentration = Largest Sale ÷  Donut chart:
                    sales                   Insider Trading → Regulation 7(2) → Company \[Input: Company Name or Symbol\] →      Total Insider Sales × 100.                 Concentrated block
                                            enter NSE symbol → select date range → open Regulation 7(2) disclosure / XBRL →                                                 sales \| Colors:
                                            Regulation 7(2) → large sale disclosures; NSE →                                                                                 Positive=Green,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Neutral=Blue,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Negative=Red,
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Insufficient/N/A=Grey
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            block/placement disclosures.                                                                                                    

  R3                Frequent capital raises https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    or repeated rights                                                                                                                                      
                    issues at discount                                                                                                                                      

  R3.1              Capital raise frequency NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Capital Raise Frequency = number of        KPI Card: Capital raise
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      material equity raises over 5 years.       frequency \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            search QIP / preferential / rights issue / public issue / placement → compile 5                                                 Negative=Red,
                                            years; NSE → https://www.nseindia.com/companies-listing/corporate-filings-actions →                                             Insufficient/N/A=Grey
                                            Corporate Actions → Company \[Input: Company Name or Symbol\] → enter NSE symbol →                                              
                                            Purpose \[Input: Search by Keyword\] → enter relevant action → Meeting \[Select if                                              
                                            applicable\] → select date range → open matching corporate action → Rights / Bonus /                                            
                                            other actions.                                                                                                                  

  R3.2              Discount / pricing      NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Pricing Score (1--5) based on transparency KPI Card: Discount /
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      and discount relative to disclosed         pricing \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      reference price.                           Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            issue terms → issue price, floor price, premium/discount and allottee class.                                                    Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  R4                Large, unexplained      https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    one-off transactions:                                                                                                                                   
                    asset sales, transfer                                                                                                                                   
                    pricing                                                                                                                                                 

  R4.1              One-off transaction     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  One-off Frequency = material one-off       KPI Card: One-off
                    frequency               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → transactions per 5 years.                  transaction frequency
                                            select reporting year → open Annual Report attachment/PDF → Notes → exceptional                                                 \| Colors:
                                            items / asset sales / business transfers; compare 5 years.                                                                      Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  R4.2              Transfer pricing /      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Transaction Rationale Score (1--5).        KPI Card: Transfer
                    rationale               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            pricing / rationale \|
                                            select reporting year → open Annual Report attachment/PDF → Related Party / tax /                                               Colors: Positive=Green,
                                            segment notes → pricing and rationale where disclosed.                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  R5                Auditor resignation     https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    mid-audit or auditor                                                                                                                                    
                    flagging internal                                                                                                                                       
                    control issues                                                                                                                                          

  R5.1              Auditor resignation     NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Auditor Resignation Flag = None /          KPI Card: Auditor
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      Historical / Recent.                       resignation \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            Change in Auditors / resignation; NSE →                                                                                         Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Auditor's Report → compare                                                 
                                            reasons.                                                                                                                        

  R5.2              Internal control issues NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Control Issue Score (1--5) based on        KPI Card: Internal
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → severity and remediation.                  control issues \|
                                            select reporting year → open Annual Report attachment/PDF → Auditor's Report →                                                  Colors: Positive=Green,
                                            Internal Financial Controls / material weaknesses / adverse remarks.                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  R6                                                                                                                                                                        

  R6.1              Response cadence        NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Response Cadence Score (1--5); use only    Line chart: Response
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      documented company responses and avoid     cadence \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      interpreting normal investor communication Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →  as defensive PR.                           Neutral=Blue,
                                            search Press Release / General Updates / Clarification / Media reports → compare                                                Negative=Red,
                                            dates around controversies.                                                                                                     Insufficient/N/A=Grey

  R6.2              Substance of response   NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Response Substance Score (1--5).           KPI Card: Substance of
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 response \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            clarification / rebuttal attachments → assess evidence, corrective actions and                                                  Negative=Red,
                                            specificity.                                                                                                                    Insufficient/N/A=Grey

  S.                                                                                                                                                                        
  Sector-specific                                                                                                                                                           
  considerations                                                                                                                                                            
  (examples)                                                                                                                                                                

  S1                Financials / banks:                                                                                                                                     
                    asset quality review,                                                                                                                                   
                    related-party                                                                                                                                           
                    exposures, regulatory                                                                                                                                   
                    capital, loan book                                                                                                                                      
                    underwriting quality                                                                                                                                    

  S1.1              Asset quality           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Asset Quality Score (1--5).                KPI Card: Asset quality
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Financial Statements /                                              Positive=Green,
                                            MD&A → GNPA, NNPA, SMA, restructuring and provisioning disclosures where applicable.                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S1.2              Related-party exposures NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  RPT Exposure Score (1--5).                 Donut chart:
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            Related-party exposures
                                            select reporting year → open Annual Report attachment/PDF → Notes → Related Party                                               \| Colors:
                                            Disclosures / exposures; governance disclosures.                                                                                Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S1.3              Regulatory capital      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Capital Adequacy Score (1--5) relative to  Donut chart: Regulatory
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → applicable regulatory minimum and          capital \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Basel / Capital Adequacy disclosed buffer.                          Positive=Green,
                                            / Pillar disclosures → CET1, Tier 1, total capital and buffers.                                                                 Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S1.4              Loan underwriting       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Underwriting Quality Score (1--5).         KPI Card: Loan
                    quality                 Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            underwriting quality \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → underwriting                                                 Colors: Positive=Green,
                                            standards, sector concentration, credit policy and monitoring.                                                                  Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S2                Pharma: drug approval   https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    pipelines, patent                                                                                                                                       
                    cliffs, regulatory                                                                                                                                      
                    inspections, price                                                                                                                                      
                    controls                                                                                                                                                

  S2.1                                                                                                                                                                      

  S2.2              Patent cliffs           NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Patent Cliff Risk Score (1--5).            Donut chart: Patent
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            cliffs \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Intellectual Property /                                             Positive=Green,
                                            Product Risk → material patent expiry disclosures.                                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S2.3              Regulatory inspections  NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Inspection Risk Score (1--5).              KPI Card: Regulatory
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 inspections \| Colors:
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 Positive=Green,
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Neutral=Blue,
                                            regulatory inspection / warning / remediation announcements; NSE →                                                              Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → regulatory compliance.                                                     

  S2.4              Price controls          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Price Control Exposure Score (1--5).       Donut chart: Price
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            controls \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → pricing                                                      Positive=Green,
                                            regulation / DPCO exposure; applicable product pricing disclosures.                                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S3                Auto / auto-components: https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    model refresh cycles,                                                                                                                                   
                    channel inventory,                                                                                                                                      
                    export dependencies                                                                                                                                     

  S3.1              Model refresh cycle     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Refresh Strength Score (1--5).             Line chart: Model
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            refresh cycle \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → product launches                                             Colors: Positive=Green,
                                            / model lifecycle / new platforms.                                                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S3.2              Channel inventory       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Channel Inventory Risk Score (1--5).       KPI Card: Channel
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            inventory \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → dealer inventory                                             Positive=Green,
                                            / channel stock commentary; NSE →                                                                                               Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-financial-results →                                                Negative=Red,
                                            Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol →                                              Insufficient/N/A=Grey
                                            Period Ended → select period → Search By → select applicable result type → open                                                 
                                            Financial Results Detail → open XBRL / attachment → sales trend.                                                                

  S3.3              Export dependency       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Export Dependency % = Export Revenue ÷     Donut chart: Export
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → Total Revenue × 100 where disclosed.       dependency \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → Geography / Revenue →                                               Positive=Green,
                                            export sales and overseas markets.                                                                                              Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S4                Tech / IT services:     https://www.nseindia.com/companies-listing/corporate-filings-annual-reports                                                     
                    client concentration,                                                                                                                                   
                    contract renewals,                                                                                                                                      
                    visa/immigration                                                                                                                                        
                    dependencies                                                                                                                                            

  S4.1              Client concentration    NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Top Client Concentration % where           KPI Card: Client
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → disclosed.                                 concentration \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → customer                                                     Colors: Positive=Green,
                                            concentration / revenue from largest clients.                                                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S4.2              Contract renewal risk   NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Renewal Risk Score (1--5).                 KPI Card: Contract
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            renewal risk \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → contracts,                                                   Positive=Green,
                                            renewals, deal pipeline and bookings.                                                                                           Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S4.3              Visa / immigration      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Visa/Immigration Risk Score (1--5).        KPI Card: Visa /
                    dependence              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            immigration dependence
                                            select reporting year → open Annual Report attachment/PDF → Risk Factors / Human                                                \| Colors:
                                            Resources → visa, immigration and overseas staffing exposure.                                                                   Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S5                Consumer goods: brand                                                                                                                                   
                    strength, distribution                                                                                                                                  
                    depth, commodity input                                                                                                                                  
                    volatility                                                                                                                                              

  S5.1              Brand strength          NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Brand Strength Score (1--5).               KPI Card: Brand
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            strength \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Brands / Market                                              Positive=Green,
                                            Position / Consumer Franchise → disclosed brand leadership indicators.                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S5.2              Distribution depth      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Distribution Depth Score (1--5).           KPI Card: Distribution
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            depth \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Distribution                                                 Positive=Green,
                                            Network → outlets, distributors, reach and rural/urban penetration where disclosed.                                             Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  S5.3              Commodity input         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Commodity Volatility Score (1--5).         Donut chart: Commodity
                    volatility              Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            input volatility \|
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Raw Materials /                                              Colors: Positive=Green,
                                            Risk Factors → key commodity exposure.                                                                                          Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  T. Country /                                                                                                                                                              
  geopolitical &                                                                                                                                                            
  cross-border                                                                                                                                                              
  risks                                                                                                                                                                     

  T1                Exposure to foreign                                                                                                                                     
                    sanctions, embargoes,                                                                                                                                   
                    or tariffs                                                                                                                                              

  T1.1              Sanctions / embargo     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Sanctions Exposure Score (1--5).           KPI Card: Sanctions /
                    exposure                Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            embargo exposure \|
                                            select reporting year → open Annual Report attachment/PDF → Risk Factors / Geography                                            Colors: Positive=Green,
                                            / Customers / Suppliers → countries and counterparties; DGFT →                                                                  Neutral=Blue,
                                            https://www.dgft.gov.in/ → Regulatory Updates / Foreign Trade Policy / ITC(HS) →                                                Negative=Red,
                                            search relevant product or policy → trade policy; RBI → https://www.rbi.org.in/ →                                               Insufficient/N/A=Grey
                                            Notifications / FEMA / Master Directions → search relevant currency, overseas                                                   
                                            investment, borrowing or remittance rule → FEMA where relevant.                                                                 

  T1.2              Tariff exposure         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Tariff Exposure Score (1--5).              Donut chart: Tariff
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            exposure \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → import/export                                                Positive=Green,
                                            markets; DGFT → https://www.dgft.gov.in/ → Regulatory Updates / Foreign Trade Policy                                            Neutral=Blue,
                                            / ITC(HS) → search relevant product or policy → ITC(HS) / Foreign Trade Policy →                                                Negative=Red,
                                            applicable tariff/trade restrictions.                                                                                           Insufficient/N/A=Grey

  T2                Earnings sensitivity to                                                                                                                                 
                    economic policy:                                                                                                                                        
                    changes in GST, import                                                                                                                                  
                    duties                                                                                                                                                  

  T2.1              GST sensitivity         NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  GST Sensitivity Score (1--5).              KPI Card: GST
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            sensitivity \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → tax/regulatory                                               Positive=Green,
                                            environment → GST-dependent pricing or costs.                                                                                   Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  T2.2              Import duty sensitivity NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Import Duty Sensitivity Score (1--5).      KPI Card: Import duty
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            sensitivity \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → imported inputs;                                             Positive=Green,
                                            DGFT → https://www.dgft.gov.in/ → Regulatory Updates / Foreign Trade Policy /                                                   Neutral=Blue,
                                            ITC(HS) → select relevant product/policy → open applicable trade-policy notification                                            Negative=Red,
                                            or ITC(HS) entry.                                                                                                               Insufficient/N/A=Grey

  T3                Currency convertibility                                                                                                                                 
                    or repatriation risks                                                                                                                                   
                    in operating                                                                                                                                            
                    jurisdictions                                                                                                                                           

  T3.1              Convertibility risk     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Convertibility Risk Score (1--5).          Donut chart:
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            Convertibility risk \|
                                            select reporting year → open Annual Report attachment/PDF → Foreign Currency Risk /                                             Colors: Positive=Green,
                                            Geography → countries with currency controls; RBI → https://www.rbi.org.in/ →                                                   Neutral=Blue,
                                            Notifications / Master Directions → FEMA / Foreign Exchange Management → select                                                 Negative=Red,
                                            relevant overseas investment / borrowing / remittance / currency rule → open                                                    Insufficient/N/A=Grey
                                            applicable direction or notification.                                                                                           

  T3.2              Repatriation risk       NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Repatriation Risk Score (1--5).            Donut chart:
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            Repatriation risk \|
                                            select reporting year → open Annual Report attachment/PDF → overseas subsidiaries /                                             Colors: Positive=Green,
                                            cash balances / dividend or remittance disclosures; RBI → https://www.rbi.org.in/ →                                             Neutral=Blue,
                                            Notifications / FEMA / Master Directions → search relevant currency, overseas                                                   Negative=Red,
                                            investment, borrowing or remittance rule → FEMA / overseas investment rules.                                                    Insufficient/N/A=Grey

  U. Questions to                                                                                                                                                           
  ask management                                                                                                                                                            
  (qualitative                                                                                                                                                              
  prompts)                                                                                                                                                                  

  U1                What keeps you awake at                                                                                                                                 
                    night about the                                                                                                                                         
                    business?                                                                                                                                               

  U1.1              Top                     NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Risk Alignment Score (1--5): compare       KPI Card: Top
                    management-identified   Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      management response with disclosed top     management-identified
                    risk                    symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      risks and actual business exposures.       risk \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment                                               Positive=Green,
                                                                                                                                                                            Neutral=Blue,
                                                                                                                                                                            Negative=Red,
                                                                                                                                                                            Insufficient/N/A=Grey

  U2                How do you prioritize                                                                                                                                   
                    capital allocation                                                                                                                                      
                    (growth vs return of                                                                                                                                    
                    capital)?                                                                                                                                               

  U2.1              Capital allocation      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Capital Allocation Mix = Growth Investment Donut chart: Capital
                    framework               Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → vs Return of Capital using disclosed       allocation framework \|
                                            select reporting year → open Annual Report attachment/PDF → Board's Report →         amounts.                                   Colors: Positive=Green,
                                            Dividend / Capital Allocation Policy; NSE →                                                                                     Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            investor presentation / earnings call → capex, acquisitions, dividends and buybacks.                                            

  U3                Who are your three                                                                                                                                      
                    biggest competitors and                                                                                                                                 
                    why?                                                                                                                                                    

  U3.1              Management-named        NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Competitor Evidence Score (1--5): named    KPI Card:
                    competitors             Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      competitors and reasons should reconcile   Management-named
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      with annual-report industry analysis.      competitors \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Positive=Green,
                                            Analysts/Institutional Investor Meet/Conference Call Updates → management discussion                                            Neutral=Blue,
                                            / investor presentation; compare NSE →                                                                                          Negative=Red,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Insufficient/N/A=Grey
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            
                                            reporting year → open Annual Report attachment/PDF → Competition section.                                                       

  U4                Where do you see                                                                                                                                        
                    revenue & margin                                                                                                                                        
                    sensitivity (top 3                                                                                                                                      
                    risks)?                                                                                                                                                 

  U4.1              Revenue sensitivity     NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Revenue Risk Coverage Score (1--5).        Donut chart: Revenue
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            sensitivity \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → Risk Factors /                                               Positive=Green,
                                            Revenue drivers / Segment Information; NSE →                                                                                    Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-announcements →                                                    Negative=Red,
                                            Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE                                                 Insufficient/N/A=Grey
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject                                                 
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             
                                            earnings call guidance.                                                                                                         

  U4.2              Margin sensitivity      NSE → https://www.nseindia.com/companies-listing/corporate-filings-annual-reports →  Margin Risk Coverage Score (1--5).         Donut chart: Margin
                                            Annual Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO →                                            sensitivity \| Colors:
                                            select reporting year → open Annual Report attachment/PDF → MD&A → raw materials /                                              Positive=Green,
                                            pricing / operating leverage; NSE →                                                                                             Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-financial-results →                                                Negative=Red,
                                            Financial Results → Company \[Input: Company Name or Symbol\] → enter NSE symbol →                                              Insufficient/N/A=Grey
                                            Period Ended → select period → Search By → select applicable result type → open                                                 
                                            Financial Results Detail → open XBRL / attachment → margin trend.                                                               

  U5                Explain any large                                                                                                                                       
                    related-party                                                                                                                                           
                    transactions in plain                                                                                                                                   
                    terms.                                                                                                                                                  

  U5.1              Management explanation  NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   Explanation Quality Score (1--5):          KPI Card: Management
                    of material RPTs        Corporate Announcements → Company \[Input: Company Name or Symbol\] → enter NSE      plain-language rationale reconciled to     explanation of material
                                            symbol → Events / Subject \[Input: Search by Keyword\] → enter relevant subject      filing terms.                              RPTs \| Colors:
                                            keyword → From / To date → GO → open matching announcement → Details / Attachment →                                             Positive=Green,
                                            earnings call / investor meet → RPT discussion where available; NSE →                                                           Neutral=Blue,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → Annual                                            Negative=Red,
                                            Reports → Company \[Input: Company Name or Symbol\] → enter NSE symbol → GO → select                                            Insufficient/N/A=Grey
                                            reporting year → open Annual Report attachment/PDF → Related Party Disclosures.                                                 

  U6                What is your succession                                                                                                                                 
                    plan for the CEO & CFO?                                                                                                                                 

  U6.1              CEO succession          NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   CEO Succession Readiness Score (1--5).     KPI Card: CEO
                                            search company/symbol → filter/search the relevant announcement subject → open                                                  succession \| Colors:
                                            filing/attachment → Change in Management / Appointment / Investor Meet; NSE →                                                   Positive=Green,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → search                                            Neutral=Blue,
                                            company/symbol → select the relevant Annual Report → open PDF → Nomination &                                                    Negative=Red,
                                            Remuneration Committee → succession planning.                                                                                   Insufficient/N/A=Grey

  U6.2              CFO succession          NSE → https://www.nseindia.com/companies-listing/corporate-filings-announcements →   CFO Succession Readiness Score (1--5).     KPI Card: CFO
                                            search company/symbol → filter/search the relevant announcement subject → open                                                  succession \| Colors:
                                            filing/attachment → Change in Management / Appointment / Investor Meet; NSE →                                                   Positive=Green,
                                            https://www.nseindia.com/companies-listing/corporate-filings-annual-reports → search                                            Neutral=Blue,
                                            company/symbol → select the relevant Annual Report → open PDF → Nomination &                                                    Negative=Red,
                                            Remuneration Committee → succession planning.                                                                                   Insufficient/N/A=Grey
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## Chart Guide

  --------------------------------------------------------------------------------------
  Rule                                Specification
  ----------------------------------- --------------------------------------------------
  Positive                            GREEN #16A34A. Use when the result indicates
                                      strength, improvement, successful execution, low
                                      risk, protection, retained customers, clean audit,
                                      etc.

  Neutral                             BLUE #2563EB. Use for
                                      moderate/mixed/stable/ambiguous-but-not-negative
                                      states.

  Negative                            RED #DC2626. Use for deterioration, high risk,
                                      failed/delayed initiatives, declining
                                      margins/revenue, adverse governance signals.

  Insufficient / Not disclosed        GREY #64748B. Never convert missing evidence into
                                      a neutral score.

  Two-category ordinal/status         Use Horizontal Bar / Progress Bar. Do NOT use a
  comparison                          pie/donut merely to show 50/50 or High/Low.

  Two-category part-to-whole          Use 100% Stacked Horizontal Bar. Example: Promoter
                                      vs Public holding, Domestic vs Export revenue.

  3+ category part-to-whole           Use Donut only when the categories genuinely
                                      represent composition/mix.

  Score / Rating                      Use Horizontal Bar or Gauge, with semantic color
                                      based on score.

  Trend / historical series           Use Line Chart. Green = improving, Blue =
                                      stable/mixed, Red = deteriorating.

  Lifecycle / segment classification  Use 100% Stacked Horizontal Bar. Growth=Green,
                                      Maturity=Blue, Commoditisation=Blue/Red depending
                                      on confirmed deterioration, Decline=Red.

  Ordered classification              Use Spectrum Bar with one marker, not multiple pie
                                      slices.

  Single supporting datapoint         Use KPI / Tag, no standalone chart.
  --------------------------------------------------------------------------------------
