"use client";
// =============================================================================
// === frontend/app/dashboard/page.tsx ===
// =============================================================================
import { Customer, customersApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { AlertTriangle, Car, Loader2, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export default function DashboardOverviewPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [vehicles, setVehicles]   = useState<Vehicle[]>([]);
  const [dueVehicles, setDueVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading]     = useState(true);

  useEffect(() => {
    Promise.all([customersApi.list(), vehiclesApi.list(), vehiclesApi.list({ dueForService: true })])
      .then(([c, v, due]) => { setCustomers(c); setVehicles(v); setDueVehicles(due); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Ringkasan</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 28 }}>Kondisi bengkel Anda hari ini.</p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 32 }}>
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
