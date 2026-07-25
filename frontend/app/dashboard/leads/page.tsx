"use client";
// =============================================================================
// === frontend/app/dashboard/leads/page.tsx ===
// Made's own words: "no money today doesn't mean no money forever."
// Deliberately NOT linked to Customer/Vehicle/WorkOrder — confirmed
// he's fine converting one into a real customer himself, manually,
// if they come back. follow_up_status filtering IS the personal
// call-list mechanism; no separate feature needed for that.
// =============================================================================
import {
  FollowUpStatus, LeadReason, RejectedQuote, RejectedQuotePayload, leadsApi,
} from "@/lib/api/leads";
import { Loader2, Phone, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

const REASON_LABEL: Record<LeadReason, string> = {
  TOO_EXPENSIVE:  "Harga Terlalu Mahal",
  WENT_ELSEWHERE: "Pilih Bengkel Lain",
  POSTPONED:      "Ditunda Dulu",
  NOT_NEEDED:     "Diputuskan Tidak Perlu",
  OTHER:          "Lainnya",
};

const STATUS_LABEL: Record<FollowUpStatus, string> = {
  PENDING:   "Belum Dihubungi",
  CONTACTED: "Sudah Dihubungi",
  CONVERTED: "Jadi Pelanggan",
  CLOSED:    "Ditutup",
};
const STATUS_COLOR: Record<FollowUpStatus, string> = {
  PENDING: "var(--rust)", CONTACTED: "var(--steel)", CONVERTED: "#2e7d4f", CLOSED: "#8a8a86",
};

const FILTER_TABS: { key: FollowUpStatus | "ALL"; label: string }[] = [
  { key: "ALL",       label: "Semua" },
  { key: "PENDING",   label: "Belum Dihubungi" },
  { key: "CONTACTED", label: "Sudah Dihubungi" },
  { key: "CONVERTED", label: "Jadi Pelanggan" },
  { key: "CLOSED",    label: "Ditutup" },
];

function money(v: string | null) {
  return v ? `Rp ${Number(v).toLocaleString("id-ID")}` : "—";
}

function CreateLeadForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<RejectedQuotePayload>({
    name: "", phone: "", vehicle_description: "", quoted_description: "",
    quoted_amount: undefined, reason: "OTHER", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const reset = () => setForm({ name: "", phone: "", vehicle_description: "", quoted_description: "", quoted_amount: undefined, reason: "OTHER", notes: "" });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true); setError(null);
    try {
      await leadsApi.create({ ...form, quoted_amount: form.quoted_amount ? Number(form.quoted_amount) : null });
      reset();
      setOpen(false);
      onCreated();
    } catch {
      setError("Gagal menyimpan data.");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return <button className="btn-rust" onClick={() => setOpen(true)}><Plus size={16} /> Tambah Lead</button>;
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Tambah Lead</h3>
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div>
            <label className="label">Nama</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label className="label">Nomor Telepon</label>
            <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label className="label">Deskripsi Kendaraan <span style={{ textTransform: "none", fontWeight: 400 }}>(bebas, mis. "Avanza putih, sekitar 2018")</span></label>
          <input className="input" value={form.vehicle_description} onChange={(e) => setForm({ ...form, vehicle_description: e.target.value })} />
        </div>
        <div style={{ marginBottom: 14 }}>
          <label className="label">Pekerjaan yang Ditawarkan</label>
          <textarea className="input" rows={2} value={form.quoted_description} onChange={(e) => setForm({ ...form, quoted_description: e.target.value })} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div>
            <label className="label">Estimasi Biaya <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" type="number" min={0} value={form.quoted_amount ?? ""} onChange={(e) => setForm({ ...form, quoted_amount: e.target.value ? Number(e.target.value) : undefined })} />
          </div>
          <div>
            <label className="label">Alasan Penolakan</label>
            <select className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value as LeadReason })}>
              {Object.entries(REASON_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
        </div>
        <div style={{ marginBottom: 18 }}>
          <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
          <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-rust" type="submit" disabled={saving}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
          <button type="button" className="btn-ghost" onClick={() => { reset(); setError(null); setOpen(false); }}>Batal</button>
        </div>
      </form>
    </div>
  );
}

function LeadRow({ lead, onChanged }: { lead: RejectedQuote; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<RejectedQuotePayload>({
    name: lead.name, phone: lead.phone, vehicle_description: lead.vehicle_description,
    quoted_description: lead.quoted_description, quoted_amount: lead.quoted_amount ? Number(lead.quoted_amount) : undefined,
    reason: lead.reason, notes: lead.notes, follow_up_status: lead.follow_up_status,
  });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await leadsApi.update(lead.id, { ...form, quoted_amount: form.quoted_amount ? Number(form.quoted_amount) : null });
      setExpanded(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Hapus data lead untuk "${lead.name}"?`)) return;
    setDeleting(true);
    try {
      await leadsApi.remove(lead.id);
      onChanged();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", cursor: "pointer" }} onClick={() => setExpanded((v) => !v)}>
        <div>
          <div style={{ fontSize: 14.5, fontWeight: 600 }}>{lead.name}</div>
          <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 2 }}>
            {lead.phone && <>{lead.phone} · </>}{lead.vehicle_description || "—"}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{money(lead.quoted_amount)}</span>
          <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[lead.follow_up_status] }}>
            {STATUS_LABEL[lead.follow_up_status]}
          </span>
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div>
              <label className="label">Nama</label>
              <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label className="label">Nomor Telepon</label>
              <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label className="label">Deskripsi Kendaraan</label>
            <input className="input" value={form.vehicle_description} onChange={(e) => setForm({ ...form, vehicle_description: e.target.value })} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label className="label">Pekerjaan yang Ditawarkan</label>
            <textarea className="input" rows={2} value={form.quoted_description} onChange={(e) => setForm({ ...form, quoted_description: e.target.value })} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div>
              <label className="label">Estimasi Biaya</label>
              <input className="input" type="number" min={0} value={form.quoted_amount ?? ""} onChange={(e) => setForm({ ...form, quoted_amount: e.target.value ? Number(e.target.value) : undefined })} />
            </div>
            <div>
              <label className="label">Alasan</label>
              <select className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value as LeadReason })}>
                {Object.entries(REASON_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Status Follow-up</label>
              <select className="input" value={form.follow_up_status} onChange={(e) => setForm({ ...form, follow_up_status: e.target.value as FollowUpStatus })}>
                {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
          </div>
          <div style={{ marginBottom: 16 }}>
            <label className="label">Catatan</label>
            <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn-rust" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
              </button>
              <button className="btn-ghost" onClick={() => setExpanded(false)}>Batal</button>
            </div>
            <button className="btn-ghost" style={{ color: "var(--danger)" }} onClick={handleDelete} disabled={deleting}>
              <Trash2 size={14} /> Hapus
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<RejectedQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FollowUpStatus | "ALL">("PENDING");

  const load = () => {
    setLoading(true);
    leadsApi.list(filter === "ALL" ? undefined : { followUpStatus: filter }).then(setLeads).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [filter]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <h1 className="display" style={{ fontSize: 26 }}>Leads</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            Estimasi yang ditolak pelanggan — daftar telepon-balik pribadi.
          </p>
        </div>
      </div>

      <div style={{ margin: "20px 0" }}>
        <CreateLeadForm onCreated={load} />
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.key}
            className={filter === tab.key ? "btn-rust" : "btn-ghost"}
            style={{ fontSize: 13, padding: "7px 14px" }}
            onClick={() => setFilter(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
        </div>
      ) : leads.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 32 }}>
          <Phone size={20} style={{ marginBottom: 8 }} />
          <p>Tidak ada data untuk filter ini.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {leads.map((lead) => <LeadRow key={lead.id} lead={lead} onChanged={load} />)}
        </div>
      )}
    </div>
  );
}
