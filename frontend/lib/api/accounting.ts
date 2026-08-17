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

  journalEntries: (opts?: { source?: JournalSource; since?: string; asOf?: string }) =>
    getListOrNull<JournalEntryRow>("/api/accounting/journal-entries/", "journal_entries", {
      source: opts?.source, since: opts?.since, as_of: opts?.asOf,
    }),

  failedPostings: (opts?: { since?: string; asOf?: string }) =>
    getListOrNull<FailedPosting>("/api/accounting/failed-postings/", "failed_postings", {
      since: opts?.since, as_of: opts?.asOf,
    }),
};
