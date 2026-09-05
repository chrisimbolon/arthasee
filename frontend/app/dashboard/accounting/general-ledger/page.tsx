"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/general-ledger/page.tsx ===
// 4 Sep 2026 — Buku Besar (General Ledger). Account-centric view of
// the same real, already-posted ledger /journal shows chronologically
// — never a second source of truth, just a different lens on it.
//
// Account picker reuses accountingApi.trialBalance()'s own account
// list (the same data /dashboard/accounting/accounts already fetches)
// grouped the same way (ACCOUNT_TYPE_ORDER) — no dedicated endpoint
// needed just for the dropdown.
//
// Ref Sumber column renders one of three real states — see
// trace_forward.py's own module docstring for the full reasoning:
//   - "link"  — an active, clickable reference to a confirmed detail
//     page (Invoice, WorkOrder, GoodsReceivedNote, SupplierInvoice).
//   - "badge" — a real reference number, rendered as a plain grey
//     chip with NO link — a real document exists, but no confirmed
//     detail page to send someone to yet; showing a dead link would
//     be worse than showing nothing clickable at all.
//   - "none"  — plain "Internal Action" text — no source document
//     exists at all (Manual Adjustment, Period Closing, Asset
//     Acquisition, Depreciation, Opening Balance).
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  ACCOUNT_TYPE_LABELS, ACCOUNT_TYPE_ORDER, accountingApi,
  generalLedgerApi, GeneralLedgerResult, GeneralLedgerRow, JournalEntryRow,
  TrialBalanceAccount,
} from "@/lib/api/accounting";
import { ChevronDown, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, Fragment, useEffect, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const PAGE_SIZE = 50;

function ReferenceCell({ row }: { row: GeneralLedgerRow }) {
  if (row.reference.kind === "link" && row.reference.url) {
    return (
      <Link href={row.reference.url} className="mono" style={{ color: "var(--rust)", fontSize: 12.5, textDecoration: "none" }}>
        {row.reference.label}
      </Link>
    );
  }
  if (row.reference.kind === "badge") {
    return (
      <span
        className="mono"
        style={{ fontSize: 12, color: "var(--steel)", background: "var(--paper-3)", padding: "2px 8px", borderRadius: 4 }}
      >
        {row.reference.label}
      </span>
    );
  }
  return <span style={{ fontSize: 12, color: "var(--steel-lt)", fontStyle: "italic" }}>Internal Action</span>;
}

export default function GeneralLedgerPage() {
  const [accounts, setAccounts] = useState<TrialBalanceAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountCode, setAccountCode] = useState("");

  const [since, setSince] = useState(`${new Date().getFullYear()}-01-01`);
  const [asOf, setAsOf] = useState(todayISO());
  const [page, setPage] = useState(1);

  const [ledger, setLedger] = useState<GeneralLedgerResult | null>(null);
  const [loading, setLoading] = useState(true);

  // 4 Sep 2026 — inline row expansion, mirroring the Journal page's
  // own existing expand-in-place pattern exactly, not a new drawer
  // component (see the design conversation for the full reasoning).
  // Buku Besar's own rows only ever carry the ONE line touching the
  // account being viewed — expanding fetches the entry's real, full,
  // balanced set of lines via the new single-entry detail endpoint,
  // lazily, once per entry, cached here so re-expanding a row already
  // opened once doesn't re-fetch.
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [entryDetails, setEntryDetails] = useState<Map<string, JournalEntryRow | null>>(new Map());
  const [loadingEntryId, setLoadingEntryId] = useState<string | null>(null);

  // Account list fetched once — same data Daftar Akun already
  // fetches, no dedicated endpoint for this dropdown. Defaults to
  // Cash (1001) when present, since it's the account an owner most
  // often wants to check first.
  useEffect(() => {
    accountingApi.trialBalance().then((res) => {
      const list = res ? res.accounts : [];
      setAccounts(list);
      if (list.length > 0) {
        const cash = list.find((a) => a.code === "1001");
        setAccountCode(cash ? cash.code : list[0].code);
      }
      setAccountsLoading(false);
    });
  }, []);

  useEffect(() => {
    if (!accountCode) return;
    setLoading(true);
    generalLedgerApi.get({ account: accountCode, since, asOf, page, pageSize: PAGE_SIZE }).then((res) => {
      setLedger(res);
      setLoading(false);
    });
  }, [accountCode, since, asOf, page]);

  // Changing account or date range always resets back to page 1 —
  // a stale page number left over from a larger result set could
  // otherwise silently request a page past the end of a smaller one.
  const handleAccountChange = (e: ChangeEvent<HTMLSelectElement>) => { setAccountCode(e.target.value); setPage(1); };
  const handleSinceChange   = (e: ChangeEvent<HTMLInputElement>) => { setSince(e.target.value); setPage(1); };
  const handleAsOfChange    = (e: ChangeEvent<HTMLInputElement>) => { setAsOf(e.target.value); setPage(1); };

  const toggleEntry = async (entryId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(entryId)) next.delete(entryId); else next.add(entryId);
      return next;
    });
    if (!entryDetails.has(entryId)) {
      setLoadingEntryId(entryId);
      const detail = await accountingApi.journalEntry(entryId);
      setEntryDetails((prev) => new Map(prev).set(entryId, detail));
      setLoadingEntryId(null);
    }
  };

  const grouped = ACCOUNT_TYPE_ORDER.map((type) => ({
    type,
    label: ACCOUNT_TYPE_LABELS[type],
    accounts: accounts.filter((a) => a.account_type === type),
  })).filter((g) => g.accounts.length > 0);

  const totalPages = ledger && ledger.success ? Math.max(Math.ceil(ledger.total_count / ledger.page_size), 1) : 1;

  return (
    <div>
      <h1 className="display" style={{ fontSize: 34 }}>Buku Besar</h1>
      <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4, marginBottom: 20 }}>
        Lihat pergerakan dan saldo satu akun secara detail, dengan saldo berjalan.
      </div>

      <AccountingSubNav />

      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
        <div style={{ minWidth: 240 }}>
          <div className="label">Akun</div>
          {accountsLoading ? (
            <div className="input" style={{ color: "var(--steel)" }}>Memuat akun...</div>
          ) : (
            <select className="input" value={accountCode} onChange={handleAccountChange}>
              {grouped.map((g) => (
                <optgroup key={g.type} label={g.label}>
                  {g.accounts.map((a) => (
                    <option key={a.code} value={a.code}>{a.code} — {a.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <div>
            <div className="label">Dari</div>
            <input type="date" className="input" value={since} onChange={handleSinceChange} />
          </div>
          <div>
            <div className="label">Sampai</div>
            <input type="date" className="input" value={asOf} onChange={handleAsOfChange} />
          </div>
        </div>
      </div>

      {loading || accountsLoading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : !ledger || !ledger.success ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--danger)", fontSize: 14 }}>
          {(ledger && !ledger.success ? ledger.message : null) || "Gagal memuat buku besar."}
        </div>
      ) : (
        <>
          <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 12 }}>
            {ledger.account.code} — {ledger.account.name}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 20 }}>
            <div className="card">
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Saldo Awal</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 700 }}>{formatRupiah(ledger.opening_balance)}</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Total Debit</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: "var(--workshop)" }}>{formatRupiah(ledger.total_debit)}</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Total Kredit</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: "var(--danger)" }}>{formatRupiah(ledger.total_credit)}</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Saldo Akhir</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 700 }}>{formatRupiah(ledger.closing_balance)}</div>
            </div>
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {ledger.rows.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--steel-lt)", fontSize: 13, padding: 32 }}>
                Tidak ada aktivitas untuk akun dan rentang tanggal ini.
              </div>
            ) : (
              <table className="data-table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th></th><th>Tanggal</th><th>No. Entri</th><th>Ref Sumber</th><th>Keterangan</th>
                    <th style={{ textAlign: "right" }}>Debit</th>
                    <th style={{ textAlign: "right" }}>Kredit</th>
                    <th style={{ textAlign: "right" }}>Saldo</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.rows.map((row) => {
                    const isExpanded = expandedIds.has(row.entry_id);
                    const detail = entryDetails.get(row.entry_id);
                    return (
                      <Fragment key={row.line_id}>
                        <tr onClick={() => toggleEntry(row.entry_id)} style={{ cursor: "pointer" }}>
                          <td>{isExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                          <td>{row.posting_date}</td>
                          <td className="mono">{row.entry_number}</td>
                          <td onClick={(e) => e.stopPropagation()}><ReferenceCell row={row} /></td>
                          <td style={{ fontSize: 13, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {row.memo}
                          </td>
                          <td className="mono" style={{ textAlign: "right" }}>
                            {toNumber(row.debit) > 0 ? formatRupiah(row.debit) : ""}
                          </td>
                          <td className="mono" style={{ textAlign: "right" }}>
                            {toNumber(row.credit) > 0 ? formatRupiah(row.credit) : ""}
                          </td>
                          <td className="mono" style={{ textAlign: "right", fontWeight: 600 }}>
                            {formatRupiah(row.running_balance)}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr>
                            <td colSpan={8} style={{ background: "var(--paper)", padding: "12px 14px 12px 40px" }}>
                              {loadingEntryId === row.entry_id ? (
                                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)", fontSize: 13 }}>
                                  <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Memuat entri...
                                </div>
                              ) : !detail ? (
                                <div style={{ color: "var(--danger)", fontSize: 13 }}>Gagal memuat detail entri.</div>
                              ) : (
                                <>
                                  <table style={{ width: "100%", fontSize: 13 }}>
                                    <thead>
                                      <tr style={{ color: "var(--steel)" }}>
                                        <th style={{ textAlign: "left", fontWeight: 600, padding: "4px 8px" }}>Kode</th>
                                        <th style={{ textAlign: "left", fontWeight: 600, padding: "4px 8px" }}>Akun</th>
                                        <th style={{ textAlign: "right", fontWeight: 600, padding: "4px 8px" }}>Debit</th>
                                        <th style={{ textAlign: "right", fontWeight: 600, padding: "4px 8px" }}>Kredit</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {detail.lines.map((l) => (
                                        <tr key={l.id}>
                                          <td className="mono" style={{ padding: "4px 8px" }}>{l.account_code}</td>
                                          <td style={{ padding: "4px 8px" }}>{l.account_name}</td>
                                          <td className="mono" style={{ textAlign: "right", padding: "4px 8px" }}>
                                            {toNumber(l.debit_amount) > 0 ? formatRupiah(l.debit_amount) : ""}
                                          </td>
                                          <td className="mono" style={{ textAlign: "right", padding: "4px 8px" }}>
                                            {toNumber(l.credit_amount) > 0 ? formatRupiah(l.credit_amount) : ""}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                  {detail.created_by_name && (
                                    <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 8 }}>
                                      Dibuat oleh {detail.created_by_name}
                                    </div>
                                  )}
                                </>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {ledger.total_count > ledger.page_size && (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginTop: 16 }}>
              <button
                type="button" className="btn-ghost" onClick={() => setPage((p) => Math.max(p - 1, 1))}
                disabled={page <= 1}
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                <ChevronLeft size={15} /> Sebelumnya
              </button>
              <span style={{ fontSize: 13, color: "var(--steel)" }}>Halaman {page} dari {totalPages}</span>
              <button
                type="button" className="btn-ghost" onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
                disabled={page >= totalPages}
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                Berikutnya <ChevronRight size={15} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
