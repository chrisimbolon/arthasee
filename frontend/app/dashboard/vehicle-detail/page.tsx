"use client";
// =============================================================================
// === frontend/app/dashboard/vehicle-detail/page.tsx ===
// Was app/dashboard/vehicles/[id]/page.tsx — moved from a dynamic
// path segment to a query param specifically to support static
// export. A dynamic route needs every possible URL known at build
// time; real vehicle UUIDs only exist after a shop creates them, so
// that's structurally impossible here. A query string doesn't have
// that problem — the served HTML is identical regardless of ?id=
// value, and the client-side JS reads it once loaded.
// =============================================================================
import { ServiceRecord, serviceRecordsApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { AlertTriangle, ArrowLeft, Loader2, Plus, Wrench } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function AddServiceRecordForm({ vehicleId, onAdded }: { vehicleId: string; onAdded: (r: ServiceRecord, newOdometer: number) => void }) {
  const [form, setForm] = useState({
    service_date: new Date().toISOString().slice(0, 10),
    odometer_km: "", issue_description: "", parts_replaced: "", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);
  const [open, setOpen]     = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const record = await serviceRecordsApi.create(vehicleId, {
        ...form, odometer_km: Number(form.odometer_km),
      });
      onAdded(record, Number(form.odometer_km));
      setForm({ service_date: new Date().toISOString().slice(0, 10), odometer_km: "", issue_description: "", parts_replaced: "", notes: "" });
      setOpen(false);
    } catch {
      setError("Gagal menyimpan catatan servis.");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return <button className="btn-rust" onClick={() => setOpen(true)}><Plus size={16} /> Catat Servis Baru</button>;
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Catat Servis Baru</h3>
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div>
            <label className="label">Tanggal Servis</label>
            <input className="input" type="date" required value={form.service_date} onChange={(e) => setForm({ ...form, service_date: e.target.value })} />
          </div>
          <div>
            <label className="label">KM Saat Servis</label>
            <input className="input" type="number" required min={0} value={form.odometer_km} onChange={(e) => setForm({ ...form, odometer_km: e.target.value })} />
          </div>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label className="label">Kerusakan</label>
          <textarea className="input" required rows={2} value={form.issue_description} onChange={(e) => setForm({ ...form, issue_description: e.target.value })} placeholder="Ganti oli, servis rem, dll." />
        </div>
        <div style={{ marginBottom: 14 }}>
          <label className="label">Part yang Diganti <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
          <input className="input" value={form.parts_replaced} onChange={(e) => setForm({ ...form, parts_replaced: e.target.value })} placeholder="Filter oli, kampas rem" />
        </div>
        <div style={{ marginBottom: 18 }}>
          <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
          <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-rust" type="submit" disabled={saving}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
          <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>Batal</button>
        </div>
      </form>
    </div>
  );
}

function VehicleDetailContent() {
  const searchParams = useSearchParams();
  const vehicleId = searchParams.get("id") ?? "";
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => vehiclesApi.get(vehicleId).then(setVehicle).finally(() => setLoading(false));
  useEffect(() => {
    if (vehicleId) load();
  }, [vehicleId]);

  const handleAdded = () => load();

  if (!vehicleId) {
    return <div style={{ color: "var(--danger)" }}>Kendaraan tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }

  if (loading || !vehicle) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      <Link href="/dashboard/vehicles" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Kendaraan
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <span className="mono" style={{ fontSize: 26, fontWeight: 700, background: "var(--ink)", color: "var(--paper)", padding: "5px 12px", borderRadius: 5, display: "inline-block" }}>
            {vehicle.plate_number}
          </span>
        </div>
        {vehicle.is_due_for_service && (
          <span className="pill due" style={{ fontSize: 13 }}><AlertTriangle size={13} /> Harus Segera Servis</span>
        )}
      </div>

      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 24 }}>
        {vehicle.model} · {vehicle.manufacture_year} · {vehicle.customer_name}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 28 }}>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>KM Sekarang</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.current_odometer_km.toLocaleString("id-ID")}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Servis Terakhir</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.last_service_date || "—"}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>KM Saat Servis Terakhir</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.last_service_odometer_km?.toLocaleString("id-ID") ?? "—"}</div>
        </div>
      </div>

      <div style={{ marginBottom: 16 }}>
        <AddServiceRecordForm vehicleId={vehicle.id} onAdded={handleAdded} />
      </div>

      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
        <Wrench size={16} /> Riwayat Servis
      </h2>

      {(vehicle.service_records?.length ?? 0) === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 32 }}>Belum ada riwayat servis untuk kendaraan ini.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {vehicle.service_records!.map((r) => (
            <div key={r.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{r.service_date}</span>
                <span className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{r.odometer_km.toLocaleString("id-ID")} km</span>
              </div>
              <p style={{ fontSize: 14, marginBottom: r.parts_replaced ? 6 : 0 }}>{r.issue_description}</p>
              {r.parts_replaced && <p style={{ fontSize: 13, color: "var(--steel)" }}>Part diganti: {r.parts_replaced}</p>}
              {r.notes && <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 4 }}>{r.notes}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// useSearchParams() requires a Suspense boundary on statically
// exported/prerendered pages — without this, the build fails.
export default function VehicleDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <VehicleDetailContent />
    </Suspense>
  );
}
