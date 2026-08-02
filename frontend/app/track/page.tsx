"use client";
// =============================================================================
// === frontend/app/track/page.tsx ===
// =============================================================================
// Public, unauthenticated — Fase 2 v1, confirmed with Made/Chris,
// 2 Aug. Deliberately a top-level route (sibling of /login,
// /register), NOT under /dashboard — it must never inherit the
// authenticated Sidebar/AuthContext wrapper that every /dashboard/*
// page gets. Query-param routing (?token=), same static-export
// convention already used by vehicle-detail/work-order-detail —
// next.config.ts's own output: "export" means a real dynamic
// /track/[token] route isn't possible here; every param-driven page
// in this app already works this way, this one is no different.
import { fetchPublicTracking, PublicTracking } from "@/lib/api/tracking";
import { CheckCircle2, Circle, Loader2, Wrench } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

function TrackingContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [tracking, setTracking] = useState<PublicTracking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) { setError("not_found"); setLoading(false); return; }
    fetchPublicTracking(token)
      .then(setTracking)
      .catch(() => setError("not_found"))
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "60vh", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    );
  }

  if (error || !tracking) {
    return (
      <div style={{ maxWidth: 420, margin: "80px auto", textAlign: "center", color: "var(--steel)" }}>
        <p style={{ fontSize: 15 }}>Link tidak ditemukan atau sudah tidak berlaku.</p>
        <p style={{ fontSize: 13, marginTop: 6 }}>Hubungi bengkel untuk link terbaru.</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 560, margin: "0 auto", padding: "40px 20px" }}>
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
          PublicTrackingView.get()'s own scope comment on the backend. */}
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

export default function PublicTrackingPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>Memuat…</div>}>
      <TrackingContent />
    </Suspense>
  );
}
