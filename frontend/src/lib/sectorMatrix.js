// Sector Applicability Matrix - static Sector→Tier lookup table.
//
// Source of truth: the "Sector Applicability Matrix" reference sheet (68
// cross-sector ratios × 26 NSE-aligned sectors, plus Sr No 69-92
// industry-specific ratios that are Core only for their named sector(s) and
// Not Applicable everywhere else). This file is the SOFTWARE's copy of that
// sheet - a plain static lookup, computed/transcribed ONCE, never
// recalculated per keystroke or per render (per the UI spec's own
// Performance/Precompute rule): resolving a ratio's tier for a company is
// exactly two O(1) lookups - (a) company → sector, (b) sector → tier - not
// a live filtering loop across all ratios on every interaction.
//
// Tiers:
//   C = Core (Tier 1)      - shown first, pre-checked by default
//   S = Secondary (Tier 2) - one click away, not pre-checked
//   N = Not Applicable     - hidden by default, never a hard block (an
//                            analyst can still search for and select it)
//   D = Different Definition Needed - applicable, but the standard
//                            formula/line-items must be reinterpreted for
//                            this sector; NEVER auto-hidden, NEVER
//                            auto-computed with the standard formula either
//                            - see SECTOR_DEFINITION_OVERRIDES below.

// The 26-sector taxonomy, in the EXACT column order the tier strings below
// are encoded in. Financial Services (Banks/NBFC/Insurance/Capital Markets)
// and Healthcare (Pharmaceuticals/Healthcare Services) are each split into
// their own columns - collapsing them into one "Financial Services"/
// "Healthcare" sector would hide the exact distinctions this matrix exists
// to capture.
export const SECTORS = [
  'Automobile & Auto Components',
  'Capital Goods',
  'Chemicals',
  'Construction',
  'Construction Materials (Cement)',
  'Consumer Durables',
  'Consumer Services',
  'Diversified',
  'Fast Moving Consumer Goods (FMCG)',
  'Banks',
  'NBFC',
  'Insurance',
  'Capital Markets (Broking/AMC/Exchanges)',
  'Forest Materials (Paper)',
  'Pharmaceuticals',
  'Healthcare Services (Hospitals/Diagnostics)',
  'Information Technology',
  'Media, Entertainment & Publication',
  'Metals & Mining',
  'Oil, Gas & Consumable Fuels',
  'Power',
  'Realty',
  'Retailing',
  'Services (Logistics/Transportation/Aviation)',
  'Telecommunication',
  'Textiles',
];

// Ratio Sr No 1-68 - [ratio_no, ratio_name, group, tierString].
// tierString has exactly 26 characters, one per SECTORS[] entry, in order.
const RATIO_ROWS = [
  [1, 'Inventory Turnover', 'INV', 'CCCSCCNSCNNNNCCSNNCSSDCSSC'],
  [2, 'Days Inventory Outstanding (DOH)', 'INV', 'CCCSCCNSCNNNNCCSNNCSSDCSSC'],
  [3, 'Receivables Turnover', 'REC', 'CCCCCCCSCNNNCCCCCCCCCCCCCC'],
  [4, 'Days Sales Outstanding (DSO)', 'REC', 'CCCCCCCSCNNNCCCCCCCCCCCCCC'],
  [5, 'Payables Turnover', 'PAY', 'CCCCCCNSCNNNNCCSNNCCCCCCCC'],
  [6, 'Days Payables Outstanding (DPO)', 'PAY', 'CCCCCCNSCNNNNCCSNNCCCCCCCC'],
  [7, 'Asset Turnover', 'EFF', 'CCCCCCNSSNNNSCSCNNCCCSSCCC'],
  [8, 'Working Capital Turnover', 'WC', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [9, 'Cash Conversion Cycle', 'WC', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [10, 'Current Ratio', 'LIQ', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [11, 'Quick Ratio', 'LIQ', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [12, 'Cash Ratio', 'LIQ', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [13, 'Working Capital', 'WC', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [14, 'Gross Profit Margin', 'MARGIN', 'CCCCCCCSCSSNCCCCCCCCCCCCCC'],
  [15, 'Operating Profit Margin', 'MARGIN', 'CCCCCCCSCSSNCCCCCCCCCCCCCC'],
  [16, 'Net Profit Margin', 'MARGIN', 'CCCCCCCSCSSNCCCCCCCCCCCCCC'],
  [17, 'Return on Assets (ROA)', 'RETURN', 'CCCCCCCCCCCSCCCCCCCCCCCCCC'],
  [18, 'Return on Equity (ROE)', 'RETURN', 'CCCCCCCCCCCSCCCCCCCCCCCCCC'],
  [19, 'Return on Capital Employed (ROCE)', 'RETURN', 'CCCCCCCCCCCSCCCCCCCCCCCCCC'],
  [20, 'Debt-to-Equity Ratio', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [21, 'Debt Ratio', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [22, 'Interest Coverage Ratio', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [23, 'Financial Leverage Ratio', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [24, 'Price-to-Earnings (P/E)', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [25, 'Price-to-Book (P/B)', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [26, 'Price-to-Sales (P/S)', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [27, 'Dividend Yield', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [28, 'Earnings Yield', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [29, 'Enterprise Value/EBITDA', 'VAL_EV', 'SSSSSSSCSNNNSSSSSSSSSCSSSS'],
  [30, 'Fixed Asset Turnover', 'EFF', 'CCCCCCNSSNNNSCSCNNCCCSSCCC'],
  [31, 'Days Working Capital', 'WC', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [32, 'Receivables-to-Payables Ratio', 'WC', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [33, 'Net Debt/EBITDA', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [34, 'Debt Service Coverage Ratio (DSCR)', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [35, 'Cash Flow Coverage Ratio', 'LEV', 'CCCCCCSCSSSNSCSSSSCCCCSCCC'],
  [36, 'Free Cash Flow (FCF)', 'CASHFLOW', 'SSSCSSCSSNNNCSSCCCSCCCSCCS'],
  [37, 'FCF Yield', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [38, 'FCF Margin', 'CASHFLOW', 'SSSCSSCSSNNNCSSCCCSCCCSCCS'],
  [39, 'Operating Cash Flow Ratio', 'LIQ', 'CCCSCCSSCNNNSCCSSSCSSDCSSC'],
  [40, 'Capex Intensity', 'CASHFLOW', 'SSSCSSCSSNNNCSSCCCSCCCSCCS'],
  [41, 'OCF/Net Profit', 'QUALITY', 'SSSCSSCSSSSNSSSSCCSCCCSCCS'],
  [42, 'Return on Invested Capital (ROIC)', 'RETURN', 'CCCCCCCCCCCSCCCCCCCCCCCCCC'],
  [43, 'Effective Tax Rate', 'TAX', 'SSSSSSSSSSSSSSSSSSSSSSSSSS'],
  [44, 'Contribution Margin', 'MARGIN', 'CCCCCCCSCSSNCCCCCCCCCCCCCC'],
  [45, 'EPS Growth Rate', 'GROWTH', 'SSSSSSCSSSSSCSSSCCSSSSSSSS'],
  [46, 'Book Value per Share (BVPS)', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [47, 'Dividend Payout Ratio', 'GROWTH', 'SSSSSSCSSSSSCSSSCCSSSSSSSS'],
  [48, 'Retention Ratio', 'GROWTH', 'SSSSSSCSSSSSCSSSCCSSSSSSSS'],
  [49, 'Sustainable Growth Rate', 'GROWTH', 'SSSSSSCSSSSSCSSSCCSSSSSSSS'],
  [50, 'PEG Ratio', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [51, 'EV/Sales', 'VAL_EV', 'SSSSSSSCSNNNSSSSSSSSSCSSSS'],
  [52, 'EV/FCF', 'VAL_EV', 'SSSSSSSCSNNNSSSSSSSSSCSSSS'],
  [53, 'Price/Cash Flow', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [54, 'Graham Number', 'VAL_EQ', 'SSSSSSSCSCCCCSSSSSSSSCSSSS'],
  [55, 'Altman Z-Score', 'RISK', 'SSSSSSSSSNNNSSSSSSSSSSSSSS'],
  [56, 'Piotroski F-Score', 'RISK', 'SSSSSSSSSNNNSSSSSSSSSSSSSS'],
  [57, 'Beneish M-Score', 'RISK', 'SSSSSSSSSNNNSSSSSSSSSSSSSS'],
  [58, 'Net Interest Margin (NIM)', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [59, 'CASA Ratio', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [60, 'Gross NPA %', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [61, 'Net NPA %', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [62, 'Provision Coverage Ratio (PCR)', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [63, 'Capital Adequacy Ratio (CRAR)', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [64, 'Credit-to-Deposit Ratio', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [65, 'Cost-to-Income Ratio', 'BANK', 'NNNNNNNNNCCNSNNNNNNNNNNNNN'],
  [66, 'Beta', 'MARKET', 'CCCCCCCCCCCCCCCCCCCCCCCCCC'],
  [67, 'Promoter Pledge %', 'MARKET', 'CCCCCCCCCCCCCCCCCCCCCCCCCC'],
  [68, 'Free Float %', 'MARKET', 'CCCCCCCCCCCCCCCCCCCCCCCCCC'],
];

// Sr No 69-92 - INDUSTRY-SPECIFIC ratios. Per spec: Core (C) ONLY for their
// named sector(s), Not Applicable everywhere else - there is no Secondary
// tier for these. Encoded directly as {ratio_no, name, sectors: [...]}
// rather than a 26-char string, since each row only ever lights up 1-2
// sectors.
export const INDUSTRY_SPECIFIC_RATIOS = [
  { ratio_no: 69, name: 'Solvency Ratio', sectors: ['Insurance'] },
  { ratio_no: 70, name: 'Combined Ratio', sectors: ['Insurance'] },
  { ratio_no: 71, name: 'Claims Ratio (Loss Ratio)', sectors: ['Insurance'] },
  { ratio_no: 72, name: 'Persistency Ratio', sectors: ['Insurance'] },
  { ratio_no: 73, name: 'Insurance Expense Ratio', sectors: ['Insurance'] },
  { ratio_no: 74, name: 'Inventory-to-Sales Ratio (Realty)', sectors: ['Realty'] },
  { ratio_no: 75, name: 'Debt-to-Presales Ratio', sectors: ['Realty'] },
  { ratio_no: 76, name: 'Collection Efficiency Ratio', sectors: ['Realty'] },
  { ratio_no: 77, name: 'ARPU (Average Revenue Per User)', sectors: ['Media, Entertainment & Publication', 'Telecommunication'] },
  { ratio_no: 78, name: 'Subscriber Churn Rate', sectors: ['Media, Entertainment & Publication', 'Telecommunication'] },
  { ratio_no: 79, name: 'Plant Load Factor (PLF) / Capacity Utilization', sectors: ['Power'] },
  { ratio_no: 80, name: 'Reserve Replacement Ratio', sectors: ['Oil, Gas & Consumable Fuels'] },
  { ratio_no: 81, name: 'Gross Refining Margin (GRM)', sectors: ['Oil, Gas & Consumable Fuels'] },
  { ratio_no: 82, name: 'EBITDA per Tonne', sectors: ['Construction Materials (Cement)', 'Metals & Mining'] },
  { ratio_no: 83, name: 'Capacity Utilization Rate', sectors: ['Automobile & Auto Components', 'Capital Goods', 'Chemicals', 'Construction Materials (Cement)', 'Consumer Durables', 'Forest Materials (Paper)', 'Metals & Mining', 'Oil, Gas & Consumable Fuels', 'Power', 'Textiles'] },
  { ratio_no: 84, name: 'Employee Attrition Rate', sectors: ['Consumer Services', 'Information Technology'] },
  { ratio_no: 85, name: 'Revenue per Employee', sectors: ['Consumer Services', 'Capital Markets (Broking/AMC/Exchanges)', 'Information Technology'] },
  { ratio_no: 86, name: 'Utilization Rate', sectors: ['Information Technology'] },
  { ratio_no: 87, name: 'Same-Store Sales Growth (SSSG)', sectors: ['Consumer Services', 'Fast Moving Consumer Goods (FMCG)', 'Retailing'] },
  { ratio_no: 88, name: 'Sales per Square Foot', sectors: ['Retailing'] },
  { ratio_no: 89, name: 'AUM Growth Rate', sectors: ['NBFC', 'Capital Markets (Broking/AMC/Exchanges)'] },
  { ratio_no: 90, name: 'Yield on AUM', sectors: ['Capital Markets (Broking/AMC/Exchanges)'] },
  { ratio_no: 91, name: 'Load Factor (Aviation)', sectors: ['Services (Logistics/Transportation/Aviation)'] },
  { ratio_no: 92, name: 'Cost per ASK (CASK)', sectors: ['Services (Logistics/Transportation/Aviation)'] },
];

// "Different Definition Needed" (D-tier) overrides - currently only Realty
// carries any D-tier ratios in the matrix. Per spec, a D-tier ratio must
// NEVER be auto-computed with the standard formula: selecting one shows
// this one-line note FIRST, before any number, so the analyst knows exactly
// what "Inventory"/"Working Capital" etc. means for this sector.
export const SECTOR_DEFINITION_OVERRIDES = {
  Realty: {
    1: 'For Realty, "Inventory" = unsold/under-construction property stock, not raw-material/finished-goods inventory.',
    2: 'For Realty, "Days Inventory Outstanding" measures how long unsold/under-construction property stock sits before sale, not raw-material/finished-goods turnover days.',
    8: 'For Realty, "Working Capital Turnover" reflects the property development cycle (land + construction WIP vs. current liabilities), not a conventional goods-business working-capital cycle.',
    9: 'For Realty, the "Cash Conversion Cycle" spans land acquisition through project completion and customer collection - materially longer than a conventional goods-business cycle, and not directly comparable to it.',
    10: 'For Realty, "Current Assets" are dominated by unsold/under-construction inventory (often illiquid for years), so Current Ratio reads very differently than for a conventional goods business.',
    11: 'For Realty, Quick Ratio\'s exclusion of "Inventory" excludes unsold/under-construction property stock - the company\'s core asset - so a low Quick Ratio here is structural, not a liquidity red flag by itself.',
    12: 'For Realty, Cash Ratio ignores both inventory (unsold property) and receivables (buyer dues) - the most conservative possible reading, and structurally low for this sector by design.',
    13: 'For Realty, "Working Capital" is dominated by unsold/under-construction property inventory rather than conventional receivables/payables/stock.',
    31: 'For Realty, "Days Working Capital" reflects the property development cycle, not a conventional goods-business working-capital cycle.',
    32: 'For Realty, "Trade Receivables" typically means buyer dues/installments recognised under the percentage-of-completion or completed-contract method, not a conventional trade-credit receivable.',
    39: 'For Realty, "Operating Cash Flow" is dominated by project-stage cash flows (land/construction spend vs. customer collections), not a conventional goods-business operating cycle.',
  },
};

// Build a Map for O(1) ratio_no -> row lookup, computed once at module load.
const RATIO_ROW_BY_NO = new Map(RATIO_ROWS.map((row) => [row[0], row]));
const INDSPEC_BY_NO = new Map(INDUSTRY_SPECIFIC_RATIOS.map((r) => [r.ratio_no, r]));

/** Tier ('C'|'S'|'N'|'D') for a given ratio_no (1-68) and sector name, or
 * null if the sector isn't recognised / the ratio_no isn't in the Sr 1-68
 * cross-sector set (use `getIndustrySpecificTier` for Sr 69-92). */
export function getTier(ratioNo, sectorName) {
  const row = RATIO_ROW_BY_NO.get(ratioNo);
  if (!row) return null;
  const col = SECTORS.indexOf(sectorName);
  if (col === -1) return null;
  return row[3][col] || null;
}

/** 'C' if this industry-specific ratio (Sr 69-92) applies to sectorName,
 * else 'N'. Returns null if ratioNo isn't an industry-specific ratio. */
export function getIndustrySpecificTier(ratioNo, sectorName) {
  const r = INDSPEC_BY_NO.get(ratioNo);
  if (!r) return null;
  return r.sectors.includes(sectorName) ? 'C' : 'N';
}

/** Every Sr 69-92 ratio that is Core for this sector - empty array if none
 * (the sector gets NO "[Sector] Specific Metrics" section at all, per spec,
 * rather than an empty one). */
export function getIndustrySpecificRatiosForSector(sectorName) {
  return INDUSTRY_SPECIFIC_RATIOS.filter((r) => r.sectors.includes(sectorName));
}

/** { core: [...], secondary: [...], notApplicable: [...], differentDefinition: [...] }
 * - every Sr 1-68 ratio bucketed by tier for one sector, each entry
 * { ratio_no, name, group, tier }. Computed on demand from the static
 * table (still O(68) per call, not a live re-derivation of the matrix
 * itself) - call once per sector resolution, not per render. */
export function getRatiosForSector(sectorName) {
  const buckets = { core: [], secondary: [], notApplicable: [], differentDefinition: [] };
  const col = SECTORS.indexOf(sectorName);
  if (col === -1) return buckets;
  for (const [ratio_no, name, group, tiers] of RATIO_ROWS) {
    const tier = tiers[col];
    const entry = { ratio_no, name, group, tier };
    if (tier === 'C') buckets.core.push(entry);
    else if (tier === 'S') buckets.secondary.push(entry);
    else if (tier === 'D') buckets.differentDefinition.push(entry);
    else buckets.notApplicable.push(entry);
  }
  return buckets;
}

/** Best-effort normalisation from whatever loose sector/industry string the
 * app currently has on hand (an AI-guessed `sector_guess`, the hardcoded
 * peer-group label in tools/peer_synthesis.py's SECTOR_GROUPS, or the raw
 * `industry` column) to one of the 26 canonical sector names above.
 *
 * IMPORTANT: this is NOT the verbatim NSE 4-tier classification match the
 * UI spec calls for (Component 1) - no canonical NSE sector field is
 * currently stored anywhere in this app (confirmed: `companies.industry` is
 * free text, `sector_guess` is an LLM guess, `SECTOR_GROUPS` is a manually
 * curated peer-grouping label). This keyword table is a deterministic
 * stand-in until real NSE sector/industry data is wired in - never a fuzzy/
 * NLP match, just an explicit alias list, so behaviour stays predictable.
 * Returns null (never a guess) if nothing matches, so callers can fall back
 * to "All ratios" instead of silently mis-tiering a company. */
const SECTOR_ALIASES = [
  [['bank'], 'Banks'],
  [['nbfc', 'housing finance', 'non-banking financial'], 'NBFC'],
  [['insurance', 'life insurance', 'general insurance'], 'Insurance'],
  [['broking', 'asset management', 'amc', 'exchange', 'capital market', 'depository'], 'Capital Markets (Broking/AMC/Exchanges)'],
  [['pharma', 'drug', 'formulation'], 'Pharmaceuticals'],
  [['hospital', 'diagnostic', 'healthcare service'], 'Healthcare Services (Hospitals/Diagnostics)'],
  [['it service', 'information technology', 'software', 'it consulting'], 'Information Technology'],
  [['media', 'entertainment', 'publication', 'broadcasting'], 'Media, Entertainment & Publication'],
  [['metal', 'mining', 'steel', 'iron', 'aluminium', 'copper'], 'Metals & Mining'],
  [['oil', 'gas', 'petroleum', 'consumable fuel', 'refinery'], 'Oil, Gas & Consumable Fuels'],
  [['power', 'electricity', 'utility', 'utilities'], 'Power'],
  [['realty', 'real estate', 'infra & realty', 'infrastructure & realty'], 'Realty'],
  [['retail'], 'Retailing'],
  [['logistics', 'transportation', 'aviation', 'shipping', 'airline'], 'Services (Logistics/Transportation/Aviation)'],
  [['telecom'], 'Telecommunication'],
  [['textile', 'apparel', 'garment'], 'Textiles'],
  [['cement', 'construction material'], 'Construction Materials (Cement)'],
  [['construction', 'infra', 'engineering & construction'], 'Construction'],
  [['auto', 'automobile'], 'Automobile & Auto Components'],
  [['capital good', 'industrial machinery', 'electrical equipment'], 'Capital Goods'],
  [['chemical'], 'Chemicals'],
  [['consumer durable', 'appliance'], 'Consumer Durables'],
  [['consumer service', 'hotel', 'restaurant', 'qsr'], 'Consumer Services'],
  [['fmcg', 'fast moving consumer good', 'consumer staple'], 'Fast Moving Consumer Goods (FMCG)'],
  [['paper', 'forest material'], 'Forest Materials (Paper)'],
  [['diversified', 'conglomerate'], 'Diversified'],
];

export function normalizeSectorLabel(looseLabel) {
  if (!looseLabel || typeof looseLabel !== 'string') return null;
  const l = looseLabel.toLowerCase();
  for (const [keywords, canonical] of SECTOR_ALIASES) {
    if (keywords.some((kw) => l.includes(kw))) return canonical;
  }
  return null;
}
