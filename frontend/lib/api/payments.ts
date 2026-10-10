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
  // 9 Oct 2026 — PPh 23 + PPh Final UMKM patch. Optional, only ever
  // sent when the customer is INSTITUTIONAL and actually withheld
  // PPh 23 at this payment (Decision #1) — Payment.record() itself
  // validates it (<= amount, >= 0), this is just the wire shape.
  pph23_withheld_amount?: number | string;
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

// ── 1 Sep 2026 — Made's own confirmed real request, arrived at
// while designing the Kas Harian dashboard: real workshops move
// physical cash to the bank regularly (theft-risk management), and
// this system had no way to record that real fact. Cash (1001) <->
// Bank (1101) only in v1 — see InternalCashMutation's own backend
// docstring for why. ────────────────────────────────────────────

export type CashBankAccountCode = "1001" | "1101";

export interface InternalCashMutation {
  id:                 string;
  number:             string;
  sequence_number:    number;
  from_account_code:  CashBankAccountCode;
  to_account_code:    CashBankAccountCode;
  amount:             string;
  transaction_date:   string;
  // Cosmetic only — e.g. "Transfer BCA". No real per-bank ledger
  // account exists yet; see Roadmap Open Decisions and
  // InternalCashMutation's own backend docstring.
  note:               string;
  created_by:         string | null;
  created_by_name:    string | null;
  created_at:         string;
}

export interface RecordInternalCashMutationPayload {
  from_account_code: CashBankAccountCode;
  to_account_code:   CashBankAccountCode;
  amount:            number | string;
  transaction_date?: string;
  note?:             string;
}

export interface RecordInternalCashMutationResult {
  success: boolean;
  message?: string;
  internal_cash_mutation?: InternalCashMutation;
}

export const internalCashMutationsApi = {
  async list(): Promise<InternalCashMutation[]> {
    const { data } = await api.get("/api/internal-cash-mutations/");
    return data.internal_cash_mutations;
  },
  // Real WRITE action — same discipline as operatingExpensesApi.record()
  // above: a failure here must surface its real message (e.g. "Akun
  // asal dan akun tujuan tidak boleh sama") to the user, not silently
  // collapse to a generic message.
  async record(payload: RecordInternalCashMutationPayload): Promise<RecordInternalCashMutationResult> {
    try {
      const { data } = await api.post("/api/internal-cash-mutations/", payload);
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal mencatat mutasi kas." };
    }
  },
};

// ── 9 Oct 2026 — PPh 23 (self-remit gross-up) + PPh Final UMKM
// (PP 55/2022) monthly tax remittances. Scoped and designed with
// Chris, grounded in Pak Holan's real, confirmed answers — see the
// "PPh23 Questions for Pak Holan" doc. Deliberately NOT automatic:
// the owner/accountant sees a SUGGESTED amount (suggested() below)
// and explicitly confirms before anything is recorded. ────────────

export type TaxType = "pph23_self_remit" | "pph_umkm_final";
export type TaxRemittanceMethod = "cash" | "bank";

export interface TaxRemittance {
  id:                string;
  number:            string;
  sequence_number:   number;
  tax_type:          TaxType;
  tax_type_display:  string;
  period_year:       number;
  period_month:      number;
  amount:            string;
  method:            TaxRemittanceMethod;
  paid_at:           string;
  reference:         string;
  notes:             string;
  created_by:        string | null;
  created_by_name:   string | null;
  created_at:        string;
}

export interface RecordTaxRemittancePayload {
  tax_type:      TaxType;
  period_year:   number;
  period_month:  number;
  amount:        number | string;
  method?:       TaxRemittanceMethod;
  paid_at?:      string;
  reference?:    string;
  notes?:        string;
}

export interface RecordTaxRemittanceResult {
  success: boolean;
  message?: string;
  tax_remittance?: TaxRemittance;
}

export const taxRemittancesApi = {
  async list(): Promise<TaxRemittance[]> {
    const { data } = await api.get("/api/tax-remittances/");
    return data.tax_remittances;
  },
  // Real WRITE action — same discipline as operatingExpensesApi.record()/
  // internalCashMutationsApi.record() above: a failure must surface its
  // real message (e.g. a duplicate for the same tax_type/period, or a
  // closed period) to the user, not a generic fallback.
  async record(payload: RecordTaxRemittancePayload): Promise<RecordTaxRemittanceResult> {
    try {
      const { data } = await api.post("/api/tax-remittances/", payload);
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal mencatat setoran pajak." };
    }
  },
  // GET /api/tax-remittances/suggested/ — read-only, never itself
  // creates a TaxRemittance row (Decision #2). Returns a plain
  // decimal string, same shape every other money field in this file
  // already uses.
  async suggested(taxType: TaxType, periodYear: number, periodMonth: number): Promise<string> {
    const { data } = await api.get("/api/tax-remittances/suggested/", {
      params: { tax_type: taxType, period_year: periodYear, period_month: periodMonth },
    });
    return data.suggested_amount;
  },
};
