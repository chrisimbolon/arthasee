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

// A real, lightweight roster entry — deliberately NOT a login-
// capable user (mechanics still never log into the system at all).
// Exists purely so a dashboard can honestly count "how many
// mechanics are currently working" against a real total, rather
// than a fabricated stat — Made's own words: "kenapa mechanic hanya
// 3 yg kerja? 3 dari 6". No delete — see mechanicsApi.remove's own
// absence below; deactivation via update() is the only removal path.
export interface Mechanic {
  id:         string;
  name:       string;
  is_active:  boolean;
  created_at: string;
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
  // Optional — nothing about starting/completing a stage requires
  // an assignment, same "trust human judgment" philosophy as
  // completing a stage never requiring all its job lines done.
  assigned_to:      string | null;
  assigned_to_name: string | null;
  // Nullable override of the backend's shared default duration
  // threshold — a genuinely heavy stage (body repair, painting)
  // legitimately takes longer than routine work without being a
  // real problem.
  expected_duration_hours: string | null;
  started_at:    string | null;
  completed_at:  string | null;
  // Made's own literal example: a job taking longer than expected.
  // Computed on the backend, never stored — see is_overdue on
  // WorkOrder below for the same pattern.
  is_overdue:    boolean;
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
  // Made's own literal example: an oil change + brake pads taking
  // more than 2 hours. Computed on read, never stored.
  is_overdue:          boolean;
  // Made's own explicit reason, confirmed 31 Jul: a specific
  // mechanic must be identifiable on every job, even routine work,
  // so he can go back and question that person directly if the same
  // car has an issue again. Distinct from each WorkOrderStage's own
  // assigned_to (see WorkOrderStage below) — that one only applies
  // to heavy, multi-phase jobs; this is the single mechanic
  // responsible for the job as a whole, the common case for most
  // real work. Optional here — the real hard requirement ("no
  // invoice without a mechanic assigned") is enforced at invoice-
  // creation time on the backend, not here.
  assigned_to:         string | null;
  assigned_to_name:    string | null;
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
  // null explicitly clears the assignment, undefined leaves it
  // untouched — same "omit vs. null" distinction already used
  // elsewhere in this API.
  assigned_to?:        string | null;
}

// The real backend for all four of Made's own numbered Owner
// Dashboard requirements from the 28 Jul meeting — one aggregating
// call for one dashboard screen, rather than four separate ones.
export interface DashboardSummary {
  mechanics: { active: number; working: number };
  vehicles_cleared: { count: number; period: "today" | "week" | "month" | "year" };
  work_orders: { queued: number; in_progress: number };
  overdue: {
    work_orders: Array<{
      id: string; number: string; vehicle_plate: string;
      work_started_at: string; hours_elapsed: number;
    }>;
    stages: Array<{
      id: string; name: string; work_order_id: string; work_order_number: string;
      started_at: string; hours_elapsed: number;
    }>;
  };
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
  // Made's own confirmed answer, 1 Aug: an internal, no-price job
  // ticket for the mechanic, available the moment "Mulai Dikerjakan"
  // is clicked. Returns a real Blob, not JSON — same reasoning as
  // estimatesApi.downloadQuotationPdf: this API authenticates with a
  // bearer token in a header, which a plain <a href> has no way to
  // attach, so the caller fetches through this same authenticated
  // axios instance and triggers the download manually. Backend hard-
  // gates on status !== "OPEN" (409 otherwise) — deliberately NOT
  // work_started_at, which is Estimate-only and stays null forever
  // for a direct-entry WorkOrder. This method doesn't duplicate that
  // check; the caller is expected to only offer it once wo.status
  // has left "OPEN".
  async downloadJobTicketPdf(id: string): Promise<Blob> {
    const { data } = await api.get(`/api/work-orders/${id}/job-ticket.pdf`, { responseType: "blob" });
    return data;
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
  async update(
    id: string,
    payload: { name?: string; sequence?: number; assigned_to?: string | null; expected_duration_hours?: string | null },
  ): Promise<WorkOrderStage> {
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

export const mechanicsApi = {
  async list(): Promise<Mechanic[]> {
    const { data } = await api.get("/api/mechanics/");
    return data.results;
  },
  async create(name: string): Promise<Mechanic> {
    const { data } = await api.post("/api/mechanics/", { name });
    return data.mechanic;
  },
  // No remove() — deliberately. Deactivation (update with
  // is_active: false) is the only removal path; see Mechanic's own
  // docstring in the backend for why a hard delete is never exposed.
  async update(id: string, payload: { name?: string; is_active?: boolean }): Promise<Mechanic> {
    const { data } = await api.put(`/api/mechanics/${id}/`, payload);
    return data.mechanic;
  },
};

// B2 in the sprint review — a full roster of everything currently in
// motion across the shop, not just the overdue subset the Owner
// Dashboard's own summary already surfaces.
export interface ActiveJob {
  id:                     string;
  number:                 string;
  vehicle_plate:          string;
  customer_name:          string;
  status:                 WorkOrderStatus;
  elapsed_since:          string;
  // Deliberately an approximation for a direct-entry WorkOrder (no
  // Estimate origin) — see the backend's own ActiveJobsView
  // docstring for exactly why work_started_at can be null there,
  // falling back to created_at instead.
  elapsed_hours:          number;
  current_stage_name:     string | null;
  current_stage_mechanic: string | null;
  is_overdue:             boolean;
}

export const activeJobsApi = {
  async list(): Promise<ActiveJob[]> {
    const { data } = await api.get("/api/work-orders/active/");
    return data.results;
  },
};

export const dashboardApi = {
  async summary(period: "today" | "week" | "month" | "year" = "today"): Promise<DashboardSummary> {
    const { data } = await api.get("/api/dashboard/summary/", { params: { period } });
    return data;
  },
};
