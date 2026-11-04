import { fetchJson } from "@/lib/api";
import type { Plan } from "./forecast";

/** An alert as the server holds it. The server checks prices every 30 seconds, also while this site is closed. */
export interface Alert {
  id: string;
  sym: string;
  name: string;
  kind: "entry" | "stop" | "target" | "exit";
  price: number | null; // null for the 15:25 exit reminder
  dir: "above" | "below" | null;
  message: string;
  created: number;
  fired: number | null;
  sent: number | null; // when it reached Telegram
}

export interface TelegramStatus {
  configured: boolean; // a bot token is set on the server
  connected: boolean; // a chat is linked
  bot: string | null;
  error?: string;
}

export interface AlertsResponse {
  alerts: Alert[];
  telegram: TelegramStatus;
}

export const ALERTS_EVENT = "navrist-alerts-change";
const notify = () => window.dispatchEvent(new Event(ALERTS_EVENT));

export const fetchAlerts = () => fetchJson<AlertsResponse>("/api/v1/alerts", { retries: 0 });

const json = (body: unknown) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function saveAlertsFor(items: Omit<Alert, "id" | "created" | "fired" | "sent">[]) {
  await fetchJson("/api/v1/alerts", { retries: 0, init: json({ alerts: items }) });
  notify();
}

export async function removeAlerts(symbol: string) {
  await fetchJson(`/api/v1/alerts?symbol=${encodeURIComponent(symbol)}`, { retries: 0, init: { method: "DELETE" } });
  notify();
}

export async function connectTelegram(): Promise<{ connected: boolean; reason?: string }> {
  const r = await fetchJson<{ connected: boolean; reason?: string }>("/api/v1/telegram/connect", { retries: 0, init: json({}) });
  notify();
  return r;
}

export const testTelegram = () => fetchJson("/api/v1/telegram/test", { retries: 0, init: json({}) });

const fmt = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** The alerts a plan needs: the entry level (when the plan is "buy above / sell below"), the stop, the target and, for a
 *  same-day trade, the 15:25 exit. A level the price has already passed gets no alert. */
export function alertsForPlan(sym: string, name: string, plan: Plan, price: number | null, sameDay: boolean) {
  const long = plan.side === "long";
  const t1 = plan.targets.find((t) => t.r === plan.first_target_r) ?? plan.targets[0];
  const mk = (kind: Alert["kind"], p: number | null, dir: Alert["dir"], message: string) => ({ sym, name, kind, price: p, dir, message });
  const out = [];
  if (plan.action.endsWith("above") || plan.action.endsWith("below")) {
    out.push(mk("entry", plan.entry, long ? "above" : "below", `${name}: ${plan.action} ${fmt(plan.entry)} reached`));
  }
  out.push(mk("stop", plan.stop, long ? "below" : "above", `${name}: stop ${fmt(plan.stop)} hit`));
  out.push(mk("target", t1.price, long ? "above" : "below", `${name}: target ${fmt(t1.price)} hit`));
  if (sameDay) out.push(mk("exit", null, null, `${name}: 15:25 — close the trade before the market shuts`));
  return out.filter((a) => a.price == null || price == null || (a.dir === "above" ? price < a.price : price > a.price));
}
