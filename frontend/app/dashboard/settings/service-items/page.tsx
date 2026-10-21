"use client";
// =============================================================================
// === frontend/app/dashboard/settings/service-items/page.tsx ===
// =============================================================================
// 20 Oct 2026 (Phase 21, Task 21.3) — Daftar Jasa. Made's handwritten note,
// 12 Sep 2026: "Jasa: misalnya tune-up: muncul klasifikasi harga tune-up —
// Sedan / SUV / Ertiga ... ini harus bisa di-update!" One price per vehicle
// class plus a default used when the vehicle has no class or the jasa has no
// price for it. Only the owner can change anything here (backend enforces it
// with a 403; this page just disables the controls). Every change is logged —
// "Riwayat" on each row shows who changed what, and when.
import SettingsSubNav from "@/components/settings/SettingsSubNav";
import {
  ServiceItem, ServiceItemChange, ServiceItemPayload, VEHICLE_CLASSES, VehicleClass, serviceItemsApi,
} from "@/lib/api/service";
import { AlertTriangle, Check, History, Loader2, Pencil, Plus, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

type PriceForm = { name: string; default_price: string; class_prices: Record<VehicleClass, string> };

function emptyClassPrices(): Record<VehicleClass, string> {
  return Object.fromEntries(VEHICLE_CLASSES.map((c) => [c, ""])) as Record<VehicleClass, string>;
}

function toForm(item?: ServiceItem): PriceForm {
  const class_prices = emptyClassPrices();
  if (item) {
    for (const c of VEHICLE_CLASSES) {
      const v = item.class_prices[c];
      class_prices[c] = v ? String(Math.round(Number(v))) : "";
    }
  }
  return {
    name: item?.name ?? "",
    default_price: item ? String(Math.round(Number(item.default_price))) : "",
    class_prices,
  };
}

// Create sends only filled classes; edit sends every class, with null for an
// emptied one, so clearing a box really removes that class's own price.
function toPayload(form: PriceForm, forCreate: boolean): ServiceItemPayload {
  const class_prices: Partial<Record<VehicleClass, number | null>> = {};
  for (const c of VEHICLE_CLASSES) {
    const v = form.class_prices[c].trim();
    if (v !== "") class_prices[c] = Number(v);
    else if (!forCreate) class_prices[c] = null;
  }
  return { name: form.name.trim(), default_price: Number(form.default_price), class_prices };
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", minimumFractionDigits: 0, maximumFractionDigits: 0,
  }).format(Number(value));
}

function apiMessage(err: unknown, fallback: string): string {
  const data = (err as { response?: { data?: { message?: string } } })?.response?.data;
  return data?.message || fallback;
}

function PriceFields({ form, onChange, disabled }: {
  form: PriceForm; onChange: (f: PriceForm) => void; disabled: boolean;
}) {
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <label className="label">Nama Jasa</label>
          <input className="input" value={form.name} disabled={disabled} placeholder="mis. Tune-up"
            onChange={(e) => onChange({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label className="label">Harga Default</label>
          <input className="input mono" type="number" min={0} value={form.default_price} disabled={disabled}
            placeholder="mis. 300000" onChange={(e) => onChange({ ...form, default_price: e.target.value })} />
        </div>
      </div>
      <div className="label" style={{ marginBottom: 6 }}>Harga per Kelas Kendaraan</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: 10, marginBottom: 6 }}>
        {VEHICLE_CLASSES.map((c) => (
          <div key={c}>
            <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 3 }}>{c}</div>
            <input className="input mono" type="number" min={0} value={form.class_prices[c]} disabled={disabled}
              placeholder="= default"
              onChange={(e) => onChange({ ...form, class_prices: { ...form.class_prices, [c]: e.target.value } })} />
          </div>
        ))}
      </div>
      <p style={{ fontSize: 12, color: "var(--steel)", marginBottom: 14 }}>
        Kosongkan kelas yang harganya sama dengan harga default.
      </p>
    </>
  );
}

export default function ServiceItemsPage() {
  const [items, setItems] = useState<ServiceItem[]>([]);
  const [loading, setLoading] = useState(true);
  // Safe default: no editing until the server confirms this user is the owner.
  const [canEdit, setCanEdit] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [adding, setAdding] = useState(false);
  const [newForm, setNewForm] = useState<PriceForm>(toForm());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<PriceForm>(toForm());
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [history, setHistory] = useState<ServiceItemChange[]>([]);

  const load = () =>
    serviceItemsApi.list({ includeInactive: showInactive })
      .then((res) => { setItems(res.results); setCanEdit(res.can_edit); })
      .catch((err) => setError(apiMessage(err, "Gagal memuat Daftar Jasa.")))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, [showInactive]); // eslint-disable-line react-hooks/exhaustive-deps

  const validate = (form: PriceForm): string | null => {
    if (!form.name.trim()) return "Nama jasa wajib diisi.";
    if (form.default_price.trim() === "") return "Harga default wajib diisi.";
    return null;
  };

  const handleCreate = async () => {
    const problem = validate(newForm);
    if (problem) { setError(problem); return; }
    setSaving(true); setError(null);
    try {
      await serviceItemsApi.create(toPayload(newForm, true));
      setNewForm(toForm()); setAdding(false);
      await load();
    } catch (err) {
      setError(apiMessage(err, "Gagal menyimpan jasa."));
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async (id: string) => {
    const problem = validate(editForm);
    if (problem) { setError(problem); return; }
    setSaving(true); setError(null);
    try {
      await serviceItemsApi.update(id, toPayload(editForm, false));
      setEditingId(null);
      await load();
      if (historyFor === id) setHistory(await serviceItemsApi.history(id));
    } catch (err) {
      setError(apiMessage(err, "Gagal menyimpan perubahan."));
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (item: ServiceItem) => {
    const verb = item.is_active ? "Nonaktifkan" : "Aktifkan kembali";
    if (!window.confirm(`${verb} "${item.name}"?`)) return;
    setError(null);
    try {
      await serviceItemsApi.update(item.id, { is_active: !item.is_active });
      await load();
    } catch (err) {
      setError(apiMessage(err, "Gagal mengubah status."));
    }
  };

  const toggleHistory = async (id: string) => {
    if (historyFor === id) { setHistoryFor(null); return; }
    setHistoryFor(id); setHistory([]);
    try {
      setHistory(await serviceItemsApi.history(id));
    } catch (err) {
      setError(apiMessage(err, "Gagal memuat riwayat."));
    }
  };

  const colSpan = VEHICLE_CLASSES.length + 4;

  return (
    <div>
      <SettingsSubNav />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <div>
          <h1 className="display" style={{ fontSize: 26, marginBottom: 4, textTransform: "none" }}>Daftar Jasa</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, maxWidth: 620 }}>
            Harga jasa per kelas kendaraan. Kelas diambil dari <b>Jenis Bodi</b> kendaraan; jika kosong atau
            jasa tidak punya harga untuk kelas itu, dipakai harga default.
          </p>
        </div>
        {canEdit && !adding && (
          <button className="btn-rust" onClick={() => { setAdding(true); setError(null); }}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <Plus size={15} /> Tambah Jasa
          </button>
        )}
      </div>

      {!loading && !canEdit && (
        <div style={{ background: "var(--paper-3)", color: "var(--steel)", padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={15} /> Hanya pemilik bengkel yang bisa mengubah Daftar Jasa.
        </div>
      )}

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {adding && (
        <div className="card" style={{ marginBottom: 20, maxWidth: 820 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Jasa Baru</h3>
          <PriceFields form={newForm} onChange={setNewForm} disabled={saving} />
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-rust" onClick={handleCreate} disabled={saving}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={15} />} Simpan
            </button>
            <button className="btn-ghost" onClick={() => { setAdding(false); setNewForm(toForm()); }} disabled={saving}>Batal</button>
          </div>
        </div>
      )}

      <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--steel)", marginBottom: 10 }}>
        <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
        Tampilkan jasa nonaktif
      </label>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)", fontSize: 14 }}>
            Belum ada jasa di Daftar Jasa.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Jasa</th>
                <th style={{ textAlign: "right" }}>Default</th>
                {VEHICLE_CLASSES.map((c) => <th key={c} style={{ textAlign: "right" }}>{c}</th>)}
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Fragment key={item.id}>
                  <tr style={{ opacity: item.is_active ? 1 : 0.55 }}>
                    <td style={{ fontWeight: 600 }}>{item.name}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{formatRupiah(item.default_price)}</td>
                    {VEHICLE_CLASSES.map((c) => (
                      <td key={c} className="mono" style={{ textAlign: "right" }}>
                        {item.class_prices[c]
                          ? formatRupiah(item.class_prices[c] as string)
                          : <span style={{ color: "var(--steel)", fontSize: 12 }}>= default</span>}
                      </td>
                    ))}
                    <td style={{ fontSize: 12.5 }}>{item.is_active ? "Aktif" : "Nonaktif"}</td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 8px", marginRight: 6 }}
                        onClick={() => toggleHistory(item.id)} title="Riwayat perubahan">
                        <History size={13} />
                      </button>
                      {canEdit && (
                        <>
                          <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 8px", marginRight: 6 }}
                            onClick={() => { setEditingId(item.id); setEditForm(toForm(item)); setError(null); }} title="Ubah">
                            <Pencil size={13} />
                          </button>
                          <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }}
                            onClick={() => toggleActive(item)}>
                            {item.is_active ? "Nonaktifkan" : "Aktifkan"}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                  {editingId === item.id && (
                    <tr>
                      <td colSpan={colSpan} style={{ background: "var(--paper-3)" }}>
                        <div style={{ padding: "8px 4px", maxWidth: 820 }}>
                          <PriceFields form={editForm} onChange={setEditForm} disabled={saving} />
                          <div style={{ display: "flex", gap: 10 }}>
                            <button className="btn-rust" onClick={() => handleUpdate(item.id)} disabled={saving}
                              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={15} />} Simpan Perubahan
                            </button>
                            <button className="btn-ghost" onClick={() => setEditingId(null)} disabled={saving}
                              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              <X size={14} /> Batal
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                  {historyFor === item.id && (
                    <tr>
                      <td colSpan={colSpan} style={{ background: "var(--paper-3)" }}>
                        <div style={{ padding: "6px 4px", fontSize: 12.5 }}>
                          <div style={{ fontWeight: 600, marginBottom: 6 }}>Riwayat Perubahan — {item.name}</div>
                          {history.length === 0 ? (
                            <span style={{ color: "var(--steel)" }}>Memuat…</span>
                          ) : history.map((h) => (
                            <div key={h.id} style={{ display: "flex", gap: 10, padding: "3px 0", borderBottom: "1px solid var(--line)" }}>
                              <span className="mono" style={{ color: "var(--steel)", minWidth: 150 }}>
                                {new Date(h.changed_at).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}
                              </span>
                              <span style={{ minWidth: 110, fontWeight: 600 }}>{h.field_label}</span>
                              <span>
                                {h.old_value && <span style={{ color: "var(--steel)", textDecoration: "line-through", marginRight: 6 }}>{h.old_value}</span>}
                                {h.new_value}
                              </span>
                              <span style={{ marginLeft: "auto", color: "var(--steel)" }}>{h.changed_by_name ?? "—"}</span>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
