"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/operating-expenses/page.tsx ===
// 27 Aug 2026 — Made's own confirmed real request: a guided
// "Catat Beban Operasional" form, an alternative to the generic
// Manual Adjusting Journal for a recurring operating cost (salary,
// rent, utilities). No account codes, no debit/credit thinking
// required from Made himself — pick a category, enter an amount,
// pick how it was paid.
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import { accountingApi, TrialBalanceAccount } from "@/lib/api/accounting";
import {
  OperatingExpense, OperatingExpenseMethod, operatingExpensesApi,
} from "@/lib/api/payments";
import { Mechanic, mechanicsApi } from "@/lib/api/workorders";
import { Loader2, Plus, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

// 6004 (Beban Penyusutan) is deliberately excluded — reserved for
// the real, separate depreciation engine (non-cash, credits a
// contra-asset account, not Cash/Bank). Posting a depreciation entry
// through this Cash/Bank-only form would produce a real, wrong
// journal entry — enforced server-side too (OperatingExpense.record()
// rejects it outright), this is just the same rule reflected here so
// the option never even appears.
const EXCLUDED_ACCOUNT_CODE = "6004";

function CreateExpenseModal({
  accounts, mechanics, onClose, onCreated,
}: {
  accounts: TrialBalanceAccount[]; mechanics: Mechanic[];
  onClose: () => void; onCreated: (e: OperatingExpense) => void;
}) {
  const [accountCode, setAccountCode] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<OperatingExpenseMethod>("cash");
  const [mechanicId, setMechanicId] = useState("");
  // Real, must-have field, not cosmetic — without this, every
  // submission silently defaults to "right now" server-side, which
  // means the form becomes unusable the moment the CURRENT month is
  // closed (confirmed live, 28 Aug 2026 — this exact scenario, since
  // August was already closed earlier this same sprint). Defaults to
  // today, but Made needs a real way to record a genuinely backdated
  // expense (e.g. entering last week's utility bill a few days late)
  // without hitting a false "period closed" block for no real reason.
  const [paidAt, setPaidAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Made's own confirmed call, 27 Aug: mechanic attribution ONLY
  // meaningful for Gaji Karyawan (6001) — helps track labor
  // efficiency against his own real Rp15.000.000/bulan target per
  // mechanic. Reveals only for this one account, matching the
  // server-side guard exactly (OperatingExpense.record() rejects
  // mechanic being set for any other account).
  const showMechanicField = accountCode === "6001";

  const canSubmit = !!accountCode && toNumber(amount) > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    const result = await operatingExpensesApi.record({
      account_code: accountCode, amount: toNumber(amount), method,
      paid_at: paidAt ? new Date(paidAt).toISOString() : undefined,
      mechanic: showMechanicField && mechanicId ? mechanicId : undefined,
      reference: reference || undefined, notes: notes || undefined,
    });
    setSaving(false);
    if (!result.success || !result.operating_expense) {
      setError(result.message || "Gagal mencatat beban operasional.");
      return;
    }
    onCreated(result.operating_expense);
    onClose();
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 480, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Catat Beban Operasional</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          Untuk beban rutin — gaji, sewa, utilitas, dll. Dibayar langsung, tanpa perlu kode akun atau debit/kredit manual.
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Kategori Beban</label>
            <select className="input" required value={accountCode} onChange={(e) => { setAccountCode(e.target.value); setMechanicId(""); }}>
              <option value="">Pilih kategori…</option>
              {accounts.map((a) => (
                <option key={a.code} value={a.code}>{a.name}</option>
              ))}
            </select>
          </div>

          {showMechanicField && (
            <div style={{ marginBottom: 14 }}>
              <label className="label">Mekanik <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <select className="input" value={mechanicId} onChange={(e) => setMechanicId(e.target.value)}>
                <option value="">Semua / Lump Sum</option>
                {mechanics.filter((m) => m.is_active).map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label className="label">Jumlah (Rp)</label>
            <input className="input" type="number" min={0} required value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0" />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label className="label">Tanggal Dibayar</label>
            <input className="input" type="date" required value={paidAt} onChange={(e) => setPaidAt(e.target.value)} />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label className="label">Metode Pembayaran</label>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className={method === "cash" ? "btn-rust" : "btn-ghost"}
                style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
                onClick={() => setMethod("cash")}
              >
                Tunai
              </button>
              <button
                type="button"
                className={method === "bank" ? "btn-rust" : "btn-ghost"}
                style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
                onClick={() => setMethod("bank")}
              >
                Transfer Bank
              </button>
            </div>
          </div>

          <div style={{ marginBottom: 14 }}>
            <label className="label">Referensi <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="No. kwitansi/struk" />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function OperatingExpensesPage() {
  const [expenses, setExpenses] = useState<OperatingExpense[]>([]);
  const [accounts, setAccounts] = useState<TrialBalanceAccount[]>([]);
  const [mechanics, setMechanics] = useState<Mechanic[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([
      operatingExpensesApi.list(),
      accountingApi.trialBalance(),
      mechanicsApi.list(),
    ]).then(([exp, trialBalance, mechs]) => {
      setExpenses(exp);
      // Real, existing data reused, not a new endpoint — Trial
      // Balance already returns every account. Filter to real,
      // active EXPENSE-type accounts, excluding 6004 (reserved for
      // the real depreciation engine — see module-level comment).
      const expenseAccounts = (trialBalance?.accounts ?? []).filter(
        (a) => a.account_type === "EXPENSE" && a.code !== EXCLUDED_ACCOUNT_CODE,
      );
      setAccounts(expenseAccounts);
      setMechanics(mechs);
      setLoading(false);
    });
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Akuntansi</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>{expenses.length} beban operasional tercatat</p>
        </div>
        <button className="btn-rust" onClick={() => setShowCreate(true)}><Plus size={16} /> Catat Beban</button>
      </div>

      <AccountingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Nomor</th><th>Kategori</th><th>Mekanik</th><th>Metode</th><th>Tanggal</th><th>Jumlah</th></tr>
            </thead>
            <tbody>
              {expenses.map((e) => (
                <tr key={e.id}>
                  <td className="mono" style={{ color: "var(--rust)", fontWeight: 600 }}>{e.number}</td>
                  <td>{e.account_name}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{e.mechanic_name || "—"}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{e.method === "cash" ? "Tunai" : "Transfer Bank"}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(e.paid_at).toLocaleDateString("id-ID")}</td>
                  <td className="mono">{formatRupiah(e.amount)}</td>
                </tr>
              ))}
              {expenses.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada beban operasional tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateExpenseModal
          accounts={accounts} mechanics={mechanics}
          onClose={() => setShowCreate(false)}
          onCreated={(e) => setExpenses((prev) => [e, ...prev])}
        />
      )}
    </div>
  );
}
