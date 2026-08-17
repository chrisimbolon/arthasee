"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/reports/page.tsx ===
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  ACCOUNT_TYPE_LABELS, accountingApi, AgingBucket, AgingInvoiceRow,
  AgingReportResponse, BalanceSheetResponse, ProfitLossComparisonResponse,
  ProfitLossResponse, ReportDelta, ReportLine, TrialBalanceResponse,
} from "@/lib/api/accounting";
import { Loader2, TriangleAlert } from "lucide-react";
import { ChangeEvent, useEffect, useState } from "react";
// ── Shared helpers ──────────────────────────────────────────────

// The one place that resolves the string|number Decimal ambiguity —
// see accounting.ts's own note on why this exists. Every component
// below goes through this, never compares/formats a raw API value
// directly.
function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

const BUCKET_ORDER: AgingBucket[] = ["0-30", "31-60", "61-90", "90+"];

function LoadingState() {
  return (
    <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
      <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
      Gagal memuat laporan, atau Anda belum tergabung dalam bengkel manapun.
    </div>
  );
}

function BalancedPill({ isBalanced }: { isBalanced: boolean }) {
  return (
    <span className={`pill ${isBalanced ? "ok" : "due"}`}>
      <span className="dot" />
      {isBalanced ? "Seimbang" : "Tidak Seimbang"}
    </span>
  );
}

function ReportSection({ title, rows, total }: { title: string; rows: ReportLine[]; total: string | number }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div className="label" style={{ marginBottom: 10 }}>{title}</div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--steel-lt)", padding: "8px 0" }}>Tidak ada transaksi.</div>
      ) : (
        <>
          {rows.map((r) => (
            <div key={r.code} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: 14 }}>
              <span style={{ color: "var(--ink-soft)" }}>{r.name}</span>
              <span className="mono">{formatRupiah(r.amount)}</span>
            </div>
          ))}
          <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0 0", fontSize: 14, fontWeight: 700, borderTop: "1px solid var(--line)", marginTop: 4 }}>
            <span>Total {title}</span>
            <span className="mono">{formatRupiah(total)}</span>
          </div>
        </>
      )}
    </div>
  );
}

function formatPct(pct: string | number | null): string {
  if (pct === null) return "—";
  const n = toNumber(pct);
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function DeltaRow({ label, current, prior, delta }: {
  label: string; current: string | number; prior: string | number; delta: ReportDelta;
}) {
  const changeIsPositive = toNumber(delta.change) >= 0;
  const color = changeIsPositive ? "var(--workshop)" : "var(--rust)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 12, alignItems: "center", padding: "9px 0", borderBottom: "1px solid var(--line)" }}>
      <span style={{ fontSize: 13.5, fontWeight: 600 }}>{label}</span>
      <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>{formatRupiah(current)}</span>
      <span className="mono" style={{ fontSize: 13, color: "var(--steel)", textAlign: "right" }}>{formatRupiah(prior)}</span>
      <span className="mono" style={{ fontSize: 13, fontWeight: 700, color, textAlign: "right" }}>
        {formatPct(delta.change_pct)}
      </span>
    </div>
  );
}

function ComparisonPanel({ since, asOf }: { since: string; asOf: string }) {
  const [data, setData] = useState<ProfitLossComparisonResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    accountingApi.profitLossComparison(since, asOf).then((res) => { setData(res); setLoading(false); });
  }, [since, asOf]);

  // Deliberately renders nothing (not an error state) if comparison
  // fails to load — this is a nice-to-have addition to the P&L view,
  // not something that should ever block seeing the main report
  // itself, which loads completely independently.
  if (loading || !data) return null;

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div className="label" style={{ marginBottom: 4 }}>Dibandingkan Periode Sebelumnya</div>
        <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 14 }}>
        Periode sebelumnya: {new Date(data.prior.since).toLocaleDateString("id-ID")}
        {" – "}
        {new Date(data.prior.as_of).toLocaleDateString("id-ID")} (durasi sama dengan periode saat ini)
        </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 12, fontSize: 11, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.02em", paddingBottom: 6, borderBottom: "1.5px solid var(--line)" }}>
        <span></span>
        <span style={{ textAlign: "right" }}>Periode Ini</span>
        <span style={{ textAlign: "right" }}>Periode Lalu</span>
        <span style={{ textAlign: "right" }}>Perubahan</span>
      </div>
      <DeltaRow label="Pendapatan" current={data.current.total_revenue} prior={data.prior.total_revenue} delta={data.revenue_delta} />
      <DeltaRow label="Laba Kotor" current={data.current.gross_profit} prior={data.prior.gross_profit} delta={data.gross_profit_delta} />
      <DeltaRow label="Laba Bersih" current={data.current.net_income} prior={data.prior.net_income} delta={data.net_income_delta} />
    </div>
  );
}

// ── Trial Balance ────────────────────────────────────────────────

function TrialBalancePanel() {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<TrialBalanceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    accountingApi.trialBalance(asOf).then((res) => { setData(res); setLoading(false); });
  }, [asOf]);

  if (loading) return <LoadingState />;
  if (!data) return <EmptyState />;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <div style={{ width: 190 }}>
          <div className="label">Per Tanggal</div>
          <input type="date" className="input" value={asOf} onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)} />
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Kode</th><th>Nama Akun</th><th>Tipe</th>
            <th style={{ textAlign: "right" }}>Saldo</th>
          </tr>
        </thead>
        <tbody>
          {data.accounts.map((a) => (
            <tr key={a.code}>
              <td className="mono">{a.code}</td>
              <td>{a.name}</td>
              <td style={{ color: "var(--steel)", fontSize: 13 }}>{ACCOUNT_TYPE_LABELS[a.account_type] ?? a.account_type}</td>
              <td style={{ textAlign: "right" }} className="mono">{formatRupiah(a.balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 32, marginTop: 20, paddingTop: 16, borderTop: "1.5px solid var(--line)" }}>
        <div>
          <div className="label" style={{ marginBottom: 2 }}>Total Debit</div>
          <div className="mono" style={{ fontSize: 16, fontWeight: 700 }}>{formatRupiah(data.total_debit)}</div>
        </div>
        <div>
          <div className="label" style={{ marginBottom: 2 }}>Total Kredit</div>
          <div className="mono" style={{ fontSize: 16, fontWeight: 700 }}>{formatRupiah(data.total_credit)}</div>
        </div>
        <BalancedPill isBalanced={data.is_balanced} />
      </div>
    </div>
  );
}

// ── Profit & Loss ────────────────────────────────────────────────

function ProfitLossPanel() {
  const today = new Date().toISOString().slice(0, 10);
  const [since, setSince] = useState(`${new Date().getFullYear()}-01-01`);
  const [asOf, setAsOf] = useState(today);
  const [data, setData] = useState<ProfitLossResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    accountingApi.profitLoss(since, asOf).then((res) => { setData(res); setLoading(false); });
  }, [since, asOf]);

  if (loading) return <LoadingState />;
  if (!data) return <EmptyState />;

  const netIncome = toNumber(data.net_income);

  return (
    <div className="card">
      <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
        <div style={{ flex: 1 }}>
          <div className="label">Dari Tanggal</div>
          <input type="date" className="input" value={since} onChange={(e: ChangeEvent<HTMLInputElement>) => setSince(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div className="label">Sampai Tanggal</div>
          <input type="date" className="input" value={asOf} onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)} />
        </div>
      </div>

      <ComparisonPanel since={since} asOf={asOf} />

      <ReportSection title="Pendapatan" rows={data.revenue} total={data.total_revenue} />
      <ReportSection title="Harga Pokok Penjualan (HPP)" rows={data.cogs} total={data.total_cogs} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 0", borderTop: "1.5px solid var(--line)", borderBottom: "1.5px solid var(--line)", margin: "8px 0 20px" }}>
        <div style={{ fontWeight: 700 }}>Laba Kotor</div>
        <div className="mono" style={{ fontWeight: 700, fontSize: 16 }}>{formatRupiah(data.gross_profit)}</div>
      </div>

      {/* Roadmap's own explicit requirement — this caveat must stay
          visible, not get buried or dropped. It ships as a real
          field in the API response specifically so this can't be
          silently omitted here. */}
      <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "10px 14px", fontSize: 12.5, marginBottom: 24, display: "flex", gap: 8, alignItems: "flex-start" }}>
        <TriangleAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>{data.gross_profit_note}</span>
      </div>

      <ReportSection title="Beban Operasional" rows={data.expenses} total={data.total_expenses} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 0 0" }}>
        <div style={{ fontWeight: 700, fontSize: 16 }}>Laba Bersih</div>
        <div className="mono" style={{ fontWeight: 800, fontSize: 20, color: netIncome >= 0 ? "var(--workshop)" : "var(--rust)" }}>
          {formatRupiah(data.net_income)}
        </div>
      </div>
    </div>
  );
}

// ── Balance Sheet ────────────────────────────────────────────────

function BalanceSheetPanel() {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<BalanceSheetResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    accountingApi.balanceSheet(asOf).then((res) => { setData(res); setLoading(false); });
  }, [asOf]);

  if (loading) return <LoadingState />;
  if (!data) return <EmptyState />;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 20 }}>
        <div style={{ width: 190 }}>
          <div className="label">Per Tanggal</div>
          <input type="date" className="input" value={asOf} onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 40 }}>
        <div>
          <ReportSection
            title="Aset"
            rows={data.assets.map((a) => ({ code: a.code, name: a.name, amount: a.balance }))}
            total={data.total_assets}
          />
        </div>
        <div>
          <ReportSection
            title="Liabilitas"
            rows={data.liabilities.map((l) => ({ code: l.code, name: l.name, amount: l.balance }))}
            total={data.total_liabilities}
          />
          <div style={{ marginBottom: 20 }}>
            <div className="label" style={{ marginBottom: 10 }}>Ekuitas</div>
            {data.equity.map((r) => (
              <div key={r.code} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: 14 }}>
                <span style={{ color: "var(--ink-soft)" }}>{r.name}</span>
                <span className="mono">{formatRupiah(r.balance)}</span>
              </div>
            ))}
            {/* The unclosed-books line — no closing entries exist in
                this system, so current-period net income has to be
                shown explicitly here for the sheet to balance
                honestly. See reports.py's own docstring for why. */}
            <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: 14 }}>
              <span style={{ color: "var(--ink-soft)" }}>Laba Tahun Berjalan (Belum Ditutup)</span>
              <span className="mono">{formatRupiah(data.current_year_earnings)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0 0", fontSize: 14, fontWeight: 700, borderTop: "1px solid var(--line)", marginTop: 4 }}>
              <span>Total Ekuitas</span>
              <span className="mono">{formatRupiah(data.total_equity)}</span>
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 0", borderTop: "1.5px solid var(--line)", marginTop: 8, flexWrap: "wrap", gap: 12 }}>
        <div style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>
          Total Aset: <span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{formatRupiah(data.total_assets)}</span>
          {"  vs  "}
          Total Liabilitas + Ekuitas: <span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{formatRupiah(data.total_liabilities_and_equity)}</span>
        </div>
        <BalancedPill isBalanced={data.is_balanced} />
      </div>
    </div>
  );
}

// ── Aging AR / AP ────────────────────────────────────────────────

function AgingPanel({ type }: { type: "ar" | "ap" }) {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<AgingReportResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const fetcher = type === "ar" ? accountingApi.agingAR : accountingApi.agingAP;
    fetcher(asOf).then((res) => { setData(res); setLoading(false); });
  }, [asOf, type]);

  if (loading) return <LoadingState />;
  if (!data) return <EmptyState />;

  const rows: AgingInvoiceRow[] = (type === "ar" ? data.invoices : data.supplier_invoices) ?? [];
  const nounLabel = type === "ar" ? "Pelanggan" : "Supplier";
  const emptyLabel = type === "ar" ? "piutang" : "utang";

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 20 }}>
        <div style={{ width: 190 }}>
          <div className="label">Per Tanggal</div>
          <input type="date" className="input" value={asOf} onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
        {BUCKET_ORDER.map((bucket) => (
          <div key={bucket} className="card" style={{ padding: 16 }}>
            <div className="label" style={{ marginBottom: 6 }}>{bucket} hari</div>
            <div className="mono" style={{ fontSize: 17, fontWeight: 700 }}>{formatRupiah(data.buckets[bucket])}</div>
          </div>
        ))}
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Nomor</th><th>{nounLabel}</th>
            <th style={{ textAlign: "right" }}>Jumlah</th><th>Umur</th><th>Kategori</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={5} style={{ textAlign: "center", color: "var(--steel-lt)", padding: 24 }}>Tidak ada {emptyLabel} tertunggak.</td></tr>
          ) : rows.map((r) => (
            <tr key={r.id}>
              <td className="mono">{r.number}</td>
              <td>{r.customer_name ?? r.supplier_name}</td>
              <td style={{ textAlign: "right" }} className="mono">{formatRupiah((r.balance_due ?? r.amount) as string | number)}</td>
              <td>{r.age_days} hari</td>
              <td>
                <span className={`pill ${r.bucket === "0-30" ? "ok" : r.bucket === "90+" ? "due" : "soon"}`}>{r.bucket}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16, paddingTop: 16, borderTop: "1.5px solid var(--line)" }}>
        <div style={{ fontWeight: 700 }}>Total Tertunggak: <span className="mono">{formatRupiah(data.total_outstanding)}</span></div>
      </div>
    </div>
  );
}

// ── Page shell ───────────────────────────────────────────────────

type ReportTab = "trial-balance" | "profit-loss" | "balance-sheet" | "aging-ar" | "aging-ap";

const TABS: { id: ReportTab; label: string }[] = [
  { id: "trial-balance", label: "Neraca Saldo" },
  { id: "profit-loss",   label: "Laba Rugi" },
  { id: "balance-sheet", label: "Neraca" },
  { id: "aging-ar",      label: "Piutang (AR)" },
  { id: "aging-ap",      label: "Utang (AP)" },
];

export default function AccountingReportsPage() {
  const [tab, setTab] = useState<ReportTab>("trial-balance");

  return (
    <div>
      <h1 className="display" style={{ fontSize: 34 }}>Laporan Keuangan</h1>
      <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4, marginBottom: 24 }}>
        Neraca saldo, laba rugi, neraca, dan umur piutang/utang — dibangun langsung dari jurnal yang sudah diposting.
      </div>

      <AccountingSubNav />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 24 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={tab === t.id ? "btn-rust" : "btn-ghost"}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "trial-balance" && <TrialBalancePanel />}
      {tab === "profit-loss" && <ProfitLossPanel />}
      {tab === "balance-sheet" && <BalanceSheetPanel />}
      {tab === "aging-ar" && <AgingPanel type="ar" />}
      {tab === "aging-ap" && <AgingPanel type="ap" />}
    </div>
  );
}
