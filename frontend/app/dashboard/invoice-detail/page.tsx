"use client";
// =============================================================================
// === frontend/app/dashboard/invoice-detail/page.tsx ===
// Same query-param pattern as vehicle-detail — static export needs
// every route's HTML identical regardless of ?id= value, since real
// invoice UUIDs don't exist at build time.
//
// UPDATED — "Tandai Lunas" no longer PATCHes status directly. The
// backend now rejects that outright (Invoice.status can only ever
// become PAID by Payment.record() actually zeroing out balance_due —
// see apps.invoicing.views.InvoiceStatusUpdateView's own docstring).
// Replaced with a real payment-recording form hitting the new
// /api/invoices/<id>/payments/ endpoint, plus a payment history list
// — genuinely useful now that partial payments (a deposit, then a
// balance payment later) are a real, supported case, not just a
// single overwritable field.
// =============================================================================
import { Invoice, InvoiceStatus, invoicesApi } from "@/lib/api/invoicing";
import { organizationsApi } from "@/lib/api/organizations";
import { Payment, PaymentMethod, paymentsApi } from "@/lib/api/payments";
import { ArrowLeft, Download, Loader2, Printer } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  DRAFT: "Draf", ISSUED: "Diterbitkan", PAID: "Lunas", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<InvoiceStatus, string> = {
  DRAFT: "var(--steel)", ISSUED: "var(--rust)", PAID: "#2e7d4f", CANCELLED: "var(--danger)",
};
// Mirrors backend/apps/payments/models.py's own METHOD_CHOICES
// exactly — keep in sync if that list ever changes.
const PAYMENT_METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: "Tunai", bank_transfer: "Transfer Bank", qris: "QRIS", card: "Kartu Debit/Kredit", other: "Lainnya",
};

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

// Chris's own ask, 5 Aug — Made's own handwritten meeting note,
// confirmed for Invoice only (not the Job Ticket, which deliberately
// shows zero prices anywhere). Mirrors backend/apps/invoicing/pdf.py's
// own terbilang_rupiah() exactly — same recursive algorithm, same
// output shape — so the on-screen Cetak view (window.print(), no
// backend PDF involved) and the actual downloaded PDF never
// disagree on what a given total spells out to.
const ONES = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"];

function terbilangWords(n: number): string {
  if (n < 12) return ONES[n];
  if (n < 20) return terbilangWords(n - 10) + " belas";
  if (n < 100) {
    const tens = Math.floor(n / 10), rest = n % 10;
    return terbilangWords(tens) + " puluh" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 200) {
    const rest = n - 100;
    return "seratus" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1000) {
    const hundreds = Math.floor(n / 100), rest = n % 100;
    return terbilangWords(hundreds) + " ratus" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 2000) {
    const rest = n - 1000;
    return "seribu" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1_000_000) {
    const thousands = Math.floor(n / 1000), rest = n % 1000;
    return terbilangWords(thousands) + " ribu" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1_000_000_000) {
    const millions = Math.floor(n / 1_000_000), rest = n % 1_000_000;
    return terbilangWords(millions) + " juta" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1_000_000_000_000) {
    const billions = Math.floor(n / 1_000_000_000), rest = n % 1_000_000_000;
    return terbilangWords(billions) + " miliar" + (rest ? " " + terbilangWords(rest) : "");
  }
  const trillions = Math.floor(n / 1_000_000_000_000), rest = n % 1_000_000_000_000;
  return terbilangWords(trillions) + " triliun" + (rest ? " " + terbilangWords(rest) : "");
}

function terbilangRupiah(value: string | number): string {
  const n = Math.round(Number(value));
  if (n === 0) return "Nol Rupiah";
  const words = terbilangWords(n).split(" ").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  return `${words} Rupiah`;
}

function InvoiceDetailContent() {
  const searchParams = useSearchParams();
  const invoiceId = searchParams.get("id") ?? "";
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [orgName, setOrgName] = useState<string | null>(null);
  const [orgAddress, setOrgAddress] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Payment-form state — kept separate from `updating` (used for
  // plain status transitions) since the two actions have genuinely
  // different in-flight UI (a form to fill in vs. a single button).
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("cash");
  const [paymentReference, setPaymentReference] = useState("");
  const [submittingPayment, setSubmittingPayment] = useState(false);

  const load = () =>
    invoicesApi.get(invoiceId)
      .then((inv) => {
        setInvoice(inv);
        // Payment history is harmless to fetch regardless of status
        // (empty for DRAFT/a never-paid CANCELLED invoice) — no
        // status check needed before calling this.
        return paymentsApi.list(inv.id).then(setPayments).catch(() => setPayments([]));
      })
      .finally(() => setLoading(false));
  useEffect(() => {
    if (invoiceId) load();
  }, [invoiceId]);
  useEffect(() => {
        organizationsApi.mine().then((res) => {
      if (res) { setOrgName(res.organization.name); setOrgAddress(res.organization.address); }
    });
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

  // Defaults the amount field to the full remaining balance — one
  // click through this form (open, then Simpan with no changes)
  // reproduces the old one-click "Tandai Lunas" behavior for the
  // common full-payment case, while still allowing a real partial
  // amount when that's what actually happened.
  const openPaymentForm = () => {
    if (!invoice) return;
    setPaymentAmount(invoice.balance_due);
    setPaymentMethod("cash");
    setPaymentReference("");
    setError(null);
    setShowPaymentForm(true);
  };

  const submitPayment = async () => {
    if (!invoice) return;
    setSubmittingPayment(true); setError(null);
    try {
      await paymentsApi.record(invoice.id, {
        amount: paymentAmount,
        method: paymentMethod,
        reference: paymentReference || undefined,
      });
      setShowPaymentForm(false);
      await load(); // re-fetch — status may now be PAID, and the new payment belongs in the history list
    } catch (err: any) {
      // Deliberate deviation from changeStatus()'s own generic
      // catch above — Payment.record() returns real, specific,
      // actionable messages (overpayment amount, wrong invoice
      // status) that are genuinely more useful to show than a flat
      // "gagal" string here, unlike a plain status PATCH which never
      // had anything that specific to say.
      setError(err?.response?.data?.message ?? "Gagal mencatat pembayaran.");
    } finally {
      setSubmittingPayment(false);
    }
  };

  // Made's own ask, 31 Jul: a real PDF for LUNAS invoices so SA/
  // cashier can forward it themselves via WhatsApp. Backend hard-
  // gates to PAID only — this button is also only ever rendered when
  // invoice.status === "PAID" (see below), but the real enforcement
  // lives server-side, not here.
  const handleDownloadPdf = async () => {
    if (!invoice) return;
    setDownloadingPdf(true); setError(null);
    try {
      const blob = await invoicesApi.downloadPdf(invoice.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Invoice_${invoice.number.replace(/\//g, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Gagal mengunduh PDF.");
    } finally {
      setDownloadingPdf(false);
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
        <div style={{ display: "flex", gap: 8 }}>
          {invoice.status === "PAID" && (
            <button className="btn-ghost" onClick={handleDownloadPdf} disabled={downloadingPdf}>
              {downloadingPdf ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={15} />}
              Download PDF
            </button>
          )}
          <button className="btn-rust" onClick={() => window.print()}>
            <Printer size={15} /> Cetak
          </button>
        </div>
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

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 28, paddingBottom: 20, borderBottom: "1px solid var(--line)" }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Pelanggan</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{invoice.customer_name_snapshot}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Nomor Plat</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 600 }}>{invoice.license_plate_snapshot}</div>
          </div>
          {/* Made's own explicit reason, 31 Jul: a specific mechanic
              must be identifiable on every invoice so he can go back
              and question that person directly if the same car has
              an issue again. Backend hard-blocks invoice creation
              without one, so this is never actually blank here on a
              real invoice. */}
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Mekanik</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{invoice.mechanic_name_snapshot}</div>
          </div>
        </div>

        {/* 4 Sep 2026 — real fix: Invoice already had the exact same
            kind field ("part"/"labor") EstimateLineItem uses to split
            Parts/Jasa — this page just never read it, rendering every
            invoice as one flat list while its own source estimate
            showed the real, expected split. No backend change needed
            — invoicing/models.py's own InvoiceLineItem.kind was
            already there. */}
        {(() => {
          const partItems = invoice.line_items.filter((li) => li.kind === "part");
          const laborItems = invoice.line_items.filter((li) => li.kind === "labor");
          const partTotal = partItems.reduce((sum, li) => sum + Number(li.subtotal), 0);
          const laborTotal = laborItems.reduce((sum, li) => sum + Number(li.subtotal), 0);

          const renderTable = (items: typeof invoice.line_items) => (
            <table className="data-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Deskripsi</th>
                  <th style={{ textAlign: "right" }}>Jml</th>
                  <th style={{ textAlign: "right" }}>Harga Satuan</th>
                  <th style={{ textAlign: "right" }}>Subtotal</th>
                </tr>
              </thead>
              <tbody>
                {items.map((li) => (
                  <tr key={li.id}>
                    <td>{li.description}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{li.quantity}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{money(li.unit_price)}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{money(li.subtotal)}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={4} style={{ textAlign: "center", padding: 16, color: "var(--steel)" }}>Belum ada item.</td></tr>
                )}
              </tbody>
            </table>
          );

          return (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>Parts</div>
              {renderTable(partItems)}
              <div style={{ textAlign: "right", fontSize: 13, color: "var(--steel)", padding: "8px 0 20px" }}>
                Total Parts&nbsp;&nbsp;<span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{money(partTotal)}</span>
              </div>

              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>Jasa</div>
              {renderTable(laborItems)}
              <div style={{ textAlign: "right", fontSize: 13, color: "var(--steel)", padding: "8px 0" }}>
                Total Jasa&nbsp;&nbsp;<span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{money(laborTotal)}</span>
              </div>
            </div>
          );
        })()}

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
            {/* New — mirrors the Deposit row above exactly, same
                reasoning: balance_due now also nets out real Payment
                rows, not just deposit_amount, so the total actually
                paid so far deserves the same visible line item. */}
            {payments.length > 0 && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 6 }}>
                <span style={{ color: "var(--steel)" }}>Sudah Dibayar</span>
                <span className="mono">− {money(payments.reduce((sum, p) => sum + Number(p.amount), 0))}</span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 17, fontWeight: 700, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
              <span>{Number(invoice.deposit_amount) > 0 || payments.length > 0 ? "Sisa Tagihan" : "Total"}</span>
              <span className="mono">{money(invoice.balance_due)}</span>
            </div>
            {/* Terbilang describes the SAME figure the row above
                shows — balance_due, not the pre-deposit subtotal.
                Spelling out a different number than what's printed
                as the bottom-line total would be a real, confusing
                inconsistency on a financial document. */}
            <div style={{ fontSize: 11.5, fontStyle: "italic", color: "var(--steel)", marginTop: 6, textAlign: "right" }}>
              Terbilang: {terbilangRupiah(invoice.balance_due)}
            </div>
          </div>
        </div>

        {/* Made's own handwritten note, 4 Aug meeting: "WO & Invoice:
            terbilang, diterima oleh" — Invoice needs the same
            sign-off block the WO's own paper form already has, for a
            real, physical customer signature. */}
        <div style={{ display: "flex", marginTop: 56 }}>
          <div style={{ width: 220 }}>
            <div style={{ height: 50 }} />
            <div style={{ borderTop: "1px solid var(--ink)", paddingTop: 4, fontSize: 12.5, color: "var(--steel)" }}>
              Diterima oleh
            </div>
          </div>
        </div>

        {invoice.created_by_name && (
          <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 16, textAlign: "right" }}>
            Dibuat oleh {invoice.created_by_name}
          </p>
        )}
      </div>

      {/* Payment history — internal/staff-facing only (no-print), same
          reasoning as the status controls below: a customer's printed
          invoice stays exactly as clean as it already was, this is
          for Made/SA's own reference (e.g. "why does this say partially
          paid") right on the same screen they're already looking at. */}
      {payments.length > 0 && (
        <div className="no-print card" style={{ maxWidth: 720, margin: "18px auto 0", padding: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--steel)", textTransform: "uppercase" }}>
            Riwayat Pembayaran
          </div>
          {payments.map((p) => (
            <div key={p.id} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 12, alignItems: "center", fontSize: 13, padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
              <span>
                {PAYMENT_METHOD_LABEL[p.method]}
                {p.reference && <span style={{ color: "var(--steel)" }}> — {p.reference}</span>}
              </span>
              <span className="mono" style={{ fontWeight: 600 }}>{money(p.amount)}</span>
              <span style={{ color: "var(--steel)", fontSize: 11.5 }}>
                {new Date(p.received_at).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Payment-recording form — replaces the old one-click "Tandai
          Lunas" PATCH, which the backend no longer accepts. Amount
          defaults to the full remaining balance (see openPaymentForm)
          so the common "pay it all off" case is still a two-click
          action (open, then Simpan), not a burdensome form fill. */}
      {showPaymentForm && invoice.status === "ISSUED" && (
        <div className="no-print card" style={{ maxWidth: 720, margin: "18px auto 0", padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Catat Pembayaran</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Jumlah</label>
              <input
                type="number" className="mono" value={paymentAmount}
                onChange={(e) => setPaymentAmount(e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
              />
              <div style={{ fontSize: 11, color: "var(--steel)", marginTop: 4 }}>
                Sisa tagihan saat ini: {money(invoice.balance_due)}
              </div>
            </div>
            <div>
              <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Metode</label>
              <select
                value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value as PaymentMethod)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
              >
                {Object.entries(PAYMENT_METHOD_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Referensi (opsional)</label>
            <input
              type="text" value={paymentReference} onChange={(e) => setPaymentReference(e.target.value)}
              placeholder="No. transfer, ID transaksi QRIS, dll."
              style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
            />
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button className="btn-ghost" disabled={submittingPayment} onClick={() => setShowPaymentForm(false)}>Batal</button>
            <button
              className="btn-rust" disabled={submittingPayment || !paymentAmount || Number(paymentAmount) <= 0}
              onClick={submitPayment}
            >
              {submittingPayment && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
              Simpan Pembayaran
            </button>
          </div>
        </div>
      )}

      <div className="no-print" style={{ maxWidth: 720, margin: "18px auto 0", display: "flex", gap: 10, justifyContent: "center" }}>
        {invoice.status === "DRAFT" && (
          <button className="btn-rust" disabled={updating} onClick={() => changeStatus("ISSUED")}>Terbitkan Invoice</button>
        )}
        {invoice.status === "ISSUED" && !showPaymentForm && (
          <button className="btn-rust" disabled={updating} onClick={openPaymentForm}>Catat Pembayaran</button>
        )}
        {(invoice.status === "DRAFT" || invoice.status === "ISSUED") && (
          <button
            className="btn-ghost" disabled={updating || payments.length > 0}
            onClick={() => changeStatus("CANCELLED")}
            // Proactive disable, mirroring the same "backend is the
            // real enforcement, frontend just disables proactively"
            // split already established elsewhere in this app (see
            // WorkOrderJobTicketPdfView's own docstring) — the
            // backend's own 409 guard on InvoiceStatusUpdateView is
            // what actually stops this, this is just the UI signal.
            title={payments.length > 0 ? "Invoice ini sudah memiliki pembayaran tercatat — tidak bisa dibatalkan langsung." : undefined}
          >
            Batalkan
          </button>
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
