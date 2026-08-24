// ===========================================================
// === frontend/lib/api/service.ts ===
// ===========================================================
import api from "@/lib/api";

export type CustomerType = "INDIVIDUAL" | "INSTITUTIONAL";

export interface Customer {
  id:            string;
  name:          string;
  phone:         string;
  stnk_name:     string;
  // Distinguishes institutional/tender clients (government bodies,
  // police, large companies) from regular walk-in customers — added
  // once apps.contracts needed a real way to filter which customers
  // are eligible to have a Contract attached, rather than showing
  // every customer in that picker, undifferentiated, forever.
  customer_type: CustomerType;
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
  // Set once an Invoice exists for this record (OneToOneField on the
  // backend) — null until then. Drives whether the UI shows "Buat
  // Invoice" or "Lihat Invoice" per record.
  invoice_id:        string | null;
  // The actual, final invoice amount — null until an Invoice exists,
  // "0" if one exists but has no line items yet. Distinct from
  // original_estimate_total (what was quoted before work started) —
  // this is what was actually charged. Drives the cost shown per
  // entry on the Vehicle Timeline.
  invoice_total:     string | null;
  // Set when this record traces back through a WorkOrder to an
  // approved Estimate — null for plain records or ones that never
  // went through the estimate flow. Purely a reference point at
  // invoice-creation time, never enforced against the real invoice.
  original_estimate_total: string | null;
  // Set when this record was produced by WorkOrder.close() — null
  // for any record predating WorkOrder, or created some other way in
  // the future. Drives the "WO #N" link on the Riwayat Servis card,
  // the fix for Sansan's "two disconnected sections" review: a
  // completed WorkOrder now renders as one entry (this card, with a
  // link back to its own checklist/material breakdown) rather than
  // also appearing as its own separate card elsewhere on the page.
  // Deliberately never present for a CANCELLED WorkOrder — cancel()
  // never creates a ServiceRecord in the first place, so there is
  // nothing here to link from on that side; cancelled orders stay visible only in WorkOrdersSection's own history.
  
  work_order_id:     string | null;
  work_order_number: string | null;
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

// ── Sprint 7, Task 7.1: Part taxonomy ──────────────────────────
// Every value here matches the backend's models.TextChoices exactly
// (apps/inventory/models.py) — the empty string "" is a real,
// distinct state (blank/unset), not a placeholder to work around;
// it's the honest migration-backfill state for every part that
// existed before this taxonomy shipped (Busi, Filter).
export type ItemType = "SPARE_PART" | "FLUID";
export type VehicleBrand = "TOYOTA" | "HONDA" | "DAIHATSU" | "SUZUKI" | "MITSUBISHI" | "";
export type FluidBrand = "SHELL" | "CASTROL" | "REPSOL" | "FASTRON" | "PERTAMINA_MEDITRAN" | "";
export type ViscosityGrade = "10W-40" | "5W-30" | "SAE_90" | "SAE_140" | "";
export type ReorderCadence = "HARIAN" | "MINGGUAN" | "BULANAN" | "TIGA_BULANAN" | "";

export interface Part {
  id:            string;
  name:          string;
  sku:           string;
  unit:          string;
  current_stock: string;
  unit_price:    string;
  // Real ledger-consistency fix, 24 Aug 2026 — "Last Cost," updated
  // automatically every time this part is actually received via a
  // real GRN (see the backend's own GoodsReceivedNoteLineItem.save()
  // docstring). Read-only — system-derived only, never hand-typed;
  // see PartSerializer's own read_only_fields for why. "0" is a real,
  // honest state meaning "this part has never actually gone through
  // a real GRN yet," not a guessed/zero cost — WorkOrderMaterialLine
  // itself falls back to unit_price for exactly this case.
  cost_price:    string;
  // Real per-part reorder threshold — replaces what used to be a
  // single hardcoded global "<=5" rule shared by every part. "0"
  // means no threshold configured; a part completely out of stock
  // still surfaces regardless of this value — UNLESS reorder_cadence
  // is "HARIAN" (see below), where zero stock is the deliberately
  // correct state, not a gap. See the backend's own Part.minimum_stock
  // docstring for the full reasoning.
  minimum_stock: string;
  // Sprint 7, Task 7.1 — see the type comment above each type alias.
  item_type:       ItemType;
  vehicle_brand:   VehicleBrand;
  fluid_brand:     FluidBrand;
  viscosity_grade: ViscosityGrade;
  reorder_cadence: ReorderCadence;
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

export interface StockSummary {
  total_parts:              number;
  total_stock_value:        string;
  // Deliberately a string, not a boolean flag — states plainly which
  // valuation basis this figure uses. As of 24 Aug 2026, this is
  // cost_price (matching Account 1301's own real GL basis on both
  // sides), with an honest caveat about parts still at cost_price=0
  // falling back to unit_price until their first real GRN.
  total_stock_value_basis:  string;
  out_of_stock_count:       number;
  low_stock_count:          number;
}

export interface StockMovement {
  type:               "usage" | "adjustment";
  date:                string;
  quantity_change:     string;
  reason:              string;
  service_record_id:   string | null;
  notes:               string;
  created_by_name?:    string | null;
}

export interface ApiErrorShape {
  success: false;
  errors?:  Record<string, string[]>;
  message?: string;
}

// ── Sprint 7, Task 7.3: Stock Opname ───────────────────────────
// Mirrors apps/inventory/serializers.py's StockOpnameSessionSerializer
// / StockOpnameLineItemSerializer exactly. Note: unit_price is
// deliberately NOT part of this shape (the backend serializer never
// exposes it here) — the frontend cross-references Part.unit_price
// from the already-fetched parts list to compute Rupiah preview
// totals client-side, rather than duplicating pricing data onto
// every line item response.

export interface StockOpnameLineItem {
  id:                    string;
  part:                  string;
  part_name:             string;
  unit:                  string;
  system_stock_at_time:  string;
  physical_count:        string | null;
  variance:              string | null;
}

export interface StockOpnameSession {
  id:               string;
  number:           string;
  status:           "DRAFT" | "COMPLETED";
  completed_at:     string | null;
  created_by:       string | null;
  created_by_name:  string | null;
  line_items:       StockOpnameLineItem[];
  created_at:       string;
  updated_at:       string;
}

export const customersApi = {
  async list(opts?: { search?: string; customerType?: CustomerType }): Promise<Customer[]> {
    const params: Record<string, string> = {};
    if (opts?.search) params.search = opts.search;
    if (opts?.customerType) params.customer_type = opts.customerType;
    const { data } = await api.get("/api/customers/", { params });
    return data.results;
  },
  async create(payload: { name: string; phone?: string; stnk_name?: string; customer_type?: CustomerType }): Promise<Customer> {
    const { data } = await api.post("/api/customers/", payload);
    return data.customer;
  },
  async update(id: string, payload: Partial<{ name: string; phone: string; stnk_name: string; customer_type: CustomerType }>): Promise<Customer> {
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

// Sprint 7, Task 7.1 — shared payload shape for both create and
// update, all taxonomy fields optional (matches the backend's own
// blank=True fields — a part can be saved mid-categorization).
// cost_price is deliberately NOT part of this payload — read-only,
// system-derived, never sent by the client.
export interface PartTaxonomyPayload {
  item_type?:       ItemType;
  vehicle_brand?:   VehicleBrand;
  fluid_brand?:     FluidBrand;
  viscosity_grade?: ViscosityGrade;
  reorder_cadence?: ReorderCadence;
}

export const partsApi = {
  async list(opts?: { search?: string; lowStock?: boolean }): Promise<Part[]> {
    const params: Record<string, string> = {};
    if (opts?.search) params.search = opts.search;
    if (opts?.lowStock) params.low_stock = "true";
    const { data } = await api.get("/api/parts/", { params });
    return data.results;
  },
  async create(payload: { name: string; sku?: string; unit: string; unit_price: number; minimum_stock?: number } & PartTaxonomyPayload): Promise<Part> {
    const { data } = await api.post("/api/parts/", payload);
    return data.part;
  },
  async update(id: string, payload: Partial<{ name: string; sku: string; unit: string; unit_price: number; minimum_stock: number }> & PartTaxonomyPayload): Promise<Part> {
    const { data } = await api.put(`/api/parts/${id}/`, payload);
    return data.part;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/api/parts/${id}/`);
  },
  async stockSummary(): Promise<StockSummary> {
    const { data } = await api.get("/api/parts/stock-summary/");
    return data;
  },
  async movements(partId: string): Promise<StockMovement[]> {
    const { data } = await api.get(`/api/parts/${partId}/movements/`);
    return data.movements;
  },
};

export const partUsagesApi = {
  async list(serviceRecordId: string): Promise<PartUsage[]> {
    const { data } = await api.get(`/api/service-records/${serviceRecordId}/part-usages/`);
    return data.results;
  },
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

// Sprint 7, Task 7.3 — deliberately flat routes ("stock-opname/",
// not "inventory/stock-opname/") — confirmed against the real
// backend apps/inventory/urls.py, matching every other route in
// that file exactly.
export const stockOpnameApi = {
  async list(): Promise<StockOpnameSession[]> {
    const { data } = await api.get("/api/stock-opname/");
    return data.results;
  },
  async get(id: string): Promise<StockOpnameSession> {
    const { data } = await api.get(`/api/stock-opname/${id}/`);
    return data.session;
  },
  async start(partIds: string[]): Promise<StockOpnameSession> {
    const { data } = await api.post("/api/stock-opname/", { part_ids: partIds });
    return data.session;
  },
  async recordCounts(
    id: string, counts: { part_id: string; physical_count: number }[],
  ): Promise<StockOpnameSession> {
    const { data } = await api.patch(`/api/stock-opname/${id}/`, { counts });
    return data.session;
  },
  async complete(id: string): Promise<StockOpnameSession> {
    const { data } = await api.post(`/api/stock-opname/${id}/complete/`);
    return data.session;
  },
};
