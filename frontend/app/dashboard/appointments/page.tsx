"use client";
// =============================================================================
// === frontend/app/dashboard/appointments/page.tsx ===
// =============================================================================
import { staffAppointmentsApi, TenantAppointment } from "@/lib/api/staffAppointments";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

function formatDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long" });
}

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState<TenantAppointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [convertedWorkOrderId, setConvertedWorkOrderId] = useState<string | null>(null);

  const load = () => staffAppointmentsApi.list().then((data) => setAppointments(data ?? []));

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, []);

  const handleConvert = async (id: string) => {
    setActioningId(id); setError(null); setConvertedWorkOrderId(null);
    try {
      const { workOrderId } = await staffAppointmentsApi.convert(id);
      setConvertedWorkOrderId(workOrderId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal mengonversi janji temu.");
    } finally {
      setActioningId(null);
    }
  };

  const handleCancel = async (id: string) => {
    setActioningId(id); setError(null);
    try {
      await staffAppointmentsApi.cancel(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal membatalkan janji temu.");
    } finally {
      setActioningId(null);
    }
  };

  return (
    <div>
      <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Janji Temu</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 28 }}>
        Booking online yang menunggu kedatangan pelanggan.
      </p>

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}
      {convertedWorkOrderId && (
        <div style={{ background: "var(--paper-3)", color: "#2e7d4f", padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 16 }}>
          Work Order berhasil dibuat.{" "}
          <Link href={`/dashboard/work-order-detail?id=${convertedWorkOrderId}`} style={{ color: "var(--rust)", fontWeight: 600 }}>
            Lihat Work Order →
          </Link>
        </div>
      )}

      <div className="card">
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
          </div>
        ) : appointments.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--steel)" }}>
            Tidak ada janji temu yang menunggu.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Tanggal</th>
                <th>Pelanggan</th>
                <th>Kendaraan</th>
                <th>Keluhan</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {appointments.map((appt) => (
                <tr key={appt.id}>
                  <td style={{ fontWeight: 600 }}>{formatDate(appt.requested_date)}</td>
                  <td>
                    {appt.customer_name}
                    {appt.customer_phone && (
                      <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{appt.customer_phone}</div>
                    )}
                  </td>
                  <td className="mono">{appt.vehicle_plate} — {appt.vehicle_model}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{appt.notes || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      <button
                        onClick={() => handleConvert(appt.id)}
                        disabled={actioningId === appt.id}
                        className="btn-rust" style={{ fontSize: 12 }}
                      >
                        {actioningId === appt.id ? "…" : "Pelanggan Datang"}
                      </button>
                      <button
                        onClick={() => handleCancel(appt.id)}
                        disabled={actioningId === appt.id}
                        className="btn-ghost" style={{ fontSize: 12 }}
                      >
                        Batalkan
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
