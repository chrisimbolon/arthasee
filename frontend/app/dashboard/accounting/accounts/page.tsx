"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/accounts/page.tsx ===
// =============================================================================
// 9 Sep 2026 — Phase 17, Task 17.2. Full rewrite. Previously this
// page only ever read accountingApi.trialBalance() and rendered a
// flat, single-level list per its own former comment: "Account has
// no parent/child relationship in the real schema, so there's
// nothing to nest." That's no longer true (migration 0010 added
// Account.parent). This version:
//   - Merges TWO real data sources: accountsApi.list() (the real
//     structural source of truth — code/name/subtype/hierarchy/
//     is_active/has_posted_history) and accountingApi.trialBalance()
//     (the real, existing balance-per-account source). Merged
//     client-side by `code`, the one identifier both responses
//     share. accountsApi.list() carries NO balance field at all —
//     deliberately; balance is a report concern, not a Chart of
//     Accounts structural concern (see AccountSerializer's own
//     docstring, backend serializers.py) — so this page is what
//     actually needs both.
//   - Renders real parent/child nesting (indented rows), not a flat
//     list — but the nesting is PURELY presentational. No balance
//     rollup anywhere in this file: a child account's own balance is
//     its own real, independent number, exactly what
//     accountingApi.trialBalance() already returns for it — nothing
//     here sums a parent + its children together. Matches the
//     backend's own "zero rollup math" design (Account's own class
//     docstring, models.py; Open Decision #21).
//   - Adds real create/edit UI via accountsApi — the actual reason
//     Task 17.1 built AccountListCreateView/AccountDetailView in the
//     first place ("a hierarchy nobody can edit isn't a real
//     feature"). Inline expand-in-place editing, mirroring the same
//     established pattern Buku Besar already uses for its own
//     journal-entry row expansion (GeneralLedgerView's own
//     docstring, backend views.py) — not a new modal/dialog paradigm
//     introduced just for this page.
//   - Deliberately NO delete action anywhere — matches
//     AccountDetailView's own real design call (backend views.py):
//     deactivate (is_active) is the only removal path.
//   - Classification fields (Sub-Tipe Akun / Akun Kontra) are
//     disabled in the edit form whenever has_posted_history is true
//     — the real backend guard (Account.apply_edit()) would reject
//     the change anyway; this just surfaces that BEFORE the user
//     tries, with a real, visible explanation, rather than after a
//     round-trip error.
//   - Cycle prevention for reassigning `parent` is deliberately NOT
//     duplicated here — the real check
//     (Account._would_create_cycle()) lives once, on the backend.
//     This page only excludes the account being edited from its own
//     parent dropdown (the one trivially-always-true exclusion);
//     anything deeper is left to the backend's real error message,
//     shown verbatim on failure — same "don't duplicate a business
//     rule client-side" discipline as every other real write path in
//     this app.
//
// Styling: uses the real .btn-rust (primary) / .btn-ghost (secondary)
// classes confirmed in globals.css — same shared component classes
// as the rest of this app, not invented inline styles.
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  ACCOUNT_TYPE_LABELS,
  ACCOUNT_TYPE_ORDER,
  accountingApi,
  AccountRow,
  accountsApi,
  RECONCILABLE_CONTROL_ACCOUNT_CODES,
  TrialBalanceAccount,
} from "@/lib/api/accounting";
import AccountForm, {
  emptyFormValues, formValuesFromAccount, MergedAccountRow,
} from "@/components/accounting/AccountForm";
import { todayISO } from "@/lib/format";
import { ChevronDown, ChevronRight, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, ReactNode, useEffect, useState } from "react";

// Same helper as the Reports page — see accounting.ts's own note on
// why every money value needs to pass through this.
function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

// MergedAccountRow moved to components/accounting/AccountForm.tsx — see
// that file's own comment. Imported above.

const MAX_RENDER_DEPTH = 6; // defensive only — mirrors the backend's
// own _would_create_cycle() hop-limit reasoning (models.py): a real
// shop's own till hierarchy is expected to be 2-3 levels deep, this
// is a circuit breaker against a malformed hierarchy hanging the
// page, not a realistic limit.

// AccountFormValues / emptyFormValues() / formValuesFromAccount() moved to
// components/accounting/AccountForm.tsx — see that file's own comment.
// Imported above.

// 19 Sep 2026 — Phase 18, Task 18.2 (second pass). The inline "Cek
// Rekonsiliasi" drawer section that used to live here (one account at a
// time, no Inventory explanation, and offered for WIP/1302, which the
// backend rejects) moved to its own page. What remains is a pointer, and
// only for the three accounts the check actually supports.
function ControlAccountCheckLink({ accountCode }: { accountCode: string }) {
  if (!(RECONCILABLE_CONTROL_ACCOUNT_CODES as readonly string[]).includes(accountCode)) return null;
  return (
    <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line)", fontSize: 13 }}>
      <Link href="/dashboard/accounting/control-accounts" style={{ color: "var(--rust)", fontWeight: 600 }}>
        Buka Cek Akun Kontrol →
      </Link>
      <span style={{ color: "var(--steel)", marginLeft: 8 }}>
        Bandingkan saldo akun ini dengan sub-ledger-nya.
      </span>
    </div>
  );
}

export default function ChartOfAccountsPage() {
  const [asOf, setAsOf] = useState(() => todayISO());
  const [trialRows, setTrialRows] = useState<TrialBalanceAccount[] | null>(null);
  const [accountRows, setAccountRows] = useState<AccountRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);

  // Which row (by id) is currently expanded for editing — only one
  // at a time, same "one thing open" simplicity as Buku Besar's own
  // inline row expansion.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  async function loadAll() {
    setLoading(true);
    setLoadFailed(false);
    const [trialRes, accountsRes] = await Promise.all([
      accountingApi.trialBalance(asOf),
      accountsApi.list(),
    ]);
    if (!trialRes || !accountsRes) {
      setLoadFailed(true);
      setLoading(false);
      return;
    }
    setTrialRows(trialRes.accounts);
    setAccountRows(accountsRes);
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOf]);

  const merged: MergedAccountRow[] = (accountRows ?? []).map((a) => {
    const trialRow = (trialRows ?? []).find((t) => t.code === a.code);
    return { ...a, balance: trialRow ? trialRow.balance : null };
  });

  const grouped = ACCOUNT_TYPE_ORDER.map((type) => ({
    type,
    label: ACCOUNT_TYPE_LABELS[type],
    // Top-level rows for this group: this account's own type matches
    // the group AND it has no parent. A child is rendered nested
    // under its real parent instead (see renderRows below) — it
    // never also appears again here as a false top-level entry.
    topLevel: merged.filter((a) => a.account_type === type && !a.parent),
  })).filter((g) => g.topLevel.length > 0);

  function renderRows(topLevel: MergedAccountRow[], depth: number): ReactNode[] {
    if (depth > MAX_RENDER_DEPTH) return [];
    return topLevel.flatMap((a) => {
      const children = merged.filter((c) => c.parent === a.id);
      return [
        <AccountTableRow
          key={a.id}
          account={a}
          depth={depth}
          isEditing={editingId === a.id}
          onToggleEdit={() => setEditingId(editingId === a.id ? null : a.id)}
        />,
        ...(editingId === a.id
          ? [
              <EditPanelRow
                key={`${a.id}-edit`}
                account={a}
                allAccounts={merged}
                onCancel={() => setEditingId(null)}
                onSaved={() => { setEditingId(null); loadAll(); }}
              />,
            ]
          : []),
        ...renderRows(children, depth + 1),
      ];
    });
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 34 }}>Daftar Akun</h1>
          <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            Setiap akun dan saldonya saat ini, dikelompokkan per tipe. Sub-akun ditampilkan
            menjorok di bawah akun induknya.
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ width: 190, flexShrink: 0 }}>
            <div className="label">Per Tanggal</div>
            <input
              type="date" className="input" value={asOf}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)}
            />
          </div>
          <Link
            href="/dashboard/accounting/accounts/import"
            className="btn-ghost"
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            Impor Akun
          </Link>
          <button
            onClick={() => { setCreating(!creating); setEditingId(null); }}
            className={creating ? "btn-ghost" : "btn-rust"}
          >
            <Plus size={16} /> Tambah Akun
          </button>
        </div>
      </div>

      <AccountingSubNav />

      {creating && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="label" style={{ marginBottom: 12 }}>Akun Baru</div>
          <AccountForm
            mode="create"
            initial={emptyFormValues()}
            lockClassification={false}
            allAccounts={merged}
            excludeIdFromParentOptions={null}
            onCancel={() => setCreating(false)}
            onSaved={() => { setCreating(false); loadAll(); }}
          />
        </div>
      )}

      {loading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : loadFailed ? (
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
                    <th style={{ width: 40 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {renderRows(g.topLevel, 0)}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// AccountTableRow — one real row (parent or child, same component
// either way). Indentation is the only visual signal of depth —
// deliberately no tree lines/connectors, keeping this consistent
// with the rest of this app's plain data-table styling.
// =============================================================================
function AccountTableRow({
  account, depth, isEditing, onToggleEdit,
}: {
  account: MergedAccountRow; depth: number; isEditing: boolean; onToggleEdit: () => void;
}) {
  return (
    <tr style={{ opacity: account.is_active ? 1 : 0.5 }}>
      <td className="mono">{account.code}</td>
      <td>
        <span style={{ paddingLeft: depth * 20 }}>
          {depth > 0 && <span style={{ color: "var(--steel)", marginRight: 4 }}>↳</span>}
          {account.name}
          {!account.is_active && (
            <span style={{ fontSize: 11, color: "var(--steel)", marginLeft: 8 }}>(nonaktif)</span>
          )}
          {account.is_control_account && (
            <span style={{ fontSize: 11, color: "var(--steel)", marginLeft: 8 }}>· akun kontrol</span>
          )}
          {account.children_count > 0 && (
            <span style={{ fontSize: 11, color: "var(--steel)", marginLeft: 8 }}>
              · {account.children_count} sub-akun
            </span>
          )}
        </span>
      </td>
      <td style={{ textAlign: "right" }} className="mono">{formatRupiah(account.balance)}</td>
      <td>
        <button
          onClick={onToggleEdit}
          aria-label="Ubah akun"
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--steel)", padding: 4 }}
        >
          {isEditing ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
      </td>
    </tr>
  );
}

// =============================================================================
// EditPanelRow — the inline expansion beneath a row being edited.
// Thin wrapper around AccountForm in "edit" mode.
// =============================================================================
function EditPanelRow({
  account, allAccounts, onCancel, onSaved,
}: {
  account: MergedAccountRow; allAccounts: MergedAccountRow[]; onCancel: () => void; onSaved: () => void;
}) {
  return (
    <tr>
      <td colSpan={4} style={{ background: "var(--paper-2)", padding: 16 }}>
        {account.has_posted_history && (
          <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 12 }}>
            Akun ini sudah memiliki riwayat transaksi terposting — Sub-Tipe Akun dan status
            Akun Kontra tidak bisa diubah lagi.
          </div>
        )}
        <AccountForm
          mode="edit"
          accountId={account.id}
          initial={formValuesFromAccount(account)}
          lockClassification={account.has_posted_history}
          allAccounts={allAccounts}
          excludeIdFromParentOptions={account.id}
          onCancel={onCancel}
          onSaved={onSaved}
        />
        {account.is_control_account && <ControlAccountCheckLink accountCode={account.code} />}
      </td>
    </tr>
  );
}

