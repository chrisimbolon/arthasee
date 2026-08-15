"use client";
// =============================================================================
// === frontend/app/dashboard/goods-received-detail/page.tsx ===
// Flat top-level page, matching vehicle-detail/work-order-detail's
// own real convention — NOT nested under dashboard/purchasing/, and
// reached via ?id= (query param), not a dynamic route segment.
// Doesn't render PurchasingSubNav — standalone detail pages in this
// app don't appear to participate in a persistent tab bar.
// =============================================================================
import { GoodsReceivedNote, goodsReceivedNotesApi, PurchaseReturn, purchaseReturnsApi } from "@/lib/api/purchasing";
import { AlertCircle, ArrowLeft, Loader2, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(toNumber(value));
}

interface ReturnLineInput {
  grn_line_item_id: string;
  part_name: string;
  received_quantity: string;
  quantity: string;
}

function CreateReturnModal({
  grn, onClose, onCreated,
}: {
  grn: GoodsReceivedNote; onClose: () => void; onCreated: (r: PurchaseReturn) => void;
}) {
  const [reason, setReason] = useState("");
  const [lineInputs, setLineInputs] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lines: ReturnLineInput[] = grn.line_items.map((li) => ({
    grn_line_item_id: li.id, part_name: li.part_name,
    received_quantity: li.quantity, quantity: lineInputs[li.id] ?? "",
  }));

  const filledLines = lines.filter((l) => toNumber(l.quantity) > 0);
  const canSubmit = reason.trim().length > 0 && filledLines.length > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const purchaseReturn = await purchaseReturnsApi.create({
        goods_received_note: grn.id,
        reason: reason.trim(),
        lines: filledLines.map((l) => ({ grn_line_item: l.grn_line_item_id, quantity: toNumber(l.quantity) })),
      });
      onCreated(purchaseReturn);
      onClose();
    } catch (err) {
      const data = (err as { response?: { data?: { message?: string } } })?.response?.data;
      setError(data?.message || "Gagal menyimpan retur pembelian.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 480, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Retur Pembelian</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>{grn.number} — {grn.supplier_name}</p>

        <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "10px 14px", fontSize: 12.5, marginBottom: 16, display: "flex", gap: 8, alignItems: "flex-start" }}>
          <AlertCircle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>Jumlah retur dibatasi oleh jumlah yang sudah diterima dikurangi retur sebelumnya — jika melebihi, sistem akan menolak dengan pesan yang jelas.</span>
        </div>

        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Alasan Retur</label>
            <textarea className="input" rows={2} required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Barang rusak, salah kirim, dll." />
          </div>

          <div className="label" style={{ marginBottom: 10 }}>Jumlah Diretur per Item</div>
          {lines.map((line) => (
            <div key={line.grn_line_item_id} style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{line.part_name}</div>
                <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Diterima: {line.received_quantity}</div>
              </div>
              <input
                className="input" type="number" min={0} style={{ width: 100 }}
                value={lineInputs[line.grn_line_item_id] ?? ""}
                onChange={(e) => setLineInputs({ ...lineInputs, [line.grn_line_item_id]: e.target.value })}
                placeholder="0"
              />
            </div>
          ))}

          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center", marginTop: 12 }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan Retur"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function GoodsReceivedNoteDetailPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? "";

  const [grn, setGrn] = useState<GoodsReceivedNote | null>(null);
  const [returns, setReturns] = useState<PurchaseReturn[]>([]);
  const [loading, setLoading] = useState(true);
  const [showReturn, setShowReturn] = useState(false);

  const load = () => {
    if (!id) { setLoading(false); return; }
    setLoading(true);
    Promise.all([goodsReceivedNotesApi.get(id), purchaseReturnsApi.list()])
      .then(([g, allReturns]) => {
        setGrn(g);
        setReturns(allReturns.filter((r) => r.goods_received_note === id));
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [id]);

  if (loading) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
        <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  if (!grn) {
    return (
      <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
        Penerimaan barang tidak ditemukan.
      </div>
    );
  }

  const alreadyInvoiced = !!grn.supplier_invoice;

  return (
    <div>
      <Link href="/dashboard/purchasing/goods-received" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", marginBottom: 12, textDecoration: "none" }}>
        <ArrowLeft size={14} /> Kembali ke Penerimaan Barang
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>{grn.number}</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{grn.supplier_name}</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <button
            className="btn-rust" onClick={() => setShowReturn(true)} disabled={alreadyInvoiced}
            style={{ display: "inline-flex", alignItems: "center", gap: 7, opacity: alreadyInvoiced ? 0.5 : 1 }}
          >
            <RotateCcw size={15} /> Retur Pembelian
          </button>
          {alreadyInvoiced && (
            <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6, maxWidth: 220 }}>
              GRN ini sudah memiliki invoice supplier — retur untuk GRN yang sudah ditagih belum didukung.
            </div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Purchase Order</div>
            <Link
              href={`/dashboard/purchase-order-detail?id=${grn.purchase_order}`}
              className="mono"
              style={{ fontSize: 13, color: "var(--rust)", textDecoration: "none", fontWeight: 600 }}
            >
              {grn.purchase_order_number}
            </Link>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Status</div>
            <span className={`pill ${alreadyInvoiced ? "ok" : "soon"}`}>{alreadyInvoiced ? "Sudah Ditagih" : "Belum Ditagih"}</span>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Diterima</div>
            <div style={{ fontSize: 13 }}>{new Date(grn.received_at).toLocaleString("id-ID")}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Referensi</div>
            <div style={{ fontSize: 13 }}>{grn.reference || "—"}</div>
          </div>
        </div>

        <table className="data-table">
          <thead>
            <tr><th>Part</th><th>Jumlah</th><th>Harga Beli</th><th style={{ textAlign: "right" }}>Subtotal</th></tr>
          </thead>
          <tbody>
            {grn.line_items.map((li) => (
              <tr key={li.id}>
                <td>{li.part_name}</td>
                <td className="mono">{li.quantity}</td>
                <td className="mono">{formatRupiah(li.unit_cost)}</td>
                <td className="mono" style={{ textAlign: "right" }}>{formatRupiah(li.subtotal)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: "flex", justifyContent: "flex-end", padding: "12px 0 0", fontSize: 14, fontWeight: 700 }}>
          Total: <span className="mono" style={{ marginLeft: 8 }}>{formatRupiah(grn.total_cost)}</span>
        </div>
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 12 }}>Riwayat Retur</div>
        {returns.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--steel-lt)", padding: "8px 0" }}>Belum ada retur untuk GRN ini.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {returns.map((r) => (
              <div key={r.id} style={{ borderBottom: "1px solid var(--line)", paddingBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 600 }}>
                  <span className="mono">{r.number}</span>
                  <span className="mono">{formatRupiah(r.total_value)}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 2 }}>{r.reason}</div>
                <div style={{ fontSize: 11.5, color: "var(--steel-lt)", marginTop: 2 }}>{new Date(r.return_date).toLocaleString("id-ID")}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showReturn && (
        <CreateReturnModal
          grn={grn}
          onClose={() => setShowReturn(false)}
          onCreated={() => load()}
        />
      )}
    </div>
  );
}
