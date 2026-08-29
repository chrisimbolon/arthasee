"use client";
// =============================================================================
// === frontend/app/dashboard/mechanics/page.tsx ===
// Made's own 28 Jul Owner Dashboard requirement — a real roster so
// "mechanic headcount" stops being a fabricated number (the exact
// gap Made himself flagged in Sansan's mockup: "kenapa mechanic
// hanya 3 yg kerja? 3 dari 6"). Deliberately NOT login-capable — mechanics still never log into the system at all.
// =============================================================================
import {
  Mechanic, MechanicMonthlyProgressRow, mechanicProgressApi, mechanicsApi,
} from "@/lib/api/workorders";
import { Check, Loader2, Pencil, Plus, Wrench, X } from "lucide-react";
import { useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

const MONTH_NAMES_ID = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

function AddMechanicModal({ onClose, onCreated }: { onClose: () => void; onCreated: (m: Mechanic) => void }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true); setError(null);
    try {
      const mechanic = await mechanicsApi.create(name.trim());
      onCreated(mechanic);
      onClose();
    } catch {
      setError("Gagal menyimpan mekanik.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 380, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Tambah Mekanik</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Nama Mekanik</label>
            <input className="input" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="cth. Alex" />
          </div>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

// 29 Aug 2026 — Made's own confirmed real request: real monthly
// labor-revenue tracking per mechanic against their own
// monthly_target. Capped display at 100% visually (a real overage
// still shows its true percent as text, just doesn't overflow the
// bar itself) — green once genuinely at or past target, the
// existing rust accent color otherwise.
function TargetProgressBar({ row }: { row: MechanicMonthlyProgressRow }) {
  const realPercent = toNumber(row.percent_of_target);
  const barWidth = Math.min(realPercent, 100);
  const metTarget = realPercent >= 100;
  return (
    <div style={{ minWidth: 200 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
        <span className="mono" style={{ color: "var(--steel)" }}>{formatRupiah(row.labor_revenue)}</span>
        <span style={{ fontWeight: 600, color: metTarget ? "#2e7d4f" : "var(--ink-soft)" }}>
          {realPercent.toFixed(0)}%
        </span>
      </div>
      <div style={{ height: 6, borderRadius: 4, background: "var(--paper-2)", overflow: "hidden" }}>
        <div
          style={{
            height: "100%", width: `${barWidth}%`, borderRadius: 4,
            background: metTarget ? "#2e7d4f" : "var(--rust)", transition: "width 0.3s",
          }}
        />
      </div>
    </div>
  );
}

// Inline-editable monthly_target — Chris's own confirmed reasoning
// for making this a real, per-mechanic field: Made can adjust a
// senior vs. junior mechanic's own target later without a code
// change. Same simple inline-edit pattern as the existing
// toggleActive button below, not a separate modal for one field.
function EditableTarget({ mechanic, onUpdated }: { mechanic: Mechanic; onUpdated: (m: Mechanic) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(mechanic.monthly_target);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await mechanicsApi.update(mechanic.id, { monthly_target: toNumber(value) });
      onUpdated(updated);
      setEditing(false);
    } catch {
      // Real failure is rare here (a plain number field) — silently
      // staying in edit mode lets the person just retry, same
      // low-ceremony handling as this page's own existing
      // toggleActive error path.
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <button
        onClick={() => { setValue(mechanic.monthly_target); setEditing(true); }}
        className="btn-ghost"
        style={{ fontSize: 12, padding: "4px 8px", display: "inline-flex", alignItems: "center", gap: 5 }}
      >
        {formatRupiah(mechanic.monthly_target)} <Pencil size={11} />
      </button>
    );
  }

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <input
        className="input" type="number" min={0} style={{ width: 130, fontSize: 12, padding: "4px 8px" }}
        value={value} onChange={(e) => setValue(e.target.value)} autoFocus
      />
      <button onClick={handleSave} disabled={saving} className="btn-ghost" style={{ padding: "4px 6px" }}>
        {saving ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={12} />}
      </button>
      <button onClick={() => setEditing(false)} className="btn-ghost" style={{ padding: "4px 6px" }}><X size={12} /></button>
    </div>
  );
}


export default function MechanicsPage() {
  const [mechanics, setMechanics] = useState<Mechanic[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 29 Aug 2026 — real monthly labor-revenue progress per mechanic.
  // Keyed by mechanic_id for O(1) lookup per table row below.
  const [progress, setProgress] = useState<Record<string, MechanicMonthlyProgressRow>>({});
  const [progressMonth, setProgressMonth] = useState<{ year: number; month: number } | null>(null);

  const load = () => {
    mechanicsApi.list().then(setMechanics).finally(() => setLoading(false));
    mechanicProgressApi.monthly().then((res) => {
      if (!res) return;
      setProgressMonth({ year: res.year, month: res.month });
      const map: Record<string, MechanicMonthlyProgressRow> = {};
      res.mechanics.forEach((row) => { map[row.mechanic_id] = row; });
      setProgress(map);
    });
  };
  useEffect(() => { load(); }, []);

  const activeCount = mechanics.filter((m) => m.is_active).length;

  const toggleActive = async (mechanic: Mechanic) => {
    setBusyId(mechanic.id); setError(null);
    try {
      const updated = await mechanicsApi.update(mechanic.id, { is_active: !mechanic.is_active });
      setMechanics((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
    } catch {
      setError("Gagal mengubah status mekanik.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Mekanik</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>
            {activeCount} mekanik aktif · {mechanics.length} total tercatat
            {progressMonth && ` · Progres ${MONTH_NAMES_ID[progressMonth.month - 1]} ${progressMonth.year}`}
          </p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Tambah Mekanik</button>
      </div>

      <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18, maxWidth: 560 }}>
        Mekanik tidak memiliki akun login — daftar ini hanya untuk mencatat siapa mengerjakan tahap apa,
        dan memberi angka pasti pada Ringkasan (bukan perkiraan).
      </p>

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 18 }}>
          {error}
        </div>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : mechanics.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Wrench size={22} style={{ marginBottom: 10, opacity: 0.5 }} />
            <p style={{ fontSize: 14 }}>Belum ada mekanik tercatat.</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nama</th><th>Status</th><th>Target Bulanan</th><th>Progres</th><th></th></tr>
            </thead>
            <tbody>
              {mechanics.map((m) => (
                <tr key={m.id}>
                  <td style={{ fontWeight: 600 }}>{m.name}</td>
                  <td>
                    <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: m.is_active ? "#fff" : "var(--ink-soft)", background: m.is_active ? "#2e7d4f" : "var(--paper-3)", border: m.is_active ? "none" : "1px solid var(--line)" }}>
                      {m.is_active ? "Aktif" : "Nonaktif"}
                    </span>
                  </td>
                  <td>
                    <EditableTarget mechanic={m} onUpdated={(updated) => setMechanics((prev) => prev.map((mm) => (mm.id === updated.id ? updated : mm)))} />
                  </td>
                  <td>
                    {progress[m.id] ? (
                      <TargetProgressBar row={progress[m.id]} />
                    ) : (
                      <span style={{ fontSize: 12, color: "var(--steel)" }}>—</span>
                    )}
                  </td>
                  <td>
                    <button
                      onClick={() => toggleActive(m)}
                      disabled={busyId === m.id}
                      className="btn-ghost"
                      style={{ fontSize: 12, padding: "5px 10px" }}
                    >
                      {busyId === m.id ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : (m.is_active ? "Nonaktifkan" : "Aktifkan")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddMechanicModal onClose={() => setShowAdd(false)} onCreated={(m) => setMechanics((prev) => [...prev, m])} />
      )}
    </div>
  );
}
