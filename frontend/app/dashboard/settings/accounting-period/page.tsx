"use client";
// =============================================================================
// === frontend/app/dashboard/settings/accounting-period/page.tsx ===
// =============================================================================
// 8 Oct 2026 — Chris + Sansan's "TenantReadiness" discussion surfaced a real
// gap: Wajib Tutup Buku Berurutan (the sequential-closing policy) was the
// only real period-level setting this app has, and it was buried inside the
// general Pengaturan Bengkel page, mixed in with name/phone/logo — no real
// "accounting period settings" destination existed, even though the
// onboarding copy (Saldo Awal step) was about to start implying one does.
//
// This page is deliberately NOT where periods get closed/reopened — that
// workflow already exists, fully built and tested, on the Laporan tab
// (Reports page's own PeriodControlPanel) right next to the P&L a person
// needs to see before deciding to close a month. Moving it here would
// separate the action from the numbers that justify it. This page only
// hosts the policy toggle, a quick status line, and a link back to that
// real screen.
import { AccountingPeriod, accountingApi } from "@/lib/api/accounting";
import { Organization, organizationsApi } from "@/lib/api/organizations";
import SettingsSubNav from "@/components/settings/SettingsSubNav";
import { AlertTriangle, Check, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const MONTH_NAMES_ID = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

function todayISO(): string {
  // Same local-date convention this codebase uses everywhere else
  // (apps.accounting.periods.safe_local_date's own frontend counterpart) —
  // never new Date().toISOString(), which would read the UTC calendar day.
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function CurrentPeriodStatus() {
  const [periods, setPeriods] = useState<AccountingPeriod[] | null>(null);

  useEffect(() => {
    accountingApi.periods().then(setPeriods);
  }, []);

  if (periods === null) {
    return (
      <p style={{ fontSize: 13, color: "var(--steel)", display: "flex", alignItems: "center", gap: 6 }}>
        <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> Memuat periode berjalan…
      </p>
    );
  }

  const today = todayISO();
  const current = periods.find((p) => p.start_date <= today && today <= p.end_date);

  if (!current) {
    // Genuinely shouldn't happen (the 60-day lookahead cron keeps every org
    // covered), but never silently show nothing if it somehow does.
    return (
      <p style={{ fontSize: 13, color: "var(--steel)" }}>
        Belum ada periode akuntansi yang mencakup tanggal hari ini.
      </p>
    );
  }

  return (
    <p style={{ fontSize: 13.5, color: "var(--ink)" }}>
      Periode berjalan: <strong>{MONTH_NAMES_ID[current.month - 1]} {current.year}</strong>
      {" — "}
      <span style={{ color: current.is_closed ? "var(--steel)" : "var(--workshop)" }}>
        {current.is_closed ? "Ditutup" : "Terbuka"}
      </span>
    </p>
  );
}

export default function AccountingPeriodSettingsPage() {
  const [org, setOrg] = useState<Organization | null>(null);
  const [requiresSequential, setRequiresSequential] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Same proactive-only gate as every other settings form in this app —
  // real enforcement is owner-only on the backend (OrganizationSettings
  // UpdateSerializer's own PATCH).
  const [isOwner, setIsOwner] = useState(true);

  useEffect(() => {
    organizationsApi.mine().then((res) => {
      if (res) {
        setOrg(res.organization);
        setRequiresSequential(res.organization.requires_sequential_period_closing);
        setIsOwner(res.role === "owner");
      }
    }).finally(() => setLoading(false));
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null); setSaved(false);
    try {
      const updated = await organizationsApi.update({
        requires_sequential_period_closing: requiresSequential,
      });
      setOrg(updated);
      setRequiresSequential(updated.requires_sequential_period_closing);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data;
      setError(apiMessage?.message || "Gagal menyimpan pengaturan.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  if (!org) {
    return <div style={{ color: "var(--danger)" }}>Anda belum tergabung dalam bengkel manapun.</div>;
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <SettingsSubNav />
      <h1 className="display" style={{ fontSize: 26, marginBottom: 4, textTransform: "none" }}>Pengaturan Periode Akuntansi</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 24 }}>
        Kebijakan penutupan buku bulanan — terpisah dari Tanggal Mulai Akuntansi
        (diisi sekali di Saldo Awal Bengkel) dan dari penutupan periode itu sendiri
        (dilakukan di Laporan Keuangan).
      </p>

      {!isOwner && (
        <div style={{ background: "var(--paper-3)", color: "var(--steel)", padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={15} /> Hanya pemilik bengkel yang bisa mengubah pengaturan ini.
        </div>
      )}

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBottom: 18 }}>
        <CurrentPeriodStatus />
        <Link href="/dashboard/accounting/reports" className="btn-ghost" style={{ display: "inline-flex", alignItems: "center", marginTop: 10, fontSize: 13 }}>
          Kelola &amp; Tutup Periode di Laporan Keuangan →
        </Link>
      </div>

      <form onSubmit={handleSave} className="card">
        <div style={{ marginBottom: 6 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, opacity: isOwner ? 1 : 0.6 }}>
            <input
              type="checkbox" checked={requiresSequential} disabled={!isOwner}
              onChange={(e) => setRequiresSequential(e.target.checked)}
            />
            Wajib Tutup Buku Berurutan
          </label>
          <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 6, marginBottom: 20 }}>
            Jika aktif (disarankan), periode akuntansi harus ditutup secara berurutan —
            periode sebelumnya harus ditutup dulu sebelum periode berikutnya bisa ditutup.
          </p>
        </div>

        <button className="btn-rust" type="submit" disabled={saving || !isOwner} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : saved ? <Check size={15} /> : <Save size={15} />}
          {saved ? "Tersimpan" : "Simpan Pengaturan"}
        </button>
      </form>
    </div>
  );
}
