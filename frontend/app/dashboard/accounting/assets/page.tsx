"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/assets/page.tsx ===
// 29 Aug 2026 — Made's own confirmed real request, 27 Aug meeting
// notes: "otomasi depresiasi... bahkan kunci/peralatan kecil izin
// dihitung penyusutannya." A real fixed asset register — record a
// purchase, see its real book value and accumulated depreciation,
// computed live from real AssetDepreciationEntry rows, never cached.
// Depreciation itself runs automatically as part of month-end
// closing (see the Tutup Buku tab on the Laporan page) — this page
// is purely for RECORDING new assets and REVIEWING existing ones,
// not for triggering depreciation directly.
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import { Asset, AssetPaymentMethod, assetsApi } from "@/lib/api/accounting";
import { Loader2, Plus, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

function RecordAssetModal({ onClose, onCreated }: { onClose: () => void; onCreated: (a: Asset) => void }) {
  const [name, setName] = useState("");
  const [acquisitionDate, setAcquisitionDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [cost, setCost] = useState("");
  const [usefulLifeMonths, setUsefulLifeMonths] = useState("");
  const [method, setMethod] = useState<AssetPaymentMethod>("cash");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // No salvage-value field, deliberately — Chris's own confirmed
  // call: Made doesn't estimate resale values for shop tools, v1
  // always assumes 0. Asking for one here would slow down exactly
  // the kind of fast, low-ceremony entry this system optimizes for
  // elsewhere (QuickPurchase, OperatingExpense).
  const monthlyPreview = cost && usefulLifeMonths && toNumber(usefulLifeMonths) > 0
    ? toNumber(cost) / toNumber(usefulLifeMonths)
    : null;

  const canSubmit = name.trim() && toNumber(cost || "0") > 0 && toNumber(usefulLifeMonths || "0") > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true); setError(null);
    const result = await assetsApi.record({
      name: name.trim(), acquisition_date: acquisitionDate,
      cost: toNumber(cost), useful_life_months: parseInt(usefulLifeMonths, 10), method,
    });
    setSaving(false);
    if (!result.success || !result.asset) {
      setError(result.message || "Gagal mencatat aset.");
      return;
    }
    onCreated(result.asset);
    onClose();
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 460, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Catat Aset Baru</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", display: "flex" }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          Penyusutan garis lurus, otomatis, mulai bulan setelah tanggal perolehan.
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Nama Aset</label>
            <input className="input" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="cth. Kompresor" />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label className="label">Tanggal Perolehan</label>
            <input className="input" type="date" required value={acquisitionDate} onChange={(e) => setAcquisitionDate(e.target.value)} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 6 }}>
            <div>
              <label className="label">Harga Perolehan (Rp)</label>
              <input className="input" type="number" min={0} required value={cost} onChange={(e) => setCost(e.target.value)} placeholder="0" />
            </div>
            <div>
              <label className="label">Umur Manfaat (Bulan)</label>
              <input className="input" type="number" min={1} required value={usefulLifeMonths} onChange={(e) => setUsefulLifeMonths(e.target.value)} placeholder="36" />
            </div>
          </div>
          {monthlyPreview !== null && (
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 16 }}>
              Penyusutan per bulan (perkiraan): <span className="mono" style={{ fontWeight: 600, color: "var(--ink)" }}>{formatRupiah(monthlyPreview)}</span>
            </div>
          )}

          <div style={{ marginBottom: 20 }}>
            <label className="label">Metode Pembayaran</label>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className={method === "cash" ? "btn-rust" : "btn-ghost"}
                style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
                onClick={() => setMethod("cash")}
              >
                Tunai
              </button>
              <button
                type="button"
                className={method === "bank" ? "btn-rust" : "btn-ghost"}
                style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
                onClick={() => setMethod("bank")}
              >
                Transfer Bank
              </button>
            </div>
          </div>

          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const load = () => {
    setLoading(true);
    assetsApi.list().then((res) => { setAssets(res ?? []); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const activeCount = assets.filter((a) => a.is_active).length;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Akuntansi</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            {activeCount} aset masih disusutkan · {assets.length} total tercatat
          </p>
        </div>
        <button className="btn-rust" onClick={() => setShowCreate(true)}><Plus size={16} /> Catat Aset</button>
      </div>

      <AccountingSubNav />

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Nomor</th><th>Nama</th><th>Tanggal Perolehan</th>
                <th>Harga Perolehan</th><th>Akumulasi Penyusutan</th><th>Nilai Buku</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id}>
                  <td className="mono" style={{ color: "var(--rust)", fontWeight: 600 }}>{a.number}</td>
                  <td>{a.name}</td>
                  <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(a.acquisition_date).toLocaleDateString("id-ID")}</td>
                  <td className="mono">{formatRupiah(a.cost)}</td>
                  <td className="mono" style={{ color: "var(--steel)" }}>{formatRupiah(a.accumulated_depreciation)}</td>
                  <td className="mono" style={{ fontWeight: 600 }}>{formatRupiah(a.book_value)}</td>
                  <td>
                    <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: a.is_active ? "#fff" : "var(--ink-soft)", background: a.is_active ? "#2e7d4f" : "var(--paper-3)", border: a.is_active ? "none" : "1px solid var(--line)" }}>
                      {a.is_active ? "Disusutkan" : "Lunas Susut"}
                    </span>
                  </td>
                </tr>
              ))}
              {assets.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada aset tercatat</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <RecordAssetModal
          onClose={() => setShowCreate(false)}
          onCreated={(a) => setAssets((prev) => [a, ...prev])}
        />
      )}
    </div>
  );
}
