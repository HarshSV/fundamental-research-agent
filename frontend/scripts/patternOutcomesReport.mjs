// Real-data outcome report for the pattern engine. Runs the SAME detectors and outcome code the app uses over a dumped
// OHLCV folder (intraday.json, daily.json, weekly.json - see scripts/dumpAuditData.py) and prints, per pattern, how many
// formations were found and what actually happened after them. Nothing here is synthetic.
//
//   node scripts/patternOutcomesReport.mjs .audit-data/TCS
//   AUDIT_NOW=<unix seconds> node ...        (pin "now" for reproducible pending/not-evaluable counts)
import fs from 'fs';
import path from 'path';
import { PATTERN_REGISTRY } from '../src/lib/patternRegistry.js';
import { replayDayEvents } from '../src/lib/eventReplay.js';
import { fullHistoryEvents, toOccurrences, statsForPattern, intradaySeries } from '../src/lib/patternHistory.js';
import { biasText } from '../src/lib/patternClassification.js';
import { DEFAULT_CONFIG } from '../src/lib/patternOutcomes.js';
import { istDate } from '../src/lib/marketTime.js';

const dir = process.argv[2] || '.audit-data/TCS';
const read = (f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
const symbol = path.basename(dir);
const intraday = read('intraday.json');
const daily = read('daily.json');
const weekly = read('weekly.json');
const nowSec = process.env.AUDIT_NOW ? Number(process.env.AUDIT_NOW) : Date.now() / 1000;
const pct = (x) => (x == null ? '  -  ' : `${(x * 100).toFixed(1)}%`.padStart(6));
const cfg = DEFAULT_CONFIG;

console.log(`PATTERN OUTCOME REPORT - ${symbol}`);
console.log(`daily bars ${daily.length} (${istDate(daily[0].time)}..${istDate(daily[daily.length - 1].time)}), weekly ${weekly.length}, intraday 5m ${intraday.length}`);
console.log(`outcome = close[ref+h]/close[ref]-1 ; Flat band = max(floor, ${cfg.flat.k} x sigma${cfg.flat.volLookback} x sqrt(h)) ; floors ${JSON.stringify(cfg.flat.floor)} ; horizons ${JSON.stringify(cfg.horizons)}`);
console.log('Rates use INDEPENDENT (non-overlapping) completed observations only. "base" = the same rule applied to every bar of the series.\n');

let t0 = Date.now();
const hist = fullHistoryEvents({ dailyBars: daily, weeklyBars: weekly, nowSec });
console.log(`full-history daily+weekly detection: ${Date.now() - t0} ms (${hist.daily.events.length} daily and ${hist.weekly.events.length} weekly raw events)\n`);

// The bar-by-bar replay is O(n^2); the CLI replays the most recent INTRADAY_BARS bars (default 750 = 10 sessions) and says so.
const nIntra = Number(process.env.INTRADAY_BARS || 750);
const intradayWin = intraday.slice(-nIntra);
console.log(`intraday occurrences: replay of the last ${intradayWin.length} five-minute bars (${istDate(intradayWin[0].time)}..${istDate(intradayWin[intradayWin.length - 1].time)})
`);
const intradayEvents = replayDayEvents(intradayWin, { patternsOnly: true, meta: { includeOptIn: true } });
const iSeries = intradaySeries(intradayWin, cfg, nowSec);
const sources = {
  daily: { series: hist.daily.series, events: hist.daily.events },
  weekly: { series: hist.weekly.series, events: hist.weekly.events },
  intraday: { series: iSeries, events: intradayEvents },
};
const occ = {};
for (const [tf, s] of Object.entries(sources)) occ[tf] = toOccurrences(s.events, { symbol, timeframe: tf, series: s.series, nowSec });

const header = ['pattern', 'tf', 'bias(conventional)', 'forms'];
for (const h of cfg.horizons.daily) header.push(`h=${h}: eval(ind) +/-/flat | pos rate | base | pend/n.a.`);
console.log(header.join('  |  '));
for (const p of PATTERN_REGISTRY) {
  const o = occ[p.timeframe].filter((x) => x.patternType === p.id);
  const st = statsForPattern(occ[p.timeframe], { patternId: p.id, timeframe: p.timeframe, series: sources[p.timeframe].series, nowSec });
  const cls = o[0] ? biasText(o[0].classification) : '-';
  const cells = st.horizons.map((hz) => {
    const i = hz.independent;
    return `${String(i.evaluable).padStart(3)} ${String(i.positive)}/${String(i.negative)}/${String(i.flat)} | ${pct(i.positiveRate)} | ${pct(hz.base.positiveRate)} | ${hz.all.pending}/${hz.all.notEvaluable}${hz.smallSample ? ' (small sample)' : ''}`;
  });
  console.log([p.displayName.padEnd(28), p.timeframe.padEnd(8), cls.padEnd(34), String(o.length).padStart(3), ...cells].join('  |  '));
}
