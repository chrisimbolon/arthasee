// =============================================================================
// === frontend/lib/api/service.ts ===
// =============================================================================
import api from "@/lib/api";

export interface Customer {
  id:            string;
  name:          string;
  phone:         string;
  stnk_name:     string;
  vehicle_count: number;
  created_at:    string;
  updated_at:    string;
}

export interface ServiceRecord {
  id:                string;
  vehicle:           string;
  service_date:      string;
  odometer_km:       number;
  issue_description: string;
  parts_replaced:    string;
  notes:             string;
  created_by:        string | null;
  created_by_name:   string | null;
  created_at:        string;
}

export interface Vehicle {
  id:                       string;
  customer:                 string;
  customer_name:            string;
  plate_number:             string;
  manufacture_year:         number;
  vehicle_type:             string;
  model:                    string;
  current_odometer_km:      number;
  last_service_date:        string | null;
  last_service_odometer_km: number | null;
  is_due_for_service:       boolean;
  service_records?:         ServiceRecord[];
  created_at:               string;
  updated_at:               string;
}

export interface ApiErrorShape {
  success: false;
  errors?:  Record<string, string[]>;
  message?: string;
}

export const customersApi = {
  async list(search?: string): Promise<Customer[]> {
    const { data } = await api.get("/api/customers/", { params: search ? { search } : {} });
    return data.results;
  },
  async create(payload: { name: string; phone?: string; stnk_name?: string }): Promise<Customer> {
    const { data } = await api.post("/api/customers/", payload);
    return data.customer;
  },
  async update(id: string, payload: Partial<{ name: string; phone: string; stnk_name: string }>): Promise<Customer> {
    const { data } = await api.put(`/api/customers/${id}/`, payload);
    return data.customer;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/api/customers/${id}/`);
  },
};

export const vehiclesApi = {
  async list(dueForService?: boolean): Promise<Vehicle[]> {
    const { data } = await api.get("/api/vehicles/", {
      params: dueForService ? { due_for_service: "true" } : {},
    });
    return data.results;
  },
  async get(id: string): Promise<Vehicle> {
    const { data } = await api.get(`/api/vehicles/${id}/`);
    return data.vehicle;
  },
  async create(payload: {
    customer: string; plate_number: string; manufacture_year: number;
    vehicle_type: string; model: string; current_odometer_km?: number;
  }): Promise<Vehicle> {
    const { data } = await api.post("/api/vehicles/", payload);
    return data.vehicle;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/api/vehicles/${id}/`);
  },
};

export const serviceRecordsApi = {
  async list(vehicleId: string): Promise<ServiceRecord[]> {
    const { data } = await api.get(`/api/vehicles/${vehicleId}/service-records/`);
    return data.results;
  },
  async create(vehicleId: string, payload: {
    service_date: string; odometer_km: number;
    issue_description: string; parts_replaced?: string; notes?: string;
  }): Promise<ServiceRecord> {
    const { data } = await api.post(`/api/vehicles/${vehicleId}/service-records/`, payload);
    return data.service_record;
  },
};
