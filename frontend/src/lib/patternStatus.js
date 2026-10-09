// Chip state for one registry pattern. Four distinct states (never conflated):
//   found        supported, >=1 detection in the loaded period  (count > 0)
//   zero         supported, detector ran, 0 detections          (still clickable)
//   needs-data   detector exists but the required timeframe's history is
//                missing / too short                            (clickable, explains why)
//   unavailable  no detector implemented                        (disabled)
// plus `loading` while daily/weekly history is still being fetched.
//
// ctx: { counts: Map<id, n>, barCounts: {intraday, daily, weekly},
//        history: { daily: 'ok'|'loading'|'failed', weekly: ... } }
export function patternStatus(entry, ctx) {
  if (!entry.enabled) return { state: 'unavailable', reason: entry.availabilityReason || 'Detector not available yet' };
  const tf = entry.timeframe;
  if (tf !== 'intraday') {
    const h = ctx.history?.[tf];
    if (h === 'loading') return { state: 'loading', reason: `Loading ${tf} history...` };
    if (h !== 'ok') return { state: 'needs-data', reason: `Requires ${tf} history` };
  }
  const have = ctx.barCounts?.[tf] ?? 0;
  if (have < entry.minBars) {
    return { state: 'needs-data', reason: `Requires ${tf} history (${have} of ${entry.minBars} bars loaded)` };
  }
  const count = ctx.counts?.get(entry.id) || 0;
  return { state: count > 0 ? 'found' : 'zero', count, reason: null };
}
