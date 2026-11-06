"use client";

import { useEffect, useRef, useState } from "react";
import { SlidingTabs, Switch } from "./controls";
import { ArrowDownRight, ArrowUpRight, ChevronDown, Minus, Newspaper } from "lucide-react";
import { fetchJson } from "@/lib/api";
import {
  ALERTS_EVENT, alertsForPlan, connectTelegram, fetchAlerts, removeAlerts, saveAlertsFor, testTelegram,
  type Alert, type TelegramStatus,
} from "./alerts";
import type { Events, Forecast, Horizon, Odds, Plan, Replay, TradeBlock } from "./forecast";

const GAIN = "var(--gain)";
const LOSS = "var(--loss)";
const MUTED = "var(--text-tertiary)";
const SOFT = "var(--text-secondary)";

const n = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const inr = (v: number | null | undefined, d = 2) => (v == null ? "—" : `₹${n(v, d)}`);
const sgn = (v: number | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${n(v, 1)}%`);

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 text-xs font-medium uppercase tracking-wider" style={{ color: MUTED }}>{children}</div>;
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
    <div className="flex justify-between gap-4 break-inside-avoid py-1 text-sm">
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

function OddsLine({ odds, replay, daily }: { odds?: Odds | null; replay?: Replay | null; daily: boolean }) {
  return (
    <div className="mt-4 space-y-2 border-t pt-4 text-sm" style={{ borderColor: "var(--border-subtle)" }}>
      {odds && odds.target != null && (
        <p>
          <span style={{ color: MUTED }}>{n(odds.paths, 0)} simulated continuations: </span>
          target first <b style={{ color: GAIN }}>{odds.target}%</b>, stop first <b style={{ color: LOSS }}>{odds.stop}%</b>, neither{" "}
          <b>{odds.open}%</b>
          <span style={{ color: MUTED }}> (the entry is reached in {odds.enters}%)</span>
        </p>
      )}
      {replay && !daily && replay.trades != null && (
        <p>
          <span style={{ color: MUTED }}>{replay.session_rule ? `The same plan on this stock's past ${replay.sessions} days in this state: ` : `Same rule on the last ${replay.sessions} sessions (${replay.trades} trades): `}</span>
          target <b style={{ color: GAIN }}>{replay.target}</b>, stop <b style={{ color: LOSS }}>{replay.stop}</b>, neither <b>{replay.open}</b>
        </p>
      )}
      {replay && daily && replay.n != null && (
        <p>
          <span style={{ color: MUTED }}>{replay.trend_rule ? "The same rule on this stock's past days in this state" : "This setup has appeared"} ({replay.n}): </span>
          {replay.target != null ? (
            <>target <b style={{ color: GAIN }}>{replay.target}</b>, stop <b style={{ color: LOSS }}>{replay.stop}</b>, neither <b>{replay.open}</b></>
          ) : replay.win == null ? (
            <span style={{ color: MUTED }}>too few to measure</span>
          ) : (
            <>
              up after {replay.horizon} sessions <b style={{ color: replay.win >= 50 ? GAIN : LOSS }}>{replay.win}%</b> of the time, typical{" "}
              <b style={{ color: (replay.median ?? 0) >= 0 ? GAIN : LOSS }}>{sgn(replay.median ?? undefined)}</b>
            </>
          )}
        </p>
      )}
    </div>
  );
}

function EdgeLine({ b }: { b: TradeBlock }) {
  if (!b.edge) return null;
  const v = b.edge.value;
  const color = b.edge.label === "favourable" ? GAIN : b.edge.label === "against" ? LOSS : SOFT;
  const word = b.edge.label === "favourable" ? "Odds favour this trade" : b.edge.label === "against" ? "Odds are against this trade" : "Odds are about even";
  return (
    <p className="mt-3 text-sm">
      <b style={{ color }}>{word}</b>
      <span style={{ color: MUTED }}> · {v > 0 ? "+" : ""}{n(v)} for every 1 of risk</span>
    </p>
  );
}

function Trade({ title, b, daily, onAlert, hasAlerts }: { title: string; b: TradeBlock; daily: boolean; onAlert: () => void; hasAlerts: boolean }) {
  const p: Plan | null | undefined = b.plan;
  const t1 = p?.targets[0];
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{title}</span>
        <span className="text-lg font-semibold" style={{ color: p ? (p.side === "long" ? GAIN : LOSS) : SOFT }}>
          {p ? `${p.action} ${inr(p.entry)}` : "No trade"}
        </span>
      </div>
      {p && t1 ? (
        <>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div>
              <div className="text-xs" style={{ color: MUTED }}>Stop</div>
              <div className="nv-num font-semibold" style={{ color: LOSS }}>{inr(p.stop)}</div>
              <div className="text-xs" style={{ color: MUTED }}>{n(p.risk_pct)}% · {inr(p.risk_per_share)} a share</div>
            </div>
            {p.targets.slice(0, 2).map((t) => (
              <div key={t.r}>
                <div className="text-xs" style={{ color: MUTED }}>Target</div>
                <div className="nv-num font-semibold" style={{ color: GAIN }}>{inr(t.price)}</div>
                <div className="text-xs" style={{ color: MUTED }}>{t.r}× the risk</div>
              </div>
            ))}
          </div>
          <EdgeLine b={b} />
          <p className="mt-2 text-xs" style={{ color: MUTED }}>
            Stop at {p.stop_basis}. {p.exit_rule}
          </p>
          {b.note && <p className="mt-1 text-xs" style={{ color: MUTED }}>{b.note}</p>}
          {p.warnings.map((w) => (
            <p key={w} className="mt-1 text-xs" style={{ color: LOSS }}>{w}</p>
          ))}
          <button onClick={onAlert} disabled={hasAlerts} className="mt-3 rounded-full border px-3 py-1 text-xs font-medium enabled:hover:border-[var(--accent-border)] disabled:opacity-60"
            style={{ borderColor: "var(--border-default)", color: SOFT }}>
            {hasAlerts ? "Alerts set for this stock" : "Alert me at the entry, stop and target"}
          </button>
        </>
      ) : (
        <p className="mt-1 text-sm" style={{ color: SOFT }}>{b.decision.reason}</p>
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
      <button onClick={toggle} aria-expanded={open} className="flex items-center gap-1.5 text-sm hover:opacity-80" style={{ color: SOFT }}>
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

/** Telegram link status and the alerts set for this stock. */
function Alerts({ symbol, alerts, tg }: { symbol: string; alerts: Alert[]; tg: TelegramStatus | null }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (f: () => Promise<unknown>) => {
    setBusy(true);
    setMsg("");
    try {
      const r = (await f()) as { connected?: boolean; reason?: string } | undefined;
      if (r && r.connected === false) setMsg(r.reason ?? "Not connected yet.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="border-t pt-4 text-sm" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="font-medium">Your alerts</span>
        {alerts.length > 0 && <button className="text-xs underline" style={{ color: MUTED }} onClick={() => removeAlerts(symbol)}>Remove all</button>}
      </div>
      {alerts.map((a) => (
        <div key={a.id} className="flex justify-between py-0.5">
          <span style={{ color: SOFT }}>{a.kind === "exit" ? "Close the trade" : a.kind === "entry" ? "Entry reached" : a.kind === "stop" ? "Stop hit" : "Target hit"}</span>
          <span className="nv-num" style={{ color: a.kind === "stop" ? LOSS : a.kind === "target" ? GAIN : undefined }}>{a.price != null ? `${a.dir === "above" ? "at or above" : "at or below"} ${inr(a.price)}` : "15:25"}</span>
        </div>
      ))}
      {tg?.configured && !tg.connected && (
        <div className="mt-2 text-xs" style={{ color: MUTED }}>
          {tg.bot ? <>Open <a className="underline" href={`https://t.me/${tg.bot}`} target="_blank" rel="noopener noreferrer">@{tg.bot}</a> in Telegram and press Start, then </> : "Press Start on your bot in Telegram, then "}
          <button disabled={busy} onClick={() => run(connectTelegram)} className="underline" style={{ color: SOFT }}>connect</button>.
        </div>
      )}
      {tg?.connected && (
        <p className="mt-2 text-xs" style={{ color: MUTED }}>
          Alerts are also sent to your Telegram, even when this site is closed.{" "}
          <button disabled={busy} onClick={() => run(testTelegram)} className="underline" style={{ color: SOFT }}>Send a test message</button>
        </p>
      )}
      {msg && <p className="mt-1 text-xs" style={{ color: LOSS }}>{msg}</p>}
    </div>
  );
}


const SPAN: Record<Horizon["id"], string> = { session: "the next session", week: "the next 5 sessions", month: "the next 20 sessions" };
const SPAN_TAB: Record<Horizon["id"], string> = { session: "1 day", week: "1 week", month: "1 month" };

/** The answer first: one sentence, how sure we are, and where the price should land. Everything else sits behind "See the reasoning". */
function Verdict({ data }: { data: Forecast }) {
  const [hid, setHid] = useState<Horizon["id"]>("week");
  const { ref, seen } = useInView<HTMLDivElement>();
  const h = data.outlook.find((x) => x.id === hid) ?? data.outlook[0];
  const span = SPAN[h.id];
  const dp = (h.price_mid ?? data.price ?? 1000) < 100 ? 2 : 0;      // a ₹16 stock needs its paise
  const call = h.up == null ? null : h.call;
  const color = call === "up" ? GAIN : call === "down" ? LOSS : SOFT;
  const Icon = call === "up" ? ArrowUpRight : call === "down" ? ArrowDownRight : Minus;
  const headline = h.up == null ? `Not enough history to forecast ${span}` : call === "up" ? `Likely to go up over ${span}` : call === "down" ? `Likely to go down over ${span}` : `Could go either way over ${span}`;
  const lean = h.up == null ? null : call === "even" || call == null ? "The odds are about even" : `${h.conviction ? h.conviction[0].toUpperCase() + h.conviction.slice(1) : "Clear"} lean`;
  return (
    <div ref={ref} className="rounded-2xl border p-6 md:p-8" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
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
            Out of 100 similar past setups, <b style={{ color: GAIN }}>{h.up}</b> went up, <b>{h.flat}</b> stayed flat and <b style={{ color: LOSS }}>{h.down}</b> went down.
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
  );
}

/** The one Forecast section on the stock page: outlook, trade plan with replay odds, levels, evidence and position size. */
export function ForecastCard({
  data, error, showLevels, onToggleLevels,
}: { data: Forecast | null; error: boolean; showLevels: boolean; onToggleLevels: () => void }) {
  return <ForecastBody data={data} error={error} showLevels={showLevels} onToggleLevels={onToggleLevels} />;
}

function ForecastBody({
  data, error, showLevels, onToggleLevels,
}: { data: Forecast | null; error: boolean; showLevels: boolean; onToggleLevels: () => void }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [tg, setTg] = useState<TelegramStatus | null>(null);
  const [open, setOpen] = useState(false);
  const sym = data?.symbol;
  useEffect(() => {
    if (!sym) return;
    let alive = true;
    const read = () =>
      fetchAlerts()
        .then((r) => {
          if (!alive) return;
          setAlerts(r.alerts.filter((a) => a.sym === sym && !a.fired));
          setTg(r.telegram);
        })
        .catch(() => {});
    read();
    window.addEventListener(ALERTS_EVENT, read);
    return () => {
      alive = false;
      window.removeEventListener(ALERTS_EVENT, read);
    };
  }, [sym]);
  const setFor = (plan: Plan, sameDay: boolean) => {
    if (!data) return;
    if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission().catch(() => {});
    saveAlertsFor(alertsForPlan(data.symbol, data.symbol, plan, data.price, sameDay)).catch(() => {});
  };
  if (error) return <p className="text-sm" style={{ color: MUTED }}>The forecast could not be worked out for this stock right now.</p>;
  if (data === null) return <div className="h-40 animate-pulse rounded-lg" style={{ background: "var(--overlay-weak)" }} aria-label="Working out the forecast" />;
  if (!data.outlook) return <p className="text-sm" style={{ color: MUTED }}>No price history could be read for this stock under this symbol (it may be newly listed or have been renamed), so no forecast can be made. News is still available above.</p>;
  const hasLevels = Boolean(data.today.setup?.range_high != null || data.today.plan || data.swing.plan);
  return (
    <div>
      <Verdict data={data} />

      <div className="mt-10">
        <Label>When to buy and when to get out</Label>
        <div className="grid items-start gap-x-14 gap-y-8 md:grid-cols-2">
          <Trade title={data.market_open && !data.session_late ? "Today" : "Next session"} b={data.today} daily={false} hasAlerts={alerts.length > 0} onAlert={() => data.today.plan && setFor(data.today.plan, true)} />
          <Trade title="Swing, up to 10 sessions" b={data.swing} daily hasAlerts={alerts.length > 0} onAlert={() => data.swing.plan && setFor(data.swing.plan, false)} />
        </div>
        {(alerts.length > 0 || tg?.configured) && <div className="mt-6"><Alerts symbol={data.symbol} alerts={alerts} tg={tg} /></div>}
      </div>

      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="mt-8 flex items-center gap-1.5 text-sm font-medium hover:opacity-80"
        style={{ color: SOFT }}
      >
        {open ? "Hide the reasoning" : "See the reasoning"}
        <ChevronDown className="h-4 w-4" style={{ transform: open ? "rotate(180deg)" : "none", transition: reduced() ? "none" : "transform 400ms ease" }} aria-hidden />
      </button>

      {open && (
        <div className="nv-rise mt-8">
          <div className="relative mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" style={{ color: MUTED }}>
            <span>{data.market_open ? "Market open" : "Market closed"}</span>
            {data.segment && <span>{data.segment}</span>}
            {data.adr20_pct != null && <span>Typical daily range {n(data.adr20_pct)}%</span>}
            <span className="ml-auto flex items-center gap-5">
              {hasLevels && <Switch on={showLevels} onChange={onToggleLevels} label="Levels on chart" />}
            </span>
          </div>
          <div className="grid items-start gap-x-14 gap-y-10 md:grid-cols-2">
            <div>
              <Label>Outlook</Label>
              {data.outlook.map((h, i) => <Outlook key={data.symbol + h.id} h={h} index={i} />)}
            </div>
            {data.levels && data.levels.length > 0 && (
              <div>
                <Label>Levels to watch</Label>
                {data.levels.map((e) => <Fact key={e.label} label={e.label} value={e.value} tone={e.tone} />)}
              </div>
            )}
          </div>
          {/* The evidence runs as one list that flows down the left column and on into the right, so the two columns end level. */}
          <div className="mt-10 border-t pt-8 md:columns-2 md:gap-x-14" style={{ borderColor: "var(--border-subtle)" }}>
            <div className="break-after-avoid"><Label>What the forecast rests on</Label></div>
            {data.evidence.map((e) => <Fact key={e.label} label={e.label} value={e.value} tone={e.tone} />)}
          </div>
        </div>
      )}
    </div>
  );
}
