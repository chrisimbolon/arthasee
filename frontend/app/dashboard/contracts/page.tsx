"use client";
// =============================================================================
// === frontend/app/dashboard/contracts/page.tsx ===
// Same shape as vehicles/page.tsx — a table + a create modal. One
// deliberate difference: on successful creation, this redirects
// straight into contract-detail rather than just closing the modal
// and staying on the list. A brand-new Contract has zero vehicles
// and zero line items until an Excel file gets uploaded — sitting on
// the list page after creating one has nothing useful to show, and
// the obvious next action is always "now upload the Excel." Same
// reasoning as WorkOrdersSection/EstimatesSection's own
// createAndOpen pattern on vehicle-detail, not the plain
// stay-on-the-list pattern this file's own AddVehicleModal uses.
// =============================================================================
import { Contract, contractsApi } from "@/lib/api/contracts";
import { Customer, customersApi } from "@/lib/api/service";
import { Briefcase, Loader2, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const STATUS_LABEL: Record<string, string> = {
  ACTIVE: "Aktif", EXPIRED: "Berakhir", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<string, string> = {
  ACTIVE: "#2e7d4f", EXPIRED: "var(--steel)", CANCELLED: "var(--danger)",
};

function AddContractModal({ customers, onClose, onCreated }: {
  customers: Customer[]; onClose: () => void; onCreated: (c: Contract) => void;
}) {
  const [form, setForm] = useState({
    customer: "", title: "", fiscal_year: new Date().getFullYear(), termin_count: 4 as 3 | 4,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const contract = await contractsApi.create(form);
      onCreated(contract);
    } catch {
      setError("Gagal membuat contract. Pastikan semua field terisi dengan benar.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, overflowY: "auto", padding: "40px 0" }}>
      <div className="card" style={{ width: 460, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Buat Contract</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Klien Institusi</label>
            {customers.length === 0 ? (
              <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", padding: "9px 12px", borderRadius: 5, fontSize: 12.5, marginBottom: 8 }}>
                Belum ada pelanggan bertipe &quot;Institusi/Tender&quot; — tambahkan dulu lewat halaman Pelanggan sebelum bisa membuat contract.
              </div>
            ) : null}
            <select className="input" required disabled={customers.length === 0} value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}>
              <option value="">— Pilih Klien —</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <p style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>
              Hanya menampilkan pelanggan bertipe &quot;Institusi/Tender&quot;. Belum ada di daftar?
              Tambahkan atau ubah jenisnya lewat halaman Pelanggan.
            </p>
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Judul Pekerjaan</label>
            <input className="input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Pengadaan Pemeliharaan Kendaraan R4/R6" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            <div>
              <label className="label">Tahun Anggaran</label>
              <input className="input" type="number" required value={form.fiscal_year} onChange={(e) => setForm({ ...form, fiscal_year: Number(e.target.value) })} />
            </div>
            <div>
              <label className="label">Jumlah Termin</label>
              <select className="input" value={form.termin_count} onChange={(e) => setForm({ ...form, termin_count: Number(e.target.value) as 3 | 4 })}>
                <option value={3}>3x per tahun</option>
                <option value={4}>4x per tahun</option>
              </select>
            </div>
          </div>

          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Buat & Lanjut Unggah Excel"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ContractsPage() {
  const router = useRouter();
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    contractsApi.list().then(setContracts).finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    // Now a real backend filter — apps.service.views' CustomerListView
    // was reviewed and confirmed to support ?customer_type=, so this
    // no longer needs the client-side workaround that fetched every
    // customer and filtered in the browser.
    customersApi.list({ customerType: "INSTITUTIONAL" }).then(setCustomers);
  }, []);

  const handleCreated = (contract: Contract) => {
    // Straight into contract-detail — see file header comment for why
    // this doesn't just close the modal and stay here.
    router.push(`/dashboard/contract-detail?id=${contract.id}`);
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Kontrak</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{contracts.length} contract tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Buat Contract</button>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : contracts.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Briefcase size={22} style={{ marginBottom: 10, opacity: 0.5 }} />
            <p style={{ fontSize: 14 }}>Belum ada contract. Klien institusi (tender/pemerintah) dicatat di sini.</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Judul Pekerjaan</th><th>Klien</th><th>Tahun</th><th>Termin</th><th>Status</th></tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <tr key={c.id}>
                  <td><Link href={`/dashboard/contract-detail?id=${c.id}`} style={{ color: "var(--rust)", fontWeight: 600 }}>{c.title}</Link></td>
                  <td>{c.customer_name}</td>
                  <td className="mono">{c.fiscal_year}</td>
                  <td className="mono">{c.termin_count}x</td>
                  <td>
                    <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[c.status] }}>
                      {STATUS_LABEL[c.status]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddContractModal customers={customers} onClose={() => setShowAdd(false)} onCreated={handleCreated} />
      )}
    </div>
  );
}
