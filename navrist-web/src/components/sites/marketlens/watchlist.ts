"use client";

import { useSyncExternalStore } from "react";

/**
 * Watchlists live in this browser (localStorage), like the saved screener filters: no account is needed, and they stay on this
 * device. Each list holds stocks with a priority (high / medium / low). A stock outside the scanned universe can still be saved;
 * it just has no scan data to show.
 */
export type Priority = "high" | "medium" | "low";
export interface WatchItem {
  symbol: string;
  name: string;
  priority: Priority;
  addedAt: number;
  note?: string;
}
export interface WatchStore {
  active: string;
  lists: Record<string, WatchItem[]>;
}

const KEY = "navrist_watchlists_v1";
const EVENT = "navrist-watchlist-change";
export const DEFAULT_LIST = "My Watchlist";
const EMPTY: WatchStore = { active: DEFAULT_LIST, lists: { [DEFAULT_LIST]: [] } };

let cache: { raw: string | null; value: WatchStore } = { raw: null, value: EMPTY };

function read(): WatchStore {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return EMPTY;
  }
  if (raw === cache.raw) return cache.value;
  let value = EMPTY;
  try {
    const p = raw ? (JSON.parse(raw) as Partial<WatchStore>) : null;
    if (p && p.lists && typeof p.lists === "object" && Object.keys(p.lists).length) {
      const lists: Record<string, WatchItem[]> = {};
      for (const [k, v] of Object.entries(p.lists)) lists[k] = Array.isArray(v) ? v.filter((x) => x && typeof x.symbol === "string") : [];
      value = { active: p.active && lists[p.active] ? p.active : Object.keys(lists)[0], lists };
    }
  } catch {
    value = EMPTY;
  }
  cache = { raw, value };
  return value;
}

function write(next: WatchStore) {
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage full or blocked: the change just will not persist */
  }
  window.dispatchEvent(new Event(EVENT));
}

const subscribe = (cb: () => void) => {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
};

export const useWatchlists = () => useSyncExternalStore(subscribe, read, () => EMPTY);

export const activeList = (s: WatchStore) => s.lists[s.active] ?? [];
export const isWatched = (s: WatchStore, symbol: string) => activeList(s).some((i) => i.symbol === symbol);

export function addToWatchlist(symbol: string, name: string, priority: Priority = "medium") {
  const s = read();
  const list = activeList(s);
  if (list.some((i) => i.symbol === symbol)) return;
  write({ ...s, lists: { ...s.lists, [s.active]: [...list, { symbol, name, priority, addedAt: Date.now() }] } });
}
export function removeFromWatchlist(symbol: string) {
  const s = read();
  write({ ...s, lists: { ...s.lists, [s.active]: activeList(s).filter((i) => i.symbol !== symbol) } });
}
export function setPriority(symbol: string, priority: Priority) {
  const s = read();
  write({ ...s, lists: { ...s.lists, [s.active]: activeList(s).map((i) => (i.symbol === symbol ? { ...i, priority } : i)) } });
}
export function setNote(symbol: string, note: string) {
  const s = read();
  write({ ...s, lists: { ...s.lists, [s.active]: activeList(s).map((i) => (i.symbol === symbol ? { ...i, note } : i)) } });
}
export function selectList(name: string) {
  const s = read();
  if (s.lists[name]) write({ ...s, active: name });
}
export function createList(name: string): boolean {
  const n = name.trim().slice(0, 40);
  const s = read();
  if (!n || s.lists[n]) return false;
  write({ active: n, lists: { ...s.lists, [n]: [] } });
  return true;
}
export function deleteList(name: string) {
  const s = read();
  const names = Object.keys(s.lists);
  if (names.length < 2) {
    write({ active: name, lists: { [name]: [] } }); // the last list is emptied, never removed
    return;
  }
  const { [name]: _gone, ...rest } = s.lists;
  void _gone;
  write({ active: s.active === name ? Object.keys(rest)[0] : s.active, lists: rest });
}

/** A short text to share a list: copy it, paste it into "Import" on another device or browser. */
export function shareText(items: WatchItem[]): string {
  return "NVWL1:" + btoa(unescape(encodeURIComponent(JSON.stringify(items.map((i) => [i.symbol, i.name, i.priority])))));
}
export function importText(code: string): number {
  try {
    const raw = code.trim();
    if (!raw.startsWith("NVWL1:")) return -1;
    const rows = JSON.parse(decodeURIComponent(escape(atob(raw.slice(6))))) as [string, string, Priority][];
    const s = read();
    const have = new Set(activeList(s).map((i) => i.symbol));
    const add: WatchItem[] = rows
      .filter((r) => Array.isArray(r) && typeof r[0] === "string" && !have.has(r[0]))
      .map((r) => ({ symbol: r[0], name: String(r[1] ?? r[0]), priority: (["high", "medium", "low"].includes(r[2]) ? r[2] : "medium") as Priority, addedAt: Date.now() }));
    write({ ...s, lists: { ...s.lists, [s.active]: [...activeList(s), ...add] } });
    return add.length;
  } catch {
    return -1;
  }
}
