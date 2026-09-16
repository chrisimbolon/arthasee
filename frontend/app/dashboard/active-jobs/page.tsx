"use client";
// =============================================================================
// === frontend/app/dashboard/active-jobs/page.tsx ===
// =============================================================================
// 16 Sep 2026 -- broadened from a narrow "currently in motion" roster
// (B2 in the original sprint review) into the real global Work Order
// master list -- Chris's own confirmed design, 16 Sep: front-desk
// staff shouldn't have to open a specific Vehicle/Customer page just
// to answer "is my car ready?" Now covers every real status
// (Antrean/Sedang Dikerjakan/QC/Selesai/Dibatalkan), with real
// server-side search and its own real payment-status column.
//
// Deliberately calls the NEW workOrderMasterListApi (GET
// /api/work-orders/), NOT the old activeJobsApi (GET /api/work-
// orders/active/) -- that endpoint stays untouched for whatever else
// may depend on its own narrow, elapsed-time-focused shape. This
// page no longer shows elapsed-time/is_overdue at all -- a real,
// deliberate drop, not an oversight: the confirmed column spec
// (WO #, Tanggal, Pelanggan, Plat/Kendaraan, Mekanik, Status
// Pekerjaan, Status Pembayaran, Total) doesn't include it, and a
// full historical roster spanning Selesai/Dibatalkan makes "how long
// has this been running" far less meaningful than it was on a
// strictly-active-only view.
import { InvoiceStatus } from "@/lib/api/invoicing";
import { WorkOrderMasterListRow, WorkOrderStatus, workOrderMasterListApi } from "@/lib/api/workorders";
import { Loader2, Search, Wrench } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const STATUS_TABS: { id: "ALL" | WorkOrderStatus; label: string }[] = [
  { id: "ALL",         label: "Semua" },
  { id: "OPEN",        label: "Antrean" },
  { id: "IN_PROGRESS", label: "Sedang Dikerjakan" },
  { id: "QC",          label: "QC" },
  { id: "DONE",        label: "Selesai" },
  { id: "CANCELLED",   label: "Dibatalkan" },
];

const STATUS_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: "Antrean", IN_PROGRESS: "Dikerjakan", QC: "QC", DONE: "Selesai", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<WorkOrderStatus, string> = {
  OPEN: "#4a6d94", IN_PROGRESS: "var(--rust)", QC: "#8a6d3b", DONE: "#2e7d4f", CANCELLED: "var(--danger)",
};

// null (no Invoice yet) is deliberately treated the same as DRAFT --
// nothing has genuinely been billed to the customer at either point,
// even though a DRAFT invoice's own number is already locked in.
const PAYMENT_STATUS_LABEL: Record<string, string> = {
  DRAFT: "Belum Ditagih", ISSUED: "Belum Dibayar", PARTIALLY_PAID: "Sebagian",
  PAID: "Lunas", CANCELLED: "Dibatalkan",
};
const PAYMENT_STATUS_COLOR: Record<string, string> = {
  DRAFT: "var(--steel)", ISSUED: "var(--rust)", PARTIALLY_PAID: "var(--hazard-dark)",
  PAID: "#2e7d4f", CANCELLED: "var(--danger)",
};

function paymentStatusKey(status: InvoiceStatus | null): string {
  return status ?? "DRAFT";
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(Number(value));
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
}

export default function ActiveJobsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<WorkOrderMasterListRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<"ALL" | WorkOrderStatus>("ALL");
  const [search, setSearch] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = () => {
    setLoading(true);
    workOrderMasterListApi.list({
      status: statusFilter === "ALL" ? undefined : statusFilter,
      search: search || undefined,
    })
      .then(setRows)
      .finally(() => setLoading(false));
  };

  // Status changes refetch immediately -- a tab click is already a
  // deliberate, single action. Search gets a real 400ms debounce --
  // this is server-side, per-keystroke traffic otherwise, same
  // reasoning already established for the invoice list and bank
  // statement import search boxes.
  useEffect(() => { load(); }, [statusFilter]);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(load, 400);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Pekerjaan Aktif</h1>
        <p style={{ color: "var(--steel)", fontSize: 14 }}>
          {rows.length} work order {statusFilter !== "ALL" || search ? "(terfilter)" : "tercatat"}
        </p>
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
        <div style={{ position: "relative", maxWidth: 280, marginLeft: "auto" }}>
          <Search size={15} style={{ position: "absolute", left: 12, top: 11, color: "var(--steel)" }} />
          <input
            className="input" style={{ paddingLeft: 34 }}
            placeholder="Cari nama, plat, atau no. WO…"
            value={search} onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
          </div>
        ) : rows.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--steel)" }}>
            <Wrench size={22} style={{ marginBottom: 10, opacity: 0.5 }} />
            <p style={{ fontSize: 14 }}>Tidak ada work order untuk filter ini.</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>WO #</th><th>Tanggal</th><th>Pelanggan</th><th>Plat / Kendaraan</th>
                <th>Mekanik</th><th>Status Pekerjaan</th><th>Status Pembayaran</th>
                <th style={{ textAlign: "right" }}>Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((wo) => {
                const paymentKey = paymentStatusKey(wo.payment_status);
                return (
                  <tr
                    key={wo.id}
                    onClick={() => router.push(`/dashboard/work-order-detail?id=${wo.id}`)}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="mono" style={{ fontWeight: 600 }}>{wo.number}</td>
                    <td>{formatDate(wo.created_at)}</td>
                    <td style={{ fontWeight: 600 }}>{wo.customer_name}</td>
                    <td>
                      <span className="mono">{wo.vehicle_plate}</span>
                      <div style={{ fontSize: 12, color: "var(--steel)" }}>{wo.vehicle_model}</div>
                    </td>
                    <td>{wo.assigned_to_name ?? <span style={{ color: "var(--steel)" }}>—</span>}</td>
                    <td>
                      <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[wo.status], whiteSpace: "nowrap" }}>
                        {STATUS_LABEL[wo.status]}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: PAYMENT_STATUS_COLOR[paymentKey], whiteSpace: "nowrap" }}>
                        {PAYMENT_STATUS_LABEL[paymentKey]}
                      </span>
                    </td>
                    <td className="mono" style={{ textAlign: "right" }}>
                      {wo.total_is_final ? (
                        formatRupiah(wo.total)
                      ) : (
                        <span style={{ color: "var(--steel)" }}>
                          {formatRupiah(wo.total)} <span style={{ fontSize: 11 }}>(Suku Cadang)*</span>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
