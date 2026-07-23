"use client";
// =============================================================================
// === frontend/app/dashboard/vehicle-detail/page.tsx ===
// Was app/dashboard/vehicles/[id]/page.tsx — moved from a dynamic
// path segment to a query param specifically to support static
// export. A dynamic route needs every possible URL known at build
// time; real vehicle UUIDs only exist after a shop creates them, so
// that's structurally impossible here. A query string doesn't have
// that problem — the served HTML is identical regardless of ?id=
// value, and the client-side JS reads it once loaded.
// =============================================================================
import { invoicesApi, LaborLinePayload } from "@/lib/api/invoicing";
import { Part, partsApi, partUsagesApi, ServiceRecord, serviceRecordsApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { AlertTriangle, ArrowLeft, Calendar, FileText, Loader2, Plus, Receipt, Trash2, Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

interface PartLine {
  key:      string;
  part:     string;
  quantity: string;
}

interface LaborLine {
  key:         string;
  description: string;
  quantity:    string;
  unit_price:  string;
}

function AddServiceRecordForm({ vehicleId, catalog, onAdded }: {
  vehicleId: string; catalog: Part[]; onAdded: (r: ServiceRecord, newOdometer: number) => void;
}) {
  const [form, setForm] = useState({
    service_date: new Date().toISOString().slice(0, 10),
    odometer_km: "", issue_description: "", parts_replaced: "", notes: "",
  });
  const [partLines, setPartLines] = useState<PartLine[]>([]);
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [open, setOpen]       = useState(false);

  const addPartLine = () => {
    setPartLines((prev) => [...prev, { key: crypto.randomUUID(), part: "", quantity: "" }]);
  };
  const removePartLine = (key: string) => {
    setPartLines((prev) => prev.filter((l) => l.key !== key));
  };
  const updatePartLine = (key: string, field: "part" | "quantity", value: string) => {
    setPartLines((prev) => prev.map((l) => (l.key === key ? { ...l, [field]: value } : l)));
  };

  const resetForm = () => {
    setForm({ service_date: new Date().toISOString().slice(0, 10), odometer_km: "", issue_description: "", parts_replaced: "", notes: "" });
    setPartLines([]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null); setWarnings([]);

    let record: ServiceRecord;
    try {
      record = await serviceRecordsApi.create(vehicleId, {
        ...form, odometer_km: Number(form.odometer_km),
      });
    } catch {
      setError("Gagal menyimpan catatan servis.");
      setSaving(false);
      return;
    }

    const filledLines = partLines.filter((l) => l.part && l.quantity);
    const results = await Promise.allSettled(
      filledLines.map((l) => partUsagesApi.create(record.id, { part: l.part, quantity: Number(l.quantity) }))
    );

    const failedLines: string[] = [];
    const allWarnings: string[] = [];
    results.forEach((result, i) => {
      const line = filledLines[i];
      const partName = catalog.find((p) => p.id === line.part)?.name ?? "Part";
      if (result.status === "rejected") {
        failedLines.push(partName);
      } else if (result.value.warnings.length > 0) {
        allWarnings.push(...result.value.warnings);
      }
    });

    onAdded(record, Number(form.odometer_km));

    if (failedLines.length > 0) {
      setError(`Catatan servis tersimpan, tapi gagal mencatat: ${failedLines.join(", ")}. Coba lagi di bawah.`);
      setWarnings(allWarnings);
      setSaving(false);
      return;
    }

    if (allWarnings.length > 0) {
      setWarnings(allWarnings);
    }

    resetForm();
    setSaving(false);
    setOpen(false);
  };

  if (!open) {
    return <button className="btn-rust" onClick={() => setOpen(true)}><Plus size={16} /> Catat Servis Baru</button>;
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Catat Servis Baru</h3>
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
      {warnings.map((w, i) => (
        <div key={i} style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 8 }}>{w}</div>
      ))}
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div>
            <label className="label">Tanggal Servis</label>
            <input className="input" type="date" required value={form.service_date} onChange={(e) => setForm({ ...form, service_date: e.target.value })} />
          </div>
          <div>
            <label className="label">KM Saat Servis</label>
            <input className="input" type="number" required min={0} value={form.odometer_km} onChange={(e) => setForm({ ...form, odometer_km: e.target.value })} />
          </div>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label className="label">Kerusakan</label>
          <textarea className="input" required rows={2} value={form.issue_description} onChange={(e) => setForm({ ...form, issue_description: e.target.value })} placeholder="Ganti oli, servis rem, dll." />
        </div>
        <div style={{ marginBottom: 14 }}>
          <label className="label">Part yang Diganti <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional, catatan bebas)</span></label>
          <input className="input" value={form.parts_replaced} onChange={(e) => setForm({ ...form, parts_replaced: e.target.value })} placeholder="Filter oli, kampas rem" />
        </div>

        <div style={{ marginBottom: 14 }}>
          <label className="label">Part dari Katalog <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional — otomatis kurangi stok)</span></label>
          {partLines.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
              {partLines.map((line) => (
                <div key={line.key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <select
                    className="input" style={{ flex: 1 }}
                    value={line.part}
                    onChange={(e) => updatePartLine(line.key, "part", e.target.value)}
                  >
                    <option value="">— Pilih Part —</option>
                    {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.current_stock} {p.unit})</option>)}
                  </select>
                  <input
                    className="input" style={{ width: 90 }} type="number" min={0} step="0.01" placeholder="Jml"
                    value={line.quantity}
                    onChange={(e) => updatePartLine(line.key, "quantity", e.target.value)}
                  />
                  <button type="button" onClick={() => removePartLine(line.key)} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}>
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <button type="button" className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} onClick={addPartLine}>
            <Plus size={13} /> Tambah Part dari Katalog
          </button>
        </div>

        <div style={{ marginBottom: 18 }}>
          <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
          <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-rust" type="submit" disabled={saving}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
          <button type="button" className="btn-ghost" onClick={() => { resetForm(); setError(null); setWarnings([]); setOpen(false); }}>Batal</button>
        </div>
      </form>
    </div>
  );
}

function PartUsageRow({ record, catalog, onUsed }: {
  record: ServiceRecord; catalog: Part[]; onUsed: () => void;
}) {
  const [adding, setAdding]     = useState(false);
  const [partId, setPartId]     = useState("");
  const [qty, setQty]           = useState("");
  const [saving, setSaving]     = useState(false);
  const [warning, setWarning]   = useState<string | null>(null);
  const [error, setError]       = useState<string | null>(null);

  const handleAdd = async () => {
    if (!partId || !qty) return;
    setSaving(true); setError(null); setWarning(null);
    try {
      const { warnings } = await partUsagesApi.create(record.id, { part: partId, quantity: Number(qty) });
      if (warnings.length > 0) setWarning(warnings[0]);
      setPartId(""); setQty(""); setAdding(false);
      onUsed();
    } catch {
      setError("Gagal mencatat pemakaian part.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: record.parts_replaced ? 8 : 0 }}>
      {record.part_usages.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
          {record.part_usages.map((pu) => (
            <div key={pu.id} className="mono" style={{ fontSize: 12.5, color: "var(--steel)", display: "flex", justifyContent: "space-between" }}>
              <span>{pu.part_name} × {pu.quantity} {pu.unit}</span>
              <span>@ Rp {Number(pu.unit_price_at_time).toLocaleString("id-ID")}</span>
            </div>
          ))}
        </div>
      )}

      {warning && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "6px 10px", borderRadius: 5, fontSize: 12, marginBottom: 8 }}>{warning}</div>}
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "6px 10px", borderRadius: 5, fontSize: 12, marginBottom: 8 }}>{error}</div>}

      {record.invoice_id ? null : (
        adding ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select className="input" style={{ fontSize: 12.5, padding: "6px 8px" }} value={partId} onChange={(e) => setPartId(e.target.value)}>
              <option value="">— Pilih Part —</option>
              {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.current_stock} {p.unit})</option>)}
            </select>
            <input className="input" style={{ fontSize: 12.5, padding: "6px 8px", width: 80 }} type="number" min={0} step="0.01" placeholder="Jml" value={qty} onChange={(e) => setQty(e.target.value)} />
            <button className="btn-rust" style={{ fontSize: 12, padding: "6px 10px" }} disabled={saving} onClick={handleAdd}>
              {saving ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
            </button>
            <button className="btn-ghost" style={{ fontSize: 12, padding: "6px 10px" }} onClick={() => setAdding(false)}>Batal</button>
          </div>
        ) : (
          <button className="btn-ghost" style={{ fontSize: 12, padding: "5px 9px" }} onClick={() => setAdding(true)}>
            <Plus size={12} /> Gunakan Part dari Katalog
          </button>
        )
      )}
    </div>
  );
}

function CreateInvoiceModal({ record, onClose, onCreated }: {
  record: ServiceRecord; onClose: () => void; onCreated: (invoiceId: string) => void;
}) {
  const [laborLines, setLaborLines] = useState<LaborLine[]>([
    { key: crypto.randomUUID(), description: "", quantity: "1", unit_price: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const addLine = () => setLaborLines((prev) => [...prev, { key: crypto.randomUUID(), description: "", quantity: "1", unit_price: "" }]);
  const removeLine = (key: string) => setLaborLines((prev) => prev.filter((l) => l.key !== key));
  const updateLine = (key: string, field: keyof Omit<LaborLine, "key">, value: string) =>
    setLaborLines((prev) => prev.map((l) => (l.key === key ? { ...l, [field]: value } : l)));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    const payload: LaborLinePayload[] = laborLines
      .filter((l) => l.description && l.unit_price)
      .map((l) => ({ description: l.description, quantity: Number(l.quantity) || 1, unit_price: Number(l.unit_price) }));
    try {
      const invoice = await invoicesApi.create(record.id, payload);
      onCreated(invoice.id);
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(apiMessage || "Gagal membuat invoice.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, overflowY: "auto", padding: "40px 0" }}>
      <div className="card" style={{ width: 560, background: "var(--paper-3)" }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Buat Invoice</h2>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 16 }}>
          {record.service_date} — {record.issue_description}
        </p>

        {/* Part usages are read-only here — they were already locked
            in the moment a mechanic logged them, same reasoning as
            everywhere else this sprint: an invoice snapshots what
            already happened, it never re-decides it. */}
        {record.part_usages.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div className="label" style={{ marginBottom: 6 }}>Part (dari catatan servis)</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {record.part_usages.map((pu) => (
                <div key={pu.id} className="mono" style={{ fontSize: 13, display: "flex", justifyContent: "space-between", color: "var(--ink-soft)" }}>
                  <span>{pu.part_name} × {pu.quantity} {pu.unit}</span>
                  <span>Rp {(Number(pu.unit_price_at_time) * Number(pu.quantity)).toLocaleString("id-ID")}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="label" style={{ marginBottom: 6 }}>Jasa</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
            {laborLines.map((line) => (
              <div key={line.key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input className="input" style={{ flex: 2 }} placeholder="Jasa Servis Rem" value={line.description} onChange={(e) => updateLine(line.key, "description", e.target.value)} />
                <input className="input" style={{ width: 60 }} type="number" min={1} value={line.quantity} onChange={(e) => updateLine(line.key, "quantity", e.target.value)} />
                <input className="input" style={{ flex: 1 }} type="number" min={0} placeholder="Harga" value={line.unit_price} onChange={(e) => updateLine(line.key, "unit_price", e.target.value)} />
                <button type="button" onClick={() => removeLine(line.key)} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}>
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", marginBottom: 18 }} onClick={addLine}>
            <Plus size={13} /> Tambah Jasa
          </button>

          <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 16 }}>
            Invoice tidak bisa diedit setelah dibuat — periksa dulu sebelum menyimpan.
          </p>

          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-rust" type="submit" disabled={saving}>
              {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Buat Invoice"}
            </button>
            <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function VehicleDetailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const vehicleId = searchParams.get("id") ?? "";
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [catalog, setCatalog] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [invoicingRecord, setInvoicingRecord] = useState<ServiceRecord | null>(null);

  const load = () => vehiclesApi.get(vehicleId).then(setVehicle).finally(() => setLoading(false));
  useEffect(() => {
    if (vehicleId) load();
  }, [vehicleId]);
  useEffect(() => { partsApi.list().then(setCatalog); }, []);

  const handleAdded = () => load();

  if (!vehicleId) {
    return <div style={{ color: "var(--danger)" }}>Kendaraan tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }

  if (loading || !vehicle) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  const stnkFields = [
    { label: "Jenis Bodi", value: vehicle.body_style },
    { label: "Warna", value: vehicle.color },
    { label: "No. Rangka", value: vehicle.chassis_number },
    { label: "No. Mesin", value: vehicle.engine_number },
    { label: "No. BPKB", value: vehicle.bpkb_number },
  ].filter((f) => f.value);

  return (
    <div>
      <Link href="/dashboard/vehicles" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Kendaraan
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <span className="mono" style={{ fontSize: 26, fontWeight: 700, background: "var(--ink)", color: "var(--paper)", padding: "5px 12px", borderRadius: 5, display: "inline-block" }}>
            {vehicle.plate_number}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {vehicle.is_due_for_service && (
            <span className="pill due" style={{ fontSize: 13 }}><AlertTriangle size={13} /> Harus Segera Servis</span>
          )}
          {vehicle.is_registration_expiring_soon && (
            <span className="pill due" style={{ fontSize: 13 }}><Calendar size={13} /> STNK Segera Habis</span>
          )}
        </div>
      </div>

      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 24 }}>
        {vehicle.model} · {vehicle.manufacture_year} · {vehicle.customer_name}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 16 }}>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>KM Sekarang</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.current_odometer_km.toLocaleString("id-ID")}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Servis Terakhir</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{vehicle.last_service_date || "—"}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>STNK Berlaku Sampai</div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: vehicle.is_registration_expiring_soon ? "var(--danger)" : undefined }}>
            {vehicle.registration_expiry || "—"}
          </div>
        </div>
      </div>

      {stnkFields.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 10 }}>Detail STNK</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10 }}>
            {stnkFields.map((f) => (
              <div key={f.label}>
                <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{f.label}</div>
                <div className="mono" style={{ fontSize: 13.5 }}>{f.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginBottom: 16 }}>
        <AddServiceRecordForm vehicleId={vehicle.id} catalog={catalog} onAdded={handleAdded} />
      </div>

      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
        <Wrench size={16} /> Riwayat Servis
      </h2>

      {(vehicle.service_records?.length ?? 0) === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 32 }}>Belum ada riwayat servis untuk kendaraan ini.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {vehicle.service_records!.map((r) => (
            <div key={r.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{r.service_date}</span>
                <span className="mono" style={{ fontSize: 13, color: "var(--steel)" }}>{r.odometer_km.toLocaleString("id-ID")} km</span>
              </div>
              <p style={{ fontSize: 14, marginBottom: r.parts_replaced ? 6 : 0 }}>{r.issue_description}</p>
              {r.parts_replaced && <p style={{ fontSize: 13, color: "var(--steel)" }}>Part diganti (catatan bebas): {r.parts_replaced}</p>}
              {r.notes && <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 4 }}>{r.notes}</p>}
              <PartUsageRow record={r} catalog={catalog} onUsed={handleAdded} />

              <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                {r.invoice_id ? (
                  <Link href={`/dashboard/invoice-detail?id=${r.invoice_id}`} className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Receipt size={13} /> Lihat Invoice
                  </Link>
                ) : (
                  <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} onClick={() => setInvoicingRecord(r)}>
                    <FileText size={13} /> Buat Invoice
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {invoicingRecord && (
        <CreateInvoiceModal
          record={invoicingRecord}
          onClose={() => setInvoicingRecord(null)}
          onCreated={(invoiceId) => router.push(`/dashboard/invoice-detail?id=${invoiceId}`)}
        />
      )}
    </div>
  );
}

// useSearchParams() requires a Suspense boundary on statically  exported/prerendered pages — without this, the build fails.

export default function VehicleDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <VehicleDetailContent />
    </Suspense>
  );
}
