// =============================================================================
// === frontend/lib/api/purchasing.ts ===
// =============================================================================
import api from "@/lib/api";

export interface Supplier {
  id: string;
  name: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  notes: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface GoodsReceivedNoteLineItem {
  id: string;
  part: string;
  part_name: string;
  quantity: string;
  unit_cost: string;
  subtotal: string;
  created_at: string;
}

export interface GoodsReceivedNote {
  id: string;
  number: string;
  sequence_number: number;
  supplier: string;
  supplier_name: string;
  // null until a SupplierInvoice links to this GRN — THE field the
  // whole Retur Pembelian Case-A guard hinges on. See
  // PurchaseReturn.create_return()'s own real backend docstring.
  supplier_invoice: string | null;
  received_at: string;
  reference: string;
  notes: string;
  received_by: string | null;
  received_by_name: string | null;
  line_items: GoodsReceivedNoteLineItem[];
  total_cost: string;
  created_at: string;
}

export interface SupplierInvoice {
  id: string;
  number: string;
  sequence_number: number;
  supplier: string;
  supplier_name: string;
  supplier_invoice_number: string;
  goods_received_notes: string[];
  amount: string;
  invoice_date: string;
  due_date: string | null;
  status: "UNPAID" | "PAID";
  notes: string;
  created_by: string | null;
  created_at: string;
}

export interface PurchaseReturnLineItem {
  id: string;
  goods_received_note_line_item: string;
  part_name: string;
  quantity: string;
  unit_cost: string;
  subtotal: string;
  created_at: string;
}

export interface PurchaseReturn {
  id: string;
  number: string;
  sequence_number: number;
  goods_received_note: string;
  goods_received_note_number: string;
  return_date: string;
  reason: string;
  line_items: PurchaseReturnLineItem[];
  total_value: string;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
}

export const suppliersApi = {
  async list(): Promise<Supplier[]> {
    const { data } = await api.get("/api/suppliers/");
    return data.suppliers;
  },
  async get(id: string): Promise<Supplier> {
    const { data } = await api.get(`/api/suppliers/${id}/`);
    return data.supplier;
  },
  async create(payload: {
    name: string; contact_person?: string; phone?: string;
    email?: string; address?: string; notes?: string;
  }): Promise<Supplier> {
    const { data } = await api.post("/api/suppliers/", payload);
    return data.supplier;
  },
};

export const goodsReceivedNotesApi = {
  async list(): Promise<GoodsReceivedNote[]> {
    const { data } = await api.get("/api/goods-received-notes/");
    return data.goods_received_notes;
  },
  async get(id: string): Promise<GoodsReceivedNote> {
    const { data } = await api.get(`/api/goods-received-notes/${id}/`);
    return data.goods_received_note;
  },
  async create(payload: {
    supplier: string;
    received_at?: string;
    reference?: string;
    notes?: string;
    lines: { part: string; quantity: number; unit_cost: number }[];
  }): Promise<GoodsReceivedNote> {
    const { data } = await api.post("/api/goods-received-notes/", payload);
    return data.goods_received_note;
  },
};

export const supplierInvoicesApi = {
  async list(): Promise<SupplierInvoice[]> {
    const { data } = await api.get("/api/supplier-invoices/");
    return data.supplier_invoices;
  },
  async get(id: string): Promise<SupplierInvoice> {
    const { data } = await api.get(`/api/supplier-invoices/${id}/`);
    return data.supplier_invoice;
  },
  async create(payload: {
    supplier: string;
    amount: number;
    invoice_date: string;
    due_date?: string;
    supplier_invoice_number?: string;
    notes?: string;
    goods_received_note_ids?: string[];
  }): Promise<SupplierInvoice> {
    const { data } = await api.post("/api/supplier-invoices/", payload);
    return data.supplier_invoice;
  },
  // Response shape beyond {success:true} isn't confirmed in this
  // conversation — deliberately not typed/parsed here. Callers
  // should re-fetch via get() afterward for the real, confirmed
  // SupplierInvoice shape rather than trust an unconfirmed payload.
  async pay(id: string, method: "cash" | "bank_transfer"): Promise<void> {
    await api.post(`/api/supplier-invoices/${id}/pay/`, { method });
  },
};

export const purchaseReturnsApi = {
  async list(): Promise<PurchaseReturn[]> {
    const { data } = await api.get("/api/purchase-returns/");
    return data.purchase_returns;
  },
  async get(id: string): Promise<PurchaseReturn> {
    const { data } = await api.get(`/api/purchase-returns/${id}/`);
    return data.purchase_return;
  },
  async create(payload: {
    goods_received_note: string;
    return_date?: string;
    reason: string;
    lines: { grn_line_item: string; quantity: number }[];
  }): Promise<PurchaseReturn> {
    const { data } = await api.post("/api/purchase-returns/", payload);
    return data.purchase_return;
  },
};
