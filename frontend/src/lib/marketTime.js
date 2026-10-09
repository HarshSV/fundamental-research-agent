// Single place for market-time conventions.
//
// Canonical representation: every candle/event time is unix SECONDS (a UTC
// instant) - exactly what the provider/backend sends. Nothing is ever
// converted on the way in. Conversion to Asia/Kolkata happens only here, at
// the display boundary, so no component uses browser-local time or raw UTC.

export const IST = 'Asia/Kolkata';
const IST_OFFSET_SEC = 5.5 * 3600;

export const istDate = (t) => new Date(t * 1000).toLocaleDateString('en-CA', { timeZone: IST }); // YYYY-MM-DD
export const todayISO = () => istDate(Date.now() / 1000);

// "03:15 PM" (12h, upper-case) - or 24h for chart axes via { hour12: false }.
export const istClock = (t, opts) => {
  const s = new Date(t * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: IST, ...opts });
  return s.toUpperCase();
};
export const fmtTime = (t) => istClock(t);
export const fmtDate = (t) =>
  new Date(t * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: IST });
export const fmtDayMonth = (t) =>
  new Date(t * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: IST });

// Unix seconds of a given IST wall-clock moment on a YYYY-MM-DD date.
export const istInstant = (dateStr, hour = 0, minute = 0) =>
  Date.parse(`${dateStr}T00:00:00Z`) / 1000 - IST_OFFSET_SEC + hour * 3600 + minute * 60;

export const MARKET_CLOSE_HM = [15, 30];

// Has the regular session of `dateStr` (IST) finished as of `nowSec`?
export const sessionComplete = (dateStr, nowSec = Date.now() / 1000) =>
  nowSec >= istInstant(dateStr, MARKET_CLOSE_HM[0], MARKET_CLOSE_HM[1]);
