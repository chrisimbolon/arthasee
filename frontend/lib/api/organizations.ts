// =============================================================================
// === frontend/lib/api/organizations.ts ===
// =============================================================================
import api from "@/lib/api";

export interface Organization {
  id:         string;
  name:       string;
  plan:       string;
  is_active:  boolean;
  created_at: string;
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
};
