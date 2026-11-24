"use client";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

const EASE = "cubic-bezier(.22,.61,.36,1)";
const ON = "#10b981";

/** On/off switch: the knob glides and the track fades to green. */
export function Switch({ on, onChange, label, title }: { on: boolean; onChange: () => void; label?: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onChange}
      title={title}
      className="flex min-h-[40px] items-center gap-2.5 text-sm sm:min-h-0"
      style={{ color: "var(--text-secondary)" }}
    >
      <span className="relative h-[20px] w-[36px] shrink-0 rounded-full" style={{ background: on ? ON : "var(--overlay)", transition: `background 320ms ${EASE}` }}>
        <span
          className="absolute left-[2px] top-[2px] h-4 w-4 rounded-full bg-white"
          style={{ transform: `translateX(${on ? 16 : 0}px)`, transition: `transform 320ms ${EASE}`, boxShadow: "0 1px 3px rgba(0,0,0,0.35)" }}
        />
      </span>
      {label}
    </button>
  );
}

const SIZE = {
  sm: "px-2.5 py-3 text-[11px] sm:py-1",
  md: "px-2 py-2.5 text-xs sm:px-3.5 sm:py-1.5",
  lg: "px-4 py-2.5 text-sm sm:py-2",
  icon: "px-3 py-2.5 sm:px-2.5 sm:py-1.5",
} as const;

/** Segmented control with equal-width options: a highlight slides under the chosen one. */
export function SlidingTabs<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = "md",
}: {
  options: { id: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (id: T) => void;
  ariaLabel: string;
  size?: keyof typeof SIZE;
}) {
  const n = options.length;
  const idx = options.findIndex((o) => o.id === value);
  const box = useRef<HTMLDivElement>(null);
  // when the row is squeezed the options are no longer equal width, so the highlight follows the chosen button itself
  const [pos, setPos] = useState<{ left: number; width: number } | null>(null);
  useLayoutEffect(() => {
    const measure = () => {
      const on = box.current?.querySelector<HTMLElement>('[aria-pressed="true"]');
      setPos(on ? { left: on.offsetLeft, width: on.offsetWidth } : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [value, n]);
  return (
    <div ref={box} className="relative inline-grid rounded-lg p-[3px]" style={{ background: "var(--overlay-weak)", gridAutoFlow: "column", gridAutoColumns: "1fr" }} role="group" aria-label={ariaLabel}>
      <span
        aria-hidden
        className="absolute inset-y-[3px] left-0 rounded-md"
        style={{
          width: pos ? pos.width : `calc((100% - 6px) / ${n})`,
          background: "var(--text-primary)",
          opacity: idx < 0 ? 0 : 0.16,
          transform: pos ? `translateX(${pos.left}px)` : `translateX(calc(3px + ${Math.max(idx, 0) * 100}%))`,
          transition: `transform 320ms ${EASE}, opacity 250ms ease`,
        }}
      />
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          aria-pressed={o.id === value}
          title={o.title}
          className={`relative z-10 flex items-center justify-center whitespace-nowrap font-medium leading-none ${SIZE[size]}`}
          style={{ color: o.id === value ? "var(--text-primary)" : "var(--text-tertiary)", transition: "color 250ms ease" }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
