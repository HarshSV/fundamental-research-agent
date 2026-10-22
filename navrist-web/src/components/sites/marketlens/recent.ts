// Recent searches (shown as chips when the search is opened empty): the last stocks / sectors the user opened,
// newest first, kept in this browser only.
const KEY = "navrist_recent_searches";
const MAX = 8;

export type Recent = { kind: "stock"; symbol: string; name: string } | { kind: "sector"; name: string };

const same = (a: Recent, b: Recent) =>
  a.kind === "stock" ? b.kind === "stock" && a.symbol === b.symbol : b.kind === "sector" && a.name === b.name;

export function loadRecents(): Recent[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw)
      ? raw.filter((r): r is Recent => !!r && ((r.kind === "stock" && typeof r.symbol === "string" && typeof r.name === "string") || (r.kind === "sector" && typeof r.name === "string"))).slice(0, MAX)
      : [];
  } catch {
    return [];
  }
}

export function addRecent(r: Recent) {
  try {
    const next = [r, ...loadRecents().filter((x) => !same(x, r))].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: recents just do not persist */
  }
}
