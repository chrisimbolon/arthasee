// =============================================================================
// === frontend/lib/api/tracking.ts ===
// =============================================================================
import api from "@/lib/api";

export interface TrackingLink {
  id:              string;
  work_order:      string;
  token:           string;
  is_revoked:      boolean;
  last_viewed_at:  string | null;
  view_count:      number;
  created_at:      string;
}

export const trackingLinksApi = {
  async list(workOrderId: string): Promise<TrackingLink[]> {
    const { data } = await api.get(`/api/work-orders/${workOrderId}/tracking-links/`);
    return data.results;
  },
  async create(workOrderId: string): Promise<TrackingLink> {
    const { data } = await api.post(`/api/work-orders/${workOrderId}/tracking-links/`);
    return data.tracking_link;
  },
  async revoke(id: string): Promise<TrackingLink> {
    const { data } = await api.post(`/api/tracking-links/${id}/revoke/`);
    return data.tracking_link;
  },
};

// ── Public tracking (unauthenticated) ───────────────────────────────
// Deliberately NOT using the shared `api` axios instance above, which
// attaches an internal bearer token to every request. The public
// /track page has no session at all — a plain fetch() keeps that
// boundary explicit rather than relying on the shared client
// happening to still work with no token attached.
//
// NEXT_PUBLIC_API_URL, confirmed against the real frontend/lib/api.ts
// — same env var, same fallback default, so a public track page
// hitting a fresh local dev environment behaves identically to every
// other page in this app rather than silently pointing at a relative
// empty-string base URL.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface PublicStage {
  name:         string;
  status:       "Menunggu" | "Sedang Berjalan" | "Selesai";
  started_at:   string | null;
  completed_at: string | null;
}

export interface PublicInvoice {
  number:                 string;
  mechanic_name_snapshot: string;
  total:                  string;
  status:                 string;
}

export interface PublicTracking {
  work_order_number: string;
  status:             string;
  vehicle_plate:      string;
  vehicle_model:       string;
  mechanic_name:       string | null;
  stages:              PublicStage[];
  invoice:             PublicInvoice | null;
}

export async function fetchPublicTracking(token: string): Promise<PublicTracking> {
  const res = await fetch(`${API_BASE}/api/track/${encodeURIComponent(token)}/`);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "not_found" : "unknown");
  }
  const data = await res.json();
  return data.tracking;
}
