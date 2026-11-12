"use client";

import { Check, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface LineOption {
  id: string;
  label: string;
  hint?: string;
  color: string;
  /** why it cannot be drawn right now (no plan for this stock, intraday chart...) */
  disabled?: string;
}

export interface LineGroup {
  title: string;
  options: LineOption[];
  note?: string;
}

/** The chart's filter: a small button that opens a list of the lines the chart can draw, each switched on or off. Closes on a click elsewhere or Escape. */
export function ChartLinesMenu({ groups, on, onToggle, onReset, count }: { groups: LineGroup[]; on: Record<string, boolean>; onToggle: (id: string) => void; onReset: () => void; count: number }) {
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const close = () => setOpen(false);
  const toggle = () => {
    if (open) return close();
    // open towards the side with room: the button can sit at the left or the right of the controls row
    const r = box.current?.getBoundingClientRect();
    if (r) setAlignRight(r.left + r.width / 2 > window.innerWidth / 2);
    setOpen(true);
  };
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && close();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  });
  return (
    <div ref={box} className="relative">
      <button
        onClick={toggle}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm hover:opacity-80"
        style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)", background: "var(--surface-1)" }}
      >
        <SlidersHorizontal className="h-4 w-4" aria-hidden />
        Chart lines
        {count > 0 && <span className="rounded-full px-1.5 text-[11px] font-semibold" style={{ background: "var(--accent-surface, var(--overlay))", color: "var(--accent)" }}>{count}</span>}
      </button>
      {open && (
        <div
          className={`menu-pop absolute top-full z-30 mt-2 w-[min(23rem,calc(100vw-2rem))] rounded-lg border p-3 text-sm shadow-xl ${alignRight ? "right-0" : "left-0"}`}
          style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", transformOrigin: alignRight ? "top right" : "top left" }}
        >
          {groups.map((g) => (
            <div key={g.title} className="mb-2.5">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>{g.title}</div>
              <div className="flex flex-wrap gap-1.5">
                {g.options.map((o) => {
                  const checked = Boolean(on[o.id]) && !o.disabled;
                  return (
                    <button
                      key={o.id}
                      type="button"
                      disabled={Boolean(o.disabled)}
                      aria-pressed={checked}
                      onClick={() => onToggle(o.id)}
                      title={o.disabled ?? o.hint}
                      className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                      style={{ borderColor: checked ? o.color : "var(--border-default)", background: checked ? `${o.color}26` : "transparent", color: "var(--text-primary)" }}
                    >
                      <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full" style={{ background: checked ? o.color : "transparent", border: checked ? "none" : `1.5px solid ${o.color}` }}>
                        {checked && <Check className="h-2.5 w-2.5" strokeWidth={3} style={{ color: "#fff" }} aria-hidden />}
                      </span>
                      {o.label}
                    </button>
                  );
                })}
              </div>
              {g.note && <p className="mt-1.5 text-[11px] leading-snug" style={{ color: "var(--text-tertiary)" }}>{g.note}</p>}
            </div>
          ))}
          <button type="button" onClick={onReset} className="w-full rounded-md py-1 text-xs underline" style={{ color: "var(--text-secondary)" }}>Back to the default (today&apos;s plan only)</button>
        </div>
      )}
    </div>
  );
}
