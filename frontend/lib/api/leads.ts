// =============================================================================
// === frontend/lib/api/leads.ts ===
// =============================================================================
import api from "@/lib/api";

export type LeadReason = "TOO_EXPENSIVE" | "WENT_ELSEWHERE" | "POSTPONED" | "NOT_NEEDED" | "OTHER";
export type FollowUpStatus = "PENDING" | "CONTACTED" | "CONVERTED" | "CLOSED";

export interface RejectedQuote {
  id:                  string;
  name:                string;
  phone:               string;
  vehicle_description: string;
  quoted_description:  string;
  quoted_amount:       string | null;
  reason:              LeadReason;
  notes:               string;
  follow_up_status:    FollowUpStatus;
  created_by:          string | null;
  created_by_name:     string | null;
  created_at:          string;
  updated_at:          string;
}

export interface RejectedQuotePayload {
  name:                 string;
  phone?:               string;
  vehicle_description?: string;
  quoted_description?:  string;
  quoted_amount?:       number | null;
  reason?:              LeadReason;
  notes?:               string;
  follow_up_status?:    FollowUpStatus;
}

export const leadsApi = {
  async list(opts?: { followUpStatus?: FollowUpStatus }): Promise<RejectedQuote[]> {
    const params: Record<string, string> = {};
    if (opts?.followUpStatus) params.follow_up_status = opts.followUpStatus;
    const { data } = await api.get("/api/leads/rejected-quotes/", { params });
    return data.results;
  },
  async create(payload: RejectedQuotePayload): Promise<RejectedQuote> {
    const { data } = await api.post("/api/leads/rejected-quotes/", payload);
    return data.rejected_quote;
  },
  async update(id: string, payload: Partial<RejectedQuotePayload>): Promise<RejectedQuote> {
    const { data } = await api.put(`/api/leads/rejected-quotes/${id}/`, payload);
    return data.rejected_quote;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/api/leads/rejected-quotes/${id}/`);
  },
};
