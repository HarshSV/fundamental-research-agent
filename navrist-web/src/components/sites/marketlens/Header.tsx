"use client";

import { Moon, Plus, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import { TICKER } from "./data";

export const THEME_KEY = "navrist_theme";
export const NEW_SCREEN_EVENT = "navrist-new-screen";
const THEME_EVENT = "navrist-theme-change";

// The <html class="light"> flag is the single source of truth (set before paint by the inline script in
// layout.tsx, so there is no flash); this subscribes React to it.
const subscribe = (cb: () => void) => {
  window.addEventListener(THEME_EVENT, cb);
  return () => window.removeEventListener(THEME_EVENT, cb);
};
const isLight = () => document.documentElement.classList.contains("light");

function toggleTheme() {
  const next = !isLight();
  document.documentElement.classList.toggle("light", next);
  try {
    localStorage.setItem(THEME_KEY, next ? "light" : "dark");
  } catch {
    /* storage unavailable: the choice just won't persist */
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function Header() {
  const light = useSyncExternalStore(subscribe, isLight, () => false);
  const items = [...TICKER, ...TICKER, ...TICKER, ...TICKER];
  return (
    <header
      className="sticky top-0 z-50 border-b backdrop-blur-xl"
      style={{ background: "var(--glass-bg)", borderColor: "var(--glass-border)" }}
    >
      <div
        className="overflow-hidden border-b py-1.5 text-[10px]"
        style={{ borderColor: "var(--glass-border)" }}
      >
        <div
          className="flex w-max gap-10 whitespace-nowrap"
          style={{ animation: "ml-ticker 40s linear infinite" }}
        >
          {items.map((t, i) => (
            <span key={i} className="flex gap-2">
              <span style={{ color: "var(--text-tertiary)" }}>{t.name}</span>
              <span className="font-medium">{t.value}</span>
              <span style={{ color: "var(--gain)" }}>{t.change}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-3 sm:px-4 sm:py-4">
        {/* Brand: clickable, goes back to the home screen (a full load resets any open stock). */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full load is intended: it resets the open stock */}
        <a href="/" aria-label="NAVRIST AI — home" className="flex items-center gap-3 rounded-lg outline-none transition-transform hover:scale-[1.02] focus-visible:ring-2 focus-visible:ring-[var(--btn-primary-bg)]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/sites/marketlens/navrist-logo.svg" alt="" className="h-10 w-10 rounded-lg" />
          <span className="brand-wordmark text-2xl font-extrabold">NAVRIST AI</span>
        </a>
        <div className="flex items-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={light ? "Switch to dark mode" : "Switch to light mode"}
            aria-pressed={light}
            title={light ? "Switch to dark mode" : "Switch to light mode"}
            className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:text-[var(--accent)]"
            style={{ background: "var(--overlay)", color: "var(--text-secondary)" }}
          >
            {light ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={() => window.dispatchEvent(new Event(NEW_SCREEN_EVENT))}
            title="Start a new screen: search a stock or a sector"
            className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-white transition-colors hover:bg-[var(--btn-primary-hover)] sm:px-5"
            style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
          >
            <Plus className="h-4 w-4" />
            <span>New Screen</span>
          </button>
        </div>
      </div>
    </header>
  );
}
