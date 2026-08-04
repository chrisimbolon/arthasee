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
import { PublicJobLine, PublicStage, PublicTracking } from "@/lib/api/tracking";
import { Check, Wrench } from "lucide-react";

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

// Made's own confirmed handwritten note, 4 Aug: "Pekerjaan bertahap:
// jam mulai – jam selesai" — real per-step timing. Chris's own
// separate, explicit call the same day: this now shows on the
// customer-facing timeline too — a badly-damaged car's owner
// genuinely wants to see "bongkar done, parts on order now," not
// just an overall stage status. A real, deliberate widening of Fase
// 2 v1's original stage-level-only scope, not inferred from Made's
// note by itself. Kept visually small/nested (a dot, not a full
// numbered circle) — the stage above it still carries the primary
// visual weight, this is supporting detail underneath.
function JobLineItem({ line }: { line: PublicJobLine }) {
  const isDone = line.status === "Selesai";
  const isInProgress = line.status === "Sedang Berjalan";
  const dotColor = isDone ? "#2e7d4f" : isInProgress ? "var(--rust)" : "var(--line)";
  const time = line.completed_at ? formatTime(line.completed_at) : line.started_at ? formatTime(line.started_at) : null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
      <span style={{ flex: 1, fontSize: 12.5, color: isDone ? "var(--steel)" : "var(--text-primary, inherit)", textDecoration: isDone ? "line-through" : "none" }}>
        {line.description}
      </span>
      {isInProgress && (
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--rust)", whiteSpace: "nowrap" }}>Sedang berjalan</span>
      )}
      {time && <span className="mono" style={{ fontSize: 11, color: "var(--steel)" }}>{time}</span>}
    </div>
  );
}

// Chris's own ask, 3 Aug — "Option A": match the visual language of
// Sansan's original mockup (numbered circles, connecting line, soft
// status pills) using real stage data. Extended 4 Aug to also nest
// each stage's own real job lines underneath (see JobLineItem's own
// comment for the scope reasoning) — the numbered circle still
// represents the STAGE, job lines are supporting detail, not
// separately numbered.
function StageStep({ stage, index, total }: { stage: PublicStage; index: number; total: number }) {
  const isDone = stage.status === "Selesai";
  const isInProgress = stage.status === "Sedang Berjalan";
  const circleColor = isDone ? "#2e7d4f" : isInProgress ? "var(--rust)" : "var(--steel-lt)";
  const circleBg = isDone || isInProgress ? circleColor : "transparent";
  const circleTextColor = isDone || isInProgress ? "#fff" : "var(--steel)";
  const pillBg = isDone ? "#e3f3e9" : isInProgress ? "#fbeae2" : "var(--paper-3)";
  const pillColor = isDone ? "#2e7d4f" : isInProgress ? "var(--rust)" : "var(--steel)";
  // Real time only, never both stacked — completed_at is the more
  // meaningful single moment once a stage is done; started_at is the
  // only real signal while it's still in progress.
  const time = stage.completed_at ? formatTime(stage.completed_at) : stage.started_at ? formatTime(stage.started_at) : null;

  return (
    <div style={{ display: "flex", gap: 12 }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
        <div style={{
          width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
          background: circleBg, border: `2px solid ${circleColor}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          color: circleTextColor, fontSize: 12, fontWeight: 700,
        }}>
          {isDone ? <Check size={13} /> : index + 1}
        </div>
        {index < total - 1 && (
          <div style={{ width: 2, flex: 1, background: isDone ? "#2e7d4f" : "var(--line)", marginTop: 4, minHeight: 24 }} />
        )}
      </div>
      <div style={{ flex: 1, paddingBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{stage.name}</div>
          <span style={{ fontSize: 10.5, fontWeight: 600, color: pillColor, background: pillBg, padding: "3px 9px", borderRadius: 20, flexShrink: 0, whiteSpace: "nowrap" }}>
            {stage.status}
          </span>
        </div>
        {time && <div className="mono" style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 3 }}>{time}</div>}
        {stage.job_lines.length > 0 && (
          <div style={{ marginTop: 8, paddingLeft: 10, borderLeft: "2px solid var(--line)" }}>
            {stage.job_lines.map((line, i) => <JobLineItem key={i} line={line} />)}
          </div>
        )}
      </div>
    </div>
  );
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
        {tracking.stages.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--steel)" }}>Belum ada tahap tercatat.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {tracking.stages.map((s, i) => (
              <StageStep key={i} stage={s} index={i} total={tracking.stages.length} />
            ))}
          </div>
        )}
      </div>

      {/* Mirrors the internal page's own "Pekerjaan Lain (Tanpa
          Tahap)" section — routine work never grouped under a stage
          still has real timing now, shown the same honest way. Only
          rendered when there's genuinely something to show. */}
      {tracking.unstaged_job_lines.length > 0 && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Pekerjaan Lain</div>
          {tracking.unstaged_job_lines.map((line, i) => <JobLineItem key={i} line={line} />)}
        </div>
      )}

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
