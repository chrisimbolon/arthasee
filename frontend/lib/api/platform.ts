// =============================================================================
// === frontend/lib/api/platform.ts ===
// Phase 22 (24 Oct 2026) — the super admin's read-only platform overview.
// Mirrors backend/apps/organizations/platform_health.py.
// =============================================================================
import api from "@/lib/api";

export type ShopStatus = "red" | "amber" | "green";

export interface ActivityCount { last_7_days: number; last_30_days: number }

export interface ControlAccountCheck {
  account_code:     string;
  account_name?:    string;
  available:        boolean;
  gl_balance?:      string | number;
  subledger_total?: string | number;
  difference?:      string | number;
  is_reconciled?:   boolean;
}

export interface ShopHealth {
  id:                   string;
  name:                 string;
  invoice_code:         string;
  plan:                 string;
  is_active:            boolean;
  created_at:           string;
  onboarding_completed: boolean;
  logins:               number;
  activity: {
    work_orders: ActivityCount;
    invoices:    ActivityCount;
    payments:    ActivityCount;
    last_activity_at: string | null;
  };
  books: {
    trial_balance_balanced:   boolean;
    trial_balance_difference: string | number;
    control_accounts:         ControlAccountCheck[];
  };
  readiness: { ready: boolean; blocks: string[]; warnings: string[] };
  events: {
    failed:        number;
    stuck_pending: number;
    last_failure: { event_type: string; occurred_at: string; attempts: number; error: string } | null;
  };
  status:  ShopStatus;
  reasons: string[];
}

export interface PlatformOverview {
  generated_at: string;
  totals: { shops: number; active_last_7_days: number; red: number; amber: number; green: number };
  shops: ShopHealth[];
}

export const platformApi = {
  async overview(): Promise<PlatformOverview> {
    const { data } = await api.get("/api/platform/overview/");
    return data;
  },
};
