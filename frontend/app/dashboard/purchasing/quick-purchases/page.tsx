"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/quick-purchases/page.tsx ===
// Made's own confirmed exception, 25 Aug meeting — real, immediate
// spot purchases for HARIAN/MINGGUAN parts: "harga sekedar numpang
// lewat, tipe harian harus tetap terpotret dari inventory." No
// PurchaseOrder, no GoodsReceivedNote — this is the entire real
// entry point. Multi-line (Made's own confirmed call — staff often
// buy a few different consumables on one real receipt during a
// quick run), plus inline "Tambah Supplier" for an unregistered
// local shop ("toko baru").
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import {
  QuickPurchase, QuickPurchasePaymentMethod, quickPurchasesApi,
  Supplier, suppliersApi,
} from "@/lib/api/purchasing";
import { ItemType, Part, partsApi, VehicleBrand } from "@/lib/api/service";
import { Loader2, Plus, Trash2, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

interface LineInput {
  part_id: string;
  quantity: string;
  unit_cost: string;
}

function emptyLine(): LineInput {
  return { part_id: "", quantity: "", unit_cost: "" };
}

// Inline "Tambah Supplier" — Made's own confirmed request: staff
// must be able to add a genuinely new, not-yet-registered vendor
// ("toko baru") on the spot, right inside this same form, without
// leaving to a separate Supplier page first. Reuses
// suppliersApi.create() directly — no separate endpoint needed.
function InlineAddSupplier({ onAdded }: { onAdded: (s: Supplier) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    if (!name.trim()) return;
    setSaving(true); setError(null);
    try {
      const supplier = await suppliersApi.create({ name: name.trim() });
      onAdded(supplier);
      setName(""); setOpen(false);
    } catch {
      setError("Gagal menambah supplier.");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button type="button" className="btn-ghost" style={{ fontSize: 12, padding: "6px 10px", marginTop: 6 }} onClick={() => setOpen(true)}>
        <Plus size={12} /> Toko Baru
      </button>
    );
  }

  return (
    <div style={{ display: "flex", gap: 8, marginTop: 6, alignItems: "flex-start" }}>
      <div style={{ flex: 1 }}>
        <input
          className="input" style={{ fontSize: 13 }} placeholder="Nama toko/supplier baru"
          value={name} onChange={(e) => setName(e.target.value)} autoFocus
        />
        {error && <div style={{ fontSize: 11.5, color: "var(--danger)", marginTop: 4 }}>{error}</div>}
      </div>
      <button type="button" className="btn-rust" style={{ fontSize: 12, padding: "9px 12px" }} disabled={!name.trim() || saving} onClick={handleAdd}>
        {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Tambah"}
      </button>
      <button type="button" className="btn-ghost" style={{ fontSize: 12, padding: "9px 10px" }} onClick={() => setOpen(false)}>
        <X size={13} />
      </button>
    </div>
  );
}

// Small, local label map — same VehicleBrand real values the
// backend's own TextChoices define, matching the convention already
// established on the Spare Parts & Fluids page. Duplicated locally
// rather than imported from that page — pages shouldn't import from
// other pages, only from shared modules.
const VEHICLE_BRAND_LABELS: Record<Exclude<VehicleBrand, "">, string> = {
  TOYOTA: "Toyota", HONDA: "Honda", DAIHATSU: "Daihatsu",
  SUZUKI: "Suzuki", MITSUBISHI: "Mitsubishi",
};

// Inline "Part Baru" — Made's own confirmed request, 27 Aug meeting
// notes: "disediakan tampilan untuk menginput parts baru (belum ada
// nama parts tersebut di persediaan)" — staff needs a real way to
// add a genuinely new, not-yet-in-inventory part right inside this
// same quick-purchase flow, without leaving to a separate page
// first. Deliberately minimal — name, unit, and a real starting
// selling price (unit_price is a required backend field with no
// default; silently defaulting it to 0 would land a wrong-looking
// "Rp0" part in production data) — plus the one field Made's own
// note explicitly asked for, vehicle_brand. Everything else (fluid
// taxonomy, reorder cadence) stays editable later via the existing
// Part edit modal, same "can finish categorizing later" philosophy
// already established for every other part in this system.
function InlineAddPart({ onAdded }: { onAdded: (p: Part) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("pcs");
  const [unitPrice, setUnitPrice] = useState("");
  const [vehicleBrand, setVehicleBrand] = useState<VehicleBrand>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave = name.trim() && toNumber(unitPrice) > 0 && !saving;

  const handleAdd = async () => {
    if (!canSave) return;
    setSaving(true); setError(null);
    try {
      const part = await partsApi.create({
        name: name.trim(), unit, unit_price: toNumber(unitPrice),
        item_type: "SPARE_PART" as ItemType,
        vehicle_brand: vehicleBrand || undefined,
      });
      onAdded(part);
      setName(""); setUnitPrice(""); setVehicleBrand(""); setOpen(false);
    } catch {
      setError("Gagal menambah part baru.");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button type="button" className="btn-ghost" style={{ fontSize: 11.5, padding: "4px 8px", marginTop: 4 }} onClick={() => setOpen(true)}>
        <Plus size={11} /> Part Baru
      </button>
    );
  }

  return (
    <div style={{ marginTop: 6, marginBottom: 6, padding: 10, border: "1px solid var(--line)", borderRadius: 6, background: "var(--paper-2)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 8, marginBottom: 8 }}>
        <input
          className="input" style={{ fontSize: 13 }} placeholder="Nama part baru"
          value={name} onChange={(e) => setName(e.target.value)} autoFocus
        />
        <select className="input" style={{ fontSize: 13 }} value={unit} onChange={(e) => setUnit(e.target.value)}>
          <option value="pcs">pcs</option>
          <option value="liter">liter</option>
          <option value="set">set</option>
          <option value="botol">botol</option>
        </select>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
        <input
          className="input" style={{ fontSize: 13 }} type="number" min={0} placeholder="Harga Jual (Rp)"
          value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)}
        />
        <select className="input" style={{ fontSize: 13 }} value={vehicleBrand} onChange={(e) => setVehicleBrand(e.target.value as VehicleBrand)}>
          <option value="">Untuk kendaraan apa? (opsional)</option>
          {(Object.keys(VEHICLE_BRAND_LABELS) as Exclude<VehicleBrand, "">[]).map((key) => (
            <option key={key} value={key}>{VEHICLE_BRAND_LABELS[key]}</option>
          ))}
        </select>
      </div>
      {error && <div style={{ fontSize: 11.5, color: "var(--danger)", marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn-rust" style={{ fontSize: 12, padding: "7px 12px" }} disabled={!canSave} onClick={handleAdd}>
          {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Tambah Part"}
        </button>
        <button type="button" className="btn-ghost" style={{ fontSize: 12, padding: "7px 10px" }} onClick={() => setOpen(false)}>
          Batal
        </button>
      </div>
    </div>
  );
}


function CreateQuickPurchaseModal({
  suppliers, parts, onClose, onCreated, onSupplierAdded, onPartAdded,
}: {
  suppliers: Supplier[]; parts: Part[]; onClose: () => void;
  onCreated: (qp: QuickPurchase) => void; onSupplierAdded: (s: Supplier) => void;
  onPartAdded: (p: Part) => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<QuickPurchasePaymentMethod>("cash");
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
  const total = filledLines.reduce((sum, l) => sum + toNumber(l.quantity) * toNumber(l.unit_cost), 0);
  const canSubmit = !!supplierId && filledLines.length > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const qp = await quickPurchasesApi.create({
        supplier: supplierId, payment_method: paymentMethod,
        reference: reference || undefined, notes: notes || undefined,
        lines: filledLines.map((l) => ({
          part: l.part_id, quantity: toNumber(l.quantity), unit_cost: toNumber(l.unit_cost),
        })),
      });
      onCreated(qp);
      onClose();
    } catch (err) {
      const data = (err as { response?: { data?: { message?: string } } })?.response?.data;
      setError(data?.message || "Gagal mencatat pembelian.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 580, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Catat Pembelian Cepat</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          Untuk part Harian/Mingguan — dibeli langsung, dibayar di tempat, tanpa Purchase Order.
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 6 }}>
            <label className="label">Dibeli Dari</label>
            <select className="input" required value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Pilih supplier…</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <InlineAddSupplier onAdded={(s) => { onSupplierAdded(s); setSupplierId(s.id); }} />

          <div style={{ marginTop: 16, marginBottom: 14 }}>
            <label className="label">Metode Pembayaran</label>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className={paymentMethod === "cash" ? "btn-rust" : "btn-ghost"}
                style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
                onClick={() => setPaymentMethod("cash")}
              >
                Tunai
              </button>
              <button
                type="button"
                className={paymentMethod === "bank" ? "btn-rust" : "btn-ghost"}
                style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
                onClick={() => setPaymentMethod("bank")}
              >
                Transfer Bank
              </button>
            </div>
          </div>

          <div style={{ marginBottom: 14 }}>
            <label className="label">Referensi <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="No. nota/struk" />
          </div>

          <div className="label" style={{ marginBottom: 10 }}>Item Dibeli</div>
          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 10 }}>
              <div style={{ flex: 2 }}>
                {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Part</div>}
                <select className="input" value={line.part_id} onChange={(e) => updateLine(i, { part_id: e.target.value })}>
                  <option value="">Pilih part…</option>
                  {parts.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                <InlineAddPart onAdded={(p) => { onPartAdded(p); updateLine(i, { part_id: p.id }); }} />
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
          <button type="button" onClick={addLine} className="btn-ghost" style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6, marginTop: 4, marginBottom: 16 }}>
            <Plus size={14} /> Tambah Item
          </button>

          {total > 0 && (
            <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>
              Total: <span className="mono" style={{ fontWeight: 600, color: "var(--ink)" }}>{formatRupiah(total)}</span>
            </div>
          )}

          <div style={{ marginBottom: 20 }}>
            <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function QuickPurchasesPage() {
  const [purchases, setPurchases] = useState<QuickPurchase[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([quickPurchasesApi.list(), suppliersApi.list(), partsApi.list()])
      .then(([qp, s, p]) => { setPurchases(qp); setSuppliers(s); setParts(p); })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{purchases.length} pembelian cepat tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowCreate(true)}><Plus size={16} /> Catat Pembelian</button>
      </div>

      <PurchasingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nomor</th><th>Dibeli Dari</th><th>Item</th><th>Metode</th><th>Tanggal</th><th>Total Biaya</th></tr>
            </thead>
            <tbody>
              {purchases.map((qp) => (
                <tr key={qp.id}>
                  <td className="mono" style={{ color: "var(--rust)", fontWeight: 600 }}>{qp.number}</td>
                  <td>{qp.supplier_name}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>
                    {qp.line_items.map((li) => li.part_name).join(", ")}
                  </td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{qp.payment_method_display}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(qp.purchased_at).toLocaleDateString("id-ID")}</td>
                  <td className="mono">{formatRupiah(qp.total_cost)}</td>
                </tr>
              ))}
              {purchases.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada pembelian cepat tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateQuickPurchaseModal
          suppliers={suppliers} parts={parts}
          onClose={() => setShowCreate(false)}
          onCreated={(qp) => setPurchases((prev) => [qp, ...prev])}
          onSupplierAdded={(s) => setSuppliers((prev) => [...prev, s])}
          onPartAdded={(p) => setParts((prev) => [...prev, p])}
        />
      )}
    </div>
  );
}
