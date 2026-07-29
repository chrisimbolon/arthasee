// =============================================================================
// === frontend/lib/api/contracts.ts ===
// =============================================================================
import api from "@/lib/api";

export type ContractStatus = "ACTIVE" | "EXPIRED" | "CANCELLED";
export type ContractImportStatus = "PENDING_REVIEW" | "APPLIED" | "REJECTED";

export interface ContractLineItem {
  id:             string;
  contract_vehicle: string;
  source_row_no:  number;
  description:    string;
  volume:         string;
  unit:           string;
  unit_price:     string;
  subtotal:       string;
  status:         "ACTIVE" | "SUPERSEDED";
  superseded_by:  string | null;
  created_at:     string;
}

export interface ContractVehicle {
  id:               string;
  contract:         string;
  vehicle:          string;
  plate_number:     string;
  vehicle_model:    string;
  allocated_budget: string;
  // Only the current ACTIVE menu — matches ContractVehicleSerializer's
  // get_line_items() on the backend, never includes SUPERSEDED history.
  line_items:       ContractLineItem[];
}

// Made's own real, worked example from the 28 Jul meeting (the
// Avanza 849 XXXI-28, tracked across real termin cycles). All
// periods for a Contract are generated together, in full, at
// creation — see Contract.generate_termin_periods() on the backend.
//
// jatuh_tempo is calculated once, at generation, from the Contract's
// own start_date — never manually typed per period. amount_expected
// is genuinely NOT frozen the same way — it live-recalculates every
// time a ContractImport successfully applies (except for any period
// already realized, which is permanently excluded). amount_received
// is a real, separate field from amount_expected, not a boolean —
// actual institutional disbursement can genuinely differ from what
// was expected.
export interface TerminPeriod {
  id:              string;
  contract:        string;
  sequence:        number;
  jatuh_tempo:     string;
  amount_expected: string;
  amount_received: string | null;
  received_at:     string | null;
  is_realized:     boolean;
  is_overdue:      boolean;
  created_at:      string;
}

export interface Contract {
  id:               string;
  customer:         string;
  customer_name:    string;
  title:            string;
  fiscal_year:      number;
  termin_count:     3 | 4;
  // The anchor point termin due dates get calculated from —
  // defaults to today on the backend if omitted at creation, but
  // deliberately editable there: the day a contract gets entered
  // into Arthasee isn't always its real authorized start.
  start_date:       string;
  status:           ContractStatus;
  contract_vehicles?: ContractVehicle[];
  termin_periods?:  TerminPeriod[];
  created_by:       string | null;
  created_by_name:  string | null;
  created_at:       string;
  updated_at:       string;
}

// ── The diff shape, mirroring apps.contracts.parsing.diff_against_contract() ──

export interface DiffAddedVehicle {
  fleet_code:       string;
  vehicle_model:    string;
  allocated_budget: string;
  existing_vehicle_id?:    string | null;
  existing_vehicle_model?: string | null;
  line_items: Array<{
    row_no: number; description: string; volume: string;
    unit: string; unit_price: string; subtotal: string;
  }>;
  manufacture_year?: number;
  vehicle_type?:     string;
}

export interface DiffAddedItem {
  fleet_code: string; row_no: number; description: string;
  volume: string; unit: string; unit_price: string; subtotal: string;
}

export interface DiffChangedItem {
  fleet_code: string; row_no: number;
  old: { description: string; volume: string; unit: string; unit_price: string; subtotal: string };
  new: { description: string; volume: string; unit: string; unit_price: string; subtotal: string };
}

export interface DiffRemovedItem {
  fleet_code: string; row_no: number; description: string;
}

export interface ParsedDiff {
  added_vehicles: DiffAddedVehicle[];
  added_items:    DiffAddedItem[];
  changed_items:  DiffChangedItem[];
  removed_items:  DiffRemovedItem[];
  unchanged_count: number;
}

export interface ContractImport {
  id:               string;
  contract:         string;
  original_file:    string;
  status:           ContractImportStatus;
  parsed_diff:      ParsedDiff;
  document_total:   string | null;
  computed_total:   string | null;
  totals_match:     boolean | null;
  parse_error:      string;
  uploaded_by:      string | null;
  uploaded_by_name: string | null;
  uploaded_at:      string;
  applied_by:       string | null;
  applied_by_name:  string | null;
  applied_at:       string | null;
}

export const contractsApi = {
  async list(): Promise<Contract[]> {
    const { data } = await api.get("/api/contracts/");
    return data.results;
  },
  async get(id: string): Promise<Contract> {
    const { data } = await api.get(`/api/contracts/${id}/`);
    return data.contract;
  },
  async create(payload: {
    customer: string; title: string; fiscal_year: number; termin_count: 3 | 4; start_date?: string;
  }): Promise<Contract> {
    const { data } = await api.post("/api/contracts/", payload);
    return data.contract;
  },
  // Retroactive backfill for any Contract that predates the termin
  // feature (created before generate_termin_periods() existed, or
  // created directly some other way) — every Contract created
  // through the normal create() call above already gets its periods
  // automatically; this only exists for the ones that don't.
  async generateTermin(id: string): Promise<Contract> {
    const { data } = await api.post(`/api/contracts/${id}/generate-termin/`);
    return data.contract;
  },
};

export const contractImportsApi = {
  async list(contractId: string): Promise<ContractImport[]> {
    const { data } = await api.get(`/api/contracts/${contractId}/imports/`);
    return data.results;
  },
  async upload(contractId: string, file: File): Promise<{ contractImport: ContractImport; success: boolean; message?: string }> {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const { data } = await api.post(`/api/contracts/${contractId}/imports/`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return { success: true, contractImport: data.contract_import };
    } catch (err) {
      const response = (err as { response?: { data?: { message?: string; contract_import?: ContractImport } } })?.response;
      if (response?.data?.contract_import) {
        return { success: false, contractImport: response.data.contract_import, message: response.data.message };
      }
      throw err;
    }
  },
  async get(id: string): Promise<ContractImport> {
    const { data } = await api.get(`/api/contract-imports/${id}/`);
    return data.contract_import;
  },
  async apply(id: string, confirmedDiff: ParsedDiff): Promise<{ success: boolean; message?: string; contractImport?: ContractImport }> {
    try {
      const { data } = await api.post(`/api/contract-imports/${id}/apply/`, { confirmed_diff: confirmedDiff });
      return { success: true, contractImport: data.contract_import };
    } catch (err) {
      const response = (err as { response?: { data?: { message?: string } } })?.response;
      return { success: false, message: response?.data?.message ?? "Gagal menerapkan perubahan." };
    }
  },
  async reject(id: string): Promise<ContractImport> {
    const { data } = await api.post(`/api/contract-imports/${id}/reject/`);
    return data.contract_import;
  },
};

export const terminPeriodsApi = {
  // receivedDate optional — the backend defaults it to today, same
  // pattern as WorkOrderCloseView's own optional service_date.
  async realize(id: string, amountReceived: string, receivedDate?: string): Promise<TerminPeriod> {
    const { data } = await api.post(`/api/termin-periods/${id}/realize/`, {
      amount_received: amountReceived,
      ...(receivedDate ? { received_at: receivedDate } : {}),
    });
    return data.termin_period;
  },
};
