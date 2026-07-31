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
  vehicle_id:             string;
  number:                 string;
  sequence_number:        number;
  year:                   number;
  customer_name_snapshot: string;
  license_plate_snapshot: string;
  // Made's own explicit reason, confirmed 31 Jul: a specific
  // mechanic must be identifiable on every invoice, even for
  // routine work, so he can go back and question that person
  // directly if the same car has an issue again. Frozen at
  // invoice-creation time, same discipline as
  // customer_name_snapshot/license_plate_snapshot — the Mechanic
  // roster can change later without altering what an already-issued
  // invoice says. The backend hard-blocks invoice creation entirely
  // if the originating WorkOrder has no mechanic assigned, so this
  // is never actually blank on a real invoice, though the type
  // still allows it defensively.
  mechanic_name_snapshot: string;
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
  // Made's own ask, 31 Jul: a real, downloadable PDF for LUNAS
  // invoices so SA/cashier can forward it themselves via their own
  // WhatsApp — same manual-download pattern already built for
  // Estimate quotations. Gated to PAID only, backend-side (confirmed
  // with Chris) — this call will fail with a real 409 message if
  // attempted on any other status; the caller should only expose the
  // button when invoice.status === "PAID" in the first place.
  // Returns a real Blob, not JSON — same reasoning as
  // estimatesApi.downloadQuotationPdf: this API needs a bearer token
  // in a header, which a plain <a href> link can't attach.
  async downloadPdf(id: string): Promise<Blob> {
    const { data } = await api.get(`/api/invoices/${id}/receipt.pdf`, { responseType: "blob" });
    return data;
  },
};
