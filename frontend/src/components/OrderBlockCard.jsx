import React from 'react';
import { fmtDate, fmtTime } from '../lib/marketTime.js';

const px = (v) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(2) : '—'); // unknown is a dash, never 0
const STATE = { formed: 'Just formed', untouched: 'Untouched', retested: 'Retested', broken: 'Broken (closed beyond invalidation)' };

function Row({ k, v, testid }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-500">{k}</span>
      <span className="text-slate-200 nv-num text-right" data-testid={testid}>{v}</span>
    </div>
  );
}

// Detail card for one order-block zone. Bottom sheet on narrow screens, floating card otherwise.
export default function OrderBlockCard({ zone, onClose }) {
  if (!zone) return null;
  const bull = zone.side === 'bull';
  return (
    <div
      data-testid="ob-card"
      className="fixed bottom-0 inset-x-0 z-40 max-h-[70vh] overflow-y-auto rounded-t-lg border border-slate-700 bg-slate-900 shadow-lg sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-2 sm:top-2 sm:w-72 sm:max-h-[400px] sm:rounded-md"
    >
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <div className="text-[12px] font-semibold text-slate-100">
          {bull ? 'Bullish' : 'Bearish'} order block
          <span className="ml-2 font-normal text-slate-500 nv-num">{fmtDate(zone.formedAt)}, {fmtTime(zone.formedAt)}</span>
        </div>
        <button onClick={onClose} className="px-2 text-slate-500 hover:text-slate-200" aria-label="Close">x</button>
      </div>
      <div className="space-y-1 px-3 py-2 text-[11px]">
        <Row k="Zone" v={`${px(zone.zoneLow)} - ${px(zone.zoneHigh)}`} />
        <Row k="Z (zone edge)" v={px(zone.z)} />
        <Row k="Invalidation" v={px(zone.inv)} />
        <Row k="Level 1" v={px(zone.level1)} />
        <Row k="Level 2" v={px(zone.level2)} />
        <Row k="Room:Risk" v={zone.rr == null ? '—' : `${zone.rr.toFixed(2)}${zone.lowRoom ? ' (low room)' : ''}`} testid="ob-rr" />
        <Row k="State" v={STATE[zone.state] || zone.state} />
        <Row k="Retests" v={String(zone.touchCount)} />
        <Row k="VWAP side" v={zone.vwapSide ? `${zone.vwapSide} VWAP at formation` : '—'} />
        {zone.reasons.length > 0 && (
          <div className="pt-1.5 text-slate-500">
            <div className="font-semibold text-slate-400">Notes</div>
            <ul className="list-disc pl-4 space-y-0.5">{zone.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        <div className="pt-1.5 text-[10px] text-slate-600">
          Rules v{zone.paramsVersion}. Analytics only, not investment advice.
        </div>
      </div>
    </div>
  );
}
