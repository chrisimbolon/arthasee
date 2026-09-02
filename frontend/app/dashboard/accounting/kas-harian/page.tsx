"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/kas-harian/page.tsx ===
// =============================================================================
// 1 Sep 2026 — Kas Harian. Made's own confirmed real request: a
// plain-language daily cash view, distinct from /journal (which
// stays exactly as-is, audit-grade, untouched). Built from Made and
// Chris's own approved mockup. Reuses the already-posted ledger via
// accountingApi.dailyCashActivity() — no second cash ledger table.
//
// "Kasir Balanced" is cosmetic/status-only for v1, per Chris's own
// confirmed scope call — no real till-closing/cash-drawer count
// feature exists yet, so this never claims to reconcile against a
// physical count, only against what's already posted.
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  accountingApi, DailyCashActivityDirection, DailyCashActivityResponse,
  DailyCashActivityRow,
} from "@/lib/api/accounting";
import {
  ArrowDownCircle, ArrowLeftRight, ArrowUpCircle, Loader2, Search,
} from "lucide-react";
import { ChangeEvent, useEffect, useMemo, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

type TabFilter = "ALL" | DailyCashActivityDirection;

const TABS: { id: TabFilter; label: (data: DailyCashActivityResponse | null) => string }[] = [
  { id: "ALL",      label: (d) => `Semua Aktivitas (${d ? d.activities.length : 0})` },
  { id: "in",       label: (d) => `Uang Masuk (${d ? d.in_count : 0})` },
  { id: "out",      label: (d) => `Uang Keluar (${d ? d.out_count : 0})` },
  { id: "mutation", label: (d) => `Mutasi Internal (${d ? d.mutation_count : 0})` },
];

function DirectionIcon({ direction }: { direction: DailyCashActivityDirection }) {
  if (direction === "in")  return <ArrowUpCircle size={16} style={{ color: "var(--workshop)" }} />;
  if (direction === "out") return <ArrowDownCircle size={16} style={{ color: "var(--danger)" }} />;
  return <ArrowLeftRight size={16} style={{ color: "var(--steel)" }} />;
}

function activityTitle(row: DailyCashActivityRow): string {
  if (row.direction === "mutation") {
    return `${row.from_account_name} → ${row.to_account_name}`;
  }
  return row.memo || row.category;
}

export default function KasHarianPage() {
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState<DailyCashActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabFilter>("ALL");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    accountingApi.dailyCashActivity(date).then((d) => {
      setData(d);
      setSelectedId(d && d.activities.length > 0 ? d.activities[0].journal_entry_id : null);
      setLoading(false);
    });
  }, [date]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data.activities;
    if (tab !== "ALL") rows = rows.filter((r) => r.direction === tab);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((r) =>
        activityTitle(r).toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.entry_number.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [data, tab, search]);

  const selected = filtered.find((r) => r.journal_entry_id === selectedId) ?? filtered[0] ?? null;

  const netCash = data ? toNumber(data.net_cash) : 0;

  return (
    <div>
      <h1 className="display" style={{ fontSize: 34 }}>Kas Harian</h1>
      <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4, marginBottom: 20 }}>
        Pantau seluruh pergerakan uang masuk dan keluar secara real-time tanpa pusing jurnal umum.
      </div>

      <AccountingSubNav />

      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
        <div>
          <div className="label">Tanggal</div>
          <input
            type="date" className="input" value={date}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setDate(e.target.value)}
          />
        </div>
        <div style={{ position: "relative", minWidth: 240 }}>
          <div className="label">&nbsp;</div>
          <Search size={14} style={{ position: "absolute", left: 10, top: 12, color: "var(--steel)" }} />
          <input
            type="text" className="input" placeholder="Cari deskripsi, kategori, no. entri..."
            style={{ paddingLeft: 30, width: "100%" }}
            value={search}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {loading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : !data ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel-lt)", padding: 40 }}>
          Tidak bisa memuat data kas harian.
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
            <div className="card">
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>
                Total Uang Masuk
              </div>
              <div className="mono" style={{ fontSize: 26, fontWeight: 600, color: "var(--workshop)" }}>
                {formatRupiah(data.total_in)}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6 }}>{data.in_count} transaksi</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>
                Total Uang Keluar
              </div>
              <div className="mono" style={{ fontSize: 26, fontWeight: 600, color: "var(--danger)" }}>
                {formatRupiah(data.total_out)}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6 }}>{data.out_count} transaksi pengeluaran</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>
                Arus Kas Bersih (Net Cash)
              </div>
              <div className="mono" style={{ fontSize: 26, fontWeight: 600, color: netCash >= 0 ? "var(--ink)" : "var(--danger)" }}>
                {netCash >= 0 ? "+" : ""}{formatRupiah(data.net_cash)}
              </div>
              <div style={{ fontSize: 11.5, color: netCash >= 0 ? "var(--workshop)" : "var(--danger)", marginTop: 6, display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: netCash >= 0 ? "var(--workshop)" : "var(--danger)", display: "inline-block" }} />
                {netCash >= 0 ? "Positif" : "Negatif"} — sesuai postingan sistem
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={tab === t.id ? "btn-rust" : "btn-ghost"}
              >
                {t.label(data)}
              </button>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 20, alignItems: "start" }}>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              {filtered.length === 0 ? (
                <div style={{ textAlign: "center", color: "var(--steel-lt)", fontSize: 13, padding: 32 }}>
                  Tidak ada aktivitas untuk filter ini.
                </div>
              ) : (
                <div>
                  {filtered.map((row) => {
                    const isSelected = selected?.journal_entry_id === row.journal_entry_id;
                    const sign = row.direction === "in" ? "+" : row.direction === "out" ? "-" : "";
                    const amountColor = row.direction === "in" ? "var(--workshop)" : row.direction === "out" ? "var(--danger)" : "var(--steel)";
                    return (
                      <div
                        key={row.journal_entry_id}
                        onClick={() => setSelectedId(row.journal_entry_id)}
                        style={{
                          display: "flex", alignItems: "center", gap: 12, padding: "14px 16px",
                          borderBottom: "1px solid var(--line)", cursor: "pointer",
                          background: isSelected ? "var(--paper-3)" : "transparent",
                        }}
                      >
                        <DirectionIcon direction={row.direction} />
                        <div style={{ width: 46, fontSize: 12, color: "var(--steel)", flexShrink: 0 }}>
                          {formatTime(row.created_at)}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {activityTitle(row)}
                          </div>
                          <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 2 }}>{row.category}</div>
                        </div>
                        <div className="mono" style={{ fontSize: 13.5, fontWeight: 600, color: amountColor, flexShrink: 0 }}>
                          {sign}{formatRupiah(row.amount)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="card">
              <div className="label" style={{ marginBottom: 12 }}>Detail Transaksi</div>
              {selected === null ? (
                <div style={{ fontSize: 13, color: "var(--steel-lt)" }}>Pilih transaksi untuk melihat detail.</div>
              ) : (
                <>
                  <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>{activityTitle(selected)}</div>

                  <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Status &amp; Waktu</div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                    <span style={{ color: "var(--steel)" }}>No. Entri</span>
                    <span className="mono">{selected.entry_number}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 14 }}>
                    <span style={{ color: "var(--steel)" }}>Waktu</span>
                    <span>{new Date(selected.created_at).toLocaleString("id-ID")}</span>
                  </div>

                  <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>
                    {selected.direction === "mutation" ? "Rincian Mutasi" : "Rincian Akun"}
                  </div>
                  {selected.direction === "mutation" ? (
                    <>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                        <span style={{ color: "var(--steel)" }}>Dari</span>
                        <span className="mono">{selected.from_account_code} — {selected.from_account_name}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 14 }}>
                        <span style={{ color: "var(--steel)" }}>Ke</span>
                        <span className="mono">{selected.to_account_code} — {selected.to_account_name}</span>
                      </div>
                    </>
                  ) : (
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 14 }}>
                      <span style={{ color: "var(--steel)" }}>Akun</span>
                      <span className="mono">{selected.account_code} — {selected.account_name}</span>
                    </div>
                  )}

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 14, borderTop: "1px solid var(--line)" }}>
                    <span style={{ fontSize: 14, fontWeight: 700 }}>Jumlah</span>
                    <span className="mono" style={{ fontSize: 18, fontWeight: 700 }}>{formatRupiah(selected.amount)}</span>
                  </div>

                  <a
                    href="/dashboard/accounting/journal"
                    style={{ display: "inline-block", fontSize: 12, color: "var(--rust)", marginTop: 16 }}
                  >
                    Lihat entri lengkap di Jurnal →
                  </a>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
