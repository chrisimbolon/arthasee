"use client";
// =============================================================================
// === frontend/app/dashboard/inventory/page.tsx ===
// Sprint 7 base + real ledger-consistency margin visibility, 24 Aug
// 2026 (Made's own real WhatsApp request, via Sansan's review).
// "Harga Satuan" split into "Harga Beli (HPP)" and "Harga Jual",
// plus a real Margin % column — the honest business need this was
// actually for: catching a part accidentally priced below cost, not
// just a cosmetic table change.
// =============================================================================
import {
  Supplier,
  SupplierPartCode, supplierPartCodesApi,
  suppliersApi,
} from "@/lib/api/purchasing";
import {
  FluidBrand, ItemType, Part, partsApi, ReorderCadence, StockAdjustment,
  stockAdjustmentsApi, StockMovement, StockSummary, VehicleBrand, ViscosityGrade,
} from "@/lib/api/service";
import {
  AlertTriangle, ClipboardList, Clock, Loader2, Package, Pencil, Plus, X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

// ── Sprint 7, Task 7.1: taxonomy label maps — mirrors the backend's
// TextChoices display labels exactly (apps/inventory/models.py) ────

const ITEM_TYPE_LABELS: Record<ItemType, string> = {
  SPARE_PART: "Spare Part",
  FLUID: "Fluida",
};

const VEHICLE_BRAND_LABELS: Record<Exclude<VehicleBrand, "">, string> = {
  TOYOTA: "Toyota", HONDA: "Honda", DAIHATSU: "Daihatsu",
  SUZUKI: "Suzuki", MITSUBISHI: "Mitsubishi",
};

const FLUID_BRAND_LABELS: Record<Exclude<FluidBrand, "">, string> = {
  SHELL: "Shell", CASTROL: "Castrol", REPSOL: "Repsol",
  FASTRON: "Fastron", PERTAMINA_MEDITRAN: "Pertamina Meditran",
};

const VISCOSITY_LABELS: Record<Exclude<ViscosityGrade, "">, string> = {
  "10W-40": "10W-40", "5W-30": "5W-30",
  SAE_90: "Oli 90 (SAE 90)", SAE_140: "Oli 140 (SAE 140)",
};

const CADENCE_LABELS: Record<Exclude<ReorderCadence, "">, string> = {
  HARIAN: "Harian", MINGGUAN: "Mingguan",
  BULANAN: "Bulanan", TIGA_BULANAN: "3 Bulanan",
};

// ── Sprint 7, Task 7.1's real behavioral rule, mirrored exactly on
// the frontend: a HARIAN part is deliberately meant to sit at zero
// stock (e.g. an expensive, on-demand sensor) — it must NEVER surface
// as "Habis" or "Menipis", full stop, matching the backend's own
// belt-and-suspenders guard in PartListView and stock_summary(). ───

function isOutOfStock(p: Part): boolean {
  if (p.reorder_cadence === "HARIAN") return false;
  return toNumber(p.current_stock) <= 0;
}

function isLowStock(p: Part): boolean {
  if (p.reorder_cadence === "HARIAN") return false;
  const stockNum = toNumber(p.current_stock);
  const minNum = toNumber(p.minimum_stock);
  return stockNum > 0 && minNum > 0 && stockNum <= minNum;
}

// ── 24 Aug 2026: real margin visibility, Made's own stated need ───
// Deliberately returns null when cost_price is 0 — that means "no
// real GRN yet," not "free." Computing a margin against 0 would show
// a fake 100%, actively misleading (looks like pure profit when the
// real cost is genuinely unknown). null renders as "—" everywhere
// this is used, same honest-blank discipline as Kategori/Frekuensi.

function marginPercent(part: Part): number | null {
  const cost = toNumber(part.cost_price);
  const price = toNumber(part.unit_price);
  if (cost <= 0 || price <= 0) return null;
  return ((price - cost) / price) * 100;
}

// ── Supplier Part Code section — real multi-supplier reality.
// Only rendered when editing an EXISTING part (a brand-new part has
// no id yet to attach codes to). Self-contained: fetches its own
// suppliers list and existing codes, doesn't rely on the parent page
// having fetched either. ─────────────────────────────────────────

function SupplierCodesSection({ part }: { part: Part }) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [codes, setCodes] = useState<SupplierPartCode[]>([]);
  const [loading, setLoading] = useState(true);
  const [newSupplierId, setNewSupplierId] = useState("");
  const [newSku, setNewSku] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([suppliersApi.list(), supplierPartCodesApi.list(part.id)])
      .then(([s, c]) => { setSuppliers(s); setCodes(c); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [part.id]);

  const handleAdd = async () => {
    if (!newSupplierId || !newSku.trim()) return;
    setSaving(true); setError(null);
    try {
      await supplierPartCodesApi.set(part.id, { supplier: newSupplierId, supplier_sku: newSku.trim() });
      setNewSupplierId(""); setNewSku("");
      load();
    } catch {
      setError("Gagal menyimpan kode supplier.");
    } finally {
      setSaving(false);
    }
  };

  const availableSuppliers = suppliers.filter((s) => !codes.some((c) => c.supplier === s.id));

  return (
    <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14, marginBottom: 20 }}>
      <label className="label">Kode Supplier</label>
      <p style={{ fontSize: 12, color: "var(--steel)", marginBottom: 10 }}>
        Kode/SKU part ini menurut masing-masing supplier — membantu mencocokkan dengan surat jalan saat menerima barang.
      </p>
      {loading ? (
        <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />
      ) : (
        <>
          {codes.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              {codes.map((c) => (
                <div key={c.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                  <span>{c.supplier_name}</span>
                  <span className="mono" style={{ color: "var(--steel)" }}>{c.supplier_sku}</span>
                </div>
              ))}
            </div>
          )}
          {error && <div style={{ fontSize: 12, color: "var(--danger)", marginBottom: 8 }}>{error}</div>}
          {availableSuppliers.length > 0 ? (
            <div style={{ display: "flex", gap: 8 }}>
              <select className="input" style={{ flex: 1 }} value={newSupplierId} onChange={(e) => setNewSupplierId(e.target.value)}>
                <option value="">Pilih supplier…</option>
                {availableSuppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <input className="input" style={{ flex: 1 }} placeholder="Kode part" value={newSku} onChange={(e) => setNewSku(e.target.value)} />
              <button type="button" className="btn-ghost" disabled={!newSupplierId || !newSku.trim() || saving} onClick={handleAdd}>
                {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : "Tambah"}
              </button>
            </div>
          ) : suppliers.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--steel-lt)" }}>Belum ada supplier tercatat.</div>
          ) : (
            <div style={{ fontSize: 12, color: "var(--steel-lt)" }}>Semua supplier sudah memiliki kode untuk part ini.</div>
          )}
        </>
      )}
    </div>
  );
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
    item_type: (editingPart?.item_type ?? "SPARE_PART") as ItemType,
    vehicle_brand: (editingPart?.vehicle_brand ?? "") as VehicleBrand,
    fluid_brand: (editingPart?.fluid_brand ?? "") as FluidBrand,
    viscosity_grade: (editingPart?.viscosity_grade ?? "") as ViscosityGrade,
    reorder_cadence: (editingPart?.reorder_cadence ?? "") as ReorderCadence,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleItemTypeChange = (value: ItemType) => {
    setForm((prev) => ({
      ...prev,
      item_type: value,
      vehicle_brand: value === "SPARE_PART" ? prev.vehicle_brand : "",
      fluid_brand: value === "FLUID" ? prev.fluid_brand : "",
      viscosity_grade: value === "FLUID" ? prev.viscosity_grade : "",
    }));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const payload = {
        name: form.name, sku: form.sku, unit: form.unit,
        unit_price: Number(form.unit_price) || 0,
        minimum_stock: Number(form.minimum_stock) || 0,
        item_type: form.item_type,
        vehicle_brand: form.vehicle_brand,
        fluid_brand: form.fluid_brand,
        viscosity_grade: form.viscosity_grade,
        reorder_cadence: form.reorder_cadence,
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

  // 24 Aug 2026 — real, read-only context shown right next to where
  // Made sets the selling price, so he can actually see current cost
  // while deciding a sensible margin. cost_price is system-derived
  // (see Part's own backend docstring) — never an input here.
  const editMargin = isEdit && editingPart ? marginPercent(editingPart) : null;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 460, maxHeight: "88vh", overflowY: "auto", background: "var(--paper-3)" }}>
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
          <div style={{ marginBottom: 6 }}>
            <label className="label">Harga Jual (Rp)</label>
            <input className="input" type="number" min={0} value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} placeholder="0" />
          </div>
          {isEdit && editingPart && (
            <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 14 }}>
              {toNumber(editingPart.cost_price) > 0 ? (
                <>
                  Harga Beli (HPP) saat ini: <strong className="mono">{formatRupiah(editingPart.cost_price)}</strong>
                  {editMargin !== null && (
                    <span style={{ color: editMargin < 0 ? "var(--danger)" : "var(--steel)" }}>
                      {" "}— margin {editMargin.toFixed(1)}%
                      {editMargin < 0 && " (JUAL DI BAWAH HARGA BELI)"}
                    </span>
                  )}
                  {" "}(dari GRN terakhir, tidak bisa diubah manual)
                </>
              ) : (
                "Belum ada data HPP — part ini belum pernah menerima GRN."
              )}
            </div>
          )}
          {!isEdit && (
            <p style={{ fontSize: 12, color: "var(--steel-lt)", marginBottom: 14 }}>
              Harga Beli (HPP) akan terisi otomatis setelah part ini menerima GRN pertamanya.
            </p>
          )}
          <div style={{ marginBottom: 14 }}>
            <label className="label">Stok Minimum</label>
            <input className="input" type="number" min={0} value={form.minimum_stock} onChange={(e) => setForm({ ...form, minimum_stock: e.target.value })} placeholder="0" />
          </div>

          <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14, marginBottom: 14 }}>
            <label className="label">Jenis Item</label>
            <select className="input" value={form.item_type} onChange={(e) => handleItemTypeChange(e.target.value as ItemType)}>
              {(Object.keys(ITEM_TYPE_LABELS) as ItemType[]).map((key) => (
                <option key={key} value={key}>{ITEM_TYPE_LABELS[key]}</option>
              ))}
            </select>
          </div>

          {form.item_type === "SPARE_PART" ? (
            <div style={{ marginBottom: 14 }}>
              <label className="label">Merk Kendaraan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <select className="input" value={form.vehicle_brand} onChange={(e) => setForm({ ...form, vehicle_brand: e.target.value as VehicleBrand })}>
                <option value="">Belum dipilih</option>
                {(Object.keys(VEHICLE_BRAND_LABELS) as Exclude<VehicleBrand, "">[]).map((key) => (
                  <option key={key} value={key}>{VEHICLE_BRAND_LABELS[key]}</option>
                ))}
              </select>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <label className="label">Merk Fluida <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
                <select className="input" value={form.fluid_brand} onChange={(e) => setForm({ ...form, fluid_brand: e.target.value as FluidBrand })}>
                  <option value="">Belum dipilih</option>
                  {(Object.keys(FLUID_BRAND_LABELS) as Exclude<FluidBrand, "">[]).map((key) => (
                    <option key={key} value={key}>{FLUID_BRAND_LABELS[key]}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Tingkat Kekentalan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
                <select className="input" value={form.viscosity_grade} onChange={(e) => setForm({ ...form, viscosity_grade: e.target.value as ViscosityGrade })}>
                  <option value="">Belum dipilih</option>
                  {(Object.keys(VISCOSITY_LABELS) as Exclude<ViscosityGrade, "">[]).map((key) => (
                    <option key={key} value={key}>{VISCOSITY_LABELS[key]}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label className="label">Frekuensi Pengecekan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <select className="input" value={form.reorder_cadence} onChange={(e) => setForm({ ...form, reorder_cadence: e.target.value as ReorderCadence })}>
              <option value="">Belum dipilih</option>
              {(Object.keys(CADENCE_LABELS) as Exclude<ReorderCadence, "">[]).map((key) => (
                <option key={key} value={key}>{CADENCE_LABELS[key]}</option>
              ))}
            </select>
            <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>
              {form.reorder_cadence === "HARIAN"
                ? "Part Harian tidak akan pernah memicu peringatan \u201cStok Menipis\u201d atau \u201cStok Habis\u201d \u2014 stok 0 adalah kondisi yang benar untuk part ini."
                : "Menentukan tab kategori tempat part ini muncul di halaman Spare Parts & Fluids."}
            </p>
          </div>

          {isEdit && editingPart && <SupplierCodesSection part={editingPart} />}

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

// ── Stock adjustment — unchanged from Task 7.2 ────────────────────

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

// ── Movement history — unchanged from Task 7.2 ─────────────────────

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

// ── Stock summary row — unchanged from Task 7.2 ────────────────────

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
      <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 8 }}>{data.total_stock_value_basis}</div>
    </div>
  );
}

// ── Category cell — brand/viscosity summary for one row ───────────

function CategoryCell({ part }: { part: Part }) {
  if (part.item_type === "FLUID") {
    const brand = part.fluid_brand ? FLUID_BRAND_LABELS[part.fluid_brand] : null;
    const grade = part.viscosity_grade ? VISCOSITY_LABELS[part.viscosity_grade] : null;
    if (!brand && !grade) return <span style={{ color: "var(--steel-lt)" }}>—</span>;
    return <span>{[brand, grade].filter(Boolean).join(" • ")}</span>;
  }
  const brand = part.vehicle_brand ? VEHICLE_BRAND_LABELS[part.vehicle_brand] : null;
  return brand ? <span>{brand}</span> : <span style={{ color: "var(--steel-lt)" }}>—</span>;
}

// ── Page shell ─────────────────────────────────────────────────────

export default function InventoryPage() {
  const router = useRouter();
  const [parts, setParts] = useState<Part[]>([]);
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"ALL" | "HARIAN" | "MINGGUAN" | "BULANAN" | "TIGA_BULANAN" | "UNSET">("ALL");
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingPart, setEditingPart] = useState<Part | null>(null);
  const [adjustingPart, setAdjustingPart] = useState<Part | null>(null);
  const [historyPart, setHistoryPart] = useState<Part | null>(null);

  const CADENCE_TABS: { key: typeof activeTab; label: string }[] = [
    { key: "ALL", label: "Semua" },
    { key: "HARIAN", label: "Harian" },
    { key: "MINGGUAN", label: "Mingguan" },
    { key: "BULANAN", label: "Bulanan" },
    { key: "TIGA_BULANAN", label: "3 Bulanan" },
    { key: "UNSET", label: "Belum Dikategorikan" },
  ];

  const loadAll = () => {
    setLoading(true);
    partsApi.list().then(setParts).finally(() => setLoading(false));
  };

  useEffect(() => { loadAll(); }, []);
  useEffect(() => { partsApi.stockSummary().then(setSummary); }, []);

  const visibleParts = useMemo(() => {
    let result = parts;
    if (activeTab === "UNSET") {
      result = result.filter((p) => !p.reorder_cadence);
    } else if (activeTab !== "ALL") {
      result = result.filter((p) => p.reorder_cadence === activeTab);
    }
    if (lowStockOnly) {
      result = result.filter((p) => isOutOfStock(p) || isLowStock(p));
    }
    return result;
  }, [parts, activeTab, lowStockOnly]);

  const refreshSummary = () => partsApi.stockSummary().then(setSummary);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Spare Parts & Fluids</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{visibleParts.length} part {lowStockOnly ? "dengan stok menipis" : "tercatat"}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn-ghost"
            style={{ display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => {
              const cadenceHint = activeTab !== "ALL" && activeTab !== "UNSET" ? `?cadence=${activeTab}` : "";
              router.push(`/dashboard/inventory/stock-opname${cadenceHint}`);
            }}
          >
            <ClipboardList size={16} /> Mulai Stock Opname
          </button>
          <button className="btn-rust" onClick={() => setShowForm(true)}><Plus size={16} /> Tambah Part</button>
        </div>
      </div>

      <StockSummaryRow data={summary} />

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        {CADENCE_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={activeTab === tab.key ? "btn-rust" : "btn-ghost"}
            style={{ fontSize: 13 }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        <button
          onClick={() => setLowStockOnly((prev) => !prev)}
          className={lowStockOnly ? "btn-rust" : "btn-ghost"}
          style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
        >
          <AlertTriangle size={14} /> Stok Menipis
        </button>
      </div>

      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Nama</th><th>SKU</th><th>Kategori</th><th>Frekuensi</th><th>Stok</th><th>Stok Min.</th>
                <th>Harga Beli (HPP)</th><th>Harga Jual</th><th>Margin</th><th></th>
              </tr>
            </thead>
            <tbody>
              {visibleParts.map((p) => {
                const isOut = isOutOfStock(p);
                const isLow = isLowStock(p);
                const margin = marginPercent(p);
                const hasCost = toNumber(p.cost_price) > 0;
                return (
                  <tr key={p.id}>
                    <td style={{ display: "flex", alignItems: "center", gap: 8 }}><Package size={14} style={{ color: "var(--steel)" }} />{p.name}</td>
                    <td className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{p.sku || "—"}</td>
                    <td style={{ fontSize: 13 }}><CategoryCell part={p} /></td>
                    <td style={{ fontSize: 13, color: "var(--steel)" }}>
                      {p.reorder_cadence ? CADENCE_LABELS[p.reorder_cadence] : <span style={{ color: "var(--steel-lt)" }}>—</span>}
                    </td>
                    <td className="mono">
                      {p.current_stock} {p.unit}
                      {isOut && <span className="pill due" style={{ marginLeft: 8, fontSize: 11 }}>Habis</span>}
                      {isLow && <span className="pill due" style={{ marginLeft: 8, fontSize: 11 }}>Menipis</span>}
                    </td>
                    <td className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{toNumber(p.minimum_stock) > 0 ? `${p.minimum_stock} ${p.unit}` : "—"}</td>
                    <td className="mono" style={{ color: hasCost ? undefined : "var(--steel-lt)" }}>
                      {hasCost ? formatRupiah(p.cost_price) : "—"}
                    </td>
                    <td className="mono">{formatRupiah(p.unit_price)}</td>
                    <td className="mono" style={{ color: margin === null ? "var(--steel-lt)" : margin < 0 ? "var(--danger)" : "var(--workshop)" }}>
                      {margin === null ? "—" : `${margin.toFixed(1)}%`}
                    </td>
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
              {visibleParts.length === 0 && (
                <tr><td colSpan={10} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>
                  {lowStockOnly ? "Tidak ada part dengan stok menipis di kategori ini" : "Tidak ada part di kategori ini"}
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showForm && (
        <PartFormModal
          onClose={() => setShowForm(false)}
          onSaved={(p) => { setParts((prev) => [p, ...prev]); refreshSummary(); }}
        />
      )}
      {editingPart && (
        <PartFormModal
          editingPart={editingPart}
          onClose={() => setEditingPart(null)}
          onSaved={(updated) => {
            setParts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
            refreshSummary();
          }}
        />
      )}
      {adjustingPart && (
        <StockAdjustmentModal
          part={adjustingPart}
          onClose={() => setAdjustingPart(null)}
          onAdjusted={(updated) => {
            setParts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
            refreshSummary();
          }}
        />
      )}
      {historyPart && (
        <MovementHistoryModal part={historyPart} onClose={() => setHistoryPart(null)} />
      )}
    </div>
  );
}
