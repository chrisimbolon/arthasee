"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/purchase-orders/page.tsx ===
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import { PurchaseOrder, purchaseOrdersApi, Supplier, suppliersApi } from "@/lib/api/purchasing";
import { Part, partsApi } from "@/lib/api/service";
import { Loader2, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(toNumber(value));
}

function statusPillType(status: PurchaseOrder["status"]): string {
  if (status === "CANCELLED") return "due";
  if (status === "FULLY_RECEIVED") return "ok";
  return "soon"; // DRAFT, ORDERED, PARTIALLY_RECEIVED
}

interface LineInput {
  part_id: string;
  quantity_ordered: string;
  unit_cost: string;
}

function emptyLine(): LineInput {
  return { part_id: "", quantity_ordered: "", unit_cost: "" };
}

function CreatePOModal({
  suppliers, parts, onClose, onCreated,
}: {
  suppliers: Supplier[]; parts: Part[]; onClose: () => void; onCreated: (po: PurchaseOrder) => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [orderDate, setOrderDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [expectedDate, setExpectedDate] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineInput[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateLine(i: number, patch: Partial<LineInput>) {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  function addLine() { setLines((prev) => [...prev, emptyLine()]); }
  function removeLine(i: number) { setLines((prev) => prev.filter((_, idx) => idx !== i)); }

  const filledLines = lines.filter((l) => l.part_id && toNumber(l.quantity_ordered) > 0 && toNumber(l.unit_cost) > 0);
  const canSubmit = !!supplierId && !!orderDate && filledLines.length > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const po = await purchaseOrdersApi.create({
        supplier: supplierId, order_date: orderDate,
        expected_date: expectedDate || undefined, notes: notes || undefined,
        lines: filledLines.map((l) => ({
          part: l.part_id, quantity_ordered: toNumber(l.quantity_ordered), unit_cost: toNumber(l.unit_cost),
        })),
      });
      onCreated(po);
      onClose();
    } catch {
      setError("Gagal membuat Purchase Order.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 560, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Buat Purchase Order</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Supplier</label>
            <select className="input" required value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Pilih supplier…</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Tanggal Pesan</label>
              <input className="input" type="date" required value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
            </div>
            <div>
              <label className="label">Perkiraan Tiba <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" type="date" value={expectedDate} onChange={(e) => setExpectedDate(e.target.value)} />
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <div className="label" style={{ marginBottom: 10 }}>Item Dipesan</div>
          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 10 }}>
              <div style={{ flex: 2 }}>
                {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Part</div>}
                <select className="input" value={line.part_id} onChange={(e) => updateLine(i, { part_id: e.target.value })}>
                  <option value="">Pilih part…</option>
                  {parts.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div style={{ width: 90 }}>
                {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Jumlah</div>}
                <input className="input" type="number" min={0} value={line.quantity_ordered} onChange={(e) => updateLine(i, { quantity_ordered: e.target.value })} placeholder="0" />
              </div>
              <div style={{ width: 130 }}>
                {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Harga Beli</div>}
                <input className="input" type="number" min={0} value={line.unit_cost} onChange={(e) => updateLine(i, { unit_cost: e.target.value })} placeholder="0" />
              </div>
              <button type="button" onClick={() => removeLine(i)} disabled={lines.length <= 1} className="btn-ghost" style={{ padding: "9px 10px" }}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <button type="button" onClick={addLine} className="btn-ghost" style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6, marginTop: 4, marginBottom: 20 }}>
            <Plus size={14} /> Tambah Item
          </button>

          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function PurchaseOrdersPage() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([purchaseOrdersApi.list(), suppliersApi.list(), partsApi.list()])
      .then(([o, s, p]) => { setOrders(o); setSuppliers(s); setParts(p); })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{orders.length} Purchase Order tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowCreate(true)}><Plus size={16} /> Buat Purchase Order</button>
      </div>

      <PurchasingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nomor</th><th>Supplier</th><th>Tanggal Pesan</th><th>Nilai Pesanan</th><th>Status</th></tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link href={`/dashboard/purchase-order-detail?id=${o.id}`} className="mono" style={{ color: "var(--rust)", textDecoration: "none", fontWeight: 600 }}>
                      {o.number}
                    </Link>
                  </td>
                  <td>{o.supplier_name}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(o.order_date).toLocaleDateString("id-ID")}</td>
                  <td className="mono">{formatRupiah(o.total_ordered_value)}</td>
                  <td><span className={`pill ${statusPillType(o.status)}`}>{o.status_display}</span></td>
                </tr>
              ))}
              {orders.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada Purchase Order tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreatePOModal
          suppliers={suppliers} parts={parts}
          onClose={() => setShowCreate(false)}
          onCreated={(po) => setOrders((prev) => [po, ...prev])}
        />
      )}
    </div>
  );
}
