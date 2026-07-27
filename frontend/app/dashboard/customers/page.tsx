"use client";
// =============================================================================
// === frontend/app/dashboard/customers/page.tsx ===
// =============================================================================
import { Customer, CustomerType, customersApi } from "@/lib/api/service";
import { Briefcase, Loader2, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

function AddCustomerModal({ onClose, onCreated }: { onClose: () => void; onCreated: (c: Customer) => void }) {
  const [form, setForm] = useState({ name: "", phone: "", stnk_name: "", customer_type: "INDIVIDUAL" as CustomerType });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const customer = await customersApi.create(form);
      onCreated(customer);
      onClose();
    } catch {
      setError("Gagal menyimpan pelanggan.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 420, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Tambah Pelanggan</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nama Pelanggan</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Nama lengkap" />
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nomor Telepon</label>
            <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="08xxxxxxxxxx" />
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nama di STNK <span style={{ textTransform: "none", fontWeight: 400 }}>(jika berbeda)</span></label>
            <input className="input" value={form.stnk_name} onChange={(e) => setForm({ ...form, stnk_name: e.target.value })} placeholder="Kosongkan jika sama" />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Jenis Pelanggan</label>
            <select className="input" value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value as CustomerType })}>
              <option value="INDIVIDUAL">Perorangan</option>
              <option value="INSTITUTIONAL">Institusi/Tender</option>
            </select>
            <p style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>
              Pilih &quot;Institusi/Tender&quot; untuk klien pemerintah, kepolisian, atau perusahaan
              yang membayar lewat kontrak — ini yang muncul saat membuat Contract.
            </p>
          </div>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

type FilterMode = "all" | "institutional";

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading]     = useState(true);
  const [search, setSearch]       = useState("");
  const [filter, setFilter]       = useState<FilterMode>("all");
  const [showAdd, setShowAdd]     = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletingId, setDeletingId]   = useState<string | null>(null);

  const load = (mode: FilterMode) => {
    setLoading(true);
    customersApi.list(mode === "institutional" ? { customerType: "INSTITUTIONAL" } : {})
      .then(setCustomers)
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(filter); }, [filter]);

  const filtered = customers.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()));

  const handleDelete = async (customer: Customer) => {
    setDeleteError(null);
    setDeletingId(customer.id);
    try {
      await customersApi.remove(customer.id);
      setCustomers((prev) => prev.filter((c) => c.id !== customer.id));
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      // 409 from PROTECT — Principle 2 enforced. Show the backend's
      // own explanation rather than a generic "something went wrong."
      setDeleteError(message ?? "Gagal menghapus pelanggan.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Pelanggan</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{customers.length} pelanggan {filter !== "all" ? "(terfilter)" : "tercatat"}</p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Tambah Pelanggan</button>
      </div>

      {deleteError && (
        <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", padding: "11px 14px", borderRadius: 6, fontSize: 13.5, marginBottom: 18 }}>
          {deleteError}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={() => setFilter("all")} className={filter === "all" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13 }}>Semua</button>
        <button onClick={() => setFilter("institutional")} className={filter === "institutional" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <Briefcase size={14} /> Institusi/Tender
        </button>
        <div style={{ position: "relative", maxWidth: 260, marginLeft: "auto" }}>
          <Search size={15} style={{ position: "absolute", left: 12, top: 11, color: "var(--steel)" }} />
          <input className="input" style={{ paddingLeft: 34 }} placeholder="Cari nama pelanggan…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nama</th><th>Jenis</th><th>Telepon</th><th>Nama di STNK</th><th>Kendaraan</th><th></th></tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 600 }}>{c.name}</td>
                  <td>
                    {c.customer_type === "INSTITUTIONAL" && (
                      <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "var(--workshop)", background: "var(--workshop-lt)", whiteSpace: "nowrap" }}>
                        Institusi/Tender
                      </span>
                    )}
                  </td>
                  <td className="mono" style={{ fontSize: 13 }}>{c.phone || "—"}</td>
                  <td>{c.stnk_name || <span style={{ color: "var(--steel)" }}>Sama dengan nama</span>}</td>
                  <td className="mono">{c.vehicle_count}</td>
                  <td>
                    <button onClick={() => handleDelete(c)} disabled={deletingId === c.id}
                      style={{ background: "none", border: "none", color: "var(--steel)", display: "flex" }}>
                      {deletingId === c.id ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Trash2 size={15} />}
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>
                  {filter === "institutional" ? "Belum ada pelanggan bertipe Institusi/Tender" : "Belum ada pelanggan"}
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddCustomerModal
          onClose={() => setShowAdd(false)}
          onCreated={(c) => {
            if (filter === "all" || c.customer_type === "INSTITUTIONAL") {
              setCustomers((prev) => [c, ...prev]);
            }
          }}
        />
      )}
    </div>
  );
}
