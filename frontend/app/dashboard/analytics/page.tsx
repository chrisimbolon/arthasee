"use client";
// =============================================================================
// === frontend/app/dashboard/analytics/page.tsx ===
// =============================================================================
import {
  analyticsApi, CustomerGrowthResponse, JobVolumeTrendResponse,
  MechanicUtilizationResponse, QueueStatusResponse, RevenueTrendResponse,
} from "@/lib/api/analytics";
import { Loader2, TriangleAlert, Users, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

function formatMonthLabel(month: string): string {
  // "2026-08" -> "Agu 2026"
  const [y, m] = month.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
  return `${names[parseInt(m, 10) - 1]} ${y}`;
}

function LoadingCard() {
  return (
    <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
      <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
    </div>
  );
}

// ── Grouped bar chart — the one chart shape this whole page reuses,
// hand-rolled SVG, no external chart library (this repo's real
// dependencies aren't confirmed in this conversation, so this is
// guaranteed to work with zero new installs). Handles negative
// values correctly — bars render below the zero baseline, not
// clipped — verified by hand before being written here.

interface ChartSeries {
  key: string;
  label: string;
  color: string;
}

function GroupedBarChart({
  data, series, formatValue, height = 220,
}: {
  data: Record<string, string | number>[];
  series: ChartSeries[];
  formatValue: (v: number) => string;
  height?: number;
}) {
  const width = 680;
  const padding = { top: 16, right: 16, bottom: 34, left: 16 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  if (data.length === 0) {
    return <div style={{ textAlign: "center", color: "var(--steel-lt)", fontSize: 13, padding: 40 }}>Belum ada data.</div>;
  }

  const allValues = data.flatMap((d) => series.map((s) => toNumber(d[s.key])));
  const maxV = Math.max(1, ...allValues, 0);
  const minV = Math.min(0, ...allValues);
  const range = maxV - minV || 1;

  const groupW = chartW / data.length;
  const barW = Math.min(20, (groupW * 0.7) / series.length);
  const barGap = 3;

  const yFor = (v: number) => padding.top + chartH - ((v - minV) / range) * chartH;
  const zeroY = yFor(0);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }} role="img">
        <line x1={padding.left} y1={zeroY} x2={width - padding.right} y2={zeroY} stroke="var(--line)" strokeWidth={1} />
        {data.map((d, i) => {
          const groupX = padding.left + i * groupW;
          const seriesTotalW = series.length * barW + (series.length - 1) * barGap;
          const startX = groupX + (groupW - seriesTotalW) / 2;
          return (
            <g key={String(d.month)}>
              {series.map((s, si) => {
                const value = toNumber(d[s.key]);
                const barX = startX + si * (barW + barGap);
                const barY = Math.min(yFor(value), zeroY);
                const barH = Math.max(Math.abs(yFor(value) - zeroY), 0.5);
                return <rect key={s.key} x={barX} y={barY} width={barW} height={barH} fill={s.color} rx={2} />;
              })}
              <text x={groupX + groupW / 2} y={height - 12} textAnchor="middle" fontSize={10.5} fill="var(--steel)">
                {formatMonthLabel(String(d.month)).replace(" ", "\u00A0")}
              </text>
            </g>
          );
        })}
      </svg>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8, fontSize: 12, color: "var(--steel)" }}>
        {series.map((s) => (
          <span key={s.key} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: s.color, display: "inline-block" }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Hero: the exact question that started this whole feature ──────

function MechanicHero({ data }: { data: MechanicUtilizationResponse | null }) {
  if (!data) return <LoadingCard />;
  const idle = data.mechanics_total - data.mechanics_working;
  return (
    <div className="card" style={{ display: "flex", alignItems: "center", gap: 24, padding: 28 }}>
      <div style={{ width: 52, height: 52, borderRadius: 10, background: "var(--rust-light)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Wrench size={24} color="var(--rust-dark)" />
      </div>
      <div>
        <div style={{ fontSize: 12.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
          Mekanik Bekerja Sekarang
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span className="display" style={{ fontSize: 44, lineHeight: 1 }}>{data.mechanics_working}</span>
          <span style={{ fontSize: 20, color: "var(--steel)" }}>/ {data.mechanics_total}</span>
        </div>
        <div style={{ fontSize: 12.5, color: "var(--steel-lt)", marginTop: 4 }}>
          {idle > 0 ? `${idle} mekanik aktif belum ditugaskan ke pekerjaan yang sedang berjalan` : "Semua mekanik aktif sedang bekerja"}
        </div>
      </div>
    </div>
  );
}

// ── Queue status row ────────────────────────────────────────────

function QueueStatusRow({ data }: { data: QueueStatusResponse | null }) {
  if (!data) return <LoadingCard />;
  const items = [
    { label: "Antre (Belum Dikerjakan)", value: data.open },
    { label: "Sedang Dikerjakan", value: data.in_progress },
    { label: "Pemeriksaan Kualitas", value: data.qc },
    { label: "Selesai", value: data.done },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
      {items.map((item) => (
        <div key={item.label} className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>
            {item.label}
          </div>
          <div className="mono" style={{ fontSize: 24, fontWeight: 700 }}>{item.value}</div>
        </div>
      ))}
    </div>
  );
}

// ── Revenue & profit trend ──────────────────────────────────────

function RevenueTrendSection({ data }: { data: RevenueTrendResponse | null }) {
  if (!data) return <LoadingCard />;

  const chartData = data.months.map((m) => ({
    month: m.month, revenue: m.revenue, net_income: m.net_income,
  }));

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 4 }}>Tren Pendapatan &amp; Laba Bersih</div>
      <GroupedBarChart
        data={chartData}
        series={[
          { key: "revenue", label: "Pendapatan", color: "var(--workshop)" },
          { key: "net_income", label: "Laba Bersih", color: "var(--rust)" },
        ]}
        formatValue={formatRupiah}
      />
      <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "10px 14px", fontSize: 12.5, marginTop: 16, display: "flex", gap: 8, alignItems: "flex-start" }}>
        <TriangleAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>
          Proyeksi bulan depan (rata-rata sederhana 3 bulan terakhir, bukan model statistik):{" "}
          <strong className="mono">{formatRupiah(data.projected_next_net_income)}</strong>
        </span>
      </div>
    </div>
  );
}

// ── Job volume trend ─────────────────────────────────────────────

function JobVolumeSection({ data }: { data: JobVolumeTrendResponse | null }) {
  if (!data) return <LoadingCard />;
  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 4 }}>Volume Pekerjaan — Dibuat vs Selesai</div>
      <GroupedBarChart
        data={data.months.map((m) => ({ month: m.month, created: m.created, completed: m.completed }))}
        series={[
          { key: "created", label: "Dibuat", color: "var(--steel)" },
          { key: "completed", label: "Selesai", color: "var(--workshop)" },
        ]}
        formatValue={(v) => String(v)}
      />
    </div>
  );
}

// ── Customer growth ──────────────────────────────────────────────

function CustomerGrowthSection({ data }: { data: CustomerGrowthResponse | null }) {
  if (!data) return <LoadingCard />;
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <div className="label" style={{ marginBottom: 0 }}>Pertumbuhan Pelanggan Baru</div>
        <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
          Total pelanggan: <span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{data.total_customers}</span>
        </div>
      </div>
      <GroupedBarChart
        data={data.months.map((m) => ({ month: m.month, new_customers: m.new_customers }))}
        series={[{ key: "new_customers", label: "Pelanggan Baru", color: "var(--rust)" }]}
        formatValue={(v) => String(v)}
      />
    </div>
  );
}

// ── Page shell ───────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [mechanicData, setMechanicData] = useState<MechanicUtilizationResponse | null>(null);
  const [queueData, setQueueData] = useState<QueueStatusResponse | null>(null);
  const [revenueData, setRevenueData] = useState<RevenueTrendResponse | null>(null);
  const [jobData, setJobData] = useState<JobVolumeTrendResponse | null>(null);
  const [customerData, setCustomerData] = useState<CustomerGrowthResponse | null>(null);

  useEffect(() => {
    analyticsApi.mechanicUtilization().then(setMechanicData);
    analyticsApi.queueStatus().then(setQueueData);
    analyticsApi.revenueTrend(6).then(setRevenueData);
    analyticsApi.jobVolumeTrend(6).then(setJobData);
    analyticsApi.customerGrowthTrend(6).then(setCustomerData);
  }, []);

  return (
    <div>
      <h1 className="display" style={{ fontSize: 34 }}>Pertumbuhan &amp; Analitik</h1>
      <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4, marginBottom: 24, display: "flex", alignItems: "center", gap: 6 }}>
        <Users size={14} />
        Data real dari transaksi dan pekerjaan yang sudah tercatat — 6 bulan terakhir.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <MechanicHero data={mechanicData} />
        <QueueStatusRow data={queueData} />
        <RevenueTrendSection data={revenueData} />
        <JobVolumeSection data={jobData} />
        <CustomerGrowthSection data={customerData} />
      </div>
    </div>
  );
}
