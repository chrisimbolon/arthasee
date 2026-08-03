"use client";
// =============================================================================
// === frontend/components/tracking/TrackingCard.tsx ===
// =============================================================================
// Extracted from /track/page.tsx (Fase 2 v1) when Fase 2.5 needed the
// exact same status/stage/invoice cards for a logged-in customer's
// own dashboard, not just a one-off token link. Pure presentational —
// takes the already-fetched PublicTracking payload as a prop, no data
// fetching of its own, so it's genuinely reusable regardless of
// whether the caller got the data via a public token
// (fetchPublicTracking) or an authenticated session
// (customerWorkOrdersApi.get) — both hit the exact same backend
// payload shape (backend/apps/customers/payload.py's shared builder).
import { PublicTracking } from "@/lib/api/tracking";
import { CheckCircle2, Circle, Wrench } from "lucide-react";

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

export default function TrackingCard({ tracking }: { tracking: PublicTracking }) {
  return (
    <div style={{ maxWidth: 560, margin: "0 auto" }}>
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 12, color: "var(--steel)", textTransform: "uppercase" }}>Status Pekerjaan</div>
        <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{tracking.vehicle_model} — {tracking.vehicle_plate}</div>
        <div style={{ marginTop: 6, fontSize: 14, color: "var(--steel)" }}>WO #{tracking.work_order_number} · {tracking.status}</div>
        {tracking.mechanic_name && (
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 6, fontSize: 13.5 }}>
            <Wrench size={14} /> Mekanik: {tracking.mechanic_name}
          </div>
        )}
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 14 }}>Tahap Pengerjaan</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {tracking.stages.length === 0 && (
            <p style={{ fontSize: 13, color: "var(--steel)" }}>Belum ada tahap tercatat.</p>
          )}
          {tracking.stages.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              {s.status === "Selesai" ? (
                <CheckCircle2 size={18} style={{ color: "#2e7d4f", flexShrink: 0 }} />
              ) : (
                <Circle size={18} style={{ color: s.status === "Sedang Berjalan" ? "var(--rust)" : "var(--line)", flexShrink: 0 }} />
              )}
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{s.name}</div>
                <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{s.status}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Only ever rendered once the backend actually includes it —
          WorkOrder.status === "DONE" and a real Invoice exists. See
          build_work_order_tracking_payload()'s own scope comment on
          the backend — applies identically here whether reached via
          a token link or a logged-in customer session. */}
      {tracking.invoice && (
        <div className="card">
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Invoice</div>
          <div style={{ fontSize: 13.5, display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span>Nomor</span><span className="mono">{tracking.invoice.number}</span>
          </div>
          <div style={{ fontSize: 13.5, display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span>Mekanik</span><span>{tracking.invoice.mechanic_name_snapshot}</span>
          </div>
          <div style={{ fontSize: 13.5, display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span>Status</span><span>{tracking.invoice.status}</span>
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, display: "flex", justifyContent: "space-between", marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
            <span>Total</span><span className="mono">{money(tracking.invoice.total)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
