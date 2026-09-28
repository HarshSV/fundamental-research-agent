// Pure, company-agnostic technical-analysis helpers over an OHLCV candle
// series (ascending by time - the same shape /api/live-chart/{symbol}
// returns). No network calls, no state - LiveChart.jsx re-runs this on
// every candle refresh and diffs the output to know what's new.
//
// Scope is deliberately limited to what's honestly computable from bare
// OHLCV bars (indicators, trend structure, candlestick shapes, volume,
// breakouts). Wyckoff phases and Smart Money Concepts (BOS/CHoCH/FVG/Order
// Blocks) are NOT included - they read as confident claims but are fuzzy
// even for human chartists, and this project's own rule (never convert an
// inconclusive read into a false-confidence value) rules out presenting
// them as fact from noisy OHLCV data alone. Derivatives (OI/PCR/IV/Gamma)
// need a live F&O feed the yfinance stand-in doesn't have.

function ema(values, period) {
  const k = 2 / (period + 1);
  const out = new Array(values.length).fill(null);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (prev === null) {
      if (i >= period - 1) {
        const seed = values.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period;
        prev = seed;
        out[i] = seed;
      }
    } else {
      prev = v * k + prev * (1 - k);
      out[i] = prev;
    }
  }
  return out;
}

function rsi(closes, period = 14) {
  const out = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return out;
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff; else losses -= diff;
  }
  let avgGain = gains / period, avgLoss = losses / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

function macd(closes, fast = 12, slow = 26, signalPeriod = 9) {
  const emaFast = ema(closes, fast);
  const emaSlow = ema(closes, slow);
  const line = closes.map((_, i) => (emaFast[i] != null && emaSlow[i] != null) ? emaFast[i] - emaSlow[i] : null);
  const validLine = line.filter((v) => v != null);
  const signalOnValid = ema(validLine, signalPeriod);
  const signal = new Array(line.length).fill(null);
  let vi = 0;
  for (let i = 0; i < line.length; i++) {
    if (line[i] != null) { signal[i] = signalOnValid[vi]; vi++; }
  }
  const hist = line.map((v, i) => (v != null && signal[i] != null) ? v - signal[i] : null);
  return { line, signal, hist };
}

function atr(candles, period = 14) {
  const out = new Array(candles.length).fill(null);
  const trs = candles.map((c, i) => {
    if (i === 0) return c.high - c.low;
    const prevClose = candles[i - 1].close;
    return Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose));
  });
  let prev = null;
  for (let i = 0; i < trs.length; i++) {
    if (i < period - 1) continue;
    if (prev === null) {
      prev = trs.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period;
    } else {
      prev = (prev * (period - 1) + trs[i]) / period;
    }
    out[i] = prev;
  }
  return out;
}

function bollinger(closes, period = 20, mult = 2) {
  const mid = new Array(closes.length).fill(null);
  const upper = new Array(closes.length).fill(null);
  const lower = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / period;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    mid[i] = mean; upper[i] = mean + mult * sd; lower[i] = mean - mult * sd;
  }
  return { mid, upper, lower };
}

// Simple pivot high/low detection (fractal, `wing` bars either side).
// Exported: chartPatterns.js reuses the same swing points so pattern
// geometry and the structure/breakout events above always agree on where
// the pivots are.
export function swingPoints(candles, wing = 2) {
  const highs = [], lows = [];
  for (let i = wing; i < candles.length - wing; i++) {
    const h = candles[i].high, l = candles[i].low;
    let isHigh = true, isLow = true;
    for (let j = i - wing; j <= i + wing; j++) {
      if (j === i) continue;
      if (candles[j].high >= h) isHigh = false;
      if (candles[j].low <= l) isLow = false;
    }
    if (isHigh) highs.push({ index: i, time: candles[i].time, price: h });
    if (isLow) lows.push({ index: i, time: candles[i].time, price: l });
  }
  return { highs, lows };
}

function candlePattern(c, prev) {
  const body = Math.abs(c.close - c.open);
  const range = c.high - c.low || 1e-9;
  const upperWick = c.high - Math.max(c.open, c.close);
  const lowerWick = Math.min(c.open, c.close) - c.low;
  const bodyPct = body / range;

  if (bodyPct < 0.1) return 'Doji';
  if (lowerWick > body * 2 && upperWick < body * 0.5 && c.close > c.open) return 'Hammer';
  if (upperWick > body * 2 && lowerWick < body * 0.5 && c.close < c.open) return 'Shooting Star';
  if (prev) {
    const prevBody = Math.abs(prev.close - prev.open);
    const bullishEngulf = prev.close < prev.open && c.close > c.open && c.close >= prev.open && c.open <= prev.close && body > prevBody;
    const bearishEngulf = prev.close > prev.open && c.close < c.open && c.open >= prev.close && c.close <= prev.open && body > prevBody;
    if (bullishEngulf) return 'Bullish Engulfing';
    if (bearishEngulf) return 'Bearish Engulfing';
  }
  return null;
}

// Runs the full analysis over a candle series and returns a flat list of
// point-in-time events, newest last, each tagged with the candle `time`
// it belongs to so the caller can dedupe against what's already logged.
export function analyzeCandles(candles) {
  if (!candles || candles.length < 30) return [];
  const closes = candles.map((c) => c.close);
  const volumes = candles.map((c) => c.volume || 0);
  const rsiSeries = rsi(closes, 14);
  const { line: macdLine, signal: macdSignal } = macd(closes);
  const atrSeries = atr(candles, 14);
  const bb = bollinger(closes, 20, 2);
  const { highs, lows } = swingPoints(candles, 2);

  const events = [];
  const last = candles.length - 1;
  const push = (time, kind, text, tone = 'neutral') => events.push({ time, kind, text, tone });

  // RSI overbought/oversold + cross of the last two closed bars.
  if (rsiSeries[last] != null && rsiSeries[last - 1] != null) {
    const cur = rsiSeries[last], prevV = rsiSeries[last - 1];
    if (prevV < 70 && cur >= 70) push(candles[last].time, 'momentum', `RSI crossed above 70 (${cur.toFixed(1)}) - overbought`, 'neg');
    if (prevV > 30 && cur <= 30) push(candles[last].time, 'momentum', `RSI crossed below 30 (${cur.toFixed(1)}) - oversold`, 'pos');
    if (prevV <= 50 && cur > 50) push(candles[last].time, 'momentum', `RSI crossed above 50 (${cur.toFixed(1)}) - momentum turning bullish`, 'pos');
    if (prevV >= 50 && cur < 50) push(candles[last].time, 'momentum', `RSI crossed below 50 (${cur.toFixed(1)}) - momentum turning bearish`, 'neg');
  }

  // MACD line/signal cross.
  if (macdLine[last] != null && macdSignal[last] != null && macdLine[last - 1] != null && macdSignal[last - 1] != null) {
    const curDiff = macdLine[last] - macdSignal[last];
    const prevDiff = macdLine[last - 1] - macdSignal[last - 1];
    if (prevDiff <= 0 && curDiff > 0) push(candles[last].time, 'momentum', 'MACD crossed above signal - bullish crossover', 'pos');
    if (prevDiff >= 0 && curDiff < 0) push(candles[last].time, 'momentum', 'MACD crossed below signal - bearish crossover', 'neg');
  }

  // Bollinger Band squeeze / breakout.
  if (bb.upper[last] != null && bb.lower[last] != null) {
    const width = bb.upper[last] - bb.lower[last];
    const widthPct = width / (bb.mid[last] || 1);
    if (widthPct < 0.04) push(candles[last].time, 'volatility', 'Bollinger Band squeeze - volatility contracting, watch for a breakout', 'neutral');
    if (closes[last] > bb.upper[last]) push(candles[last].time, 'volatility', 'Price closed above the upper Bollinger Band', 'pos');
    if (closes[last] < bb.lower[last]) push(candles[last].time, 'volatility', 'Price closed below the lower Bollinger Band', 'neg');
  }

  // NR7 - narrowest true range of the last 7 bars.
  if (candles.length >= 7) {
    const last7 = candles.slice(last - 6, last + 1);
    const ranges = last7.map((c) => c.high - c.low);
    if (ranges[6] === Math.min(...ranges)) {
      push(candles[last].time, 'volatility', 'NR7 - narrowest range in 7 bars, often precedes a breakout', 'neutral');
    }
  }

  // Volume spike vs trailing 20-bar average.
  if (candles.length >= 21) {
    const avgVol = volumes.slice(last - 20, last).reduce((a, b) => a + b, 0) / 20;
    if (avgVol > 0 && volumes[last] > avgVol * 2) {
      push(candles[last].time, 'volume', `Volume spike - ${(volumes[last] / avgVol).toFixed(1)}x the 20-bar average`, closes[last] >= candles[last].open ? 'pos' : 'neg');
    }
  }

  // Candlestick pattern on the last closed bar.
  const pattern = candlePattern(candles[last], candles[last - 1]);
  if (pattern) {
    const tone = pattern.includes('Bullish') || pattern === 'Hammer' ? 'pos' : pattern.includes('Bearish') || pattern === 'Shooting Star' ? 'neg' : 'neutral';
    push(candles[last].time, 'candlestick', `${pattern} candle formed`, tone);
  }

  // Structure: new higher-high / lower-low relative to the last two swing points.
  if (highs.length >= 2) {
    const [prevH, curH] = highs.slice(-2);
    if (curH.index === last - 2 || curH.index === last) {
      push(curH.time, 'structure', curH.price > prevH.price ? 'New swing high formed (HH) - trend structure bullish' : 'New swing high formed, lower than prior (LH)', curH.price > prevH.price ? 'pos' : 'neg');
    }
  }
  if (lows.length >= 2) {
    const [prevL, curL] = lows.slice(-2);
    if (curL.index === last - 2 || curL.index === last) {
      push(curL.time, 'structure', curL.price < prevL.price ? 'New swing low formed (LL) - trend structure bearish' : 'New swing low formed, higher than prior (HL)', curL.price < prevL.price ? 'neg' : 'pos');
    }
  }

  // Resistance/support breakout: close beyond the most recent confirmed swing point.
  if (highs.length) {
    const recentHigh = highs[highs.length - 1];
    if (recentHigh.index < last && closes[last] > recentHigh.price && closes[last - 1] <= recentHigh.price) {
      push(candles[last].time, 'breakout', `Broke above resistance at ${recentHigh.price.toFixed(2)} (prior swing high)`, 'pos');
    }
  }
  if (lows.length) {
    const recentLow = lows[lows.length - 1];
    if (recentLow.index < last && closes[last] < recentLow.price && closes[last - 1] >= recentLow.price) {
      push(candles[last].time, 'breakout', `Broke below support at ${recentLow.price.toFixed(2)} (prior swing low)`, 'neg');
    }
  }

  return events;
}
