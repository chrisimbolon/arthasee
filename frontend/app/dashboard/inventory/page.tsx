"use client";
// =============================================================================
// === frontend/app/dashboard/inventory/page.tsx ===
// Full rewrite — Menu Persediaan. Mirrors vehicles/page.tsx's
// established structure, same as the original. Real changes:
//   1. AddPartModal generalized into PartFormModal, handling both
//      create AND edit — partsApi.update() already existed in
//      service.ts with zero UI ever calling it; this finally wires
//      it up, which is exactly what a per-part minimum_stock needs
//      (backfilled parts need a way to be re-tuned afterward).
//   2. The low-stock badge logic now reads each part's OWN
//      minimum_stock instead of a hardcoded global constant.
//   3. A real stock summary row — the actual "Menu Persediaan"
//      report deliverable, with an honest note on which valuation
//      basis the total uses.
//   4. A per-part movement history modal — the real merged
//      PartUsage + StockAdjustment timeline from the new backend
//      endpoint.
// =============================================================================
import {
  Part, partsApi, StockAdjustment,
  stockAdjustmentsApi,
  StockMovement, StockSummary,
} from "@/lib/api/service";
import {
  AlertTriangle, Clock, Loader2, Package, Pencil, Plus, X,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

// ── Create/Edit part — one shared form, not two near-duplicates ───

function PartFormModal({
  editingPart, onClose, onSaved,
}: {
  editingPart?: Part | null;
  onClose: () => void;
  onSaved: (p: Part) => void;
}) {
  const isEdit = !!editingPart;
  const [form, setForm] = useState({
    name: editingPart?.name ?? "",
    sku: editingPart?.sku ?? "",
    unit: editingPart?.unit ?? "pcs",
    unit_price: editingPart?.unit_price ?? "",
    minimum_stock: editingPart?.minimum_stock ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const payload = {
        name: form.name, sku: form.sku, unit: form.unit,
        unit_price: Number(form.unit_price) || 0,
        minimum_stock: Number(form.minimum_stock) || 0,
      };
      const part = isEdit
        ? await partsApi.update(editingPart!.id, payload)
        : await partsApi.create(payload);
      onSaved(part);
      onClose();
    } catch {
      setError(isEdit ? "Gagal menyimpan perubahan part." : "Gagal menyimpan part.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 420, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>{isEdit ? "Ubah Part" : "Tambah Part"}</h2>
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            <div>
              <label className="label">Harga Satuan (Rp)</label>
              <input className="input" type="number" min={0} value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} placeholder="0" />
            </div>
            <div>
              <label className="label">Stok Minimum</label>
              <input className="input" type="number" min={0} value={form.minimum_stock} onChange={(e) => setForm({ ...form, minimum_stock: e.target.value })} placeholder="0" />
            </div>
          </div>
          <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14 }}>
            {isEdit
              ? "Stok Minimum menentukan kapan part ini muncul di filter \u201cStok Menipis\u201d \u2014 0 berarti tidak ada peringatan dari ambang batas ini."
              : "Stok awal dimulai dari 0 \u2014 gunakan \u201cTambah Stok\u201d setelah part dibuat untuk mencatat stok masuk pertama."}
          </p>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Stock adjustment — unchanged from the original page ──────────

function StockAdjustmentModal({ part, onClose, onAdjusted }: {
  part: Part; onClose: () => void; onAdjusted: (p: Part) => void;
}) {
  const [form, setForm] = useState<{ quantity_change: string; reason: StockAdjustment["reason"]; notes: string }>({
    quantity_change: "", reason: "restock", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
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

// ── Movement history — new, the real merged timeline ──────────────

function MovementHistoryModal({ part, onClose }: { part: Part; onClose: () => void }) {
  const [movements, setMovements] = useState<StockMovement[] | null>(null);

  useEffect(() => {
    partsApi.movements(part.id).then(setMovements);
  }, [part.id]);

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 460, maxHeight: "78vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Riwayat Pergerakan</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>{part.name}</p>

        {movements === null ? (
          <div style={{ textAlign: "center", padding: 24 }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : movements.length === 0 ? (
          <div style={{ textAlign: "center", padding: 24, color: "var(--steel)", fontSize: 13 }}>Belum ada pergerakan tercatat.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {movements.map((m, i) => {
              const qty = toNumber(m.quantity_change);
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "1px solid var(--line)", paddingBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{m.reason}</div>
                    <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{new Date(m.date).toLocaleString("id-ID")}</div>
                    {m.notes && <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 2 }}>{m.notes}</div>}
                  </div>
                  <span className="mono" style={{ fontWeight: 700, flexShrink: 0, color: qty >= 0 ? "var(--workshop)" : "var(--danger)" }}>
                    {qty >= 0 ? "+" : ""}{m.quantity_change}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Stock summary row — the real "Menu Persediaan" deliverable ────

function StockSummaryRow({ data }: { data: StockSummary | null }) {
  if (!data) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 32, color: "var(--steel)", marginBottom: 18 }}>
        <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>Total Part</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 700 }}>{data.total_parts}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>Nilai Stok</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 700 }}>{formatRupiah(data.total_stock_value)}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11.5, color: "var(--hazard-dark)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>Stok Menipis</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--hazard-dark)" }}>{data.low_stock_count}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11.5, color: "var(--danger)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>Stok Habis</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--danger)" }}>{data.out_of_stock_count}</div>
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--steel-lt)", marginTop: 8 }}>{data.total_stock_value_basis}</div>
    </div>
  );
}

// ── Page shell ─────────────────────────────────────────────────────

export default function InventoryPage() {
  const [parts, setParts] = useState<Part[]>([]);
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingPart, setEditingPart] = useState<Part | null>(null);
  const [adjustingPart, setAdjustingPart] = useState<Part | null>(null);
  const [historyPart, setHistoryPart] = useState<Part | null>(null);

  const load = (lowStock: boolean) => {
    setLoading(true);
    partsApi.list({ lowStock }).then(setParts).finally(() => setLoading(false));
  };

  useEffect(() => { load(lowStockOnly); }, [lowStockOnly]);
  useEffect(() => { partsApi.stockSummary().then(setSummary); }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Inventaris</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{parts.length} part {lowStockOnly ? "dengan stok menipis" : "tercatat"}</p>
        </div>
        <button className="btn-rust" onClick={() => setShowForm(true)}><Plus size={16} /> Tambah Part</button>
      </div>

      <StockSummaryRow data={summary} />

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        <button onClick={() => setLowStockOnly(false)} className={lowStockOnly ? "btn-ghost" : "btn-rust"} style={{ fontSize: 13 }}>Semua</button>
        <button onClick={() => setLowStockOnly(true)} className={lowStockOnly ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={14} /> Stok Menipis
        </button>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nama</th><th>SKU</th><th>Stok</th><th>Stok Min.</th><th>Harga Satuan</th><th></th></tr>
            </thead>
            <tbody>
              {parts.map((p) => {
                const stockNum = toNumber(p.current_stock);
                const minNum = toNumber(p.minimum_stock);
                // Real per-part logic, matching the backend exactly:
                // completely out always flags regardless of any
                // threshold; "low" only applies once a real,
                // nonzero threshold has been configured for this
                // specific part.
                const isOut = stockNum <= 0;
                const isLow = !isOut && minNum > 0 && stockNum <= minNum;
                return (
                  <tr key={p.id}>
                    <td style={{ display: "flex", alignItems: "center", gap: 8 }}><Package size={14} style={{ color: "var(--steel)" }} />{p.name}</td>
                    <td className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{p.sku || "—"}</td>
                    <td className="mono">
                      {p.current_stock} {p.unit}
                      {isOut && <span className="pill due" style={{ marginLeft: 8, fontSize: 11 }}>Habis</span>}
                      {isLow && <span className="pill due" style={{ marginLeft: 8, fontSize: 11 }}>Menipis</span>}
                    </td>
                    <td className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{minNum > 0 ? `${p.minimum_stock} ${p.unit}` : "—"}</td>
                    <td className="mono">{formatRupiah(p.unit_price)}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                        <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 8px" }} onClick={() => setEditingPart(p)} title="Ubah Part">
                          <Pencil size={13} />
                        </button>
                        <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 8px" }} onClick={() => setHistoryPart(p)} title="Riwayat Pergerakan">
                          <Clock size={13} />
                        </button>
                        <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} onClick={() => setAdjustingPart(p)}>
                          Sesuaikan Stok
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {parts.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>
                  {lowStockOnly ? "Tidak ada part dengan stok menipis" : "Belum ada part tercatat"}
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showForm && (
        <PartFormModal
          onClose={() => setShowForm(false)}
          onSaved={(p) => { setParts((prev) => [p, ...prev]); partsApi.stockSummary().then(setSummary); }}
        />
      )}
      {editingPart && (
        <PartFormModal
          editingPart={editingPart}
          onClose={() => setEditingPart(null)}
          onSaved={(updated) => {
            setParts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
            partsApi.stockSummary().then(setSummary);
          }}
        />
      )}
      {adjustingPart && (
        <StockAdjustmentModal
          part={adjustingPart}
          onClose={() => setAdjustingPart(null)}
          onAdjusted={(updated) => {
            setParts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
            partsApi.stockSummary().then(setSummary);
          }}
        />
      )}
      {historyPart && (
        <MovementHistoryModal part={historyPart} onClose={() => setHistoryPart(null)} />
      )}
    </div>
  );
}
