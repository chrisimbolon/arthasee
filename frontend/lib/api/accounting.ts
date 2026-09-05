// =============================================================================
// === frontend/lib/api/accounting.ts ===
// =============================================================================
import api from "@/lib/api";

// Every money field is typed string | number, not just number —
// DRF's JSONEncoder handles Decimal specially, and depending on
// COERCE_DECIMAL_TO_STRING (not confirmed against this project's
// real settings.py), these could arrive as either "500000.00" or
// 500000.00. toNumber()/formatRupiah() (defined per-page) are the
// ONLY places that ever need to know which — every component just
// uses those.

export interface TrialBalanceAccount {
  code: string;
  name: string;
  account_type: string;
  normal_balance: "DEBIT" | "CREDIT";
  balance: string | number;
}

export interface TrialBalanceResponse {
  as_of: string;
  accounts: TrialBalanceAccount[];
  total_debit: string | number;
  total_credit: string | number;
  is_balanced: boolean;
}

export interface ReportLine {
  code: string;
  name: string;
  amount: string | number;
}

export interface ProfitLossResponse {
  as_of: string;
  revenue: ReportLine[];
  total_revenue: string | number;
  cogs: ReportLine[];
  since: string;
  total_cogs: string | number;
  gross_profit: string | number;
  gross_profit_note: string;
  expenses: ReportLine[];
  total_expenses: string | number;
  net_income: string | number;
}

// change_pct is null when the prior period's value was exactly zero
// — an honest "can't compute a percentage from zero," not a
// fabricated infinite number. See reports.py's own
// profit_and_loss_comparison() docstring for the full reasoning,
// including how a loss-to-profit swing is handled.
export interface ReportDelta {
  change: string | number;
  change_pct: string | number | null;
}

export interface ProfitLossComparisonResponse {
  current: ProfitLossResponse;
  prior: ProfitLossResponse;
  revenue_delta: ReportDelta;
  gross_profit_delta: ReportDelta;
  net_income_delta: ReportDelta;
}

export interface BalanceSheetLine {
  code: string;
  name: string;
  balance: string | number;
}

export interface BalanceSheetResponse {
  as_of: string;
  assets: BalanceSheetLine[];
  total_assets: string | number;
  liabilities: BalanceSheetLine[];
  total_liabilities: string | number;
  equity: BalanceSheetLine[];
  current_year_earnings: string | number;
  total_equity: string | number;
  total_liabilities_and_equity: string | number;
  is_balanced: boolean;
}

export interface CashConversionCycleResponse {
  since: string;
  as_of: string;
  days_in_period: number;
  avg_inventory: string | number;
  avg_ar: string | number;
  avg_ap: string | number;
  total_cogs: string | number;
  total_revenue: string | number;
  dio: string | number;
  dso: string | number;
  dpo: string | number;
  ccc: string | number;
}

export type AgingBucket = "0-30" | "31-60" | "61-90" | "90+";

export interface AgingInvoiceRow {
  id: string;
  number: string;
  age_days: number;
  bucket: AgingBucket;
  customer_name?: string;
  supplier_name?: string;
  balance_due?: string | number;
  amount?: string | number;
}

export interface AgingReportResponse {
  as_of: string;
  invoices?: AgingInvoiceRow[];
  supplier_invoices?: AgingInvoiceRow[];
  buckets: Record<AgingBucket, string | number>;
  total_outstanding: string | number;
}

export interface DashboardOverdueInvoiceRow {
  id: string;
  number: string;
  customer_name: string;
  balance_due: string | number;
  age_days: number;
  bucket: AgingBucket;
}

export interface DashboardDueSoonInvoiceRow {
  id: string;
  number: string;
  supplier_name: string;
  amount: string | number;
  due_date: string;
}

export interface DashboardFinancialSummaryResponse {
  as_of: string;
  ar_total_outstanding: string | number;
  ar_overdue_total: string | number;
  ar_overdue_count: number;
  ar_overdue_customers: string[];
  ar_overdue_invoices: DashboardOverdueInvoiceRow[];
  ap_total_outstanding: string | number;
  ap_due_soon_total: string | number;
  ap_due_soon_count: number;
  ap_due_soon_invoices: DashboardDueSoonInvoiceRow[];
}

// Task 5.2 — new types for the journal viewer.

export type JournalSource = "DOMAIN_EVENT" | "MANUAL";

export interface JournalLineRow {
  id: string;
  account_code: string;
  account_name: string;
  debit_amount: string | number;
  credit_amount: string | number;
  description: string;
}

export interface JournalEntryRow {
  id: string;
  entry_number: string;
  posting_date: string;
  source: JournalSource;
  event_type: string;
  memo: string;
  status: string;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  lines: JournalLineRow[];
}

export interface FailedPosting {
  id: string;
  event_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  attempts: number;
  last_error: string;
  processed_at: string | null;
  created_at: string;
}

// 28 Aug 2026 — real month-end closing, Made's own confirmed
// requirement via his tax & accounting consultant.

export interface AccountingPeriod {
  id: string;
  year: number;
  month: number;
  start_date: string;
  end_date: string;
  is_closed: boolean;
  is_locked: boolean;
  is_open_for_posting: boolean;
  closed_at: string | null;
  closed_by: string | null;
  closed_by_name: string | null;
  reopened_at: string | null;
  reopened_by: string | null;
  reopened_by_name: string | null;
  created_at: string;
}

export interface ClosePeriodResult {
  success: boolean;
  message?: string;
  period?: AccountingPeriod;
  net_income?: string | number;
  closing_entry?: JournalEntryRow | null;
}

export interface ReopenPeriodResult {
  success: boolean;
  message?: string;
  period?: AccountingPeriod;
}

// Shared between the Reports page (Trial Balance tab) and the Chart
// of Accounts page — one real mapping, not two copies that could
// drift. ACCOUNT_TYPE_ORDER matches the real COA blueprint's own
// section order (Asset -> Liability -> Equity -> Revenue -> COGS ->
// Expense), not alphabetical or insertion order.
export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  ASSET: "Aset", LIABILITY: "Liabilitas", EQUITY: "Ekuitas",
  REVENUE: "Pendapatan", COGS: "HPP", EXPENSE: "Beban",
};

export const ACCOUNT_TYPE_ORDER: string[] = [
  "ASSET", "LIABILITY", "EQUITY", "REVENUE", "COGS", "EXPENSE",
];

// 1 Sep 2026 — Kas Harian. `direction` "mutation" is the real,
// distinct third case (alongside "in"/"out") for an internal
// Cash<->Bank transfer — see reports.py's own daily_cash_activity()
// docstring for why it's never folded into in/out. Only the
// "mutation" rows carry from_account_code/to_account_code; only
// "in"/"out" rows carry account_code/account_name — TypeScript can't
// express that split cleanly without a discriminated union, so both
// sets of fields are optional here and the UI branches on
// `direction` to know which are actually present.
export type DailyCashActivityDirection = "in" | "out" | "mutation";

export interface DailyCashActivityRow {
  journal_entry_id: string;
  entry_number: string;
  posting_date: string;
  created_at: string;
  event_type: string;
  category: string;
  memo: string;
  direction: DailyCashActivityDirection;
  amount: string | number;
  // Present only when direction is "in" or "out".
  account_code?: string;
  account_name?: string;
  // Present only when direction is "mutation".
  from_account_code?: string;
  from_account_name?: string;
  to_account_code?: string;
  to_account_name?: string;
}

export interface DailyCashActivityResponse {
  date: string;
  activities: DailyCashActivityRow[];
  total_in: string | number;
  total_out: string | number;
  net_cash: string | number;
  in_count: number;
  out_count: number;
  mutation_count: number;
}

async function getOrNull<T>(url: string, params: Record<string, string | undefined>): Promise<T | null> {
  try {
    const { data } = await api.get(url, { params });
    return data as T;
  } catch {
    // Mirrors organizationsApi.mine()'s own "no org yet" -> null
    // pattern — a 404 here (Anda belum tergabung dalam bengkel
    // manapun) is a real, expected state a page should render
    // gracefully, not an error to surface as a crash.
    return null;
  }
}

async function getListOrNull<T>(url: string, key: string, params: Record<string, string | undefined>): Promise<T[] | null> {
  try {
    const { data } = await api.get(url, { params });
    return data[key] as T[];
  } catch {
    return null;
  }
}

export const accountingApi = {
  trialBalance: (asOf?: string) =>
    getOrNull<TrialBalanceResponse>("/api/accounting/trial-balance/", { as_of: asOf }),

  profitLoss: (since?: string, asOf?: string) =>
    getOrNull<ProfitLossResponse>("/api/accounting/profit-loss/", { since, as_of: asOf }),

// Same real endpoint as profitLoss() above, just with compare=1 —
  // deliberately a separate method rather than an overload, so call
  // sites are explicit about which response shape they're getting
  // instead of relying on a conditional return type.
  profitLossComparison: (since?: string, asOf?: string) =>
    getOrNull<ProfitLossComparisonResponse>("/api/accounting/profit-loss/", { since, as_of: asOf, compare: "1" }),  

  balanceSheet: (asOf?: string) =>
    getOrNull<BalanceSheetResponse>("/api/accounting/balance-sheet/", { as_of: asOf }),

  cashConversionCycle: (since?: string, asOf?: string) =>
    getOrNull<CashConversionCycleResponse>("/api/accounting/cash-conversion-cycle/", { since, as_of: asOf }),

  agingAR: (asOf?: string) =>
    getOrNull<AgingReportResponse>("/api/accounting/aging-ar/", { as_of: asOf }),

  agingAP: (asOf?: string) =>
    getOrNull<AgingReportResponse>("/api/accounting/aging-ap/", { as_of: asOf }),

  dashboardFinancialSummary: (asOf?: string) =>
    getOrNull<DashboardFinancialSummaryResponse>("/api/accounting/dashboard-financial-summary/", { as_of: asOf }),

  // 1 Sep 2026 — Kas Harian. `date` defaults server-side to today
  // when omitted, same convention as every other as_of-style param
  // on this page.
  dailyCashActivity: (date?: string) =>
    getOrNull<DailyCashActivityResponse>("/api/accounting/daily-cash-activity/", { date }),

  journalEntries: (opts?: { source?: JournalSource; since?: string; asOf?: string }) =>
    getListOrNull<JournalEntryRow>("/api/accounting/journal-entries/", "journal_entries", {
      source: opts?.source, since: opts?.since, as_of: opts?.asOf,
    }),

  // 4 Sep 2026 — the real, single-entry detail fetch Buku Besar's
  // own inline row expansion needs — general_ledger()'s own row
  // shape only ever carries the ONE line touching the account being
  // viewed, never every line on the entry. Same null-on-failure
  // convention as depreciationRunApi.forPeriod() below — a real 404
  // (a stale/deleted id) collapses to null, letting the page render
  // its own "couldn't load" state rather than throwing.
  async journalEntry(id: string): Promise<JournalEntryRow | null> {
    try {
      const { data } = await api.get(`/api/accounting/journal-entries/${id}/`);
      return data.journal_entry;
    } catch {
      return null;
    }
  },

  failedPostings: (opts?: { since?: string; asOf?: string }) =>
    getListOrNull<FailedPosting>("/api/accounting/failed-postings/", "failed_postings", {
      since: opts?.since, as_of: opts?.asOf,
    }),

  periods: () => getListOrNull<AccountingPeriod>("/api/accounting/periods/", "periods", {}),

  // Real WRITE actions — unlike every read above, a failure here
  // must surface its REAL message to the user (e.g. "periode ini
  // sudah pernah ditutup sebelumnya"), not silently collapse to
  // null the way a missing-org 404 does for a read.
  async closePeriod(id: string): Promise<ClosePeriodResult> {
    try {
      const { data } = await api.post(`/api/accounting/periods/${id}/close/`);
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal menutup periode." };
    }
  },

  async reopenPeriod(id: string): Promise<ReopenPeriodResult> {
    try {
      const { data } = await api.post(`/api/accounting/periods/${id}/reopen/`);
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal membuka kembali periode." };
    }
  },
};

// 29 Aug 2026 — real fixed asset register & automated depreciation,
// Made's own confirmed request.

export type AssetPaymentMethod = "cash" | "bank";

export interface Asset {
  id: string;
  number: string;
  sequence_number: number;
  name: string;
  acquisition_date: string;
  cost: string | number;
  useful_life_months: number;
  method: string;
  is_active: boolean;
  // Real Python properties on the backend, computed on read from
  // AssetDepreciationEntry rows — never cached, never stale.
  monthly_depreciation: string | number;
  accumulated_depreciation: string | number;
  book_value: string | number;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface RecordAssetPayload {
  name: string;
  acquisition_date: string;
  cost: number | string;
  useful_life_months: number;
  method?: AssetPaymentMethod;
}

export interface RecordAssetResult {
  success: boolean;
  message?: string;
  asset?: Asset;
}

export interface AssetDepreciationEntryRow {
  id: string;
  asset_id: string;
  asset_number: string;
  asset_name: string;
  amount: string | number;
  created_at: string;
}

export interface DepreciationRunResponse {
  id: string;
  accounting_period: string;
  journal_entry_id: string | null;
  total_amount: string | number;
  run_at: string;
  entries: AssetDepreciationEntryRow[];
}

export const assetsApi = {
  list: () => getListOrNull<Asset>("/api/accounting/assets/", "assets", {}),

  // Real WRITE action — same discipline as closePeriod()/reopenPeriod()
  // above: a failure here must surface its real message (e.g. a
  // rejected zero/negative cost) to the user, not silently collapse.
  async record(payload: RecordAssetPayload): Promise<RecordAssetResult> {
    try {
      const { data } = await api.post("/api/accounting/assets/", payload);
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal mencatat aset." };
    }
  },
};

export const depreciationRunApi = {
  // Returns depreciation_run: null (not a thrown error) when no run
  // exists yet for this period — a real, honest "hasn't been closed
  // yet" state, matching the backend's own real response shape.
  async forPeriod(periodId: string): Promise<DepreciationRunResponse | null> {
    try {
      const { data } = await api.get(`/api/accounting/periods/${periodId}/depreciation-run/`);
      return data.depreciation_run;
    } catch {
      return null;
    }
  },
};

// =============================================================================
// Opening Balance — new-workshop onboarding (3 Sep 2026)
// =============================================================================
// Mirrors the real backend serializer shapes exactly (see
// backend/apps/accounting/serializers.py) — a plain read row per
// category, matching what OpeningBalanceSessionSerializer nests
// under the session. Write payloads are separate, smaller types,
// same split as RecordAssetPayload/Asset above.

export interface OpeningBalanceCashLineRow {
  id: string;
  account_code: "1001" | "1101";
  amount: string | number;
  created_at: string;
}

export interface OpeningBalancePartLineRow {
  id: string;
  part_name: string;
  sku: string;
  unit: string;
  quantity: string | number;
  cost_price: string | number;
  // Null until the session is actually posted — see that model's
  // own docstring: never fabricated before the real Part exists.
  part_id: string | null;
  created_at: string;
}

export interface OpeningBalanceAssetLineRow {
  id: string;
  name: string;
  current_book_value: string | number;
  remaining_useful_life_months: number;
  asset_id: string | null;
  created_at: string;
}

export interface OpeningBalanceReceivableRow {
  id: string;
  customer: string;
  customer_name: string;
  balance_due: string | number;
  due_date: string | null;
  reference: string;
  created_at: string;
}

export interface OpeningBalancePayableRow {
  id: string;
  supplier: string;
  supplier_name: string;
  balance_due: string | number;
  due_date: string | null;
  reference: string;
  created_at: string;
}

export type OpeningBalanceOtherSide = "debit" | "credit";

export interface OpeningBalanceOtherLineRow {
  id: string;
  account_code: string;
  // Best-effort on the backend — null if account_code doesn't
  // (yet) resolve to a real Account. See that serializer's own
  // docstring: only ever validated for real at post() time.
  account_name: string | null;
  side: OpeningBalanceOtherSide;
  amount: string | number;
  description: string;
  created_at: string;
}

export interface OpeningBalanceSessionResponse {
  id: string;
  start_date: string;
  status: "DRAFT" | "POSTED";
  cash_lines: OpeningBalanceCashLineRow[];
  part_lines: OpeningBalancePartLineRow[];
  asset_lines: OpeningBalanceAssetLineRow[];
  receivable_lines: OpeningBalanceReceivableRow[];
  payable_lines: OpeningBalancePayableRow[];
  other_lines: OpeningBalanceOtherLineRow[];
  // Live PREVIEW totals, computed the same way post() itself
  // assembles the real journal — see OpeningBalanceSessionSerializer's
  // own docstring for why this is a client-facing preview, not the
  // same code path as the real balance check inside post().
  total_debit: string | number;
  total_credit: string | number;
  is_balanced: boolean;
  difference: string | number;
  journal_entry_id: string | null;
  posted_at: string | null;
  posted_by: string | null;
  posted_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface OpeningBalanceActionResult {
  success: boolean;
  message?: string;
  opening_balance_session?: OpeningBalanceSessionResponse;
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
  return message || fallback;
}

export const openingBalanceApi = {
  // Returns null when no session exists yet for this org — a real,
  // honest "hasn't started yet" state (the endpoint itself returns
  // {opening_balance_session: null} with a 200, not a 404), same
  // precedent as depreciationRunApi.forPeriod() above. Also returns
  // null on any real request failure (e.g. no organization) — same
  // "collapse to null, let the page render its own empty state"
  // convention as every other read in this file.
  async getSession(): Promise<OpeningBalanceSessionResponse | null> {
    try {
      const { data } = await api.get("/api/accounting/opening-balance/");
      return data.opening_balance_session;
    } catch {
      return null;
    }
  },

  async createSession(payload: { start_date: string }): Promise<OpeningBalanceActionResult> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal membuat sesi saldo awal.") };
    }
  },

  // The real, final, irreversible action.
  async post(): Promise<OpeningBalanceActionResult> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/post/");
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal memposting saldo awal.") };
    }
  },

  // Real upsert — a second call for the same account_code updates
  // the existing amount, matching the backend's own
  // update_or_create() behavior. No delete counterpart exists (by
  // backend design — see OpeningBalanceCashLine's own
  // unique_together) — correcting a cash/bank line means calling
  // this again with the right amount, not removing and re-adding.
  async upsertCash(payload: { account_code: "1001" | "1101"; amount: string | number }):
    Promise<{ success: boolean; message?: string; cash_line?: OpeningBalanceCashLineRow }> {
    try {
      const { data } = await api.put("/api/accounting/opening-balance/cash/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menyimpan saldo kas/bank.") };
    }
  },

  async addPart(payload: { part_name: string; sku?: string; unit?: string; quantity: string | number; cost_price: string | number }):
    Promise<{ success: boolean; message?: string; part_line?: OpeningBalancePartLineRow }> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/parts/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menambah item stok.") };
    }
  },
  async deletePart(id: string): Promise<{ success: boolean; message?: string }> {
    try {
      await api.delete(`/api/accounting/opening-balance/parts/${id}/`);
      return { success: true };
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menghapus item stok.") };
    }
  },

  async addAsset(payload: { name: string; current_book_value: string | number; remaining_useful_life_months: number }):
    Promise<{ success: boolean; message?: string; asset_line?: OpeningBalanceAssetLineRow }> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/assets/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menambah aset.") };
    }
  },
  async deleteAsset(id: string): Promise<{ success: boolean; message?: string }> {
    try {
      await api.delete(`/api/accounting/opening-balance/assets/${id}/`);
      return { success: true };
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menghapus aset.") };
    }
  },

  // customer is a real Customer UUID, resolved server-side against
  // the acting org — never a bare name. See this module's own
  // pending follow-up note in OnboardingOverlay.tsx for the
  // Customer-picker UI this is waiting on.
  async addReceivable(payload: { customer: string; balance_due: string | number; due_date?: string; reference?: string }):
    Promise<{ success: boolean; message?: string; receivable_line?: OpeningBalanceReceivableRow }> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/receivables/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menambah piutang.") };
    }
  },
  async deleteReceivable(id: string): Promise<{ success: boolean; message?: string }> {
    try {
      await api.delete(`/api/accounting/opening-balance/receivables/${id}/`);
      return { success: true };
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menghapus piutang.") };
    }
  },

  async addPayable(payload: { supplier: string; balance_due: string | number; due_date?: string; reference?: string }):
    Promise<{ success: boolean; message?: string; payable_line?: OpeningBalancePayableRow }> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/payables/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menambah utang.") };
    }
  },
  async deletePayable(id: string): Promise<{ success: boolean; message?: string }> {
    try {
      await api.delete(`/api/accounting/opening-balance/payables/${id}/`);
      return { success: true };
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menghapus utang.") };
    }
  },

  async addOther(payload: { account_code: string; side: OpeningBalanceOtherSide; amount: string | number; description?: string }):
    Promise<{ success: boolean; message?: string; other_line?: OpeningBalanceOtherLineRow }> {
    try {
      const { data } = await api.post("/api/accounting/opening-balance/other/", payload);
      return data;
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menambah entri.") };
    }
  },
  async deleteOther(id: string): Promise<{ success: boolean; message?: string }> {
    try {
      await api.delete(`/api/accounting/opening-balance/other/${id}/`);
      return { success: true };
    } catch (err) {
      return { success: false, message: extractErrorMessage(err, "Gagal menghapus entri.") };
    }
  },
};

// =============================================================================
// General Ledger (Buku Besar) — 4 Sep 2026
// =============================================================================
// Mirrors the real backend response shape exactly (reports.
// general_ledger() + trace_forward.resolve_references() mutating
// each row's own "reference" key). "reference" carries one of three
// real states — see trace_forward.py's own module docstring:
//   - "link"  — a real document with a confirmed frontend detail
//     page. url is always set when kind is "link".
//   - "badge" — a real document exists (a real reference number) but
//     no confirmed detail page to link to yet. url is always null.
//   - "none"  — no source document at all (MANUAL, PERIOD_CLOSING,
//     ASSET_ACQUISITION, DEPRECIATION, OPENING_BALANCE), or any
//     event_type the backend doesn't have a mapping for yet. label
//     and url are always null.

export type GeneralLedgerReferenceKind = "link" | "badge" | "none";

export interface GeneralLedgerReference {
  kind: GeneralLedgerReferenceKind;
  label: string | null;
  url: string | null;
}

export interface GeneralLedgerRow {
  line_id: string;
  // 4 Sep 2026 — the entry's own real UUID, distinct from
  // entry_number (a human-readable display string, "000010") —
  // needed to actually call accountingApi.journalEntry() for inline
  // row expansion.
  entry_id: string;
  posting_date: string;
  entry_number: string;
  event_type: string;
  source: string;
  memo: string;
  debit: string | number;
  credit: string | number;
  running_balance: string | number;
  reference_event_id: string | null;
  reference: GeneralLedgerReference;
}

export interface GeneralLedgerAccountInfo {
  code: string;
  name: string;
  account_type: string;
  normal_balance: "DEBIT" | "CREDIT";
}

export interface GeneralLedgerData {
  account: GeneralLedgerAccountInfo;
  since: string | null;
  as_of: string;
  opening_balance: string | number;
  total_debit: string | number;
  total_credit: string | number;
  closing_balance: string | number;
  total_count: number;
  page: number;
  page_size: number;
  rows: GeneralLedgerRow[];
}

// Discriminated on `success` — a real 400 (e.g. an invalid account
// code) must surface its own real message to the user, not silently
// collapse to an empty/null state the way a plain missing-org read
// does elsewhere in this file (getOrNull's own convention). Matches
// the same {success, message} shape every other real WRITE action in
// this file already uses (closePeriod, reopenPeriod, assetsApi.
// record) — this GET can genuinely fail with a real, user-facing
// validation error too, so it gets the same honest treatment.
export type GeneralLedgerResult =
  | ({ success: true } & GeneralLedgerData)
  | { success: false; message: string };

export const generalLedgerApi = {
  async get(params: {
    account: string; since?: string; asOf?: string; page?: number; pageSize?: number;
  }): Promise<GeneralLedgerResult> {
    try {
      const { data } = await api.get("/api/accounting/general-ledger/", {
        params: {
          account: params.account, since: params.since, as_of: params.asOf,
          page: params.page, page_size: params.pageSize,
        },
      });
      return data;
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      return { success: false, message: message || "Gagal memuat buku besar." };
    }
  },
};
