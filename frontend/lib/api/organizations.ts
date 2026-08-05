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
  plan:         string;
  is_active:    boolean;
  created_at:   string;
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
  async update(payload: { name?: string; invoice_code?: string }): Promise<Organization> {
    const { data } = await api.patch("/api/organizations/mine/", payload);
    return data.organization;
  },
};
