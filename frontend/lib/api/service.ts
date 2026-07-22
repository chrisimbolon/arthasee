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

export interface PartUsageSummary {
  id:                 string;
  part:               string;
  part_name:          string;
  quantity:           string;
  unit:               string;
  unit_price_at_time: string;
}

export interface ServiceRecord {
  id:                string;
  vehicle:           string;
  service_date:      string;
  odometer_km:       number;
  issue_description: string;
  parts_replaced:    string;
  notes:             string;
  part_usages:       PartUsageSummary[];
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
  body_style:               string;
  model:                    string;
  chassis_number:           string;
  engine_number:            string;
  bpkb_number:              string;
  color:                    string;
  registration_expiry:      string | null;
  current_odometer_km:      number;
  last_service_date:        string | null;
  last_service_odometer_km: number | null;
  is_due_for_service:       boolean;
  is_registration_expiring_soon: boolean;
  service_records?:         ServiceRecord[];
  created_at:               string;
  updated_at:               string;
}

export interface Part {
  id:            string;
  name:          string;
  sku:           string;
  unit:          string;
  current_stock: string;   // DecimalField serializes as string — do not coerce to number for display without parseFloat
  unit_price:    string;
  created_at:    string;
  updated_at:    string;
}

export interface PartUsage {
  id:                 string;
  service_record:     string;
  part:                string;
  part_name:          string;
  unit:               string;
  quantity:           string;
  unit_price_at_time: string;
  resulting_stock:    string;
  created_at:         string;
}

export interface StockAdjustment {
  id:               string;
  part:             string;
  part_name:        string;
  quantity_change:  string;
  reason:           "restock" | "correction" | "damage";
  notes:            string;
  created_by:       string | null;
  created_by_name:  string | null;
  resulting_stock:  string;
  created_at:       string;
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

export interface VehicleCreatePayload {
  customer: string; plate_number: string; manufacture_year: number;
  vehicle_type: string; model: string; current_odometer_km?: number;
  // Sprint 1 additions — all optional, matching the backend's
  // blank=True fields, since STNK data fills in over time rather
  // than being required at creation.
  body_style?: string; chassis_number?: string; engine_number?: string;
  bpkb_number?: string; color?: string; registration_expiry?: string;
}

export const vehiclesApi = {
  async list(opts?: { dueForService?: boolean; registrationExpiringSoon?: boolean }): Promise<Vehicle[]> {
    const params: Record<string, string> = {};
    if (opts?.dueForService) params.due_for_service = "true";
    if (opts?.registrationExpiringSoon) params.registration_expiring_soon = "true";
    const { data } = await api.get("/api/vehicles/", { params });
    return data.results;
  },
  async get(id: string): Promise<Vehicle> {
    const { data } = await api.get(`/api/vehicles/${id}/`);
    return data.vehicle;
  },
  async create(payload: VehicleCreatePayload): Promise<Vehicle> {
    const { data } = await api.post("/api/vehicles/", payload);
    return data.vehicle;
  },
  async update(id: string, payload: Partial<VehicleCreatePayload>): Promise<Vehicle> {
    const { data } = await api.put(`/api/vehicles/${id}/`, payload);
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

// =============================================================================
// === Sprint 1: Inventory ===
// =============================================================================

export const partsApi = {
  async list(opts?: { search?: string; lowStock?: boolean }): Promise<Part[]> {
    const params: Record<string, string> = {};
    if (opts?.search) params.search = opts.search;
    if (opts?.lowStock) params.low_stock = "true";
    const { data } = await api.get("/api/parts/", { params });
    return data.results;
  },
  async create(payload: { name: string; sku?: string; unit: string; unit_price: number }): Promise<Part> {
    const { data } = await api.post("/api/parts/", payload);
    return data.part;
  },
  async update(id: string, payload: Partial<{ name: string; sku: string; unit: string; unit_price: number }>): Promise<Part> {
    const { data } = await api.put(`/api/parts/${id}/`, payload);
    return data.part;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/api/parts/${id}/`);
  },
};

export const partUsagesApi = {
  async list(serviceRecordId: string): Promise<PartUsage[]> {
    const { data } = await api.get(`/api/service-records/${serviceRecordId}/part-usages/`);
    return data.results;
  },
  // Returns both the created usage AND any soft warnings (e.g.
  // resulting stock going negative) — caller decides how to surface
  // those, this layer doesn't swallow them.
  async create(serviceRecordId: string, payload: { part: string; quantity: number }):
    Promise<{ usage: PartUsage; warnings: string[] }> {
    const { data } = await api.post(`/api/service-records/${serviceRecordId}/part-usages/`, payload);
    return { usage: data.part_usage, warnings: data.warnings ?? [] };
  },
};

export const stockAdjustmentsApi = {
  async list(partId: string): Promise<StockAdjustment[]> {
    const { data } = await api.get(`/api/parts/${partId}/adjustments/`);
    return data.results;
  },
  async create(partId: string, payload: {
    quantity_change: number; reason: "restock" | "correction" | "damage"; notes?: string;
  }): Promise<StockAdjustment> {
    const { data } = await api.post(`/api/parts/${partId}/adjustments/`, payload);
    return data.adjustment;
  },
};
