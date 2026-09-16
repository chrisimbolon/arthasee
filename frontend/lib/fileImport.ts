// =============================================================================
// === frontend/lib/fileImport.ts ===
// =============================================================================
// 16 Sep 2026 — real, shared spreadsheet-import parsing utility.
//
// Real, deliberate scope: this only ever turns a real uploaded file
// (CSV or Excel) into a plain array of loosely-typed row objects,
// keyed by the file's own real header row (lowercased, trimmed) —
// it does NOT know anything about what a "valid row" means for any
// particular feature. That's each feature's own real column-mapping
// and validation, layered on top — see reconciliation/page.tsx's own
// rowsFromParsedObjects() for the first real consumer.
//
// Real, deliberate reason this lives as its own shared file rather
// than inline in one page: Chris's own confirmed plan — reused
// as-is for Task 18.8's own Account Import wizard as a quick
// follow-up, once this is proven working end-to-end for Bank
// Statement Import first. Both features share the exact same real
// need (a person uploads a spreadsheet, gets back structured rows),
// so the parsing logic belongs in one place, not duplicated per page.
//
// Excel parsing uses SheetJS (the `xlsx` package) — installed from
// SheetJS's own CDN tarball (https://cdn.sheetjs.com/xlsx-0.20.3/
// xlsx-0.20.3.tgz), NOT the plain `xlsx` name on the public npm
// registry. The npm-registry release is permanently stuck at 0.18.5
// with multiple real, unpatched high-severity advisories (prototype
// pollution, ReDoS) — SheetJS stopped publishing patched builds to
// npm itself in 2023 and now only publishes current, patched
// versions through their own CDN. This is a real, non-hypothetical
// concern specifically for this file: its whole job is parsing a
// file a real user uploads, which is exactly the "reading a
// specially crafted file" threat model those advisories describe.
import * as XLSX from "xlsx";

// Real, dependency-free CSV parser — handles quoted fields (embedded
// commas, escaped "" quotes), \r\n or \n line endings. Same real
// implementation already proven for Account import (Phase 18, Task
// 18.8), moved here so it's shared rather than duplicated per page.
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

// A real Excel date CELL (genuinely formatted as a date in the
// spreadsheet) comes back from SheetJS as a real JS Date object when
// the workbook is read with cellDates:true (below) — converted here
// to a plain ISO YYYY-MM-DD string, matching what every backend
// DateField in this app expects. A cell that's really just TEXT (a
// shop's own "10/09/2026"-style string typed into a plain cell, not
// a genuinely formatted Excel date) comes back as a plain string
// already, untouched — the real, per-feature validator downstream is
// what catches a genuinely malformed date string, not this utility.
function cellToString(value: unknown): string {
  if (value instanceof Date) {
    const yyyy = value.getFullYear();
    const mm = String(value.getMonth() + 1).padStart(2, "0");
    const dd = String(value.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  }
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

// Normalizes a raw CSV table (header row + data rows) into the same
// real shape SheetJS's own sheet_to_json() naturally gives us for
// Excel — an array of objects keyed by the file's own real header
// text, lowercased and trimmed, so a feature's own column-matching
// logic never has to care which real format the file actually was.
function tableToObjects(table: string[][]): Record<string, string>[] {
  if (table.length < 2) return [];
  const header = table[0].map((h) => h.trim().toLowerCase());
  return table.slice(1).map((cells) => {
    const obj: Record<string, string> = {};
    header.forEach((key, i) => { obj[key] = (cells[i] ?? "").trim(); });
    return obj;
  });
}

export interface ParsedSpreadsheet {
  rows: Record<string, string>[];
  error: string | null;
}

// The one real entry point this whole file exists for — reads a
// real uploaded File (CSV or Excel, detected by extension) and
// returns a normalized array of row objects, or a real, honest
// parse-level error (a genuinely corrupt/unreadable file, or a file
// with no real header row at all) — never both.
export async function parseSpreadsheetFile(file: File): Promise<ParsedSpreadsheet> {
  const isExcel = /\.xlsx?$/i.test(file.name);

  if (isExcel) {
    try {
      const buffer = await file.arrayBuffer();
      // cellDates:true — real Excel date cells come back as genuine
      // JS Date objects (see cellToString above), not raw serial
      // numbers a naive reader would otherwise hand back unparsed.
      const workbook = XLSX.read(buffer, { type: "array", cellDates: true });
      const firstSheetName = workbook.SheetNames[0];
      if (!firstSheetName) {
        return { rows: [], error: "File Excel tidak memiliki sheet sama sekali." };
      }
      const sheet = workbook.Sheets[firstSheetName];
      // header:1 -> array-of-arrays first, so this goes through the
      // exact same header-normalization tableToObjects() already
      // provides for CSV — one real, shared normalization path for
      // both formats, not two independent ones that could drift
      // apart on how they lowercase/trim headers.
      const rawTable = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: "" });
      const stringTable = rawTable.map((row) => row.map((cell) => cellToString(cell)));
      const rows = tableToObjects(stringTable);
      if (rows.length === 0) {
        return { rows: [], error: "File Excel tidak memiliki baris data — hanya baris judul kolom, atau sheet kosong." };
      }
      return { rows, error: null };
    } catch {
      return { rows: [], error: "Gagal membaca file Excel — pastikan file tidak rusak dan berformat .xlsx atau .xls yang valid." };
    }
  }

  try {
    const text = await file.text();
    const table = parseCsvText(text);
    const rows = tableToObjects(table);
    if (rows.length === 0) {
      return { rows: [], error: "File CSV tidak memiliki baris data — hanya baris judul kolom, atau file kosong." };
    }
    return { rows, error: null };
  } catch {
    return { rows: [], error: "Gagal membaca file." };
  }
}

// The real, shared file-input accept attribute — every import
// wizard using this utility should use this exact same value, so a
// future format added here doesn't require updating N separate
// pages' own hardcoded accept strings.
export const SPREADSHEET_IMPORT_ACCEPT =
  ".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel";
