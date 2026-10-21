// Client for the Navrist backend (proxied through /api/* by next.config.ts).
// Uses the same JWT bearer scheme and storage key as the existing Navrist frontend.

export const TOKEN_KEY = "navrist_token";
export const AUTH_EVENT = "navrist-auth-change";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function logout() {
  setToken(null);
}

export async function login(password: string): Promise<void> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Login failed.");
  }
  const data: { access_token: string } = await res.json();
  setToken(data.access_token);
}

export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    setToken(null);
    throw new Error("Session expired");
  }
  return res;
}

class HttpError extends Error {
  constructor(public status: number) {
    super(`Request failed (${status})`);
  }
}

export interface FetchJsonOptions<T> {
  retries?: number; // extra attempts after the first (default 2)
  delayMs?: number; // base back-off; attempt n waits n x delayMs (default 700)
  /** Returns false when a 200 response is really "nothing" (e.g. an empty candle list). Such answers are
   *  retried; if every attempt is unusable the last answer is returned as-is rather than thrown. */
  usable?: (d: T) => boolean;
  init?: RequestInit;
}

/**
 * Shared JSON fetch used across the app. The market-data providers behind the backend intermittently
 * return an empty answer or a 5xx under load, which used to surface as a blank chart or a panel stuck
 * on "unavailable". Retries cover network errors, 5xx, 429 and unusable answers; auth and other 4xx
 * errors are not retried.
 */
export async function fetchJson<T>(path: string, o: FetchJsonOptions<T> = {}): Promise<T> {
  const { retries = 2, delayMs = 700, usable, init } = o;
  let lastErr: Error = new Error("Request failed");
  let lastData: T | undefined;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await authFetch(path, init);
      if (res.status >= 500 || res.status === 429) throw new HttpError(res.status);
      if (!res.ok) {
        const err = new HttpError(res.status);
        (err as Error & { fatal?: boolean }).fatal = true;
        throw err;
      }
      const data = (await res.json()) as T;
      lastData = data;
      if (usable && !usable(data)) throw new Error("No data returned");
      return data;
    } catch (e) {
      lastErr = e as Error;
      const fatal = (e as { fatal?: boolean }).fatal || lastErr.message === "Session expired" || lastErr.name === "AbortError";
      if (fatal || attempt === retries) break;
      await new Promise((r) => setTimeout(r, delayMs * (attempt + 1)));
    }
  }
  if (lastData !== undefined) return lastData; // answered, but never with usable data
  throw lastErr;
}

export async function checkSession(): Promise<boolean> {
  if (!getToken()) return false;
  try {
    const res = await authFetch("/api/auth/me");
    return res.ok;
  } catch {
    return false;
  }
}

// Shape is passed through from the backend; fields beyond symbol/name are optional.
export interface CompanyHit {
  symbol: string;
  name?: string;
  company_name?: string;
  [key: string]: unknown;
}

export async function searchSymbols(q: string, signal?: AbortSignal): Promise<CompanyHit[]> {
  const res = await authFetch(`/api/search-symbols?q=${encodeURIComponent(q)}`, { signal });
  if (!res.ok) throw new Error(`Search failed (${res.status})`);
  return res.json();
}
