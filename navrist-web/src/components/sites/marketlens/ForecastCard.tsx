"use client";

import { useEffect, useRef, useState } from "react";
import { SlidingTabs, Switch } from "./controls";
import { ArrowDownRight, ArrowUpRight, ChevronDown, Minus, Newspaper, Sparkles } from "lucide-react";
import { ForecastFan } from "./ForecastFan";
import { ForecastStrip } from "./ForecastStrip";
import { fetchJson } from "@/lib/api";
import { basisNote, type Events, type Forecast, type Horizon, type Odds, type Plan, type Replay, type TradeBlock } from "./forecast";

const GAIN = "var(--gain)";
const LOSS = "var(--loss)";
const MUTED = "var(--text-tertiary)";
const SOFT = "var(--text-secondary)";

const n = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const inr = (v: number | null | undefined, d = 2) => (v == null ? "—" : `₹${n(v, d)}`);
const sgn = (v: number | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${n(v, 1)}%`);

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border p-5" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-0)" }}>
      <div className="mb-3 text-sm font-semibold">{title}</div>
      {children}
    </div>
  );
}

/** True once the element has scrolled into view (once). */
function useInView<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") {
      const t = setTimeout(() => setSeen(true), 0);
      return () => clearTimeout(t);
    }
    const io = new IntersectionObserver((e) => e[0]?.isIntersecting && setSeen(true), { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  return { ref, seen };
}

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Counts from 0 up to `target` once `play` turns true (after `delay` ms). */
function useCountUp(target: number, play: boolean, delay: number, dur = 850) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!play) return;
    if (reduced()) {
      const t = setTimeout(() => setV(target), 0);
      return () => clearTimeout(t);
    }
    let raf = 0;
    const t0 = performance.now() + delay;
    const tick = (now: number) => {
      const p = Math.min(1, Math.max(0, (now - t0) / dur));
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, play, delay, dur]);
  return v;
}

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

/** One label / value line of the facts list; never split across columns. */
function Fact({ label, value, tone }: { label: string; value: string; tone: "good" | "bad" | null }) {
  return (
    <div className="flex justify-between gap-4 break-inside-avoid border-b py-2 text-sm last:border-b-0" style={{ borderColor: "var(--border-subtle)" }}>
      <span style={{ color: MUTED }}>{label}</span>
      <span className="nv-num text-right font-medium" style={{ color: tone === "good" ? GAIN : tone === "bad" ? LOSS : "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

function Outlook({ h, index }: { h: Horizon; index: number }) {
  const { ref, seen } = useInView<HTMLDivElement>();
  const delay = index * 220;
  const up = useCountUp(h.up ?? 0, seen, delay + 200);
  const flat = useCountUp(h.flat ?? 0, seen, delay + 200);
  const down = useCountUp(h.down ?? 0, seen, delay + 200);
  const fade = (extra: number): React.CSSProperties => ({
    opacity: seen ? 1 : 0, transform: seen ? "none" : "translateY(10px)",
    transition: reduced() ? "none" : `opacity 600ms ${EASE} ${delay + extra}ms, transform 600ms ${EASE} ${delay + extra}ms`,
  });
  const word = h.call === "up" ? "Up" : h.call === "down" ? "Down" : h.call === "even" ? "Even" : "No call";
  const color = h.call === "up" ? GAIN : h.call === "down" ? LOSS : SOFT;
  return (
    <div ref={ref} className="border-t py-4 first:border-t-0 first:pt-0" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{h.label}</span>
        <span className="text-lg font-semibold" style={{ color, ...fade(450) }}>
          {word}
          {h.conviction && <span className="ml-2 text-xs font-normal" style={{ color: MUTED }}>{h.conviction} lean</span>}
        </span>
      </div>
      {h.up == null ? (
        <p className="mt-1 text-sm" style={{ color: MUTED }}>{h.reason ?? "Not enough history to measure."}</p>
      ) : (
        <>
          <div className="relative mt-2 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--overlay)" }} role="img" aria-label={`Up ${h.up}%, flat ${h.flat}%, down ${h.down}%`}>
            <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: seen ? `${h.up}%` : 0, background: "var(--gain)", transition: reduced() ? "none" : `width 1100ms ${EASE} ${delay}ms` }} />
            <div className="absolute inset-y-0 right-0 rounded-full" style={{ width: seen ? `${h.down}%` : 0, background: "var(--loss)", transition: reduced() ? "none" : `width 1100ms ${EASE} ${delay}ms` }} />
          </div>
          <div className="mt-2 flex justify-between text-sm" style={fade(500)}>
            <span style={{ color: GAIN }}>Up {up}%</span>
            <span style={{ color: MUTED }}>Flat {flat}%</span>
            <span style={{ color: LOSS }}>Down {down}%</span>
          </div>
          {h.price_low != null && (
            <p className="mt-2 text-sm" style={fade(700)}>
              <span style={{ color: MUTED }}>Likely price </span>
              <b className="nv-num">{inr(h.price_low)} to {inr(h.price_high)}</b>
              <span style={{ color: MUTED }}> · middle {inr(h.price_mid)}</span>
            </p>
          )}
          <p className="mt-1 text-xs" style={{ color: MUTED, ...fade(800) }}>
            Typical move {sgn(h.p10)} to {sgn(h.p90)}, from {h.samples?.toLocaleString("en-IN")}{" "}
            {h.basis === "state" ? "past days in the same trend state" : h.basis === "sessions" ? "past sessions at this time of day" : "past days"}
          </p>
        </>
      )}
    </div>
  );
}

/** A stacked bar with a legend underneath: each part is a count or a percentage, drawn in proportion. */
function Split({ title, note, parts }: { title: string; note?: string; parts: { label: string; value: number; shown: string; color: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (total <= 0) return null;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="font-medium" style={{ color: SOFT }}>{title}</span>
        {note && <span style={{ color: MUTED }}>{note}</span>}
      </div>
      <div className="mt-2 flex h-2 overflow-hidden rounded-full" style={{ background: "var(--overlay)" }} role="img" aria-label={parts.map((p) => `${p.label} ${p.shown}`).join(", ")}>
        {parts.map((p) => (p.value > 0 ? <div key={p.label} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} /> : null))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        {parts.map((p) => (
          <span key={p.label} className="flex items-center gap-1.5" style={{ color: MUTED }}>
            <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            {p.label} <b className="nv-num" style={{ color: "var(--text-primary)" }}>{p.shown}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

const NEUTRAL = "var(--text-tertiary)";

function OddsLine({ odds, replay, daily }: { odds?: Odds | null; replay?: Replay | null; daily: boolean }) {
  const blocks: React.ReactNode[] = [];
  if (odds && odds.target != null && odds.stop != null) {
    blocks.push(
      <Split key="sim" title="Simulated outcomes" note={`${n(odds.paths, 0)} simulated paths · entry reached in ${odds.enters}%`}
        parts={[
          { label: "Target first", value: odds.target, shown: `${odds.target}%`, color: "var(--gain)" },
          { label: "Stop first", value: odds.stop, shown: `${odds.stop}%`, color: "var(--loss)" },
          { label: "Neither", value: odds.open ?? 0, shown: `${odds.open ?? 0}%`, color: NEUTRAL },
        ]} />,
    );
  }
  if (replay && !daily && replay.trades != null && replay.target != null) {
    blocks.push(
      <Split key="rep" title="The same plan on past days" note={replay.session_rule ? `${replay.sessions} past days in this state` : `last ${replay.sessions} sessions · ${replay.trades} trades`}
        parts={[
          { label: "Target", value: replay.target, shown: String(replay.target), color: "var(--gain)" },
          { label: "Stop", value: replay.stop ?? 0, shown: String(replay.stop ?? 0), color: "var(--loss)" },
          { label: "Neither", value: replay.open ?? 0, shown: String(replay.open ?? 0), color: NEUTRAL },
        ]} />,
    );
  }
  if (replay && daily && replay.n != null) {
    const note = `${replay.trend_rule ? "past days in this state" : "past appearances"} · ${replay.n}`;
    if (replay.target != null) {
      blocks.push(
        <Split key="rep" title="The same rule on past days" note={note}
          parts={[
            { label: "Target", value: replay.target, shown: String(replay.target), color: "var(--gain)" },
            { label: "Stop", value: replay.stop ?? 0, shown: String(replay.stop ?? 0), color: "var(--loss)" },
            { label: "Neither", value: replay.open ?? 0, shown: String(replay.open ?? 0), color: NEUTRAL },
          ]} />,
      );
    } else {
      blocks.push(
        <div key="rep" className="text-xs">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-medium" style={{ color: SOFT }}>History of this setup</span>
            <span style={{ color: MUTED }}>{note}</span>
          </div>
          <p className="mt-1.5 text-sm" style={{ color: SOFT }}>
            {replay.win == null ? (
              <span style={{ color: MUTED }}>Too few cases to measure.</span>
            ) : (
              <>
                Up after {replay.horizon} sessions <b style={{ color: replay.win >= 50 ? GAIN : LOSS }}>{replay.win}%</b> of the time, typical move{" "}
                <b style={{ color: (replay.median ?? 0) >= 0 ? GAIN : LOSS }}>{sgn(replay.median ?? undefined)}</b>
              </>
            )}
          </p>
        </div>,
      );
    }
  }
  if (!blocks.length) return null;
  return <div className="mt-5 space-y-4 border-t pt-5" style={{ borderColor: "var(--border-subtle)" }}>{blocks}</div>;
}

function EdgeLine({ b }: { b: TradeBlock }) {
  if (!b.edge) return null;
  const v = b.edge.value;
  const color = b.edge.label === "favourable" ? GAIN : b.edge.label === "against" ? LOSS : SOFT;
  const word = b.edge.label === "favourable" ? "Odds favour this trade" : b.edge.label === "against" ? "Odds are against this trade" : "Odds are about even";
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-sm" style={{ background: "var(--overlay-weak)" }}>
      <b style={{ color }}>{word}</b>
      <span className="text-xs" style={{ color: MUTED }}>{v > 0 ? "+" : ""}{n(v)} gained for every 1 risked</span>
    </div>
  );
}

/** Stop, entry and targets on one price line, so the trade can be read at a glance. */
function Ladder({ p }: { p: Plan }) {
  const pts = [
    { k: "stop", price: p.stop, color: "var(--loss)" },
    { k: "entry", price: p.entry, color: "var(--text-primary)" },
    ...p.targets.slice(0, 2).map((t, i) => ({ k: `t${i}`, price: t.price, color: "var(--gain)" })),
  ];
  const lo = Math.min(...pts.map((x) => x.price));
  const hi = Math.max(...pts.map((x) => x.price));
  if (!(hi > lo)) return null;
  const at = (v: number) => `${4 + ((v - lo) / (hi - lo)) * 92}%`;
  const seg = (a: number, b: number, color: string) => {
    const l = Math.min(a, b);
    const r = Math.max(a, b);
    return <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full" style={{ left: at(l), width: `calc(${at(r)} - ${at(l)})`, background: color, opacity: 0.55 }} />;
  };
  const far = p.targets[Math.min(1, p.targets.length - 1)]?.price ?? p.entry;
  return (
    <div className="relative mt-5 h-5" aria-hidden>
      <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full" style={{ background: "var(--overlay)" }} />
      {seg(p.stop, p.entry, "var(--loss)")}
      {seg(p.entry, far, "var(--gain)")}
      {pts.map((x) => (
        <span key={x.k} className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2" style={{ left: at(x.price), background: x.color, borderColor: "var(--surface-1)" }} />
      ))}
    </div>
  );
}

function Tile({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
  return (
    <div className="rounded-lg px-3 py-2.5" style={{ background: "var(--overlay-weak)" }}>
      <div className="text-[11px] uppercase tracking-wide" style={{ color: MUTED }}>{label}</div>
      <div className="nv-num mt-0.5 text-base font-semibold" style={{ color }}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-snug" style={{ color: MUTED }}>{sub}</div>}
    </div>
  );
}

function Trade({ title, b, daily }: { title: string; b: TradeBlock; daily: boolean }) {
  const p: Plan | null | undefined = b.plan;
  const t1 = p?.targets[0];
  const long = p?.side === "long";
  const accent = p ? (long ? GAIN : LOSS) : SOFT;
  return (
    <div className="flex h-full flex-col rounded-2xl border p-5" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-0)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium" style={{ color: SOFT }}>{title}</span>
        <span className="rounded-full px-3 py-1 text-xs font-semibold" style={{ color: accent, background: "var(--overlay-weak)" }}>
          {p ? `${p.action} ${inr(p.entry)}` : "No trade"}
        </span>
      </div>
      {p && t1 ? (
        <>
          <Ladder p={p} />
          <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Tile label="Stop" value={inr(p.stop)} sub={`${n(p.risk_pct)}% risk · ${inr(p.risk_per_share)} a share`} color="var(--loss)" />
            <Tile label="Entry" value={inr(p.entry)} sub={p.action} color="var(--text-primary)" />
            {p.targets.slice(0, 2).map((t, i) => (
              <Tile key={t.r} label={`Target ${i + 1}`} value={inr(t.price)} sub={`${t.r}× the risk`} color="var(--gain)" />
            ))}
          </div>
          <EdgeLine b={b} />
          <ul className="mt-4 space-y-1.5 text-xs leading-relaxed" style={{ color: MUTED }}>
            <li>Stop at {p.stop_basis}.</li>
            <li>{p.exit_rule}</li>
            {b.note && <li>{b.note}</li>}
            {p.warnings.map((w) => (
              <li key={w} style={{ color: LOSS }}>{w}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-4 text-sm leading-relaxed" style={{ color: SOFT }}>{b.decision.reason}</p>
      )}
      {(b.odds || b.replay) && <OddsLine odds={b.odds} replay={b.replay} daily={daily} />}
    </div>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

/** A small "News" button that opens a light popover with the company's filings (NSE / BSE) and headlines (Google News). It reads
 *  them only when first opened. Nothing is scored or interpreted. */
export function News({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false); // mounted
  const [shown, setShown] = useState(false); // fade/slide state
  const [ev, setEv] = useState<Events | null>(null);
  const [failed, setFailed] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const loaded = useRef(false);
  const close = () => {
    setShown(false);
    setTimeout(() => setOpen(false), 200);
  };
  const toggle = () => {
    if (open) return close();
    setOpen(true);
    requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)));
    if (!loaded.current) {
      loaded.current = true;
      fetchJson<Events>(`/api/v1/events/${symbol}`, { retries: 1 }).then(setEv).catch(() => setFailed(true));
    }
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
  const down = ev ? Object.entries(ev.sources).filter(([, v]) => v === "unavailable").map(([k]) => k) : [];
  return (
    <div ref={box}>
      <button onClick={toggle} aria-expanded={open} className="flex min-h-10 items-center gap-1.5 text-sm hover:opacity-80 sm:min-h-0" style={{ color: SOFT }}>
        <Newspaper className="h-4 w-4" aria-hidden />
        News
      </button>
      {open && (
        <div
          className="absolute inset-x-0 top-full z-30 mt-2 max-h-[26rem] overflow-y-auto overflow-x-hidden sm:right-auto sm:left-0 sm:w-[23rem] rounded-lg border p-3 text-xs shadow-xl"
          style={{
            background: "var(--surface-1)", borderColor: "var(--border-default)",
            opacity: shown ? 1 : 0, transform: shown ? "none" : "translateY(-6px) scale(0.98)", transformOrigin: "top left",
            transition: reduced() ? "none" : `opacity 220ms ${EASE}, transform 220ms ${EASE}`,
          }}
        >
          {failed ? (
            <p style={{ color: MUTED }}>News could not be read right now.</p>
          ) : !ev ? (
            <div className="h-12 animate-pulse rounded" style={{ background: "var(--overlay-weak)" }} />
          ) : (
            <>
              {ev.upcoming.length > 0 && (
                <p className="mb-2.5">
                  <span style={{ color: MUTED }}>Board meeting </span>
                  <b>{day(ev.upcoming[0].date)}</b>
                  <span style={{ color: SOFT }}> · {ev.upcoming[0].purpose}</span>
                </p>
              )}
              {ev.items.length === 0 ? (
                <p style={{ color: MUTED }}>Nothing in the last 30 days.</p>
              ) : (
                <ul className="space-y-2">
                  {ev.items.map((i) => (
                    <li key={i.source + i.ts + i.title} className="flex gap-2.5">
                      <span className="w-12 shrink-0 whitespace-nowrap" style={{ color: MUTED }}>{day(i.ts)}</span>
                      <span className="min-w-0 flex-1 leading-snug">
                        {i.link ? <a href={i.link} target="_blank" rel="noopener noreferrer" className="hover:underline">{i.title}</a> : i.title}
                        <span className="ml-1.5" style={{ color: MUTED }}>{i.source === "News" ? i.category : i.source}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {down.length > 0 && <p className="mt-2.5" style={{ color: MUTED }}>Could not be read: {down.join(", ")}.</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

const SPAN: Record<Horizon["id"], string> = { session: "the next session", week: "the next 5 sessions", month: "the next 20 sessions" };
const SPAN_TAB: Record<Horizon["id"], string> = { session: "1 day", week: "1 week", month: "1 month" };

/** The answer first: one sentence, how sure we are, and where the price should land. Everything else sits behind "See the reasoning". */
function Verdict({ data, chart }: { data: Forecast; chart: boolean }) {
  const [hid, setHid] = useState<Horizon["id"]>("week");
  const { ref, seen } = useInView<HTMLDivElement>();
  // the forecast chart (switched on beside "Highlights") slides in over this block from the left, and slides back out to the left when switched off
  const [mounted, setMounted] = useState(false);
  const [slideIn, setSlideIn] = useState(false);
  const [plays, setPlays] = useState(0);
  const hasFan = Boolean(data.fan && data.fan.paths.length >= 20);
  useEffect(() => {
    // mount the panel off to the left first, then let it slide in on the next frame (and out again when switched off)
    let id2 = 0;
    const id1 = requestAnimationFrame(() => {
      if (chart && hasFan) {
        setMounted(true);
        setPlays((n) => n + 1);
        id2 = requestAnimationFrame(() => setSlideIn(true));
      } else setSlideIn(false);
    });
    return () => {
      cancelAnimationFrame(id1);
      cancelAnimationFrame(id2);
    };
  }, [chart, hasFan]);
  const slide = reduced() ? "none" : `transform 640ms ${EASE}, opacity 420ms ease`;
  const h = data.outlook.find((x) => x.id === hid) ?? data.outlook[0];
  const span = SPAN[h.id];
  const dp = (h.price_mid ?? data.price ?? 1000) < 100 ? 2 : 0;      // a ₹16 stock needs its paise
  const call = h.up == null ? null : h.call;
  const color = call === "up" ? GAIN : call === "down" ? LOSS : SOFT;
  const Icon = call === "up" ? ArrowUpRight : call === "down" ? ArrowDownRight : Minus;
  const odds = h.up == null ? "" : `: ${h.up}% up, ${h.down}% down`;
  const headline = h.up == null ? `Not enough history to forecast ${span}` : call === "up" ? `Leans up over ${span}${odds}` : call === "down" ? `Leans down over ${span}${odds}` : `Too close to call over ${span}${odds}`;
  const lean = h.up == null ? null : call === "even" || call == null ? "The odds are about even" : `${h.conviction ? h.conviction[0].toUpperCase() + h.conviction.slice(1) : "Clear"} lean`;
  return (
    <div ref={ref} className="relative overflow-hidden rounded-2xl border" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
      <div className="p-6 md:p-8" style={{ transform: slideIn ? "translateX(7%)" : "none", opacity: slideIn ? 0 : 1, transition: slide, pointerEvents: slideIn ? "none" : "auto" }} aria-hidden={slideIn}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full" style={{ background: "var(--overlay-weak)", color, transition: "color 300ms ease" }}>
            <Icon className="h-6 w-6" aria-hidden />
          </span>
          <div className="min-w-0">
            <div key={h.id} className="nv-rise text-xl font-semibold leading-snug md:text-2xl" style={{ color }}>{headline}</div>
            {lean && (
              <div className="mt-1 text-sm" style={{ color: MUTED }}>
                {lean}
                {h.samples ? ` · based on ${h.samples.toLocaleString("en-IN")} similar past ${h.basis === "sessions" ? "sessions" : "days"}` : ""}
              </div>
            )}
          </div>
        </div>
        <SlidingTabs ariaLabel="Forecast span" size="sm" value={hid} onChange={setHid} options={data.outlook.map((x) => ({ id: x.id, label: SPAN_TAB[x.id] }))} />
      </div>

      {h.up == null ? (
        <p className="mt-5 text-sm" style={{ color: MUTED }}>{h.reason ?? "Not enough history to measure."}</p>
      ) : (
        <div key={h.id + "-body"} className="nv-rise">
          <div className="mt-6 flex h-2 overflow-hidden rounded-full" style={{ background: "var(--overlay)" }} role="img" aria-label={`Up ${h.up}%, flat ${h.flat}%, down ${h.down}%`}>
            <div style={{ width: seen ? `${h.up}%` : 0, background: "var(--gain)", transition: reduced() ? "none" : `width 900ms ${EASE}` }} />
            <div style={{ width: seen ? `${h.flat}%` : 0, background: "var(--text-tertiary)", opacity: 0.45, transition: reduced() ? "none" : `width 900ms ${EASE}` }} />
            <div style={{ width: seen ? `${h.down}%` : 0, background: "var(--loss)", transition: reduced() ? "none" : `width 900ms ${EASE}` }} />
          </div>
          <p className="mt-3 text-sm" style={{ color: SOFT }}>
            Out of 100 similar past setups, <b style={{ color: GAIN }}>{h.up}</b> went up, <b>{h.flat}</b> stayed flat and <b style={{ color: LOSS }}>{h.down}</b> went down.{h.flat_band_pct != null ? <span style={{ color: MUTED }}> “Flat” means a move smaller than ±{h.flat_band_pct}% over {span}.</span> : null}
          </p>
          {h.price_low != null && h.price_high != null && (
            <p className="mt-2 text-sm" style={{ color: SOFT }}>
              Most likely range: <b className="nv-num" style={{ color: "var(--text-primary)" }}>{inr(h.price_low, dp)} to {inr(h.price_high, dp)}</b>
              {h.price_mid != null && <span style={{ color: MUTED }}> · middle {inr(h.price_mid, dp)}</span>}
            </p>
          )}
        </div>
      )}
      </div>
      {mounted && hasFan && (
        <div className="absolute inset-0 p-4 md:px-8 md:py-6" style={{ transform: slideIn ? "none" : "translateX(-104%)", opacity: slideIn ? 1 : 0, transition: slide, pointerEvents: slideIn ? "auto" : "none", background: "var(--surface-1)" }} aria-hidden={!slideIn}>
          <ForecastFan data={data} play={plays} />
        </div>
      )}
    </div>
  );
}

/** The one Forecast section on the stock page: outlook, trade plan with replay odds, levels, evidence and position size. */
export function ForecastCard({
  data, error, showLevels, onToggleLevels, chart = false,
}: { data: Forecast | null; error: boolean; showLevels: boolean; onToggleLevels: () => void; chart?: boolean }) {
  return <ForecastBody data={data} error={error} showLevels={showLevels} onToggleLevels={onToggleLevels} chart={chart} />;
}

/** One folding line: a label with a down arrow that turns over when it is open. */
function FoldRow({ label, open, onClick }: { label: string; open: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} aria-expanded={open} className="flex w-full min-h-12 items-center justify-between gap-3 border-t py-3 text-left text-sm font-medium hover:opacity-80" style={{ borderColor: "var(--border-subtle)", color: SOFT }}>
      <span>{label}</span>
      <ChevronDown className="h-4 w-4 shrink-0" style={{ transform: open ? "rotate(180deg)" : "none", transition: reduced() ? "none" : "transform 400ms ease" }} aria-hidden />
    </button>
  );
}

function ForecastBody({
  data, error, showLevels, onToggleLevels, chart,
}: { data: Forecast | null; error: boolean; showLevels: boolean; onToggleLevels: () => void; chart: boolean }) {
  // two folding lines under the verdict; opening one closes the other, so only one is on show at a time
  const [panel, setPanel] = useState<"plan" | "why" | null>(null);
  const pick = (p: "plan" | "why") => setPanel((cur) => (cur === p ? null : p));
  if (error) return <p className="text-sm" style={{ color: MUTED }}>The forecast could not be worked out for this stock right now.</p>;
  if (data === null) return <div className="h-40 animate-pulse rounded-lg" style={{ background: "var(--overlay-weak)" }} aria-label="Working out the forecast" />;
  if (!data.outlook) return <p className="text-sm" style={{ color: MUTED }}>No price history could be read for this stock under this symbol (it may be newly listed or have been renamed), so no forecast can be made. News is still available above.</p>;
  const hasLevels = Boolean(data.today.setup?.range_high != null || data.today.plan || data.swing.plan);
  return (
    <div>
      <Verdict data={data} chart={chart} />
      {basisNote(data) && <p className="mt-3 text-xs" style={{ color: MUTED }}>{basisNote(data)}{data.forecast_basis ? " The odds are the index's, applied to this fund's price; a trade plan needs the fund's own history." : ""}</p>}

      <div className="mt-5 border-b" style={{ borderColor: "var(--border-subtle)" }}>
        <FoldRow label="When to buy and when to get out" open={panel === "plan"} onClick={() => pick("plan")} />
        {panel === "plan" && (
          <div className="nv-rise pb-6 pt-2">
            <div className="grid items-stretch gap-5 lg:grid-cols-2">
              <Trade title={data.market_open && !data.session_late ? "Today" : "Next session"} b={data.today} daily={false} />
              <Trade title="Swing, up to 10 sessions" b={data.swing} daily />
            </div>
          </div>
        )}
        <FoldRow label="See the reasoning" open={panel === "why"} onClick={() => pick("why")} />
      </div>

      {panel === "why" && (
        <div className="nv-rise mt-6">
          <div className="relative mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" style={{ color: MUTED }}>
            <span>{data.market_open ? "Market open" : "Market closed"}</span>
            {data.segment && <span>{data.segment}</span>}
            {data.adr20_pct != null && <span>Typical daily range {n(data.adr20_pct)}%</span>}
            <span className="ml-auto flex items-center gap-5">
              {hasLevels && <Switch on={showLevels} onChange={onToggleLevels} label="Levels on chart" />}
            </span>
          </div>
          <div className="grid items-start gap-5 lg:grid-cols-2">
            <Panel title="Outlook by horizon">
              {data.outlook.map((h, i) => <Outlook key={data.symbol + h.id} h={h} index={i} />)}
            </Panel>
            {data.levels && data.levels.length > 0 && (
              <Panel title="Levels to watch">
                {data.levels.map((e) => <Fact key={e.label} label={e.label} value={e.value} tone={e.tone} />)}
              </Panel>
            )}
          </div>
          <div className="mt-5">
            <Panel title="What the forecast rests on">
              <div className="md:columns-2 md:gap-x-12">
                {(data.evidence ?? []).map((e) => <Fact key={e.label} label={e.label} value={e.value} tone={e.tone} />)}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}

/** A small "Highlights" button beside News: the next-session, 5-session and 20-session forecasts in a light popup. */
export function Highlights({ data, loading, error }: { data: Forecast | null; loading: boolean; error: boolean }) {
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const close = () => {
    setShown(false);
    setTimeout(() => setOpen(false), 200);
  };
  const toggle = () => {
    if (open) return close();
    setOpen(true);
    requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)));
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
    <div ref={box}>
      <button onClick={toggle} aria-expanded={open} className="flex min-h-10 items-center gap-1.5 text-sm hover:opacity-80 sm:min-h-0" style={{ color: SOFT }}>
        <Sparkles className="h-4 w-4" aria-hidden />
        Highlights
      </button>
      {open && (
        <div
          className="absolute inset-x-0 top-full z-30 mt-2 max-h-[34rem] overflow-y-auto overflow-x-hidden rounded-lg border p-3 shadow-xl sm:left-0 sm:right-auto sm:w-[46rem] sm:max-w-full"
          style={{
            background: "var(--surface-1)", borderColor: "var(--border-default)",
            opacity: shown ? 1 : 0, transform: shown ? "none" : "translateY(-6px) scale(0.98)", transformOrigin: "top left",
            transition: reduced() ? "none" : `opacity 220ms ${EASE}, transform 220ms ${EASE}`,
          }}
        >
          <ForecastStrip data={data} loading={loading} error={error} />
        </div>
      )}
    </div>
  );
}
