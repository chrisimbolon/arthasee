"use client";
// =============================================================================
// === frontend/app/dashboard/page.tsx ===
// =============================================================================
import { Customer, customersApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { dashboardApi, DashboardSummary } from "@/lib/api/workorders";
import { AlertTriangle, Car, CheckCircle2, Clock, Loader2, Users, Wrench } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

type Period = "today" | "week" | "month" | "year";
const PERIOD_LABEL: Record<Period, string> = { today: "Hari Ini", week: "Minggu Ini", month: "Bulan Ini", year: "Tahun Ini" };

function formatHours(h: number) {
  return h < 1 ? `${Math.round(h * 60)} menit` : `${h.toFixed(1)} jam`;
}

export default function DashboardOverviewPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [vehicles, setVehicles]   = useState<Vehicle[]>([]);
  const [dueVehicles, setDueVehicles] = useState<Vehicle[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [period, setPeriod] = useState<Period>("today");
  const [loading, setLoading]     = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);

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
