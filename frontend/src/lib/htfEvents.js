// Runs the daily / weekly detectors and places their detections on the loaded
// INTRADAY chart. Detection happens on the correct source timeframe (daily or
// completed-weekly bars); the live/day chart only receives the result,
// positioned on a real intraday bar of the session it completed on.
//
// Dataset rule (live and history alike): a detection is only returned if the
// session it was formed/confirmed on is inside the loaded intraday window, and
// each detector only ever sees bars up to that session - so a loaded historical
// day never shows (or leaks) later daily/weekly information.

import { runDetectors } from './patternRegistry.js';
import { stampEvent } from './eventModel.js';
import { istDate, istInstant, sessionComplete } from './marketTime.js';

const LISTING_KNOWN_BELOW = 1200; // daily bars requested = ~5y; fewer means the data starts at the listing

// Drop the trailing bar if its session has not finished (partial daily bar).
export function completedDaily(bars, nowSec) {
  if (!bars.length) return bars;
  const last = bars[bars.length - 1];
  return sessionComplete(istDate(last.time), nowSec) ? bars : bars.slice(0, -1);
}

// A weekly bar (time = Monday 00:00 IST) is complete once Friday 15:30 IST has passed.
export function completedWeekly(bars, nowSec) {
  if (!bars.length) return bars;
  const last = bars[bars.length - 1];
  const fridayClose = istInstant(istDate(last.time), 15, 30) + 4 * 86400;
  return nowSec >= fridayClose ? bars : bars.slice(0, -1);
}

function intradayIndex(intradayCandles) {
  const byDate = new Map();
  intradayCandles.forEach((c, i) => {
    const d = istDate(c.time);
    const cur = byDate.get(d);
    if (!cur) byDate.set(d, { first: i, last: i });
    else cur.last = i;
  });
  return { byDate, dates: [...byDate.keys()].sort() };
}

function place(e, srcBars, formDate, evalDate, idx, intradayCandles) {
  const D = idx.byDate.has(formDate) ? formDate : idx.byDate.has(evalDate) ? evalDate : null;
  if (!D) return null;
  const { last } = idx.byDate.get(D);
  const startDate = istDate(srcBars[Math.max(0, e.startIndex)].time);
  const startKey = idx.dates.find((d) => d >= startDate);
  const startIndex = startKey ? idx.byDate.get(startKey).first : idx.byDate.get(D).first;
  return {
    ...e,
    timeframe: e.timeframe,
    formedDate: D,
    formedAt: istInstant(formDate, 15, 30),
    confirmedAt: istInstant(evalDate, 15, 30),
    barIndex: last,
    startIndex: Math.min(startIndex, last),
    endIndex: last,
    time: intradayCandles[last].time, // primary market time = a real intraday bar of that session
  };
}

export function computeHigherTimeframeEvents({ dailyBars, weeklyBars, intradayCandles, nowSec = Date.now() / 1000 }) {
  if (!intradayCandles || !intradayCandles.length) return [];
  const idx = intradayIndex(intradayCandles);
  const firstDate = idx.dates[0];
  const lastDate = idx.dates[idx.dates.length - 1];
  const out = [];
  const seen = new Set();
  const push = (e) => {
    if (!e) return;
    const key = `${e.patternType}|${e.formedAt}|${e.text}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(e);
  };

  if (dailyBars && dailyBars.length) {
    const daily = completedDaily(dailyBars, nowSec);
    const meta = { listingKnown: dailyBars.length < LISTING_KNOWN_BELOW };
    for (let i = 0; i < daily.length; i++) {
      const evalDate = istDate(daily[i].time);
      if (evalDate < firstDate || evalDate > lastDate) continue;
      const window = daily.slice(0, i + 1);
      for (const ev of runDetectors('daily', window, meta)) {
        const formDate = istDate(window[Math.min(ev.endIndex, window.length - 1)].time);
        const stamped = stampEvent(ev, window[window.length - 1]);
        push(place(stamped, window, formDate, evalDate, idx, intradayCandles));
      }
    }
  }

  if (weeklyBars && weeklyBars.length && dailyBars && dailyBars.length) {
    const weekly = completedWeekly(weeklyBars, nowSec);
    // Last trading date inside each weekly bar's Mon-Sun span.
    const dailyDates = dailyBars.map((b) => ({ t: b.time, d: istDate(b.time) }));
    for (let j = 0; j < weekly.length; j++) {
      const wStart = weekly[j].time;
      const inWeek = dailyDates.filter((x) => x.t >= wStart && x.t < wStart + 7 * 86400);
      if (!inWeek.length) continue;
      const weekEnd = inWeek[inWeek.length - 1].d;
      if (weekEnd < firstDate || weekEnd > lastDate) continue;
      const window = weekly.slice(0, j + 1);
      for (const ev of runDetectors('weekly', window)) {
        push(place(stampEvent(ev, window[window.length - 1]), window, weekEnd, weekEnd, idx, intradayCandles));
      }
    }
  }
  return out;
}
