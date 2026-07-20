// Centralised API layer — same backend endpoints and JWT bearer scheme the app
// has always used. New components import from here instead of threading fetch
// helpers through props.

export const API_BASE = (function () {
  const origin = window.location.origin || '';
  const isStandaloneDev = origin.includes(':5500') || origin.startsWith('file');
  if (origin.startsWith('http') && !isStandaloneDev) return origin;
  return 'http://127.0.0.1:8000';
})();

export const TOKEN_KEY = 'navrist_token';

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
};

// Fetch with bearer token attached. Throws on 401 so callers can surface expiry.
export async function authFetch(path, options = {}) {
  const token = getToken();
  const headers = Object.assign({}, options.headers || {}, token ? { Authorization: `Bearer ${token}` } : {});
  const res = await fetch(`${API_BASE}${path}`, Object.assign({}, options, { headers }));
  if (res.status === 401) {
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ }
    throw new Error('Session expired');
  }
  return res;
}

// POST helper for the /api/v1/* ratio endpoints — every one of these is
// backed by the fast Supabase precompute table first (falling back to a
// live PDF parse only on a cache miss), so they resolve in ~1s for any
// already-precomputed company instead of waiting on the slow multi-LLM
// /api/v1/generate-report pipeline. Never throws — callers get `null` on
// any failure (network, 401, non-2xx) and treat that the same as "not
// applicable" rather than crashing the caller's Promise.all.
export async function fetchRatio(path, symbol, name, to_date = null) {
  try {
    const res = await authFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, name, to_date }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

export async function fetchQuote(symbol) {
  try {
    const res = await authFetch(`/api/quote?symbol=${encodeURIComponent(symbol)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

export async function searchSymbols(q) {
  if (!q || !q.trim()) return [];
  try {
    const res = await authFetch(`/api/search-symbols?q=${encodeURIComponent(q)}`);
    return await res.json();
  } catch (e) {
    return [];
  }
}
