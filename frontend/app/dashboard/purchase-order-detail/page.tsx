"use client";
// =============================================================================
// === frontend/app/dashboard/purchase-order-detail/page.tsx ===
// Flat top-level page, matching goods-received-detail's own real
// convention — reached via ?id=, no persistent sub-nav.
// =============================================================================
import { PurchaseOrder, PurchaseOrderLineItem, purchaseOrdersApi } from "@/lib/api/purchasing";
import { ArrowLeft, Loader2, Pencil, X, XCircle } from "lucide-react";
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

function statusPillType(status: PurchaseOrder["status"]): string {
  if (status === "CANCELLED") return "due";
  if (status === "FULLY_RECEIVED") return "ok";
  return "soon";
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const data = (err as { response?: { data?: { message?: string } } })?.response?.data;
  return data?.message || fallback;
}

function AmendLineModal({
  lineItem, onClose, onAmended,
}: {
  lineItem: PurchaseOrderLineItem; onClose: () => void; onAmended: () => void;
}) {
  const [quantity, setQuantity] = useState(lineItem.quantity_ordered);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      await purchaseOrdersApi.amendLineItem(lineItem.id, toNumber(quantity));
      onAmended();
      onClose();
    } catch (err) {
      setError(extractErrorMessage(err, "Gagal mengubah jumlah pesanan."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 380, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Ubah Jumlah Pesanan</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>{lineItem.part_name}</p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label className="label">Jumlah Dipesan Baru</label>
            <input className="input" type="number" min={0} required value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>
              Sudah diterima: {lineItem.quantity_received} — tidak bisa diubah menjadi kurang dari ini.
            </div>
          </div>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function PurchaseOrderDetailPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? "";

  const [po, setPo] = useState<PurchaseOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [amendingLine, setAmendingLine] = useState<PurchaseOrderLineItem | null>(null);

  const load = () => {
    if (!id) { setLoading(false); return; }
    setLoading(true);
    purchaseOrdersApi.get(id).then(setPo).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [id]);

  const handleCancel = async () => {
    if (!po) return;
    setCancelling(true); setError(null);
    try {
      await purchaseOrdersApi.cancel(po.id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Gagal membatalkan Purchase Order."));
    } finally {
      // Real bug, caught live: this only reset in the catch branch
      // before — on a SUCCESSFUL cancel, `cancelling` stayed true
      // forever, permanently stuck showing just the spinner even
      // though the cancel itself genuinely worked. finally covers
      // both paths, matching every other submit handler in this
      // whole codebase.
      setCancelling(false);
    }
  };

  if (loading) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
        <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  if (!po) {
    return (
      <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
        Purchase Order tidak ditemukan.
      </div>
    );
  }

  // Real guard mirrored from the backend — only DRAFT/ORDERED (zero
  // real receipts) can be cancelled cleanly. Shown disabled-with-
  // explanation once anything's been received, matching the exact
  // same honesty pattern as the Retur Pembelian button on GRN detail.
  const canCancel = po.status === "DRAFT" || po.status === "ORDERED";
  const cancelBlockedReason =
    po.status === "CANCELLED" ? "PO ini sudah dibatalkan."
    : po.status === "FULLY_RECEIVED" ? "Semua barang untuk PO ini sudah diterima — tidak bisa dibatalkan."
    : po.status === "PARTIALLY_RECEIVED" ? "Sudah ada barang yang diterima untuk PO ini — tidak bisa dibatalkan."
    : null;

  return (
    <div>
      <Link href="/dashboard/purchasing/purchase-orders" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", marginBottom: 12, textDecoration: "none" }}>
        <ArrowLeft size={14} /> Kembali ke Purchase Order
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>{po.number}</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{po.supplier_name}</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <span className={`pill ${statusPillType(po.status)}`} style={{ marginBottom: 8, display: "inline-block" }}>
            {po.status_display}
          </span>
          <div>
            <button
              className="btn-ghost" onClick={handleCancel} disabled={!canCancel || cancelling}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, opacity: canCancel ? 1 : 0.5 }}
            >
              {cancelling ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <><XCircle size={14} /> Batalkan PO</>}
            </button>
            {!canCancel && cancelBlockedReason && (
              <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6, maxWidth: 220 }}>
                {cancelBlockedReason}
              </div>
            )}
          </div>
        </div>
      </div>

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Tanggal Pesan</div>
            <div style={{ fontSize: 13 }}>{new Date(po.order_date).toLocaleDateString("id-ID")}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Perkiraan Tiba</div>
            <div style={{ fontSize: 13 }}>{po.expected_date ? new Date(po.expected_date).toLocaleDateString("id-ID") : "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Total Nilai Pesanan</div>
            <div className="mono" style={{ fontSize: 13 }}>{formatRupiah(po.total_ordered_value)}</div>
          </div>
        </div>

        <table className="data-table">
          <thead>
            <tr><th>Part</th><th>Dipesan</th><th>Diterima</th><th>Sisa</th><th>Harga Beli</th><th></th></tr>
          </thead>
          <tbody>
            {po.line_items.map((li) => (
              <tr key={li.id}>
                <td>{li.part_name}</td>
                <td className="mono">{li.quantity_ordered}</td>
                <td className="mono">{li.quantity_received}</td>
                <td className="mono">{li.quantity_outstanding}</td>
                <td className="mono">{formatRupiah(li.unit_cost)}</td>
                <td>
                  <button className="btn-ghost" style={{ fontSize: 12, padding: "6px 8px" }} onClick={() => setAmendingLine(li)} title="Ubah Jumlah Pesanan">
                    <Pencil size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {amendingLine && (
        <AmendLineModal
          lineItem={amendingLine}
          onClose={() => setAmendingLine(null)}
          onAmended={() => load()}
        />
      )}
    </div>
  );
}
