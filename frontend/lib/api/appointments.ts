// =============================================================================
// === frontend/lib/api/appointments.ts ===
// =============================================================================
// Reuses customerFetch from customerAuth.ts — same token handling,
// same 401-clearing behavior, not duplicated here.
import { customerFetch } from "./customerAuth";

export interface AppointmentAvailabilityDay {
  date:      string;
  booked:    number;
  capacity:  number;
  available: boolean;
}

export interface Appointment {
  id:              string;
  requested_date:  string;
  notes:           string;
  status:          "CONFIRMED" | "CONVERTED" | "CANCELLED";
  vehicle_plate:   string;
  vehicle_model:   string;
  created_at:      string;
}

export interface CustomerVehicle {
  id:                string;
  plate_number:      string;
  model:             string;
  manufacture_year:  number;
}

export interface AppointmentCreatePayload {
  vehicle_id:      string;
  requested_date:  string;
  notes?:          string;
}

export const appointmentsApi = {
  async availability(since?: string, asOf?: string): Promise<AppointmentAvailabilityDay[]> {
    const params = new URLSearchParams();
    if (since) params.set("since", since);
    if (asOf) params.set("as_of", asOf);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const data = await customerFetch<{ success: boolean; days: AppointmentAvailabilityDay[] }>(
      `/api/customer/appointments/availability/${qs}`,
    );
    return data.days;
  },
  async list(): Promise<Appointment[]> {
    const data = await customerFetch<{ success: boolean; results: Appointment[] }>(
      "/api/customer/appointments/",
    );
    return data.results;
  },
  // A real, specific error CAN come back here (day is full, past
  // date) — customerFetch() throws the backend's own message, same
  // as the self-registration flow, so the caller can show the real
  // reason, not a generic failure.
  async create(payload: AppointmentCreatePayload): Promise<Appointment> {
    const data = await customerFetch<{ success: boolean; appointment: Appointment }>(
      "/api/customer/appointments/",
      { method: "POST", body: JSON.stringify(payload) },
    );
    return data.appointment;
  },
  async cancel(id: string): Promise<Appointment> {
    const data = await customerFetch<{ success: boolean; appointment: Appointment }>(
      `/api/customer/appointments/${id}/cancel/`,
      { method: "POST" },
    );
    return data.appointment;
  },
};

export const customerVehiclesApi = {
  async list(): Promise<CustomerVehicle[]> {
    const data = await customerFetch<{ success: boolean; results: CustomerVehicle[] }>(
      "/api/customer/vehicles/",
    );
    return data.results;
  },
};
