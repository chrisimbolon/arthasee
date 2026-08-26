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

export interface PurchaseOrderLineItem {
  id: string;
  part: string;
  part_name: string;
  // The supplier's own code for this part, if one's on file for
  // THIS PO's specific supplier — null when no code has been
  // entered yet. See SupplierPartCode for the real (Part, Supplier)
  // bridge this is looked up from.
  supplier_sku: string | null;
  quantity_ordered: string;
  unit_cost: string;
  // Both computed live on the backend from real GRN lines tracing
  // back to this one — never stored, never trust a second source of
  // truth.
  quantity_received: string;
  quantity_outstanding: string;
  created_at: string;
}

export interface PurchaseOrder {
  id: string;
  number: string;
  sequence_number: number;
  supplier: string;
  supplier_name: string;
  status: "DRAFT" | "ORDERED" | "PARTIALLY_RECEIVED" | "FULLY_RECEIVED" | "CANCELLED";
  status_display: string;
  order_date: string;
  expected_date: string | null;
  notes: string;
  line_items: PurchaseOrderLineItem[];
  total_ordered_value: string;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoodsReceivedNoteLineItem {
  id: string;
  part: string;
  part_name: string;
  // Same lookup as PurchaseOrderLineItem's own supplier_sku, resolved
  // against THIS GRN's own supplier.
  supplier_sku: string | null;
  // Real traceability — every GRN line must trace back to an
  // authorized PO line now.
  purchase_order_line_item: string;
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
  purchase_order: string;
  purchase_order_number: string;
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
  // Made's own confirmed request, 25 Aug meeting — a real file so
  // the physical supplier invoice isn't lost. null until uploaded
  // via supplierInvoicesApi.uploadAttachment() — an invoice can be
  // recorded before the file is actually ready, same as
  // apps.letters's own IncomingLetter pattern this mirrors.
  attachment: string | null;
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
  // System-determined at creation, never user-editable — "before
  // any supplier invoice existed" vs "after an unpaid invoice
  // existed". Real audit visibility: which liability account this
  // return actually reduced.
  return_classification: "BEFORE_INVOICE" | "AFTER_INVOICE_UNPAID";
  classification_display: string;
  line_items: PurchaseReturnLineItem[];
  total_value: string;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface SupplierReliabilityRow {
  supplier_id: string;
  supplier_name: string;
  total_pos_judged: number;
  on_time_pos: number;
  on_time_rate: string | number | null;
  total_received_value: string | number;
  total_returned_value: string | number;
  return_rate: string | number;
}

export interface SupplierReliabilityResponse {
  since: string;
  as_of: string;
  suppliers: SupplierReliabilityRow[];
}

// Real (Part, Supplier) bridge — the same real part can have a
// different code per supplier, confirmed by Made directly (and by
// Chris's own visit to Arya Motor) — this shop genuinely buys from
// more than one supplier for the same part.
export interface SupplierPartCode {
  id: string;
  part: string;
  supplier: string;
  supplier_name: string;
  supplier_sku: string;
  created_at: string;
  updated_at: string;
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

export const purchaseOrdersApi = {
  async list(): Promise<PurchaseOrder[]> {
    const { data } = await api.get("/api/purchase-orders/");
    return data.purchase_orders;
  },
  async get(id: string): Promise<PurchaseOrder> {
    const { data } = await api.get(`/api/purchase-orders/${id}/`);
    return data.purchase_order;
  },
  async create(payload: {
    supplier: string;
    order_date: string;
    expected_date?: string;
    notes?: string;
    status?: "DRAFT" | "ORDERED";
    lines: { part: string; quantity_ordered: number; unit_cost: number }[];
  }): Promise<PurchaseOrder> {
    const { data } = await api.post("/api/purchase-orders/", payload);
    return data.purchase_order;
  },
  async cancel(id: string): Promise<PurchaseOrder> {
    const { data } = await api.post(`/api/purchase-orders/${id}/cancel/`);
    return data.purchase_order;
  },
  // The real, deliberate resolution path for the over-receiving hard
  // block on GRN creation — raises a PO line's own ceiling, on
  // purpose, before a GRN is re-attempted.
  async amendLineItem(lineItemId: string, quantityOrdered: number): Promise<PurchaseOrderLineItem> {
    const { data } = await api.post(`/api/purchase-order-line-items/${lineItemId}/amend/`, {
      quantity_ordered: quantityOrdered,
    });
    return data.purchase_order_line_item;
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
  // Return shape: { grn, warnings } — matches partUsagesApi.create()'s
  // own already-established { usage, warnings } shape exactly.
  // warnings is a real, non-blocking price-variance signal from
  // GoodsReceivedNote.receive() — see that method's own backend
  // docstring. The GRN is ALREADY saved by the time this resolves;
  // warnings are informational, not a rejection.
  async create(payload: {
    purchase_order: string;
    received_at?: string;
    reference?: string;
    notes?: string;
    lines: { purchase_order_line_item: string; quantity: number; unit_cost: number }[];
  }): Promise<{ grn: GoodsReceivedNote; warnings: string[] }> {
    const { data } = await api.post("/api/goods-received-notes/", payload);
    return { grn: data.goods_received_note, warnings: data.warnings ?? [] };
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
  // Made's own confirmed request, 25 Aug meeting — real file upload,
  // mirroring apps.letters's own IncomingLetter pattern exactly.
  // Multipart, not JSON — axios sets the correct Content-Type
  // automatically when the body is a real FormData instance.
  async uploadAttachment(id: string, file: File): Promise<SupplierInvoice> {
    const formData = new FormData();
    formData.append("attachment", file);
    const { data } = await api.post(`/api/supplier-invoices/${id}/attachment/`, formData);
    return data.supplier_invoice;
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

export const purchasingReportsApi = {
  async supplierReliability(since?: string, asOf?: string): Promise<SupplierReliabilityResponse | null> {
    try {
      const { data } = await api.get("/api/supplier-reliability/", { params: { since, as_of: asOf } });
      return data as SupplierReliabilityResponse;
    } catch {
      return null;
    }
  },
};

// Deliberately mounted under /api/parts/<part_id>/supplier-codes/,
// not a "purchasing" URL prefix — see the backend view's own
// docstring (SupplierPartCodeListCreateView, apps.purchasing.views,
// mounted via apps.inventory.urls) for why: "everything about one
// specific part" stays under one consistent URL namespace even
// though the model's real domain home is apps.purchasing.
export const supplierPartCodesApi = {
  async list(partId: string): Promise<SupplierPartCode[]> {
    const { data } = await api.get(`/api/parts/${partId}/supplier-codes/`);
    return data.supplier_codes;
  },
  async set(partId: string, payload: { supplier: string; supplier_sku: string }): Promise<SupplierPartCode> {
    const { data } = await api.post(`/api/parts/${partId}/supplier-codes/`, payload);
    return data.supplier_code;
  },
};

// ── Made's own confirmed exception, 25 Aug meeting — HARIAN/
// MINGGUAN parts skip PurchaseOrder -> GoodsReceivedNote entirely:
// a real, immediate, over-the-counter spot purchase, paid on the
// spot. ──────────────────────────────────────────────────────────

export type QuickPurchasePaymentMethod = "cash" | "bank";

export interface QuickPurchaseLineItem {
  id: string;
  part: string;
  part_name: string;
  quantity: string;
  unit_cost: string;
  subtotal: string;
  created_at: string;
}

export interface QuickPurchase {
  id: string;
  number: string;
  sequence_number: number;
  supplier: string;
  supplier_name: string;
  payment_method: QuickPurchasePaymentMethod;
  payment_method_display: string;
  purchased_at: string;
  reference: string;
  notes: string;
  line_items: QuickPurchaseLineItem[];
  total_cost: string;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
}

export const quickPurchasesApi = {
  async list(): Promise<QuickPurchase[]> {
    const { data } = await api.get("/api/quick-purchases/");
    return data.quick_purchases;
  },
  async get(id: string): Promise<QuickPurchase> {
    const { data } = await api.get(`/api/quick-purchases/${id}/`);
    return data.quick_purchase;
  },
  async create(payload: {
    supplier: string;
    payment_method?: QuickPurchasePaymentMethod;
    purchased_at?: string;
    reference?: string;
    notes?: string;
    lines: { part: string; quantity: number; unit_cost: number }[];
  }): Promise<QuickPurchase> {
    const { data } = await api.post("/api/quick-purchases/", payload);
    return data.quick_purchase;
  },
};
