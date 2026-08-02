"use client";
// =============================================================================
// === frontend/app/dashboard/work-order-detail/page.tsx ===
// Same query-param pattern as vehicle-detail/invoice-detail — static
// export needs every route's HTML identical regardless of ?id= value.
// =============================================================================
import { Part, partsApi } from "@/lib/api/service";
import {
  Mechanic,
  mechanicsApi,
  WorkOrder,
  WorkOrderJobLine,
  workOrderJobLinesApi, workOrderMaterialLinesApi, workOrdersApi,
  WorkOrderStage,
  workOrderStagesApi,
  WorkOrderStatus,
} from "@/lib/api/workorders";
import { AlertTriangle, ArrowLeft, Check, Download, Loader2, Pencil, Plus, Printer, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const STATUS_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: "Terbuka", IN_PROGRESS: "Dikerjakan", QC: "Pemeriksaan Kualitas", DONE: "Selesai", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<WorkOrderStatus, string> = {
  // Same muted slate-blue as vehicle-detail and active-jobs' own
  // OPEN status badges — kept identical across all three so
  // "Terbuka" reads as one consistent color everywhere, not
  // different shades depending on which screen it's shown on.
  OPEN: "#4a6d94", IN_PROGRESS: "var(--rust)", QC: "#b5860b", DONE: "#2e7d4f", CANCELLED: "var(--danger)",
};
const OPEN_STATUSES: WorkOrderStatus[] = ["OPEN", "IN_PROGRESS", "QC"];

// Deliberately includes the clock time, not just the date — Made's
// own request was specifically "jam mulai dikerjakan" (the hour work
// started), so a date-only display would miss the actual point of
// asking for this at all.
function formatDateTimeWithClock(iso: string) {
  const d = new Date(iso);
  const datePart = d.toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
  const timePart = d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  return `${datePart}, ${timePart}`;
}

// Shorter form for stage cards, where a start AND complete time may
// both show side by side — the full month name would crowd the row.
function formatCompactDateTime(iso: string) {
  const d = new Date(iso);
  const datePart = d.toLocaleDateString("id-ID", { day: "numeric", month: "short" });
  const timePart = d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  return `${datePart}, ${timePart}`;
}

function IntakeCard({ wo, mechanics, onUpdated }: { wo: WorkOrder; mechanics: Mechanic[]; onUpdated: () => void }) {
  const editable = OPEN_STATUSES.includes(wo.status);
  const [form, setForm] = useState({
    odometer_km_intake: wo.odometer_km_intake?.toString() ?? "",
    received_by: wo.received_by,
    notes: wo.notes,
    assigned_to: wo.assigned_to ?? "",
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
        assigned_to: form.assigned_to || null,
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          <div><div style={{ fontSize: 11.5, color: "var(--steel)" }}>KM Saat Masuk</div><div className="mono">{wo.odometer_km_intake ?? "—"}</div></div>
          <div><div style={{ fontSize: 11.5, color: "var(--steel)" }}>Diterima Oleh</div><div>{wo.received_by || "—"}</div></div>
          {/* Made's own explicit reason, 31 Jul: a specific mechanic
              must be identifiable on every job so he can go back and
              question that person directly if the same car has an
              issue again. */}
          <div><div style={{ fontSize: 11.5, color: "var(--steel)" }}>Mekanik</div><div>{wo.assigned_to_name || "—"}</div></div>
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
      <div style={{ marginBottom: 12 }}>
        <label className="label">Mekanik Penanggung Jawab</label>
        <select className="input" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}>
          <option value="">— Belum ditentukan —</option>
          {mechanics.map((m) => (
            <option key={m.id} value={m.id} disabled={!m.is_active && m.id !== wo.assigned_to}>
              {m.name}{!m.is_active ? " (nonaktif)" : ""}
            </option>
          ))}
        </select>
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

// Chris's own explicit ask, 2 Aug — caught live from a real
// screenshot: a job line typed with a typo ("Pemasangan Kembal") had
// no way to ever be fixed, and no way to remove a wrongly-added item
// either. Shared between StageCard's per-stage list and
// JobLinesSection's unstaged list, rather than duplicating the same
// inline-edit state machine in two places — the two render locations
// only ever differed in sizing (compact vs. not), never in behavior.
function JobLineRow({ line, editable, onToggle, onUpdated, compact }: {
  line: WorkOrderJobLine;
  editable: boolean;
  onToggle: (id: string) => void;
  onUpdated: () => void;
  compact?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [value, setValue] = useState(line.description);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Two conditions combined deliberately, not just one: `editable`
  // is the WO-level open-status check the caller already computes;
  // `!line.is_locked` is the backend's own, stricter rule (also
  // covers a completed stage locking its own lines even while the
  // WorkOrder overall still has other open stages). Checking both
  // client-side is real defense-in-depth, not redundancy — the
  // backend is still the actual enforcement either way (409 on a
  // stale client).
  const canModify = editable && !line.is_locked;

  const startEdit = () => { setValue(line.description); setError(null); setIsEditing(true); };
  const cancelEdit = () => { setValue(line.description); setError(null); setIsEditing(false); };

  const save = async () => {
    const trimmed = value.trim();
    if (!trimmed) { setError("Deskripsi tidak boleh kosong."); return; }
    if (trimmed === line.description) { setIsEditing(false); return; }
    setSaving(true); setError(null);
    try {
      await workOrderJobLinesApi.update(line.id, trimmed);
      setIsEditing(false);
      onUpdated();
    } catch {
      setError("Gagal menyimpan perubahan.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Hapus item "${line.description}"?`)) return;
    setError(null);
    try {
      await workOrderJobLinesApi.remove(line.id);
      onUpdated();
    } catch {
      setError("Gagal menghapus item.");
    }
  };

  const boxSize = compact ? 16 : 20;
  const boxRadius = compact ? 4 : 5;
  const iconSize = compact ? 10 : 13;
  const fontSize = compact ? 13 : 14;

  if (isEditing) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            className="input" autoFocus
            style={{ flex: 1, fontSize, padding: compact ? "4px 8px" : "6px 10px" }}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") cancelEdit(); }}
          />
          <button className="btn-ghost" style={{ fontSize: 11, padding: "4px 9px", flexShrink: 0 }} onClick={save} disabled={saving}>
            {saving ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
          <button className="btn-ghost" style={{ fontSize: 11, padding: "4px 9px", flexShrink: 0 }} onClick={cancelEdit}>
            Batal
          </button>
        </div>
        {error && <span style={{ fontSize: 11, color: "var(--danger)" }}>{error}</span>}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", alignItems: "center", gap: compact ? 8 : 10 }}>
        <button
          onClick={() => canModify && onToggle(line.id)}
          disabled={!canModify}
          style={{
            width: boxSize, height: boxSize, borderRadius: boxRadius, border: "1px solid var(--line)",
            background: line.is_done ? "var(--rust)" : "transparent",
            display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            cursor: canModify ? "pointer" : "default",
          }}
        >
          {line.is_done && <Check size={iconSize} color="#fff" />}
        </button>
        <span style={{ flex: 1, fontSize, textDecoration: line.is_done ? "line-through" : "none", color: line.is_done ? "var(--steel)" : undefined }}>
          {line.description}
        </span>
        {canModify && (
          <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
            <button onClick={startEdit} title="Ubah" style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: "var(--steel)", display: "flex" }}>
              <Pencil size={compact ? 12 : 13} />
            </button>
            <button onClick={remove} title="Hapus" style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: "var(--steel)", display: "flex" }}>
              <Trash2 size={compact ? 12 : 13} />
            </button>
          </div>
        )}
      </div>
      {error && <span style={{ fontSize: 11, color: "var(--danger)" }}>{error}</span>}
    </div>
  );
}

function StageCard({ stage, mechanics, editable, onUpdated }: {
  stage: WorkOrderStage; mechanics: Mechanic[]; editable: boolean; onUpdated: () => void;
}) {
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const extractMessage = (err: unknown, fallback: string) =>
    (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? fallback;

  const start = async () => {
    setError(null);
    try {
      await workOrderStagesApi.start(stage.id);
      onUpdated();
    } catch (err) {
      setError(extractMessage(err, "Gagal memulai tahap."));
    }
  };

  const complete = async () => {
    setError(null);
    try {
      await workOrderStagesApi.complete(stage.id);
      onUpdated();
    } catch (err) {
      setError(extractMessage(err, "Gagal menyelesaikan tahap."));
    }
  };

  const toggle = async (lineId: string) => {
    try {
      await workOrderJobLinesApi.toggle(lineId);
      onUpdated();
    } catch (err) {
      setError(extractMessage(err, "Gagal mengubah status item."));
    }
  };

  const addLine = async () => {
    if (!desc.trim()) return;
    setSaving(true); setError(null);
    try {
      await workOrderJobLinesApi.create(stage.work_order, desc.trim(), stage.id);
      setDesc("");
      onUpdated();
    } catch (err) {
      setError(extractMessage(err, "Gagal menambah item."));
    } finally {
      setSaving(false);
    }
  };

  // Made's own diagram showed real, named mechanics working stages
  // in parallel — this is the concrete UI for that. Deliberately
  // optional: nothing about starting/completing a stage requires an
  // assignment, same "trust human judgment" reasoning as completing
  // a stage never requiring all its job lines checked off first.
  const assignMechanic = async (mechanicId: string) => {
    setError(null);
    try {
      await workOrderStagesApi.update(stage.id, { assigned_to: mechanicId || null });
      onUpdated();
    } catch (err) {
      setError(extractMessage(err, "Gagal menetapkan mekanik."));
    }
  };

  const borderColor = stage.completed_at ? "#2e7d4f" : stage.started_at ? "var(--rust)" : "var(--steel-lt)";

  return (
    <div className="card" style={{ marginBottom: 10, borderLeft: `3px solid ${borderColor}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 14, display: "flex", alignItems: "center", gap: 6 }}>
          {stage.name}
          {/* Made's own literal example: an oil change + brake pads
              taking more than 2 hours. Only ever shown while a stage
              is genuinely in-progress and past its own threshold —
              is_overdue already accounts for a completed stage never
              qualifying, regardless of how long it actually took. */}
          {stage.is_overdue && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 10.5, fontWeight: 600, color: "var(--danger)", background: "var(--danger-light)", padding: "2px 7px", borderRadius: 20 }}>
              <AlertTriangle size={10} /> Lama
            </span>
          )}
        </span>
        {stage.completed_at ? (
          <span style={{ fontSize: 11, color: "#2e7d4f", fontWeight: 600, display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
            <Check size={12} /> Selesai
          </span>
        ) : editable ? (
          !stage.started_at ? (
            <button className="btn-ghost" style={{ fontSize: 11.5, padding: "4px 10px", flexShrink: 0 }} onClick={start}>Mulai Tahap</button>
          ) : (
            <button className="btn-ghost" style={{ fontSize: 11.5, padding: "4px 10px", flexShrink: 0 }} onClick={complete}>Selesaikan Tahap</button>
          )
        ) : null}
      </div>

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "7px 10px", borderRadius: 5, fontSize: 12, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={12} /> {error}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <span style={{ fontSize: 11.5, color: "var(--steel)" }}>Dikerjakan oleh:</span>
        {editable ? (
          <select
            value={stage.assigned_to ?? ""}
            onChange={(e) => assignMechanic(e.target.value)}
            className="input"
            style={{ fontSize: 12, padding: "3px 8px", width: "auto" }}
          >
            <option value="">— Belum ditentukan —</option>
            {mechanics.map((m) => (
              <option key={m.id} value={m.id} disabled={!m.is_active && m.id !== stage.assigned_to}>
                {m.name}{!m.is_active ? " (nonaktif)" : ""}
              </option>
            ))}
          </select>
        ) : (
          <span style={{ fontSize: 12.5, fontWeight: 500 }}>{stage.assigned_to_name ?? "—"}</span>
        )}
      </div>

      {(stage.started_at || stage.completed_at) && (
        <div className="mono" style={{ fontSize: 11, color: "var(--steel)", marginBottom: 10 }}>
          {stage.started_at && <>Mulai: {formatCompactDateTime(stage.started_at)}</>}
          {stage.completed_at && <> · Selesai: {formatCompactDateTime(stage.completed_at)}</>}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: editable ? 10 : 0 }}>
        {stage.job_lines.length === 0 && <p style={{ fontSize: 12.5, color: "var(--steel)" }}>Belum ada item di tahap ini.</p>}
        {stage.job_lines.map((line) => (
          <JobLineRow key={line.id} line={line} editable={editable} onToggle={toggle} onUpdated={onUpdated} compact />
        ))}
      </div>

      {editable && (
        <div style={{ display: "flex", gap: 6 }}>
          <input
            className="input" style={{ flex: 1, fontSize: 13, padding: "6px 10px" }}
            placeholder="Tambah item ke tahap ini" value={desc}
            onChange={(e) => setDesc(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addLine()}
          />
          <button className="btn-ghost" style={{ fontSize: 11.5, padding: "6px 10px" }} onClick={addLine} disabled={saving}>
            {saving ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={12} />}
          </button>
        </div>
      )}
    </div>
  );
}

function StagesSection({ wo, mechanics, onUpdated }: { wo: WorkOrder; mechanics: Mechanic[]; onUpdated: () => void }) {
  const editable = OPEN_STATUSES.includes(wo.status);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Purely additive — a routine, single-visit repair never creates a
  // stage at all, and this section renders nothing but a small,
  // easy-to-ignore "+ Tambah Tahap" affordance in that case. Made's
  // own scoping: stages are for genuinely multi-phase jobs (heavy
  // collision/overhaul work), not something every job is expected to use.
  if (wo.stages.length === 0 && !editable) return null;

  const addStage = async () => {
    if (!name.trim()) return;
    setSaving(true); setError(null);
    try {
      await workOrderStagesApi.create(wo.id, name.trim());
      setName("");
      setShowAdd(false);
      onUpdated();
    } catch (err) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(message ?? "Gagal menambah tahap.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginBottom: 20 }}>
      {wo.stages.length > 0 && (
        <>
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Tahap Pengerjaan</h3>
          {wo.stages.map((stage) => (
            <StageCard key={stage.id} stage={stage} mechanics={mechanics} editable={editable} onUpdated={onUpdated} />
          ))}
        </>
      )}
      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginTop: wo.stages.length > 0 ? 8 : 0, marginBottom: 4 }}>
          {error}
        </div>
      )}
      {editable && (
        showAdd ? (
          <div style={{ display: "flex", gap: 8, marginTop: wo.stages.length > 0 || error ? 8 : 0 }}>
            <input
              className="input" style={{ flex: 1 }} placeholder="Nama tahap, cth. Body Repair"
              value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addStage()}
            />
            <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={addStage} disabled={saving}>
              {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Tambah"}
            </button>
            <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={() => { setShowAdd(false); setError(null); }}>Batal</button>
          </div>
        ) : (
          <button
            className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px", marginTop: wo.stages.length > 0 ? 8 : 0 }}
            onClick={() => setShowAdd(true)}
          >
            <Plus size={13} /> Tambah Tahap{wo.stages.length === 0 && " (untuk pekerjaan besar/bertahap)"}
          </button>
        )
      )}
    </div>
  );
}

function JobLinesSection({ wo, onUpdated }: { wo: WorkOrder; onUpdated: () => void }) {
  const editable = OPEN_STATUSES.includes(wo.status);
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);

  // Only the unstaged lines — anything grouped into a stage already
  // renders inside its own StageCard above, and showing it twice
  // here would be pure duplication, not a second, different view.
  const unstagedLines = wo.job_lines.filter((line) => !line.stage);

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
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>
        {wo.stages.length > 0 ? "Pekerjaan Lain (Tanpa Tahap)" : "Pekerjaan"}
      </h3>
      {unstagedLines.length === 0 && <p style={{ color: "var(--steel)", fontSize: 13.5, marginBottom: 12 }}>Belum ada item pekerjaan.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: editable ? 14 : 0 }}>
        {unstagedLines.map((line) => (
          <JobLineRow key={line.id} line={line} editable={editable} onToggle={toggle} onUpdated={onUpdated} />
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
    // Simple, honest prompt rather than silently defaulting — Made
    // specifically described customer-cancelled parts (already
    // installed, then removed mid-repair on a multi-day job) as a
    // real, recurring scenario distinct from a plain mistake.
    const customerCancelled = window.confirm(
      "Apakah pelanggan yang membatalkan part ini?\n\nOK = Ya, pelanggan membatalkan\nBatal = Tidak, ini koreksi kesalahan input"
    );
    await workOrderMaterialLinesApi.remove(lineId, customerCancelled ? "customer_cancelled_part" : "correction");
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
  const [mechanics, setMechanics] = useState<Mechanic[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closeDate, setCloseDate] = useState(new Date().toISOString().slice(0, 10));
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  const load = () => workOrdersApi.get(workOrderId).then(setWo).finally(() => setLoading(false));
  useEffect(() => { if (workOrderId) load(); }, [workOrderId]);
  useEffect(() => { partsApi.list().then(setCatalog); }, []);
  // Fetched once at this level, not per-StageCard — every stage on
  // this WO shares the same roster, so this avoids N duplicate calls
  // for N stage cards. Includes inactive mechanics deliberately: an
  // already-assigned stage referencing a since-deactivated mechanic
  // must still show their real name, not silently disappear from
  // the picker's own source data.
  useEffect(() => { mechanicsApi.list().then(setMechanics); }, []);

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
      await workOrdersApi.close(workOrderId, closeDate);
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

  // Made's own confirmed answer, 1 Aug: an internal, no-price job
  // ticket for the mechanic, available the moment "Mulai Dikerjakan"
  // is clicked. Gated on wo.status !== "OPEN", NOT wo.work_started_at
  // — that field is deliberately Estimate-only (see WorkOrder.
  // mark_started() on the backend) and stays null forever for a
  // direct-entry WorkOrder, which is the majority of real jobs.
  // Caught this the hard way mid-build: gating on work_started_at
  // would've left this permanently disabled for most work orders.
  const handleDownloadPdf = async () => {
    if (!wo) return;
    setDownloadingPdf(true); setError(null);
    try {
      const blob = await workOrdersApi.downloadJobTicketPdf(wo.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `WO_${wo.number}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Gagal mengunduh job ticket.");
    } finally {
      setDownloadingPdf(false);
    }
  };

  // Chris's own explicit ask, 1 Aug: unlike estimate-detail/invoice-
  // detail, this page has no dedicated print-styled layout — it's
  // all live editable forms (selects, checkboxes, delete icons). A
  // raw window.print() here would print that messy interactive UI
  // verbatim, not a clean ticket. Rather than building and
  // maintaining a second, React-only copy of the exact same layout
  // already built once in workorders/pdf.py, "Cetak" opens the same
  // PDF in a new tab instead — one real source of truth, and the
  // browser's own PDF viewer handles printing from there. Genuinely
  // simpler than Estimasi/Invoice's own two-copies-of-the-same-
  // layout pattern, not a shortcut around it.
  const handlePrint = async () => {
    if (!wo) return;
    setDownloadingPdf(true); setError(null);
    try {
      const blob = await workOrdersApi.downloadJobTicketPdf(wo.id);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    } catch {
      setError("Gagal membuka job ticket.");
    } finally {
      setDownloadingPdf(false);
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <Link href={`/dashboard/vehicle-detail?id=${wo.vehicle}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)" }}>
          <ArrowLeft size={14} /> Kembali ke Kendaraan
        </Link>
        {/* Chris's own explicit ask, 1 Aug: a real, printable/
            downloadable job ticket for the mechanic — gated on
            wo.status !== "OPEN", not wo.work_started_at (that field
            is Estimate-only, see the backend's own mark_started()).
            Backend enforces this for real (409 if still OPEN);
            disabled-with-tooltip here just keeps SA from hitting
            that error in the common case, same pattern as the PDF
            gate on estimate-detail. */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn-ghost"
            onClick={handleDownloadPdf}
            disabled={downloadingPdf || wo.status === "OPEN"}
            title={wo.status === "OPEN" ? "Tersedia setelah WO mulai dikerjakan" : undefined}
          >
            {downloadingPdf ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={15} />}
            Download PDF
          </button>
          <button
            className="btn-rust"
            onClick={handlePrint}
            disabled={downloadingPdf || wo.status === "OPEN"}
            title={wo.status === "OPEN" ? "Tersedia setelah WO mulai dikerjakan" : undefined}
          >
            <Printer size={15} /> Cetak
          </button>
        </div>
      </div>

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

      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: wo.work_started_at ? 6 : 20 }}>
        {wo.vehicle_plate} · {wo.customer_name}
      </p>

      {wo.work_started_at && (
        <p style={{ color: "var(--workshop)", fontSize: 13, marginBottom: wo.is_overdue ? 8 : 20, display: "flex", alignItems: "center", gap: 6 }}>
          <Check size={13} />
          Mulai dikerjakan: <span className="mono">{formatDateTimeWithClock(wo.work_started_at)}</span>
        </p>
      )}

      {/* Made's own literal example: an oil change + brake pads
          taking more than 2 hours. Whole-WorkOrder version of the
          same signal shown per-stage in StageCard below — a routine
          job has no stages at all, so it needs this at the WO level
          too, not only inside stage cards. */}
      {wo.is_overdue && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "8px 12px", borderRadius: 5, fontSize: 13, marginBottom: 20, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={13} /> Pekerjaan ini sudah berjalan lebih lama dari perkiraan.
        </div>
      )}

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <IntakeCard wo={wo} mechanics={mechanics} onUpdated={load} />
      <StagesSection wo={wo} mechanics={mechanics} onUpdated={load} />
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
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          {wo.status === "OPEN" && (
            <button className="btn-rust" disabled={busy} onClick={() => advanceStatus("IN_PROGRESS")}>Mulai WO #{wo.number} Sekarang</button>
          )}
          {wo.status === "IN_PROGRESS" && (
            <button className="btn-rust" disabled={busy} onClick={() => advanceStatus("QC")}>Ajukan Pemeriksaan</button>
          )}
          {/* Chris's own catch, 2 Aug: this used to render
              unconditionally for every OPEN_STATUSES status,
              including a fresh OPEN WorkOrder that never even
              clicked "Mulai Dikerjakan" — letting a job jump straight
              to DONE with zero actual work recorded. Same real
              enforcement backing this on the backend now
              (WorkOrder.close() itself rejects status="OPEN" with a
              409), this is just the proactive layer that stops SA
              from seeing a button with no valid action behind it. */}
          {wo.status !== "OPEN" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <label className="label" style={{ marginBottom: 0 }}>Tanggal Servis</label>
                <input
                  className="input" type="date" style={{ padding: "6px 10px", fontSize: 13, width: 150 }}
                  value={closeDate} onChange={(e) => setCloseDate(e.target.value)}
                  // Defaults to today but editable — this is what lets a
                  // Work Order genuinely replace the old free-text quick
                  // entry: backdating a visit that happened days ago,
                  // not just logging one that just finished.
                />
              </div>
              <button className="btn-rust" disabled={busy} onClick={handleClose}>Selesaikan Work Order</button>
            </>
          )}
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
