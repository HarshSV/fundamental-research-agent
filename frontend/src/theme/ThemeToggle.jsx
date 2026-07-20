import React, { useEffect, useState } from 'react';

const STORAGE_KEY = 'navrist_theme';

// Resolve the initial theme: the last choice saved ON THIS COMPUTER wins (there
// are no user accounts, so persistence is per-browser via localStorage). If no
// choice has ever been made, default to light. Kept in sync with the pre-paint
// script in index.html so there is no flash of the wrong theme on load.
export function getInitialTheme() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch (e) { /* localStorage may be unavailable */ }
  return 'light';
}

export function applyTheme(theme) {
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) { /* ignore */ }
}

const SunIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
const MoonIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </svg>
);

// Floating theme switch, rendered once as a sibling of <App/> so it is available
// in every app state (login, dashboard, landing).
export default function ThemeToggle() {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  const isDark = theme === 'dark';

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Light mode' : 'Dark mode'}
      className="nv-elevate fixed top-3 right-3 z-[60] w-9 h-9 rounded-full flex items-center justify-center bg-slate-900 border border-slate-800 text-slate-400 hover:text-blue-600 hover:border-slate-700 transition-colors"
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
