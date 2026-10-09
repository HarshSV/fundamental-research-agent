// Pattern audit: for every registry pattern, is it implemented, which
// timeframe feeds it, is there enough data, and how many detections does the
// real data produce. Reads JSON dumped by scripts/dumpAuditData.py:
//   node scripts/auditPatterns.mjs .audit-data/TCS
// (expects intraday.json, daily.json, weekly.json, day.json in that folder)
import fs from 'fs';
import path from 'path';
import { PATTERN_REGISTRY } from '../src/lib/patternRegistry.js';
import { patternStatus } from '../src/lib/patternStatus.js';
import { replayDayEvents } from '../src/lib/eventReplay.js';
import { computeHigherTimeframeEvents } from '../src/lib/htfEvents.js';
import { collapseRuns } from '../src/lib/patternCatalog.js';
import { istDate, istClock, fmtDate } from '../src/lib/marketTime.js';

const dir = process.argv[2] || '.audit-data/TCS';
const read = (f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
const intraday = read('intraday.json');
const daily = read('daily.json');
const weekly = read('weekly.json');
const day = read('day.json');
const NOW = process.env.AUDIT_NOW ? Number(process.env.AUDIT_NOW) : Date.now() / 1000;

const stamp = (t) => `${fmtDate(t)} ${istClock(t)}`;
const last = (a) => a[a.length - 1];
console.log('--- last bars (IST) ---');
console.log('last raw 5m candle   :', stamp(last(intraday).time), 'close', last(intraday).close);
console.log('last daily candle    :', istDate(last(daily).time), 'close', last(daily).close);
console.log('last weekly candle   :', 'week of', istDate(last(weekly).time), 'close', last(weekly).close);

function run(label, candles, sessionStart = 0, all = candles) {
  const intradayEv = replayDayEvents(all, { patternsOnly: true, sessionStart });
  const htf = computeHigherTimeframeEvents({ dailyBars: daily, weeklyBars: weekly, intradayCandles: candles, nowSec: NOW });
  const events = [...intradayEv, ...htf];
  const formations = collapseRuns(events);
  const countsRaw = new Map(), countsF = new Map();
  events.forEach((e) => countsRaw.set(e.patternType, (countsRaw.get(e.patternType) || 0) + 1));
  formations.forEach((e) => countsF.set(e.patternType, (countsF.get(e.patternType) || 0) + 1));
  const ctx = {
    counts: countsF,
    barCounts: { intraday: all.length, daily: daily.length, weekly: weekly.length },
    history: { daily: 'ok', weekly: 'ok' },
  };
  console.log(`\n=== ${label}: ${candles.length} displayed bars, ${events.length} pattern events ===`);
  console.log('pattern'.padEnd(34), 'tf'.padEnd(9), 'minBars'.padEnd(8), 'have'.padEnd(6), 'raw'.padEnd(6), 'formations'.padEnd(11), 'state');
  for (const p of PATTERN_REGISTRY) {
    const st = patternStatus(p, ctx);
    console.log(
      p.displayName.padEnd(34), p.timeframe.padEnd(9), String(p.minBars).padEnd(8),
      String(ctx.barCounts[p.timeframe]).padEnd(6), String(countsRaw.get(p.id) || 0).padEnd(6),
      String(countsF.get(p.id) || 0).padEnd(11), st.state + (st.reason ? ` (${st.reason})` : ''),
    );
  }
  const emitted = [...countsRaw.keys()].filter((k) => !PATTERN_REGISTRY.some((p) => p.id === k));
  console.log('event types NOT in registry:', emitted.length ? emitted.join(', ') : 'none');
  return events;
}

const liveEv = run('LIVE 5m window', intraday);
const dayWarm = day.warmup || [];
run(`HISTORY ${istDate(day.candles[0].time)} session`, day.candles, dayWarm.length, [...dayWarm, ...day.candles]);
void liveEv;
