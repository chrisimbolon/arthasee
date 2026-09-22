"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/opening-balance/page.tsx ===
// =============================================================================
// 22 Sep 2026 — Roadmap Open Decision #33: a real destination for the
// readiness gate's OPEN_OPENING_BALANCE block, for a shop that is already
// past first login (Arya Motor's own case — its `onboarding_completed` flag
// was switched on by hand in Phase 13, so it never saw the wizard, and the
// Ringkasan banner's own button had nowhere to send it — see Roadmap Task
// 19.8). An ordinary page in the dashboard layout, sidebar included — this
// is no longer a hard, unskippable first-login gate, so it should not look
// or feel like one.
//
// Reuses OpeningBalanceStep exactly as onboarding uses it — same six-category
// wizard, same preview/variance-confirmation flow, same "Bengkel Baru" escape
// hatch (now with a warning: see OnboardingOverlay.tsx) — with `embedded`
// making it render as a normal in-page card instead of a full-screen modal.
//
// onComplete() calls organizationsApi.completeOnboarding() internally
// (unchanged): safe here because a POST that already succeeded, or an
// explicit "Bengkel Baru" click, always happens first — by the time that
// call fires, this org's OpeningBalanceSession already exists, so the
// backend's own "no session exists yet" branch (which auto-confirms zero)
// never runs for a shop arriving here. Verified by reading
// OrganizationOnboardingCompleteView (backend/apps/organizations/views.py)
// before wiring this up.
import { OpeningBalanceStep } from "@/components/onboarding/OnboardingOverlay";
import { useRouter } from "next/navigation";

export default function OpeningBalancePage() {
  const router = useRouter();

  return (
    <div>
      <h1 className="display" style={{ fontSize: 34, marginBottom: 4 }}>Saldo Awal Bengkel</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 20, maxWidth: 640 }}>
        Catat kas, stok, aset, piutang, atau utang yang sudah ada sebelum bengkel ini memakai
        Arthasee, supaya laporan keuangan akurat sejak hari pertama.
      </p>
      <OpeningBalanceStep embedded onComplete={() => router.push("/dashboard")} />
    </div>
  );
}
