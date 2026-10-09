// Shared bits of the company-search UI (header search box + landing hero).
// The matching itself lives on the backend (tools/company_search.py); this only
// decides how results are labelled and what Enter / "Analyze" is allowed to open.

// "NSE / BSE", "BSE", or "Uploaded" for a company with no exchange listing on record.
export const exchangeLabel = (m) => (m && m.exchanges && m.exchanges.length ? m.exchanges.join(' / ') : 'Uploaded');

// Second line of a result row: "TCS · NSE / BSE" (+ the BSE scrip code when we have one).
export const detailLine = (m) =>
  [m.symbol, exchangeLabel(m), m.exchanges && m.exchanges.includes('BSE') && m.bse_code ? `BSE ${m.bse_code}` : null]
    .filter(Boolean)
    .join(' · ');

// What may Enter / Analyze open for a fresh result list? The top hit, unless it is only a
// typo-tier (fuzzy) suggestion - those must be picked from the dropdown. Never raw text.
export function chooseCompany(results) {
  const top = results && results[0];
  return top && top.match !== 'fuzzy' ? top : null;
}

export const NO_MATCH_TEXT = 'No matching company found';
