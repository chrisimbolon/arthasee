"use client";
// =============================================================================
// === frontend/app/dashboard/customer-detail/page.tsx ===
// =============================================================================
// 13 Sep 2026 — new page, no prior version existed. Real, deliberate
// design call: Customer previously had no detail page at all — only
// a flat list with Add/Delete. Built to match the EXACT real shell
// convention vehicle-detail/page.tsx already established (query-param
// id via useSearchParams + Suspense, back link, header, stat cards,
// stacked sections below) — NOT the tabbed-modal shape the original
// reference screenshot used, since every other detail page in this
// app (vehicle-detail, invoice-detail, work-order-detail,
// estimate-detail) is a single scrolling page with real sections,
// never tabs.
//
// The "Edit" section is a toggle-to-edit card, matching the inline
// expand-to-edit pattern the Daftar Akun page already established
// (Phase 17/18) — not a separate route, not a modal.
//
// "Riwayat Perubahan" is the real payoff: every genuine field change
// Customer.apply_edit() has ever recorded (backend), red-strikethrough
// old value -> green new value, who changed it, when — the same real
// pattern the RT Mudah reference showed, just as its own section here
// rather than a modal tab.
import { Customer, CustomerFieldChange, CustomerType, customersApi } from "@/lib/api/service";
import { AlertTriangle, ArrowLeft, Loader2, Pencil } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function formatChangedAt(iso: string): string {
  return new Date(iso).toLocaleString("id-ID", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function EditCustomerCard({ customer, onSaved }: { customer: Customer; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: customer.name, phone: customer.phone,
    stnk_name: customer.stnk_name, customer_type: customer.customer_type,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setForm({
      name: customer.name, phone: customer.phone,
      stnk_name: customer.stnk_name, customer_type: customer.customer_type,
    });
    setError(null);
    setEditing(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await customersApi.update(customer.id, form);
      setEditing(false);
      onSaved();
    } catch {
      setError("Gagal menyimpan perubahan.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Data Pelanggan</div>
          <button onClick={startEditing} className="btn-ghost" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <Pencil size={13} /> Edit
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 14 }}>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Nama Pelanggan</div>
            <div style={{ fontSize: 14 }}>{customer.name}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Nomor Telepon</div>
            <div className="mono" style={{ fontSize: 14 }}>{customer.phone || "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Nama di STNK</div>
            <div style={{ fontSize: 14 }}>{customer.stnk_name || "Sama dengan nama"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Jenis Pelanggan</div>
            <div style={{ fontSize: 14 }}>{customer.customer_type === "INSTITUTIONAL" ? "Institusi/Tender" : "Perorangan"}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="card" style={{ marginBottom: 24 }}>
      <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 14 }}>Edit Data Pelanggan</div>
      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>
          {error}
        </div>
      )}
      <div style={{ marginBottom: 14 }}>
        <label className="label">Nama Pelanggan</label>
        <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </div>
      <div style={{ marginBottom: 14 }}>
        <label className="label">Nomor Telepon</label>
        <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
      </div>
      <div style={{ marginBottom: 14 }}>
        <label className="label">Nama di STNK</label>
        <input className="input" value={form.stnk_name} onChange={(e) => setForm({ ...form, stnk_name: e.target.value })} placeholder="Kosongkan jika sama" />
      </div>
      <div style={{ marginBottom: 20 }}>
        <label className="label">Jenis Pelanggan</label>
        <select
          className="input" value={form.customer_type}
          onChange={(e) => setForm({ ...form, customer_type: e.target.value as CustomerType })}
        >
          <option value="INDIVIDUAL">Perorangan</option>
          <option value="INSTITUTIONAL">Institusi/Tender</option>
        </select>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn-rust" type="submit" disabled={saving}>
          {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
        </button>
        <button type="button" className="btn-ghost" disabled={saving} onClick={() => setEditing(false)}>
          Batal
        </button>
      </div>
    </form>
  );
}

function HistorySection({ customerId }: { customerId: string }) {
  const [changes, setChanges] = useState<CustomerFieldChange[] | null>(null);

  useEffect(() => {
    customersApi.history(customerId).then(setChanges);
  }, [customerId]);

  return (
    <div>
      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>Riwayat Perubahan</h2>
      {changes === null ? (
        <div style={{ color: "var(--steel)", fontSize: 13.5, display: "flex", alignItems: "center", gap: 8 }}>
          <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> Memuat riwayat…
        </div>
      ) : changes.length === 0 ? (
        <div className="card" style={{ color: "var(--steel)", fontSize: 13.5 }}>
          Belum ada perubahan tercatat untuk pelanggan ini.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {changes.map((change) => (
            <div key={change.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{change.field_label}</span>
                <span style={{ fontSize: 12, color: "var(--steel)" }}>{formatChangedAt(change.changed_at)}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13.5, marginBottom: 8, flexWrap: "wrap" }}>
                <span style={{ color: "var(--danger)", textDecoration: "line-through" }}>
                  {change.old_value || "(kosong)"}
                </span>
                <span style={{ color: "var(--steel)" }}>→</span>
                <span style={{ color: "var(--workshop)", fontWeight: 600 }}>
                  {change.new_value || "(kosong)"}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--steel)" }}>
                Diubah oleh {change.changed_by_name ?? "Sistem"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CustomerDetailContent() {
  const searchParams = useSearchParams();
  const customerId = searchParams.get("id") ?? "";
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => customersApi.get(customerId).then(setCustomer).finally(() => setLoading(false));
  useEffect(() => {
    if (customerId) load();
  }, [customerId]);

  if (!customerId) {
    return <div style={{ color: "var(--danger)" }}>Pelanggan tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }

  if (loading || !customer) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      <Link href="/dashboard/customers" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Kembali ke Pelanggan
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <h1 className="display" style={{ fontSize: 28, textTransform: "none" }}>{customer.name}</h1>
        {customer.customer_type === "INSTITUTIONAL" && (
          <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "var(--workshop)", background: "var(--workshop-lt)", whiteSpace: "nowrap", display: "inline-flex", alignItems: "center", gap: 4 }}>
            <AlertTriangle size={11} /> Institusi/Tender
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Nomor Telepon</div>
          <div className="mono" style={{ fontSize: 18, fontWeight: 600 }}>{customer.phone || "—"}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Nama di STNK</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{customer.stnk_name || "Sama dengan nama"}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", marginBottom: 6 }}>Kendaraan</div>
          <div className="mono" style={{ fontSize: 18, fontWeight: 600 }}>{customer.vehicle_count}</div>
        </div>
      </div>

      <EditCustomerCard customer={customer} onSaved={load} />

      <HistorySection customerId={customer.id} />
    </div>
  );
}

// useSearchParams() requires a Suspense boundary on statically
// exported/prerendered pages — without this, the build fails. Same
// real requirement vehicle-detail/page.tsx already documents.
export default function CustomerDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <CustomerDetailContent />
    </Suspense>
  );
}
