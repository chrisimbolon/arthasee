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
import { organizationsApi } from "@/lib/api/organizations";
import { Part, partsApi } from "@/lib/api/service";
import { ArrowLeft, Download, Loader2, Plus, Printer, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

// Shared handle for any small editable card on this page (KM Saat
// Masuk, Catatan dan Analisa) that has its own local "Simpan"
// button. Chris's own explicit ask, 1 Aug QA: SA shouldn't have to
// remember to click every small Simpan button before Setujui
// Estimasi — the page itself flushes any real unsaved edit right
// before approving. A genuine save failure (e.g. the odometer's own
// hard-block validation) throws, so the caller can abort the
// approval instead of silently discarding the value or approving
// past a real validation error.
interface FieldCardHandle {
  flush: () => Promise<void>;
}

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

// Made's own real, sketched structural input, 30 Jul follow-up
// meeting: a real quotation document reads as two clearly separate
// sections — Parts and Jasa (labor) — each with its own subtotal,
// both rolling into one final total. Deliberately NOT restructuring
// LineItemsSection's own flat, interactive editing list below to
// match this — that's the working, already-tested day-to-day
// editing interface, and this print document is a new, additional
// view built on top of the exact same underlying line_items, not a
// replacement for how they get edited.
function QuotationLineTable({ title, items }: { title: string; items: Estimate["line_items"] }) {
  const total = items.reduce((sum, li) => sum + Number(li.subtotal), 0);
  return (
    <div style={{ marginBottom: 22 }}>
      <h3 style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 10, textTransform: "uppercase", color: "var(--steel)" }}>
        {title}
      </h3>
      <table className="data-table" style={{ width: "100%", marginBottom: 8 }}>
        <thead>
          <tr>
            <th>Deskripsi</th>
            <th style={{ textAlign: "right" }}>Jml</th>
            <th style={{ textAlign: "right" }}>Harga Satuan</th>
            <th style={{ textAlign: "right" }}>Subtotal</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr><td colSpan={4} style={{ textAlign: "center", padding: 14, color: "var(--steel)" }}>Belum ada item.</td></tr>
          ) : items.map((li) => (
            <tr key={li.id}>
              <td>{li.description}</td>
              <td className="mono" style={{ textAlign: "right" }}>{li.quantity}</td>
              <td className="mono" style={{ textAlign: "right" }}>{money(li.unit_price)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{money(li.subtotal)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", justifyContent: "flex-end", fontSize: 13.5 }}>
        <span style={{ color: "var(--steel)", marginRight: 10 }}>Total {title}</span>
        <span className="mono" style={{ fontWeight: 600 }}>{money(total)}</span>
      </div>
    </div>
  );
}

function PrintableQuotation({ estimate, orgName }: { estimate: Estimate; orgName: string | null }) {
  const partItems = estimate.line_items.filter((li) => li.kind === "part");
  const laborItems = estimate.line_items.filter((li) => li.kind === "labor");

  return (
    <div className="card" style={{ maxWidth: 720, margin: "0 auto 20px", padding: 40 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
        <div>
          <div className="display" style={{ fontSize: 22 }}>{orgName || "Arthasee"}</div>
          <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 4 }}>QUOTATION / ESTIMASI</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>EST #{estimate.number}</div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>
            {new Date(estimate.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" })}
          </div>
          <span style={{ display: "inline-block", marginTop: 8, fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[estimate.status] }}>
            {STATUS_LABEL[estimate.status]}
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24, paddingBottom: 20, borderBottom: "1px solid var(--line)" }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Pelanggan</div>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{estimate.customer_name}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Nomor Plat</div>
          <div className="mono" style={{ fontSize: 15, fontWeight: 600 }}>{estimate.vehicle_plate}</div>
        </div>
      </div>

      {estimate.diagnosis_notes && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Catatan dan Analisa</div>
          {/* Bug caught in 1 Aug QA: a textarea holding two real
              lines ("Tenaga kurang" / "Asap tebal") was printing as
              one run-on sentence with no separator at all — the
              browser collapses \n by default unless told otherwise.
              whiteSpace: "pre-line" preserves real line breaks while
              still collapsing repeated spaces, same as any normal
              paragraph — the correct middle ground vs. "pre", which
              would also preserve accidental extra whitespace. */}
          <p style={{ fontSize: 13.5, whiteSpace: "pre-line" }}>{estimate.diagnosis_notes}</p>
        </div>
      )}

      <QuotationLineTable title="Parts" items={partItems} />
      <QuotationLineTable title="Jasa" items={laborItems} />

      {/* estimate.total, not partsTotal + laborTotal recomputed here
          — the API's own server-computed figure is the authoritative
          source, same discipline as invoice-detail trusting
          invoice.subtotal/balance_due directly rather than
          recalculating client-side. */}
      <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 14, borderTop: "1px solid var(--line)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", width: 260, fontSize: 17, fontWeight: 700 }}>
          <span>Total</span>
          <span className="mono">{money(estimate.total)}</span>
        </div>
      </div>

      {estimate.created_by_name && (
        <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 32, textAlign: "right" }}>
          Dibuat oleh {estimate.created_by_name}
        </p>
      )}
    </div>
  );
}

// Chris's own framing, 31 Jul: "estimasi is like a gate" — real
// odometer capture belongs here, before any diagnosis/quote work.
// Same editable-while-PENDING / read-only-otherwise pattern as
// DiagnosisCard, kept as its own separate component rather than
// merged into it — different concern, different validation rule.
const OdometerCard = forwardRef<FieldCardHandle, { estimate: Estimate; onUpdated: () => void }>(
  function OdometerCard({ estimate, onUpdated }, ref) {
  const editable = estimate.status === "PENDING";
  const [value, setValue] = useState(estimate.odometer_km_intake?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDirty = editable && value !== "" && value !== (estimate.odometer_km_intake?.toString() ?? "");

  const handleSave = async () => {
    if (!value) return;
    setSaving(true); setError(null);
    try {
      await estimatesApi.updateOdometer(estimate.id, Number(value));
      onUpdated();
    } catch (err) {
      // Backend hard-block returns a real, specific message — surface
      // it exactly, not a generic fallback, since the whole point is
      // telling SA precisely why it was rejected.
      const apiErrors = (err as { response?: { data?: { errors?: { odometer_km_intake?: string[] } } } })?.response?.data?.errors;
      setError(apiErrors?.odometer_km_intake?.[0] ?? "Gagal menyimpan KM saat masuk.");
      throw err; // re-thrown so a flush() called from Setujui Estimasi can abort the approval, not swallow a real validation failure
    } finally {
      setSaving(false);
    }
  };

  useImperativeHandle(ref, () => ({
    flush: async () => { if (isDirty) await handleSave(); },
  }));

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>KM Terakhir Service</div>
          <div className="mono" style={{ fontSize: 16, fontWeight: 600 }}>
            {estimate.last_service_odometer_km != null ? `${estimate.last_service_odometer_km.toLocaleString("id-ID")} km` : "Belum ada riwayat"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>KM Saat Masuk</div>
          {editable ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input className="input" type="number" min={0} style={{ width: 140 }} value={value} onChange={(e) => setValue(e.target.value)} />
              <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
              </button>
            </div>
          ) : (
            <div className="mono" style={{ fontSize: 16, fontWeight: 600 }}>
              {estimate.odometer_km_intake != null ? `${estimate.odometer_km_intake.toLocaleString("id-ID")} km` : "—"}
            </div>
          )}
        </div>
      </div>
      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginTop: 12 }}>
          {error}
        </div>
      )}
    </div>
  );
});

const DiagnosisCard = forwardRef<FieldCardHandle, { estimate: Estimate; onUpdated: () => void }>(
  function DiagnosisCard({ estimate, onUpdated }, ref) {
  const editable = estimate.status === "PENDING";
  const [notes, setNotes] = useState(estimate.diagnosis_notes);
  const [saving, setSaving] = useState(false);

  const isDirty = editable && notes !== estimate.diagnosis_notes;

  const handleSave = async () => {
    setSaving(true);
    try {
      await estimatesApi.updateNotes(estimate.id, notes);
      onUpdated();
    } finally {
      setSaving(false);
    }
  };

  useImperativeHandle(ref, () => ({
    flush: async () => { if (isDirty) await handleSave(); },
  }));

  if (!editable) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 14, color: "var(--ink)", fontWeight: 700, marginBottom: 8 }}>Catatan dan Analisa</div>
        {/* Same bug, same fix, as PrintableQuotation's own Catatan
            dan Analisa above — caught separately in 1 Aug QA because
            this is a genuinely different render path (the read-only
            view shown once an estimate is APPROVED/REJECTED, not the
            printed document), not a duplicate of the earlier fix.
            whiteSpace: "pre-line" preserves real line breaks
            ("Asap tebal" / "Rem kurang kuat") while still collapsing
            accidental repeated whitespace, same reasoning as before. */}
        <p style={{ fontSize: 14, whiteSpace: "pre-line" }}>{estimate.diagnosis_notes || "—"}</p>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 14, color: "var(--ink)", fontWeight: 700, marginBottom: 8 }}>Catatan dan Analisa</div>
      <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} style={{ marginBottom: 10 }} />
      <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={handleSave} disabled={saving}>
        {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
      </button>
    </div>
  );
});

function LineItemsSection({ estimate, catalog, onUpdated }: { estimate: Estimate; catalog: Part[]; onUpdated: () => void }) {
  const editable = estimate.status === "PENDING";
  const [kind, setKind] = useState<EstimateLineKind>("labor");
  const [description, setDescription] = useState("");
  const [partId, setPartId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unitPrice, setUnitPrice] = useState("");
  const [priceFocused, setPriceFocused] = useState(false);
  const [saving, setSaving] = useState(false);

  // Real gap caught in QA: selecting a Part previously only set
  // partId — nothing ever read that part's own current price from
  // the inventory catalog, so SA had to know and manually type it
  // every time, completely disconnected from real inventory data.
  // The field stays editable after auto-fill, not disabled — a
  // genuine quoted price occasionally needs to differ from the
  // current catalog price, same "real default, still overridable"
  // pattern already used for RecordRealizationModal's own amount
  // pre-fill.
  //
  // unitPrice itself always stays clean raw digits ("120000"), never
  // a formatted display string — Part.unit_price can come back from
  // the backend as "120000.00" (a real Decimal serialization, not a
  // display value), so this rounds it to a plain integer string,
  // matching the same "money() never shows Rupiah cents" convention
  // already used everywhere else in this app.
  const handlePartChange = (id: string) => {
    setPartId(id);
    const selected = catalog.find((p) => p.id === id);
    setUnitPrice(selected ? String(Math.round(Number(selected.unit_price))) : "");
  };

  // Also clears a stale auto-filled price when switching away from
  // Part — otherwise a Jasa entry could silently inherit whatever
  // unrelated part's price was showing a moment ago.
  const handleKindChange = (newKind: EstimateLineKind) => {
    setKind(newKind);
    setPartId(""); setDescription(""); setUnitPrice("");
  };

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
          <select className="input" style={{ width: 90 }} value={kind} onChange={(e) => handleKindChange(e.target.value as EstimateLineKind)}>
            <option value="labor">Jasa</option>
            <option value="part">Part</option>
          </select>
          {kind === "part" ? (
            <select className="input" style={{ flex: 1, minWidth: 160 }} value={partId} onChange={(e) => handlePartChange(e.target.value)}>
              <option value="">— Pilih Part —</option>
              {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.current_stock} {p.unit})</option>)}
            </select>
          ) : (
            <input className="input" style={{ flex: 1, minWidth: 160 }} placeholder="Deskripsi jasa" value={description} onChange={(e) => setDescription(e.target.value)} />
          )}
          <input className="input" style={{ width: 60 }} type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          <input
            className="input" style={{ width: 120 }} type="text" inputMode="numeric" placeholder="Harga"
            // Real, controllable formatting only — deliberately not
            // type="number", whose display formatting is the
            // browser's own OS-level locale behavior, outside the
            // app's control (the exact odd "120000,00" rendering
            // caught in QA). Shows plain raw digits while actively
            // typing (avoids cursor-jump bugs that come with
            // reformatting on every keystroke), then reformats with
            // real thousands separators on blur — id-ID locale,
            // period separator, no decimals, matching money()'s own
            // convention used everywhere else in this app.
            value={priceFocused || !unitPrice ? unitPrice : Number(unitPrice).toLocaleString("id-ID")}
            onFocus={() => setPriceFocused(true)}
            onBlur={() => setPriceFocused(false)}
            onChange={(e) => setUnitPrice(e.target.value.replace(/[^0-9]/g, ""))}
          />
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
  const [orgName, setOrgName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<EstimateRejectionReason>("TOO_EXPENSIVE");
  const [rejectNotes, setRejectNotes] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const odometerRef = useRef<FieldCardHandle>(null);
  const diagnosisRef = useRef<FieldCardHandle>(null);

  const load = () => estimatesApi.get(estimateId).then(setEstimate).finally(() => setLoading(false));
  useEffect(() => { if (estimateId) load(); }, [estimateId]);
  useEffect(() => { partsApi.list().then(setCatalog); }, []);
  useEffect(() => {
    organizationsApi.mine().then((res) => { if (res) setOrgName(res.organization.name); });
  }, []);

  const handleApprove = async () => {
    // A Rp 0 estimate is a legitimate edge case (e.g. testing, or a
    // genuinely free courtesy check) but far more often it means
    // Chris's own explicit ask, 1 Aug QA: three separate small
    // "Simpan" buttons on this page (KM Saat Masuk, Catatan dan
    // Analisa) made it too easy to lose a real typed value if
    // Setujui Estimasi got clicked first, before either. Flush both
    // right here rather than trusting SA to remember every button —
    // a no-op if nothing's actually unsaved, and a genuine failure
    // (e.g. the odometer's own hard-block) aborts the approval
    // outright instead of silently discarding the value.
    setError(null);
    try {
      await odometerRef.current?.flush();
      await diagnosisRef.current?.flush();
    } catch {
      setError("Ada perubahan (KM atau catatan) yang gagal disimpan — perbaiki dulu sebelum menyetujui.");
      return;
    }

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

  // Made's own urgent ask, 30 Jul follow-up: SA/cashier need a real
  // PDF file so they can forward it themselves via their own
  // WhatsApp — deliberately not automated sending, just a download.
  // Not a plain <a href> — this API needs a bearer token in a
  // header a normal link click can't attach, same reasoning already
  // proven for the termin report's own export button.
  const handleDownloadPdf = async () => {
    setDownloadingPdf(true); setError(null);
    try {
      const blob = await estimatesApi.downloadQuotationPdf(estimateId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Estimasi_${estimate?.number ?? estimateId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Gagal mengunduh PDF.");
    } finally {
      setDownloadingPdf(false);
    }
  };

  // Made's own urgent request: a real, downloadable PDF so SA/cashier
  // can forward the quotation themselves via their own WhatsApp —
  // deliberately not the automated WhatsApp integration, which is
  // still on hold and unscoped separately. Same blob-download pattern
  // already proven for the contracts termin export: fetch through
  // the authenticated axios instance, trigger the browser download
  // manually — a plain <a href> link would silently 401 instead,
  // since this API needs a bearer token in a header a normal link
  // click has no way to attach.
  if (!estimateId) {
    return <div style={{ color: "var(--danger)" }}>Estimasi tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !estimate) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  // Same "has anything real been added yet" check already used for
  // the Rp 0 approve-confirmation below — a real Parts or Jasa line
  // is what makes this an actual document worth sending, not just
  // an empty PENDING estimate carrying a header and Rp 0 everywhere.
  const hasContent = Number(estimate.total) > 0;

  return (
    <div>
      {/* Print stylesheet — identical pattern to invoice-detail's own,
          reused deliberately rather than reinvented: hides everything
          outside the document itself (sidebar, back link, editing
          tools, status controls) when actually printed/exported to
          PDF via the browser. */}
      <style>{`
        @media print {
          .no-print { display: none !important; }
          aside { display: none !important; }
          body, main { margin: 0 !important; padding: 0 !important; }
        }
      `}</style>

      <div className="no-print" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <Link href={`/dashboard/vehicle-detail?id=${estimate.vehicle}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)" }}>
          <ArrowLeft size={14} /> Kembali ke Kendaraan
        </Link>
        <div style={{ display: "flex", gap: 8 }}>
          {/* Chris's own explicit call, 1 Aug QA: a Rp 0 estimate
              with no real Parts/Jasa lines has nothing to actually
              communicate — downloading/printing it produces a blank
              shell, and it's too easy for SA to click either button
              on a fresh estimate before adding anything. Disabled
              (not hidden) with a tooltip, so the button's presence
              still signals the feature exists, just not yet
              usable — same choice already made for other guarded
              actions in this app (frozen-after-invoice, etc). */}
          <button
            className="btn-ghost"
            onClick={handleDownloadPdf}
            disabled={downloadingPdf || !hasContent}
            title={!hasContent ? "Tambah item Parts/Jasa terlebih dahulu" : undefined}
          >
            {downloadingPdf ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={15} />}
            Download PDF
          </button>
          <button
            className="btn-rust"
            onClick={() => window.print()}
            disabled={!hasContent}
            title={!hasContent ? "Tambah item Parts/Jasa terlebih dahulu" : undefined}
          >
            <Printer size={15} /> Cetak
          </button>
        </div>
      </div>

      {error && <div className="no-print" style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <PrintableQuotation estimate={estimate} orgName={orgName} />

      <div className="no-print">
        <OdometerCard ref={odometerRef} estimate={estimate} onUpdated={load} />
        <DiagnosisCard ref={diagnosisRef} estimate={estimate} onUpdated={load} />
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
