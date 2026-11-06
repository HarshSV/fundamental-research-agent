"use client";

import { Check, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CatalogueEntry } from "./patterns";
import { RESISTANCE_ID, isSpecial } from "./patternScan";
import { LIST_SCANNERS } from "./scanners";

function Tick({ checked, label, hint, onChange }: { checked: boolean; label: string; hint?: string; onChange: (v: boolean) => void }) {
  return (
    <label className="flex min-h-[40px] cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-[var(--overlay-weak)] sm:min-h-0" title={hint}>
      <span
        className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors"
        style={{ borderColor: checked ? "#b7b4e7" : "var(--border-default)", background: checked ? "#b7b4e7" : "transparent" }}
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} style={{ color: "var(--on-accent)" }} />}
      </span>
      <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span style={{ color: "var(--text-primary)" }}>{label}</span>
    </label>
  );
}

/**
 * Multiple Scans: tick two or more scanners; the results are the stocks that appear in ALL of them at once (for example
 * Horizontal Resistance and Tight Setup). Chart patterns, Horizontal Resistance and every market-list scanner can be combined.
 */
export function MultiScanModal({
  catalogue, initial, onApply, onClose,
}: {
  catalogue: CatalogueEntry[];
  initial: string[];
  onApply: (ids: string[]) => void;
  onClose: () => void;
}) {
  const [sel, setSel] = useState<string[]>(initial);
  const toggle = (id: string, on: boolean) => setSel((s) => (on ? (s.includes(id) ? s : [...s, id]) : s.filter((x) => x !== id)));
  const patterns = useMemo(() => catalogue.filter((c) => !isSpecial(c.id)), [catalogue]);
  const groups = useMemo(() => {
    const by = new Map<string, { id: string; name: string; hint?: string }[]>();
    by.set("Scanners", [{ id: RESISTANCE_ID, name: "Horizontal Resistance", hint: "Price just under or just through a horizontal resistance" }]);
    for (const s of LIST_SCANNERS) by.set(s.group, [...(by.get(s.group) ?? []), { id: s.id, name: s.name, hint: s.definition }]);
    return [...by.entries()];
  }, []);
  const byCategory = useMemo(() => {
    const by = new Map<string, CatalogueEntry[]>();
    for (const c of patterns) by.set(c.category, [...(by.get(c.category) ?? []), c]);
    return [...by.entries()];
  }, [patterns]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[4vh]" role="dialog" aria-modal="true" aria-label="Multiple scans">
      <div className="absolute inset-0" style={{ background: "var(--backdrop)", backdropFilter: "blur(6px)" }} onMouseDown={onClose} />
      <div className="relative w-full max-w-[760px]">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute -right-2 -top-2 z-10 flex h-9 w-9 items-center justify-center rounded-full text-white shadow-lg"
          style={{ background: "#f97316" }}
        >
          <X className="h-4 w-4" />
        </button>
        <div className="flex max-h-[88vh] flex-col overflow-hidden rounded-2xl border" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "var(--shadow-lg, 0 20px 60px rgba(0,0,0,.45))" }}>
          <div className="border-b px-6 pb-4 pt-5" style={{ borderColor: "var(--border-subtle)" }}>
            <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: "var(--text-tertiary)" }}>Scanner · combine</div>
            <h2 className="mt-1 text-xl font-semibold">Multiple Scans</h2>
            <p className="mt-1.5 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              Tick two or more scanners. Only stocks that appear in <b>all</b> of them are shown, so the list is shorter and stronger.
            </p>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {groups.map(([g, list]) => (
              <div key={g} className="mb-3">
                <div className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: "var(--text-tertiary)" }}>{g}</div>
                <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                  {list.map((x) => <Tick key={x.id} checked={sel.includes(x.id)} label={x.name} hint={x.hint} onChange={(on) => toggle(x.id, on)} />)}
                </div>
              </div>
            ))}
            {byCategory.map(([cat, list]) => (
              <div key={cat} className="mb-3">
                <div className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: "var(--text-tertiary)" }}>Chart patterns · {cat}</div>
                <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                  {list.map((c) => <Tick key={c.id} checked={sel.includes(c.id)} label={c.name} hint={c.definition} onChange={(on) => toggle(c.id, on)} />)}
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3 border-t px-6 py-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <button type="button" onClick={() => setSel([])} className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              Clear ({sel.length})
            </button>
            <button
              type="button"
              disabled={sel.length < 2}
              onClick={() => onApply(sel)}
              className="rounded-lg px-8 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[var(--btn-primary-hover)] disabled:opacity-40"
              style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
              title={sel.length < 2 ? "Pick at least two scanners" : undefined}
            >
              {sel.length < 2 ? "Pick at least 2" : `Scan ${sel.length} together`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
