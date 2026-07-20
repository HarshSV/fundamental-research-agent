import React from 'react';
import { SECTIONS, SETTINGS_SECTION } from './sections.jsx';

const ChevronIcon = ({ dir }) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d={dir === 'left' ? 'M15 18l-6-6 6-6' : 'M9 18l6-6-6-6'} />
  </svg>
);

// Permanent, collapsible left navigation. Settings is pinned to the bottom.
// Hidden below lg (MobileNav takes over). Drives a single `activeKey`.
export default function Sidebar({ activeKey, onSelect, collapsed, onToggle }) {
  const Item = ({ s }) => {
    const active = activeKey === s.key;
    const Ic = s.Icon;
    return (
      <button
        type="button"
        onClick={() => onSelect(s)}
        title={collapsed ? s.label : undefined}
        className={`group/i relative w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors ${collapsed ? 'justify-center' : ''} ${
          active ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-850'
        }`}
      >
        <span className="flex-shrink-0"><Ic /></span>
        {!collapsed && <span className="text-[13.5px] font-semibold truncate">{s.label}</span>}
        {collapsed && (
          <span className="pointer-events-none absolute left-full ml-2 px-2 py-1 rounded-md bg-slate-900 border border-slate-800 text-[12px] font-medium text-slate-200 whitespace-nowrap opacity-0 group-hover/i:opacity-100 transition-opacity z-50 nv-float2">
            {s.label}
          </span>
        )}
      </button>
    );
  };

  return (
    <aside
      className={`hidden lg:flex flex-col flex-shrink-0 sticky top-0 self-start h-screen transition-[width] duration-200 ${collapsed ? 'w-[68px]' : 'w-[236px]'}`}
    >
      <div className="nv-card m-3 mr-0 rounded-2xl flex flex-col h-[calc(100vh-24px)] overflow-hidden">
        {/* brand */}
        <div className={`flex items-center gap-2.5 px-4 h-16 flex-shrink-0 ${collapsed ? 'justify-center px-0' : ''}`}>
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white grid place-items-center font-extrabold text-sm flex-shrink-0">N</div>
          {!collapsed && <span className="font-heading font-bold text-slate-100 tracking-tight truncate">Navrist<span className="text-blue-600"> AI</span></span>}
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-2 space-y-0.5">
          {SECTIONS.map((s) => <Item key={s.key} s={s} />)}
        </nav>

        <div className="px-2.5 py-2 border-t border-slate-800 space-y-0.5 flex-shrink-0">
          <Item s={SETTINGS_SECTION} />
          <button
            type="button"
            onClick={onToggle}
            className={`w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-slate-500 hover:text-slate-200 hover:bg-slate-850 transition-colors ${collapsed ? 'justify-center' : ''}`}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <ChevronIcon dir={collapsed ? 'right' : 'left'} />
            {!collapsed && <span className="text-[13px] font-medium">Collapse</span>}
          </button>
        </div>
      </div>
    </aside>
  );
}
