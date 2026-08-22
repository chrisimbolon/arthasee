"use client";
// =============================================================================
// === frontend/app/dashboard/inventory/stock-opname/page.tsx ===
// Sprint 7, Task 7.3 — the guided Stock Opname workflow's frontend.
//
// Flow, per Chris and Made's own confirmed decisions:
//   1. SELECTION — pick which parts this session covers. Pre-scoped
//      by whichever cadence tab the "Mulai Stock Opname" button was
//      clicked from (?cadence= query param), but always adjustable —
//      a scoped session, never forced to the whole catalog.
//   2. COUNTING — one row per part, system stock shown, a physical-
//      count input per row, and a LIVE variance preview computed
//      entirely client-side as staff types — no per-keystroke server
//      round-trip.
//   3. BATCH SUBMIT — "Submit Counts" sends every entered count in
//      ONE PATCH call, only once the whole table is filled in.
//   4. CONFIRM — a modal shows the netted Shortage/Surplus Rupiah
//      totals (client-computed from Part.unit_price, the same
//      valuation basis the backend itself uses) and states plainly
//      that confirming posts a real, permanent journal entry. Only
//      on confirm does this call POST .../complete/.
//   5. HISTORY — a toggleable section at the bottom lists past
//      sessions with their own net variance, computed the same way.
//
// Unit prices for the Rupiah preview are cross-referenced from the
// already-fetched Part catalog (partsApi.list()) — the backend's own
// StockOpnameLineItemSerializer deliberately doesn't duplicate
// pricing data onto every line item response.
// =============================================================================
import {
  Part, partsApi, StockOpnameLineItem, stockOpnameApi, StockOpnameSession,
} from "@/lib/api/service";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, ChevronUp,
  ClipboardList, Loader2, X,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

function toNumber(value: string | null | undefined): number {
  if (value === null || value === undefined || value === "") return NaN;
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : NaN;
}

function formatRupiah(value: number): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(value);
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const anyErr = err as { response?: { data?: { message?: string; errors?: string[] | Record<string, string[]> } } };
  const data = anyErr?.response?.data;
  if (!data) return fallback;
  if (typeof data.message === "string") return data.message;
  if (Array.isArray(data.errors)) return data.errors.join(" ");
  if (data.errors && typeof data.errors === "object") {
    return Object.values(data.errors).flat().join(" ") || fallback;
  }
  return fallback;
}

// One session's net shortage/surplus in Rupiah, computed the exact
// same way the backend does — abs(variance) × Part.unit_price per
// line, summed separately by direction. unitPriceByPart covers every
// part in the org's catalog, not just this session's own lines, so
// this same helper works for history rows about past sessions too.
function computeNetTotals(
  lineItems: StockOpnameLineItem[],
  unitPriceByPart: Record<string, number>,
  liveCounts?: Record<string, string>,
): { shortage: number; surplus: number } {
  let shortage = 0;
  let surplus = 0;
  for (const line of lineItems) {
    const physical = liveCounts ? toNumber(liveCounts[line.part]) : toNumber(line.physical_count);
    if (Number.isNaN(physical)) continue;
    const variance = physical - toNumber(line.system_stock_at_time);
    if (variance === 0) continue;
    const value = Math.abs(variance) * (unitPriceByPart[line.part] ?? 0);
    if (variance < 0) shortage += value; else surplus += value;
  }
  return { shortage, surplus };
}

// ── Confirmation modal — the real "this posts permanently" gate ───

function ConfirmCompleteModal({
  totals, submitting, onCancel, onConfirm,
}: {
  totals: { shortage: number; surplus: number };
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const zeroVariance = totals.shortage === 0 && totals.surplus === 0;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 440, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Konfirmasi Stock Opname</h2>
          <button onClick={onCancel} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          Periksa kembali sebelum melanjutkan — langkah ini akan memposting jurnal permanen ke buku besar dan tidak dapat diubah setelahnya.
        </p>

        {zeroVariance ? (
          <div style={{ background: "var(--paper)", borderRadius: 6, padding: 14, marginBottom: 18, fontSize: 13, color: "var(--steel)" }}>
            Semua hasil hitung fisik sesuai dengan stok sistem — tidak ada selisih. Tidak ada jurnal yang akan diposting, hanya sesi ini yang akan ditandai selesai.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
            <div className="card" style={{ padding: 14 }}>
              <div style={{ fontSize: 11, color: "var(--danger)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>Kekurangan (Dr 5004)</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 700, color: "var(--danger)" }}>{formatRupiah(totals.shortage)}</div>
            </div>
            <div className="card" style={{ padding: 14 }}>
              <div style={{ fontSize: 11, color: "var(--workshop)", textTransform: "uppercase", letterSpacing: "0.03em", marginBottom: 6 }}>Kelebihan (Cr 4004)</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 700, color: "var(--workshop)" }}>{formatRupiah(totals.surplus)}</div>
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-ghost" style={{ flex: 1, justifyContent: "center" }} onClick={onCancel} disabled={submitting}>
            Batal
          </button>
          <button className="btn-rust" style={{ flex: 1, justifyContent: "center" }} onClick={onConfirm} disabled={submitting}>
            {submitting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Konfirmasi & Posting"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── History section — toggleable, at the bottom of the page ───────

function HistorySection({ unitPriceByPart }: { unitPriceByPart: Record<string, number> }) {
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<StockOpnameSession[] | null>(null);

  useEffect(() => {
    if (open && sessions === null) {
      stockOpnameApi.list().then(setSessions);
    }
  }, [open, sessions]);

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <button
        onClick={() => setOpen((prev) => !prev)}
        style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center", background: "none", border: "none", padding: 0, fontSize: 15, fontWeight: 700, cursor: "pointer" }}
      >
        Riwayat Stock Opname
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>

      {open && (
        <div style={{ marginTop: 16 }}>
          {sessions === null ? (
            <div style={{ textAlign: "center", padding: 24 }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : sessions.length === 0 ? (
            <div style={{ textAlign: "center", padding: 24, color: "var(--steel)", fontSize: 13 }}>Belum ada sesi Stock Opname.</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Nomor</th><th>Status</th><th>Tanggal</th><th>Jumlah Part</th><th>Selisih Bersih</th></tr>
              </thead>
              <tbody>
                {sessions.map((s) => {
                  const totals = computeNetTotals(s.line_items, unitPriceByPart);
                  const net = totals.surplus - totals.shortage;
                  return (
                    <tr key={s.id}>
                      <td className="mono">{s.number}</td>
                      <td>
                        <span className="pill" style={{ background: s.status === "COMPLETED" ? "var(--workshop-light)" : "var(--paper)" }}>
                          {s.status === "COMPLETED" ? "Selesai" : "Draft"}
                        </span>
                      </td>
                      <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(s.created_at).toLocaleDateString("id-ID")}</td>
                      <td className="mono" style={{ fontSize: 13 }}>{s.line_items.length}</td>
                      <td className="mono" style={{ color: net > 0 ? "var(--workshop)" : net < 0 ? "var(--danger)" : "var(--steel)" }}>
                        {net === 0 ? "—" : `${net > 0 ? "+" : ""}${formatRupiah(net)}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page shell ─────────────────────────────────────────────────────

function StockOpnamePageContent() {
  const searchParams = useSearchParams();
  const cadenceHint = searchParams.get("cadence");

  const [parts, setParts] = useState<Part[]>([]);
  const [loadingParts, setLoadingParts] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [session, setSession] = useState<StockOpnameSession | null>(null);
  const [starting, setStarting] = useState(false);
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    partsApi.list().then((all) => {
      setParts(all);
      const scoped = cadenceHint ? all.filter((p) => p.reorder_cadence === cadenceHint) : all;
      setSelectedIds(new Set(scoped.map((p) => p.id)));
      setLoadingParts(false);
    });
  }, [cadenceHint]);

  const unitPriceByPart = useMemo(() => {
    const map: Record<string, number> = {};
    parts.forEach((p) => { map[p.id] = toNumber(p.unit_price); });
    return map;
  }, [parts]);

  const toggleSelected = (partId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(partId)) next.delete(partId); else next.add(partId);
      return next;
    });
  };

  const scopedParts = cadenceHint ? parts.filter((p) => p.reorder_cadence === cadenceHint) : parts;

  const handleStart = async () => {
    if (selectedIds.size === 0) {
      setError("Pilih minimal satu part untuk memulai sesi.");
      return;
    }
    setStarting(true); setError(null);
    try {
      const s = await stockOpnameApi.start(Array.from(selectedIds));
      setSession(s);
      const initial: Record<string, string> = {};
      s.line_items.forEach((li) => { initial[li.part] = ""; });
      setCounts(initial);
    } catch (err) {
      setError(extractErrorMessage(err, "Gagal memulai sesi Stock Opname."));
    } finally {
      setStarting(false);
    }
  };

  const allCounted = session
    ? session.line_items.every((li) => counts[li.part] !== undefined && counts[li.part] !== "" && !Number.isNaN(toNumber(counts[li.part])))
    : false;

  const liveTotals = useMemo(() => {
    if (!session) return { shortage: 0, surplus: 0 };
    return computeNetTotals(session.line_items, unitPriceByPart, counts);
  }, [session, counts, unitPriceByPart]);

  const handleSubmitCounts = async () => {
    if (!session) return;
    setSubmitting(true); setError(null);
    try {
      const payload = session.line_items.map((li) => ({
        part_id: li.part, physical_count: toNumber(counts[li.part]),
      }));
      const updated = await stockOpnameApi.recordCounts(session.id, payload);
      setSession(updated);
      setShowConfirm(true);
    } catch (err) {
      setError(extractErrorMessage(err, "Gagal menyimpan hasil hitung."));
    } finally {
      setSubmitting(false);
    }
  };

  const handleComplete = async () => {
    if (!session) return;
    setCompleting(true); setError(null);
    try {
      const done = await stockOpnameApi.complete(session.id);
      setSession(done);
      setShowConfirm(false);
    } catch (err) {
      setError(extractErrorMessage(err, "Gagal menyelesaikan sesi."));
      setShowConfirm(false);
    } finally {
      setCompleting(false);
    }
  };

  return (
    <div>
      <Link href="/dashboard/inventory" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>
        <ArrowLeft size={14} /> Kembali ke Spare Parts & Fluids
      </Link>

      <div style={{ marginBottom: 24 }}>
        <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Stock Opname</h1>
        <p style={{ color: "var(--steel)", fontSize: 14 }}>
          {session ? `Sesi ${session.number}` : "Hitung fisik stok dan cocokkan dengan sistem"}
        </p>
      </div>

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 18, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* ── COMPLETED ─────────────────────────────────────────── */}
      {session?.status === "COMPLETED" && (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <CheckCircle2 size={40} style={{ color: "var(--workshop)", marginBottom: 12 }} />
          <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>Sesi Selesai</h2>
          <p style={{ color: "var(--steel)", fontSize: 13, marginBottom: 20 }}>
            {session.number} telah diposting ke buku besar dan stok sistem sudah disesuaikan.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
            <button className="btn-ghost" onClick={() => { setSession(null); setCounts({}); }}>
              <ClipboardList size={15} /> Mulai Sesi Baru
            </button>
            <Link href="/dashboard/inventory" className="btn-rust" style={{ display: "flex", alignItems: "center" }}>
              Kembali ke Spare Parts & Fluids
            </Link>
          </div>
        </div>
      )}

      {/* ── COUNTING (session is DRAFT) ───────────────────────── */}
      {session && session.status === "DRAFT" && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr><th>Nama Part</th><th>Stok Sistem</th><th>Hasil Hitung Fisik</th><th>Selisih</th></tr>
            </thead>
            <tbody>
              {session.line_items.map((li) => {
                const raw = counts[li.part] ?? "";
                const physical = toNumber(raw);
                const variance = Number.isNaN(physical) ? null : physical - toNumber(li.system_stock_at_time);
                return (
                  <tr key={li.id}>
                    <td>{li.part_name}</td>
                    <td className="mono" style={{ color: "var(--steel)" }}>{li.system_stock_at_time} {li.unit}</td>
                    <td>
                      <input
                        className="input" type="number" step="0.01" min={0} style={{ width: 120 }}
                        value={raw}
                        onChange={(e) => setCounts((prev) => ({ ...prev, [li.part]: e.target.value }))}
                        placeholder="0"
                      />
                    </td>
                    <td className="mono" style={{ color: variance === null ? "var(--steel-lt)" : variance < 0 ? "var(--danger)" : variance > 0 ? "var(--workshop)" : "var(--steel)" }}>
                      {variance === null ? "—" : `${variance > 0 ? "+" : ""}${variance} ${li.unit}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ padding: 16, borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 12.5, color: "var(--steel)" }}>
              {allCounted ? "Semua part sudah dihitung." : "Isi hasil hitung untuk setiap part sebelum melanjutkan."}
            </span>
            <button className="btn-rust" disabled={!allCounted || submitting} onClick={handleSubmitCounts}>
              {submitting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Submit Counts"}
            </button>
          </div>
        </div>
      )}

      {/* ── SELECTION (no session yet) ────────────────────────── */}
      {!session && (
        <>
          {cadenceHint && (
            <div style={{ background: "var(--paper)", borderRadius: 6, padding: "10px 14px", fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>
              Menampilkan part dengan Frekuensi Pengecekan: <strong>{cadenceHint}</strong> — centang/hapus centang untuk menyesuaikan.
            </div>
          )}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {loadingParts ? (
              <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>
                      <input
                        type="checkbox"
                        checked={scopedParts.length > 0 && scopedParts.every((p) => selectedIds.has(p.id))}
                        onChange={(e) => {
                          setSelectedIds((prev) => {
                            const next = new Set(prev);
                            scopedParts.forEach((p) => (e.target.checked ? next.add(p.id) : next.delete(p.id)));
                            return next;
                          });
                        }}
                      />
                    </th>
                    <th>Nama Part</th>
                    <th>Stok Sistem Saat Ini</th>
                  </tr>
                </thead>
                <tbody>
                  {scopedParts.map((p) => (
                    <tr key={p.id}>
                      <td><input type="checkbox" checked={selectedIds.has(p.id)} onChange={() => toggleSelected(p.id)} /></td>
                      <td>{p.name}</td>
                      <td className="mono" style={{ color: "var(--steel)" }}>{p.current_stock} {p.unit}</td>
                    </tr>
                  ))}
                  {scopedParts.length === 0 && (
                    <tr><td colSpan={3} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Tidak ada part di kategori ini.</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
          <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
            <button className="btn-rust" disabled={starting || selectedIds.size === 0} onClick={handleStart}>
              {starting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : `Mulai Hitung (${selectedIds.size} part)`}
            </button>
          </div>
        </>
      )}

      {showConfirm && (
        <ConfirmCompleteModal
          totals={liveTotals}
          submitting={completing}
          onCancel={() => setShowConfirm(false)}
          onConfirm={handleComplete}
        />
      )}

      <HistorySection unitPriceByPart={unitPriceByPart} />
    </div>
  );
}

// Required by Next.js App Router: any component calling
// useSearchParams() must be wrapped in a Suspense boundary, or
// `next build`'s static generation fails outright for this route.
// The actual page logic lives in StockOpnamePageContent above; this
// default export is purely the required wrapper.
export default function StockOpnamePage() {
  return (
    <Suspense fallback={
      <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
        <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    }>
      <StockOpnamePageContent />
    </Suspense>
  );
}
