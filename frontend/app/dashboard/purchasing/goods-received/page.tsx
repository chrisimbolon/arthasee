"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/goods-received/page.tsx ===
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import { GoodsReceivedNote, goodsReceivedNotesApi, Supplier, suppliersApi } from "@/lib/api/purchasing";
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

interface LineInput {
  part_id: string;
  quantity: string;
  unit_cost: string;
}

function emptyLine(): LineInput {
  return { part_id: "", quantity: "", unit_cost: "" };
}

function CreateGrnModal({
  suppliers, parts, onClose, onCreated,
}: {
  suppliers: Supplier[]; parts: Part[]; onClose: () => void; onCreated: (g: GoodsReceivedNote) => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineInput[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateLine(i: number, patch: Partial<LineInput>) {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  function addLine() { setLines((prev) => [...prev, emptyLine()]); }
  function removeLine(i: number) { setLines((prev) => prev.filter((_, idx) => idx !== i)); }

  const filledLines = lines.filter((l) => l.part_id && toNumber(l.quantity) > 0 && toNumber(l.unit_cost) > 0);
  const canSubmit = !!supplierId && filledLines.length > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const grn = await goodsReceivedNotesApi.create({
        supplier: supplierId,
        reference: reference || undefined,
        notes: notes || undefined,
        lines: filledLines.map((l) => ({
          part: l.part_id, quantity: toNumber(l.quantity), unit_cost: toNumber(l.unit_cost),
        })),
      });
      onCreated(grn);
      onClose();
    } catch {
      setError("Gagal mencatat penerimaan barang.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 560, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Catat Penerimaan Barang</h2>
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            <div>
              <label className="label">Referensi <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="No. surat jalan" />
            </div>
            <div>
              <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
          </div>

          <div className="label" style={{ marginBottom: 10 }}>Item Diterima</div>
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
                <input className="input" type="number" min={0} value={line.quantity} onChange={(e) => updateLine(i, { quantity: e.target.value })} placeholder="0" />
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

export default function GoodsReceivedNotesPage() {
  const [grns, setGrns] = useState<GoodsReceivedNote[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([goodsReceivedNotesApi.list(), suppliersApi.list(), partsApi.list()])
      .then(([g, s, p]) => { setGrns(g); setSuppliers(s); setParts(p); })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{grns.length} penerimaan barang tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowCreate(true)}><Plus size={16} /> Catat Penerimaan</button>
      </div>

      <PurchasingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nomor</th><th>Supplier</th><th>Diterima</th><th>Total Biaya</th><th>Status</th></tr>
            </thead>
            <tbody>
              {grns.map((g) => (
                <tr key={g.id}>
                  <td>
                    <Link href={`/dashboard/goods-received-detail?id=${g.id}`} className="mono" style={{ color: "var(--rust)", textDecoration: "none", fontWeight: 600 }}>
                      {g.number}
                    </Link>
                  </td>
                  <td>{g.supplier_name}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(g.received_at).toLocaleDateString("id-ID")}</td>
                  <td className="mono">{formatRupiah(g.total_cost)}</td>
                  <td>
                    <span className={`pill ${g.supplier_invoice ? "ok" : "soon"}`}>
                      {g.supplier_invoice ? "Sudah Ditagih" : "Belum Ditagih"}
                    </span>
                  </td>
                </tr>
              ))}
              {grns.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada penerimaan barang tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateGrnModal
          suppliers={suppliers} parts={parts}
          onClose={() => setShowCreate(false)}
          onCreated={(g) => setGrns((prev) => [g, ...prev])}
        />
      )}
    </div>
  );
}
