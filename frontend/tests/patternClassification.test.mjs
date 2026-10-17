import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { PATTERN_REGISTRY } from '../src/lib/patternRegistry.js';
import { PATTERN_CLASSIFICATION, classificationById, classifyEvent, biasText, BIAS } from '../src/lib/patternClassification.js';
import { patternType } from '../src/lib/chartPatterns.js';

const id = patternType;
const ev = (name, extra = {}) => ({ patternType: id(name), pattern: name, kind: 'pattern', ...extra });

// ---------------------------------------------------------------- registry integrity
test('classification covers EXACTLY the registered patterns (names and ids), no orphans either way', () => {
  const reg = new Map(PATTERN_REGISTRY.map((p) => [p.id, p.displayName]));
  for (const [rid, name] of reg) {
    const c = classificationById.get(rid);
    assert.ok(c, `registry pattern "${name}" has no classification`);
    assert.equal(c.displayName, name);
  }
  for (const c of PATTERN_CLASSIFICATION) assert.ok(reg.has(c.id), `classification "${c.displayName}" is not a registered pattern`);
  assert.equal(PATTERN_CLASSIFICATION.length, PATTERN_REGISTRY.length);
  assert.equal(new Set(PATTERN_CLASSIFICATION.map((c) => c.id)).size, PATTERN_CLASSIFICATION.length);
});

test('every pattern from the requested lists is classified as specified', () => {
  const bullish = ['Double Bottom', 'Cup & Handle', 'Flat Base', 'Ascending Base', 'IPO Base', 'High Tight Flag', 'Three Weeks Tight', 'Inverse Head & Shoulders',
    'Triple Bottom', 'Rounding Bottom', 'Cup Base', 'Saucer Base', 'Falling Wedge', 'Ascending Triangle', 'Pocket Pivot', 'Undercut & Rally', 'Shakeout', 'Wyckoff Spring'];
  const bearish = ['Double Top', 'Head & Shoulders', 'Triple Top', 'Rising Wedge', 'Wyckoff Upthrust'];
  const context = ['VCP', 'Flag', 'Pennant', 'Symmetrical Triangle', 'Rectangle', 'Harmonic pattern (Gartley-like)', 'Order Block Retest', 'Order Block Broken'];
  for (const n of bullish) assert.equal(classificationById.get(id(n)).bias, BIAS.BULLISH, n);
  for (const n of bearish) assert.equal(classificationById.get(id(n)).bias, BIAS.BEARISH, n);
  for (const n of context) assert.equal(classificationById.get(id(n)).bias, BIAS.CONTEXT, n);
  // Order blocks are split by side; Descending Triangle (not in the list) is the mirror of Ascending Triangle.
  assert.equal(classificationById.get(id('Bullish Order Block')).bias, BIAS.BULLISH);
  assert.equal(classificationById.get(id('Bearish Order Block')).bias, BIAS.BEARISH);
  assert.equal(classificationById.get(id('Descending Triangle')).bias, BIAS.BEARISH);
  // Documented exception: Rounding Top is conventionally bearish but needs structural confirmation.
  const rt = classificationById.get(id('Rounding Top'));
  assert.equal(rt.bias, BIAS.BEARISH); assert.equal(rt.confirmation, 'structure');
  // Breakout-confirmed patterns say so.
  for (const n of ['Falling Wedge', 'Ascending Triangle', 'Rising Wedge', 'Descending Triangle']) assert.equal(classificationById.get(id(n)).confirmation, 'breakout', n);
});

// ---------------------------------------------------------------- verified against the REAL detector source
test('registry detectorTone matches what the detector source code actually emits', () => {
  const src = ['../src/lib/chartPatterns.js', '../src/lib/higherTimeframePatterns.js'].map((f) => fs.readFileSync(new URL(f, import.meta.url), 'utf8')).join('\n');
  const tones = new Map();
  for (const m of src.matchAll(/mk\('([^']+)',\s*[^,]+,\s*'(pos|neg|neutral)'/g)) {
    if (!tones.has(m[1])) tones.set(m[1], new Set());
    tones.get(m[1]).add(m[2]);
  }
  let checked = 0;
  for (const c of PATTERN_CLASSIFICATION) {
    const seen = tones.get(c.displayName);
    if (!seen) continue;                               // order blocks / ternary tones are covered by their own tests
    checked++;
    if (c.detectorTone === 'by-pole') {
      // Flag emits the up-pole variant through a `label` variable (invisible to the literal regex) and the down-pole variant literally.
      assert.ok([...seen].every((t) => t === 'pos' || t === 'neg'), `${c.displayName} emits a non-directional tone`);
      assert.match(src, /mk\(label, [^,]+, 'pos'/, 'Flag up-pole branch');
      assert.match(src, /mk\('Flag', [^,]+, 'neg'/, 'Flag down-pole branch');
    }
    else assert.deepEqual([...seen], [c.detectorTone], `${c.displayName}: registry says ${c.detectorTone}, detector emits ${[...seen]}`);
  }
  assert.ok(checked >= 24, `only ${checked} patterns were cross-checked against detector source`);
  // Bias vs detector direction: a fixed bullish/bearish bias may only differ from a directional detector tone by being absent (neutral).
  for (const c of PATTERN_CLASSIFICATION.filter((x) => x.bias === 'bullish')) assert.ok(['pos', 'neutral'].includes(c.detectorTone), c.displayName);
  for (const c of PATTERN_CLASSIFICATION.filter((x) => x.bias === 'bearish')) assert.ok(['neg', 'neutral'].includes(c.detectorTone), c.displayName);
});

// ---------------------------------------------------------------- event-level classification (subtypes)
test('fixed-bias patterns keep their bias', () => {
  assert.equal(classifyEvent(ev('Double Bottom', { tone: 'pos' })).bias, 'bullish');
  assert.equal(classifyEvent(ev('Head & Shoulders', { tone: 'neg' })).bias, 'bearish');
  assert.equal(classifyEvent(ev('Flat Base', { tone: 'neutral' })).bias, 'bullish');          // detector is neutral, textbook bias is bullish
});

test('Flag and Pennant: bullish / bearish SUBTYPE comes from the detector pole direction; no pole direction = unconfirmed', () => {
  for (const n of ['Flag', 'Pennant']) {
    assert.equal(classifyEvent(ev(n, { tone: 'pos' })).bias, 'bullish', `${n} up-pole`);
    assert.equal(classifyEvent(ev(n, { tone: 'neg' })).bias, 'bearish', `${n} down-pole`);
    const u = classifyEvent(ev(n, { tone: 'neutral' }));
    assert.equal(u.bias, 'context'); assert.match(u.basis, /unconfirmed/);
  }
});

test('Order Block Retest takes the zone side; Order Block Broken never claims a direction', () => {
  assert.equal(classifyEvent(ev('Order Block Retest', { side: 'bull' })).bias, 'bullish');
  assert.equal(classifyEvent(ev('Order Block Retest', { side: 'bear' })).bias, 'bearish');
  assert.equal(classifyEvent(ev('Order Block Retest', {})).bias, 'context');
  assert.equal(classifyEvent(ev('Order Block Broken', { tone: 'neutral', side: 'bull' })).bias, 'context');
});

test('VCP / Symmetrical Triangle / Rectangle / Harmonic are never forced to a direction', () => {
  for (const n of ['VCP', 'Symmetrical Triangle', 'Rectangle', 'Harmonic pattern (Gartley-like)']) {
    for (const tone of ['pos', 'neg', 'neutral', undefined]) {
      const r = classifyEvent(ev(n, { tone }));
      assert.equal(r.bias, 'context', `${n} tone=${tone}`);
    }
  }
  assert.match(classifyEvent(ev('VCP', { tone: 'pos' })).basis, /breakout/);
  assert.match(biasText(classifyEvent(ev('Rectangle'))), /direction unconfirmed/);
});

test('contradicting detector direction is reported, not resolved; unknown patterns are Unknown', () => {
  const c = classifyEvent(ev('Double Top', { tone: 'pos' }));
  assert.equal(c.bias, 'context'); assert.equal(c.conflict, true);
  assert.equal(classifyEvent(ev('Some Future Pattern')).bias, 'unknown');
  assert.equal(classifyEvent(null).bias, 'unknown');
  assert.equal(classifyEvent({}).bias, 'unknown');
});

test('bias text mentions confirmation requirements', () => {
  assert.equal(biasText(classifyEvent(ev('Double Bottom'))), 'Bullish bias');
  assert.match(biasText(classifyEvent(ev('Ascending Triangle', { tone: 'pos' }))), /needs confirmation/);
  assert.match(biasText(classifyEvent(ev('Rounding Top', { tone: 'neg' }))), /needs confirmation/);
});
