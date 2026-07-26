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
