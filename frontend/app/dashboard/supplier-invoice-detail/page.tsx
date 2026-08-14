"use client";
// =============================================================================
// === frontend/app/dashboard/supplier-invoice-detail/page.tsx ===
// Flat top-level page, matching invoice-detail's own real convention
// — NOT nested under dashboard/purchasing/, reached via ?id=.
// =============================================================================
import { SupplierInvoice, supplierInvoicesApi } from "@/lib/api/purchasing";
import { ArrowLeft, Loader2, Wallet } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(toNumber(value));
}

export default function SupplierInvoiceDetailPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? "";

  const [invoice, setInvoice] = useState<SupplierInvoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [method, setMethod] = useState<"cash" | "bank_transfer">("bank_transfer");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!id) { setLoading(false); return; }
    setLoading(true);
    supplierInvoicesApi.get(id).then(setInvoice).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [id]);

  const handlePay = async () => {
    setPaying(true); setError(null);
    try {
      await supplierInvoicesApi.pay(id, method);
      load();
    } catch {
      setError("Gagal mencatat pembayaran.");
      setPaying(false);
    }
  };

  if (loading) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
        <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
        Invoice supplier tidak ditemukan.
      </div>
    );
  }

  const isPaid = invoice.status === "PAID";

  return (
    <div>
      <Link href="/dashboard/purchasing/supplier-invoices" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", marginBottom: 12, textDecoration: "none" }}>
        <ArrowLeft size={14} /> Kembali ke Invoice Supplier
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>{invoice.number}</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{invoice.supplier_name}</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <span className={`pill ${isPaid ? "ok" : "due"}`} style={{ marginBottom: 8, display: "inline-block" }}>
            {isPaid ? "Lunas" : "Belum Dibayar"}
          </span>
          {!isPaid && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select className="input" style={{ width: 150 }} value={method} onChange={(e) => setMethod(e.target.value as "cash" | "bank_transfer")}>
                <option value="bank_transfer">Transfer Bank</option>
                <option value="cash">Tunai</option>
              </select>
              <button className="btn-rust" onClick={handlePay} disabled={paying} style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                {paying ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <><Wallet size={15} /> Bayar</>}
              </button>
            </div>
          )}
        </div>
      </div>

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Jumlah</div>
            <div className="mono" style={{ fontSize: 20, fontWeight: 700 }}>{formatRupiah(invoice.amount)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Tanggal Invoice</div>
            <div style={{ fontSize: 13 }}>{new Date(invoice.invoice_date).toLocaleDateString("id-ID")}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>Jatuh Tempo</div>
            <div style={{ fontSize: 13 }}>{invoice.due_date ? new Date(invoice.due_date).toLocaleDateString("id-ID") : "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>No. Invoice Supplier</div>
            <div style={{ fontSize: 13 }}>{invoice.supplier_invoice_number || "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 4 }}>GRN Terkait</div>
            <div style={{ fontSize: 13 }}>{invoice.goods_received_notes.length > 0 ? `${invoice.goods_received_notes.length} GRN` : "—"}</div>
          </div>
        </div>
        {invoice.notes && (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line)", fontSize: 13, color: "var(--steel)" }}>
            {invoice.notes}
          </div>
        )}
      </div>
    </div>
  );
}
