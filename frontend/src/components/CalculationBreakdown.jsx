import React, { useState } from 'react';

/*
 * One reusable calculation-breakdown view for EVERY ratio.
 *
 * It renders the `breakdown` payload produced by the backend (tools/ratio_breakdown.py) and nothing else:
 * no number is calculated, rounded or looked up here. Every value is a pre-formatted `*_display` string made
 * from the same unrounded `value_raw` the calculation engine used, and `calculation.expression` is the exact
 * arithmetic the engine performed (the backend re-evaluates it and reports `reconciles`).
 */

const BASIS_LABEL = { consolidated: 'Consolidated', standalone: 'Standalone' };

function inputSource(i) {
  const where = [
    i.period,
    [BASIS_LABEL[i.basis] || i.basis, i.statement].filter(Boolean).join(' '),
    !i.statement && i.source ? i.source : null,
    i.page ? `p.${i.page}` : null,
  ].filter(Boolean);
  return where.join(' · ');
}

function Section({ title, children }) {
  return (
    <div className="pt-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">{title}</div>
      {children}
    </div>
  );
}

function InputRow({ i }) {
  const missing = i.value_raw == null;
  const src = inputSource(i);
  return (
    <div className="py-1" data-input={i.fact || i.name}>
      <div className="flex items-baseline gap-2">
        <span className="text-slate-300 flex-1 min-w-0">{i.name}</span>
        <span className="flex-1 border-b border-dotted border-slate-800 translate-y-[-3px] min-w-[12px]" aria-hidden="true" />
        <span className={`nv-num whitespace-nowrap ${missing ? 'text-amber-300/90 italic' : 'text-slate-100 font-semibold'}`}
          title={missing ? undefined : `Unrounded: ${i.value_raw}`}>
          {missing ? 'Not disclosed' : i.value_display}
        </span>
      </div>
      {src && !missing && (
        <div className="text-[10.5px] text-slate-600 leading-snug">
          {src}
        </div>
      )}
      {i.detail && <div className="text-[10.5px] text-slate-600 leading-snug">{i.detail}</div>}
      {missing && i.note && <div className="text-[10.5px] text-amber-300/70">{i.note}</div>}
    </div>
  );
}

function ParentRow({ p }) {
  const [open, setOpen] = useState(false);
  const differs = p.value_calc && p.value_display && p.value_calc !== p.value_display;
  return (
    <div className="py-1" data-parent={p.ratio_key}>
      <div className="flex items-baseline gap-2">
        <span className="text-slate-300 flex-1 min-w-0">{p.label}</span>
        <span className="nv-num text-slate-100 font-semibold whitespace-nowrap">
          {p.value_raw == null ? 'Unavailable' : p.value_display}
        </span>
      </div>
      {differs && (
        <div className="text-[10.5px] text-slate-500">Display value {p.value_display} · calculation value {p.value_calc}</div>
      )}
      {p.breakdown && (
        <button type="button" onClick={() => setOpen((o) => !o)}
          className="text-[10.5px] font-semibold text-blue-400 hover:text-blue-300">
          {open ? 'Hide how this was calculated ▴' : 'Show how this was calculated ▾'}
        </button>
      )}
      {open && p.breakdown && (
        <div className="mt-1 ml-1 pl-2.5 border-l border-slate-800">
          <CalculationBreakdown b={p.breakdown} nested />
        </div>
      )}
    </div>
  );
}

export default function CalculationBreakdown({ b, nested = false }) {
  if (!b) return null;
  const calc = b.calculation;
  const hasMissing = (b.missing || []).length > 0;
  return (
    <div className="space-y-0.5" data-breakdown={b.ratio_key}>
      <Section title="Formula">
        <p className="text-slate-200">{b.formula}</p>
        {!nested && b.definition && <p className="text-[11px] text-slate-500 mt-0.5">{b.definition}</p>}
      </Section>

      {(b.inputs || []).length > 0 && (
        <Section title="Inputs">
          <div>{b.inputs.map((i) => <InputRow key={i.id} i={i} />)}</div>
        </Section>
      )}

      {(b.parents || []).length > 0 && (
        <Section title="Derived from">
          <div>{b.parents.map((p) => <ParentRow key={p.ratio_key} p={p} />)}</div>
        </Section>
      )}

      {(b.steps || []).length > 0 && (
        <Section title="Intermediate">
          {b.steps.map((s) => (
            <div key={s.id} className="py-0.5" data-step={s.id}>
              <div className="text-slate-400">{s.label}{s.formula ? <span className="text-slate-600"> = {s.formula}</span> : null}</div>
              <div className="nv-num text-slate-200">{s.expression} = <span className="font-semibold">{s.result_display}</span></div>
            </div>
          ))}
        </Section>
      )}

      {calc && (
        <Section title="Calculation">
          <div className="nv-num text-slate-100 break-words" data-calculation>
            {calc.expression} = <span className="font-bold">{calc.result_display}</span>
          </div>
        </Section>
      )}

      {b.result && b.result.value_raw != null && (
        <Section title="Result">
          <div className="nv-num text-slate-100">
            <span className="font-bold" data-result>{b.result.value_display}</span>
            {b.result.value_calc && b.result.value_calc !== b.result.value_display && (
              <span className="text-[10.5px] text-slate-500"> · calculation value {b.result.value_calc}</span>
            )}
          </div>
        </Section>
      )}

      {!calc && hasMissing && (
        <p className="text-[11px] text-amber-300/90 pt-2" data-missing>
          {b.missing_message || 'Required input was not disclosed in the source.'} No calculation is shown because it
          would need a number that was not found.
        </p>
      )}
      {!calc && !hasMissing && b.reason && b.result?.value_raw == null && (
        <p className="text-[11px] text-slate-500 pt-2">{b.reason}</p>
      )}
      {b.reconciles === false && (
        <p className="text-[11px] text-rose-300/90 pt-2" data-unreconciled>
          The inputs shown do not reproduce the stored result exactly - treat this breakdown with caution.
        </p>
      )}
      {(b.notes || []).filter((n) => !n.startsWith('The shown inputs')).map((n, k) => (
        <p key={k} className="text-[10.5px] text-slate-500 pt-1">{n}</p>
      ))}
      {!nested && b.source && (
        <Section title="Source"><p className="text-slate-400">{b.source}</p></Section>
      )}
    </div>
  );
}
