// Classic chart-pattern detection over an OHLCV candle series (ascending by
// time, same shape as technicalAnalysis.js). Company-agnostic: works off
// raw swing-point geometry only, no per-ticker branching.
//
// Every pattern here is fundamentally a subjective geometric read - even
// human chartists disagree on where a Cup & Handle starts or whether a
// Head & Shoulders is "real" until it's already played out. Per this
// project's rule (an inconclusive/uncertain read must never be dressed up
// as a confident fact), every hit below carries an explicit confidence
// tier (High/Medium/Low) computed from how well the actual geometry fits
// the textbook definition - never a flat "Cup & Handle detected" claim.
// Confidence is a fit-quality signal for the user to weigh, not a
// probability the pattern will play out.

import { swingPoints } from './technicalAnalysis.js';

export const pct = (a, b) => Math.abs(a - b) / ((a + b) / 2);

function tierFromScore(score) {
  // score in [0,1]: how closely the geometry matches the textbook shape.
  if (score >= 0.75) return 'High';
  if (score >= 0.5) return 'Medium';
  return 'Low';
}

// `loc` carries the detector's real location data so the chart can mark the
// exact occurrence: { barIndex, startIndex, endIndex, price, rangeLow, rangeHigh }.
// Indexes refer to the candle array handed to detectChartPatterns (replay
// windows are prefixes of the full array, so they stay valid). `confidence`
// is kept on the event but is deliberately not shown in the UI.
export function patternType(name) {
  return name.toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

export function mk(name, time, tone, score, note, loc) {
  return {
    time, kind: 'pattern', pattern: name, patternType: patternType(name), tone,
    confidence: tierFromScore(score), text: `${name}${note ? ` - ${note}` : ''}`,
    ...(loc || {}),
  };
}

function rangeOf(candles, a, b) {
  const w = candles.slice(a, b + 1);
  return { rangeLow: Math.min(...w.map((c) => c.low)), rangeHigh: Math.max(...w.map((c) => c.high)) };
}
export function locOf(candles, startIndex, endIndex, barIndex, price) {
  return { barIndex, startIndex, endIndex, price, ...rangeOf(candles, startIndex, endIndex) };
}

// --- Double Top / Double Bottom --------------------------------------------
function doubleTopBottom(candles, highs, lows) {
  const out = [];
  const last = candles.length - 1;
  if (highs.length >= 2) {
    const [h1, h2] = highs.slice(-2);
    const spacing = h2.index - h1.index;
    if (spacing >= 5 && spacing <= 60 && h2.index >= last - 3) {
      const similarity = 1 - pct(h1.price, h2.price);
      if (similarity > 0.97) {
        const troughBetween = Math.min(...candles.slice(h1.index, h2.index + 1).map((c) => c.low));
        const depth = pct(troughBetween, (h1.price + h2.price) / 2);
        const score = Math.min(1, similarity * 0.6 + Math.min(depth / 0.05, 1) * 0.4);
        out.push(mk('Double Top', candles[h2.index].time, 'neg', score, `peaks ${h1.price.toFixed(2)} / ${h2.price.toFixed(2)}`, locOf(candles, h1.index, h2.index, h2.index, h2.price)));
      }
    }
  }
  if (lows.length >= 2) {
    const [l1, l2] = lows.slice(-2);
    const spacing = l2.index - l1.index;
    if (spacing >= 5 && spacing <= 60 && l2.index >= last - 3) {
      const similarity = 1 - pct(l1.price, l2.price);
      if (similarity > 0.97) {
        const peakBetween = Math.max(...candles.slice(l1.index, l2.index + 1).map((c) => c.high));
        const height = pct(peakBetween, (l1.price + l2.price) / 2);
        const score = Math.min(1, similarity * 0.6 + Math.min(height / 0.05, 1) * 0.4);
        out.push(mk('Double Bottom', candles[l2.index].time, 'pos', score, `troughs ${l1.price.toFixed(2)} / ${l2.price.toFixed(2)}`, locOf(candles, l1.index, l2.index, l2.index, l2.price)));
      }
    }
  }
  return out;
}

// --- Head & Shoulders / Inverse H&S ----------------------------------------
function headAndShoulders(candles, highs, lows) {
  const out = [];
  const last = candles.length - 1;
  if (highs.length >= 3) {
    const [ls, head, rs] = highs.slice(-3);
    if (rs.index >= last - 3) {
      const shoulderSim = 1 - pct(ls.price, rs.price);
      const headTaller = head.price > ls.price && head.price > rs.price;
      if (headTaller && shoulderSim > 0.9) {
        const headDominance = (head.price - Math.max(ls.price, rs.price)) / head.price;
        const score = Math.min(1, shoulderSim * 0.5 + Math.min(headDominance / 0.02, 1) * 0.5);
        out.push(mk('Head & Shoulders', candles[rs.index].time, 'neg', score, `shoulders ${ls.price.toFixed(2)}/${rs.price.toFixed(2)}, head ${head.price.toFixed(2)}`, locOf(candles, ls.index, rs.index, rs.index, rs.price)));
      }
    }
  }
  if (lows.length >= 3) {
    const [ls, head, rs] = lows.slice(-3);
    if (rs.index >= last - 3) {
      const shoulderSim = 1 - pct(ls.price, rs.price);
      const headDeeper = head.price < ls.price && head.price < rs.price;
      if (headDeeper && shoulderSim > 0.9) {
        const headDominance = (Math.min(ls.price, rs.price) - head.price) / head.price;
        const score = Math.min(1, shoulderSim * 0.5 + Math.min(headDominance / 0.02, 1) * 0.5);
        out.push(mk('Inverse Head & Shoulders', candles[rs.index].time, 'pos', score, `shoulders ${ls.price.toFixed(2)}/${rs.price.toFixed(2)}, head ${head.price.toFixed(2)}`, locOf(candles, ls.index, rs.index, rs.index, rs.price)));
      }
    }
  }
  return out;
}

// --- Triangles (Ascending / Symmetrical) + Wedges + Rectangle -------------
// Fits a line through the last 3+ swing highs and the last 3+ swing lows,
// classifies by the slopes' signs/magnitudes relative to each other.
export function linRegSlope(points) {
  const n = points.length;
  const sx = points.reduce((a, p) => a + p.index, 0);
  const sy = points.reduce((a, p) => a + p.price, 0);
  const sxy = points.reduce((a, p) => a + p.index * p.price, 0);
  const sxx = points.reduce((a, p) => a + p.index * p.index, 0);
  const denom = n * sxx - sx * sx;
  if (denom === 0) return 0;
  return (n * sxy - sx * sy) / denom;
}

function trianglesAndWedges(candles, highs, lows) {
  const out = [];
  const last = candles.length - 1;
  if (highs.length < 3 || lows.length < 3) return out;
  const recentHighs = highs.slice(-4);
  const recentLows = lows.slice(-4);
  if (recentHighs[recentHighs.length - 1].index < last - 5 && recentLows[recentLows.length - 1].index < last - 5) return out;

  const avgPrice = candles[last].close;
  const highSlope = linRegSlope(recentHighs) / avgPrice;
  const lowSlope = linRegSlope(recentLows) / avgPrice;
  const flatTol = 0.0008; // near-zero slope, normalised by price
  const t = candles[last].time;
  const startIndex = Math.min(recentHighs[0].index, recentLows[0].index);
  const loc = locOf(candles, startIndex, last, last, candles[last].close);

  const highFlat = Math.abs(highSlope) < flatTol;
  const lowFlat = Math.abs(lowSlope) < flatTol;
  const converging = highSlope < -flatTol && lowSlope > flatTol;
  const bothRising = highSlope > flatTol && lowSlope > flatTol;
  const bothFalling = highSlope < -flatTol && lowSlope < -flatTol;

  if (highFlat && lowSlope > flatTol) {
    out.push(mk('Ascending Triangle', t, 'pos', 0.65, 'flat resistance, rising support', loc));
  } else if (lowFlat && highSlope < -flatTol) {
    out.push(mk('Descending Triangle', t, 'neg', 0.65, 'flat support, falling resistance', loc));
  } else if (converging) {
    out.push(mk('Symmetrical Triangle', t, 'neutral', 0.6, 'converging highs and lows', loc));
  } else if (bothRising && highSlope < lowSlope) {
    out.push(mk('Rising Wedge', t, 'neg', 0.55, 'both bounds rising, narrowing - bearish continuation risk', loc));
  } else if (bothFalling && lowSlope < highSlope) {
    out.push(mk('Falling Wedge', t, 'pos', 0.55, 'both bounds falling, narrowing - bullish reversal risk', loc));
  } else if (highFlat && lowFlat) {
    out.push(mk('Rectangle', t, 'neutral', 0.6, 'trading in a horizontal range', loc));
  }
  return out;
}

// --- Flag (intraday; the High Tight Flag is a daily structure) ------------------------------------------------
// Flagpole: a strong directional move over the prior N bars, followed by a
// tight, low-volatility consolidation drifting counter to the pole.
function flags(candles) {
  const out = [];
  const last = candles.length - 1;
  const poleLen = 10, flagLen = 8;
  if (candles.length < poleLen + flagLen + 1) return out;

  const poleStart = candles[last - flagLen - poleLen];
  const poleEnd = candles[last - flagLen];
  const poleMove = (poleEnd.close - poleStart.close) / poleStart.close;

  const flagBars = candles.slice(last - flagLen + 1, last + 1);
  const flagHigh = Math.max(...flagBars.map((c) => c.high));
  const flagLow = Math.min(...flagBars.map((c) => c.low));
  const flagRange = (flagHigh - flagLow) / poleEnd.close;
  const flagDrift = (flagBars[flagBars.length - 1].close - flagBars[0].close) / flagBars[0].close;

  const isTight = flagRange < Math.abs(poleMove) * 0.5;
  if (!isTight) return out;

  if (poleMove > 0.08 && flagDrift <= 0.01) {
    const score = Math.min(1, (poleMove / 0.15) * 0.5 + (1 - flagRange / (Math.abs(poleMove) * 0.5)) * 0.5);
    const label = 'Flag';
    out.push(mk(label, candles[last].time, 'pos', score, `${(poleMove * 100).toFixed(0)}% pole, tight ${(flagRange * 100).toFixed(1)}% consolidation`, locOf(candles, last - flagLen - poleLen, last, last, candles[last].close)));
  } else if (poleMove < -0.08 && flagDrift >= -0.01) {
    const score = Math.min(1, (Math.abs(poleMove) / 0.15) * 0.5 + (1 - flagRange / (Math.abs(poleMove) * 0.5)) * 0.5);
    out.push(mk('Flag', candles[last].time, 'neg', score, `${(poleMove * 100).toFixed(0)}% pole, tight ${(flagRange * 100).toFixed(1)}% consolidation`, locOf(candles, last - flagLen - poleLen, last, last, candles[last].close)));
  }
  return out;
}

// --- Pocket Pivot ----------------------------------------------------------
function pocketPivot(candles) {
  const out = [];
  const last = candles.length - 1;
  if (candles.length < 12) return out;
  const c = candles[last];
  if (c.close <= c.open) return out;
  const priorTen = candles.slice(last - 10, last);
  const maxDownVol = Math.max(0, ...priorTen.filter((p) => p.close < p.open).map((p) => p.volume || 0));
  if (maxDownVol > 0 && (c.volume || 0) > maxDownVol) {
    const ratio = (c.volume || 0) / maxDownVol;
    const score = Math.min(1, 0.4 + Math.min(ratio - 1, 1) * 0.4);
    out.push(mk('Pocket Pivot', c.time, 'pos', score, `volume ${ratio.toFixed(1)}x the largest down-day in the last 10 bars`, locOf(candles, last - 10, last, last, c.close)));
  }
  return out;
}

// --- Undercut & Rally -------------------------------------------------
function undercutRally(candles, lows) {
  const out = [];
  const last = candles.length - 1;
  if (lows.length < 2) return out;
  const priorLow = lows[lows.length - 2];
  const recentBars = candles.slice(priorLow.index + 1, last + 1);
  if (!recentBars.length) return out;
  const undercutBar = recentBars.find((c) => c.low < priorLow.price);
  if (!undercutBar) return out;
  const c = candles[last];
  if (c.close > priorLow.price && c.low < priorLow.price) {
    out.push(mk('Undercut & Rally', c.time, 'pos', 0.55, `undercut ${priorLow.price.toFixed(2)} then closed back above it`, locOf(candles, priorLow.index, last, last, c.close)));
  }
  return out;
}

// --- Wyckoff Spring / Upthrust (kept explicitly Low confidence) -----------
// These read trader intent (a stop-hunt before reversal) that OHLCV alone
// cannot confirm - included because the requested list asks for them, but
// always capped Low, never presented as a strong signal.
function wyckoffSpringUpthrust(candles, highs, lows) {
  const out = [];
  const last = candles.length - 1;
  const c = candles[last];
  if (lows.length >= 1) {
    const range = lows[lows.length - 1];
    if (c.low < range.price && c.close > range.price && c.close > c.open) {
      out.push(mk('Wyckoff Spring', c.time, 'pos', 0.3, 'false breakdown below support, closed back above - unconfirmed intent', locOf(candles, range.index, last, last, c.close)));
    }
  }
  if (highs.length >= 1) {
    const range = highs[highs.length - 1];
    if (c.high > range.price && c.close < range.price && c.close < c.open) {
      out.push(mk('Wyckoff Upthrust', c.time, 'neg', 0.3, 'false breakout above resistance, closed back below - unconfirmed intent', locOf(candles, range.index, last, last, c.close)));
    }
  }
  return out;
}

// --- Harmonic patterns (very coarse XABCD Fibonacci-ratio check) ----------
// Genuinely hard to do reliably off raw swings; always capped Low.
function harmonics(candles, highs, lows) {
  const out = [];
  const last = candles.length - 1;
  const points = [...highs, ...lows].sort((a, b) => a.index - b.index).slice(-4);
  if (points.length < 4 || points[3].index < last - 3) return out;
  const [x, a, b, c] = points;
  const xa = Math.abs(a.price - x.price);
  const ab = Math.abs(b.price - a.price);
  const bc = Math.abs(c.price - b.price);
  if (xa === 0 || ab === 0) return out;
  const abXa = ab / xa;
  const bcAb = bc / ab;
  // Gartley-ish tolerance band only, not a precise XABCD label.
  if (abXa > 0.55 && abXa < 0.68 && bcAb > 0.35 && bcAb < 0.9) {
    out.push(mk('Harmonic pattern (Gartley-like)', candles[last].time, 'neutral', 0.25, 'approximate Fibonacci ratio fit on last 4 swings - low reliability from OHLCV alone', locOf(candles, x.index, c.index, last, candles[last].close)));
  }
  return out;
}

// Runs every detector and returns the combined, deduped-by-caller event
// list (LiveChart.jsx dedupes on time+text same as the indicator events).
export function detectChartPatterns(candles) {
  if (!candles || candles.length < 30) return [];
  const { highs, lows } = swingPoints(candles, 2);
  return [
    ...doubleTopBottom(candles, highs, lows),
    ...headAndShoulders(candles, highs, lows),
    ...trianglesAndWedges(candles, highs, lows),
    ...flags(candles),
    ...pocketPivot(candles),
    ...undercutRally(candles, lows),
    ...wyckoffSpringUpthrust(candles, highs, lows),
    ...harmonics(candles, highs, lows),
  ];
}
