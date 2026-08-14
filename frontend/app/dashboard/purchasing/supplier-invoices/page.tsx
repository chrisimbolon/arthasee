"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/supplier-invoices/page.tsx ===
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import {
  GoodsReceivedNote, goodsReceivedNotesApi, Supplier,
  SupplierInvoice, supplierInvoicesApi,
  suppliersApi,
} from "@/lib/api/purchasing";
import { Loader2, Plus, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

function CreateInvoiceModal({
  suppliers, grns, onClose, onCreated,
}: {
  suppliers: Supplier[]; grns: GoodsReceivedNote[]; onClose: () => void; onCreated: (i: SupplierInvoice) => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [amount, setAmount] = useState("");
  const [invoiceDate, setInvoiceDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [dueDate, setDueDate] = useState("");
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState("");
  const [selectedGrnIds, setSelectedGrnIds] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only GRNs from the chosen supplier that DON'T already have an
  // invoice — the real, honest set of what this new invoice could
  // legitimately cover.
  const eligibleGrns = grns.filter((g) => g.supplier === supplierId && !g.supplier_invoice);
  const selectedTotal = eligibleGrns
    .filter((g) => selectedGrnIds.has(g.id))
    .reduce((sum, g) => sum + toNumber(g.total_cost), 0);

  function toggleGrn(id: string) {
    setSelectedGrnIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  const canSubmit = !!supplierId && toNumber(amount) > 0 && !!invoiceDate && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const invoice = await supplierInvoicesApi.create({
        supplier: supplierId, amount: toNumber(amount), invoice_date: invoiceDate,
        due_date: dueDate || undefined,
        supplier_invoice_number: supplierInvoiceNumber || undefined,
        goods_received_note_ids: Array.from(selectedGrnIds),
      });
      onCreated(invoice);
      onClose();
    } catch {
      setError("Gagal menyimpan invoice supplier.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 520, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Catat Invoice Supplier</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Supplier</label>
            <select className="input" required value={supplierId} onChange={(e) => { setSupplierId(e.target.value); setSelectedGrnIds(new Set()); }}>
              <option value="">Pilih supplier…</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          {supplierId && (
            <div style={{ marginBottom: 16 }}>
              <label className="label">GRN Terkait <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              {eligibleGrns.length === 0 ? (
                <div style={{ fontSize: 12.5, color: "var(--steel)" }}>Tidak ada GRN yang belum ditagih dari supplier ini.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {eligibleGrns.map((g) => (
                    <label key={g.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                      <input type="checkbox" checked={selectedGrnIds.has(g.id)} onChange={() => toggleGrn(g.id)} />
                      <span className="mono">{g.number}</span>
                      <span style={{ color: "var(--steel)" }}>— {formatRupiah(g.total_cost)}</span>
                    </label>
                  ))}
                  {selectedGrnIds.size > 0 && (
                    <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 2 }}>
                      Total GRN dipilih: <span className="mono">{formatRupiah(selectedTotal)}</span> — bandingkan dengan jumlah di invoice asli supplier.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label className="label">Jumlah (Rp)</label>
            <input className="input" type="number" min={0} required value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Sesuai invoice asli dari supplier" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Tanggal Invoice</label>
              <input className="input" type="date" required value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
            </div>
            <div>
              <label className="label">Jatuh Tempo <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">No. Invoice Supplier <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={supplierInvoiceNumber} onChange={(e) => setSupplierInvoiceNumber(e.target.value)} />
          </div>

          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function SupplierInvoicesPage() {
  const [invoices, setInvoices] = useState<SupplierInvoice[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [grns, setGrns] = useState<GoodsReceivedNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([supplierInvoicesApi.list(), suppliersApi.list(), goodsReceivedNotesApi.list()])
      .then(([i, s, g]) => { setInvoices(i); setSuppliers(s); setGrns(g); })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{invoices.length} invoice supplier tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowCreate(true)}><Plus size={16} /> Catat Invoice</button>
      </div>

      <PurchasingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nomor</th><th>Supplier</th><th>Jumlah</th><th>Tanggal</th><th>Jatuh Tempo</th><th>Status</th></tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id}>
                  <td>
                    <Link href={`/dashboard/supplier-invoice-detail?id=${inv.id}`} className="mono" style={{ color: "var(--rust)", textDecoration: "none", fontWeight: 600 }}>
                      {inv.number}
                    </Link>
                  </td>
                  <td>{inv.supplier_name}</td>
                  <td className="mono">{formatRupiah(inv.amount)}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(inv.invoice_date).toLocaleDateString("id-ID")}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{inv.due_date ? new Date(inv.due_date).toLocaleDateString("id-ID") : "—"}</td>
                  <td><span className={`pill ${inv.status === "PAID" ? "ok" : "due"}`}>{inv.status === "PAID" ? "Lunas" : "Belum Dibayar"}</span></td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada invoice supplier tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateInvoiceModal
          suppliers={suppliers} grns={grns}
          onClose={() => setShowCreate(false)}
          onCreated={(i) => setInvoices((prev) => [i, ...prev])}
        />
      )}
    </div>
  );
}
