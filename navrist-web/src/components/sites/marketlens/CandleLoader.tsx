"use client";

// [open, high, low, close] as percentages of the loader height (higher = further up).
const CANDLES: ReadonlyArray<readonly [number, number, number, number]> = [
  [40, 70, 30, 60], [55, 80, 40, 48], [45, 75, 35, 65], [30, 68, 22, 58], [48, 72, 30, 38],
  [28, 60, 18, 50], [20, 55, 10, 30], [18, 48, 8, 40], [12, 42, 4, 34],
];

/** A row of candles that builds left to right in a loop. Only transform and opacity animate, so it stays smooth; it stands still when the
 *  visitor asks for reduced motion. */
export function CandleLoader({ label, height = 96 }: { label?: string; height?: number }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-4" role="status" aria-live="polite">
      <style>{`
        @keyframes nv-candle-rise{0%{opacity:0;transform:translateY(10px) scaleY(.4)}25%,70%{opacity:1;transform:translateY(0) scaleY(1)}100%{opacity:0;transform:translateY(-4px) scaleY(1)}}
        .nv-candle{animation:nv-candle-rise 1.8s cubic-bezier(.4,0,.2,1) infinite both}
        @media (prefers-reduced-motion:reduce){.nv-candle{animation:none;opacity:1}}
      `}</style>
      <div className="flex items-center gap-2.5" style={{ height }} aria-hidden>
        {CANDLES.map(([o, hi, lo, c], i) => {
          const col = c >= o ? "var(--gain, #10b981)" : "var(--loss, #ef4444)";
          return (
            <div key={i} className="nv-candle relative h-full w-3.5" style={{ animationDelay: `${i * 110}ms` }}>
              <div className="absolute left-1/2 w-0.5 -translate-x-1/2" style={{ top: `${100 - hi}%`, bottom: `${lo}%`, background: col }} />
              <div className="absolute inset-x-0 rounded-sm" style={{ top: `${100 - Math.max(o, c)}%`, bottom: `${Math.min(o, c)}%`, background: col }} />
            </div>
          );
        })}
      </div>
      {label && <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{label}</span>}
    </div>
  );
}
