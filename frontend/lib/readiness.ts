// =============================================================================
// === frontend/lib/readiness.ts ===
// =============================================================================
// 20 Sep 2026 — Roadmap Principle #17(c) / Task 19.3 follow-up.
//
// One shared place for everything a screen needs to react to the backend's
// readiness gate (apps.accounting.services.readiness.readiness_block_response):
// a 409 whose body is
//     { success: false, message: "...", blocks: [{code, message, action}], warnings: [...] }
//
// Before this file, only the Ringkasan banner understood that response. The six
// gated actions (estimate approval, work order close, part consumption, invoice
// issue, customer payment, supplier payment) each swallowed it into a generic
// "Gagal ..." string, so a shop that was merely not ready looked like a broken
// app. Every gated screen now uses readinessBlockFromError() + the shared
// <ReadinessBlockNotice /> instead.
//
// Action labels and destinations live HERE, once — the Ringkasan banner and every
// notice read the same two maps, so a destination added later appears everywhere
// at the same moment.
import type { ReadinessBlock } from "@/lib/api/accounting";

export const READINESS_ACTION_LABEL: Record<string, string> = {
  OPEN_ACCOUNTING_SETUP: "Buka Pengaturan Akuntansi",
  OPEN_OPENING_BALANCE: "Lengkapi Saldo Awal",
};

// Only actions with a REAL destination get an entry — deliberately no
// placeholder href for the others, because a button that goes nowhere is worse
// than no button (Roadmap Principle #17(c)).
//
// OPEN_OPENING_BALANCE has none, and that is a known gap, not an oversight:
// the opening-balance wizard exists (OnboardingOverlay), but it only appears
// for a shop whose onboarding is unfinished, so an already-onboarded shop has
// nowhere to go. Roadmap Open Decision #33. When a destination exists, add its
// href here and every banner and notice picks it up.
export const READINESS_ACTION_HREF: Partial<Record<string, string>> = {
  OPEN_ACCOUNTING_SETUP: "/dashboard/accounting/accounts",
  // 22 Sep 2026 — Roadmap Open Decision #33, resolved: reuses the existing
  // OpeningBalanceStep wizard, embedded outside first-login (see the new page
  // itself and OnboardingOverlay.tsx for the full reasoning).
  OPEN_OPENING_BALANCE: "/dashboard/accounting/opening-balance",
};

export interface ReadinessBlockedError {
  /** What the person tried, in their words — e.g. "Pembayaran belum dapat dicatat." */
  headline: string;
  /** The server's own summary sentence. */
  message: string;
  blocks: ReadinessBlock[];
}

const DEFAULT_MESSAGE = "Workshop belum siap untuk transaksi operasional.";

/**
 * If `err` is the readiness gate's 409, returns its parsed contents; otherwise
 * null — so the caller falls through to its own normal error handling.
 *
 * Strict on purpose: a 409 WITHOUT a non-empty `blocks` list is some other
 * conflict (an invoice-status guard, say) and must not be mistaken for the gate.
 */
export function readinessBlockFromError(err: unknown, headline?: string): ReadinessBlockedError | null {
  const response = (err as { response?: { status?: number; data?: unknown } } | null | undefined)?.response;
  if (!response || response.status !== 409) return null;

  const data = response.data as { message?: unknown; blocks?: unknown } | null | undefined;
  if (!data || !Array.isArray(data.blocks)) return null;

  const blocks = data.blocks.filter(
    (b): b is ReadinessBlock =>
      !!b &&
      typeof (b as ReadinessBlock).code === "string" &&
      typeof (b as ReadinessBlock).message === "string",
  );
  if (blocks.length === 0) return null;

  const message = typeof data.message === "string" && data.message ? data.message : DEFAULT_MESSAGE;
  return { headline: headline ?? message, message, blocks };
}
