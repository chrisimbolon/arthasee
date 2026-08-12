// =============================================================================
// === frontend/lib/api/analytics.ts ===
// =============================================================================
import api from "@/lib/api";

export interface RevenueTrendMonth {
  month: string;
  revenue: string | number;
  cogs: string | number;
  expenses: string | number;
  net_income: string | number;
}

export interface RevenueTrendResponse {
  months: RevenueTrendMonth[];
  projected_next_net_income: string | number;
  projected_months_used: number;
}

export interface MechanicUtilizationResponse {
  mechanics_working: number;
  mechanics_total: number;
}

export interface QueueStatusResponse {
  open: number;
  in_progress: number;
  qc: number;
  done: number;
}

export interface JobVolumeMonth {
  month: string;
  created: number;
  completed: number;
}

export interface JobVolumeTrendResponse {
  months: JobVolumeMonth[];
}

export interface CustomerGrowthMonth {
  month: string;
  new_customers: number;
}

export interface CustomerGrowthResponse {
  months: CustomerGrowthMonth[];
  total_customers: number;
}

async function getOrNull<T>(url: string, params: Record<string, string | undefined> = {}): Promise<T | null> {
  try {
    const { data } = await api.get(url, { params });
    return data as T;
  } catch {
    // Same "no org yet -> null" pattern as every other API client in
    // this app — a 404 is a real, expected state a page should
    // render gracefully, not a crash.
    return null;
  }
}

export const analyticsApi = {
  revenueTrend: (months?: number) =>
    getOrNull<RevenueTrendResponse>("/api/analytics/revenue-trend/", { months: months?.toString() }),

  mechanicUtilization: () =>
    getOrNull<MechanicUtilizationResponse>("/api/analytics/mechanic-utilization/"),

  queueStatus: () =>
    getOrNull<QueueStatusResponse>("/api/analytics/queue-status/"),

  jobVolumeTrend: (months?: number) =>
    getOrNull<JobVolumeTrendResponse>("/api/analytics/job-volume-trend/", { months: months?.toString() }),

  customerGrowthTrend: (months?: number) =>
    getOrNull<CustomerGrowthResponse>("/api/analytics/customer-growth-trend/", { months: months?.toString() }),
};
