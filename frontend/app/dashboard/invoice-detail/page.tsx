"use client";
// =============================================================================
// === frontend/app/dashboard/invoice-detail/page.tsx ===
// Same query-param pattern as vehicle-detail — static export needs
// every route's HTML identical regardless of ?id= value, since real
// invoice UUIDs don't exist at build time.
// =============================================================================
import { Invoice, InvoiceStatus, invoicesApi } from "@/lib/api/invoicing";
import { organizationsApi } from "@/lib/api/organizations";
import { ArrowLeft, Loader2, Printer } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  DRAFT: "Draf", ISSUED: "Diterbitkan", PAID: "Lunas", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<InvoiceStatus, string> = {
  DRAFT: "var(--steel)", ISSUED: "var(--rust)", PAID: "#2e7d4f", CANCELLED: "var(--danger)",
};

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

function InvoiceDetailContent() {
  const searchParams = useSearchParams();
  const invoiceId = searchParams.get("id") ?? "";
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [orgName, setOrgName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => invoicesApi.get(invoiceId).then(setInvoice).finally(() => setLoading(false));
  useEffect(() => {
    if (invoiceId) load();
  }, [invoiceId]);
  useEffect(() => {
    organizationsApi.mine().then((res) => { if (res) setOrgName(res.organization.name); });
  }, []);

  const changeStatus = async (status: InvoiceStatus) => {
    if (!invoice) return;
    setUpdating(true); setError(null);
    try {
      const updated = await invoicesApi.updateStatus(invoice.id, status);
      setInvoice(updated);
    } catch {
      setError("Gagal mengubah status invoice.");
    } finally {
      setUpdating(false);
    }
  };

  if (!invoiceId) {
    return <div style={{ color: "var(--danger)" }}>Invoice tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !invoice) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      {/* Print stylesheet, scoped inline since this page has no
          access to globals.css — hides everything outside the
          document itself (sidebar, back link, status controls) when
          actually printed/exported to PDF via the browser. */}
      <style>{`
        @media print {
          .no-print { display: none !important; }
          aside { display: none !important; }
          body, main { margin: 0 !important; padding: 0 !important; }
        }
      `}</style>

      <div className="no-print" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <Link href={`/dashboard/vehicle-detail?id=${invoice.vehicle_id}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)" }}>
          <ArrowLeft size={14} /> Kembali
        </Link>
        <button className="btn-rust" onClick={() => window.print()}>
          <Printer size={15} /> Cetak
        </button>
      </div>

      {error && <div className="no-print" style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}

      <div className="card" style={{ maxWidth: 720, margin: "0 auto", padding: 40 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
          <div>
            <div className="display" style={{ fontSize: 22 }}>{orgName || "Arthasee"}</div>
            <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 4 }}>INVOICE</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{invoice.number}</div>
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>
              {new Date(invoice.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" })}
            </div>
            <span style={{ display: "inline-block", marginTop: 8, fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[invoice.status] }}>
              {STATUS_LABEL[invoice.status]}
            </span>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 28, paddingBottom: 20, borderBottom: "1px solid var(--line)" }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Pelanggan</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{invoice.customer_name_snapshot}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Nomor Plat</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 600 }}>{invoice.license_plate_snapshot}</div>
          </div>
        </div>

        <table className="data-table" style={{ width: "100%", marginBottom: 20 }}>
          <thead>
            <tr>
              <th>Deskripsi</th>
              <th style={{ textAlign: "right" }}>Jml</th>
              <th style={{ textAlign: "right" }}>Harga Satuan</th>
              <th style={{ textAlign: "right" }}>Subtotal</th>
            </tr>
          </thead>
          <tbody>
            {invoice.line_items.map((li) => (
              <tr key={li.id}>
                <td>{li.description}</td>
                <td className="mono" style={{ textAlign: "right" }}>{li.quantity}</td>
                <td className="mono" style={{ textAlign: "right" }}>{money(li.unit_price)}</td>
                <td className="mono" style={{ textAlign: "right" }}>{money(li.subtotal)}</td>
              </tr>
            ))}
            {invoice.line_items.length === 0 && (
              <tr><td colSpan={4} style={{ textAlign: "center", padding: 20, color: "var(--steel)" }}>Belum ada item.</td></tr>
            )}
          </tbody>
        </table>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <div style={{ width: 260 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 6 }}>
              <span style={{ color: "var(--steel)" }}>Subtotal</span>
              <span className="mono">{money(invoice.subtotal)}</span>
            </div>
            {Number(invoice.deposit_amount) > 0 && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 6 }}>
                <span style={{ color: "var(--steel)" }}>Deposit</span>
                <span className="mono">− {money(invoice.deposit_amount)}</span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 17, fontWeight: 700, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
              <span>{Number(invoice.deposit_amount) > 0 ? "Sisa Tagihan" : "Total"}</span>
              <span className="mono">{money(invoice.balance_due)}</span>
            </div>
          </div>
        </div>

        {invoice.created_by_name && (
          <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 32, textAlign: "right" }}>
            Dibuat oleh {invoice.created_by_name}
          </p>
        )}
      </div>

      <div className="no-print" style={{ maxWidth: 720, margin: "18px auto 0", display: "flex", gap: 10, justifyContent: "center" }}>
        {invoice.status === "DRAFT" && (
          <button className="btn-rust" disabled={updating} onClick={() => changeStatus("ISSUED")}>Terbitkan Invoice</button>
        )}
        {invoice.status === "ISSUED" && (
          <button className="btn-rust" disabled={updating} onClick={() => changeStatus("PAID")}>Tandai Lunas</button>
        )}
        {(invoice.status === "DRAFT" || invoice.status === "ISSUED") && (
          <button className="btn-ghost" disabled={updating} onClick={() => changeStatus("CANCELLED")}>Batalkan</button>
        )}
      </div>
    </div>
  );
}

export default function InvoiceDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <InvoiceDetailContent />
    </Suspense>
  );
}
