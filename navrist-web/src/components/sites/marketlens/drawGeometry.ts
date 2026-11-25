/** Geometry for the drawing tools (from the HeatCharting project). Pixel math only: no chart, no DOM. */
export interface Px {
  x: number;
  y: number;
}

export function distToSegment(p: Px, a: Px, b: Px): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

/** Distance to the half-line that starts at a and passes through b, going on forever. */
export function distToRay(p: Px, a: Px, b: Px): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = Math.max(0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2);
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

export function inRect(p: Px, a: Px, b: Px, pad = 0): boolean {
  return p.x >= Math.min(a.x, b.x) - pad && p.x <= Math.max(a.x, b.x) + pad && p.y >= Math.min(a.y, b.y) - pad && p.y <= Math.max(a.y, b.y) + pad;
}

export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

/** Retracement prices: 0 sits at the second point (where the move ended) and 1 at the first (where it began). */
export function fibPrices(p1: number, p2: number): { level: number; price: number }[] {
  return FIB_LEVELS.map((level) => ({ level, price: p2 - (p2 - p1) * level }));
}

export interface Measure {
  dPrice: number;
  pct: number | null; // null when the starting price is not positive
  bars: number;
  seconds: number;
}

export function measure(a: { t: number; p: number }, b: { t: number; p: number }, barSec: number): Measure {
  return { dPrice: b.p - a.p, pct: a.p > 0 ? ((b.p - a.p) / a.p) * 100 : null, bars: Math.round((b.t - a.t) / barSec), seconds: b.t - a.t };
}

/** "2d 3h", "45m", "3h 15m": a duration for labels. */
export function duration(seconds: number): string {
  const s = Math.abs(Math.round(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return h ? `${d}d ${h}h` : `${d}d`;
  if (h) return m ? `${h}h ${m}m` : `${h}h`;
  return `${m}m`;
}

/** Snap a price to the closest of the given candidates (open, high, low, close) when it is within `tolerance` price units, else leave it. */
export function snapPrice(price: number, candidates: number[], tolerance: number): number {
  let best = price;
  let d = tolerance;
  for (const c of candidates) {
    const e = Math.abs(c - price);
    if (e <= d) (d = e), (best = c);
  }
  return best;
}
