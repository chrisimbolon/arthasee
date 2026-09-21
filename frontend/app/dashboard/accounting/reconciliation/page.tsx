"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/reconciliation/page.tsx ===
// =============================================================================
// 9 Sep 2026 — Phase 17, Task 17.3. New page — no prior version
// existed. Manual bank-statement reconciliation, v1 scope (Open
// Decision #20 defers a real live bank-feed integration).
//
// Real UI shape, mirroring the two-column pattern observed in the
// Mekari Jurnal comparison: bank statement lines on the left,
// journal activity on the right, running totals for both sides, and
// a real match/unmatch flow — select one line from each column,
// "Cocokkan" pairs them. A third, "Sudah Dicocokkan" section lists
// already-matched pairs with an "Batalkan" (unmatch) action.
//
// Account picker is scoped to Kas dan Setara Kas (KAS_SETARA_KAS)
// accounts only — the real, intended use of this feature (multi-
// till Cash/Bank reconciliation) — not every account in the COA.
//
// No rollup, no ledger mutation anywhere on this page: matching only
// ever creates/deletes a ReconciliationMatch row (pure metadata);
// nothing here ever touches a JournalEntry/JournalLine directly.
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  AccountRow,
  accountsApi,
  BankStatementImportPreviewResult,
  BankStatementImportRow, BankStatementLineRow,
  reconciliationApi,
  ReconciliationJournalLineRow, ReconciliationMatchRow, ReconciliationSummary,
} from "@/lib/api/accounting";
import { parseSpreadsheetFile, SPREADSHEET_IMPORT_ACCEPT } from "@/lib/fileImport";
import { todayISO } from "@/lib/format";
import { Loader2, Plus, Upload } from "lucide-react";
import { ChangeEvent, useEffect, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

// 16 Sep 2026 — real, deliberate design: this page never needs the
// uploaded file's own account_code column at all (if the file even
// has one) — the page already knows which account is selected via
// its own accountCode state, and every real bank statement export
// is scoped to one real account anyway. Repeating the same code on
// every row of a real Excel/CSV export would be pure friction with
// zero real benefit, so it's injected here, once, per parsed row.
function rowsFromParsedObjects(
  objects: Record<string, string>[], accountCode: string,
): { rows: BankStatementImportRow[]; error: string | null } {
  if (objects.length === 0) {
    return { rows: [], error: "File tidak memiliki baris data." };
  }
  const header = Object.keys(objects[0]);
  const required = ["statement_date", "description", "amount"];
  const missing = required.filter((c) => !header.includes(c));
  if (missing.length > 0) {
    return {
      rows: [],
      error: `Kolom wajib tidak ditemukan: ${missing.join(", ")}. Gunakan template yang disediakan.`,
    };
  }
  const rows: BankStatementImportRow[] = objects.map((obj) => ({
    account_code: accountCode,
    statement_date: obj["statement_date"] ?? "",
    description: obj["description"] ?? "",
    amount: obj["amount"] ?? "",
  }));
  return { rows, error: null };
}

function ImportStatementLinesWizard({
  accountCode, onImported,
}: {
  accountCode: string; onImported: () => void;
}) {
  const [fileName, setFileName] = useState<string | null>(null);
  const [parsedRows, setParsedRows] = useState<BankStatementImportRow[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);

  const [preview, setPreview] = useState<BankStatementImportPreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const [committing, setCommitting] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setPreview(null);
    setCommitError(null);

    const { rows: parsedObjects, error: parseErr } = await parseSpreadsheetFile(file);
    if (parseErr) {
      setParsedRows([]);
      setParseError(parseErr);
      return;
    }
    const { rows, error: mappingError } = rowsFromParsedObjects(parsedObjects, accountCode);
    setParsedRows(rows);
    setParseError(mappingError);
  }

  async function handlePreview() {
    setPreviewing(true);
    setCommitError(null);
    const result = await reconciliationApi.statementLines.previewImport(parsedRows);
    setPreview(result);
    setPreviewing(false);
  }

  async function handleCommit() {
    setCommitting(true);
    setCommitError(null);
    const result = await reconciliationApi.statementLines.commitImport(parsedRows);
    setCommitting(false);
    if (!result.success) {
      setCommitError(result.message ?? "Gagal mengimpor baris rekening koran.");
      return;
    }
    onImported();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div className="label" style={{ marginBottom: 0 }}>Impor Rekening Koran (CSV / Excel)</div>
        <a
          href="/templates/bank-statement-import-template.xlsx" download
          className="btn-ghost" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}
        >
          Unduh Template
        </a>
      </div>

      <input type="file" accept={SPREADSHEET_IMPORT_ACCEPT} onChange={handleFileChange} style={{ marginBottom: 8 }} />
      {fileName && !parseError && (
        <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 8 }}>
          {fileName} — {parsedRows.length} baris terbaca
        </div>
      )}
      {parseError && (
        <div style={{ fontSize: 13, color: "var(--danger)", marginBottom: 8 }}>{parseError}</div>
      )}

      {parsedRows.length > 0 && !parseError && !preview && (
        <button onClick={handlePreview} disabled={previewing} className="btn-rust" style={{ marginTop: 8 }}>
          {previewing ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Tinjau Data"}
        </button>
      )}

      {preview && !preview.success && (
        <div style={{ fontSize: 13, color: "var(--danger)", marginTop: 12 }}>{preview.message}</div>
      )}

      {preview && preview.success && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: "flex", gap: 16, marginBottom: 14, fontSize: 13 }}>
            <div>Total: <span className="mono">{preview.total_rows}</span></div>
            <div style={{ color: "var(--workshop)" }}>Valid: <span className="mono">{preview.valid_count}</span></div>
            <div style={{ color: (preview.error_count ?? 0) > 0 ? "var(--danger)" : undefined }}>
              Error: <span className="mono">{preview.error_count}</span>
            </div>
          </div>

          {(preview.errors?.length ?? 0) > 0 && (
            <table className="data-table" style={{ marginBottom: 14 }}>
              <thead><tr><th>Baris</th><th>Keterangan</th><th>Masalah</th></tr></thead>
              <tbody>
                {preview.errors!.map((e) => (
                  <tr key={e.row}>
                    <td className="mono">{e.row}</td>
                    <td>{e.description || "—"}</td>
                    <td style={{ color: "var(--danger)" }}>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {commitError && (
            <div style={{ fontSize: 13, color: "var(--danger)", marginBottom: 12 }}>{commitError}</div>
          )}

          {preview.can_commit ? (
            <button onClick={handleCommit} disabled={committing} className="btn-rust">
              {committing ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : `Impor ${preview.valid_count} Baris`}
            </button>
          ) : (
            <div style={{ fontSize: 13, color: "var(--steel)" }}>
              Perbaiki baris bermasalah, lalu unggah dan tinjau ulang sebelum bisa mengimpor.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ReconciliationPage() {
  const [accounts, setAccounts] = useState<AccountRow[] | null>(null);
  const [accountCode, setAccountCode] = useState<string>("");
  const [asOf, setAsOf] = useState(() => todayISO());

  const [summary, setSummary] = useState<ReconciliationSummary | null>(null);
  const [matched, setMatched] = useState<ReconciliationMatchRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);

  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selectedStatementId, setSelectedStatementId] = useState<string | null>(null);
  const [selectedJournalId, setSelectedJournalId] = useState<string | null>(null);
  const [matching, setMatching] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);

  // Load the real Kas/Bank account list once, pick a sensible default.
  useEffect(() => {
    accountsApi.list().then((rows) => {
      if (!rows) return;
      const cashAndBank = rows.filter((a) => a.account_subtype === "KAS_SETARA_KAS" && a.is_active);
      setAccounts(cashAndBank);
      if (cashAndBank.length > 0) setAccountCode(cashAndBank[0].code);
    });
  }, []);

  async function loadReconciliation() {
    if (!accountCode) return;
    setLoading(true);
    setLoadFailed(false);
    const [summaryRes, matchedRes] = await Promise.all([
      reconciliationApi.summary(accountCode, asOf),
      reconciliationApi.matches.list(accountCode),
    ]);
    if (!summaryRes) {
      setLoadFailed(true);
      setLoading(false);
      return;
    }
    setSummary(summaryRes);
    setMatched(matchedRes ?? []);
    setLoading(false);
  }

  useEffect(() => {
    loadReconciliation();
    setSelectedStatementId(null);
    setSelectedJournalId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountCode, asOf]);

  async function handleMatch() {
    if (!selectedStatementId || !selectedJournalId) return;
    setMatching(true);
    setMatchError(null);
    const result = await reconciliationApi.matches.create(selectedStatementId, selectedJournalId);
    setMatching(false);
    if (!result.success) {
      setMatchError(result.message ?? "Gagal mencocokkan baris.");
      return;
    }
    setSelectedStatementId(null);
    setSelectedJournalId(null);
    loadReconciliation();
  }

  async function handleUnmatch(matchId: string) {
    await reconciliationApi.matches.delete(matchId);
    loadReconciliation();
  }

  async function handleDeleteStatementLine(id: string) {
    const result = await reconciliationApi.statementLines.delete(id);
    if (!result.success) {
      // A matched line returns a real, specific 409 message — shown
      // directly rather than silently failing, since the user's own
      // next real action (unmatch first) is spelled out right there.
      setMatchError(result.message ?? "Gagal menghapus baris.");
      return;
    }
    loadReconciliation();
  }

  const difference = summary
    ? toNumber(summary.total_bank_balance) - toNumber(summary.total_journal_balance)
    : 0;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 34 }}>Rekonsiliasi Bank</h1>
          <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            Cocokkan baris rekening koran dengan aktivitas jurnal. Entri manual — belum
            terhubung ke rekening bank secara langsung.
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ width: 220 }}>
            <div className="label">Akun</div>
            <select
              className="input" value={accountCode}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => setAccountCode(e.target.value)}
            >
              {(accounts ?? []).map((a) => (
                <option key={a.code} value={a.code}>{a.code} — {a.name}</option>
              ))}
            </select>
          </div>
          <div style={{ width: 170 }}>
            <div className="label">Per Tanggal</div>
            <input
              type="date" className="input" value={asOf}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)}
            />
          </div>
          <button
            onClick={() => { setCreating(!creating); setImporting(false); }}
            className={creating ? "btn-ghost" : "btn-rust"}
          >
            <Plus size={16} /> Baris Rekening Koran
          </button>
          <button
            onClick={() => { setImporting(!importing); setCreating(false); }}
            className={importing ? "btn-ghost" : "btn-rust"}
          >
            <Upload size={16} /> Impor CSV/Excel
          </button>
        </div>
      </div>

      <AccountingSubNav />

      {creating && summary && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="label" style={{ marginBottom: 12 }}>Baris Rekening Koran Baru</div>
          <StatementLineForm
            accountCode={accountCode}
            onCancel={() => setCreating(false)}
            onSaved={() => { setCreating(false); loadReconciliation(); }}
          />
        </div>
      )}

      {importing && summary && (
        <div className="card" style={{ marginBottom: 20 }}>
          <ImportStatementLinesWizard
            accountCode={accountCode}
            onImported={() => { setImporting(false); loadReconciliation(); }}
          />
        </div>
      )}

      {loading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : loadFailed || !summary ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
          Gagal memuat data, atau belum ada akun Kas/Bank untuk direkonsiliasi.
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
            <div className="card" style={{ flex: 1 }}>
              <div className="label">Total Saldo di Bank</div>
              <div className="mono" style={{ fontSize: 24 }}>{formatRupiah(summary.total_bank_balance)}</div>
            </div>
            <div className="card" style={{ flex: 1 }}>
              <div className="label">Total Saldo di Jurnal</div>
              <div className="mono" style={{ fontSize: 24 }}>{formatRupiah(summary.total_journal_balance)}</div>
            </div>
            <div className="card" style={{ flex: 1 }}>
              <div className="label">Selisih</div>
              <div className="mono" style={{ fontSize: 24, color: difference === 0 ? "var(--workshop)" : "var(--danger)" }}>
                {formatRupiah(difference)}
              </div>
            </div>
          </div>

          {matchError && (
            <div className="card" style={{ marginBottom: 20, borderColor: "var(--danger)", color: "var(--danger)", fontSize: 14 }}>
              {matchError}
            </div>
          )}

          <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
            <div className="card" style={{ flex: 1 }}>
              <div className="label" style={{ marginBottom: 12 }}>
                Rekening Koran — Belum Dicocokkan ({summary.unmatched_statement_lines.length})
              </div>
              {summary.unmatched_statement_lines.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--steel)" }}>Semua baris sudah dicocokkan.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {summary.unmatched_statement_lines.map((line) => (
                    <StatementLineRow
                      key={line.id} line={line}
                      selected={selectedStatementId === line.id}
                      onSelect={() => setSelectedStatementId(selectedStatementId === line.id ? null : line.id)}
                      onDelete={() => handleDeleteStatementLine(line.id)}
                    />
                  ))}
                </div>
              )}
            </div>

            <div className="card" style={{ flex: 1 }}>
              <div className="label" style={{ marginBottom: 12 }}>
                Jurnal — Belum Dicocokkan ({summary.unmatched_journal_lines.length})
              </div>
              {summary.unmatched_journal_lines.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--steel)" }}>Semua baris sudah dicocokkan.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {summary.unmatched_journal_lines.map((line) => (
                    <JournalLineRow
                      key={line.id} line={line}
                      selected={selectedJournalId === line.id}
                      onSelect={() => setSelectedJournalId(selectedJournalId === line.id ? null : line.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }}>
            <button
              onClick={handleMatch}
              disabled={!selectedStatementId || !selectedJournalId || matching}
              className="btn-rust"
              style={{ opacity: (!selectedStatementId || !selectedJournalId) ? 0.5 : 1 }}
            >
              {matching ? "Mencocokkan..." : "Cocokkan Baris Terpilih"}
            </button>
          </div>

          <div className="card">
            <div className="label" style={{ marginBottom: 12 }}>
              Sudah Dicocokkan {matched ? `(${matched.length})` : ""}
            </div>
            {!matched || matched.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--steel)" }}>Belum ada pencocokan untuk akun ini.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Rekening Koran</th><th>Jurnal</th>
                    <th style={{ textAlign: "right" }}>Jumlah</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {matched.map((m) => (
                    <tr key={m.id}>
                      <td>{m.statement_line_description}</td>
                      <td>{m.journal_line_description || "—"}</td>
                      <td style={{ textAlign: "right" }} className="mono">{formatRupiah(m.statement_line_amount)}</td>
                      <td>
                        <button onClick={() => handleUnmatch(m.id)} className="btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }}>
                          Batalkan
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function StatementLineRow({
  line, selected, onSelect, onDelete,
}: {
  line: BankStatementLineRow; selected: boolean; onSelect: () => void; onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "10px 12px", borderRadius: 6, cursor: "pointer",
        background: selected ? "var(--workshop-lt)" : "var(--paper)",
        border: `1px solid ${selected ? "var(--workshop)" : "var(--line)"}`,
      }}
    >
      <div>
        <div style={{ fontSize: 14 }}>{line.description}</div>
        <div style={{ fontSize: 12, color: "var(--steel)" }}>{line.statement_date}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className="mono" style={{ fontSize: 14 }}>{formatRupiah(line.amount)}</div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--steel)", fontSize: 12 }}
        >
          Hapus
        </button>
      </div>
    </div>
  );
}

function JournalLineRow({
  line, selected, onSelect,
}: {
  line: ReconciliationJournalLineRow; selected: boolean; onSelect: () => void;
}) {
  const amount = toNumber(line.debit_amount) > 0 ? line.debit_amount : line.credit_amount;
  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "10px 12px", borderRadius: 6, cursor: "pointer",
        background: selected ? "var(--workshop-lt)" : "var(--paper)",
        border: `1px solid ${selected ? "var(--workshop)" : "var(--line)"}`,
      }}
    >
      <div>
        <div style={{ fontSize: 14 }}>{line.description || "(tanpa keterangan)"}</div>
        <div style={{ fontSize: 12, color: "var(--steel)" }}>
          {line.posting_date} · #{line.entry_number}
        </div>
      </div>
      <div className="mono" style={{ fontSize: 14 }}>{formatRupiah(amount)}</div>
    </div>
  );
}

function StatementLineForm({
  accountCode, onCancel, onSaved,
}: {
  accountCode: string; onCancel: () => void; onSaved: () => void;
}) {
  const [statementDate, setStatementDate] = useState(() => todayISO());
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    const result = await reconciliationApi.statementLines.create({
      account_code: accountCode, statement_date: statementDate, description, amount,
    });
    setSubmitting(false);
    if (!result.success) {
      setError(result.message ?? "Gagal menyimpan baris.");
      return;
    }
    onSaved();
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
      <div>
        <div className="label">Tanggal Transaksi</div>
        <input type="date" className="input" value={statementDate} onChange={(e) => setStatementDate(e.target.value)} />
      </div>
      <div>
        <div className="label">Keterangan</div>
        <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="mis. Setoran tunai" />
      </div>
      <div>
        <div className="label">Jumlah</div>
        <input
          className="input" type="number" value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="Positif untuk masuk, negatif untuk keluar"
        />
      </div>
      {error && <div style={{ fontSize: 13, color: "var(--danger)" }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={handleSubmit} disabled={submitting} className="btn-rust">
          {submitting ? "Menyimpan..." : "Simpan"}
        </button>
        <button onClick={onCancel} disabled={submitting} className="btn-ghost">
          Batal
        </button>
      </div>
    </div>
  );
}
