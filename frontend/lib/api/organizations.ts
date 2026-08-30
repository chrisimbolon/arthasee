// =============================================================================
// === frontend/lib/api/organizations.ts ===
// =============================================================================
import api from "@/lib/api";

export interface Organization {
  id:           string;
  name:         string;
  // Added 5 Aug — the backend serializer now includes this too
  // (previously silently omitted from GET /api/organizations/mine/,
  // a real gap for any settings page needing to display the current
  // value). Auto-generated from the shop's own name at creation time
  // — see Organization._generate_invoice_code() on the backend —
  // customizable any time via organizationsApi.update() below.
  invoice_code: string;
  // 29 Aug 2026 — real onboarding gate. phone/address stay editable
  // later via update() below, same as invoice_code already is.
  // onboarding_completed is read-only — it only ever flips via
  // completeOnboarding() below, never a generic settings edit.
  phone:        string;
  address:      string;
  onboarding_completed: boolean;
  plan:         string;
  is_active:    boolean;
  created_at:   string;
}

export interface CompleteOnboardingPayload {
  phone: string;
  address: string;
  invoice_code: string;
}

export const organizationsApi = {
  async mine(): Promise<{ organization: Organization; role: string } | null> {
    try {
      const { data } = await api.get("/api/organizations/mine/");
      return { organization: data.organization, role: data.role };
    } catch {
      return null;
    }
  },
  // Added 5 Aug — Organization Settings (/settings/organization).
  // Owner-only on the backend (a real 403 for anyone else) — this
  // client function doesn't re-check that itself, matching how every
  // other write-endpoint client in this app stays a thin wrapper and
  // leaves real enforcement to the server.
  // phone/address added 29 Aug 2026 — same "everything gathered at
  // onboarding stays editable in Settings afterward" philosophy
  // already established for invoice_code.
  async update(payload: { name?: string; invoice_code?: string; phone?: string; address?: string }): Promise<Organization> {
    const { data } = await api.patch("/api/organizations/mine/", payload);
    return data.organization;
  },

  // 29 Aug 2026 — the real, single action behind the mandatory
  // first-login welcome gate. All three fields required — this call
  // is only ever made from the onboarding overlay itself, never a
  // partial/optional context.
  async completeOnboarding(payload: CompleteOnboardingPayload): Promise<Organization> {
    const { data } = await api.post("/api/organizations/mine/complete-onboarding/", payload);
    return data.organization;
  },
};
