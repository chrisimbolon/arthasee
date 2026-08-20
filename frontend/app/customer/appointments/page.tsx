"use client";
// =============================================================================
// === frontend/app/customer/appointments/page.tsx ===
// =============================================================================
// A real, separate page from the dashboard — booking is a distinct
// action with its own state (selected date, selected vehicle,
// submission), not something that belongs squeezed into "here's my
// current job status." Same maxWidth/padding/card conventions as
// CustomerDashboardPage, so it reads as the same app.
import {
  Appointment, AppointmentAvailabilityDay, appointmentsApi,
  CustomerVehicle, customerVehiclesApi,
} from "@/lib/api/appointments";
import { customerTokenStorage } from "@/lib/api/customerAuth";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const APPOINTMENT_STATUS: Record<string, { label: string; color: string }> = {
  CONFIRMED: { label: "Terkonfirmasi", color: "var(--rust)" },
  CONVERTED: { label: "Sudah Datang", color: "#2e7d4f" },
  CANCELLED: { label: "Dibatalkan", color: "var(--danger)" },
};

function formatDay(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("id-ID", { weekday: "short", day: "numeric", month: "short" });
}

export default function CustomerAppointmentsPage() {
  const [signedOut, setSignedOut] = useState(false);
  const [loading, setLoading] = useState(true);

  const [days, setDays] = useState<AppointmentAvailabilityDay[]>([]);
  const [vehicles, setVehicles] = useState<CustomerVehicle[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);

  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedVehicleId, setSelectedVehicleId] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const loadAll = () =>
    Promise.all([appointmentsApi.availability(), customerVehiclesApi.list(), appointmentsApi.list()])
      .then(([availabilityDays, vehicleList, appointmentList]) => {
        setDays(availabilityDays);
        setVehicles(vehicleList);
        setAppointments(appointmentList);
        setSelectedVehicleId((current) => current || (vehicleList[0]?.id ?? ""));
      });

  useEffect(() => {
    if (!customerTokenStorage.get()) { setSignedOut(true); setLoading(false); return; }
    loadAll().catch(() => setSignedOut(true)).finally(() => setLoading(false));
  }, []);

  const handleSubmit = async () => {
    if (!selectedDate || !selectedVehicleId) return;
    setSubmitting(true); setError(null); setSuccessMessage(null);
    try {
      await appointmentsApi.create({ vehicle_id: selectedVehicleId, requested_date: selectedDate, notes: notes.trim() });
      setSuccessMessage("Janji temu berhasil dibuat.");
      setSelectedDate(null);
      setNotes("");
      // Refetch everything — the day just booked may now be full for
      // the next person, and the new appointment needs to show up
      // in the list below. Never trust stale local state here.
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal membuat janji temu. Coba lagi.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (id: string) => {
    setCancellingId(id);
    setError(null);
    try {
      await appointmentsApi.cancel(id);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal membatalkan janji temu.");
    } finally {
      setCancellingId(null);
    }
  };

  if (signedOut) {
    return (
      <div style={{ maxWidth: 400, margin: "100px auto", textAlign: "center", padding: "0 20px" }}>
        <p style={{ fontSize: 15 }}>Sesi Anda sudah berakhir atau belum masuk.</p>
        <Link href="/customer/login" style={{ color: "var(--rust)", fontSize: 13.5, marginTop: 10, display: "inline-block" }}>
          Masuk kembali
        </Link>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ maxWidth: 640, margin: "0 auto", padding: "40px 20px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
        </div>
      </div>
    );
  }

  // CANCELLED entries stay out of the visible list — nothing useful
  // for the customer to do with a booking that's already been
  // called off, and it would just clutter the real, active history.
  const visibleAppointments = appointments.filter((a) => a.status !== "CANCELLED");

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "40px 20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Buat Janji Temu</h1>
        <Link href="/customer/dashboard" style={{ fontSize: 13, color: "var(--steel)" }}>
          ← Kembali
        </Link>
      </div>

      {vehicles.length === 0 ? (
        <div className="card">
          <p style={{ fontSize: 13.5, color: "var(--steel)" }}>
            Belum ada kendaraan terdaftar pada akun Anda. Hubungi bengkel untuk mendaftarkan kendaraan Anda.
          </p>
        </div>
      ) : (
        <>
          <div className="card" style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Pilih Tanggal</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
              {days.map((day) => {
                const isSelected = selectedDate === day.date;
                return (
                  <button
                    key={day.date}
                    disabled={!day.available}
                    onClick={() => setSelectedDate(day.date)}
                    style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "9px 12px", borderRadius: 6, fontSize: 13.5, textAlign: "left",
                      border: isSelected ? "1.5px solid var(--rust)" : "1px solid var(--line)",
                      background: isSelected ? "var(--paper-3)" : "transparent",
                      color: day.available ? "var(--ink)" : "var(--steel-lt)",
                      cursor: day.available ? "pointer" : "not-allowed",
                      opacity: day.available ? 1 : 0.55,
                    }}
                  >
                    <span>{formatDay(day.date)}</span>
                    {!day.available && (
                      <span style={{ fontSize: 11, fontWeight: 600, color: "var(--danger)" }}>Penuh</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="card" style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Detail</h2>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12.5, color: "var(--steel)", display: "block", marginBottom: 4 }}>
                Kendaraan
              </label>
              <select
                value={selectedVehicleId}
                onChange={(e) => setSelectedVehicleId(e.target.value)}
                className="input" style={{ width: "100%" }}
              >
                {vehicles.map((v) => (
                  <option key={v.id} value={v.id}>{v.plate_number} — {v.model}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12.5, color: "var(--steel)", display: "block", marginBottom: 4 }}>
                Keluhan / Jenis Servis (opsional)
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Misal: Ganti oli & cek rem"
                className="input" style={{ width: "100%", minHeight: 70, resize: "vertical" }}
              />
            </div>
          </div>

          {error && (
            <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "8px 10px", borderRadius: 5, fontSize: 12.5, marginBottom: 14 }}>
              {error}
            </div>
          )}
          {successMessage && (
            <div style={{ background: "var(--paper-3)", color: "#2e7d4f", padding: "8px 10px", borderRadius: 5, fontSize: 12.5, marginBottom: 14 }}>
              {successMessage}
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={!selectedDate || !selectedVehicleId || submitting}
            className="btn-rust"
            style={{ width: "100%", justifyContent: "center", marginBottom: 32 }}
          >
            {submitting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Buat Janji Temu"}
          </button>
        </>
      )}

      <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>Janji Temu Saya</h2>
      {visibleAppointments.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--steel)" }}>Belum ada janji temu.</p>
      ) : (
        visibleAppointments.map((appt) => {
          const meta = APPOINTMENT_STATUS[appt.status] || { label: appt.status, color: "var(--steel)" };
          return (
            <div key={appt.id} className="card" style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{formatDay(appt.requested_date)}</div>
                  <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 3 }}>
                    {appt.vehicle_model} — {appt.vehicle_plate}
                  </div>
                  {appt.notes && (
                    <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 5 }}>{appt.notes}</div>
                  )}
                </div>
                <span
                  style={{
                    fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff",
                    background: meta.color, whiteSpace: "nowrap",
                  }}
                >
                  {meta.label}
                </span>
              </div>
              {appt.status === "CONFIRMED" && (
                <button
                  onClick={() => handleCancel(appt.id)}
                  disabled={cancellingId === appt.id}
                  className="btn-ghost"
                  style={{ fontSize: 12, marginTop: 10 }}
                >
                  {cancellingId === appt.id ? "Membatalkan…" : "Batalkan"}
                </button>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
