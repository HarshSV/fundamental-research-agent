import React, { useState } from 'react';
import { getInitialTheme, applyTheme } from '../theme/ThemeToggle.jsx';

export default function Settings({ onLogout }) {
  const [theme, setTheme] = useState(getInitialTheme);
  const pick = (t) => { setTheme(t); applyTheme(t); };

  const Opt = ({ id, title, desc }) => (
    <button
      onClick={() => pick(id)}
      className={`flex-1 text-left nv-card p-4 transition-colors ${theme === id ? 'border-blue-500' : ''}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-[14px] font-semibold text-slate-100">{title}</span>
        <span className={`w-4 h-4 rounded-full border-2 ${theme === id ? 'border-blue-600 bg-blue-600' : 'border-slate-600'}`} />
      </div>
      <p className="text-[12px] text-slate-500 mt-1">{desc}</p>
    </button>
  );

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="nv-h2 text-[18px] text-slate-100">Settings</h2>
        <p className="text-[13px] text-slate-500 mt-1">Appearance and session.</p>
      </div>

      <section className="space-y-3">
        <h3 className="nv-eyebrow text-slate-500">Appearance</h3>
        <div className="flex gap-3">
          <Opt id="light" title="Light" desc="Bright, high-contrast surfaces." />
          <Opt id="dark" title="Dark" desc="Native dark theme for low-light." />
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="nv-eyebrow text-slate-500">Session</h3>
        <div className="nv-card p-4 flex items-center justify-between">
          <div>
            <div className="text-[14px] font-semibold text-slate-100">Sign out</div>
            <div className="text-[12px] text-slate-500">End this research session on the terminal.</div>
          </div>
          <button onClick={onLogout} className="nv-btn nv-btn-ghost h-9 px-4 text-[13px]">Sign out</button>
        </div>
      </section>

      <p className="text-[11px] text-slate-600">Navrist AI · Research Terminal · For internal research use only. Not investment advice.</p>
    </div>
  );
}
