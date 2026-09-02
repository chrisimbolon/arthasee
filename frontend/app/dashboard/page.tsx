"use client";
// =============================================================================
// === frontend/app/dashboard/page.tsx ===
// =============================================================================
import {
  accountingApi, DailyCashActivityResponse, DashboardFinancialSummaryResponse,
  ProfitLossComparisonResponse, ReportDelta,
} from "@/lib/api/accounting";
import { Customer, customersApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { ActiveJob, activeJobsApi, dashboardApi, DashboardSummary } from "@/lib/api/workorders";
import {
  AlertTriangle, ArrowLeftRight, Car, CheckCircle2, Clock, Landmark, Layers,
  Loader2, TrendingDown, TrendingUp, Users, Wallet, Wrench,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

type Period = "today" | "week" | "month" | "year";
const PERIOD_LABEL: Record<Period, string> = { today: "Hari Ini", week: "Minggu Ini", month: "Bulan Ini", year: "Tahun Ini" };

function formatHours(h: number) {
  return h < 1 ? `${Math.round(h * 60)} menit` : `${h.toFixed(1)} jam`;
}

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(toNumber(value));
}

// Sprint 7, Task 7.4 — one reusable delta caption for the Net Profit
// card's three sub-metrics (Revenue, Gross Profit, Net Income).
// change_pct is null when the PRIOR period was exactly zero (see
// reports.py's own profit_and_loss_comparison() docstring) — falls
// back to showing the raw Rupiah change instead of a percentage in
// that case, never a fabricated/undefined number.
function DeltaCaption({ delta }: { delta: ReportDelta }) {
  const changeNum = toNumber(delta.change);
  const pct = delta.change_pct === null ? null : toNumber(delta.change_pct);
  const positive = changeNum >= 0;
  const Icon = positive ? TrendingUp : TrendingDown;
  const color = positive ? "var(--workshop)" : "var(--danger)";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 600, color }}>
      <Icon size={12} />
      {pct === null ? formatRupiah(Math.abs(changeNum)) : `${Math.abs(pct).toFixed(1)}%`}
      <span style={{ color: "var(--steel)", fontWeight: 400 }}>vs 90 hari sebelumnya</span>
    </span>
  );
}

export default function DashboardOverviewPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [vehicles, setVehicles]   = useState<Vehicle[]>([]);
  const [dueVehicles, setDueVehicles] = useState<Vehicle[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [period, setPeriod] = useState<Period>("today");
  const [loading, setLoading]     = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  // Made's own request, 4 Aug meeting: "Tahap pekerjaan berat, gimana
  // caranya muncul di dashboard owner (responsive)" — a clean summary
  // of active staged/heavy jobs and their current stage, checkable
  // from his phone without opening each full WorkOrder. Deliberately
  // NOT a new backend endpoint — GET /api/work-orders/active/ already
  // returns current_stage_name/current_stage_mechanic for every open
  // WorkOrder (built for the full /dashboard/active-jobs roster);
  // this just reuses it, filtered client-side to the ones that
  // genuinely have a stage in motion. A routine, unstaged job (no
  // current_stage_name) isn't what "heavy" means here, so it's left
  // out — that's what the "Antrian / Dikerjakan" count above already
  // covers.
  const [stagedJobs, setStagedJobs] = useState<ActiveJob[]>([]);
  const [stagedJobsLoading, setStagedJobsLoading] = useState(true);

  // Made's own real question, quoted directly: "Berapa banyak
  // pelanggan yang belum bayar? Siapa saja? (Piutang)" and "Bengkel
  // kita berhutang ke siapa saja dan berapa jumlahnya? (Utang)".
  // Fetched independently — a point-in-time snapshot, not tied to
  // the operational `period` toggle above.
  const [financialSummary, setFinancialSummary] = useState<DashboardFinancialSummaryResponse | null>(null);
  const [financialSummaryLoading, setFinancialSummaryLoading] = useState(true);  

  // 1 Sep 2026 — Kas Harian. Made's own confirmed real request,
  // arrived at from a real UX gap: the Jurnal & Audit Log page is
  // correct for audit purposes but not friendly for a daily glance
  // — this compact card is that glance; the full filterable/
  // searchable view lives at /dashboard/accounting/kas-harian. Own
  // fetch, own loading state, same as financialSummary above —
  // always today's own date, not tied to the `period` toggle below.
  const [cashActivity, setCashActivity] = useState<DailyCashActivityResponse | null>(null);
  const [cashActivityLoading, setCashActivityLoading] = useState(true);

  // Sprint 7, Task 7.4 — Chris and Made's own confirmed call: no new
  // calculation engine, reuses profit_and_loss_comparison() exactly
  // as-is (already live since Phase 5, Task 5.5), the dashboard card
  // just passes explicit since/as_of 90 days apart rather than the
  // endpoint gaining a new "quarterly" preset param. Own fetch, own
  // loading state — a real point-in-time comparison, not tied to the
  // operational `period` toggle below.
  const [netProfit, setNetProfit] = useState<ProfitLossComparisonResponse | null>(null);
  const [netProfitLoading, setNetProfitLoading] = useState(true);

  useEffect(() => {
    Promise.all([customersApi.list(), vehiclesApi.list(), vehiclesApi.list({ dueForService: true })])
      .then(([c, v, due]) => { setCustomers(c); setVehicles(v); setDueVehicles(due); })
      .finally(() => setLoading(false));
  }, []);

  // Made's own 28 Jul Owner Dashboard requirements — his own words
  // on the real underlying problem: "Masalah utama pd kontrol adalah
  // pelacakan & pemeriksaan" (the main problem with control is
  // tracking & checking). Fetched separately from the block above —
  // period changes only need to refetch this, not the whole page.
  useEffect(() => {
    setSummaryLoading(true);
    dashboardApi.summary(period).then(setSummary).finally(() => setSummaryLoading(false));
  }, [period]);

  useEffect(() => {
    activeJobsApi.list()
      .then((jobs) => setStagedJobs(jobs.filter((j) => j.current_stage_name !== null)))
      .finally(() => setStagedJobsLoading(false));
  }, []);

  useEffect(() => {
    accountingApi.dashboardFinancialSummary()
      .then(setFinancialSummary)
      .finally(() => setFinancialSummaryLoading(false));
  }, []);  

  useEffect(() => {
    accountingApi.dailyCashActivity()
      .then(setCashActivity)
      .finally(() => setCashActivityLoading(false));
  }, []);

  useEffect(() => {
    // Local date components, deliberately NOT toISOString().slice(0,10)
    // — that method converts to UTC first, which can silently shift
    // the computed date by one day depending on time-of-day and
    // timezone (this shop is UTC+7). Low-stakes for a 90-day window,
    // but cheap to get right rather than risk it.
    const toISO = (d: Date) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${day}`;
    };
    const today = new Date();
    const ninetyDaysAgo = new Date(today);
    ninetyDaysAgo.setDate(today.getDate() - 90);

    accountingApi.profitLossComparison(toISO(ninetyDaysAgo), toISO(today))
      .then(setNetProfit)
      .finally(() => setNetProfitLoading(false));
  }, []);

  if (loading) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Ringkasan</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 28 }}>Kondisi bengkel Anda hari ini.</p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <Users size={18} style={{ color: "var(--workshop)" }} />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Pelanggan</span>
          </div>
          <div className="mono" style={{ fontSize: 32, fontWeight: 600 }}>{customers.length}</div>
        </div>
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <Car size={18} style={{ color: "var(--workshop)" }} />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Kendaraan</span>
          </div>
          <div className="mono" style={{ fontSize: 32, fontWeight: 600 }}>{vehicles.length}</div>
        </div>
        <div className="card" style={{ borderColor: dueVehicles.length > 0 ? "var(--hazard)" : "var(--line)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <AlertTriangle size={18} style={{ color: "var(--hazard-dark)" }} />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Harus Servis</span>
          </div>
          <div className="mono" style={{ fontSize: 32, fontWeight: 600, color: dueVehicles.length > 0 ? "var(--hazard-dark)" : "var(--ink)" }}>{dueVehicles.length}</div>
        </div>
      </div>

      {!financialSummaryLoading && financialSummary && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16, marginBottom: 16 }}>
            <div className="card" style={{ borderColor: toNumber(financialSummary.ar_overdue_total) > 0 ? "var(--hazard)" : "var(--line)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <Wallet size={18} style={{ color: "var(--workshop)" }} />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Piutang Belum Dibayar</span>
              </div>
              <div className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{formatRupiah(financialSummary.ar_total_outstanding)}</div>
              {toNumber(financialSummary.ar_overdue_total) > 0 && (
                <p style={{ fontSize: 11.5, color: "var(--hazard-dark)", marginTop: 6 }}>
                  {formatRupiah(financialSummary.ar_overdue_total)} lewat 30 hari — {financialSummary.ar_overdue_customers.length} pelanggan
                </p>
              )}
            </div>
            <div className="card" style={{ borderColor: toNumber(financialSummary.ap_due_soon_total) > 0 ? "var(--hazard)" : "var(--line)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <Landmark size={18} style={{ color: "var(--steel)" }} />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Utang Belum Dibayar</span>
              </div>
              <div className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{formatRupiah(financialSummary.ap_total_outstanding)}</div>
              {toNumber(financialSummary.ap_due_soon_total) > 0 && (
                <p style={{ fontSize: 11.5, color: "var(--hazard-dark)", marginTop: 6 }}>
                  {formatRupiah(financialSummary.ap_due_soon_total)} jatuh tempo minggu ini — {financialSummary.ap_due_soon_count} invoice
                </p>
              )}
            </div>
          </div>

          {(financialSummary.ar_overdue_invoices.length > 0 || financialSummary.ap_due_soon_invoices.length > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 32 }}>
              {financialSummary.ar_overdue_invoices.length > 0 && (
                <div className="card" style={{ borderColor: "var(--danger)" }}>
                  <h2 style={{ fontSize: 14.5, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center", gap: 7, color: "var(--danger)" }}>
                    <AlertTriangle size={15} /> Piutang Lewat 30 Hari
                  </h2>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {financialSummary.ar_overdue_invoices.map((inv) => (
                      <div key={inv.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                        <span>{inv.customer_name}</span>
                        <span className="mono" style={{ fontWeight: 600 }}>{formatRupiah(inv.balance_due)}</span>
                      </div>
                    ))}
                  </div>
                  <Link href="/dashboard/accounting/reports" style={{ display: "inline-block", fontSize: 12, color: "var(--rust)", marginTop: 12 }}>
                    Lihat semua piutang →
                  </Link>
                </div>
              )}
              {financialSummary.ap_due_soon_invoices.length > 0 && (
                <div className="card" style={{ borderColor: "var(--hazard)" }}>
                  <h2 style={{ fontSize: 14.5, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center", gap: 7, color: "var(--hazard-dark)" }}>
                    <AlertTriangle size={15} /> Utang Jatuh Tempo Minggu Ini
                  </h2>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {financialSummary.ap_due_soon_invoices.map((inv) => (
                      <div key={inv.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                        <span>{inv.supplier_name}</span>
                        <span className="mono" style={{ fontWeight: 600 }}>{formatRupiah(inv.amount)}</span>
                      </div>
                    ))}
                  </div>
                  <Link href="/dashboard/accounting/reports" style={{ display: "inline-block", fontSize: 12, color: "var(--rust)", marginTop: 12 }}>
                    Lihat semua utang →
                  </Link>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* 1 Sep 2026 — Kas Harian. Made and Chris's own confirmed
          placement: same row-shape as the Piutang/Utang cards above
          (a compact glance, not the full filterable/searchable
          view), linking out to /dashboard/accounting/kas-harian for
          the real thing — same "glance card + dedicated page" split
          already established for Laba Bersih below. */}
      {!cashActivityLoading && cashActivity && (
        <div className="card" style={{ marginBottom: 32 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <ArrowLeftRight size={18} style={{ color: "var(--workshop)" }} />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Kas Hari Ini</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
            <div>
              <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Masuk</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 600, color: "var(--workshop)" }}>{formatRupiah(cashActivity.total_in)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Keluar</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 600, color: "var(--danger)" }}>{formatRupiah(cashActivity.total_out)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Bersih</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 600, color: toNumber(cashActivity.net_cash) < 0 ? "var(--danger)" : "var(--ink)" }}>
                {formatRupiah(cashActivity.net_cash)}
              </div>
            </div>
          </div>
          <Link href="/dashboard/accounting/kas-harian" style={{ display: "inline-block", fontSize: 12, color: "var(--rust)", marginTop: 16 }}>
            Lihat Kas Harian →
          </Link>
        </div>
      )}

      {/* Sprint 7, Task 7.4 — Made and Chris's own confirmed
          placement: alongside the existing Dashboard Financial
          Summary cards from Phase 5, not the Laporan Keuangan
          reports page. gross_profit_note is surfaced here too — the
          same caveat Task 4.1's own roadmap note required stay
          visible in the UI wherever gross_profit appears, not
          dropped just because this is a compact dashboard card. */}
      {!netProfitLoading && netProfit && (
        <div className="card" style={{ marginBottom: 32 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <TrendingUp size={18} style={{ color: "var(--workshop)" }} />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Laba Bersih (90 Hari Terakhir)</span>
          </div>
          <div
            className="mono"
            style={{ fontSize: 32, fontWeight: 600, marginBottom: 4, color: toNumber(netProfit.current.net_income) < 0 ? "var(--danger)" : "var(--ink)" }}
          >
            {formatRupiah(netProfit.current.net_income)}
          </div>
          <DeltaCaption delta={netProfit.net_income_delta} />
          <p style={{ fontSize: 11, color: "var(--steel-lt)", marginTop: 8, marginBottom: 18 }}>{netProfit.current.gross_profit_note}</p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
            <div>
              <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Pendapatan</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>{formatRupiah(netProfit.current.total_revenue)}</div>
              <DeltaCaption delta={netProfit.revenue_delta} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Laba Kotor</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>{formatRupiah(netProfit.current.gross_profit)}</div>
              <DeltaCaption delta={netProfit.gross_profit_delta} />
            </div>
          </div>

          <Link href="/dashboard/accounting/reports" style={{ display: "inline-block", fontSize: 12, color: "var(--rust)", marginTop: 16 }}>
            Lihat laporan lengkap →
          </Link>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700 }}>Operasional Bengkel</h2>
        <div style={{ display: "flex", gap: 4 }}>
          {(["today", "week", "month", "year"] as Period[]).map((p) => (
            <button
              key={p} onClick={() => setPeriod(p)}
              className={period === p ? "btn-rust" : "btn-ghost"}
              style={{ fontSize: 11.5, padding: "4px 10px" }}
            >
              {PERIOD_LABEL[p]}
            </button>
          ))}
        </div>
      </div>

      {summaryLoading || !summary ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)", marginBottom: 32 }}>
          <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> Memuat data operasional…
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 32 }}>
            <div className="card">
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <Wrench size={18} style={{ color: "var(--workshop)" }} />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Mekanik Bekerja</span>
              </div>
              <div className="mono" style={{ fontSize: 32, fontWeight: 600 }}>
                {summary.mechanics.working} <span style={{ fontSize: 16, color: "var(--steel)" }}>/ {summary.mechanics.active}</span>
              </div>
              {summary.mechanics.active === 0 && (
                <p style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6 }}>
                  Belum ada mekanik tercatat — <Link href="/dashboard/mechanics" style={{ color: "var(--rust)" }}>tambahkan di sini</Link>.
                </p>
              )}
            </div>
            <div className="card">
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <CheckCircle2 size={18} style={{ color: "#2e7d4f" }} />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Selesai ({PERIOD_LABEL[period]})</span>
              </div>
              <div className="mono" style={{ fontSize: 32, fontWeight: 600 }}>{summary.vehicles_cleared.count}</div>
            </div>
            <div className="card">
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <Clock size={18} style={{ color: "var(--steel)" }} />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase" }}>Antrian / Dikerjakan</span>
              </div>
              <div className="mono" style={{ fontSize: 32, fontWeight: 600 }}>
                {summary.work_orders.queued} <span style={{ fontSize: 16, color: "var(--steel)" }}>/ {summary.work_orders.in_progress}</span>
              </div>
            </div>
          </div>

          {(summary.overdue.work_orders.length > 0 || summary.overdue.stages.length > 0) && (
            <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 32 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 4, display: "flex", alignItems: "center", gap: 8, color: "var(--danger)" }}>
                <AlertTriangle size={16} /> Pekerjaan Lebih Lama dari Perkiraan
              </h2>
              <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14 }}>
                Made's own example: ganti oli + kampas rem lebih dari 2 jam.
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {summary.overdue.work_orders.map((wo) => (
                  <Link
                    key={wo.id} href={`/dashboard/work-order-detail?id=${wo.id}`}
                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 12px", background: "var(--paper-3)", borderRadius: 6, fontSize: 13.5 }}
                  >
                    <span><span className="mono" style={{ fontWeight: 600 }}>WO #{wo.number}</span> · {wo.vehicle_plate}</span>
                    <span className="mono" style={{ color: "var(--danger)", fontWeight: 600 }}>{formatHours(wo.hours_elapsed)}</span>
                  </Link>
                ))}
                {summary.overdue.stages.map((s) => (
                  <Link
                    key={s.id} href={`/dashboard/work-order-detail?id=${s.work_order_id}`}
                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 12px", background: "var(--paper-3)", borderRadius: 6, fontSize: 13.5 }}
                  >
                    <span>{s.name} · <span className="mono">WO #{s.work_order_number}</span></span>
                    <span className="mono" style={{ color: "var(--danger)", fontWeight: 600 }}>{formatHours(s.hours_elapsed)}</span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Made's own 4 Aug request — a clean, at-a-glance view of every
          staged/heavy job and its CURRENT step, checkable from his
          phone. Deliberately its own card, separate from the overdue
          alert above: that one is "what needs attention," this one
          is "what's happening right now," good and bad both. Grid on
          desktop, stacks to one column under 640px — no fixed-width
          assumptions, matching Made's own explicit "responsive" ask. */}
      {!stagedJobsLoading && stagedJobs.length > 0 && (
        <div className="card" style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
            <Layers size={16} style={{ color: "var(--workshop)" }} /> Pekerjaan Bertahap Aktif
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
            {stagedJobs.map((job) => (
              <Link
                key={job.id} href={`/dashboard/work-order-detail?id=${job.id}`}
                style={{
                  display: "block", padding: "12px 14px", borderRadius: 8, background: "var(--paper-3)",
                  border: job.is_overdue ? "1px solid var(--danger)" : "1px solid transparent",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span className="mono" style={{ fontWeight: 600, fontSize: 13.5 }}>WO #{job.number}</span>
                  {job.is_overdue && <AlertTriangle size={13} style={{ color: "var(--danger)" }} />}
                </div>
                <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 8 }}>{job.vehicle_plate} · {job.customer_name}</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: job.is_overdue ? "var(--danger)" : "var(--rust)" }}>
                    {job.current_stage_name}
                  </span>
                  <span className="mono" style={{ fontSize: 11, color: "var(--steel)" }}>{formatHours(job.elapsed_hours)}</span>
                </div>
                {job.current_stage_mechanic && (
                  <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 3 }}>{job.current_stage_mechanic}</div>
                )}
              </Link>
            ))}
          </div>
        </div>
      )}

      {dueVehicles.length > 0 && (
        <div className="card">
          <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>Kendaraan yang harus segera servis</h2>
          <table className="data-table">
            <thead>
              <tr><th>Plat</th><th>Model</th><th>Pelanggan</th><th>KM Sekarang</th></tr>
            </thead>
            <tbody>
              {dueVehicles.map((v) => (
                <tr key={v.id}>
                  <td><Link href={`/dashboard/vehicle-detail?id=${v.id}`} className="mono" style={{ fontWeight: 600, color: "var(--rust)" }}>{v.plate_number}</Link></td>
                  <td>{v.model}</td>
                  <td>{v.customer_name}</td>
                  <td className="mono">{v.current_odometer_km.toLocaleString("id-ID")} km</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
