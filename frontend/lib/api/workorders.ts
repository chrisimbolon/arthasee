// =============================================================================
// === frontend/lib/api/workorders.ts ===
// =============================================================================
import api from "@/lib/api";

export type WorkOrderStatus = "OPEN" | "IN_PROGRESS" | "QC" | "DONE" | "CANCELLED";

export interface WorkOrderJobLine {
  id:          string;
  work_order:  string;
  description: string;
  is_done:     boolean;
  created_at:  string;
}

export interface WorkOrderMaterialLine {
  id:                 string;
  work_order:         string;
  part:               string;
  part_name:          string;
  unit:               string;
  quantity:           string;
  unit_price_at_time: string;
  subtotal:           string;
  created_at:         string;
}

export interface WorkOrder {
  id:                  string;
  vehicle:             string;
  vehicle_plate:       string;
  customer_name:       string;
  number:              string;
  sequence_number:     number;
  status:              WorkOrderStatus;
  odometer_km_intake:  number | null;
  received_by:         string;
  notes:               string;
  service_record:      string | null;
  job_lines:           WorkOrderJobLine[];
  material_lines:      WorkOrderMaterialLine[];
  created_by:          string | null;
  created_by_name:     string | null;
  created_at:          string;
  updated_at:          string;
}

// Lighter shape returned by the list endpoint — no nested lines,
// matching WorkOrderListSerializer on the backend.
export type WorkOrderSummary = Omit<WorkOrder, "job_lines" | "material_lines">;

export interface WorkOrderIntakePayload {
  odometer_km_intake?: number;
  received_by?:        string;
  notes?:               string;
}

export const workOrdersApi = {
  async list(vehicleId: string): Promise<WorkOrderSummary[]> {
    const { data } = await api.get(`/api/vehicles/${vehicleId}/work-orders/`);
    return data.results;
  },
  async create(vehicleId: string, payload: WorkOrderIntakePayload = {}): Promise<WorkOrder> {
    const { data } = await api.post(`/api/vehicles/${vehicleId}/work-orders/`, payload);
    return data.work_order;
  },
  async get(id: string): Promise<WorkOrder> {
    const { data } = await api.get(`/api/work-orders/${id}/`);
    return data.work_order;
  },
  async update(id: string, payload: WorkOrderIntakePayload): Promise<WorkOrder> {
    const { data } = await api.put(`/api/work-orders/${id}/`, payload);
    return data.work_order;
  },
  // Only ever OPEN/IN_PROGRESS/QC — DONE and CANCELLED go through
  // close()/cancel() below, which carry real side effects a bare
  // status write must never trigger implicitly (matches the
  // backend's own explicit split).
  async updateStatus(id: string, status: "OPEN" | "IN_PROGRESS" | "QC"): Promise<WorkOrder> {
    const { data } = await api.patch(`/api/work-orders/${id}/status/`, { status });
    return data.work_order;
  },
  async close(id: string): Promise<WorkOrder> {
    const { data } = await api.post(`/api/work-orders/${id}/close/`);
    return data.work_order;
  },
  async cancel(id: string): Promise<WorkOrder> {
    const { data } = await api.post(`/api/work-orders/${id}/cancel/`);
    return data.work_order;
  },
};

export const workOrderJobLinesApi = {
  async create(workOrderId: string, description: string): Promise<WorkOrderJobLine> {
    const { data } = await api.post(`/api/work-orders/${workOrderId}/job-lines/`, { description });
    return data.job_line;
  },
  async toggle(id: string): Promise<WorkOrderJobLine> {
    const { data } = await api.patch(`/api/work-orders/job-lines/${id}/toggle/`);
    return data.job_line;
  },
};

export const workOrderMaterialLinesApi = {
  async create(workOrderId: string, payload: { part: string; quantity: number }): Promise<WorkOrderMaterialLine> {
    const { data } = await api.post(`/api/work-orders/${workOrderId}/material-lines/`, payload);
    return data.material_line;
  },
  // Deleting reverses the stock it deducted — see the backend's own
  // WorkOrderMaterialLineDetailView docstring for why.
  async remove(id: string): Promise<void> {
    await api.delete(`/api/work-orders/material-lines/${id}/`);
  },
};
