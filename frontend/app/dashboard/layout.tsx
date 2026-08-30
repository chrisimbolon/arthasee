"use client";
// =============================================================================
// === frontend/app/dashboard/layout.tsx ===
// =============================================================================
import Sidebar from "@/components/layout/Sidebar";
import OnboardingOverlay from "@/components/onboarding/OnboardingOverlay";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, organization, loading, refreshOrganization } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--steel)" }}>
        <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  // 29 Aug 2026 — real, mandatory first-login welcome gate, Chris's
  // own confirmed design: un-skippable, intercepts every real
  // dashboard page (not just some) until the shop's profile is
  // genuinely complete. organization can legitimately be null here
  // (a real 404 from /api/organizations/mine/ — e.g. a user with no
  // active membership at all) — the gate only ever fires for a real,
  // known organization still missing its own setup, never for a
  // missing-organization state that's an entirely different problem.
  if (organization && !organization.onboarding_completed) {
    return <OnboardingOverlay organization={organization} onComplete={refreshOrganization} />;
  }

  return (
    <div style={{ display: "flex" }}>
      <Sidebar />
      <main style={{ flex: 1, padding: "32px 40px", maxWidth: 1100 }}>
        {children}
      </main>
    </div>
  );
}
