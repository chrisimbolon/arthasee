"use client";
// =============================================================================
// === frontend/app/dashboard/inventory/page.tsx ===
// New page, Sprint 1. Mirrors vehicles/page.tsx's structure
// deliberately — same modal-for-create pattern, same table shape,
// same className conventions (card, btn-rust, btn-ghost, input,
// label, mono, pill) — so this doesn't read as a bolted-on page in
// a different style.
// =============================================================================
import { Part, partsApi, StockAdjustment, stockAdjustmentsApi } from "@/lib/api/service";
import { AlertTriangle, Loader2, Package, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

const LOW_STOCK_THRESHOLD = 5; // mirrors PartListView.LOW_STOCK_THRESHOLD on the backend — display-only, the real filter still runs server-side via ?low_stock=true

function AddPartModal({ onClose, onCreated }: { onClose: () => void; onCreated: (p: Part) => void }) {
  const [form, setForm] = useState({ name: "", sku: "", unit: "pcs", unit_price: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const part = await partsApi.create({ ...form, unit_price: Number(form.unit_price) || 0 });
      onCreated(part);
      onClose();
    } catch {
      setError("Gagal menyimpan part.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 420, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Tambah Part</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nama Part</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Busi, Filter Oli, Oli Mesin" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">SKU <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} />
            </div>
            <div>
              <label className="label">Satuan</label>
              <select className="input" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>
                <option value="pcs">pcs</option>
                <option value="liter">liter</option>
                <option value="set">set</option>
                <option value="botol">botol</option>
              </select>
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Harga Satuan (Rp)</label>
            <input className="input" type="number" min={0} value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} placeholder="0" />
          </div>
          <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14 }}>
            Stok awal dimulai dari 0 — gunakan &quot;Tambah Stok&quot; setelah part dibuat untuk mencatat stok masuk pertama.
          </p>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

function StockAdjustmentModal({ part, onClose, onAdjusted }: {
  part: Part; onClose: () => void; onAdjusted: (p: Part) => void;
}) {
  const [form, setForm] = useState<{ quantity_change: string; reason: StockAdjustment["reason"]; notes: string }>({
    quantity_change: "", reason: "restock", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const signedQty = form.reason === "restock"
        ? Math.abs(Number(form.quantity_change))
        : -Math.abs(Number(form.quantity_change));
      const adjustment = await stockAdjustmentsApi.create(part.id, {
        quantity_change: signedQty, reason: form.reason, notes: form.notes,
      });
      onAdjusted({ ...part, current_stock: adjustment.resulting_stock });
      onClose();
    } catch {
      setError("Gagal menyimpan penyesuaian stok.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 420, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Sesuaikan Stok</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          {part.name} — stok saat ini: <span className="mono">{part.current_stock} {part.unit}</span>
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Alasan</label>
            <select className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value as StockAdjustment["reason"] })}>
              <option value="restock">Restock / Pembelian (+)</option>
              <option value="correction">Koreksi Stok (−)</option>
              <option value="damage">Rusak / Hilang (−)</option>
            </select>
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Jumlah</label>
            <input className="input" type="number" min={0} step="0.01" required value={form.quantity_change} onChange={(e) => setForm({ ...form, quantity_change: e.target.value })} />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function InventoryPage() {
  const [parts, setParts]         = useState<Part[]>([]);
  const [loading, setLoading]     = useState(true);
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [showAdd, setShowAdd]     = useState(false);
  const [adjustingPart, setAdjustingPart] = useState<Part | null>(null);

  const load = (lowStock: boolean) => {
    setLoading(true);
    partsApi.list({ lowStock }).then(setParts).finally(() => setLoading(false));
  };

  useEffect(() => { load(lowStockOnly); }, [lowStockOnly]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Inventaris</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{parts.length} part {lowStockOnly ? "dengan stok menipis" : "tercatat"}</p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Tambah Part</button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        <button onClick={() => setLowStockOnly(false)} className={lowStockOnly ? "btn-ghost" : "btn-rust"} style={{ fontSize: 13 }}>Semua</button>
        <button onClick={() => setLowStockOnly(true)} className={lowStockOnly ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={14} /> Stok Menipis (≤ {LOW_STOCK_THRESHOLD})
        </button>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nama</th><th>SKU</th><th>Stok</th><th>Harga Satuan</th><th></th></tr>
            </thead>
            <tbody>
              {parts.map((p) => {
                const stockNum = Number(p.current_stock);
                return (
                  <tr key={p.id}>
                    <td style={{ display: "flex", alignItems: "center", gap: 8 }}><Package size={14} style={{ color: "var(--steel)" }} />{p.name}</td>
                    <td className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{p.sku || "—"}</td>
                    <td className="mono">
                      {p.current_stock} {p.unit}
                      {stockNum <= 0 && <span className="pill due" style={{ marginLeft: 8, fontSize: 11 }}>Habis</span>}
                      {stockNum > 0 && stockNum <= LOW_STOCK_THRESHOLD && <span className="pill due" style={{ marginLeft: 8, fontSize: 11 }}>Menipis</span>}
                    </td>
                    <td className="mono">Rp {Number(p.unit_price).toLocaleString("id-ID")}</td>
                    <td>
                      <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} onClick={() => setAdjustingPart(p)}>
                        Sesuaikan Stok
                      </button>
                    </td>
                  </tr>
                );
              })}
              {parts.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>
                  {lowStockOnly ? "Tidak ada part dengan stok menipis" : "Belum ada part tercatat"}
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddPartModal onClose={() => setShowAdd(false)} onCreated={(p) => setParts((prev) => [p, ...prev])} />
      )}
      {adjustingPart && (
        <StockAdjustmentModal
          part={adjustingPart}
          onClose={() => setAdjustingPart(null)}
          onAdjusted={(updated) => setParts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))}
        />
      )}
    </div>
  );
}
