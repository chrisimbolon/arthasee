"use client";
// =============================================================================
// === frontend/app/customer/dashboard/page.tsx ===
// =============================================================================
// Fase 2.5's real payoff over Fase 2 v1's token links: a fleet client
// sees every one of their vehicles in one place, not one link per
// job. No auth wrapper/redirect middleware exists yet for this
// route group — a missing/expired token just shows an empty state
// with a link back to login, same low-friction spirit as the rest of his flow, rather than a hard redirect loop.

import { customerAuthApi, customerTokenStorage, customerWorkOrdersApi, CustomerWorkOrderSummary } from "@/lib/api/customerAuth";
import { Loader2, LogOut } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const STATUS_COLOR: Record<string, string> = {
  Terbuka: "#4a6d94", Dikerjakan: "var(--rust)", "Pemeriksaan Kualitas": "#b5860b",
  Selesai: "#2e7d4f", Dibatalkan: "var(--danger)",
};

function WorkOrderRow({ wo }: { wo: CustomerWorkOrderSummary }) {
  return (
    <Link
      href={`/customer/work-order?id=${wo.id}`}
      className="card"
      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, textDecoration: "none", color: "inherit" }}
    >
      <div>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{wo.vehicle_model} — {wo.vehicle_plate}</div>
        <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 3 }}>WO #{wo.work_order_number}</div>
      </div>
      <span
        style={{
          fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff",
          background: STATUS_COLOR[wo.status] || "var(--steel)",
        }}
      >
        {wo.status}
      </span>
    </Link>
  );
}

export default function CustomerDashboardPage() {
  const [tab, setTab] = useState<"active" | "history">("active");
  const [active, setActive] = useState<CustomerWorkOrderSummary[]>([]);
  const [history, setHistory] = useState<CustomerWorkOrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  // Caught live via a real hydration-mismatch error, 3 Aug:
  // useState(!customerTokenStorage.get()) reads localStorage
  // synchronously during render, which returns null on the SERVER
  // (no window there) but a real token on the CLIENT — so the
  // server-rendered HTML and the first client render genuinely
  // disagreed on which branch to show, exactly the anti-pattern
  // React's own hydration warning describes. Fixed by starting both
  // server and client renders from the SAME value (false) and only
  // ever checking the real token inside useEffect, which — unlike a
  // useState initializer — never runs during server rendering at
  // all, only after the client has mounted.
  const [signedOut, setSignedOut] = useState(false);

  useEffect(() => {
    if (!customerTokenStorage.get()) { setSignedOut(true); setLoading(false); return; }
    customerWorkOrdersApi.list()
      .then((data) => { setActive(data.active); setHistory(data.history); })
      .catch(() => setSignedOut(true))
      .finally(() => setLoading(false));
  }, []);

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

  const list = tab === "active" ? active : history;

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "40px 20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Kendaraan Saya</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Link href="/customer/appointments" className="btn-rust" style={{ fontSize: 13 }}>
            Buat Janji Temu
          </Link>
          <button
            onClick={() => { customerAuthApi.logout(); setSignedOut(true); }}
            style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", color: "var(--steel)", fontSize: 13 }}
          >
            <LogOut size={14} /> Keluar
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 18 }}>
        <button onClick={() => setTab("active")} className={tab === "active" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13 }}>
          Aktif {active.length > 0 && `(${active.length})`}
        </button>
        <button onClick={() => setTab("history")} className={tab === "history" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13 }}>
          Riwayat {history.length > 0 && `(${history.length})`}
        </button>
      </div>

      {loading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
        </div>
      ) : list.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--steel)" }}>
          {tab === "active" ? "Tidak ada pekerjaan yang sedang berjalan." : "Belum ada riwayat servis."}
        </p>
      ) : (
        list.map((wo) => <WorkOrderRow key={wo.id} wo={wo} />)
      )}
    </div>
  );
}
