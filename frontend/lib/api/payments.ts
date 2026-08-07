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
