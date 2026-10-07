// Display grouping for the Fundamental Ratios tab. The classification itself
// (which category each ratio belongs to) lives ONLY in the backend registry
// (tools/fundamental_ratio_registry.py -> `category`, applied to every row by
// get_fundamental_results); this module just orders and splits what the API
// returns. CATEGORY_ORDER must equal the registry's CATEGORY_ORDER (a backend
// test enforces it).
export const CATEGORY_ORDER = [
  'Balance Sheet', 'P&L', 'P&L + Balance Sheet', 'Cash Flow', 'Multi-source / Derived',
  'Market / Valuation', 'Banking-specific', 'Market / Shareholding',
];
export const DEFAULT_VISIBLE_CATEGORIES = ['Balance Sheet', 'P&L'];

// -> { primary: [{category, items}], more: [{category, items}] }
// Category order is fixed; within a category the API order (Sr No) is kept.
// Unknown categories (should not occur) go last in "more" rather than vanish.
export function groupFundamentalRatios(rows) {
  const by = {};
  for (const r of rows || []) (by[r.category] = by[r.category] || []).push(r);
  const known = CATEGORY_ORDER.filter((c) => by[c]).map((c) => ({ category: c, items: by[c] }));
  const extra = Object.keys(by).filter((c) => !CATEGORY_ORDER.includes(c)).map((c) => ({ category: c, items: by[c] }));
  const all = [...known, ...extra];
  return {
    primary: all.filter((g) => DEFAULT_VISIBLE_CATEGORIES.includes(g.category)),
    more: all.filter((g) => !DEFAULT_VISIBLE_CATEGORIES.includes(g.category)),
  };
}
