"use client";
// =============================================================================
// === frontend/app/dashboard/estimate-detail/page.tsx ===
// Same query-param pattern as vehicle-detail/work-order-detail —
// static export needs every route's HTML identical regardless of
// ?id= value, since real estimate UUIDs don't exist at build time.
// =============================================================================
import {
  Estimate, EstimateLineKind, EstimateRejectionReason, estimateLineItemsApi, estimatesApi,
} from "@/lib/api/estimates";
import { Part, partsApi } from "@/lib/api/service";
import { ArrowLeft, Loader2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const STATUS_LABEL: Record<string, string> = {
  PENDING: "Menunggu Persetujuan", APPROVED: "Disetujui", REJECTED: "Ditolak",
};
const STATUS_COLOR: Record<string, string> = {
  PENDING: "var(--rust)", APPROVED: "#2e7d4f", REJECTED: "var(--danger)",
};
const REASON_LABEL: Record<string, string> = {
  TOO_EXPENSIVE: "Harga Terlalu Mahal", WENT_ELSEWHERE: "Pilih Bengkel Lain",
  POSTPONED: "Ditunda Dulu", NOT_NEEDED: "Diputuskan Tidak Perlu", OTHER: "Lainnya",
};

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

function DiagnosisCard({ estimate, onUpdated }: { estimate: Estimate; onUpdated: () => void }) {
  const editable = estimate.status === "PENDING";
  const [notes, setNotes] = useState(estimate.diagnosis_notes);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await estimatesApi.updateNotes(estimate.id, notes);
      onUpdated();
    } finally {
      setSaving(false);
    }
  };

  if (!editable) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>Catatan Diagnosa</div>
        <p style={{ fontSize: 14 }}>{estimate.diagnosis_notes || "—"}</p>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>Catatan Diagnosa</div>
      <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} style={{ marginBottom: 10 }} />
      <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={handleSave} disabled={saving}>
        {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
      </button>
    </div>
  );
}

function LineItemsSection({ estimate, catalog, onUpdated }: { estimate: Estimate; catalog: Part[]; onUpdated: () => void }) {
  const editable = estimate.status === "PENDING";
  const [kind, setKind] = useState<EstimateLineKind>("labor");
  const [description, setDescription] = useState("");
  const [partId, setPartId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unitPrice, setUnitPrice] = useState("");
  const [saving, setSaving] = useState(false);

  const addLine = async () => {
    if (kind === "labor" && (!description || !unitPrice)) return;
    if (kind === "part" && (!partId || !unitPrice)) return;
    setSaving(true);
    try {
      await estimateLineItemsApi.create(estimate.id, {
        kind, description: kind === "part" ? (catalog.find((p) => p.id === partId)?.name ?? description) : description,
        quantity: Number(quantity) || 1, unit_price: Number(unitPrice), part: kind === "part" ? partId : undefined,
      });
      setDescription(""); setPartId(""); setQuantity("1"); setUnitPrice("");
      onUpdated();
    } finally {
      setSaving(false);
    }
  };

  const removeLine = async (id: string) => {
    await estimateLineItemsApi.remove(id);
    onUpdated();
  };

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Item Estimasi</h3>
      {estimate.line_items.length === 0 && <p style={{ color: "var(--steel)", fontSize: 13.5, marginBottom: 12 }}>Belum ada item.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: editable ? 16 : 0 }}>
        {estimate.line_items.map((li) => (
          <div key={li.id} className="mono" style={{ fontSize: 13, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{li.description} × {li.quantity}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {money(li.subtotal)}
              {editable && (
                <button onClick={() => removeLine(li.id)} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}>
                  <Trash2 size={14} />
                </button>
              )}
            </span>
          </div>
        ))}
      </div>

      {editable && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select className="input" style={{ width: 90 }} value={kind} onChange={(e) => setKind(e.target.value as EstimateLineKind)}>
            <option value="labor">Jasa</option>
            <option value="part">Part</option>
          </select>
          {kind === "part" ? (
            <select className="input" style={{ flex: 1, minWidth: 160 }} value={partId} onChange={(e) => setPartId(e.target.value)}>
              <option value="">— Pilih Part —</option>
              {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.current_stock} {p.unit})</option>)}
            </select>
          ) : (
            <input className="input" style={{ flex: 1, minWidth: 160 }} placeholder="Deskripsi jasa" value={description} onChange={(e) => setDescription(e.target.value)} />
          )}
          <input className="input" style={{ width: 60 }} type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          <input className="input" style={{ width: 110 }} type="number" min={0} placeholder="Harga" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} />
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={addLine} disabled={saving}>
            <Plus size={13} /> Tambah
          </button>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
        <span style={{ fontSize: 15, fontWeight: 700 }}>Total: <span className="mono">{money(estimate.total)}</span></span>
      </div>
    </div>
  );
}

function EstimateDetailContent() {
  const searchParams = useSearchParams();
  const estimateId = searchParams.get("id") ?? "";
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [catalog, setCatalog] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<EstimateRejectionReason>("TOO_EXPENSIVE");
  const [rejectNotes, setRejectNotes] = useState("");
  const [rejecting, setRejecting] = useState(false);

  const load = () => estimatesApi.get(estimateId).then(setEstimate).finally(() => setLoading(false));
  useEffect(() => { if (estimateId) load(); }, [estimateId]);
  useEffect(() => { partsApi.list().then(setCatalog); }, []);

  const handleApprove = async () => {
    // A Rp 0 estimate is a legitimate edge case (e.g. testing, or a
    // genuinely free courtesy check) but far more often it means
    // someone moving fast approved before actually filling in line
    // items — worth one honest pause before committing to it, same
    // reasoning as the material-line-deletion reason prompt.
    if (Number(estimate?.total ?? 0) === 0) {
      const proceed = window.confirm("Estimasi ini belum punya item — lanjutkan?");
      if (!proceed) return;
    }
    setBusy(true); setError(null);
    try {
      await estimatesApi.approve(estimateId);
      load();
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(apiMessage || "Gagal menyetujui estimasi.");
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    setBusy(true); setError(null);
    try {
      await estimatesApi.reject(estimateId, rejectReason, rejectNotes);
      setRejecting(false);
      load();
    } catch {
      setError("Gagal menolak estimasi.");
    } finally {
      setBusy(false);
    }
  };

  if (!estimateId) {
    return <div style={{ color: "var(--danger)" }}>Estimasi tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !estimate) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      <Link href={`/dashboard/vehicle-detail?id=${estimate.vehicle}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Kendaraan
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <span className="mono" style={{ fontSize: 22, fontWeight: 700, background: "var(--ink)", color: "var(--paper)", padding: "5px 12px", borderRadius: 5, display: "inline-block" }}>
          EST #{estimate.number}
        </span>
        <span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 12px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[estimate.status] }}>
          {STATUS_LABEL[estimate.status]}
        </span>
      </div>

      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 20 }}>
        {estimate.vehicle_plate} · {estimate.customer_name}
      </p>

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <DiagnosisCard estimate={estimate} onUpdated={load} />
      <LineItemsSection estimate={estimate} catalog={catalog} onUpdated={load} />

      {estimate.status === "APPROVED" && estimate.work_order && (
        <div className="card" style={{ textAlign: "center", padding: 24 }}>
          <p style={{ fontSize: 14, marginBottom: 10 }}>Estimasi disetujui — work order telah dibuat.</p>
          <Link href={`/dashboard/work-order-detail?id=${estimate.work_order}`} className="btn-rust" style={{ display: "inline-flex" }}>
            Lihat Work Order
          </Link>
        </div>
      )}

      {estimate.status === "REJECTED" && (
        <div className="card" style={{ padding: 20 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Alasan Penolakan</div>
          <p style={{ fontSize: 14, marginBottom: estimate.rejection_notes ? 6 : 0 }}>{REASON_LABEL[estimate.rejection_reason] ?? estimate.rejection_reason}</p>
          {estimate.rejection_notes && <p style={{ fontSize: 13, color: "var(--steel)" }}>{estimate.rejection_notes}</p>}
        </div>
      )}

      {estimate.status === "PENDING" && !rejecting && (
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-rust" disabled={busy} onClick={handleApprove}>Setujui Estimasi</button>
          <button className="btn-ghost" disabled={busy} onClick={() => setRejecting(true)}>Tolak</button>
        </div>
      )}

      {estimate.status === "PENDING" && rejecting && (
        <div className="card" style={{ padding: 20 }}>
          <div style={{ marginBottom: 12 }}>
            <label className="label">Alasan Penolakan</label>
            <select className="input" value={rejectReason} onChange={(e) => setRejectReason(e.target.value as EstimateRejectionReason)}>
              {Object.entries(REASON_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: 16 }}>
            <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={rejectNotes} onChange={(e) => setRejectNotes(e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-rust" disabled={busy} onClick={handleReject}>Konfirmasi Penolakan</button>
            <button className="btn-ghost" disabled={busy} onClick={() => setRejecting(false)}>Batal</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function EstimateDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <EstimateDetailContent />
    </Suspense>
  );
}
