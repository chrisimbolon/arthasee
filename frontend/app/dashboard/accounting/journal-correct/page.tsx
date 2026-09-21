"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/journal-correct/page.tsx ===
// =============================================================================
// 15 Sep 2026 — Phase 18, Task 18.7. New page — no prior version
// existed; this was the one real piece of Phase 18 explicitly
// deferred at the time (see that phase's own close-out doc: "the
// biggest piece in this whole phase," deliberately not squeezed in
// as an afterthought).
//
// Real, deliberate design: the original entry renders READ-ONLY at
// the top (mirroring journal/page.tsx's own expanded-row line-table
// styling exactly, not a new visual language), and the correction
// form below is PRE-FILLED from the original's own lines — an owner
// is editing the mistake, not retyping every account code from
// scratch. The line-entry form itself mirrors manual-journal/page.tsx's
// real, established conventions (account select sourced from the
// real trial balance, side toggle, amount input, add/remove rows,
// the same Seimbang/Belum Seimbang balance pill) rather than
// inventing a second line-entry pattern for what is, at the input
// layer, the identical kind of data (JournalEntryCorrectRecordSerializer
// deliberately mirrors ManualJournalRecordSerializer's own exact
// shape — see that serializer's own docstring, backend
// serializers.py).
//
// has_been_reversed (JournalEntryRow's own new field, this same
// batch) is checked UPFRONT here — a second correction attempt is
// blocked with a clear message before the form even renders, rather
// than letting a real caller hit JournalEntry.correct()'s own
// double-reversal guard as a raw backend error.
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  accountingApi, JournalEntryRow, JournalLineInput, TrialBalanceAccount,
} from "@/lib/api/accounting";
import api from "@/lib/api";
import { todayISO } from "@/lib/format";
import { ArrowLeft, Check, Loader2, Plus, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChangeEvent, Suspense, useEffect, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) || 0 : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

interface LineInput {
  account_code: string;
  side: "debit" | "credit";
  amount: string;
}

function emptyLine(): LineInput {
  return { account_code: "", side: "debit", amount: "" };
}

function linesFromOriginal(entry: JournalEntryRow): LineInput[] {
  return entry.lines.map((l) => {
    const debit = toNumber(l.debit_amount);
    return {
      account_code: l.account_code,
      side: debit > 0 ? "debit" : "credit",
      amount: String(debit > 0 ? l.debit_amount : l.credit_amount),
    };
  });
}

function OriginalEntryCard({ entry }: { entry: JournalEntryRow }) {
  return (
    <div className="card" style={{ marginBottom: 24, background: "var(--paper-2)" }}>
      <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 10 }}>
        Entri Asli — Tidak Bisa Diubah Langsung
      </div>
      <div style={{ display: "flex", gap: 24, marginBottom: 14, fontSize: 13.5 }}>
        <div><span style={{ color: "var(--steel)" }}>No. Entri: </span><span className="mono">{entry.entry_number}</span></div>
        <div><span style={{ color: "var(--steel)" }}>Tanggal: </span>{entry.posting_date}</div>
      </div>
      <div style={{ fontSize: 13.5, marginBottom: 14 }}>{entry.memo}</div>
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
          {entry.lines.map((l) => (
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
    </div>
  );
}

function JournalCorrectContent() {
  const searchParams = useSearchParams();
  const entryId = searchParams.get("id") ?? "";

  const [role, setRole] = useState<string | null>(null);
  const [roleLoading, setRoleLoading] = useState(true);
  const [accounts, setAccounts] = useState<TrialBalanceAccount[]>([]);

  const [entry, setEntry] = useState<JournalEntryRow | null>(null);
  const [entryLoading, setEntryLoading] = useState(true);

  const [postingDate, setPostingDate] = useState(() => todayISO());
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<LineInput[]>([emptyLine(), emptyLine()]);

  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<{ reversal_number: string; correction_number: string } | null>(null);

  useEffect(() => {
    api.get("/api/organizations/mine/")
      .then(({ data }) => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setRoleLoading(false));
    accountingApi.trialBalance().then((res) => setAccounts(res ? res.accounts : []));
  }, []);

  useEffect(() => {
    if (!entryId) { setEntryLoading(false); return; }
    accountingApi.journalEntry(entryId).then((e) => {
      setEntry(e);
      if (e) setLines(linesFromOriginal(e));
      setEntryLoading(false);
    });
  }, [entryId]);

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

    const payload = {
      posting_date: postingDate,
      reason: reason.trim(),
      lines: filledLines.map((l): JournalLineInput => ({
        account_code: l.account_code,
        ...(l.side === "debit" ? { debit: l.amount } : { credit: l.amount }),
      })),
    };

    const data = await accountingApi.correctJournalEntry(entryId, payload);
    setSubmitting(false);
    if (!data.success || !data.reversal || !data.correction) {
      setErrorMsg(data.message ?? "Gagal membuat koreksi.");
      return;
    }
    setResult({ reversal_number: data.reversal.entry_number, correction_number: data.correction.entry_number });
  }

  if (!entryId) {
    return <div style={{ color: "var(--danger)" }}>Entri jurnal tidak ditemukan — tidak ada ID yang diberikan.</div>;
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

      <h1 className="display" style={{ fontSize: 34 }}>Koreksi Entri Jurnal</h1>
      <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
        Untuk entri yang sudah terposting di periode tertutup — entri asli tidak diubah, tapi
        dibalik lalu diganti dengan entri koreksi yang baru. Kedua entri tercatat permanen.
      </div>

      <AccountingSubNav />

      {(roleLoading || entryLoading) ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : !entry ? (
        <div className="card" style={{ color: "var(--danger)" }}>Entri jurnal tidak ditemukan.</div>
      ) : result ? (
        <div className="card" style={{ padding: 40, textAlign: "center" }}>
          <Check size={28} style={{ color: "var(--workshop)", marginBottom: 12 }} />
          <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>Koreksi Berhasil Diposting</div>
          <div style={{ color: "var(--steel)", fontSize: 14, marginBottom: 20 }}>
            Entri pembalik <span className="mono">{result.reversal_number}</span> dan entri
            koreksi <span className="mono">{result.correction_number}</span> sudah tercatat.
          </div>
          <Link href="/dashboard/accounting/journal" className="btn-rust">Lihat Jurnal</Link>
        </div>
      ) : entry.has_been_reversed ? (
        <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "12px 16px", fontSize: 13, display: "flex", gap: 8, alignItems: "flex-start" }}>
          <TriangleAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>Entri ini sudah pernah dikoreksi sebelumnya — tidak bisa dikoreksi dua kali.</span>
        </div>
      ) : (
        <>
          <OriginalEntryCard entry={entry} />

          {formDisabled && (
            <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 6, padding: "12px 16px", fontSize: 13, marginBottom: 16, display: "flex", gap: 8, alignItems: "flex-start" }}>
              <TriangleAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>Hanya pemilik bengkel yang bisa membuat koreksi periode tertutup.</span>
            </div>
          )}
          {errorMsg && (
            <div style={{ background: "var(--danger-light)", color: "var(--danger)", borderRadius: 6, padding: "10px 14px", fontSize: 13, marginBottom: 16 }}>
              {errorMsg}
            </div>
          )}

          <div className="card" style={{ opacity: formDisabled ? 0.55 : 1, pointerEvents: formDisabled ? "none" : "auto" }}>
            <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 14 }}>
              Baris Koreksi — Sudah Diisi dari Entri Asli, Ubah Sesuai Kebutuhan
            </div>
            <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
              <div style={{ width: 220 }}>
                <div className="label">Tanggal Koreksi</div>
                <input
                  type="date" className="input" value={postingDate}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setPostingDate(e.target.value)}
                />
              </div>
            </div>

            <div style={{ marginBottom: 20 }}>
              <div className="label">Alasan Koreksi (wajib)</div>
              <textarea
                className="input" rows={2} value={reason}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setReason(e.target.value)}
                placeholder="Jelaskan alasan koreksi ini — akan tercatat permanen sebagai audit trail."
              />
            </div>

            <div className="label" style={{ marginBottom: 10 }}>Baris Jurnal Koreksi</div>
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
              {submitting ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : "Posting Koreksi"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// useSearchParams() requires a Suspense boundary on statically
// exported/prerendered pages — same real requirement vehicle-detail/
// customer-detail's own pages already document.
export default function JournalCorrectPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <JournalCorrectContent />
    </Suspense>
  );
}
