import test from 'node:test';
import assert from 'node:assert/strict';
import { CATEGORY_ORDER, DEFAULT_VISIBLE_CATEGORIES, groupFundamentalRatios } from '../src/lib/ratioCategories.js';

const SIZES = [9, 7, 16, 7, 6, 12, 8, 3];
const rows = () => CATEGORY_ORDER.flatMap((c, ci) =>
  Array.from({ length: SIZES[ci] }, (_, i) => ({ ratio_key: `${ci}_${i}`, category: c })));

test('first view = Balance Sheet + P&L = 16; more = 52; 68 total, none duplicated', () => {
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
  assert.deepEqual(groupFundamentalRatios(null), { primary: [], more: [] });
});
