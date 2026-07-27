// =============================================================================
// === frontend/lib/api/workorders.ts ===
// =============================================================================
import api from "@/lib/api";

export type WorkOrderStatus = "OPEN" | "IN_PROGRESS" | "QC" | "DONE" | "CANCELLED";

export interface WorkOrderJobLine {
  id:          string;
  work_order:  string;
  // Optional grouping into a WorkOrderStage — null for the
  // overwhelming majority of job lines (routine, single-visit
  // repairs never use stages at all). See WorkOrderStage below.
  stage:       string | null;
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

// Made's own request: a custom, per-repair breakdown of heavy jobs
// (collision, overhaul) into named stages — body work, painting,
// reassembly, etc. — each with its own start/complete clock time,
// eventually feeding a "Vehicle Timeline" view Made can check
// remotely without being physically at the shop. Deliberately
// optional and additive: a routine job's WorkOrder simply has zero
// stages, and nothing about its UI or data changes because of that.
export interface WorkOrderStage {
  id:            string;
  work_order:    string;
  name:          string;
  sequence:      number;
  started_at:    string | null;
  completed_at:  string | null;
  // Only the job lines currently grouped under this specific stage —
  // a convenience view, not a separate source of truth from
  // WorkOrder.job_lines' own flat list.
  job_lines:     WorkOrderJobLine[];
  created_at:    string;
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
  // Made's own request — "jam mulai dikerjakan," the exact clock
  // time work actually began, not just the date. Set automatically
  // the instant status first moves to IN_PROGRESS — see the
  // backend's WorkOrder.mark_started() for the exact rule. Stays
  // null forever for a Work Order with no Estimate origin; per
  // Made's own phrasing, this concept only applies to a Work Order
  // born from an approved Estimate.
  work_started_at:     string | null;
  service_record:      string | null;
  job_lines:           WorkOrderJobLine[];
  material_lines:      WorkOrderMaterialLine[];
  stages:              WorkOrderStage[];
  created_by:          string | null;
  created_by_name:     string | null;
  created_at:          string;
  updated_at:          string;
}

// Lighter shape returned by the list endpoint — no nested lines,
// matching WorkOrderListSerializer on the backend.
export type WorkOrderSummary = Omit<WorkOrder, "job_lines" | "material_lines" | "stages">;

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
  // backend's own explicit split). Moving into IN_PROGRESS also
  // silently sets work_started_at server-side — nothing extra to
  // pass here, the caller just sees it appear in the response.
  async updateStatus(id: string, status: "OPEN" | "IN_PROGRESS" | "QC"): Promise<WorkOrder> {
    const { data } = await api.patch(`/api/work-orders/${id}/status/`, { status });
    return data.work_order;
  },
  async close(id: string, serviceDate?: string): Promise<WorkOrder> {
    const { data } = await api.post(`/api/work-orders/${id}/close/`, serviceDate ? { service_date: serviceDate } : {});
    return data.work_order;
  },
  async cancel(id: string): Promise<WorkOrder> {
    const { data } = await api.post(`/api/work-orders/${id}/cancel/`);
    return data.work_order;
  },
};

export const workOrderJobLinesApi = {
  // stageId is optional — omit it entirely for a routine, unstaged
  // job line, exactly as this already worked before stages existed.
  async create(workOrderId: string, description: string, stageId?: string): Promise<WorkOrderJobLine> {
    const { data } = await api.post(`/api/work-orders/${workOrderId}/job-lines/`, {
      description, ...(stageId ? { stage: stageId } : {}),
    });
    return data.job_line;
  },
  async toggle(id: string): Promise<WorkOrderJobLine> {
    const { data } = await api.patch(`/api/work-orders/job-lines/${id}/toggle/`);
    return data.job_line;
  },
  // Moves an existing job line into a stage, or clears it back to
  // unstaged with stageId = null — lets a line created before any
  // stage existed get grouped in later.
  async assignStage(id: string, stageId: string | null): Promise<WorkOrderJobLine> {
    const { data } = await api.patch(`/api/work-orders/job-lines/${id}/assign-stage/`, { stage: stageId });
    return data.job_line;
  },
};

export const workOrderMaterialLinesApi = {
  async create(workOrderId: string, payload: { part: string; quantity: number }): Promise<WorkOrderMaterialLine> {
    const { data } = await api.post(`/api/work-orders/${workOrderId}/material-lines/`, payload);
    return data.material_line;
  },
  // Deleting reverses the stock it deducted — see the backend's own
  // WorkOrderMaterialLineDetailView docstring for why. reason
  // distinguishes a genuine customer cancellation (Made's own
  // described scenario) from a plain data-entry correction, so the
  // audit trail stays honest about which actually happened.
  async remove(id: string, reason: "correction" | "customer_cancelled_part" = "correction"): Promise<void> {
    await api.delete(`/api/work-orders/material-lines/${id}/`, { data: { reason } });
  },
};

export const workOrderStagesApi = {
  async create(workOrderId: string, name: string): Promise<WorkOrderStage> {
    const { data } = await api.post(`/api/work-orders/${workOrderId}/stages/`, { name });
    return data.stage;
  },
  async update(id: string, payload: { name?: string; sequence?: number }): Promise<WorkOrderStage> {
    const { data } = await api.put(`/api/work-orders/stages/${id}/`, payload);
    return data.stage;
  },
  async remove(id: string): Promise<void> {
    // Never deletes the job lines grouped under it — see the
    // backend's own WorkOrderStageDetailView.delete() docstring.
    await api.delete(`/api/work-orders/stages/${id}/`);
  },
  async start(id: string): Promise<WorkOrderStage> {
    const { data } = await api.post(`/api/work-orders/stages/${id}/start/`);
    return data.stage;
  },
  async complete(id: string): Promise<WorkOrderStage> {
    const { data } = await api.post(`/api/work-orders/stages/${id}/complete/`);
    return data.stage;
  },
};
