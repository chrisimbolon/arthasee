"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/goods-received/page.tsx ===
// Adds inline supplier-code capture: when a PO line's part has no
// code on file yet for THAT PO's supplier, a lightweight optional
// input appears right on the receiving row — captures the code at
// the exact moment staff have the vendor's surat jalan in hand
// (Chris and Made's own confirmed call). Saved via a SEPARATE call
// to supplierPartCodesApi.set() after the GRN itself saves — kept
// out of the GRN creation payload entirely, so GRN creation stays
// atomic and simple; code capture is a secondary, best-effort action.
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import { GoodsReceivedNote, goodsReceivedNotesApi, PurchaseOrder, purchaseOrdersApi, supplierPartCodesApi } from "@/lib/api/purchasing";
import { AlertTriangle, CheckCircle2, Loader2, Plus, X } from "lucide-react";
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

interface LineState {
  quantity: string;
  unit_cost: string;
  supplier_sku_input: string;
}

function CreateGrnModal({
  purchaseOrders, onClose, onCreated,
}: {
  purchaseOrders: PurchaseOrder[]; onClose: () => void; onCreated: (g: GoodsReceivedNote) => void;
}) {
  const [poId, setPoId] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lineInputs, setLineInputs] = useState<Record<string, LineState>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedWithWarnings, setSavedWithWarnings] = useState<string[] | null>(null);

  const selectedPo = purchaseOrders.find((p) => p.id === poId) ?? null;

  useEffect(() => {
    if (!selectedPo) { setLineInputs({}); return; }
    const seeded: Record<string, LineState> = {};
    for (const li of selectedPo.line_items) {
      seeded[li.id] = { quantity: "", unit_cost: li.unit_cost, supplier_sku_input: "" };
    }
    setLineInputs(seeded);
  }, [poId]);

  function updateLine(lineId: string, patch: Partial<LineState>) {
    setLineInputs((prev) => ({ ...prev, [lineId]: { ...prev[lineId], ...patch } }));
  }

  const filledLines = selectedPo
    ? selectedPo.line_items
        .map((li) => ({ li, input: lineInputs[li.id] }))
        .filter((entry): entry is { li: typeof entry.li; input: LineState } =>
          !!entry.input && toNumber(entry.input.quantity) > 0 && toNumber(entry.input.unit_cost) > 0)
    : [];

  const canSubmit = !!selectedPo && filledLines.length > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedPo) return;
    setSaving(true); setError(null);
    try {
      const { grn, warnings } = await goodsReceivedNotesApi.create({
        purchase_order: selectedPo.id,
        reference: reference || undefined,
        notes: notes || undefined,
        lines: filledLines.map(({ li, input }) => ({
          purchase_order_line_item: li.id,
          quantity: toNumber(input.quantity), unit_cost: toNumber(input.unit_cost),
        })),
      });

      // Best-effort supplier-code capture — a real, secondary action,
      // never allowed to block or fail the GRN itself (already saved
      // by this point regardless). Fire-and-forget per line where
      // staff actually typed a code.
      const codesToSave = filledLines.filter(({ input }) => input.supplier_sku_input.trim());
      await Promise.all(
        codesToSave.map(({ li, input }) =>
          supplierPartCodesApi.set(li.part, {
            supplier: selectedPo.supplier, supplier_sku: input.supplier_sku_input.trim(),
          }).catch(() => {
            // Deliberately swallowed — a failed code save must never
            // undo or block an already-successful GRN. Worst case,
            // staff re-enters it next time from the Part edit modal.
          })
        )
      );

      onCreated(grn);
      if (warnings.length > 0) {
        setSavedWithWarnings(warnings);
      } else {
        onClose();
      }
    } catch (err) {
      const data = (err as { response?: { data?: { message?: string } } })?.response?.data;
      setError(data?.message || "Gagal mencatat penerimaan barang.");
    } finally {
      setSaving(false);
    }
  };

  if (savedWithWarnings) {
    return (
      <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
        <div className="card" style={{ width: 480, background: "var(--paper-3)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <CheckCircle2 size={20} style={{ color: "var(--workshop)" }} />
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Penerimaan Tersimpan</h2>
          </div>
          <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>
            Barang sudah tercatat dan stok sudah diperbarui. Perhatikan hal berikut sebelum melanjutkan:
          </p>
          <div style={{ background: "var(--hazard-light)", borderRadius: 6, padding: 14, marginBottom: 20 }}>
            {savedWithWarnings.map((w, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, color: "var(--hazard-dark)", marginBottom: i < savedWithWarnings.length - 1 ? 8 : 0 }}>
                <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                <span>{w}</span>
              </div>
            ))}
          </div>
          <button className="btn-rust" style={{ width: "100%", justifyContent: "center" }} onClick={onClose}>
            Tutup
          </button>
        </div>
      </div>
    );
  }

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
            <label className="label">Purchase Order</label>
            <select className="input" required value={poId} onChange={(e) => setPoId(e.target.value)}>
              <option value="">Pilih PO…</option>
              {purchaseOrders.map((p) => (
                <option key={p.id} value={p.id}>{p.number} — {p.supplier_name}</option>
              ))}
            </select>
            {purchaseOrders.length === 0 && (
              <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 6 }}>
                Tidak ada PO yang masih bisa menerima barang. Buat PO terlebih dahulu di halaman Purchase Order.
              </div>
            )}
          </div>

          {selectedPo && (
            <>
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

              <div className="label" style={{ marginBottom: 10 }}>Item — Jumlah Diterima</div>
              {selectedPo.line_items.map((li) => {
                const input = lineInputs[li.id] ?? { quantity: "", unit_cost: li.unit_cost, supplier_sku_input: "" };
                const enteredCost = toNumber(input.unit_cost);
                const poCost = toNumber(li.unit_cost);
                const priceDiffers = input.unit_cost !== "" && enteredCost !== poCost;
                return (
                  <div key={li.id} style={{ marginBottom: 14 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                      <div style={{ flex: 2 }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{li.part_name}</div>
                        <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Sisa PO: {li.quantity_outstanding}</div>
                      </div>
                      <div style={{ width: 100 }}>
                        <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Jumlah</div>
                        <input
                          className="input" type="number" min={0}
                          value={input.quantity}
                          onChange={(e) => updateLine(li.id, { quantity: e.target.value })}
                          placeholder="0"
                        />
                      </div>
                      <div style={{ width: 130 }}>
                        <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>
                          Harga Beli <span style={{ color: "var(--steel-lt)" }}>(PO: {formatRupiah(li.unit_cost)})</span>
                        </div>
                        <input
                          className="input" type="number" min={0}
                          style={priceDiffers ? { borderColor: "var(--hazard-dark)" } : undefined}
                          value={input.unit_cost}
                          onChange={(e) => updateLine(li.id, { unit_cost: e.target.value })}
                        />
                      </div>
                    </div>
                    {priceDiffers && (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--hazard-dark)", marginTop: 6 }}>
                        <AlertTriangle size={12} />
                        Berbeda dari harga PO ({formatRupiah(li.unit_cost)}) — akan tetap tersimpan, hanya sebagai catatan.
                      </div>
                    )}
                    {/* Real, non-blocking inline capture — the backend
                        doesn't tell us up front whether a code already
                        exists for this (part, supplier); shown for
                        every line, optional, and simply overwrites via
                        SupplierPartCode.set_code()'s own idempotent
                        upsert if one already exists. Cheap to show
                        always rather than an extra round-trip just to
                        decide whether to show it. */}
                    <div style={{ marginTop: 8 }}>
                      <input
                        className="input" style={{ fontSize: 12.5, padding: "6px 10px" }}
                        placeholder="Kode part supplier (opsional, mis. KNR-TOY-221)"
                        value={input.supplier_sku_input}
                        onChange={(e) => updateLine(li.id, { supplier_sku_input: e.target.value })}
                      />
                    </div>
                  </div>
                );
              })}
              <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 20 }}>
                Jumlah tidak boleh melebihi sisa PO — sistem akan menolak dengan pesan yang jelas jika melebihi.
              </div>
            </>
          )}

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
  const [purchaseOrders, setPurchaseOrders] = useState<PurchaseOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const loadPurchaseOrders = () => purchaseOrdersApi.list().then(setPurchaseOrders);

  useEffect(() => {
    Promise.all([goodsReceivedNotesApi.list(), purchaseOrdersApi.list()])
      .then(([g, po]) => { setGrns(g); setPurchaseOrders(po); })
      .finally(() => setLoading(false));
  }, []);

  const receivablePOs = purchaseOrders.filter((p) => p.status === "ORDERED" || p.status === "PARTIALLY_RECEIVED");

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
              <tr><th>Nomor</th><th>PO</th><th>Supplier</th><th>Diterima</th><th>Total Biaya</th><th>Status</th></tr>
            </thead>
            <tbody>
              {grns.map((g) => (
                <tr key={g.id}>
                  <td>
                    <Link href={`/dashboard/goods-received-detail?id=${g.id}`} className="mono" style={{ color: "var(--rust)", textDecoration: "none", fontWeight: 600 }}>
                      {g.number}
                    </Link>
                  </td>
                  <td>
                    <Link href={`/dashboard/purchase-order-detail?id=${g.purchase_order}`} className="mono" style={{ color: "var(--steel)", textDecoration: "none" }}>
                      {g.purchase_order_number}
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
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada penerimaan barang tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateGrnModal
          purchaseOrders={receivablePOs}
          onClose={() => setShowCreate(false)}
          onCreated={(g) => {
            setGrns((prev) => [g, ...prev]);
            loadPurchaseOrders();
          }}
        />
      )}
    </div>
  );
}
