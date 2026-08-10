"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/accounts/page.tsx ===
// =============================================================================
import {
  ACCOUNT_TYPE_LABELS, ACCOUNT_TYPE_ORDER, accountingApi, TrialBalanceAccount,
} from "@/lib/api/accounting";
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import { Loader2 } from "lucide-react";
import { ChangeEvent, useEffect, useState } from "react";

// Same helper as the Reports page — see accounting.ts's own note on
// why every money value needs to pass through this.
function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

export default function ChartOfAccountsPage() {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [accounts, setAccounts] = useState<TrialBalanceAccount[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    accountingApi.trialBalance(asOf).then((res) => {
      setAccounts(res ? res.accounts : null);
      setLoading(false);
    });
  }, [asOf]);

  // Reuses trial-balance's own data — no dedicated backend endpoint
  // needed for this page. "Grouped list," not "tree": Account has no
  // parent/child relationship in the real schema, so there's nothing
  // to nest — every account is genuinely a flat, single-level row
  // under its type.
  const grouped = ACCOUNT_TYPE_ORDER.map((type) => ({
    type,
    label: ACCOUNT_TYPE_LABELS[type],
    accounts: (accounts ?? []).filter((a) => a.account_type === type),
  })).filter((g) => g.accounts.length > 0);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 34 }}>Daftar Akun</h1>
          <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            Setiap akun dan saldonya saat ini, dikelompokkan per tipe.
          </div>
        </div>
        <div style={{ width: 190, flexShrink: 0 }}>
          <div className="label">Per Tanggal</div>
          <input
            type="date" className="input" value={asOf}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)}
          />
        </div>
      </div>

      <AccountingSubNav />

      {loading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : !accounts ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
          Gagal memuat data, atau Anda belum tergabung dalam bengkel manapun.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {grouped.map((g) => (
            <div key={g.type} className="card">
              <div className="label" style={{ marginBottom: 12 }}>{g.label}</div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Kode</th><th>Nama Akun</th>
                    <th style={{ textAlign: "right" }}>Saldo</th>
                  </tr>
                </thead>
                <tbody>
                  {g.accounts.map((a) => (
                    <tr key={a.code}>
                      <td className="mono">{a.code}</td>
                      <td>{a.name}</td>
                      <td style={{ textAlign: "right" }} className="mono">{formatRupiah(a.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
