"use client";
// =============================================================================
// === frontend/app/dashboard/contract-import-review/page.tsx ===
// Same query-param + Suspense pattern as every other detail page in
// this app (vehicle-detail, work-order-detail, etc.) — static export
// needs every route's HTML identical regardless of ?id= value.
//
// This page is the human half of the promotion pattern used here for
// the 4th time: an uploaded Excel file NEVER becomes live data on its
// own. It only ever produces a diff sitting in PENDING_REVIEW, and
// this screen is where a person actually looks at what would change
// before an explicit "Terapkan Perubahan" confirms it.
//
// One thing this screen must do that no other review screen in this
// app needs to: fill in gaps the source document itself can't
// provide. Vehicle.manufacture_year is required on the backend, but
// it appears nowhere in the real HPS document reviewed for this
// project — so a brand-new vehicle in "added_vehicles" can't be applied until a human types that in here.
// =============================================================================
import {
  ContractImport, DiffAddedVehicle, ParsedDiff, contractImportsApi,
} from "@/lib/api/contracts";
import { AlertTriangle, ArrowLeft, Loader2, PlusCircle, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

function AddedVehicleCard({
  vehicle, onFieldChange,
}: {
  vehicle: DiffAddedVehicle;
  onFieldChange: (fleetCode: string, field: "manufacture_year" | "vehicle_type", value: string) => void;
}) {
  const total = vehicle.line_items.reduce((sum, li) => sum + Number(li.subtotal), 0);
  const isReuse = Boolean(vehicle.existing_vehicle_id);
  return (
    <div className="card" style={{ borderLeft: `4px solid ${isReuse ? "var(--rust)" : "var(--workshop)"}`, marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: isReuse ? "var(--rust)" : "var(--workshop)" }}>
            {isReuse ? "Kendaraan Sudah Ada" : "Kendaraan Baru"}
          </span>
          <div className="mono" style={{ fontSize: 16, fontWeight: 700, marginTop: 4 }}>{vehicle.fleet_code || "(kode armada tidak terbaca)"}</div>
          <div style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>{isReuse ? vehicle.existing_vehicle_model : vehicle.vehicle_model}</div>
        </div>
        <div className="mono" style={{ fontSize: 14, fontWeight: 600 }}>{money(vehicle.allocated_budget)}</div>
      </div>

      {!vehicle.fleet_code && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "8px 10px", borderRadius: 5, fontSize: 12.5, marginBottom: 10 }}>
          <AlertTriangle size={13} style={{ marginRight: 5 }} />
          Kode armada tidak terbaca dari dokumen — isi nomor plat secara manual sebelum bisa diterapkan.
        </div>
      )}

      {isReuse ? (
        // Same real fleet vehicle already exists in the org — most
        // plausibly from a prior fiscal year's contract. Nothing to
        // fill in: it's being linked to this contract, not created
        // again, so its existing manufacture_year/vehicle_type stay
        // exactly as they already are.
        <div style={{ background: "var(--paper)", border: "1px solid var(--line)", padding: "9px 12px", borderRadius: 5, fontSize: 12.5, color: "var(--ink-soft)", marginBottom: 12 }}>
          Kendaraan ini sudah terdaftar di sistem ({vehicle.existing_vehicle_model}) — akan dihubungkan ke contract ini,
          bukan dibuat sebagai kendaraan baru.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <div>
            <label className="label">Tahun Pembuatan <span style={{ color: "var(--danger)" }}>*</span></label>
            <input
              className="input" type="number" placeholder="cth. 2020"
              value={vehicle.manufacture_year ?? ""}
              onChange={(e) => onFieldChange(vehicle.fleet_code, "manufacture_year", e.target.value)}
            />
            <p style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>
              Tidak tercantum di dokumen sumber — wajib diisi manual.
            </p>
          </div>
          <div>
            <label className="label">Jenis Kendaraan</label>
            <select
              className="input"
              value={vehicle.vehicle_type ?? "Mobil"}
              onChange={(e) => onFieldChange(vehicle.fleet_code, "vehicle_type", e.target.value)}
            >
              <option>Mobil</option>
              <option>Motor</option>
            </select>
          </div>
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        {vehicle.line_items.map((li) => (
          <div key={li.row_no} className="mono" style={{ fontSize: 12.5, display: "flex", justifyContent: "space-between", padding: "3px 0" }}>
            <span>{li.row_no}. {li.description} × {li.volume} {li.unit}</span>
            <span>{money(li.subtotal)}</span>
          </div>
        ))}
        {Math.abs(total - Number(vehicle.allocated_budget)) > 1 && (
          <div style={{ fontSize: 11.5, color: "var(--danger)", marginTop: 6 }}>
            <AlertTriangle size={11} style={{ marginRight: 4 }} />
            Jumlah item ({money(total)}) tidak sama dengan anggaran tertulis ({money(vehicle.allocated_budget)}) — periksa dokumen sumber.
          </div>
        )}
      </div>
    </div>
  );
}

function ContractImportReviewContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const importId = searchParams.get("id") ?? "";

  const [contractImport, setContractImport] = useState<ContractImport | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Local edits layered on top of the raw parsed diff — the human
  // corrections (manufacture_year, vehicle_type) that never existed
  // in the source document. Kept separate from contractImport.parsed_diff
  // itself so the original machine parse stays untouched as a record
  // of what the file actually said.
  const [addedVehicleEdits, setAddedVehicleEdits] = useState<Record<string, { manufacture_year?: number; vehicle_type?: string }>>({});

  const load = () => contractImportsApi.get(importId).then(setContractImport).finally(() => setLoading(false));
  useEffect(() => { if (importId) load(); }, [importId]);

  const diff = contractImport?.parsed_diff;

  const mergedAddedVehicles: DiffAddedVehicle[] = useMemo(() => {
    // Deliberately diff?.added_vehicles, not just !diff — parsed_diff
    // defaults to {} (an empty but truthy object) whenever a parse
    // fails, since the backend only ever populates it on success.
    // Checking plain truthiness let {} slip through, then crashed on
    // .map() of an undefined key — one render before this component
    // would have reached its own parse_error early-return further
    // down (hooks always run before any conditional return, so this
    // guard has to hold on its own, it can't rely on that later check
    // happening first).
    if (!diff?.added_vehicles) return [];
    return diff.added_vehicles.map((v) => ({
      ...v,
      manufacture_year: addedVehicleEdits[v.fleet_code]?.manufacture_year ?? v.manufacture_year,
      vehicle_type: addedVehicleEdits[v.fleet_code]?.vehicle_type ?? v.vehicle_type ?? "Mobil",
    }));
  }, [diff, addedVehicleEdits]);

  const handleFieldChange = (fleetCode: string, field: "manufacture_year" | "vehicle_type", value: string) => {
    setAddedVehicleEdits((prev) => ({
      ...prev,
      [fleetCode]: {
        ...prev[fleetCode],
        [field]: field === "manufacture_year" ? Number(value) : value,
      },
    }));
  };

  // Every added vehicle needs a real fleet_code AND a manufacture_year
  // before this import can be applied — the two things the source
  // document can never supply on its own.
  // A reuse-case vehicle (existing_vehicle_id set) only needs a real
  // fleet_code — it never needs manufacture_year, since it's linking
  // to an already-real Vehicle, not creating one.
  const readyToApply = mergedAddedVehicles.every((v) =>
    v.fleet_code && (v.existing_vehicle_id || v.manufacture_year)
  );

  const handleApply = async () => {
    if (!diff || !readyToApply) return;
    setApplying(true); setError(null);
    const confirmedDiff: ParsedDiff = { ...diff, added_vehicles: mergedAddedVehicles };
    const result = await contractImportsApi.apply(importId, confirmedDiff);
    if (result.success && result.contractImport) {
      setContractImport(result.contractImport);
      router.push(`/dashboard/contract-detail?id=${result.contractImport.contract}`);
    } else {
      setError(result.message ?? "Gagal menerapkan perubahan.");
    }
    setApplying(false);
  };

  const handleReject = async () => {
    setRejecting(true);
    try {
      const updated = await contractImportsApi.reject(importId);
      setContractImport(updated);
    } finally {
      setRejecting(false);
    }
  };

  if (!importId) {
    return <div style={{ color: "var(--danger)" }}>Import tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !contractImport) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  if (contractImport.parse_error) {
    return (
      <div>
        <Link href={`/dashboard/contract-detail?id=${contractImport.contract}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
          <ArrowLeft size={14} /> Kembali ke Contract
        </Link>
        <div className="card" style={{ borderLeft: "4px solid var(--danger)" }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={17} color="var(--danger)" /> Gagal Membaca File
          </h2>
          <p style={{ fontSize: 14, marginBottom: 8 }}>File Excel tidak sesuai format template yang diharapkan.</p>
          <pre className="mono" style={{ fontSize: 12.5, background: "var(--paper)", padding: 12, borderRadius: 5, whiteSpace: "pre-wrap" }}>{contractImport.parse_error}</pre>
        </div>
      </div>
    );
  }

  if (contractImport.status !== "PENDING_REVIEW") {
    return (
      <div>
        <Link href={`/dashboard/contract-detail?id=${contractImport.contract}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
          <ArrowLeft size={14} /> Kembali ke Contract
        </Link>
        <div className="card" style={{ textAlign: "center", padding: 32 }}>
          <p style={{ fontSize: 14.5 }}>
            Import ini sudah {contractImport.status === "APPLIED" ? "diterapkan" : "ditolak"} sebelumnya — tidak ada lagi yang perlu ditinjau.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Link href={`/dashboard/contract-detail?id=${contractImport.contract}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Contract
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>Tinjau Perubahan Import</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 20 }}>
        Tidak ada yang berubah sampai Anda menekan &quot;Terapkan Perubahan&quot; di bawah.
      </p>

      {contractImport.totals_match === false && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 6, fontSize: 13.5, marginBottom: 20, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={15} />
          Total hasil baca sistem ({money(contractImport.computed_total ?? 0)}) tidak sama dengan
          &quot;TOTAL KESELURUHAN&quot; yang tertulis di dokumen ({money(contractImport.document_total ?? 0)}).
          Periksa kembali sebelum menerapkan — kemungkinan ada baris yang salah terbaca.
        </div>
      )}

      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>}

      {mergedAddedVehicles.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <PlusCircle size={15} color="var(--workshop)" /> Kendaraan Baru ({mergedAddedVehicles.length})
          </h2>
          {mergedAddedVehicles.map((v) => (
            <AddedVehicleCard key={v.fleet_code || v.vehicle_model} vehicle={v} onFieldChange={handleFieldChange} />
          ))}
        </div>
      )}

      {diff!.added_items.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Item Baru pada Kendaraan Lama ({diff!.added_items.length})</h2>
          <div className="card">
            {diff!.added_items.map((item) => (
              <div key={`${item.fleet_code}-${item.row_no}`} className="mono" style={{ fontSize: 13, display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                <span>{item.fleet_code} · {item.row_no}. {item.description}</span>
                <span>{money(item.subtotal)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {diff!.changed_items.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Item Berubah ({diff!.changed_items.length})</h2>
          <div className="card">
            {diff!.changed_items.map((item) => (
              <div key={`${item.fleet_code}-${item.row_no}`} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="mono" style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 4 }}>{item.fleet_code} · Baris {item.row_no}</div>
                <div style={{ display: "flex", gap: 16, fontSize: 13 }}>
                  <div style={{ flex: 1, textDecoration: "line-through", color: "var(--steel)" }}>
                    {item.old.description} — {item.old.volume} {item.old.unit} @ {money(item.old.unit_price)} = {money(item.old.subtotal)}
                  </div>
                  <div style={{ flex: 1, color: "var(--workshop)", fontWeight: 600 }}>
                    {item.new.description} — {item.new.volume} {item.new.unit} @ {money(item.new.unit_price)} = {money(item.new.subtotal)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {diff!.removed_items.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <X size={15} color="var(--danger)" /> Item Dihapus dari Dokumen ({diff!.removed_items.length})
          </h2>
          <div className="card">
            {diff!.removed_items.map((item) => (
              <div key={`${item.fleet_code}-${item.row_no}`} className="mono" style={{ fontSize: 13, color: "var(--danger)", padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                {item.fleet_code} · {item.row_no}. {item.description}
              </div>
            ))}
            <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 8 }}>
              Tidak akan dihapus permanen — hanya ditandai tidak aktif, sehingga Work Order lama yang pernah memakai item ini tetap utuh.
            </p>
          </div>
        </div>
      )}

      {diff!.unchanged_count > 0 && (
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 24 }}>
          {diff!.unchanged_count} item lainnya tidak berubah.
        </p>
      )}

      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn-rust" onClick={handleApply} disabled={applying || rejecting || !readyToApply}>
          {applying ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Terapkan Perubahan"}
        </button>
        <button className="btn-ghost" onClick={handleReject} disabled={applying || rejecting}>
          {rejecting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Tolak Import Ini"}
        </button>
      </div>
      {!readyToApply && mergedAddedVehicles.length > 0 && (
        <p style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 10 }}>
          Lengkapi kode armada dan tahun pembuatan untuk setiap kendaraan baru sebelum bisa diterapkan.
        </p>
      )}
    </div>
  );
}

export default function ContractImportReviewPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <ContractImportReviewContent />
    </Suspense>
  );
}
