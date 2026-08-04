"use client";
// =============================================================================
// === frontend/app/dashboard/vehicles/page.tsx ===
// =============================================================================
import { Customer, customersApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import { AlertTriangle, Calendar, Check, ChevronDown, Loader2, Plus, Search, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

// Chris's own catch, 4 Aug: a plain <select> genuinely doesn't scale
// once Made has 50+ real customers — scrolling and squinting through
// a long alphabetical list every time a vehicle gets added, made
// worse by institutional clients whose names all start similarly
// ("Polresta Batanghari", "Polresta Tanjung Pinang"). Client-side
// substring search, not a new backend endpoint — customersApi.list()
// already fetches the full list once for this page, and a real shop's
// customer count is nowhere near the scale where filtering in the
// browser would ever be the bottleneck.
function CustomerCombobox({ customers, value, onChange }: {
  customers: Customer[]; value: string; onChange: (id: string) => void;
}) {
  const selected = customers.find((c) => c.id === value) ?? null;
  const [query, setQuery] = useState(selected?.name ?? "");
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Keeps the input's displayed text in sync if `value` ever changes
  // from outside this component (e.g. the whole form getting reset
  // after a successful save) — not just on first mount.
  useEffect(() => {
    setQuery(selected?.name ?? "");
  }, [selected?.id]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
        // Snap back to the real selected name (or blank) — typing
        // something that matches nobody and clicking away shouldn't
        // leave stray, non-committed text sitting in the field.
        setQuery(selected?.name ?? "");
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [selected]);

  const results = query.trim()
    ? customers.filter((c) => c.name.toLowerCase().includes(query.trim().toLowerCase()))
    : customers;

  const selectCustomer = (customer: Customer) => {
    onChange(customer.id);
    setQuery(customer.name);
    setOpen(false);
  };

  const handleInputChange = (text: string) => {
    setQuery(text);
    setOpen(true);
    setHighlighted(0);
    // A real selection only exists once explicitly picked from the
    // list — typing over a previously-selected name (even by one
    // character) must clear the actual committed value, so the
    // form's own `required` check on customer can't silently pass
    // with a stale id that no longer matches what's displayed.
    if (!selected || text !== selected.name) onChange("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlighted((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && results[highlighted]) selectCustomer(results[highlighted]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery(selected?.name ?? "");
    }
  };

  return (
    <div ref={wrapperRef} style={{ position: "relative" }}>
      <div style={{ position: "relative" }}>
        <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--steel)", pointerEvents: "none" }} />
        <input
          className="input"
          style={{ paddingLeft: 30 }}
          placeholder="Cari nama pelanggan…"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          // A customer must be genuinely picked from the dropdown —
          // typed text alone never counts as a real selection, see
          // handleInputChange's own comment. The actual required
          // check happens in AddVehicleModal's handleSubmit(), not
          // here (a hidden input can't enforce `required` — see the
          // comment on that field just below).
        />
        {/* Purely a semantic conduit for the actual committed
            selection — NOT a validation mechanism. Caught before
            shipping: the HTML spec explicitly ignores `required` on
            type="hidden" inputs, so a required attribute here would
            have silently done nothing. The real check lives in
            handleSubmit() below instead. */}
        <input type="hidden" value={value} onChange={() => {}} />
      </div>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 20,
          background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 6,
          maxHeight: 220, overflowY: "auto", boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
        }}>
          {results.length === 0 ? (
            <div style={{ padding: "10px 12px", fontSize: 13, color: "var(--steel)" }}>Tidak ada pelanggan yang cocok.</div>
          ) : (
            results.map((c, i) => (
              <div
                key={c.id}
                onMouseDown={(e) => { e.preventDefault(); selectCustomer(c); }}
                onMouseEnter={() => setHighlighted(i)}
                style={{
                  padding: "9px 12px", fontSize: 13.5, cursor: "pointer",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  background: i === highlighted ? "var(--paper-3)" : "transparent",
                }}
              >
                {c.name}
                {c.id === value && <Check size={13} style={{ color: "var(--rust)" }} />}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function AddVehicleModal({ customers, onClose, onCreated }: {
  customers: Customer[]; onClose: () => void; onCreated: (v: Vehicle) => void;
}) {
  const [form, setForm] = useState({
    customer: "", plate_number: "", manufacture_year: new Date().getFullYear(),
    vehicle_type: "Mobil", model: "", current_odometer_km: 0,
    // Sprint 1: STNK fields — all optional, kept in a separate
    // "collapsed by default" section below so the fast path (add a
    // vehicle with the basics, fill in STNK details later) stays
    // exactly as quick as it was before this sprint.
    body_style: "", chassis_number: "", engine_number: "",
    bpkb_number: "", color: "", registration_expiry: "",
  });
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [showStnk, setShowStnk]   = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // The real required-field check for customer — the old <select
    // required> enforced this natively; a hidden input can't (see
    // CustomerCombobox's own comment on why), so it has to happen
    // here instead, explicitly.
    if (!form.customer) {
      setError("Pilih pelanggan terlebih dahulu.");
      return;
    }
    setSaving(true); setError(null);
    try {
      // Strip empty-string optional fields rather than sending them —
      // an empty string for registration_expiry (a DateField on the
      // backend) would fail validation outright instead of being
      // treated as "not provided."
      const payload = { ...form };
      (Object.keys(payload) as (keyof typeof payload)[]).forEach((key) => {
        if (payload[key] === "" && key !== "plate_number" && key !== "model") {
          delete (payload as Record<string, unknown>)[key];
        }
      });
      const vehicle = await vehiclesApi.create(payload);
      onCreated(vehicle);
      onClose();
    } catch {
      setError("Gagal menyimpan kendaraan. Pastikan nomor plat belum terdaftar.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, overflowY: "auto", padding: "40px 0" }}>
      <div className="card" style={{ width: 460, background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Tambah Kendaraan</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Pelanggan</label>
            <CustomerCombobox customers={customers} value={form.customer} onChange={(id) => setForm({ ...form, customer: id })} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Nomor Plat</label>
              <input className="input" required value={form.plate_number} onChange={(e) => setForm({ ...form, plate_number: e.target.value.toUpperCase() })} placeholder="BP 1234 AB" />
            </div>
            <div>
              <label className="label">Tahun</label>
              <input className="input" type="number" required value={form.manufacture_year} onChange={(e) => setForm({ ...form, manufacture_year: Number(e.target.value) })} />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Jenis Kendaraan</label>
              <select className="input" value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}>
                <option>Mobil</option><option>Motor</option>
              </select>
            </div>
            <div>
              <label className="label">Merek/Type</label>
              <input className="input" required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="Toyota Avanza" />
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">KM Saat Ini</label>
            <input className="input" type="number" min={0} value={form.current_odometer_km} onChange={(e) => setForm({ ...form, current_odometer_km: Number(e.target.value) })} />
          </div>

          {/* Sprint 1: STNK details — collapsed by default, optional */}
          <button
            type="button"
            onClick={() => setShowStnk(!showStnk)}
            style={{ background: "none", border: "none", display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", padding: 0, marginBottom: showStnk ? 14 : 20, cursor: "pointer" }}
          >
            <ChevronDown size={14} style={{ transform: showStnk ? "rotate(180deg)" : "none", transition: "transform 0.15s" }} />
            Detail STNK <span style={{ fontWeight: 400 }}>(opsional)</span>
          </button>

          {showStnk && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                <div>
                  <label className="label">Jenis/Model</label>
                  <input className="input" value={form.body_style} onChange={(e) => setForm({ ...form, body_style: e.target.value })} placeholder="Sedan, SUV, MPV" />
                </div>
                <div>
                  <label className="label">Warna</label>
                  <input className="input" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} placeholder="Putih" />
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="label">No. Rangka</label>
                <input className="input mono" value={form.chassis_number} onChange={(e) => setForm({ ...form, chassis_number: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="label">No. Mesin</label>
                <input className="input mono" value={form.engine_number} onChange={(e) => setForm({ ...form, engine_number: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="label">No. BPKB</label>
                <input className="input mono" value={form.bpkb_number} onChange={(e) => setForm({ ...form, bpkb_number: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ marginBottom: 20 }}>
                <label className="label">STNK Berlaku Sampai</label>
                <input className="input" type="date" value={form.registration_expiry} onChange={(e) => setForm({ ...form, registration_expiry: e.target.value })} />
              </div>
            </>
          )}

          <button className="btn-rust" type="submit" disabled={saving} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

type FilterMode = "all" | "due" | "expiring";

export default function VehiclesPage() {
  const [vehicles, setVehicles]   = useState<Vehicle[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading]     = useState(true);
  const [filter, setFilter]       = useState<FilterMode>("all");
  const [showAdd, setShowAdd]     = useState(false);

  const load = (mode: FilterMode) => {
    setLoading(true);
    vehiclesApi.list({
      dueForService: mode === "due",
      registrationExpiringSoon: mode === "expiring",
    }).then(setVehicles).finally(() => setLoading(false));
  };

  useEffect(() => { load(filter); }, [filter]);
  useEffect(() => { customersApi.list().then(setCustomers); }, []);

  const emptyMessage = filter === "due" ? "Tidak ada kendaraan yang harus servis"
    : filter === "expiring" ? "Tidak ada STNK yang akan jatuh tempo dalam 30 hari"
    : "Belum ada kendaraan";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, marginBottom: 4, textTransform: "none" }}>Kendaraan</h1>
          <p style={{ color: "var(--steel)", fontSize: 14 }}>{vehicles.length} kendaraan {filter !== "all" ? "(terfilter)" : "tercatat"}</p>
        </div>
        <button className="btn-rust" onClick={() => setShowAdd(true)}><Plus size={16} /> Tambah Kendaraan</button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        <button onClick={() => setFilter("all")} className={filter === "all" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13 }}>Semua</button>
        <button onClick={() => setFilter("due")} className={filter === "due" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={14} /> Harus Servis
        </button>
        <button onClick={() => setFilter("expiring")} className={filter === "expiring" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <Calendar size={14} /> STNK Segera Habis
        </button>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Plat</th><th>Merek/Type</th><th>Pelanggan</th><th>KM Sekarang</th><th>Servis Terakhir</th><th>Status</th></tr>
            </thead>
            <tbody>
              {vehicles.map((v) => (
                <tr key={v.id}>
                  <td><Link href={`/dashboard/vehicle-detail?id=${v.id}`} className="mono" style={{ fontWeight: 600, color: "var(--rust)" }}>{v.plate_number}</Link></td>
                  <td>{v.model} <span style={{ color: "var(--steel)", fontSize: 12.5 }}>({v.manufacture_year})</span></td>
                  <td>{v.customer_name}</td>
                  <td className="mono">{v.current_odometer_km.toLocaleString("id-ID")} km</td>
                  <td className="mono" style={{ fontSize: 13 }}>{v.last_service_date || <span style={{ color: "var(--steel)" }}>Belum pernah</span>}</td>
                  <td style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <span className={`pill ${v.is_due_for_service ? "due" : "ok"}`}>
                      <span className="dot" />{v.is_due_for_service ? "Harus Servis" : "Aman"}
                    </span>
                    {v.is_registration_expiring_soon && (
                      <span className="pill due"><Calendar size={11} style={{ marginRight: 3 }} />STNK Segera Habis</span>
                    )}
                  </td>
                </tr>
              ))}
              {vehicles.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>{emptyMessage}</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddVehicleModal customers={customers} onClose={() => setShowAdd(false)} onCreated={(v) => setVehicles((prev) => [v, ...prev])} />
      )}
    </div>
  );
}
