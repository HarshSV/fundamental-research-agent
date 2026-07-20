// Recently-analyzed companies, persisted per-browser (no user accounts) so a
// symbol searched once doesn't need to be typed again.
const KEY = 'navrist_history';
const MAX = 30;

export function getHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY));
    return Array.isArray(raw) ? raw : [];
  } catch (e) {
    return [];
  }
}

// Adds/moves `symbol` to the front of the list, deduped, capped at MAX.
export function addHistory(symbol, name) {
  if (!symbol) return;
  try {
    const list = getHistory().filter((h) => h.symbol !== symbol);
    list.unshift({ symbol, name: name || symbol, ts: Date.now() });
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
  } catch (e) { /* localStorage may be unavailable */ }
}

export function removeHistory(symbol) {
  try {
    localStorage.setItem(KEY, JSON.stringify(getHistory().filter((h) => h.symbol !== symbol)));
  } catch (e) { /* ignore */ }
}

export function clearHistory() {
  try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
}
