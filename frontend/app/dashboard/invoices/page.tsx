"use client";
// =============================================================================
// === frontend/app/dashboard/invoices/page.tsx ===
// =============================================================================
// 15 Sep 2026 — new page, no prior version existed. The real,
// previously-missing global invoice list — every other real invoice-
// facing surface in this app only ever shows ONE invoice at a time
// (Riwayat Servis on vehicle-detail, a Work Order's own linked
// invoice). Mirrors customers/page.tsx's own real conventions
// (header, filter buttons, search input, data-table, row-click
// navigation via useRouter) as closely as the two features' real
// differences allow — the one real departure is that filtering here
// is SERVER-SIDE (invoicesApi.list()'s own status/overdue/search
// params), not client-side, since a shop-wide invoice list is a
// real, potentially large dataset unlike the small per-org customer
// list that page filters in the browser.
import { Invoice, InvoiceStatus, invoicesApi } from "@/lib/api/invoicing";
import { AlertTriangle, Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const STATUS_TABS: { id: "ALL" | InvoiceStatus; label: string }[] = [
  { id: "ALL", label: "Semua" },
  { id: "DRAFT", label: "Draf" },
  { id: "ISSUED", label: "Diterbitkan" },
  { id: "PARTIALLY_PAID", label: "Dibayar Sebagian" },
  { id: "PAID", label: "Lunas" },
  { id: "CANCELLED", label: "Dibatalkan" },
];

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  DRAFT: "Draf", ISSUED: "Diterbitkan", PARTIALLY_PAID: "Dibayar Sebagian", PAID: "Lunas", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<InvoiceStatus, string> = {
  DRAFT: "var(--steel)", ISSUED: "var(--rust)", PARTIALLY_PAID: "var(--hazard-dark)", PAID: "#2e7d4f", CANCELLED: "var(--danger)",
};

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

export default function InvoicesPage() {
  const router = useRouter();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<"ALL" | InvoiceStatus>("ALL");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [search, setSearch] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = () => {
    setLoading(true);
    invoicesApi.list({
      status: statusFilter === "ALL" ? undefined : statusFilter,
      overdue: overdueOnly || undefined,
      search: search || undefined,
    })
      .then(setInvoices)
      .finally(() => setLoading(false));
  };

  // status/overdue changes refetch immediately — no debounce needed,
  // a button click is already a deliberate, single action.
  useEffect(() => { load(); }, [statusFilter, overdueOnly]);

  // search is real, server-side per-keystroke traffic if left
  // undebounced — a short, real 400ms debounce here, matching the
  // real cost difference from customers/page.tsx's own client-side
  // (free) filtering.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(load, 400);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Penjualan</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>
            {invoices.length} invoice {statusFilter !== "ALL" || overdueOnly ? "(terfilter)" : "tercatat"}
          </p>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
        {STATUS_TABS.map((t) => (
          <button
            key={t.id} onClick={() => setStatusFilter(t.id)}
            className={statusFilter === t.id ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13 }}
          >
            {t.label}
          </button>
        ))}
        <button
          onClick={() => setOverdueOnly((prev) => !prev)}
          className={overdueOnly ? "btn-rust" : "btn-ghost"}
          style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
        >
          <AlertTriangle size={14} /> Telat Bayar
        </button>
        <div style={{ position: "relative", maxWidth: 280, marginLeft: "auto" }}>
          <Search size={15} style={{ position: "absolute", left: 12, top: 11, color: "var(--steel)" }} />
          <input
            className="input" style={{ paddingLeft: 34 }}
            placeholder="Cari nama, plat, atau no. invoice…"
            value={search} onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>No. Invoice</th><th>Tanggal</th><th>Pelanggan</th><th>Plat</th>
                <th>Status</th><th style={{ textAlign: "right" }}>Total</th>
                <th style={{ textAlign: "right" }}>Sisa Tagihan</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr
                  key={inv.id}
                  onClick={() => router.push(`/dashboard/invoice-detail?id=${inv.id}`)}
                  style={{ cursor: "pointer" }}
                >
                  <td className="mono">{inv.number}</td>
                  <td>{new Date(inv.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}</td>
                  <td style={{ fontWeight: 600 }}>{inv.customer_name_snapshot}</td>
                  <td className="mono">{inv.license_plate_snapshot}</td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[inv.status], whiteSpace: "nowrap" }}>
                        {STATUS_LABEL[inv.status]}
                      </span>
                      {inv.is_overdue && (
                        <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: "var(--danger)", whiteSpace: "nowrap" }}>
                          Telat Bayar
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>{money(inv.total)}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{money(inv.balance_due)}</td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>
                  Belum ada invoice untuk filter ini.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
