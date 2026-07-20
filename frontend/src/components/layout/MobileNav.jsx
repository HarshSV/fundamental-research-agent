import React from 'react';
import { SECTIONS, SETTINGS_SECTION, MOBILE_KEYS } from './sections.jsx';

// Fixed bottom navigation for small screens (replaces the sidebar below lg).
export default function MobileNav({ activeKey, onSelect }) {
  const items = [...MOBILE_KEYS.map((k) => SECTIONS.find((s) => s.key === k)).filter(Boolean), SETTINGS_SECTION];
  return (
    <nav
      className="lg:hidden fixed bottom-0 inset-x-0 z-50 bg-slate-900/95 backdrop-blur border-t border-slate-800"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      aria-label="Sections"
    >
      <div className="flex items-stretch justify-between px-1">
        {items.map((s) => {
          const active = activeKey === s.key;
          const Ic = s.Icon;
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onSelect(s)}
              className={`flex-1 flex flex-col items-center gap-0.5 py-2 min-w-0 transition-colors ${active ? 'text-blue-600' : 'text-slate-500'}`}
              aria-current={active ? 'page' : undefined}
            >
              <Ic />
              <span className="text-[9px] font-semibold truncate max-w-full">{s.label.split(' ')[0]}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
