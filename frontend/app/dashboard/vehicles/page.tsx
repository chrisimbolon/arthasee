"use client";
// =============================================================================
// === frontend/app/dashboard/vehicles/page.tsx ===
// =============================================================================
import { Customer, customersApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { AlertTriangle, Calendar, ChevronDown, Loader2, Plus, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

function AddVehicleModal({ customers, onClose, onCreated }: {
  customers: Customer[]; onClose: () => void; onCreated: (v: Vehicle) => void;
}) {
  const [form, setForm] = useState({
    customer: "", plate_number: "", manufacture_year: new Date().getFullYear(),
    vehicle_type: "Mobil", model: "", current_odometer_km: 0,
    // Sprint 1: STNK fields — all optional, kept in a separate
    // "collapsed by default" section below so the fast path (add a
    // vehicle with the basics, fill in STNK details later) stays
    // exactly as quick as it was before this sprint.
    body_style: "", chassis_number: "", engine_number: "",
    bpkb_number: "", color: "", registration_expiry: "",
  });
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [showStnk, setShowStnk]   = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      // Strip empty-string optional fields rather than sending them —
      // an empty string for registration_expiry (a DateField on the
      // backend) would fail validation outright instead of being
      // treated as "not provided."
      const payload = { ...form };
      (Object.keys(payload) as (keyof typeof payload)[]).forEach((key) => {
        if (payload[key] === "" && key !== "plate_number" && key !== "model") {
          delete (payload as Record<string, unknown>)[key];
        }
      });
      const vehicle = await vehiclesApi.create(payload);
      onCreated(vehicle);
      onClose();
    } catch {
      setError("Gagal menyimpan kendaraan. Pastikan nomor plat belum terdaftar.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, overflowY: "auto", padding: "40px 0" }}>
      <div className="card" style={{ width: 460, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Tambah Kendaraan</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Pelanggan</label>
            <select className="input" required value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}>
              <option value="">— Pilih Pelanggan —</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Nomor Plat</label>
              <input className="input" required value={form.plate_number} onChange={(e) => setForm({ ...form, plate_number: e.target.value.toUpperCase() })} placeholder="BP 1234 AB" />
            </div>
            <div>
              <label className="label">Tahun</label>
              <input className="input" type="number" required value={form.manufacture_year} onChange={(e) => setForm({ ...form, manufacture_year: Number(e.target.value) })} />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Jenis</label>
              <select className="input" value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}>
                <option>Mobil</option><option>Motor</option>
              </select>
            </div>
            <div>
              <label className="label">Model</label>
              <input className="input" required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="Toyota Avanza" />
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">KM Saat Ini</label>
            <input className="input" type="number" min={0} value={form.current_odometer_km} onChange={(e) => setForm({ ...form, current_odometer_km: Number(e.target.value) })} />
          </div>

          {/* Sprint 1: STNK details — collapsed by default, optional */}
          <button
            type="button"
            onClick={() => setShowStnk(!showStnk)}
            style={{ background: "none", border: "none", display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", padding: 0, marginBottom: showStnk ? 14 : 20, cursor: "pointer" }}
          >
            <ChevronDown size={14} style={{ transform: showStnk ? "rotate(180deg)" : "none", transition: "transform 0.15s" }} />
            Detail STNK <span style={{ fontWeight: 400 }}>(opsional)</span>
          </button>

          {showStnk && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                <div>
                  <label className="label">Jenis Bodi</label>
                  <input className="input" value={form.body_style} onChange={(e) => setForm({ ...form, body_style: e.target.value })} placeholder="Sedan, SUV, MPV" />
                </div>
                <div>
                  <label className="label">Warna</label>
                  <input className="input" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} placeholder="Putih" />
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="label">No. Rangka</label>
                <input className="input mono" value={form.chassis_number} onChange={(e) => setForm({ ...form, chassis_number: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="label">No. Mesin</label>
                <input className="input mono" value={form.engine_number} onChange={(e) => setForm({ ...form, engine_number: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="label">No. BPKB</label>
                <input className="input mono" value={form.bpkb_number} onChange={(e) => setForm({ ...form, bpkb_number: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ marginBottom: 20 }}>
                <label className="label">STNK Berlaku Sampai</label>
                <input className="input" type="date" value={form.registration_expiry} onChange={(e) => setForm({ ...form, registration_expiry: e.target.value })} />
              </div>
            </>
          )}

          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

type FilterMode = "all" | "due" | "expiring";

export default function VehiclesPage() {
  const [vehicles, setVehicles]   = useState<Vehicle[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading]     = useState(true);
  const [filter, setFilter]       = useState<FilterMode>("all");
  const [showAdd, setShowAdd]     = useState(false);

  const load = (mode: FilterMode) => {
    setLoading(true);
    vehiclesApi.list({
      dueForService: mode === "due",
      registrationExpiringSoon: mode === "expiring",
    }).then(setVehicles).finally(() => setLoading(false));
  };

  useEffect(() => { load(filter); }, [filter]);
  useEffect(() => { customersApi.list().then(setCustomers); }, []);

  const emptyMessage = filter === "due" ? "Tidak ada kendaraan yang harus servis"
    : filter === "expiring" ? "Tidak ada STNK yang akan jatuh tempo dalam 30 hari"
    : "Belum ada kendaraan";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Kendaraan</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{vehicles.length} kendaraan {filter !== "all" ? "(terfilter)" : "tercatat"}</p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Tambah Kendaraan</button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        <button onClick={() => setFilter("all")} className={filter === "all" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13 }}>Semua</button>
        <button onClick={() => setFilter("due")} className={filter === "due" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={14} /> Harus Servis
        </button>
        <button onClick={() => setFilter("expiring")} className={filter === "expiring" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <Calendar size={14} /> STNK Segera Habis
        </button>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Plat</th><th>Model</th><th>Pelanggan</th><th>KM Sekarang</th><th>Servis Terakhir</th><th>Status</th></tr>
            </thead>
            <tbody>
              {vehicles.map((v) => (
                <tr key={v.id}>
                  <td><Link href={`/dashboard/vehicle-detail?id=${v.id}`} className="mono" style={{ fontWeight: 600, color: "var(--rust)" }}>{v.plate_number}</Link></td>
                  <td>{v.model} <span style={{ color: "var(--steel)", fontSize: 12.5 }}>({v.manufacture_year})</span></td>
                  <td>{v.customer_name}</td>
                  <td className="mono">{v.current_odometer_km.toLocaleString("id-ID")} km</td>
                  <td className="mono" style={{ fontSize: 13 }}>{v.last_service_date || <span style={{ color: "var(--steel)" }}>Belum pernah</span>}</td>
                  <td style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <span className={`pill ${v.is_due_for_service ? "due" : "ok"}`}>
                      <span className="dot" />{v.is_due_for_service ? "Harus Servis" : "Aman"}
                    </span>
                    {v.is_registration_expiring_soon && (
                      <span className="pill due"><Calendar size={11} style={{ marginRight: 3 }} />STNK Segera Habis</span>
                    )}
                  </td>
                </tr>
              ))}
              {vehicles.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>{emptyMessage}</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddVehicleModal customers={customers} onClose={() => setShowAdd(false)} onCreated={(v) => setVehicles((prev) => [v, ...prev])} />
      )}
    </div>
  );
}
