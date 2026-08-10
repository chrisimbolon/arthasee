"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/manual-journal/page.tsx ===
// =============================================================================
import api from "@/lib/api";
import { accountingApi, JournalEntryRow, TrialBalanceAccount } from "@/lib/api/accounting";
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import { ArrowLeft, Loader2, Plus, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, useEffect, useState } from "react";

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(value);
}

// Two genuinely different error shapes can come back from this one
// endpoint. My own view code (unbalanced totals, bad account code,
// closed period) returns {"message": "..."}. DRF's own serializer
// validation (blank reason, wrong line count) — which client-side
// validation below should catch first in almost every real case —
// falls back to its default {"field": ["error"]} shape instead. This
// walks both honestly rather than assuming only one exists.
function extractErrorMessage(err: unknown): string {
  const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (!data) return "Gagal memposting jurnal.";
  if (typeof data.message === "string") return data.message;
  for (const key of Object.keys(data)) {
    const val = data[key];
    if (Array.isArray(val) && typeof val[0] === "string") return val[0];
    if (Array.isArray(val) && val[0] && typeof val[0] === "object") {
      const nested = val[0] as Record<string, unknown>;
      const nestedKey = Object.keys(nested)[0];
      const nestedVal = nestedKey ? nested[nestedKey] : undefined;
      if (Array.isArray(nestedVal) && typeof nestedVal[0] === "string") return nestedVal[0];
    }
  }
  return "Gagal memposting jurnal.";
}

interface LineInput {
  account_code: string;
  side: "debit" | "credit";
  amount: string;
}

function emptyLine(): LineInput {
  return { account_code: "", side: "debit", amount: "" };
}

export default function ManualJournalPage() {
  const [role, setRole] = useState<string | null>(null);
  const [roleLoading, setRoleLoading] = useState(true);
  const [accounts, setAccounts] = useState<TrialBalanceAccount[]>([]);

  const [postingDate, setPostingDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<LineInput[]>([emptyLine(), emptyLine()]);

  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [warningMsg, setWarningMsg] = useState<string | null>(null);

  useEffect(() => {
    api.get("/api/organizations/mine/")
      .then(({ data }) => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setRoleLoading(false));
    accountingApi.trialBalance().then((res) => setAccounts(res ? res.accounts : []));
  }, []);

  const totalDebit = lines.reduce((sum, l) => sum + (l.side === "debit" ? toNumber(l.amount) : 0), 0);
  const totalCredit = lines.reduce((sum, l) => sum + (l.side === "credit" ? toNumber(l.amount) : 0), 0);
  const filledLines = lines.filter((l) => l.account_code && toNumber(l.amount) > 0);
  const isBalanced = totalDebit > 0 && totalDebit === totalCredit;
  const canSubmit = role === "owner" && reason.trim().length > 0 && isBalanced && filledLines.length >= 2 && !submitting;

  function updateLine(index: number, patch: Partial<LineInput>) {
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, emptyLine()]);
  }
  function removeLine(index: number) {
    setLines((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit() {
    setSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    setWarningMsg(null);

    const body = {
      posting_date: postingDate,
      reason: reason.trim(),
      lines: filledLines.map((l) => ({
        account_code: l.account_code,
        ...(l.side === "debit" ? { debit: l.amount } : { credit: l.amount }),
      })),
    };

    try {
      const { data } = await api.post<{ manual_journal: JournalEntryRow; warning?: string }>(
        "/api/accounting/manual-journals/", body,
      );
      setSuccessMsg(`Jurnal ${data.manual_journal.entry_number} berhasil diposting.`);
      if (data.warning) setWarningMsg(data.warning);
      setReason("");
      setLines([emptyLine(), emptyLine()]);
    } catch (err) {
      setErrorMsg(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  const formDisabled = role !== "owner";

  return (
    <div>
      <Link
        href="/dashboard/accounting/journal"
        style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", marginBottom: 12, textDecoration: "none" }}
      >
        <ArrowLeft size={14} /> Kembali ke Jurnal
      </Link>

      <h1 className="display" style={{ fontSize: 34 }}>Jurnal Manual</h1>
      <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
        Untuk penyesuaian akhir periode — selisih stock opname, penyusutan aset, dan koreksi lain yang tidak berasal dari transaksi otomatis.
      </div>

      <AccountingSubNav />

      {roleLoading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : (
        <>
          {formDisabled && (
            <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "12px 16px", fontSize: 13, marginBottom: 16, display: "flex", gap: 8, alignItems: "flex-start" }}>
              <TriangleAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>Hanya pemilik bengkel yang bisa memposting jurnal manual. Form di bawah dinonaktifkan untuk akun Anda.</span>
            </div>
          )}

          {successMsg && (
            <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 6, padding: "10px 14px", fontSize: 13, marginBottom: 16 }}>
              {successMsg}
            </div>
          )}
          {warningMsg && (
            <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "10px 14px", fontSize: 13, marginBottom: 16, display: "flex", gap: 8, alignItems: "flex-start" }}>
              <TriangleAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>{warningMsg}</span>
            </div>
          )}
          {errorMsg && (
            <div style={{ background: "var(--danger-light)", color: "var(--danger)", borderRadius: 6, padding: "10px 14px", fontSize: 13, marginBottom: 16 }}>
              {errorMsg}
            </div>
          )}

          <div className="card" style={{ opacity: formDisabled ? 0.55 : 1, pointerEvents: formDisabled ? "none" : "auto" }}>
            <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
              <div style={{ width: 220 }}>
                <div className="label">Tanggal Posting</div>
                <input
                  type="date" className="input" value={postingDate}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setPostingDate(e.target.value)}
                />
              </div>
            </div>

            <div style={{ marginBottom: 20 }}>
              <div className="label">Alasan (wajib)</div>
              <textarea
                className="input" rows={2} value={reason}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setReason(e.target.value)}
                placeholder="Jelaskan alasan jurnal manual ini — akan tercatat permanen sebagai audit trail."
              />
            </div>

            <div className="label" style={{ marginBottom: 10 }}>Baris Jurnal</div>
            {lines.map((line, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 10 }}>
                <div style={{ flex: 2 }}>
                  {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Akun</div>}
                  <select
                    className="input" value={line.account_code}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => updateLine(i, { account_code: e.target.value })}
                  >
                    <option value="">Pilih akun…</option>
                    {accounts.map((a) => (
                      <option key={a.code} value={a.code}>{a.code} — {a.name}</option>
                    ))}
                  </select>
                </div>
                <div style={{ width: 110 }}>
                  {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Sisi</div>}
                  <select
                    className="input" value={line.side}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => updateLine(i, { side: e.target.value as "debit" | "credit" })}
                  >
                    <option value="debit">Debit</option>
                    <option value="credit">Kredit</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  {i === 0 && <div style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 4 }}>Jumlah</div>}
                  <input
                    type="number" min="0" className="input" value={line.amount} placeholder="0"
                    onChange={(e: ChangeEvent<HTMLInputElement>) => updateLine(i, { amount: e.target.value })}
                  />
                </div>
                <button
                  type="button" onClick={() => removeLine(i)} disabled={lines.length <= 2}
                  className="btn-ghost" style={{ padding: "9px 10px" }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              type="button" onClick={addLine} className="btn-ghost"
              style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6, marginTop: 4 }}
            >
              <Plus size={14} /> Tambah Baris
            </button>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 0", borderTop: "1px solid var(--line)", marginTop: 16 }}>
              <div style={{ fontSize: 13, color: "var(--steel)" }}>
                Debit: <span className="mono" style={{ fontWeight: 600, color: "var(--ink)" }}>{formatRupiah(totalDebit)}</span>
                {"   ·   "}
                Kredit: <span className="mono" style={{ fontWeight: 600, color: "var(--ink)" }}>{formatRupiah(totalCredit)}</span>
              </div>
              <span className={`pill ${isBalanced ? "ok" : "due"}`}>
                <span className="dot" />
                {isBalanced ? "Seimbang" : "Belum Seimbang"}
              </span>
            </div>

            <button type="button" onClick={handleSubmit} disabled={!canSubmit} className="btn-rust" style={{ marginTop: 8 }}>
              {submitting ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : "Posting Jurnal"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
