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

export interface Contract {
  id:               string;
  customer:         string;
  customer_name:    string;
  title:            string;
  fiscal_year:      number;
  termin_count:     3 | 4;
  status:           ContractStatus;
  contract_vehicles?: ContractVehicle[];
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
  line_items: Array<{
    row_no: number; description: string; volume: string;
    unit: string; unit_price: string; subtotal: string;
  }>;
  // Populated client-side during review, NOT present in the raw
  // machine parse — the source document never provides this, but
  // Vehicle.manufacture_year is required on the backend, so the
  // reviewer must fill it in before this entry can be applied.
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
  // null until both totals are known — see ContractImport.totals_match
  // on the backend for the exact comparison (within Rp 1 tolerance).
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
    customer: string; title: string; fiscal_year: number; termin_count: 3 | 4;
  }): Promise<Contract> {
    const { data } = await api.post("/api/contracts/", payload);
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
        // A parse failure still returns the ContractImport row (with
        // parse_error populated) — surface both rather than throwing
        // the detail away.
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
