import React from 'react';

// Sidebar navigation. Deliberately minimal - Overview and AI Research only.
// AI Research routes to tab 6, the rich ratio dashboard (every ratio card carries
// an info tooltip + "How we calculated this" drawer + source, grouped into
// Liquidity/Efficiency/Profitability/Returns/Leverage/Valuation categories).
// `key` is the unique sidebar selection id.

const I = ({ children }) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
       strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

const Icons = {
  overview: () => (<I><rect x="3" y="3" width="8" height="8" rx="1.6" /><rect x="13" y="3" width="8" height="5" rx="1.6" /><rect x="13" y="10" width="8" height="11" rx="1.6" /><rect x="3" y="13" width="8" height="8" rx="1.6" /></I>),
  ai: () => (<I><path d="M12 3a3.5 3.5 0 0 1 3.5 3.5c0 .5-.1 1-.3 1.4A3.5 3.5 0 0 1 17 15.9V17a3 3 0 0 1-5 2.2A3 3 0 0 1 7 17v-1.1A3.5 3.5 0 0 1 8.8 7.9 3.5 3.5 0 0 1 12 3z" /></I>),
  history: () => (<I><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></I>),
  settings: () => (<I><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7.7 1.6 1.6 0 0 0-1.9 1.2H12a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-2.6-1.1 1.6 1.6 0 0 0-1.8.3l-.1.1A2 2 0 1 1 .7 17l.1-.1a1.6 1.6 0 0 0-1-2.7A2 2 0 0 1 1 10.4h.1A1.6 1.6 0 0 0 2.3 7.7l-.1-.1A2 2 0 1 1 5 4.8l.1.1a1.6 1.6 0 0 0 2.7-1V3.8a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1l.1-.1A2 2 0 1 1 21.3 7l-.1.1a1.6 1.6 0 0 0 1 2.7h.1a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" /></I>),
};

export const SECTIONS = [
  { key: 'overview', label: 'Overview',    Icon: Icons.overview, view: { kind: 'overview' } },
  { key: 'ai',        label: 'AI research', Icon: Icons.ai,       view: { kind: 'tab', tab: 6, sub: 0, ratioCat: 0 } },
  { key: 'history',   label: 'History',     Icon: Icons.history,  view: { kind: 'history' } },
];

// Settings isn't a main nav item - it's a small icon in the sidebar/mobile-nav
// footer so theme control stays reachable without cluttering the nav list.
export const SETTINGS_SECTION = { key: 'settings', label: 'Settings', Icon: Icons.settings, view: { kind: 'settings' } };

// Primary items shown in the mobile bottom bar.
export const MOBILE_KEYS = ['overview', 'ai', 'history'];
