"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/tax-remittances/page.tsx ===
// 9 Oct 2026 — "Setoran Pajak Bulanan": PPh 23 self-remit (gross-up,
// for individual/OP customers who didn't withhold at payment) + PPh
// Final UMKM (PP 55/2022, 0.5% of sparepart/parts revenue). Scoped
// and designed with Chris, grounded in Pak Holan's real, confirmed
// answers — see the "PPh23 Questions for Pak Holan" doc.
//
// Decision #2 (9 Oct 2026, with Chris): deliberately NOT automatic —
// this page shows a SUGGESTED amount per tax per month, and the
// owner/accountant must explicitly confirm (and may edit the amount)
// before anything is actually recorded via POST /api/tax-remittances/.
//
// Month picker reuses the real AccountingPeriod rows every other
// accounting page already works with (accountingApi.periods()), not
// a freeform date input — a month that was never opened as a real
// period can't have a tax obligation recorded against it anyway
// (TaxRemittance.record() calls the same AccountingPeriod.assert_
// open_for_posting() guard every other real posting in this system
// goes through).
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import { accountingApi, AccountingPeriod } from "@/lib/api/accounting";
import {
  RecordTaxRemittancePayload, TaxRemittance, TaxRemittanceMethod,
  TaxType, taxRemittancesApi,
} from "@/lib/api/payments";
import { Loader2 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

const MONTH_NAMES_ID = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

function periodLabel(p: AccountingPeriod): string {
  return `${MONTH_NAMES_ID[p.month - 1]} ${p.year}`;
}

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRupiah(value: string | number): string {
  const n = typeof value === "string" ? toNumber(value) : value;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
}

const TAX_TYPE_LABEL: Record<TaxType, string> = {
  pph23_self_remit: "PPh 23 Disetor Sendiri",
  pph_umkm_final:   "PPh Final UMKM (PP 55/2022)",
};
const TAX_TYPE_DESCRIPTION: Record<TaxType, string> = {
  pph23_self_remit:
    "Gross-up PPh 23 untuk pelanggan perorangan/OP yang tidak memotong saat bayar — 2% dari porsi jasa pembayaran bulan ini.",
  pph_umkm_final:
    "PPh Final UMKM (PP 55/2022) — 0,5% dari total pendapatan sparepart bulan ini, berlaku untuk semua pelanggan.",
};

// Confirm-and-record modal — shared between both tax cards,
// parametrized by which tax/period it's recording for. Mirrors
// CreateExpenseModal's own shape (operating-expenses/page.tsx):
// prefilled from a suggestion, but always editable before saving —
// Decision #2 means this is never a one-click "accept" action.
function RecordRemittanceModal({
  taxType, periodYear, periodMonth, suggestedAmount, onClose, onRecorded,
}: {
  taxType: TaxType; periodYear: number; periodMonth: number; suggestedAmount: string;
  onClose: () => void; onRecorded: (r: TaxRemittance) => void;
}) {
  const [amount, setAmount] = useState(suggestedAmount);
  const [method, setMethod] = useState<TaxRemittanceMethod>("bank");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = toNumber(amount) > 0 && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    const payload: RecordTaxRemittancePayload = {
      tax_type: taxType, period_year: periodYear, period_month: periodMonth,
      amount: toNumber(amount), method,
      reference: reference || undefined, notes: notes || undefined,
    };
    const result = await taxRemittancesApi.record(payload);
    setSaving(false);
    if (!result.success || !result.tax_remittance) {
      setError(result.message || "Gagal mencatat setoran pajak.");
      return;
    }
    onRecorded(result.tax_remittance);
    onClose();
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }}>
      <div className="card" style={{ width: 460, maxHeight: "85vh", overflowY: "auto", background: "var(--paper-3)" }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Catat Setoran — {TAX_TYPE_LABEL[taxType]}</h2>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          {MONTH_NAMES_ID[periodMonth - 1]} {periodYear} — jumlah di bawah adalah SARAN, cek dan ubah jika perlu sebelum disimpan.
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Jumlah (Rp)</label>
            <input className="input" type="number" min={0} step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label className="label">Metode Pembayaran</label>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className={method === "bank" ? "btn-rust" : "btn-ghost"} style={{ flex: 1, justifyContent: "center", fontSize: 13 }} onClick={() => setMethod("bank")}>Transfer Bank</button>
              <button type="button" className={method === "cash" ? "btn-rust" : "btn-ghost"} style={{ flex: 1, justifyContent: "center", fontSize: 13 }} onClick={() => setMethod("cash")}>Tunai</button>
            </div>
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Referensi <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="No. NTPN/bukti setor" />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Catatan <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
          </button>
        </form>
      </div>
    </div>
  );
}

function TaxCard({
  taxType, period, remittance, onRecorded,
}: {
  taxType: TaxType; period: AccountingPeriod; remittance: TaxRemittance | undefined;
  onRecorded: (r: TaxRemittance) => void;
}) {
  const [suggested, setSuggested] = useState<string | null>(null);
  const [loadingSuggestion, setLoadingSuggestion] = useState(!remittance);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (remittance) { setLoadingSuggestion(false); return; }
    setLoadingSuggestion(true);
    taxRemittancesApi.suggested(taxType, period.year, period.month)
      .then(setSuggested)
      .finally(() => setLoadingSuggestion(false));
  }, [taxType, period.year, period.month, remittance]);

  return (
    <div className="card" style={{ flex: 1 }}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{TAX_TYPE_LABEL[taxType]}</div>
      <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14, lineHeight: 1.5 }}>{TAX_TYPE_DESCRIPTION[taxType]}</p>

      {remittance ? (
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#2e7d4f" }}>{formatRupiah(remittance.amount)}</div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>
            Sudah dicatat — {remittance.number} ({new Date(remittance.paid_at).toLocaleDateString("id-ID")})
          </div>
        </div>
      ) : loadingSuggestion ? (
        <div style={{ color: "var(--steel)", display: "flex", alignItems: "center", gap: 6 }}>
          <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Menghitung saran…
        </div>
      ) : (
        <div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 2 }}>Saran jumlah</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{formatRupiah(suggested || "0")}</div>
          <button className="btn-rust" style={{ marginTop: 12 }} onClick={() => setShowModal(true)}>
            Catat Setoran
          </button>
        </div>
      )}

      {showModal && (
        <RecordRemittanceModal
          taxType={taxType} periodYear={period.year} periodMonth={period.month}
          suggestedAmount={suggested || "0"}
          onClose={() => setShowModal(false)}
          onRecorded={onRecorded}
        />
      )}
    </div>
  );
}

export default function TaxRemittancesPage() {
  const [periods, setPeriods] = useState<AccountingPeriod[] | null>(null);
  const [selectedPeriodId, setSelectedPeriodId] = useState<string>("");
  const [remittances, setRemittances] = useState<TaxRemittance[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([accountingApi.periods(), taxRemittancesApi.list()]).then(([periodsRes, remits]) => {
      const list = periodsRes ?? [];
      setPeriods(list);
      // Defaults to the most recently STARTED period that's already
      // open for posting (i.e. not a far-future auto-opened one) —
      // falls back to the newest period in the list either way, same
      // "never leave the picker genuinely empty" discipline every
      // other period-aware page in this app already follows.
      const sorted = [...list].sort((a, b) => (a.year * 12 + a.month) - (b.year * 12 + b.month));
      const today = new Date();
      const current = sorted.filter((p) => p.year * 12 + p.month <= today.getFullYear() * 12 + (today.getMonth() + 1));
      const defaultPeriod = current[current.length - 1] ?? sorted[sorted.length - 1];
      if (defaultPeriod) setSelectedPeriodId(defaultPeriod.id);
      setRemittances(remits);
      setLoading(false);
    });
  }, []);

  const selectedPeriod = useMemo(
    () => (periods ?? []).find((p) => p.id === selectedPeriodId) ?? null,
    [periods, selectedPeriodId],
  );

  const remittanceFor = (taxType: TaxType): TaxRemittance | undefined => {
    if (!selectedPeriod) return undefined;
    return remittances.find(
      (r) => r.tax_type === taxType && r.period_year === selectedPeriod.year && r.period_month === selectedPeriod.month,
    );
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Akuntansi</h1>
          <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>Setoran Pajak Bulanan — PPh 23 &amp; PPh Final UMKM</p>
        </div>
      </div>

      <AccountingSubNav />

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : (
        <>
          <div style={{ marginBottom: 18, maxWidth: 260 }}>
            <label className="label">Periode</label>
            <select className="input" value={selectedPeriodId} onChange={(e) => setSelectedPeriodId(e.target.value)}>
              {(periods ?? []).map((p) => (
                <option key={p.id} value={p.id}>{periodLabel(p)}</option>
              ))}
            </select>
          </div>

          {selectedPeriod ? (
            <div style={{ display: "flex", gap: 16, marginBottom: 28 }}>
              <TaxCard
                taxType="pph23_self_remit" period={selectedPeriod}
                remittance={remittanceFor("pph23_self_remit")}
                onRecorded={(r) => setRemittances((prev) => [r, ...prev])}
              />
              <TaxCard
                taxType="pph_umkm_final" period={selectedPeriod}
                remittance={remittanceFor("pph_umkm_final")}
                onRecorded={(r) => setRemittances((prev) => [r, ...prev])}
              />
            </div>
          ) : (
            <div className="card" style={{ marginBottom: 28, color: "var(--steel)", textAlign: "center", padding: 32 }}>
              Belum ada periode akuntansi — buka bulan berjalan terlebih dahulu.
            </div>
          )}

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="data-table">
              <thead>
                <tr><th>Nomor</th><th>Jenis Pajak</th><th>Periode</th><th>Metode</th><th>Tanggal</th><th>Jumlah</th></tr>
              </thead>
              <tbody>
                {remittances.map((r) => (
                  <tr key={r.id}>
                    <td className="mono" style={{ color: "var(--rust)", fontWeight: 600 }}>{r.number}</td>
                    <td>{r.tax_type_display}</td>
                    <td style={{ fontSize: 13, color: "var(--steel)" }}>{MONTH_NAMES_ID[r.period_month - 1]} {r.period_year}</td>
                    <td style={{ fontSize: 13, color: "var(--steel)" }}>{r.method === "cash" ? "Tunai" : "Transfer Bank"}</td>
                    <td style={{ fontSize: 13, color: "var(--steel)" }}>{new Date(r.paid_at).toLocaleDateString("id-ID")}</td>
                    <td className="mono">{formatRupiah(r.amount)}</td>
                  </tr>
                ))}
                {remittances.length === 0 && (
                  <tr><td colSpan={6} style={{ textAlign: "center", padding: 32, color: "var(--steel)" }}>Belum ada setoran pajak tercatat</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
