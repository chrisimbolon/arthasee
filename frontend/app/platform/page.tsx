"use client";
// =============================================================================
// === frontend/app/platform/page.tsx ===
// Phase 22 (24 Oct 2026) — the super admin's read-only health view of every
// shop. Its own simple layout (no shop sidebar): a super admin has no shop.
// Problems first; click a row for its books and event details.
// Not /admin — that path belongs to Django admin.
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import { PlatformOverview, platformApi, ShopHealth, ShopStatus } from "@/lib/api/platform";
import { ChevronDown, ChevronRight, Loader2, LogOut, RefreshCw } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useState } from "react";

const STATUS_LABEL: Record<ShopStatus, string> = { red: "Masalah", amber: "Perhatian", green: "Sehat" };
const STATUS_COLOR: Record<ShopStatus, string> = { red: "var(--danger)", amber: "var(--hazard-dark)", green: "#2e7d4f" };
const STATUS_BG: Record<ShopStatus, string> = { red: "var(--danger-light)", amber: "rgba(214, 158, 46, 0.15)", green: "rgba(46, 125, 79, 0.12)" };
const ACCOUNT_LABEL: Record<string, string> = { "1201": "Piutang", "1301": "Persediaan", "2001": "Utang" };

function rupiah(v: string | number | undefined) {
  const n = typeof v === "string" ? parseFloat(v) : v ?? 0;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

function ago(iso: string | null) {
  if (!iso) return "Belum ada";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "Hari ini";
  if (days === 1) return "Kemarin";
  return `${days} hari lalu`;
}

function StatusPill({ status }: { status: ShopStatus }) {
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 999, fontSize: 12, fontWeight: 700,
      color: STATUS_COLOR[status], background: STATUS_BG[status], whiteSpace: "nowrap",
    }}>
      {STATUS_LABEL[status]}
    </span>
  );
}

function Tile({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div style={{ fontSize: 11.5, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--steel)", marginBottom: 6 }}>{label}</div>
      <div className="mono" style={{ fontSize: 28, fontWeight: 700, color: color ?? "inherit" }}>{value}</div>
    </div>
  );
}

function ShopDetail({ shop }: { shop: ShopHealth }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 18, padding: "14px 4px 6px", fontSize: 13 }}>
      <div>
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Kenapa statusnya begini</div>
        {shop.reasons.length === 0
          ? <div style={{ color: "var(--steel)" }}>Tidak ada masalah.</div>
          : <ul style={{ margin: 0, paddingLeft: 18 }}>{shop.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
      </div>
      <div>
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Pembukuan</div>
        <div>Neraca saldo: {shop.books.trial_balance_balanced ? "seimbang" : `TIDAK seimbang (selisih ${rupiah(shop.books.trial_balance_difference)})`}</div>
        <table style={{ width: "100%", marginTop: 6, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--steel)", fontSize: 11.5, textAlign: "left" }}>
              <th style={{ fontWeight: 600 }}>Akun</th><th style={{ fontWeight: 600, textAlign: "right" }}>Buku besar</th>
              <th style={{ fontWeight: 600, textAlign: "right" }}>Subledger</th><th style={{ fontWeight: 600, textAlign: "right" }}>Selisih</th>
            </tr>
          </thead>
          <tbody>
            {shop.books.control_accounts.map((c) => (
              <tr key={c.account_code} className="mono" style={{ fontSize: 12.5 }}>
                <td>{c.account_code} {ACCOUNT_LABEL[c.account_code] ?? ""}</td>
                {c.available ? (
                  <>
                    <td style={{ textAlign: "right" }}>{rupiah(c.gl_balance)}</td>
                    <td style={{ textAlign: "right" }}>{rupiah(c.subledger_total)}</td>
                    <td style={{ textAlign: "right", color: c.is_reconciled ? "inherit" : "var(--danger)", fontWeight: c.is_reconciled ? 400 : 700 }}>
                      {rupiah(c.difference)}
                    </td>
                  </>
                ) : <td colSpan={3} style={{ textAlign: "right", color: "var(--steel)" }}>akun tidak ada</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Event & kesiapan</div>
        <div>Event gagal: <b>{shop.events.failed}</b> · tertahan &gt; 10 menit: <b>{shop.events.stuck_pending}</b></div>
        {shop.events.last_failure && (
          <div style={{ marginTop: 6, padding: "8px 10px", background: "var(--danger-light)", borderRadius: 5, fontSize: 12 }}>
            <div><b>{shop.events.last_failure.event_type}</b> · {new Date(shop.events.last_failure.occurred_at).toLocaleString("id-ID")} · {shop.events.last_failure.attempts}x</div>
            <div className="mono" style={{ marginTop: 4, wordBreak: "break-word" }}>{shop.events.last_failure.error}</div>
          </div>
        )}
        <div style={{ marginTop: 8 }}>
          Kesiapan: {shop.readiness.ready ? "siap transaksi" : `diblokir (${shop.readiness.blocks.join(", ")})`}
        </div>
        {shop.readiness.warnings.length > 0 && (
          <div style={{ color: "var(--steel)", fontSize: 12 }}>Peringatan: {shop.readiness.warnings.join(", ")}</div>
        )}
        <div style={{ color: "var(--steel)", fontSize: 12, marginTop: 8 }}>
          Dibuat {new Date(shop.created_at).toLocaleDateString("id-ID")} · paket {shop.plan}{shop.is_active ? "" : " · NONAKTIF"}
        </div>
      </div>
    </div>
  );
}

export default function PlatformPage() {
  const { user, loading: authLoading, logout } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<PlatformOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setData(await platformApi.overview());
    } catch {
      setError("Gagal memuat data platform. Coba muat ulang.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!user) { router.replace("/login"); return; }
    if (user.role !== "super_admin") { router.replace("/dashboard"); return; }
    load();
  }, [authLoading, user, router, load]);

  if (authLoading || !user || user.role !== "super_admin") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--steel)" }}>
        <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1180, margin: "0 auto", padding: "28px max(16px, env(safe-area-inset-right, 0px)) 48px max(16px, env(safe-area-inset-left, 0px))" }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Image src="/Logo-teks-dark.png" alt="Arthasee" width={130} height={34} priority />
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--steel)" }}>Platform</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, color: "var(--steel)" }}>{user.email}</span>
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={load} disabled={loading}>
            {loading ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <RefreshCw size={13} />} Muat ulang
          </button>
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={logout}>
            <LogOut size={13} /> Keluar
          </button>
        </div>
      </header>

      <h1 className="display" style={{ fontSize: 26, marginBottom: 4, textTransform: "none" }}>Kesehatan Bengkel</h1>
      <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 20 }}>
        Semua bengkel di Arthasee, yang bermasalah paling atas. Hanya angka dan saldo akun, tanpa data pelanggan.
        {data && <> Diperbarui {new Date(data.generated_at).toLocaleTimeString("id-ID")}.</>}
      </p>

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 22 }}>
            <Tile label="Bengkel" value={data.totals.shops} />
            <Tile label="Aktif 7 hari" value={data.totals.active_last_7_days} />
            <Tile label="Masalah" value={data.totals.red} color={data.totals.red ? "var(--danger)" : undefined} />
            <Tile label="Perhatian" value={data.totals.amber} color={data.totals.amber ? "var(--hazard-dark)" : undefined} />
            <Tile label="Sehat" value={data.totals.green} color="#2e7d4f" />
          </div>

          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
              <thead>
                <tr style={{ textAlign: "left", fontSize: 11.5, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--steel)" }}>
                  <th style={{ padding: "12px 14px", width: 28 }} />
                  <th style={{ padding: "12px 8px" }}>Bengkel</th>
                  <th style={{ padding: "12px 8px" }}>Status</th>
                  <th style={{ padding: "12px 8px", textAlign: "right" }}>WO 7 / 30 hr</th>
                  <th style={{ padding: "12px 8px", textAlign: "right" }}>Invoice 7 / 30 hr</th>
                  <th style={{ padding: "12px 8px", textAlign: "right" }}>Bayar 7 / 30 hr</th>
                  <th style={{ padding: "12px 8px" }}>Aktivitas terakhir</th>
                  <th style={{ padding: "12px 14px 12px 8px", textAlign: "right" }}>Login</th>
                </tr>
              </thead>
              <tbody>
                {data.shops.map((s) => {
                  const isOpen = open === s.id;
                  return (
                    <Fragment key={s.id}>
                      <tr onClick={() => setOpen(isOpen ? null : s.id)}
                        style={{ borderTop: "1px solid var(--border, rgba(0,0,0,0.08))", cursor: "pointer", opacity: s.is_active ? 1 : 0.55 }}>
                        <td style={{ padding: "12px 14px", color: "var(--steel)" }}>{isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                        <td style={{ padding: "12px 8px" }}>
                          <div style={{ fontWeight: 600 }}>{s.name}</div>
                          <div className="mono" style={{ fontSize: 11.5, color: "var(--steel)" }}>{s.invoice_code}{s.onboarding_completed ? "" : " · onboarding belum selesai"}</div>
                        </td>
                        <td style={{ padding: "12px 8px" }}>
                          <StatusPill status={s.status} />
                          {s.reasons[0] && <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4, maxWidth: 260 }}>{s.reasons[0]}{s.reasons.length > 1 ? ` (+${s.reasons.length - 1})` : ""}</div>}
                        </td>
                        <td className="mono" style={{ padding: "12px 8px", textAlign: "right" }}>{s.activity.work_orders.last_7_days} / {s.activity.work_orders.last_30_days}</td>
                        <td className="mono" style={{ padding: "12px 8px", textAlign: "right" }}>{s.activity.invoices.last_7_days} / {s.activity.invoices.last_30_days}</td>
                        <td className="mono" style={{ padding: "12px 8px", textAlign: "right" }}>{s.activity.payments.last_7_days} / {s.activity.payments.last_30_days}</td>
                        <td style={{ padding: "12px 8px", fontSize: 13 }}>{ago(s.activity.last_activity_at)}</td>
                        <td className="mono" style={{ padding: "12px 14px 12px 8px", textAlign: "right" }}>{s.logins}</td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td />
                          <td colSpan={7} style={{ padding: "0 14px 14px 8px" }}><ShopDetail shop={s} /></td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!data && loading && (
        <div style={{ display: "flex", justifyContent: "center", padding: 48, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      )}
    </div>
  );
}
