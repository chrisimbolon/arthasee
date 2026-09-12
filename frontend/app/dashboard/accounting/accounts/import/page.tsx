"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/accounts/import/page.tsx ===
// =============================================================================
// 9 Sep 2026 — Phase 18, Task 18.8. New page — no prior version
// existed. Real, deliberate v1 scope, matching the locked design
// spec exactly: a fixed-template CSV upload (no fuzzy auto-detected
// column mapping — "Unduh Template" is the real answer to "what
// columns do I need"), parsed entirely client-side into plain JSON,
// then a real preview -> commit flow against the backend's own
// account_import.py, the same two-step "review the exact figure
// before committing" doctrine the Opening Balance wizard already
// established.
//
// The backend NEVER receives a raw file -- only a plain JSON array
// of row objects (see accountImportApi in lib/api/accounting.ts).
// CSV parsing lives here, entirely dependency-free -- a deliberate
// choice (Chris's own confirmed call) to avoid a new frontend
// library for a v1 feature whose real file format is this app's own
// fixed, six-column template, not arbitrary user spreadsheets.
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  accountImportApi, AccountImportPreviewResult, AccountImportRow,
  ACCOUNT_SUBTYPE_LABELS, AccountSubtype,
} from "@/lib/api/accounting";
import { AlertTriangle, Check, Download, FileUp, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

// -----------------------------------------------------------------------
// Real, minimal, dependency-free CSV parser -- handles quoted fields
// (embedded commas, escaped "" quotes), \r\n or \n line endings, and
// skips fully-blank lines. Deliberately not a general-purpose CSV
// library -- this only ever needs to read this app's own fixed
// six-column template, not arbitrary spreadsheet exports.
// -----------------------------------------------------------------------
function parseCsvText(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  while (i < text.length) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQuotes = false; i++; continue;
      }
      field += char; i++; continue;
    }
    if (char === '"') { inQuotes = true; i++; continue; }
    if (char === ",") { row.push(field); field = ""; i++; continue; }
    if (char === "\r") { i++; continue; }
    if (char === "\n") { row.push(field); rows.push(row); row = []; field = ""; i++; continue; }
    field += char; i++;
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

// Recognized cells normalize into a real boolean; anything else
// passes through UNCHANGED as the raw string -- deliberately not
// guessed at here. The backend's own strict is-boolean check
// (account_import._validate_import_rows()) reports an unrecognized
// value as a real, visible row error instead.
function normalizeBoolCell(raw: string): boolean | string {
  const v = raw.trim().toLowerCase();
  if (v === "") return false;
  if (["true", "1", "ya", "yes"].includes(v)) return true;
  if (["false", "0", "tidak", "no"].includes(v)) return false;
  return raw.trim();
}

function csvToImportRows(text: string): { rows: AccountImportRow[]; error: string | null } {
  const table = parseCsvText(text);
  if (table.length < 1) {
    return { rows: [], error: "File kosong atau tidak bisa dibaca." };
  }

  const header = table[0].map((h) => h.trim().toLowerCase());
  const required = ["code", "name", "account_subtype"];
  const missing = required.filter((c) => !header.includes(c));
  if (missing.length > 0) {
    return {
      rows: [],
      error: `Kolom wajib tidak ditemukan: ${missing.join(", ")}. Gunakan template yang disediakan.`,
    };
  }
  if (table.length < 2) {
    return { rows: [], error: "File tidak memiliki baris data — hanya baris judul kolom." };
  }

  const idx = (name: string) => header.indexOf(name);
  const rows: AccountImportRow[] = table.slice(1).map((cells) => {
    const get = (name: string) => (idx(name) >= 0 ? (cells[idx(name)] ?? "").trim() : "");
    return {
      code: get("code"),
      name: get("name"),
      account_subtype: get("account_subtype").toUpperCase(),
      is_contra: normalizeBoolCell(get("is_contra")),
      parent_code: get("parent_code") || undefined,
      description: get("description") || undefined,
    };
  });
  return { rows, error: null };
}

export default function AccountImportPage() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [parsedRows, setParsedRows] = useState<AccountImportRow[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);

  const [preview, setPreview] = useState<AccountImportPreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const [committing, setCommitting] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);
  const [committedCount, setCommittedCount] = useState<number | null>(null);

  function resetAfterNewFile() {
    setPreview(null);
    setCommitError(null);
    setCommittedCount(null);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    resetAfterNewFile();

    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      const { rows, error } = csvToImportRows(text);
      setParsedRows(rows);
      setParseError(error);
    };
    reader.onerror = () => {
      setParsedRows([]);
      setParseError("Gagal membaca file.");
    };
    reader.readAsText(file);
  }

  async function handlePreview() {
    setPreviewing(true);
    setCommitError(null);
    setCommittedCount(null);
    const result = await accountImportApi.preview(parsedRows);
    setPreview(result);
    setPreviewing(false);
  }

  async function handleCommit() {
    setCommitting(true);
    setCommitError(null);
    const result = await accountImportApi.commit(parsedRows);
    setCommitting(false);
    if (!result.success) {
      setCommitError(result.message ?? "Gagal mengimpor akun.");
      return;
    }
    setCommittedCount(result.created_count ?? 0);
    setPreview(null);
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 34 }}>Impor Akun</h1>
          <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            Tambahkan banyak akun sekaligus dari file CSV — tinjau hasilnya sebelum
            benar-benar disimpan.
          </div>
        </div>
        <a
          href="/templates/account-import-template.csv" download
          className="btn-ghost" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Download size={16} /> Unduh Template
        </a>
      </div>

      <AccountingSubNav />

      {committedCount !== null ? (
        <div className="card" style={{ padding: 40, textAlign: "center" }}>
          <Check size={28} style={{ color: "var(--workshop)", marginBottom: 12 }} />
          <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
            {committedCount} Akun Berhasil Diimpor
          </div>
          <div style={{ color: "var(--steel)", fontSize: 14, marginBottom: 20 }}>
            Semua akun baru sudah tersimpan dan siap digunakan.
          </div>
          <Link href="/dashboard/accounting/accounts" className="btn-rust">
            Lihat Daftar Akun
          </Link>
        </div>
      ) : (
        <>
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="label" style={{ marginBottom: 12 }}>1. Pilih File CSV</div>
            <input
              type="file" accept=".csv,text/csv" onChange={handleFileChange}
              style={{ marginBottom: 8 }}
            />
            {fileName && (
              <div style={{ fontSize: 13, color: "var(--steel)", display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
                <FileUp size={14} /> {fileName}
                {!parseError && parsedRows.length > 0 && (
                  <span>— {parsedRows.length} baris terbaca</span>
                )}
              </div>
            )}
            {parseError && (
              <div style={{ fontSize: 13, color: "var(--danger)", marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <AlertTriangle size={14} /> {parseError}
              </div>
            )}
          </div>

          {parsedRows.length > 0 && !parseError && (
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="label" style={{ marginBottom: 12 }}>2. Tinjau Data</div>
              <button onClick={handlePreview} disabled={previewing} className="btn-rust">
                {previewing ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Tinjau Data"}
              </button>
            </div>
          )}

          {preview && !preview.success && (
            <div className="card" style={{ marginBottom: 20, borderColor: "var(--danger)", color: "var(--danger)", fontSize: 14 }}>
              {preview.message}
            </div>
          )}

          {preview && preview.success && (
            <>
              <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
                <div className="card" style={{ flex: 1 }}>
                  <div className="label">Total Baris</div>
                  <div className="mono" style={{ fontSize: 22 }}>{preview.total_rows}</div>
                </div>
                <div className="card" style={{ flex: 1 }}>
                  <div className="label">Valid</div>
                  <div className="mono" style={{ fontSize: 22, color: "var(--workshop)" }}>{preview.valid_count}</div>
                </div>
                <div className="card" style={{ flex: 1 }}>
                  <div className="label">Error</div>
                  <div className="mono" style={{ fontSize: 22, color: (preview.error_count ?? 0) > 0 ? "var(--danger)" : undefined }}>
                    {preview.error_count}
                  </div>
                </div>
              </div>

              {(preview.errors?.length ?? 0) > 0 && (
                <div className="card" style={{ marginBottom: 20 }}>
                  <div className="label" style={{ marginBottom: 12 }}>Baris Bermasalah</div>
                  <table className="data-table">
                    <thead>
                      <tr><th>Baris</th><th>Kode</th><th>Masalah</th></tr>
                    </thead>
                    <tbody>
                      {preview.errors!.map((e) => (
                        <tr key={e.row}>
                          <td className="mono">{e.row}</td>
                          <td className="mono">{e.code || "—"}</td>
                          <td style={{ color: "var(--danger)" }}>{e.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {(preview.valid_rows?.length ?? 0) > 0 && (
                <div className="card" style={{ marginBottom: 20 }}>
                  <div className="label" style={{ marginBottom: 12 }}>Baris Valid — Siap Diimpor</div>
                  <table className="data-table">
                    <thead>
                      <tr><th>Kode</th><th>Nama</th><th>Sub-Tipe</th><th>Induk</th></tr>
                    </thead>
                    <tbody>
                      {preview.valid_rows!.map((r) => (
                        <tr key={r.row}>
                          <td className="mono">{r.code}</td>
                          <td>{r.name}</td>
                          <td>{ACCOUNT_SUBTYPE_LABELS[r.account_subtype as AccountSubtype] ?? r.account_subtype}</td>
                          <td className="mono">{r.parent_code || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {commitError && (
                <div className="card" style={{ marginBottom: 20, borderColor: "var(--danger)", color: "var(--danger)", fontSize: 14 }}>
                  {commitError}
                </div>
              )}

              {preview.can_commit ? (
                <button onClick={handleCommit} disabled={committing} className="btn-rust">
                  {committing ? (
                    <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />
                  ) : (
                    `Impor ${preview.valid_count} Akun`
                  )}
                </button>
              ) : (
                <div style={{ fontSize: 13, color: "var(--steel)" }}>
                  Perbaiki baris bermasalah di file Anda, lalu unggah dan tinjau ulang
                  sebelum bisa mengimpor.
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
