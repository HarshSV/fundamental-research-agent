"use client";

import { useEffect, useState } from "react";
import { ALERTS_EVENT, alertsForPlan, loadAlerts, saveAlerts, type Alert } from "./alerts";
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

function Outlook({ h }: { h: Horizon }) {
  const word = h.call === "up" ? "Up" : h.call === "down" ? "Down" : h.call === "none" ? "No clear edge" : "No call";
  const color = h.call === "up" ? GAIN : h.call === "down" ? LOSS : SOFT;
  return (
    <div className="border-t py-4 first:border-t-0 first:pt-0" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{h.label}</span>
        <span className="text-lg font-semibold" style={{ color }}>{word}</span>
      </div>
      {h.up == null ? (
        <p className="mt-1 text-sm" style={{ color: MUTED }}>{h.reason ?? "Not enough history to measure."}</p>
      ) : (
        <>
          <div className="mt-2 flex h-1.5 overflow-hidden rounded-full" role="img" aria-label={`Up ${h.up}%, flat ${h.flat}%, down ${h.down}%`}>
            <div style={{ width: `${h.up}%`, background: "var(--gain)" }} />
            <div style={{ width: `${h.flat}%`, background: "var(--overlay)" }} />
            <div style={{ width: `${h.down}%`, background: "var(--loss)" }} />
          </div>
          <div className="mt-2 flex justify-between text-sm">
            <span style={{ color: GAIN }}>Up {h.up}%</span>
            <span style={{ color: MUTED }}>Flat {h.flat}%</span>
            <span style={{ color: LOSS }}>Down {h.down}%</span>
          </div>
          <p className="mt-1.5 text-xs" style={{ color: MUTED }}>
            Typical move {sgn(h.p10)} to {sgn(h.p90)} (middle {sgn(h.median)}), from {h.samples?.toLocaleString("en-IN")}{" "}
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
          <span style={{ color: MUTED }}>Same rule on the last {replay.sessions} sessions ({replay.trades} trades): </span>
          target <b style={{ color: GAIN }}>{replay.target}</b>, stop <b style={{ color: LOSS }}>{replay.stop}</b>, neither <b>{replay.open}</b>
        </p>
      )}
      {replay && daily && replay.n != null && (
        <p>
          <span style={{ color: MUTED }}>This setup has appeared {replay.n} times before: </span>
          {replay.win == null ? (
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

function Trade({ title, b, daily, onAlert, hasAlerts }: { title: string; b: TradeBlock; daily: boolean; onAlert: () => void; hasAlerts: boolean }) {
  const p: Plan | null | undefined = b.plan;
  const t1 = p?.targets.find((t) => t.r === p.first_target_r) ?? p?.targets[0];
  const t2 = p?.targets.find((t) => t.r > p.first_target_r);
  return (
    <div className="border-t py-4 first:border-t-0 first:pt-0" style={{ borderColor: "var(--border-subtle)" }}>
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
            <div>
              <div className="text-xs" style={{ color: MUTED }}>Target</div>
              <div className="nv-num font-semibold" style={{ color: GAIN }}>{inr(t1.price)}</div>
              <div className="text-xs" style={{ color: MUTED }}>{t1.r}× the risk</div>
            </div>
            <div>
              <div className="text-xs" style={{ color: MUTED }}>Second target</div>
              <div className="nv-num font-semibold" style={{ color: GAIN }}>{t2 ? inr(t2.price) : "—"}</div>
              <div className="text-xs" style={{ color: MUTED }}>{t2 ? `${t2.r}× the risk` : ""}</div>
            </div>
          </div>
          <p className="mt-3 text-xs" style={{ color: MUTED }}>
            Stop at {p.stop_basis}. {p.exit_rule}
          </p>
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

/** Filings (NSE / BSE) and headlines (Google News) for the company, newest first. Nothing is scored or interpreted. */
function News({ ev }: { ev: Events }) {
  const down = Object.entries(ev.sources).filter(([, v]) => v === "unavailable").map(([k]) => k);
  return (
    <div>
      <Label>News and filings</Label>
      {ev.upcoming.length > 0 && (
        <p className="mb-3 text-sm">
          <span style={{ color: MUTED }}>Next board meeting: </span>
          <b>{day(ev.upcoming[0].date)}</b>
          <span style={{ color: SOFT }}> — {ev.upcoming[0].purpose}</span>
        </p>
      )}
      {ev.items.length === 0 ? (
        <p className="text-sm" style={{ color: MUTED }}>No filings or headlines in the last 30 days.</p>
      ) : (
        <ul className="space-y-2.5 text-sm">
          {ev.items.map((i) => (
            <li key={i.source + i.ts + i.title} className="flex gap-3">
              <span className="w-14 shrink-0 text-xs leading-5" style={{ color: MUTED }}>{day(i.ts)}</span>
              <span className="min-w-0 flex-1">
                {i.link ? (
                  <a href={i.link} target="_blank" rel="noopener noreferrer" className="hover:underline">{i.title}</a>
                ) : (
                  i.title
                )}
                <span className="ml-2 text-xs" style={{ color: MUTED }}>{i.source === "News" ? i.category : `${i.source} · ${i.category}`}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {down.length > 0 && (
        <p className="mt-3 text-xs" style={{ color: MUTED }}>Could not be read right now: {down.join(", ")}.</p>
      )}
    </div>
  );
}

const KEY = "navrist_position_inputs";

/** Position size for a plan from the user's own account size and loss limit, capped by what the stock trades in a day. */
function Size({ f }: { f: Forecast }) {
  const [capital, setCapital] = useState("");
  const [maxLoss, setMaxLoss] = useState("");
  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) ?? "{}");
      if (s.capital) setCapital(String(s.capital)); // eslint-disable-line react-hooks/set-state-in-effect
      if (s.maxLoss) setMaxLoss(String(s.maxLoss));
    } catch {
      /* no saved inputs */
    }
  }, []);
  const save = (c: string, m: string) => localStorage.setItem(KEY, JSON.stringify({ capital: c, maxLoss: m }));
  const plan = f.today.plan ?? f.swing.plan ?? null;
  const cap = Number(capital);
  const loss = Number(maxLoss);
  const ok = plan && cap > 0 && loss > 0;
  let shares = 0;
  let limit = "";
  if (ok) {
    const byRisk = Math.floor(loss / plan.risk_per_share);
    const byCash = Math.floor(cap / plan.entry);
    const byLiq = f.liquidity.max_position_inr ? Math.floor(f.liquidity.max_position_inr / plan.entry) : Infinity;
    shares = Math.max(0, Math.min(byRisk, byCash, byLiq));
    limit = shares === byLiq && byLiq < Math.min(byRisk, byCash) ? "limited by what the stock trades in a day" : shares === byCash && byCash < byRisk ? "limited by your capital" : "limited by your loss limit";
  }
  const t1 = plan?.targets.find((t) => t.r === plan.first_target_r) ?? plan?.targets[0];
  const input = "w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:border-[var(--accent-border)]";
  return (
    <div>
      <Label>Position size</Label>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-xs" style={{ color: MUTED }}>
          Capital (₹)
          <input inputMode="numeric" className={`${input} mt-1`} style={{ borderColor: "var(--border-default)" }} value={capital}
            onChange={(e) => { setCapital(e.target.value); save(e.target.value, maxLoss); }} placeholder="e.g. 500000" />
        </label>
        <label className="text-xs" style={{ color: MUTED }}>
          Most you will lose on a trade (₹)
          <input inputMode="numeric" className={`${input} mt-1`} style={{ borderColor: "var(--border-default)" }} value={maxLoss}
            onChange={(e) => { setMaxLoss(e.target.value); save(capital, e.target.value); }} placeholder="e.g. 2500" />
        </label>
      </div>
      {!plan ? (
        <p className="mt-3 text-sm" style={{ color: MUTED }}>There is no trade to size right now.</p>
      ) : !ok ? (
        <p className="mt-3 text-sm" style={{ color: MUTED }}>Enter both figures to see the size for {plan.action.toLowerCase()} {inr(plan.entry)}.</p>
      ) : shares === 0 ? (
        <p className="mt-3 text-sm" style={{ color: LOSS }}>Even one share breaks a limit ({limit}).</p>
      ) : (
        <dl className="mt-3 space-y-1.5 text-sm">
          <div className="flex justify-between"><dt style={{ color: MUTED }}>Shares</dt><dd className="nv-num font-semibold">{shares.toLocaleString("en-IN")}</dd></div>
          <div className="flex justify-between"><dt style={{ color: MUTED }}>Amount</dt><dd className="nv-num">{inr(shares * plan.entry, 0)}</dd></div>
          <div className="flex justify-between"><dt style={{ color: MUTED }}>Lost if the stop is hit</dt><dd className="nv-num" style={{ color: LOSS }}>{inr(shares * plan.risk_per_share, 0)}</dd></div>
          {t1 && <div className="flex justify-between"><dt style={{ color: MUTED }}>Gained at the target</dt><dd className="nv-num" style={{ color: GAIN }}>{inr(shares * Math.abs(t1.price - plan.entry), 0)}</dd></div>}
          <p className="pt-1 text-xs" style={{ color: MUTED }}>Size is {limit}.</p>
        </dl>
      )}
    </div>
  );
}

/** The one Forecast section on the stock page: outlook, trade plan with replay odds, evidence and position size. */
export function ForecastCard({
  data, error, showLevels, onToggleLevels,
}: { data: Forecast | null; error: boolean; showLevels: boolean; onToggleLevels: () => void }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const sym = data?.symbol;
  useEffect(() => {
    const read = () => setAlerts(loadAlerts().filter((a) => a.sym === sym && !a.fired));
    read();
    window.addEventListener(ALERTS_EVENT, read);
    return () => window.removeEventListener(ALERTS_EVENT, read);
  }, [sym]);
  const setFor = (plan: Plan, sameDay: boolean) => {
    if (!data) return;
    if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission().catch(() => {});
    const fresh = alertsForPlan(data.symbol, data.symbol, plan, data.price, sameDay);
    saveAlerts([...loadAlerts().filter((a) => a.fired || a.sym !== data.symbol), ...fresh]);
  };
  if (error) return <p className="text-sm" style={{ color: MUTED }}>The forecast could not be worked out for this stock right now.</p>;
  if (data === null) return <div className="h-40 animate-pulse rounded-lg" style={{ background: "var(--overlay-weak)" }} aria-label="Working out the forecast" />;
  if (!data.outlook) return <p className="text-sm" style={{ color: MUTED }}>There is no price history for this stock, so no forecast can be made.</p>;
  const hasLevels = Boolean(data.today.setup?.range_high != null || data.today.plan || data.swing.plan);
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" style={{ color: MUTED }}>
        <span>{data.market_open ? "Market open" : "Market closed"}</span>
        {data.segment && <span>{data.segment}</span>}
        {data.adr20_pct != null && <span>Typical daily range {n(data.adr20_pct)}%</span>}
        {hasLevels && (
          <button onClick={onToggleLevels} aria-pressed={showLevels} className="ml-auto rounded-full border px-3 py-1 text-sm font-medium hover:border-[var(--accent-border)]"
            style={{ borderColor: "var(--border-default)", color: showLevels ? "var(--text-primary)" : SOFT }}>
            {showLevels ? "Hide levels on chart" : "Show levels on chart"}
          </button>
        )}
      </div>
      <div className="grid gap-x-12 gap-y-10 md:grid-cols-2">
        <div>
          <Label>Outlook</Label>
          {data.outlook.map((h) => <Outlook key={h.id} h={h} />)}
        </div>
        <div>
          <Label>Trade plan</Label>
          <Trade title="Today" b={data.today} daily={false} hasAlerts={alerts.length > 0} onAlert={() => data.today.plan && setFor(data.today.plan, true)} />
          <Trade title="Swing, up to 10 sessions" b={data.swing} daily hasAlerts={alerts.length > 0} onAlert={() => data.swing.plan && setFor(data.swing.plan, false)} />
          {alerts.length > 0 && (
            <div className="border-t pt-4 text-sm" style={{ borderColor: "var(--border-subtle)" }}>
              <div className="mb-2 flex items-baseline justify-between">
                <span className="font-medium">Your alerts</span>
                <button className="text-xs underline" style={{ color: MUTED }} onClick={() => saveAlerts(loadAlerts().filter((a) => a.sym !== data.symbol))}>Remove all</button>
              </div>
              {alerts.map((a) => (
                <div key={a.id} className="flex justify-between py-0.5">
                  <span style={{ color: SOFT }}>{a.kind === "exit" ? "Close the trade" : a.kind === "entry" ? "Entry reached" : a.kind === "stop" ? "Stop hit" : "Target hit"}</span>
                  <span className="nv-num" style={{ color: a.kind === "stop" ? LOSS : a.kind === "target" ? GAIN : undefined }}>{a.price != null ? `${a.dir === "above" ? "at or above" : "at or below"} ${inr(a.price)}` : "15:25"}</span>
                </div>
              ))}
              <p className="mt-2 text-xs" style={{ color: MUTED }}>Checked every 20 seconds while this site is open in your browser.</p>
            </div>
          )}
        </div>
        <div>
          <Label>What the forecast rests on</Label>
          <dl className="space-y-2 text-sm">
            {data.evidence.map((e) => (
              <div key={e.label} className="flex justify-between gap-4">
                <dt style={{ color: MUTED }}>{e.label}</dt>
                <dd className="nv-num text-right font-medium" style={{ color: e.tone === "good" ? GAIN : e.tone === "bad" ? LOSS : "var(--text-primary)" }}>{e.value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <Size f={data} />
      </div>
      {data.events && (
        <div className="mt-10 border-t pt-8" style={{ borderColor: "var(--border-subtle)" }}>
          <News ev={data.events} />
        </div>
      )}
      <p className="mt-8 text-xs" style={{ color: MUTED }}>
        Odds come from this stock&apos;s own past prices and are not a guarantee or investment advice.
      </p>
    </div>
  );
}
