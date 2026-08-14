"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/suppliers/page.tsx ===
// =============================================================================
import { Supplier, suppliersApi } from "@/lib/api/purchasing";
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import { Loader2, Plus, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

function AddSupplierModal({ onClose, onCreated }: { onClose: () => void; onCreated: (s: Supplier) => void }) {
  const [form, setForm] = useState({ name: "", contact_person: "", phone: "", email: "", address: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const supplier = await suppliersApi.create(form);
      onCreated(supplier);
      onClose();
    } catch {
      setError("Gagal menyimpan supplier.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 420, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Tambah Supplier</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nama Supplier</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="PT Sparepart Jaya" />
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Kontak <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={form.contact_person} onChange={(e) => setForm({ ...form, contact_person: e.target.value })} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Telepon <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
            <div>
              <label className="label">Email <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Alamat <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </div>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function SuppliersPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    suppliersApi.list().then(setSuppliers).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{suppliers.length} supplier tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Tambah Supplier</button>
      </div>

      <PurchasingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nama</th><th>Kontak</th><th>Telepon</th><th>Email</th></tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{s.contact_person || "—"}</td>
                  <td className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{s.phone || "—"}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{s.email || "—"}</td>
                </tr>
              ))}
              {suppliers.length === 0 && (
                <tr><td colSpan={4} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada supplier tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddSupplierModal onClose={() => setShowAdd(false)} onCreated={(s) => setSuppliers((prev) => [...prev, s])} />
      )}
    </div>
  );
}
