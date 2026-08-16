"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/purchase-returns/page.tsx ===
// List-only, deliberately no create modal — a PurchaseReturn is
// always created from the specific GRN it's against
// (CreateReturnModal lives on goods-received-detail), never from a
// standalone flow, same reasoning as how a SupplierInvoice's payment
// is triggered from the invoice's own detail page. This page exists
// purely so returns have a real, browsable home — the one gap left
// in this Purchasing area; every other document type already had
// its own list page.
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import { PurchaseReturn, purchaseReturnsApi } from "@/lib/api/purchasing";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(toNumber(value));
}

function classificationPillType(classification: PurchaseReturn["return_classification"]): string {
  // Neither classification is a problem state — both are equally
  // valid, correct accounting paths — so deliberately avoid "due"
  // (this app's danger/urgency-coded pill) for either one.
  return classification === "AFTER_INVOICE_UNPAID" ? "soon" : "ok";
}

export default function PurchaseReturnsPage() {
  const [returns, setReturns] = useState<PurchaseReturn[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    purchaseReturnsApi.list().then(setReturns).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div style={{ marginBottom: 4 }}>
        <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
        <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{returns.length} retur pembelian tercatat</p>
      </div>

      <PurchasingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nomor</th><th>GRN Asal</th><th>Alasan</th><th>Klasifikasi</th><th>Nilai</th><th>Tanggal</th></tr>
            </thead>
            <tbody>
              {returns.map((r) => (
                <tr key={r.id}>
                  <td className="mono" style={{ fontWeight: 600 }}>{r.number}</td>
                  <td>
                    <Link
                      href={`/dashboard/goods-received-detail?id=${r.goods_received_note}`}
                      className="mono"
                      style={{ color: "var(--rust)", textDecoration: "none" }}
                    >
                      {r.goods_received_note_number}
                    </Link>
                  </td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{r.reason}</td>
                  <td><span className={`pill ${classificationPillType(r.return_classification)}`}>{r.classification_display}</span></td>
                  <td className="mono">{formatRupiah(r.total_value)}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(r.return_date).toLocaleDateString("id-ID")}</td>
                </tr>
              ))}
              {returns.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada retur pembelian tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
