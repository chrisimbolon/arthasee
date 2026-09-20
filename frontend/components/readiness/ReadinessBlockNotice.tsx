// =============================================================================
// === frontend/components/readiness/ReadinessBlockNotice.tsx ===
// =============================================================================
// 20 Sep 2026 — the contextual "blocked action" message the readiness gate's own
// docstring always promised (Estimasi belum dapat disetujui. -> Buka Pengaturan
// Akuntansi) but only the Ringkasan banner ever received.
//
// Shows: what the person tried and could not do (headline), EVERY block's own
// specific message, and a button per action that has a real destination. When a
// block has no destination yet (OPEN_OPENING_BALANCE — Roadmap Open Decision
// #33), it says so plainly instead of leaving a dead end or a fake button.
//
// Used by the six gated actions; see lib/readiness.ts for the parsing helper and
// for the one shared action-label / destination table.
import { READINESS_ACTION_HREF, READINESS_ACTION_LABEL, ReadinessBlockedError } from "@/lib/readiness";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";

export default function ReadinessBlockNotice({ blocked }: { blocked: ReadinessBlockedError }) {
  const actions = Array.from(new Set(blocked.blocks.map((b) => b.action)));
  const reachable = actions.filter((a) => READINESS_ACTION_HREF[a]);
  const hasUnreachable = actions.some((a) => !READINESS_ACTION_HREF[a]);

  return (
    <div
      className="no-print"
      role="alert"
      style={{
        background: "var(--danger-light)", border: "1px solid var(--danger)", borderRadius: 5,
        padding: "12px 14px", marginBottom: 16, display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", gap: 16, flexWrap: "wrap",
      }}
    >
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 14, color: "var(--danger)", marginBottom: 6 }}>
          <AlertTriangle size={16} /> {blocked.headline}
        </div>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--ink)" }}>
          {blocked.blocks.map((block) => (
            <li key={block.code}>{block.message}</li>
          ))}
        </ul>
        {hasUnreachable && (
          <p style={{ margin: "8px 0 0", fontSize: 12.5, color: "var(--steel)" }}>
            Sebagian langkah ini belum bisa diselesaikan sendiri dari layar mana pun — hubungi tim Arthasee.
          </p>
        )}
      </div>
      {reachable.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {reachable.map((action) => (
            <Link key={action} href={READINESS_ACTION_HREF[action]!} className="btn-rust" style={{ whiteSpace: "nowrap" }}>
              {READINESS_ACTION_LABEL[action] ?? "Lihat & Selesaikan"}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
