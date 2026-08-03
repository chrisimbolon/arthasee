"use client";
// =============================================================================
// === frontend/app/customer/work-order/page.tsx ===
// =============================================================================
// Reached from the dashboard list — an authenticated equivalent of
// /track, sharing the exact same TrackingCard component and backend
// payload shape (build_work_order_tracking_payload). The only real
// difference from /track is the fetch call itself (JWT session vs.
// a one-off token) and the ownership check living on the backend
// (CustomerWorkOrderDetailView only ever returns a WorkOrder for one
// of THIS customer's own vehicles).
import TrackingCard from "@/components/tracking/TrackingCard";
import { customerWorkOrdersApi } from "@/lib/api/customerAuth";
import { PublicTracking } from "@/lib/api/tracking";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function WorkOrderDetailContent() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? "";
  const [tracking, setTracking] = useState<PublicTracking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) { setError("not_found"); setLoading(false); return; }
    customerWorkOrdersApi.get(id)
      .then(setTracking)
      .catch(() => setError("not_found"))
      .finally(() => setLoading(false));
  }, [id]);

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
        <p style={{ fontSize: 15 }}>Work order tidak ditemukan.</p>
        <Link href="/customer/dashboard" style={{ color: "var(--rust)", fontSize: 13.5, marginTop: 10, display: "inline-block" }}>
          Kembali ke Kendaraan Saya
        </Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 560, margin: "0 auto", padding: "40px 20px" }}>
      <Link href="/customer/dashboard" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kendaraan Saya
      </Link>
      <TrackingCard tracking={tracking} />
    </div>
  );
}

export default function CustomerWorkOrderPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>Memuat…</div>}>
      <WorkOrderDetailContent />
    </Suspense>
  );
}
