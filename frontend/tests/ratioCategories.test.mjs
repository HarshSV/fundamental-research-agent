import test from 'node:test';
import assert from 'node:assert/strict';
import { CATEGORY_ORDER, DEFAULT_VISIBLE_CATEGORIES, groupFundamentalRatios } from '../src/lib/ratioCategories.js';

const SIZES = [9, 7, 16, 7, 6, 12, 8, 3];
const rows = () => CATEGORY_ORDER.flatMap((c, ci) =>
  Array.from({ length: SIZES[ci] }, (_, i) => ({ ratio_key: `${ci}_${i}`, category: c })));

test('first view = Balance Sheet + P&L = 16; more = 52; 68 total, none duplicated (no priority rows)', () => {
  const { primary, more } = groupFundamentalRatios(rows().reverse()); // input order must not matter for category order
  assert.deepEqual(primary.map((g) => g.category), DEFAULT_VISIBLE_CATEGORIES);
  assert.deepEqual(primary.map((g) => g.items.length), [9, 7]);
  assert.equal(primary.reduce((n, g) => n + g.items.length, 0), 16);
  assert.deepEqual(more.map((g) => g.category), CATEGORY_ORDER.slice(2));
  assert.equal(more.reduce((n, g) => n + g.items.length, 0), 52);
  const keys = [...primary, ...more].flatMap((g) => g.items.map((r) => r.ratio_key));
  assert.equal(new Set(keys).size, 68);
});

test('API order inside a category is preserved', () => {
  const r = [{ ratio_key: 'b', category: 'P&L' }, { ratio_key: 'a', category: 'P&L' }];
  assert.deepEqual(groupFundamentalRatios(r).primary[0].items.map((x) => x.ratio_key), ['b', 'a']);
});

test('unknown category is kept (last, in "more"), never dropped', () => {
  const { more } = groupFundamentalRatios([{ ratio_key: 'x', category: 'Mystery' }]);
  assert.equal(more[0].items[0].ratio_key, 'x');
});

test('empty/missing input is safe', () => {
  assert.deepEqual(groupFundamentalRatios(null), { priority: [], primary: [], more: [] });
});

test('display_priority rows come out first, in priority order, and are removed from their category (each ratio once)', () => {
  const all = rows().map((r, i) => ({ ...r, ratio_key: `k${i}` }));
  // give 13 of them a priority in scrambled input order
  const picks = [40, 3, 30, 10, 55, 20, 45, 5, 60, 25, 35, 15, 50];
  picks.forEach((idx, n) => { all[idx].display_priority = n + 1; });
  const g = groupFundamentalRatios([...all].reverse());
  assert.deepEqual(g.priority.map((r) => r.display_priority), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]);
  assert.deepEqual(g.priority.map((r) => r.ratio_key), picks.map((i) => `k${i}`));
  const rest = [...g.primary, ...g.more].flatMap((x) => x.items);
  assert.equal(rest.length, 55);
  const keys = [...g.priority, ...rest].map((r) => r.ratio_key);
  assert.equal(new Set(keys).size, 68);                       // none lost, none duplicated
  assert.ok(rest.every((r) => !r.display_priority));
});

test('rows with a null / missing display_priority are ordinary category rows', () => {
  const g = groupFundamentalRatios([{ ratio_key: 'a', category: 'P&L', display_priority: null }, { ratio_key: 'b', category: 'P&L' }]);
  assert.equal(g.priority.length, 0);
  assert.equal(g.primary[0].items.length, 2);
});
