// NSE cash-market session: Monday to Friday, 09:15 to 15:30 IST, except exchange-declared trading holidays.
// Weekday holidays only (weekends are closed anyway). Extend this list when the exchange publishes the next year's calendar.
const HOLIDAYS = new Set([
  // 2026
  "2026-11-10", "2026-11-24", "2026-12-25",
  // 2027
  "2027-01-26", "2027-03-10", "2027-03-22", "2027-03-26", "2027-04-14", "2027-04-15", "2027-04-19", "2027-05-17",
  "2027-06-15", "2027-10-29",
]);

const OPEN_MIN = 9 * 60 + 15;
const CLOSE_MIN = 15 * 60 + 30;

/** The clock in India, whatever the browser's own time zone is. */
function istParts(now: Date) {
  const ist = new Date(now.getTime() + 330 * 60000);
  return { day: ist.getUTCDay(), mins: ist.getUTCHours() * 60 + ist.getUTCMinutes(), date: ist.toISOString().slice(0, 10) };
}

export function isTradingDay(now = new Date()): boolean {
  const { day, date } = istParts(now);
  return day >= 1 && day <= 5 && !HOLIDAYS.has(date);
}

export function marketOpen(now = new Date()): boolean {
  const { mins } = istParts(now);
  return isTradingDay(now) && mins >= OPEN_MIN && mins <= CLOSE_MIN;
}
