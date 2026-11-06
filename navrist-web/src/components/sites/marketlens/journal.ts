"use client";

import { useSyncExternalStore } from "react";

/**
 * Trade journal, kept in this browser (localStorage; the chart image is stored with the trade as a small compressed picture).
 * Nothing is sent anywhere. Unknown values stay unknown: an open trade has no P&L, a trade without a stop has no R-multiple.
 */
export type Side = "long" | "short";
export interface Trade {
  id: string;
  symbol: string;
  name: string;
  side: Side;
  setup: string;
  entryDate: string; // YYYY-MM-DD
  entryPrice: number;
  qty: number;
  stop: number | null;
  target: number | null;
  exitDate: string | null;
  exitPrice: number | null;
  fees: number | null;
  notes: string;
  wentWell: string;
  improve: string;
  mistakes: string[];
  image: string | null;
  createdAt: number;
}

export const MISTAKES = ["Chased the entry", "No stop loss", "Moved the stop", "Position too big", "Exited too early", "Held too long", "Ignored my plan", "Revenge trade", "FOMO"];

const KEY = "navrist_journal_v1";
const EVENT = "navrist-journal-change";
const EMPTY: Trade[] = [];
let cache: { raw: string | null; value: Trade[] } = { raw: null, value: EMPTY };

function read(): Trade[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return EMPTY;
  }
  if (raw === cache.raw) return cache.value;
  let value = EMPTY;
  try {
    const p = raw ? (JSON.parse(raw) as Trade[]) : [];
    value = Array.isArray(p) ? p.filter((t) => t && typeof t.id === "string" && typeof t.entryPrice === "number") : EMPTY;
  } catch {
    value = EMPTY;
  }
  cache = { raw, value };
  return value;
}

/** Returns an error message when the browser refused to store it (usually a full quota), else "". */
function write(next: Trade[]): string {
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    return "This browser has no room left to save. Remove an old chart image or trade and try again.";
  }
  window.dispatchEvent(new Event(EVENT));
  return "";
}

const subscribe = (cb: () => void) => {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
};
export const useTrades = () => useSyncExternalStore(subscribe, read, () => EMPTY);

export const newId = () => `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
export const saveTrade = (t: Trade): string => {
  const all = read();
  return write(all.some((x) => x.id === t.id) ? all.map((x) => (x.id === t.id ? t : x)) : [...all, t]);
};
export const deleteTrade = (id: string) => write(read().filter((t) => t.id !== id));

// ------------------------------------------------------------------ metrics
export interface Metrics {
  closed: boolean;
  pnl: number | null; // money, after fees
  pct: number | null; // price move in the trade's direction, %
  r: number | null; // R-multiple (needs a stop)
  days: number | null;
}
const dayMs = 86400000;
export function metrics(t: Trade): Metrics {
  const dir = t.side === "long" ? 1 : -1;
  const closed = t.exitPrice != null && t.exitDate != null;
  const days = t.exitDate ? Math.round((Date.parse(t.exitDate) - Date.parse(t.entryDate)) / dayMs) : null;
  if (!closed || t.exitPrice == null) return { closed: false, pnl: null, pct: null, r: null, days: null };
  const perShare = (t.exitPrice - t.entryPrice) * dir;
  const risk = t.stop != null ? Math.abs(t.entryPrice - t.stop) : 0;
  return {
    closed: true,
    pnl: perShare * t.qty - (t.fees ?? 0),
    pct: (perShare / t.entryPrice) * 100,
    r: risk > 0 ? perShare / risk : null,
    days: days != null && days >= 0 ? days : null,
  };
}

export interface Summary {
  trades: number;
  open: number;
  closed: number;
  wins: number;
  losses: number;
  winRate: number | null;
  totalPnl: number | null;
  avgWin: number | null;
  avgLoss: number | null;
  profitFactor: number | null;
  expectancy: number | null;
  avgR: number | null;
  bySetup: { setup: string; n: number; winRate: number; pnl: number }[];
  mistakes: { tag: string; n: number }[];
}
export function summarize(all: Trade[]): Summary {
  const ms = all.map((t) => ({ t, m: metrics(t) }));
  const closed = ms.filter((x) => x.m.closed && x.m.pnl != null);
  const wins = closed.filter((x) => (x.m.pnl as number) > 0);
  const losses = closed.filter((x) => (x.m.pnl as number) < 0);
  const sum = (a: { m: Metrics }[]) => a.reduce((s, x) => s + (x.m.pnl as number), 0);
  const gross = sum(wins), lost = -sum(losses);
  const rs = closed.map((x) => x.m.r).filter((v): v is number => v != null);
  const setups = new Map<string, { n: number; w: number; pnl: number }>();
  for (const x of closed) {
    const k = x.t.setup.trim() || "No setup";
    const s = setups.get(k) ?? { n: 0, w: 0, pnl: 0 };
    s.n += 1;
    s.w += (x.m.pnl as number) > 0 ? 1 : 0;
    s.pnl += x.m.pnl as number;
    setups.set(k, s);
  }
  const mk = new Map<string, number>();
  for (const t of all) for (const m of t.mistakes) mk.set(m, (mk.get(m) ?? 0) + 1);
  return {
    trades: all.length,
    open: all.length - closed.length,
    closed: closed.length,
    wins: wins.length,
    losses: losses.length,
    winRate: closed.length ? (wins.length / closed.length) * 100 : null,
    totalPnl: closed.length ? sum(closed) : null,
    avgWin: wins.length ? gross / wins.length : null,
    avgLoss: losses.length ? -lost / losses.length : null,
    profitFactor: lost > 0 ? gross / lost : null,
    expectancy: closed.length ? sum(closed) / closed.length : null,
    avgR: rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null,
    bySetup: [...setups.entries()].map(([setup, s]) => ({ setup, n: s.n, winRate: (s.w / s.n) * 100, pnl: s.pnl })).sort((a, b) => b.pnl - a.pnl),
    mistakes: [...mk.entries()].map(([tag, n]) => ({ tag, n })).sort((a, b) => b.n - a.n),
  };
}

/** Shrinks a chart screenshot to a small JPEG so many trades fit in the browser's storage. */
export function compressImage(file: File, maxSide = 1000, quality = 0.72): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, maxSide / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k);
      c.height = Math.round(img.height * k);
      const ctx = c.getContext("2d");
      if (!ctx) return reject(new Error("Could not read the image."));
      ctx.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", quality));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file is not an image the browser can read."));
    };
    img.src = url;
  });
}

const csv = (v: unknown) => {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
export function toCsv(all: Trade[]): string {
  const head = ["Symbol", "Name", "Side", "Setup", "Entry date", "Entry price", "Qty", "Stop", "Target", "Exit date", "Exit price", "Fees", "P&L", "Return %", "R", "Days", "Mistakes", "Notes", "What went well", "To improve"];
  const lines = all.map((t) => {
    const m = metrics(t);
    return [t.symbol, t.name, t.side, t.setup, t.entryDate, t.entryPrice, t.qty, t.stop, t.target, t.exitDate, t.exitPrice, t.fees, m.pnl?.toFixed(2), m.pct?.toFixed(2), m.r?.toFixed(2), m.days, t.mistakes.join("; "), t.notes, t.wentWell, t.improve].map(csv).join(",");
  });
  return [head.join(","), ...lines].join("\n");
}
