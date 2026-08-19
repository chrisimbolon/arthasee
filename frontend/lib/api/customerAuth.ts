// =============================================================================
// === frontend/lib/api/customerAuth.ts ===
// =============================================================================
// Fase 2.5 — real customer accounts, magic-link login. Deliberately a
// completely separate client from lib/api.ts's own `api` instance —
// that one attaches a CustomUser bearer token and auto-refreshes it
// on 401; this one attaches a Customer-scoped token (see
// backend/apps/customers/auth.py) with no refresh flow at all — a
// single 30-day token, by design (see
// generate_customer_access_token's own docstring for why no second,
// more complex token system was built for a v1 customer portal).
// Mixing both token types on one shared axios instance risked exactly
// the kind of accidental-permission-bleed Chris explicitly called out
// as the reason for full separation in the first place.
import type { PublicTracking } from "./tracking";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const STORAGE_KEY = "arthasee_customer_access_token";

export const customerTokenStorage = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(STORAGE_KEY);
  },
  set(token: string) {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, token);
  },
  clear() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(STORAGE_KEY);
  },
};

async function customerFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const token = customerTokenStorage.get();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    // Real session expiry (or a token that was never valid) — the
    // only sane recovery here is a fresh magic link, there's no
    // refresh-token dance to attempt for this token type.
    customerTokenStorage.clear();
  }
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.message || "Terjadi kesalahan.");
  }
  return data as T;
}

export interface CustomerSession {
  access: string;
  name:   string;
  email:  string;
}

export interface CustomerRegistrationPayload {
  full_name:    string;
  phone:        string;
  email:        string;
  plate_number: string;
}

export const customerAuthApi = {
  async requestMagicLink(email: string) {
    return customerFetch<{ success: boolean; message: string; dev_token?: string }>(
      "/api/customer-auth/magic-link/",
      { method: "POST", body: JSON.stringify({ email }) },
    );
  },
  // The missing path for a genuine first-time visitor — mandatory
  // login (confirmed directly) meant requestMagicLink() alone could
  // never onboard someone who has no Customer record yet. Same
  // response shape as requestMagicLink — including the same
  // self-eliminating dev_token passthrough — since both hit the
  // same real send_magic_link_email() path on the backend once a
  // Customer genuinely exists.
  async register(payload: CustomerRegistrationPayload) {
    return customerFetch<{ success: boolean; message: string; dev_token?: string }>(
      "/api/customer-auth/register/",
      { method: "POST", body: JSON.stringify(payload) },
    );
  },
  async verifyMagicLink(token: string): Promise<CustomerSession> {
    const data = await customerFetch<{ success: boolean; session: CustomerSession }>(
      "/api/customer-auth/magic-link/verify/",
      { method: "POST", body: JSON.stringify({ token }) },
    );
    return data.session;
  },
  logout() {
    customerTokenStorage.clear();
  },
};

export interface CustomerWorkOrderSummary {
  id:                string;
  work_order_number: string;
  status:            string;
  vehicle_plate:     string;
  vehicle_model:     string;
  created_at:        string;
}

export const customerWorkOrdersApi = {
  async list(): Promise<{ active: CustomerWorkOrderSummary[]; history: CustomerWorkOrderSummary[] }> {
    const data = await customerFetch<{ success: boolean; active: CustomerWorkOrderSummary[]; history: CustomerWorkOrderSummary[] }>(
      "/api/customer/work-orders/",
    );
    return { active: data.active, history: data.history };
  },
  // Same PublicTracking shape as fetchPublicTracking in tracking.ts —
  // both callers hit backend/apps/customers/payload.py's own shared
  // builder, so the response is genuinely identical either way.
  async get(id: string): Promise<PublicTracking> {
    const data = await customerFetch<{ success: boolean; tracking: PublicTracking }>(
      `/api/customer/work-orders/${id}/`,
    );
    return data.tracking;
  },
};
