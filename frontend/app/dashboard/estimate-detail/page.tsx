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
//     (OPEN/IN_PROGRESS/QC).
//
// SECOND ROUND — Sansan's remaining point, now resolved: a completed
// WorkOrder used to still render as its own separate card behind a
// history toggle in the Work Order section, disconnected from the
// ServiceRecord it produced sitting in Riwayat Servis below — "two
// disconnected sections" for one real job, exactly what he flagged.
// Per PROJECT_STATE, WorkOrder and ServiceRecord stay two genuinely
// separate models (deliberate, confirmed with Made) — so the fix is
// a read-only link, not a data-model merge:
//   - DONE WorkOrders are no longer shown in WorkOrdersSection at
//     all — a done order's real, final form is the ServiceRecord it
//     promoted into, which already has its own card below.
//   - Every Riwayat Servis card now shows a small "WO #N" link
//     (ServiceRecord.work_order_number) back to the WorkOrder that
//     produced it, when one exists — one entry, one link, not two
//     unrelated cards.
//   - WorkOrdersSection's history toggle is now CANCELLED-only.
//     Cancelled orders genuinely have nowhere else to live —
//     WorkOrder.cancel() never creates a ServiceRecord, only
//     close() does — so they'd vanish from view entirely if treated
//     the same as DONE. They stay real, visible history, just in
//     their own small section rather than implying they became a
//     real visit.
// =============================================================================
import { EstimateStatus, EstimateSummary, estimatesApi } from "@/lib/api/estimates";
import { LaborLinePayload, invoicesApi } from "@/lib/api/invoicing";
import { ServiceRecord, Vehicle, vehiclesApi } from "@/lib/api/service";
import { WorkOrderStatus, WorkOrderSummary, workOrdersApi } from "@/lib/api/workorders";
import { formatDateID } from "@/lib/format";
import { AlertTriangle, ArrowLeft, Calendar, ClipboardList, FileSearch, FileText, Loader2, Plus, Receipt, Trash2, Wrench } from "lucide-react";
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
          {formatDateID(record.service_date)} — {record.issue_description.split("\n").filter((line) => line.trim() !== "").join(", ")}
        </p>

        {record.original_estimate_total && (
          <div style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 6, padding: "8px 12px", marginBottom: 16, fontSize: 13 }}>
            Awalnya diestimasi: <span className="mono" style={{ fontWeight: 600 }}>Rp {Number(record.original_estimate_total).toLocaleString("id-ID")}</span>
            <span style={{ color: "var(--steel)" }}> — hanya referensi, pekerjaan bisa berubah selama perbaikan.</span>
          </div>
        )}

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
  // Muted slate-blue, not var(--steel) — "Terbuka" was previously
  // indistinguishable from ordinary muted text since it shared the
  // exact same neutral gray. Deliberately kept lower-hierarchy than
  // var(--rust) (the CTA color) — informational, not competing for
  // attention with "Buat Estimasi"/"Buat Work Order".
  OPEN: "#4a6d94", IN_PROGRESS: "var(--rust)", QC: "#b5860b", DONE: "#2e7d4f", CANCELLED: "var(--danger)",
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

  // DONE orders are deliberately excluded here entirely, not just
  // hidden behind the toggle — a completed order's real, final form
  // is the ServiceRecord it promoted into via close(), which already
  // renders below in Riwayat Servis with its own "WO #N" link back
  // to this order. Showing it again here would be exactly the "two
  // disconnected sections for one job" Sansan flagged.
  const relevantOrders = orders.filter((wo) => wo.status !== "DONE");
  const activeOrders    = relevantOrders.filter((wo) => WO_OPEN_STATUSES.includes(wo.status));
  const cancelledOrders = relevantOrders.filter((wo) => wo.status === "CANCELLED");
  // CANCELLED-only history, not "everything non-active" — a
  // cancelled order genuinely has nowhere else to live (cancel()
  // never creates a ServiceRecord, only close() does), so it stays
  // real, visible history here rather than vanishing from the page.
  const visibleOrders = showHistory ? relevantOrders : activeOrders;

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
          {showHistory ? "Belum ada work order yang dibatalkan." : "Tidak ada work order aktif saat ini."}
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

      {cancelledOrders.length > 0 && (
        <button
          className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", marginTop: 10 }}
          onClick={() => setShowHistory((v) => !v)}
        >
          {showHistory ? "Sembunyikan Riwayat Dibatalkan" : `Lihat Riwayat Dibatalkan (${cancelledOrders.length})`}
        </button>
      )}
    </div>
  );
}

const EST_STATUS_LABEL: Record<EstimateStatus, string> = {
  PENDING: "Menunggu Persetujuan", APPROVED: "Disetujui", REJECTED: "Ditolak",
};
const EST_STATUS_COLOR: Record<EstimateStatus, string> = {
  PENDING: "var(--rust)", APPROVED: "#2e7d4f", REJECTED: "var(--danger)",
};

function EstimatesSection({ vehicleId }: { vehicleId: string }) {
  const router = useRouter();
  const [estimates, setEstimates] = useState<EstimateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const load = () => estimatesApi.list(vehicleId).then(setEstimates).finally(() => setLoading(false));
  useEffect(() => { load(); }, [vehicleId]);

  const createDraft = async () => {
    setCreating(true);
    try {
      const est = await estimatesApi.create(vehicleId);
      router.push(`/dashboard/estimate-detail?id=${est.id}`);
    } finally {
      setCreating(false);
    }
  };

  const pending = estimates.filter((e) => e.status === "PENDING");
  const history = estimates.filter((e) => e.status !== "PENDING");
  const visible = showHistory ? estimates : pending;

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <FileSearch size={16} /> Estimasi
        </h2>
        <button className="btn-rust" onClick={createDraft} disabled={creating}>
          {creating ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <><Plus size={16} /> Buat Estimasi</>}
        </button>
      </div>

      {loading ? (
        <div style={{ color: "var(--steel)", fontSize: 13.5 }}><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : visible.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 24, fontSize: 13.5 }}>
          {showHistory ? "Belum ada estimasi untuk kendaraan ini." : "Tidak ada estimasi yang menunggu persetujuan."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {visible.map((est) => (
            <Link key={est.id} href={`/dashboard/estimate-detail?id=${est.id}`} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px" }}>
              <span className="mono" style={{ fontSize: 13.5, fontWeight: 600 }}>EST #{est.number}</span>
              <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: EST_STATUS_COLOR[est.status] }}>
                {EST_STATUS_LABEL[est.status]}
              </span>
            </Link>
          ))}
        </div>
      )}

      {history.length > 0 && (
        <button
          className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", marginTop: 10 }}
          onClick={() => setShowHistory((v) => !v)}
        >
          {showHistory ? "Sembunyikan Riwayat Estimasi" : `Lihat Riwayat Estimasi (${history.length})`}
        </button>
      )}
    </div>
  );
}


// ── Vehicle Timeline ──────────────────────────────────────────────
// Sansan's "Digital Medical Record" mockup, built against what's
// already real: work_order_number/invoice_id/invoice_total all trace
// through existing reverse OneToOne relations, nothing new to
// validate with Made here — this is a restyle plus one new backend
// field (invoice_total), not a new data model.
//
// UpcomingServiceEntry is deliberately its own isolated component,
// not inline logic — the explicit reason: KM stays the sole trigger
// for the badge/color, by design (see the conversation that led
// here). If date-based prediction ever gets added later, it only
// ever appears as a second, clearly-labeled line inside THIS
// component — nothing else in the timeline needs to change.

function TimelineDot({ color, isLast, pulse }: { color: string; isLast: boolean; pulse?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 24, flexShrink: 0 }}>
      <div
        style={{
          width: 12, height: 12, borderRadius: "50%", background: color,
          border: "2px solid var(--paper)", boxShadow: "0 0 0 1px var(--line)",
          flexShrink: 0, marginTop: 4,
          animation: pulse ? "timeline-pulse 1.8s ease-in-out infinite" : undefined,
        }}
      />
      {!isLast && <div style={{ flex: 1, width: 2, background: "var(--line)", marginTop: 2, minHeight: 24 }} />}
    </div>
  );
}

function UpcomingServiceEntry({ vehicle, isLast }: { vehicle: Vehicle; isLast: boolean }) {
  const due = vehicle.is_due_for_service;
  const kmRemaining = vehicle.last_service_odometer_km != null
    ? Math.max(0, (vehicle.last_service_odometer_km + 5000) - vehicle.current_odometer_km)
    : null;

  return (
    <div style={{ display: "flex", gap: 12 }}>
      <TimelineDot color={due ? "var(--rust)" : "var(--hazard)"} isLast={isLast} pulse={due} />
      <div style={{ flex: 1, paddingBottom: 16 }}>
        <div className="card" style={{ background: "var(--paper-3)", border: `1.5px dashed ${due ? "var(--rust)" : "var(--steel-lt)"}` }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 4 }}>
            Servis Berikutnya
          </div>
          {vehicle.last_service_odometer_km == null ? (
            <p style={{ fontSize: 13.5, color: "var(--steel)" }}>Belum ada data servis untuk memperkirakan jadwal berikutnya.</p>
          ) : due ? (
            <p style={{ fontSize: 14, fontWeight: 600, color: "var(--rust)" }}>
              Sudah waktunya servis — <span className="mono">{(vehicle.current_odometer_km - vehicle.last_service_odometer_km).toLocaleString("id-ID")} km</span> sejak servis terakhir.
            </p>
          ) : (
            <p style={{ fontSize: 14 }}>
              Sekitar <span className="mono" style={{ fontWeight: 600 }}>{kmRemaining?.toLocaleString("id-ID")} km</span> lagi (setiap 5.000 km).
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function TimelineEntry({ record, isLast, onInvoice }: { record: ServiceRecord; isLast: boolean; onInvoice: (r: ServiceRecord) => void }) {
  const dotColor = record.invoice_id ? "#2e7d4f" : "var(--steel-lt)";

  return (
    <div style={{ display: "flex", gap: 12 }}>
      <TimelineDot color={dotColor} isLast={isLast} />
      <div style={{ flex: 1, paddingBottom: 16 }}>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{formatDateID(record.service_date)}</span>
              {/* The actual fix for Sansan's "two disconnected
                  sections" review: when this record came from a
                  WorkOrder, link straight back to it here instead
                  of it also showing up as its own separate card
                  in the Work Order section above. One entry, one
                  link — not two unrelated cards for the same job. */}
              {record.work_order_number && (
                <Link
                  href={`/dashboard/work-order-detail?id=${record.work_order_id}`}
                  className="btn-ghost"
                  style={{ fontSize: 11, padding: "2px 8px", display: "inline-flex", alignItems: "center", gap: 4 }}
                >
                  <ClipboardList size={11} /> WO #{record.work_order_number}
                </Link>
              )}
            </div>
            <span className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{record.odometer_km.toLocaleString("id-ID")} km</span>
          </div>
          {/* issue_description joins multiple job lines with \n
              (see WorkOrder.close()) — a plain <p> silently collapses
              those into one run-on line in HTML, invisible with a
              single job line but genuinely unreadable with several.
              Splitting and rendering each as its own line here fixes
              that without needing any backend change — the \n was
              always there, this just stops discarding it. */}
          {record.issue_description
            .split("\n")
            .filter((line) => line.trim() !== "")
            .map((line, idx, arr) => (
              <p
                key={idx}
                style={{
                  fontSize: 14, margin: 0,
                  marginBottom: idx < arr.length - 1 ? 3 : (record.parts_replaced ? 6 : 0),
                }}
              >
                {line}
              </p>
            ))}
          {record.parts_replaced && <p style={{ fontSize: 13, color: "var(--steel)" }}>Part diganti (catatan bebas): {record.parts_replaced}</p>}
          {record.notes && <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 4 }}>{record.notes}</p>}
          <PartUsageDisplay record={record} />

          <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            {record.invoice_id ? (
              <Link href={`/dashboard/invoice-detail?id=${record.invoice_id}`} className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Receipt size={13} /> Lihat Invoice
              </Link>
            ) : (
              <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} onClick={() => onInvoice(record)}>
                <FileText size={13} /> Buat Invoice
              </button>
            )}
            {record.invoice_total != null && (
              <span className="mono" style={{ fontSize: 14, fontWeight: 600 }}>
                Rp {Number(record.invoice_total).toLocaleString("id-ID")}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function VehicleTimeline({ vehicle, onInvoice }: { vehicle: Vehicle; onInvoice: (r: ServiceRecord) => void }) {
  const records = vehicle.service_records ?? [];

  return (
    <div>
      <style>{`
        @keyframes timeline-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
      <UpcomingServiceEntry vehicle={vehicle} isLast={records.length === 0} />
      {records.length === 0 ? (
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ width: 24, flexShrink: 0 }} />
          <div className="card" style={{ flex: 1, textAlign: "center", color: "var(--steel)", padding: 32 }}>
            Belum ada riwayat servis untuk kendaraan ini.
          </div>
        </div>
      ) : (
        records.map((r, idx) => (
          <TimelineEntry key={r.id} record={r} isLast={idx === records.length - 1} onInvoice={onInvoice} />
        ))
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
    { label: "Jenis/Model", value: vehicle.body_style },
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
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{formatDateID(vehicle.last_service_date)}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>STNK Berlaku Sampai</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: vehicle.is_registration_expiring_soon ? "var(--danger)" : undefined }}>
            {formatDateID(vehicle.registration_expiry)}
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

      <EstimatesSection vehicleId={vehicle.id} />
      <WorkOrdersSection vehicleId={vehicle.id} />

      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14, marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
        <Wrench size={16} /> Riwayat Servis
      </h2>

      <VehicleTimeline vehicle={vehicle} onInvoice={setInvoicingRecord} />

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
