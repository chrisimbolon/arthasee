// =============================================================================
// === frontend/lib/api/staffAppointments.ts ===
// =============================================================================
// Staff-facing — uses the SAME shared `api` instance as every other
// internal dashboard client (accounting.ts, purchasing.ts), NOT
// customerFetch from customerAuth.ts. Genuinely separate identity
// system from the customer-facing lib/api/appointments.ts client —
// same "two separate token systems, never share one instance"
// reasoning already established for customerAuth.ts vs api.ts.
import api from "@/lib/api";

export interface TenantAppointment {
  id:              string;
  requested_date:  string;
  notes:           string;
  status:          "CONFIRMED" | "CONVERTED" | "CANCELLED";
  customer_name:   string;
  customer_phone:  string;
  vehicle_plate:   string;
  vehicle_model:   string;
  created_at:      string;
}

export const staffAppointmentsApi = {
  async list(all?: boolean): Promise<TenantAppointment[] | null> {
    try {
      const { data } = await api.get("/api/appointments/", { params: all ? { all: "1" } : {} });
      return data.results;
    } catch {
      return null;
    }
  },
  // convert/cancel deliberately THROW rather than swallow — a real,
  // specific error can come back here (someone else already
  // converted or cancelled this exact appointment a moment ago),
  // and staff genuinely need to see that message, not a silent
  // failure. Matches the same discipline already used for the
  // customer-facing create() call.
  async convert(id: string): Promise<{ appointment: TenantAppointment; workOrderId: string }> {
    const { data } = await api.post(`/api/appointments/${id}/convert/`);
    return { appointment: data.appointment, workOrderId: data.work_order_id };
  },
  async cancel(id: string): Promise<TenantAppointment> {
    const { data } = await api.post(`/api/appointments/${id}/cancel/`);
    return data.appointment;
  },
};
