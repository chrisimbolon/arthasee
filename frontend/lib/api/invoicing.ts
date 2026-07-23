// =============================================================================
// === frontend/lib/api/invoicing.ts ===
// =============================================================================
import api from "@/lib/api";

export interface InvoiceLineItem {
  id:          string;
  kind:        "part" | "labor";
  description: string;
  quantity:    string;
  unit_price:  string;
  part:        string | null;
  part_name:   string | null;
  subtotal:    string;
}

export type InvoiceStatus = "DRAFT" | "ISSUED" | "PAID" | "CANCELLED";

export interface Invoice {
  id:                     string;
  service_record:         string;
  number:                 string;
  sequence_number:        number;
  year:                   number;
  customer_name_snapshot: string;
  license_plate_snapshot: string;
  status:                 InvoiceStatus;
  deposit_amount:         string;
  line_items:             InvoiceLineItem[];
  subtotal:               string;
  total:                  string;
  balance_due:            string;
  created_by:             string | null;
  created_by_name:        string | null;
  created_at:             string;
}

export interface LaborLinePayload {
  description: string;
  quantity:    number;
  unit_price:  number;
}

export const invoicesApi = {
  async create(serviceRecordId: string, laborLines: LaborLinePayload[]): Promise<Invoice> {
    const { data } = await api.post(`/api/service-records/${serviceRecordId}/invoice/`, {
      labor_lines: laborLines,
    });
    return data.invoice;
  },
  async get(id: string): Promise<Invoice> {
    const { data } = await api.get(`/api/invoices/${id}/`);
    return data.invoice;
  },
  async updateStatus(id: string, status: InvoiceStatus): Promise<Invoice> {
    const { data } = await api.patch(`/api/invoices/${id}/status/`, { status });
    return data.invoice;
  },
};
