// Explicit timestamp model for chart / "What's happening" events.
//
// Every field is unix seconds (UTC instant); IST conversion happens only in
// marketTime.js at display time.
//
//   time         PRIMARY market time of the event. This is what the feed shows,
//                what sorting uses and what the chart marker sits on:
//                  candle signal      -> that candle's time
//                  swing structure    -> the pivot candle's time (not the later
//                                        bar that confirmed it)
//                  intraday pattern   -> the bar where the structure completed
//                  daily/weekly       -> the last intraday bar of the session
//                                        the pattern completed on
//   candleTime   the candle the detectors were evaluating when it fired
//   formedAt     when the structure completed (same market clock as `time`; for
//                daily/weekly patterns the close of the session it completed on)
//   confirmedAt  the bar at which enough data existed for the detector to
//                report it (>= formedAt)
//   detectedAt   when this engine produced the result (processing time; never
//                used for display or ordering)
//   receivedAt   live feed only: when the poll that delivered it arrived
//                (never used for display or ordering)
//
// Not every event needs every field; absent ones are simply undefined.

export function makeEventId(e) {
  return `${e.timeframe || 'intraday'}|${e.patternType || e.kind}|${e.formedAt ?? e.time}|${e.text}`;
}

export function stampEvent(e, evalBar, nowSec = Date.now() / 1000) {
  const stamped = {
    ...e,
    candleTime: e.candleTime ?? evalBar.time,
    formedAt: e.formedAt ?? e.time,
    confirmedAt: e.confirmedAt ?? evalBar.time,
    detectedAt: nowSec,
  };
  return { ...stamped, id: e.id ?? makeEventId(stamped) };
}
