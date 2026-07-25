"use client";
// =============================================================================
// === frontend/app/dashboard/vehicle-detail/page.tsx ===
// Was app/dashboard/vehicles/[id]/page.tsx — moved from a dynamic
// path segment to a query param specifically to support static
// export. A dynamic route needs every possible URL known at build
// time; real vehicle UUIDs only exist after a shop creates them, so
// that's structurally impossible here. A query string doesn't have
// that problem — the served HTML is identical regardless of ?id=value, and the client-side JS reads it once loaded.
// 
//
// RESTRUCTURED — confirmed with Made across several rounds of
// follow-up calls:
//   - "Catat Servis Baru" (the old free-text quick-entry form) is
//     removed entirely. It used to exist as a competing pathway
//     alongside "Buat Work Order", with nothing distinguishing when
//     to use which — a real UX gap Sansan's review flagged directly.
//     Work Order now genuinely covers everything that button used
//     to (including backdating, via the optional service_date on
//     close — see work-order-detail/page.tsx).
//   - Riwayat Servis is now strictly read-only. "+ Gunakan Part dari
//     Katalog" is gone from every entry, including pre-Work-Order
//     legacy records — parts are only ever logged through an active
//     Work Order now, never retroactively against a closed record.
//   - The Work Order section defaults to active-only
//     (OPEN/IN_PROGRESS/QC); DONE/CANCELLED ones are real history
//     (never deleted — see the customer_cancelled_part StockAdjustment
//     reason) but sit behind a toggle rather than cluttering the
//     primary, actionable view.
// =============================================================================
import { LaborLinePayload, invoicesApi } from "@/lib/api/invoicing";
import { ServiceRecord, Vehicle, vehiclesApi } from "@/lib/api/service";
import { WorkOrderStatus, WorkOrderSummary, workOrdersApi } from "@/lib/api/workorders";
import { AlertTriangle, ArrowLeft, Calendar, ClipboardList, FileText, Loader2, Plus, Receipt, Trash2, Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

interface LaborLine {
  key:         string;
  description: string;
  quantity:    string;
  unit_price:  string;
}

function PartUsageDisplay({ record }: { record: ServiceRecord }) {
  if (record.part_usages.length === 0) return null;
  return (
    <div style={{ marginTop: record.parts_replaced ? 8 : 0, display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
      {record.part_usages.map((pu) => (
        <div key={pu.id} className="mono" style={{ fontSize: 12.5, color: "var(--steel)", display: "flex", justifyContent: "space-between" }}>
          <span>{pu.part_name} × {pu.quantity} {pu.unit}</span>
          <span>@ Rp {Number(pu.unit_price_at_time).toLocaleString("id-ID")}</span>
        </div>
      ))}
    </div>
  );
}

function CreateInvoiceModal({ record, onClose, onCreated }: {
  record: ServiceRecord; onClose: () => void; onCreated: (invoiceId: string) => void;
}) {
  const [laborLines, setLaborLines] = useState<LaborLine[]>([
    { key: crypto.randomUUID(), description: "", quantity: "1", unit_price: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const addLine = () => setLaborLines((prev) => [...prev, { key: crypto.randomUUID(), description: "", quantity: "1", unit_price: "" }]);
  const removeLine = (key: string) => setLaborLines((prev) => prev.filter((l) => l.key !== key));
  const updateLine = (key: string, field: keyof Omit<LaborLine, "key">, value: string) =>
    setLaborLines((prev) => prev.map((l) => (l.key === key ? { ...l, [field]: value } : l)));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    const payload: LaborLinePayload[] = laborLines
      .filter((l) => l.description && l.unit_price)
      .map((l) => ({ description: l.description, quantity: Number(l.quantity) || 1, unit_price: Number(l.unit_price) }));
    try {
      const invoice = await invoicesApi.create(record.id, payload);
      onCreated(invoice.id);
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(apiMessage || "Gagal membuat invoice.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, overflowY: "auto", padding: "40px 0" }}>
      <div className="card" style={{ width: 560, background: "var(--paper-3)" }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Buat Invoice</h2>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>
          {record.service_date} — {record.issue_description}
        </p>

        {record.part_usages.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div className="label" style={{ marginBottom: 6 }}>Part (dari catatan servis)</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {record.part_usages.map((pu) => (
                <div key={pu.id} className="mono" style={{ fontSize: 13, display: "flex", justifyContent: "space-between", color: "var(--ink-soft)" }}>
                  <span>{pu.part_name} × {pu.quantity} {pu.unit}</span>
                  <span>Rp {(Number(pu.unit_price_at_time) * Number(pu.quantity)).toLocaleString("id-ID")}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="label" style={{ marginBottom: 6 }}>Jasa</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
            {laborLines.map((line) => (
              <div key={line.key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input className="input" style={{ flex: 2 }} placeholder="Jasa Servis Rem" value={line.description} onChange={(e) => updateLine(line.key, "description", e.target.value)} />
                <input className="input" style={{ width: 60 }} type="number" min={1} value={line.quantity} onChange={(e) => updateLine(line.key, "quantity", e.target.value)} />
                <input className="input" style={{ flex: 1 }} type="number" min={0} placeholder="Harga" value={line.unit_price} onChange={(e) => updateLine(line.key, "unit_price", e.target.value)} />
                <button type="button" onClick={() => removeLine(line.key)} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}>
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", marginBottom: 18 }} onClick={addLine}>
            <Plus size={13} /> Tambah Jasa
          </button>

          <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 16 }}>
            Invoice tidak bisa diedit setelah dibuat — periksa dulu sebelum menyimpan.
          </p>

          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-rust" type="submit" disabled={saving}>
              {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Buat Invoice"}
            </button>
            <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
          </div>
        </form>
      </div>
    </div>
  );
}

const WO_STATUS_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: "Terbuka", IN_PROGRESS: "Dikerjakan", QC: "Pemeriksaan Kualitas", DONE: "Selesai", CANCELLED: "Dibatalkan",
};
const WO_STATUS_COLOR: Record<WorkOrderStatus, string> = {
  OPEN: "var(--steel)", IN_PROGRESS: "var(--rust)", QC: "#b5860b", DONE: "#2e7d4f", CANCELLED: "var(--danger)",
};
const WO_OPEN_STATUSES: WorkOrderStatus[] = ["OPEN", "IN_PROGRESS", "QC"];

function WorkOrdersSection({ vehicleId }: { vehicleId: string }) {
  const router = useRouter();
  const [orders, setOrders] = useState<WorkOrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const load = () => workOrdersApi.list(vehicleId).then(setOrders).finally(() => setLoading(false));
  useEffect(() => { load(); }, [vehicleId]);

  const createAndOpen = async () => {
    setCreating(true);
    try {
      const wo = await workOrdersApi.create(vehicleId);
      router.push(`/dashboard/work-order-detail?id=${wo.id}`);
    } finally {
      setCreating(false);
    }
  };

  const activeOrders  = orders.filter((wo) => WO_OPEN_STATUSES.includes(wo.status));
  const historyOrders = orders.filter((wo) => !WO_OPEN_STATUSES.includes(wo.status));
  const visibleOrders = showHistory ? orders : activeOrders;

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <ClipboardList size={16} /> Work Order
        </h2>
        <button className="btn-rust" onClick={createAndOpen} disabled={creating}>
          {creating ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <><Plus size={16} /> Buat Work Order</>}
        </button>
      </div>

      {loading ? (
        <div style={{ color: "var(--steel)", fontSize: 13.5 }}><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : visibleOrders.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 24, fontSize: 13.5 }}>
          {showHistory ? "Belum ada work order untuk kendaraan ini." : "Tidak ada work order aktif saat ini."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {visibleOrders.map((wo) => (
            <Link key={wo.id} href={`/dashboard/work-order-detail?id=${wo.id}`} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px" }}>
              <span className="mono" style={{ fontSize: 13.5, fontWeight: 600 }}>WO #{wo.number}</span>
              <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: WO_STATUS_COLOR[wo.status] }}>
                {WO_STATUS_LABEL[wo.status]}
              </span>
            </Link>
          ))}
        </div>
      )}

      {historyOrders.length > 0 && (
        <button
          className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", marginTop: 10 }}
          onClick={() => setShowHistory((v) => !v)}
        >
          {showHistory ? "Sembunyikan Riwayat Work Order" : `Lihat Riwayat Work Order (${historyOrders.length})`}
        </button>
      )}
    </div>
  );
}

function VehicleDetailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const vehicleId = searchParams.get("id") ?? "";
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [loading, setLoading] = useState(true);
  const [invoicingRecord, setInvoicingRecord] = useState<ServiceRecord | null>(null);

  const load = () => vehiclesApi.get(vehicleId).then(setVehicle).finally(() => setLoading(false));
  useEffect(() => {
    if (vehicleId) load();
  }, [vehicleId]);

  if (!vehicleId) {
    return <div style={{ color: "var(--danger)" }}>Kendaraan tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }

  if (loading || !vehicle) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  const stnkFields = [
    { label: "Jenis Bodi", value: vehicle.body_style },
    { label: "Warna", value: vehicle.color },
    { label: "No. Rangka", value: vehicle.chassis_number },
    { label: "No. Mesin", value: vehicle.engine_number },
    { label: "No. BPKB", value: vehicle.bpkb_number },
  ].filter((f) => f.value);

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
        <div style={{ display: "flex", gap: 8 }}>
          {vehicle.is_due_for_service && (
            <span className="pill due" style={{ fontSize: 13 }}><AlertTriangle size={13} /> Harus Segera Servis</span>
          )}
          {vehicle.is_registration_expiring_soon && (
            <span className="pill due" style={{ fontSize: 13 }}><Calendar size={13} /> STNK Segera Habis</span>
          )}
        </div>
      </div>

      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 24 }}>
        {vehicle.model} · {vehicle.manufacture_year} · {vehicle.customer_name}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 16 }}>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>KM Sekarang</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.current_odometer_km.toLocaleString("id-ID")}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Servis Terakhir</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.last_service_date || "—"}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>STNK Berlaku Sampai</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: vehicle.is_registration_expiring_soon ? "var(--danger)" : undefined }}>
            {vehicle.registration_expiry || "—"}
          </div>
        </div>
      </div>

      {stnkFields.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 10 }}>Detail STNK</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10 }}>
            {stnkFields.map((f) => (
              <div key={f.label}>
                <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{f.label}</div>
                <div className="mono" style={{ fontSize: 13.5 }}>{f.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <WorkOrdersSection vehicleId={vehicle.id} />

      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14, marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
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
              {r.parts_replaced && <p style={{ fontSize: 13, color: "var(--steel)" }}>Part diganti (catatan bebas): {r.parts_replaced}</p>}
              {r.notes && <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 4 }}>{r.notes}</p>}
              <PartUsageDisplay record={r} />

              <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                {r.invoice_id ? (
                  <Link href={`/dashboard/invoice-detail?id=${r.invoice_id}`} className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Receipt size={13} /> Lihat Invoice
                  </Link>
                ) : (
                  <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} onClick={() => setInvoicingRecord(r)}>
                    <FileText size={13} /> Buat Invoice
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {invoicingRecord && (
        <CreateInvoiceModal
          record={invoicingRecord}
          onClose={() => setInvoicingRecord(null)}
          onCreated={(invoiceId) => router.push(`/dashboard/invoice-detail?id=${invoiceId}`)}
        />
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
