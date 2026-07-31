// =============================================================================
// === frontend/lib/api/estimates.ts ===
// =============================================================================
import api from "@/lib/api";

export type EstimateStatus = "PENDING" | "APPROVED" | "REJECTED";
export type EstimateLineKind = "part" | "labor";
export type EstimateRejectionReason = "TOO_EXPENSIVE" | "WENT_ELSEWHERE" | "POSTPONED" | "NOT_NEEDED" | "OTHER";

export interface EstimateLineItem {
  id:          string;
  estimate:    string;
  kind:        EstimateLineKind;
  description: string;
  quantity:    string;
  unit_price:  string;
  part:        string | null;
  part_name:   string | null;
  subtotal:    string;
  created_at:  string;
}

export interface Estimate {
  id:                string;
  vehicle:           string;
  vehicle_plate:     string;
  customer_name:     string;
  number:            string;
  sequence_number:   number;
  status:            EstimateStatus;
  diagnosis_notes:   string;
  // Chris's own framing, 31 Jul: "estimasi is like a gate" — real
  // odometer capture belongs here, before any diagnosis/quote work,
  // not left until WorkOrder creation. odometer_km_intake is
  // writable (only while PENDING, enforced backend-side);
  // last_service_odometer_km is read-only, pulled directly from
  // Vehicle.last_service_odometer_km — already correctly maintained
  // elsewhere, not something this page computes itself.
  odometer_km_intake:       number | null;
  last_service_odometer_km: number | null;
  rejection_reason:  EstimateRejectionReason | "";
  rejection_notes:   string;
  work_order:        string | null;
  line_items:        EstimateLineItem[];
  total:             string;
  created_by:        string | null;
  created_by_name:   string | null;
  created_at:        string;
  updated_at:        string;
}

export type EstimateSummary = Omit<Estimate, "line_items">;

export const estimatesApi = {
  async list(vehicleId: string): Promise<EstimateSummary[]> {
    const { data } = await api.get(`/api/vehicles/${vehicleId}/estimates/`);
    return data.results;
  },
  async create(vehicleId: string, diagnosisNotes?: string): Promise<Estimate> {
    const { data } = await api.post(`/api/vehicles/${vehicleId}/estimates/`, diagnosisNotes ? { diagnosis_notes: diagnosisNotes } : {});
    return data.estimate;
  },
  async get(id: string): Promise<Estimate> {
    const { data } = await api.get(`/api/estimates/${id}/`);
    return data.estimate;
  },
  async updateNotes(id: string, diagnosisNotes: string): Promise<Estimate> {
    const { data } = await api.put(`/api/estimates/${id}/`, { diagnosis_notes: diagnosisNotes });
    return data.estimate;
  },
  // Backend hard-blocks (400) if less than the vehicle's last
  // recorded service odometer — the caller is responsible for
  // surfacing that real validation message, not a generic one.
  async updateOdometer(id: string, odometerKmIntake: number): Promise<Estimate> {
    const { data } = await api.put(`/api/estimates/${id}/`, { odometer_km_intake: odometerKmIntake });
    return data.estimate;
  },
  async approve(id: string): Promise<Estimate> {
    const { data } = await api.post(`/api/estimates/${id}/approve/`);
    return data.estimate;
  },
  async reject(id: string, reason: EstimateRejectionReason, notes?: string): Promise<Estimate> {
    const { data } = await api.post(`/api/estimates/${id}/reject/`, { reason, notes });
    return data.estimate;
  },
  // Made's own urgent ask, 30 Jul follow-up: a real, downloadable
  // PDF so SA/cashier can forward it themselves via their own
  // WhatsApp — deliberately separate from the still-on-hold
  // automated WhatsApp integration. Returns a real Blob, not JSON —
  // same reasoning as contractsApi.exportTermin: this API
  // authenticates with a bearer token in a header, which a plain
  // <a href> link has no way to attach, so the caller fetches
  // through this same authenticated axios instance and triggers the
  // download manually.
  async downloadQuotationPdf(id: string): Promise<Blob> {
    const { data } = await api.get(`/api/estimates/${id}/quotation.pdf`, { responseType: "blob" });
    return data;
  },
};

export const estimateLineItemsApi = {
  async create(estimateId: string, payload: {
    kind: EstimateLineKind; description: string; quantity?: number; unit_price: number; part?: string;
  }): Promise<EstimateLineItem> {
    const { data } = await api.post(`/api/estimates/${estimateId}/line-items/`, payload);
    return data.line_item;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/api/estimates/line-items/${id}/`);
  },
};
