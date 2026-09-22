// =============================================================================
// === frontend/lib/format.ts ===
// One shared helper rather than repeating this in every page — the
// backend correctly stores/returns dates as plain ISO strings
// ("2026-07-25"), which is exactly right for an API, but reads like
// a database column rather than something a shop owner would say
// out loud. This is purely a display-layer concern, so it belongs
// here, not in the API layer or the backend.
// =============================================================================

/**
 * Formats an ISO date string ("2026-07-25") as "25 Juli 2026" —
 * the way a shop owner in Indonesia would actually read a date,
 * rather than the raw ISO form.
 *
 * Deliberately parses year/month/day manually and builds the Date
 * via new Date(year, month - 1, day) instead of new Date(dateStr)
 * directly. Passing an ISO date-only string straight to the Date
 * constructor parses it as UTC midnight — correct for a viewer in
 * Indonesia (UTC+7), but a viewer in a negative-offset timezone
 * would see it silently roll back to the previous day. Arya Motor
 * is Indonesia-only today, but there's no reason to bake in a
 * timezone assumption when constructing the date locally avoids it
 * entirely, at zero extra cost.
 *
 * Returns "—" for null/undefined/empty, matching the same "—"
 * placeholder already used elsewhere on this page (e.g.
 * registration_expiry when unset) — one convention for "no value
 * yet," not several.
 */
export function formatDateID(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";

  const parts = dateStr.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) {
    // Malformed input — show it as-is rather than silently hiding
    // a real value behind "—", which would look like data loss.
    return dateStr;
  }

  const [year, month, day] = parts;
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
}

const SHOP_TIME_ZONE = "Asia/Jakarta";

/**
 * Today's date in the SHOP's own calendar, as "YYYY-MM-DD" — for date-input
 * defaults ("Per Tanggal", a transaction date, and so on).
 *
 * Deliberately NOT `new Date().toISOString().slice(0, 10)`: toISOString()
 * converts to UTC first, so between 00:00 and 07:00 in Indonesia (UTC+7) it
 * returns YESTERDAY's date. That is the front-end twin of the backend bug
 * fixed by safe_local_date() (Cheat Sheet §12) — and on the 1st of a month
 * it would default a form into the previous, possibly already closed, period.
 *
 * Pinned to Asia/Jakarta rather than the browser's own zone so it always
 * agrees with the backend's idea of "today", even on a device whose clock
 * is set to another zone. Built with formatToParts so it never depends on
 * a locale's date-format quirks. `now` is injectable purely for testing.
 */
export function todayISO(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: SHOP_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

// 22 Sep 2026 — moved here from vehicles/page.tsx (its own original comment
// kept below), once journal/page.tsx and general-ledger/page.tsx needed the
// same short form for their own dense, multi-column ledger tables — a raw
// "2026-09-21" posting_date sitting next to a "22/09/2026" date-range picker
// on the same screen was the real, live inconsistency that prompted this.
//
// dd-mm-yyyy specifically for a compact table column — v.last_service_date /
// e.posting_date / row.posting_date all arrive as a plain "YYYY-MM-DD"
// string (a DateField, never a datetime), so this is a direct, safe string
// split — no real Date object/timezone conversion involved at all.
export function formatDateShortID(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}-${month}-${year}`;
}
