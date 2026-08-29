// =============================================================================
// === frontend/lib/api/payments.ts ===
// =============================================================================
import api from "@/lib/api";

// Mirrors backend/apps/payments/models.py's own METHOD_CHOICES
// exactly — keep these in sync if the backend list ever changes.
export type PaymentMethod = "cash" | "bank_transfer" | "qris" | "card" | "other";

export interface Payment {
  id:                string;
  invoice:           string;
  amount:            string;
  method:            PaymentMethod;
  received_at:       string;
  reference:         string;
  notes:             string;
  received_by:       string | null;
  received_by_name:  string | null;
  created_at:        string;
}

export interface RecordPaymentPayload {
  amount:      number | string;
  method?:     PaymentMethod;
  received_at?: string;
  reference?:  string;
  notes?:      string;
}

export const paymentsApi = {
  // GET /api/invoices/<id>/payments/ — full payment history for one
  // invoice, oldest first (matches Payment.Meta.ordering on the
  // backend). Multiple rows per invoice are expected and normal — a
  // deposit followed by a balance payment, not an edge case.
  async list(invoiceId: string): Promise<Payment[]> {
    const { data } = await api.get(`/api/invoices/${invoiceId}/payments/`);
    return data.payments;
  },
  // POST /api/invoices/<id>/payments/ — records one real payment.
  // All the actual business logic (status guard, overpayment guard,
  // auto-transition to PAID once balance_due hits zero) lives
  // server-side in Payment.record() — this call can fail with a
  // real, specific 400 message (wrong invoice status, amount exceeds
  // balance_due) that the caller should surface directly rather than
  // replacing with a generic fallback.
  async record(invoiceId: string, payload: RecordPaymentPayload): Promise<Payment> {
    const { data } = await api.post(`/api/invoices/${invoiceId}/payments/`, payload);
    return data.payment;
  },
};

// ── 27 Aug 2026 — Made's own confirmed real request: a guided
// "Catat Beban Operasional" form, an alternative to the generic
// Manual Adjusting Journal for a recurring operating cost (salary,
// rent, utilities). ─────────────────────────────────────────────

export type OperatingExpenseMethod = "cash" | "bank";

export interface OperatingExpense {
  id:               string;
  number:           string;
  sequence_number:  number;
  account:          string;
  account_code:     string;
  account_name:     string;
  amount:           string;
  method:           OperatingExpenseMethod;
  paid_at:          string;
  // Optional, ONLY meaningful when account_code === "6001" (Gaji
  // Karyawan) — enforced server-side in OperatingExpense.record(),
  // not just a frontend convention. null means "All / Lump Sum," a
  // real, valid choice — not every payout is attributable to one
  // specific mechanic.
  mechanic:         string | null;
  mechanic_name:    string | null;
  reference:        string;
  notes:            string;
  created_by:       string | null;
  created_by_name:  string | null;
  created_at:       string;
}

export interface RecordOperatingExpensePayload {
  account_code: string;
  amount:       number | string;
  method?:      OperatingExpenseMethod;
  paid_at?:     string;
  mechanic?:    string | null;
  reference?:   string;
  notes?:       string;
}

export interface RecordOperatingExpenseResult {
  success: boolean;
  message?: string;
  operating_expense?: OperatingExpense;
}

export const operatingExpensesApi = {
  async list(): Promise<OperatingExpense[]> {
    const { data } = await api.get("/api/operating-expenses/");
    return data.operating_expenses;
  },
  // Real WRITE action — a failure here must surface its real message
  // (e.g. "Akun 6004 ... tidak bisa dicatat di sini") to the user,
  // same discipline as accountingApi.closePeriod()/reopenPeriod().
  async record(payload: RecordOperatingExpensePayload): Promise<RecordOperatingExpenseResult> {
    try {
      const { data } = await api.post("/api/operating-expenses/", payload);
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal mencatat beban operasional." };
    }
  },
};
