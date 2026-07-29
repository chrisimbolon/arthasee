"use client";
// =============================================================================
// === frontend/app/dashboard/contract-detail/page.tsx ===
// Same query-param + Suspense pattern as every other detail page in
// this app — static export needs every route's HTML identical
// regardless of ?id= value.
//
// This is the entry point into the whole contracts feature: shows a
// Contract's current live state (its vehicles and their pre-
// authorized line items, per ContractVehicleSerializer's own
// ACTIVE-only filtering), the upload dropzone for a new/revised
// HPS/RAB Excel file, and the full import history. Uploading never
// changes anything on this page directly — a successful parse
// always redirects to contract-import-review, where a human
// actually confirms what changes before anything becomes live.
// =============================================================================
import {
  Contract, ContractImport, TerminPeriod,
  contractImportsApi, contractsApi, terminPeriodsApi,
} from "@/lib/api/contracts";
import { formatDateID } from "@/lib/format";
import {
  AlertTriangle, ArrowLeft, Car, Download, History, Loader2, UploadCloud, Wallet, X,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

function formatDateTimeID(iso: string) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
}

const CONTRACT_STATUS_LABEL: Record<string, string> = {
  ACTIVE: "Aktif", EXPIRED: "Berakhir", CANCELLED: "Dibatalkan",
};
const CONTRACT_STATUS_COLOR: Record<string, string> = {
  ACTIVE: "#2e7d4f", EXPIRED: "var(--steel)", CANCELLED: "var(--danger)",
};
const IMPORT_STATUS_LABEL: Record<string, string> = {
  PENDING_REVIEW: "Menunggu Peninjauan", APPLIED: "Diterapkan", REJECTED: "Ditolak",
};
const IMPORT_STATUS_COLOR: Record<string, string> = {
  PENDING_REVIEW: "var(--rust)", APPLIED: "#2e7d4f", REJECTED: "var(--danger)",
};

// original_file stores the full storage path
// ("contract_imports/2026/07/rencana_anggaran.xlsx") — only the
// filename itself is useful to show on this screen.
function fileNameFromPath(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function TerminStatusBadge({ period }: { period: TerminPeriod }) {
  if (period.is_realized) {
    return (
      <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: "#2e7d4f" }}>
        Direalisasi
      </span>
    );
  }
  if (period.is_overdue) {
    return (
      <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: "var(--danger)" }}>
        Jatuh Tempo
      </span>
    );
  }
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "var(--ink-soft)", background: "var(--paper-3)", border: "1px solid var(--line)" }}>
      Belum Jatuh Tempo
    </span>
  );
}

function RecordRealizationModal({ period, onClose, onRecorded }: {
  period: TerminPeriod; onClose: () => void; onRecorded: (p: TerminPeriod) => void;
}) {
  // Pre-filled with amount_expected, not left blank — the real,
  // current planning figure is almost always the right starting
  // point; Made only needs to change it when the actual disbursement
  // genuinely differs, which is the exact scenario amount_received
  // being its own real field (not just a boolean) exists for.
  const [amount, setAmount] = useState(period.amount_expected);
  const [receivedDate, setReceivedDate] = useState(new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      const updated = await terminPeriodsApi.realize(period.id, amount, receivedDate);
      onRecorded(updated);
      onClose();
    } catch {
      setError("Gagal mencatat realisasi.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 380, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Catat Realisasi Termin {period.sequence}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nilai Realisasi (Rp)</label>
            <input className="input" type="number" step="0.01" min="0" required value={amount} onChange={(e) => setAmount(e.target.value)} />
            <p style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>Perkiraan: {money(period.amount_expected)}</p>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Tanggal Diterima</label>
            <input className="input" type="date" required value={receivedDate} onChange={(e) => setReceivedDate(e.target.value)} />
          </div>
          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

function ContractDetailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const contractId = searchParams.get("id") ?? "";
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [contract, setContract] = useState<Contract | null>(null);
  const [imports, setImports] = useState<ContractImport[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [terminError, setTerminError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [realizingPeriod, setRealizingPeriod] = useState<TerminPeriod | null>(null);
  const [generatingTermin, setGeneratingTermin] = useState(false);
  const [exportingTermin, setExportingTermin] = useState(false);

  const load = () => {
    Promise.all([contractsApi.get(contractId), contractImportsApi.list(contractId)])
      .then(([c, i]) => { setContract(c); setImports(i); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { if (contractId) load(); }, [contractId]);

  const handleFile = async (file: File) => {
    setUploading(true); setUploadError(null);
    const result = await contractImportsApi.upload(contractId, file);
    setUploading(false);
    if (result.contractImport) {
      // Whether the parse succeeded or failed, contract-import-review
      // is where the outcome gets shown — including a parse_error
      // state it already handles. Nothing here duplicates that.
      router.push(`/dashboard/contract-import-review?id=${result.contractImport.id}`);
    } else {
      setUploadError(result.message ?? "Gagal mengunggah file.");
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  // Retroactive backfill — see contractsApi.generateTermin's own
  // comment for why this exists at all: any Contract created before
  // the termin feature shipped (like this one, in real testing) has
  // zero periods and no other way to get them.
  const handleGenerateTermin = async () => {
    setGeneratingTermin(true); setTerminError(null);
    try {
      await contractsApi.generateTermin(contractId);
      load();
    } catch {
      setTerminError("Gagal membuat data termin.");
    } finally {
      setGeneratingTermin(false);
    }
  };

  // Deliberately not a plain <a href="..."> — this API authenticates
  // with a bearer token in a header (see lib/api.ts's own request
  // interceptor), which a normal browser link click has no way to
  // attach at all. Fetching through the same axios instance (which
  // already carries that token) as a real Blob, then triggering the
  // download manually, is the correct pattern here — a plain link
  // would silently 401 instead of downloading anything.
  const handleExportTermin = async () => {
    setExportingTermin(true); setTerminError(null);
    try {
      const blob = await contractsApi.exportTermin(contractId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Termin_${contract?.title ?? "Contract"}_${contract?.fiscal_year ?? ""}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setTerminError("Gagal mengunduh laporan termin.");
    } finally {
      setExportingTermin(false);
    }
  };

  if (!contractId) {
    return <div style={{ color: "var(--danger)" }}>Contract tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !contract) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  const vehicles = contract.contract_vehicles ?? [];
  const terminPeriods = contract.termin_periods ?? [];
  const totalAllocated = vehicles.reduce((sum, v) => sum + Number(v.allocated_budget), 0);
  const lastImport = imports[0];

  return (
    <div>
      <Link href="/dashboard/contracts" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Kontrak
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 12, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
            {contract.customer_name} · {contract.fiscal_year}
          </div>
          <h1 style={{ fontSize: 24, fontWeight: 700 }}>{contract.title}</h1>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 12px", borderRadius: 20, color: "#fff", background: CONTRACT_STATUS_COLOR[contract.status] }}>
            {CONTRACT_STATUS_LABEL[contract.status]}
          </span>
          <span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 12px", borderRadius: 20, color: "var(--ink-soft)", background: "var(--paper-3)", border: "1px solid var(--line)" }}>
            termin {contract.termin_count}x
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Kendaraan</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicles.length}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Total Anggaran</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{money(totalAllocated)}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Import Terakhir</div>
          <div className="mono" style={{ fontSize: 16, fontWeight: 600 }}>{lastImport ? formatDateTimeID(lastImport.uploaded_at) : "Belum pernah"}</div>
        </div>
      </div>

      {uploading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite", color: "var(--steel)" }} />
          <span style={{ fontSize: 14 }}>Membaca file Excel…</span>
        </div>
      ) : (
        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          style={{
            border: `1.5px dashed ${dragOver ? "var(--rust)" : "var(--steel-lt)"}`,
            borderRadius: 8, padding: "32px 24px", textAlign: "center", cursor: "pointer",
            background: dragOver ? "var(--paper-3)" : "transparent", marginBottom: 24,
            transition: "border-color 0.15s ease, background 0.15s ease",
          }}
        >
          <UploadCloud size={26} style={{ color: "var(--steel)", marginBottom: 8 }} />
          <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            Seret file Excel ke sini, atau <span style={{ color: "var(--rust)" }}>pilih file</span>
          </p>
          <p style={{ fontSize: 12.5, color: "var(--steel)" }}>Format HPS/RAB standar · .xlsx</p>
          <input ref={fileInputRef} type="file" accept=".xlsx" onChange={handleFileInputChange} style={{ display: "none" }} />
        </div>
      )}

      {uploadError && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 20, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={14} /> {uploadError}
        </div>
      )}

      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14, marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
        <Car size={16} /> Kendaraan dalam Kontrak
      </h2>
      {vehicles.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 24, fontSize: 13.5, marginBottom: 28 }}>
          Belum ada kendaraan — unggah file Excel untuk memulai.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12, marginBottom: 28 }}>
          {vehicles.map((v) => (
            <Link key={v.id} href={`/dashboard/vehicle-detail?id=${v.vehicle}`} className="card" style={{ display: "block" }}>
              <div className="mono" style={{ fontSize: 14, fontWeight: 600 }}>{v.plate_number}</div>
              <div style={{ fontSize: 12.5, color: "var(--steel)", margin: "3px 0 10px" }}>{v.vehicle_model}</div>
              <div className="mono" style={{ fontSize: 13 }}>{money(v.allocated_budget)}</div>
              <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{v.line_items.length} item</div>
            </Link>
          ))}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Wallet size={16} /> Termin Pembayaran
        </h2>
        {terminPeriods.length > 0 && (
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} onClick={handleExportTermin} disabled={exportingTermin}>
            {exportingTermin ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={13} />}
            Export Laporan Termin
          </button>
        )}
      </div>
      {terminError && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={14} /> {terminError}
        </div>
      )}
      {terminPeriods.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 24, fontSize: 13.5, marginBottom: 28 }}>
          <p style={{ marginBottom: 12 }}>Belum ada data termin untuk contract ini.</p>
          {/* Only ever needed for a Contract that predates this
              feature — every Contract created from now on already
              gets its periods automatically at creation. */}
          <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 14px" }} onClick={handleGenerateTermin} disabled={generatingTermin}>
            {generatingTermin ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Buat Data Termin"}
          </button>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 28 }}>
          <table className="data-table">
            <thead>
              <tr><th>Termin</th><th>Jatuh Tempo</th><th>Perkiraan</th><th>Realisasi</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {terminPeriods.map((p) => (
                <tr key={p.id}>
                  <td className="mono">#{p.sequence}</td>
                  <td className="mono">{formatDateID(p.jatuh_tempo)}</td>
                  <td className="mono">{money(p.amount_expected)}</td>
                  <td className="mono">{p.amount_received != null ? money(p.amount_received) : "—"}</td>
                  <td><TerminStatusBadge period={p} /></td>
                  <td>
                    {!p.is_realized && (
                      <button className="btn-ghost" style={{ fontSize: 12, padding: "5px 10px" }} onClick={() => setRealizingPeriod(p)}>
                        Catat Realisasi
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
        <History size={16} /> Riwayat Import
      </h2>
      {imports.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 24, fontSize: 13.5 }}>
          Belum ada riwayat import untuk contract ini.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {imports.map((imp) => (
            <Link
              key={imp.id} href={`/dashboard/contract-import-review?id=${imp.id}`}
              className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px" }}
            >
              <div>
                <div style={{ fontSize: 13.5 }}>{fileNameFromPath(imp.original_file)}</div>
                <div style={{ fontSize: 12, color: "var(--steel)" }}>
                  {formatDateTimeID(imp.uploaded_at)} · {imp.uploaded_by_name ?? "—"}
                </div>
              </div>
              <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: IMPORT_STATUS_COLOR[imp.status] }}>
                {IMPORT_STATUS_LABEL[imp.status]}
              </span>
            </Link>
          ))}
        </div>
      )}

      {realizingPeriod && (
        <RecordRealizationModal
          period={realizingPeriod}
          onClose={() => setRealizingPeriod(null)}
          // Reload rather than patch state in place — guarantees this
          // stays consistent with the backend, and a realized period
          // can also shift every OTHER unrealized period's own
          // amount_expected... actually it can't (realizing doesn't
          // trigger recalculation, only a new ContractImport apply()
          // does) — but reload is still the simpler, equally correct
          // choice here regardless, matching this page's own existing
          // pattern of calling load() after every mutating action.
          onRecorded={() => load()}
        />
      )}
    </div>
  );
}

export default function ContractDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <ContractDetailContent />
    </Suspense>
  );
}
