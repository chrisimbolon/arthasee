"use client";
// =============================================================================
// === frontend/app/dashboard/work-order-detail/page.tsx ===
// Same query-param pattern as vehicle-detail/invoice-detail — static
// export needs every route's HTML identical regardless of ?id= value.
// =============================================================================
import { Part, partsApi } from "@/lib/api/service";
import {
  WorkOrder, WorkOrderStatus, workOrderJobLinesApi, workOrderMaterialLinesApi, workOrdersApi,
} from "@/lib/api/workorders";
import { AlertTriangle, ArrowLeft, Check, Loader2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const STATUS_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: "Terbuka", IN_PROGRESS: "Dikerjakan", QC: "Pemeriksaan Kualitas", DONE: "Selesai", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<WorkOrderStatus, string> = {
  OPEN: "var(--steel)", IN_PROGRESS: "var(--rust)", QC: "#b5860b", DONE: "#2e7d4f", CANCELLED: "var(--danger)",
};
const OPEN_STATUSES: WorkOrderStatus[] = ["OPEN", "IN_PROGRESS", "QC"];

function IntakeCard({ wo, onUpdated }: { wo: WorkOrder; onUpdated: () => void }) {
  const editable = OPEN_STATUSES.includes(wo.status);
  const [form, setForm] = useState({
    odometer_km_intake: wo.odometer_km_intake?.toString() ?? "",
    received_by: wo.received_by,
    notes: wo.notes,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true); setError(null);
    try {
      await workOrdersApi.update(wo.id, {
        odometer_km_intake: form.odometer_km_intake ? Number(form.odometer_km_intake) : undefined,
        received_by: form.received_by,
        notes: form.notes,
      });
      onUpdated();
    } catch {
      setError("Gagal menyimpan detail intake.");
    } finally {
      setSaving(false);
    }
  };

  if (!editable) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 10 }}>Detail Intake</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          <div><div style={{ fontSize: 11.5, color: "var(--steel)" }}>KM Saat Masuk</div><div className="mono">{wo.odometer_km_intake ?? "—"}</div></div>
          <div><div style={{ fontSize: 11.5, color: "var(--steel)" }}>Diterima Oleh</div><div>{wo.received_by || "—"}</div></div>
          <div><div style={{ fontSize: 11.5, color: "var(--steel)" }}>Catatan</div><div>{wo.notes || "—"}</div></div>
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 10 }}>Detail Intake</div>
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <label className="label">KM Saat Masuk</label>
          <input className="input" type="number" min={0} value={form.odometer_km_intake} onChange={(e) => setForm({ ...form, odometer_km_intake: e.target.value })} />
        </div>
        <div>
          <label className="label">Diterima Oleh</label>
          <input className="input" value={form.received_by} onChange={(e) => setForm({ ...form, received_by: e.target.value })} placeholder="Nama staf" />
        </div>
      </div>
      <div style={{ marginBottom: 14 }}>
        <label className="label">Catatan</label>
        <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={handleSave} disabled={saving}>
        {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
      </button>
    </div>
  );
}

function JobLinesSection({ wo, onUpdated }: { wo: WorkOrder; onUpdated: () => void }) {
  const editable = OPEN_STATUSES.includes(wo.status);
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);

  const addLine = async () => {
    if (!desc.trim()) return;
    setSaving(true);
    try {
      await workOrderJobLinesApi.create(wo.id, desc.trim());
      setDesc("");
      onUpdated();
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (lineId: string) => {
    await workOrderJobLinesApi.toggle(lineId);
    onUpdated();
  };

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Pekerjaan</h3>
      {wo.job_lines.length === 0 && <p style={{ color: "var(--steel)", fontSize: 13.5, marginBottom: 12 }}>Belum ada item pekerjaan.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: editable ? 14 : 0 }}>
        {wo.job_lines.map((line) => (
          <div key={line.id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              onClick={() => editable && toggle(line.id)}
              disabled={!editable}
              style={{
                width: 20, height: 20, borderRadius: 5, border: "1px solid var(--line)",
                background: line.is_done ? "var(--rust)" : "transparent",
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                cursor: editable ? "pointer" : "default",
              }}
            >
              {line.is_done && <Check size={13} color="#fff" />}
            </button>
            <span style={{ fontSize: 14, textDecoration: line.is_done ? "line-through" : "none", color: line.is_done ? "var(--steel)" : undefined }}>
              {line.description}
            </span>
          </div>
        ))}
      </div>
      {editable && (
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" style={{ flex: 1 }} placeholder="Deskripsi pekerjaan" value={desc} onChange={(e) => setDesc(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addLine()} />
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={addLine} disabled={saving}>
            <Plus size={13} /> Tambah
          </button>
        </div>
      )}
    </div>
  );
}

function MaterialLinesSection({ wo, catalog, onUpdated }: { wo: WorkOrder; catalog: Part[]; onUpdated: () => void }) {
  const editable = OPEN_STATUSES.includes(wo.status);
  const [partId, setPartId] = useState("");
  const [qty, setQty]       = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const addLine = async () => {
    if (!partId || !qty) return;
    setSaving(true); setError(null);
    try {
      await workOrderMaterialLinesApi.create(wo.id, { part: partId, quantity: Number(qty) });
      setPartId(""); setQty("");
      onUpdated();
    } catch {
      setError("Gagal menambahkan material — periksa ketersediaan stok.");
    } finally {
      setSaving(false);
    }
  };

  const removeLine = async (lineId: string) => {
    await workOrderMaterialLinesApi.remove(lineId);
    onUpdated();
  };

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Material</h3>
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
      {wo.material_lines.length === 0 && <p style={{ color: "var(--steel)", fontSize: 13.5, marginBottom: 12 }}>Belum ada material digunakan.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: editable ? 14 : 0 }}>
        {wo.material_lines.map((line) => (
          <div key={line.id} className="mono" style={{ fontSize: 13, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{line.part_name} × {line.quantity} {line.unit}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              Rp {Number(line.subtotal).toLocaleString("id-ID")}
              {editable && (
                <button onClick={() => removeLine(line.id)} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}>
                  <Trash2 size={14} />
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
      {editable && (
        <div style={{ display: "flex", gap: 8 }}>
          <select className="input" style={{ flex: 1 }} value={partId} onChange={(e) => setPartId(e.target.value)}>
            <option value="">— Pilih Part —</option>
            {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.current_stock} {p.unit})</option>)}
          </select>
          <input className="input" style={{ width: 90 }} type="number" min={0} step="0.01" placeholder="Jml" value={qty} onChange={(e) => setQty(e.target.value)} />
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={addLine} disabled={saving}>
            <Plus size={13} /> Tambah
          </button>
        </div>
      )}
    </div>
  );
}

function WorkOrderDetailContent() {
  const searchParams = useSearchParams();
  const workOrderId = searchParams.get("id") ?? "";
  const [wo, setWo] = useState<WorkOrder | null>(null);
  const [catalog, setCatalog] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => workOrdersApi.get(workOrderId).then(setWo).finally(() => setLoading(false));
  useEffect(() => { if (workOrderId) load(); }, [workOrderId]);
  useEffect(() => { partsApi.list().then(setCatalog); }, []);

  const advanceStatus = async (status: "IN_PROGRESS" | "QC") => {
    setBusy(true); setError(null);
    try {
      await workOrdersApi.updateStatus(workOrderId, status);
      load();
    } catch {
      setError("Gagal mengubah status.");
    } finally {
      setBusy(false);
    }
  };

  const handleClose = async () => {
    setBusy(true); setError(null);
    try {
      await workOrdersApi.close(workOrderId);
      load();
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(apiMessage || "Gagal menyelesaikan work order.");
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    setBusy(true); setError(null);
    try {
      await workOrdersApi.cancel(workOrderId);
      load();
    } catch {
      setError("Gagal membatalkan work order.");
    } finally {
      setBusy(false);
    }
  };

  if (!workOrderId) {
    return <div style={{ color: "var(--danger)" }}>Work order tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !wo) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      <Link href={`/dashboard/vehicle-detail?id=${wo.vehicle}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Kendaraan
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <span className="mono" style={{ fontSize: 22, fontWeight: 700, background: "var(--ink)", color: "var(--paper)", padding: "5px 12px", borderRadius: 5, display: "inline-block" }}>
            WO #{wo.number}
          </span>
        </div>
        <span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 12px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[wo.status] }}>
          {STATUS_LABEL[wo.status]}
        </span>
      </div>

      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 20 }}>
        {wo.vehicle_plate} · {wo.customer_name}
      </p>

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <IntakeCard wo={wo} onUpdated={load} />
      <JobLinesSection wo={wo} onUpdated={load} />
      <MaterialLinesSection wo={wo} catalog={catalog} onUpdated={load} />

      {wo.status === "DONE" && (
        <div className="card" style={{ textAlign: "center", padding: 24 }}>
          <p style={{ fontSize: 14, marginBottom: 10 }}>Work order selesai — catatan servis telah dibuat.</p>
          <Link href={`/dashboard/vehicle-detail?id=${wo.vehicle}`} className="btn-rust" style={{ display: "inline-flex" }}>
            Lihat Riwayat Servis
          </Link>
        </div>
      )}

      {wo.status === "CANCELLED" && (
        <div className="card" style={{ textAlign: "center", padding: 24, color: "var(--steel)" }}>
          <AlertTriangle size={20} style={{ marginBottom: 8 }} />
          <p style={{ fontSize: 14 }}>Work order ini telah dibatalkan. Stok yang terpakai sudah dikembalikan.</p>
        </div>
      )}

      {OPEN_STATUSES.includes(wo.status) && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {wo.status === "OPEN" && (
            <button className="btn-rust" disabled={busy} onClick={() => advanceStatus("IN_PROGRESS")}>Mulai Dikerjakan</button>
          )}
          {wo.status === "IN_PROGRESS" && (
            <button className="btn-rust" disabled={busy} onClick={() => advanceStatus("QC")}>Ajukan Pemeriksaan</button>
          )}
          <button className="btn-rust" disabled={busy} onClick={handleClose}>Selesaikan Work Order</button>
          <button className="btn-ghost" disabled={busy} onClick={handleCancel}>Batalkan</button>
        </div>
      )}
    </div>
  );
}

export default function WorkOrderDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <WorkOrderDetailContent />
    </Suspense>
  );
}
