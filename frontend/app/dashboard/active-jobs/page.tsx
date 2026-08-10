"use client";
// =============================================================================
// === frontend/app/dashboard/active-jobs/page.tsx ===
// B2 in the sprint review — a full roster of everything currently in
// motion across the shop, not just the overdue subset the Owner
// Dashboard's own summary already surfaces. The natural extension of
// the same "kontrol dari jauh" (remote supervision) theme that
// drove the whole Owner Dashboard sprint.
// =============================================================================
import { ActiveJob, WorkOrderStatus, activeJobsApi } from "@/lib/api/workorders";
import { AlertTriangle, Loader2, RefreshCw, Wrench } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const STATUS_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: "Antrian", IN_PROGRESS: "Dikerjakan", QC: "QC", DONE: "Selesai", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<WorkOrderStatus, string> = {
 
  OPEN: "#4a6d94", IN_PROGRESS: "var(--rust)", QC: "#8a6d3b", DONE: "#2e7d4f", CANCELLED: "var(--danger)",
};

function formatHours(h: number) {
  return h < 1 ? `${Math.round(h * 60)} menit` : `${h.toFixed(1)} jam`;
}

export default function ActiveJobsPage() {
  const [jobs, setJobs] = useState<ActiveJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = (showRefreshSpinner = false) => {
    if (showRefreshSpinner) setRefreshing(true);
    activeJobsApi.list()
      .then(setJobs)
      .finally(() => { setLoading(false); setRefreshing(false); });
  };
  useEffect(() => { load(); }, []);

  const overdueCount = jobs.filter((j) => j.is_overdue).length;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Pekerjaan Aktif</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>
            {jobs.length} pekerjaan sedang berjalan
            {overdueCount > 0 && <> · <span style={{ color: "var(--danger)", fontWeight: 600 }}>{overdueCount} lebih lama dari perkiraan</span></>}
          </p>
        </div>
        <button className="btn-ghost" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <RefreshCw size={15} />}
          Muat Ulang
        </button>
      </div>

      {loading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
        </div>
      ) : jobs.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--steel)" }}>
          <Wrench size={22} style={{ marginBottom: 10, opacity: 0.5 }} />
          <p style={{ fontSize: 14 }}>Tidak ada pekerjaan yang sedang berjalan saat ini.</p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Kendaraan</th>
                <th>Status</th>
                <th>Tahap Saat Ini</th>
                <th>Mekanik</th>
                <th>Berjalan</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <Link href={`/dashboard/work-order-detail?id=${job.id}`} className="mono" style={{ fontWeight: 600, color: "var(--rust)" }}>
                      {job.vehicle_plate}
                    </Link>
                    <div style={{ fontSize: 12, color: "var(--steel)" }}>{job.customer_name}</div>
                  </td>
                  <td>
                    <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[job.status] }}>
                      {STATUS_LABEL[job.status]}
                    </span>
                  </td>
                  <td>{job.current_stage_name ?? <span style={{ color: "var(--steel)" }}>—</span>}</td>
                  <td>{job.current_stage_mechanic ?? <span style={{ color: "var(--steel)" }}>—</span>}</td>
                  <td>
                    <span className="mono" style={{ fontWeight: job.is_overdue ? 600 : 400, color: job.is_overdue ? "var(--danger)" : "var(--ink)" }}>
                      {formatHours(job.elapsed_hours)}
                    </span>
                    {job.is_overdue && (
                      <span style={{ marginLeft: 6, display: "inline-flex", alignItems: "center", gap: 3, fontSize: 10.5, fontWeight: 600, color: "var(--danger)", background: "var(--danger-light)", padding: "2px 7px", borderRadius: 20 }}>
                        <AlertTriangle size={10} /> Lama
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
