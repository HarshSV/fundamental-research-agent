import { fetchJson } from "@/lib/api";
import type { Plan } from "./forecast";

/** A price or time alert. Alerts live in this browser and are checked every 20 seconds while the site is open. */
export interface Alert {
  id: string;
  sym: string;
  name: string;
  kind: "entry" | "stop" | "target" | "exit";
  price: number | null; // null for the exit-time alert
  dir: "above" | "below" | null;
  message: string;
  created: number;
  fired: number | null;
}

const KEY = "navrist_alerts";
export const ALERTS_EVENT = "navrist-alerts-change";

export function loadAlerts(): Alert[] {
  try {
    const a = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(a) ? a : [];
  } catch {
    return [];
  }
}

export function saveAlerts(a: Alert[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(ALERTS_EVENT));
}

const fmt = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** The alerts a plan needs: the entry level (when the plan is "buy above / sell below"), the stop, the target and, for a
 *  same-day trade, the 15:25 exit. A level the price has already passed gets no alert. */
export function alertsForPlan(sym: string, name: string, plan: Plan, price: number | null, sameDay: boolean): Alert[] {
  const long = plan.side === "long";
  const t1 = plan.targets.find((t) => t.r === plan.first_target_r) ?? plan.targets[0];
  const now = Date.now();
  const mk = (kind: Alert["kind"], p: number | null, dir: Alert["dir"], message: string): Alert =>
    ({ id: `${sym}-${kind}-${plan.entry}-${now}`, sym, name, kind, price: p, dir, message, created: now, fired: null });
  const out: Alert[] = [];
  if (plan.action.endsWith("above") || plan.action.endsWith("below")) {
    out.push(mk("entry", plan.entry, long ? "above" : "below", `${name}: ${plan.action} ${fmt(plan.entry)} reached`));
  }
  out.push(mk("stop", plan.stop, long ? "below" : "above", `${name}: stop ${fmt(plan.stop)} hit`));
  out.push(mk("target", t1.price, long ? "above" : "below", `${name}: target ${fmt(t1.price)} hit`));
  if (sameDay) out.push(mk("exit", null, null, `${name}: 15:25 — close the trade before the market shuts`));
  return out.filter((a) => a.price == null || price == null || (a.dir === "above" ? price < a.price : price > a.price));
}

const istMinutes = (d = new Date()) => {
  const ist = new Date(d.getTime() + 330 * 60000);
  return { day: ist.getUTCDay(), mins: ist.getUTCHours() * 60 + ist.getUTCMinutes(), date: ist.toISOString().slice(0, 10) };
};

/** Check every pending alert once. Returns the alerts that fired (already marked fired and saved). */
export async function checkAlerts(): Promise<Alert[]> {
  const all = loadAlerts();
  const pending = all.filter((a) => !a.fired);
  if (!pending.length) return [];
  const fired: Alert[] = [];
  const t = istMinutes();
  const weekday = t.day >= 1 && t.day <= 5;
  const price = new Map<string, number | null>();
  await Promise.all(
    [...new Set(pending.filter((a) => a.price != null).map((a) => a.sym))].map(async (sym) => {
      try {
        const q = await fetchJson<{ ltp: number | null }>(`/api/quote?symbol=${sym}`, { retries: 0 });
        price.set(sym, q.ltp);
      } catch {
        price.set(sym, null);
      }
    }),
  );
  const now = Date.now();
  for (const a of pending) {
    let hit = false;
    if (a.kind === "exit") {
      const created = istMinutes(new Date(a.created));
      const window = weekday && t.mins >= 15 * 60 + 25 && t.mins < 15 * 60 + 40;
      hit = window && t.date === created.date && created.mins < 15 * 60 + 25;
      if (!hit && now - a.created > 12 * 3600 * 1000) a.fired = now; // the day is over: retire it quietly
    } else {
      const p = price.get(a.sym);
      hit = p != null && a.price != null && (a.dir === "above" ? p >= a.price : p <= a.price);
    }
    if (hit) {
      a.fired = now;
      fired.push(a);
    }
  }
  if (pending.some((a) => a.fired)) saveAlerts(all);   // fired alerts and quietly retired ones
  return fired;
}
