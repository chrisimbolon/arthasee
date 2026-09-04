"use client";
// =============================================================================
// === frontend/components/onboarding/OnboardingOverlay.tsx ===
// 29 Aug 2026 — the real, un-skippable first-login welcome gate,
// Chris's own confirmed design. Rendered by dashboard/layout.tsx
// itself whenever organization.onboarding_completed is false —
// blocks every real dashboard page until a shop's setup is genuinely
// complete.
//
// 3 Sep 2026 — REDESIGNED into a real 2-step wizard, matching
// Sansan's own canonical onboarding doctrine (steps 01->02 of that
// document are exactly Step 1 below; the Opening Balance wizard is
// steps 02->04). Step 1 (profile) now saves via organizationsApi.
// update() — NOT completeOnboarding() — so a browser refresh
// between steps has real, persisted data to resume from: the
// component decides its own starting step by checking whether
// organization.phone/address are already saved, rather than tracking
// a separate "which step" flag anywhere. onboarding_completed itself
// only ever flips at the very end of Step 2, via one of its two real
// exit paths (a posted OpeningBalanceSession, or "Bengkel Baru" for
// a shop with no prior history to record).
//
// Receivable/Payable line entry uses a real, inline "pick or create"
// combobox for Customer/Supplier — the same established pattern
// already used elsewhere in this app (e.g. picking/adding a Customer
// while creating a Vehicle), not a new one invented for this wizard.
// customersApi.list() supports real server-side search;
// suppliersApi.list() does not (no search param at all), so
// SupplierPicker filters client-side instead — a deliberate, small
// asymmetry between the two pickers, not an oversight.
// =============================================================================
import {
  OpeningBalanceActionResult, OpeningBalanceOtherSide,
  OpeningBalanceSessionResponse, openingBalanceApi,
} from "@/lib/api/accounting";
import { Organization, organizationsApi } from "@/lib/api/organizations";
import { Supplier, suppliersApi } from "@/lib/api/purchasing";
import { Customer, customersApi } from "@/lib/api/service";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { FormEvent, ReactNode, useEffect, useState } from "react";

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function extractMessage(err: unknown, fallback: string): string {
  const data = (err as { response?: { data?: { message?: string; errors?: Record<string, string[]> } } })?.response?.data;
  const firstFieldError = data?.errors ? Object.values(data.errors)[0]?.[0] : undefined;
  return data?.message || firstFieldError || fallback;
}

// ── Shared small pieces ─────────────────────────────────────────

function Overlay({ width, children }: { width: number; children: ReactNode }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "var(--paper)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 20 }}>
      <div className="card" style={{ width, maxHeight: "90vh", overflowY: "auto" }}>
        {children}
      </div>
    </div>
  );
}

function StepBadge({ current }: { current: 1 | 2 }) {
  return (
    <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--rust)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10 }}>
      Langkah {current} dari 2
    </div>
  );
}

function ErrorBanner({ text }: { text: string }) {
  return (
    <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 18 }}>
      {text}
    </div>
  );
}

function SectionCard({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 16, marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 2 }}>{title}</div>
      <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 12 }}>{hint}</div>
      {children}
    </div>
  );
}

function LineRow({ label, sub, amount, onDelete }: { label: string; sub?: string; amount: number; onDelete?: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--line)", fontSize: 13 }}>
      <div>
        <div>{label}</div>
        {sub && <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{sub}</div>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="mono">{formatRupiah(amount)}</span>
        {onDelete && (
          <button type="button" onClick={onDelete} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--steel)", padding: 2, display: "flex" }} aria-label="Hapus">
            <Trash2 size={13} />
          </button>
        )}
      </div>
    </div>
  );
}

// ── Step 1 — profile ────────────────────────────────────────────

function ProfileStep({ organization, onDone }: { organization: Organization; onDone: () => void }) {
  const [phone, setPhone] = useState(organization.phone || "");
  const [address, setAddress] = useState(organization.address || "");
  const [invoiceCode, setInvoiceCode] = useState(organization.invoice_code);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = phone.trim() && address.trim() && invoiceCode.trim() && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true); setError(null);
    try {
      // Real update(), NOT completeOnboarding() — Step 1 only ever
      // SAVES the profile now; onboarding_completed only ever flips
      // at the very end of Step 2.
      await organizationsApi.update({
        phone: phone.trim(), address: address.trim(), invoice_code: invoiceCode.trim().toUpperCase(),
      });
      onDone();
    } catch (err) {
      setError(extractMessage(err, "Gagal menyimpan pengaturan awal."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Overlay width={480}>
      <StepBadge current={1} />
      <h1 className="display" style={{ fontSize: 24, marginBottom: 8, textTransform: "none" }}>
        Selamat Datang di Arthasee!
      </h1>
      <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 22, lineHeight: 1.5 }}>
        Lengkapi profil bengkel Anda dulu — data ini akan muncul di invoice dan dokumen resmi lainnya yang dilihat langsung oleh pelanggan.
      </p>

      {error && <ErrorBanner text={error} />}

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 16 }}>
          <label className="label">Nomor Telepon Bengkel</label>
          <input
            className="input" required autoFocus value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="cth. 0812-3456-7890"
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label className="label">Alamat Bengkel</label>
          <textarea
            className="input" required rows={3} value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="Alamat lengkap untuk ditampilkan di invoice"
            style={{ resize: "vertical", fontFamily: "inherit" }}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <label className="label">Kode Invoice</label>
          <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 8, lineHeight: 1.5 }}>
            Kami membuatkan <strong className="mono">&ldquo;{organization.invoice_code}&rdquo;</strong> untuk Anda dari nama bengkel — cocok, atau ingin diubah?
          </p>
          <input
            className="input mono" required value={invoiceCode}
            onChange={(e) => setInvoiceCode(e.target.value.toUpperCase())}
            maxLength={10}
            style={{ textTransform: "uppercase" }}
          />
        </div>

        <button className="btn-rust" type="submit" disabled={!canSubmit} style={{ width: "100%", justifyContent: "center" }}>
          {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Lanjut ke Saldo Awal →"}
        </button>
      </form>
    </Overlay>
  );
}

// ── Step 2 — Opening Balance ────────────────────────────────────

type SectionProps = {
  session: OpeningBalanceSessionResponse;
  onChange: () => void;
  setError: (e: string | null) => void;
};

function CashSection({ session, onChange, setError }: SectionProps) {
  const [accountCode, setAccountCode] = useState<"1001" | "1101">("1001");
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!amount.trim()) return;
    setSaving(true); setError(null);
    const result = await openingBalanceApi.upsertCash({ account_code: accountCode, amount });
    setSaving(false);
    if (!result.success) { setError(result.message || null); return; }
    setAmount("");
    onChange();
  };

  return (
    <SectionCard title="Kas & Bank" hint="Uang tunai dan saldo rekening bank saat ini.">
      {session.cash_lines.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {session.cash_lines.map((l) => (
            <LineRow key={l.id} label={l.account_code === "1001" ? "Kas" : "Bank"} amount={toNumber(l.amount)} />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <select className="input" value={accountCode} onChange={(e) => setAccountCode(e.target.value as "1001" | "1101")} style={{ width: 100 }}>
          <option value="1001">Kas</option>
          <option value="1101">Bank</option>
        </select>
        <input className="input" placeholder="Jumlah (Rp)" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ flex: 1 }} />
        <button type="button" className="btn-ghost" onClick={handleSave} disabled={saving || !amount.trim()}>
          {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
        </button>
      </div>
    </SectionCard>
  );
}

function PartSection({ session, onChange, setError }: SectionProps) {
  const [partName, setPartName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [costPrice, setCostPrice] = useState("");
  const [saving, setSaving] = useState(false);

  const canAdd = partName.trim() && quantity.trim() && costPrice.trim();

  const handleAdd = async () => {
    if (!canAdd) return;
    setSaving(true); setError(null);
    const result = await openingBalanceApi.addPart({ part_name: partName.trim(), quantity, cost_price: costPrice });
    setSaving(false);
    if (!result.success) { setError(result.message || null); return; }
    setPartName(""); setQuantity(""); setCostPrice("");
    onChange();
  };

  const handleDelete = async (id: string) => {
    setError(null);
    const result = await openingBalanceApi.deletePart(id);
    if (!result.success) { setError(result.message || null); return; }
    onChange();
  };

  return (
    <SectionCard title="Stok Sparepart" hint="Sparepart yang sudah ada di rak sebelum pakai Arthasee.">
      {session.part_lines.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {session.part_lines.map((l) => (
            <LineRow
              key={l.id} label={l.part_name} sub={`${l.quantity} ${l.unit} × ${formatRupiah(l.cost_price)}`}
              amount={toNumber(l.quantity) * toNumber(l.cost_price)}
              onDelete={() => handleDelete(l.id)}
            />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="input" placeholder="Nama part" value={partName} onChange={(e) => setPartName(e.target.value)} style={{ flex: "2 1 140px" }} />
        <input className="input" placeholder="Jumlah" value={quantity} onChange={(e) => setQuantity(e.target.value)} style={{ width: 80 }} />
        <input className="input" placeholder="Harga pokok/pcs" value={costPrice} onChange={(e) => setCostPrice(e.target.value)} style={{ width: 140 }} />
        <button type="button" className="btn-ghost" onClick={handleAdd} disabled={saving || !canAdd} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={14} />}
        </button>
      </div>
    </SectionCard>
  );
}

function AssetSection({ session, onChange, setError }: SectionProps) {
  const [name, setName] = useState("");
  const [bookValue, setBookValue] = useState("");
  const [remainingMonths, setRemainingMonths] = useState("");
  const [saving, setSaving] = useState(false);

  const canAdd = name.trim() && bookValue.trim() && remainingMonths.trim();

  const handleAdd = async () => {
    if (!canAdd) return;
    setSaving(true); setError(null);
    const result = await openingBalanceApi.addAsset({
      name: name.trim(), current_book_value: bookValue, remaining_useful_life_months: parseInt(remainingMonths, 10),
    });
    setSaving(false);
    if (!result.success) { setError(result.message || null); return; }
    setName(""); setBookValue(""); setRemainingMonths("");
    onChange();
  };

  const handleDelete = async (id: string) => {
    setError(null);
    const result = await openingBalanceApi.deleteAsset(id);
    if (!result.success) { setError(result.message || null); return; }
    onChange();
  };

  return (
    <SectionCard title="Aset Tetap" hint="Peralatan bengkel yang sudah dimiliki — masukkan nilai buku SAAT INI, bukan harga beli aslinya.">
      {session.asset_lines.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {session.asset_lines.map((l) => (
            <LineRow
              key={l.id} label={l.name} sub={`Sisa ${l.remaining_useful_life_months} bulan`}
              amount={toNumber(l.current_book_value)}
              onDelete={() => handleDelete(l.id)}
            />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="input" placeholder="Nama aset" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: "2 1 140px" }} />
        <input className="input" placeholder="Nilai buku saat ini (Rp)" value={bookValue} onChange={(e) => setBookValue(e.target.value)} style={{ width: 170 }} />
        <input className="input" placeholder="Sisa umur (bulan)" value={remainingMonths} onChange={(e) => setRemainingMonths(e.target.value)} style={{ width: 130 }} />
        <button type="button" className="btn-ghost" onClick={handleAdd} disabled={saving || !canAdd} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={14} />}
        </button>
      </div>
    </SectionCard>
  );
}

function OtherSection({ session, onChange, setError }: SectionProps) {
  const [accountCode, setAccountCode] = useState("3001");
  const [side, setSide] = useState<OpeningBalanceOtherSide>("credit");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const canAdd = accountCode.trim() && amount.trim();

  const handleAdd = async () => {
    if (!canAdd) return;
    setSaving(true); setError(null);
    const result = await openingBalanceApi.addOther({
      account_code: accountCode.trim(), side, amount, description: description.trim(),
    });
    setSaving(false);
    if (!result.success) { setError(result.message || null); return; }
    setAmount(""); setDescription("");
    onChange();
  };

  const handleDelete = async (id: string) => {
    setError(null);
    const result = await openingBalanceApi.deleteOther(id);
    if (!result.success) { setError(result.message || null); return; }
    onChange();
  };

  return (
    <SectionCard title="Lainnya" hint="Modal pemilik, pinjaman, pajak terutang, atau akun lain yang tidak masuk kategori di atas — masukkan kode akunnya langsung. Modal Pemilik (3001) biasanya jadi penyeimbang akhir.">
      {session.other_lines.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {session.other_lines.map((l) => (
            <LineRow
              key={l.id} label={l.account_name || l.account_code} sub={l.description || undefined}
              amount={toNumber(l.amount)}
              onDelete={() => handleDelete(l.id)}
            />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="input mono" placeholder="Kode akun (cth. 3001)" value={accountCode} onChange={(e) => setAccountCode(e.target.value)} style={{ width: 130 }} />
        <select className="input" value={side} onChange={(e) => setSide(e.target.value as OpeningBalanceOtherSide)} style={{ width: 100 }}>
          <option value="credit">Kredit</option>
          <option value="debit">Debit</option>
        </select>
        <input className="input" placeholder="Jumlah (Rp)" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 130 }} />
        <input className="input" placeholder="Keterangan (opsional)" value={description} onChange={(e) => setDescription(e.target.value)} style={{ flex: "1 1 140px" }} />
        <button type="button" className="btn-ghost" onClick={handleAdd} disabled={saving || !canAdd} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={14} />}
        </button>
      </div>
    </SectionCard>
  );
}

// ── Customer / Supplier pickers — inline pick-or-create ─────────

function CustomerPicker({ value, onChange }: { value: Customer | null; onChange: (c: Customer | null) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Customer[]>([]);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open || !query.trim()) { setResults([]); return; }
    let cancelled = false;
    customersApi.list({ search: query.trim() })
      .then((rows) => { if (!cancelled) setResults(rows); })
      .catch(() => { if (!cancelled) setResults([]); });
    return () => { cancelled = true; };
  }, [query, open]);

  if (value) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div className="input" style={{ flex: 1, display: "flex", alignItems: "center" }}>{value.name}</div>
        <button type="button" className="btn-ghost" onClick={() => onChange(null)}>Ganti</button>
      </div>
    );
  }

  const exactMatch = results.some((c) => c.name.toLowerCase() === query.trim().toLowerCase());

  const handleCreate = async () => {
    if (!query.trim()) return;
    setCreating(true);
    try {
      const customer = await customersApi.create({ name: query.trim() });
      onChange(customer);
    } finally {
      setCreating(false);
      setOpen(false);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <input
        className="input" placeholder="Cari atau tambah pelanggan..." value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && query.trim() && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 6, marginTop: 4, maxHeight: 180, overflowY: "auto", zIndex: 10, boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
          {results.map((c) => (
            <div
              key={c.id} onMouseDown={() => { onChange(c); setOpen(false); }}
              style={{ padding: "8px 10px", cursor: "pointer", fontSize: 13 }}
            >
              {c.name}
            </div>
          ))}
          {!exactMatch && (
            <div
              onMouseDown={handleCreate}
              style={{ padding: "8px 10px", cursor: "pointer", fontSize: 13, color: "var(--rust)", borderTop: results.length ? "1px solid var(--line)" : "none" }}
            >
              {creating ? "Menyimpan..." : `+ Tambah pelanggan baru: "${query.trim()}"`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SupplierPicker({ value, onChange }: { value: Supplier | null; onChange: (s: Supplier | null) => void }) {
  const [query, setQuery] = useState("");
  const [all, setAll] = useState<Supplier[] | null>(null);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    // suppliersApi.list() has no search param — fetched once,
    // filtered client-side below, unlike CustomerPicker's own real
    // server-side search.
    if (open && all === null) {
      suppliersApi.list().then(setAll).catch(() => setAll([]));
    }
  }, [open, all]);

  if (value) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div className="input" style={{ flex: 1, display: "flex", alignItems: "center" }}>{value.name}</div>
        <button type="button" className="btn-ghost" onClick={() => onChange(null)}>Ganti</button>
      </div>
    );
  }

  const results = (all || []).filter((s) => s.name.toLowerCase().includes(query.trim().toLowerCase()));
  const exactMatch = results.some((s) => s.name.toLowerCase() === query.trim().toLowerCase());

  const handleCreate = async () => {
    if (!query.trim()) return;
    setCreating(true);
    try {
      const supplier = await suppliersApi.create({ name: query.trim() });
      onChange(supplier);
    } finally {
      setCreating(false);
      setOpen(false);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <input
        className="input" placeholder="Cari atau tambah supplier..." value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && query.trim() && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 6, marginTop: 4, maxHeight: 180, overflowY: "auto", zIndex: 10, boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
          {results.map((s) => (
            <div
              key={s.id} onMouseDown={() => { onChange(s); setOpen(false); }}
              style={{ padding: "8px 10px", cursor: "pointer", fontSize: 13 }}
            >
              {s.name}
            </div>
          ))}
          {!exactMatch && (
            <div
              onMouseDown={handleCreate}
              style={{ padding: "8px 10px", cursor: "pointer", fontSize: 13, color: "var(--rust)", borderTop: results.length ? "1px solid var(--line)" : "none" }}
            >
              {creating ? "Menyimpan..." : `+ Tambah supplier baru: "${query.trim()}"`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReceivableSection({ session, onChange, setError }: SectionProps) {
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [balanceDue, setBalanceDue] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [saving, setSaving] = useState(false);

  const canAdd = customer && balanceDue.trim();

  const handleAdd = async () => {
    if (!customer || !balanceDue.trim()) return;
    setSaving(true); setError(null);
    const result = await openingBalanceApi.addReceivable({
      customer: customer.id, balance_due: balanceDue, due_date: dueDate || undefined,
    });
    setSaving(false);
    if (!result.success) { setError(result.message || null); return; }
    setCustomer(null); setBalanceDue(""); setDueDate("");
    onChange();
  };

  const handleDelete = async (id: string) => {
    setError(null);
    const result = await openingBalanceApi.deleteReceivable(id);
    if (!result.success) { setError(result.message || null); return; }
    onChange();
  };

  return (
    <SectionCard title="Piutang Pelanggan" hint="Tagihan pelanggan yang belum lunas dari sebelum pakai Arthasee.">
      {session.receivable_lines.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {session.receivable_lines.map((l) => (
            <LineRow key={l.id} label={l.customer_name} sub={l.reference || undefined} amount={toNumber(l.balance_due)} onDelete={() => handleDelete(l.id)} />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: "2 1 180px" }}>
          <CustomerPicker value={customer} onChange={setCustomer} />
        </div>
        <input className="input" placeholder="Jumlah (Rp)" value={balanceDue} onChange={(e) => setBalanceDue(e.target.value)} style={{ width: 130 }} />
        <input type="date" className="input" value={dueDate} onChange={(e) => setDueDate(e.target.value)} style={{ width: 140 }} title="Jatuh tempo (opsional)" />
        <button type="button" className="btn-ghost" onClick={handleAdd} disabled={saving || !canAdd} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={14} />}
        </button>
      </div>
    </SectionCard>
  );
}

function PayableSection({ session, onChange, setError }: SectionProps) {
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [balanceDue, setBalanceDue] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [saving, setSaving] = useState(false);

  const canAdd = supplier && balanceDue.trim();

  const handleAdd = async () => {
    if (!supplier || !balanceDue.trim()) return;
    setSaving(true); setError(null);
    const result = await openingBalanceApi.addPayable({
      supplier: supplier.id, balance_due: balanceDue, due_date: dueDate || undefined,
    });
    setSaving(false);
    if (!result.success) { setError(result.message || null); return; }
    setSupplier(null); setBalanceDue(""); setDueDate("");
    onChange();
  };

  const handleDelete = async (id: string) => {
    setError(null);
    const result = await openingBalanceApi.deletePayable(id);
    if (!result.success) { setError(result.message || null); return; }
    onChange();
  };

  return (
    <SectionCard title="Utang Supplier" hint="Tagihan dari supplier yang belum dibayar dari sebelum pakai Arthasee.">
      {session.payable_lines.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {session.payable_lines.map((l) => (
            <LineRow key={l.id} label={l.supplier_name} sub={l.reference || undefined} amount={toNumber(l.balance_due)} onDelete={() => handleDelete(l.id)} />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: "2 1 180px" }}>
          <SupplierPicker value={supplier} onChange={setSupplier} />
        </div>
        <input className="input" placeholder="Jumlah (Rp)" value={balanceDue} onChange={(e) => setBalanceDue(e.target.value)} style={{ width: 130 }} />
        <input type="date" className="input" value={dueDate} onChange={(e) => setDueDate(e.target.value)} style={{ width: 140 }} title="Jatuh tempo (opsional)" />
        <button type="button" className="btn-ghost" onClick={handleAdd} disabled={saving || !canAdd} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={14} />}
        </button>
      </div>
    </SectionCard>
  );
}

function OpeningBalanceStep({ onComplete }: { onComplete: () => void }) {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<OpeningBalanceSessionResponse | null>(null);
  const [startDate, setStartDate] = useState(todayISO());
  const [creating, setCreating] = useState(false);
  const [posting, setPosting] = useState(false);
  const [goingFresh, setGoingFresh] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    openingBalanceApi.getSession().then((s) => {
      setSession(s);
      setLoading(false);
    });
  }, []);

  const refresh = async () => {
    const s = await openingBalanceApi.getSession();
    setSession(s);
  };

  const finishOnboarding = async () => {
    try {
      await organizationsApi.completeOnboarding();
      onComplete();
      return true;
    } catch (err) {
      setError(extractMessage(err, "Gagal menyelesaikan pengaturan awal."));
      return false;
    }
  };

  const handleFreshStart = async () => {
    setGoingFresh(true); setError(null);
    const ok = await finishOnboarding();
    if (!ok) setGoingFresh(false);
  };

  const handleCreateSession = async () => {
    setCreating(true); setError(null);
    const result = await openingBalanceApi.createSession({ start_date: startDate });
    setCreating(false);
    if (!result.success || !result.opening_balance_session) {
      setError(result.message || "Gagal membuat sesi saldo awal.");
      return;
    }
    setSession(result.opening_balance_session);
  };

  const handlePost = async () => {
    setPosting(true); setError(null);
    const result: OpeningBalanceActionResult = await openingBalanceApi.post();
    if (!result.success) {
      setError(result.message || "Gagal memposting saldo awal.");
      setPosting(false);
      return;
    }
    const ok = await finishOnboarding();
    if (!ok) setPosting(false);
  };

  if (loading) {
    return (
      <Overlay width={480}>
        <div style={{ display: "flex", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      </Overlay>
    );
  }

  // No session yet — the real choice point: a brand-new shop with
  // nothing to record, or one that wants to enter real prior
  // history. See this file's own module docstring for why
  // "Bengkel Baru" is a permanent escape hatch, not just a pre-
  // session option — it stays available even after a session has
  // been started, since starting one and later deciding you have
  // nothing to add is a real, normal path too.
  if (!session) {
    return (
      <Overlay width={520}>
        <StepBadge current={2} />
        <h1 className="display" style={{ fontSize: 24, marginBottom: 8, textTransform: "none" }}>
          Saldo Awal Bengkel
        </h1>
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 22, lineHeight: 1.5 }}>
          Punya kas, stok, atau aset dari sebelum pakai Arthasee? Catat di sini supaya laporan keuangan Anda akurat sejak hari pertama.
        </p>

        {error && <ErrorBanner text={error} />}

        <div style={{ marginBottom: 20 }}>
          <label className="label">Tanggal Mulai Akuntansi</label>
          <input type="date" className="input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </div>

        <button
          type="button" className="btn-rust" onClick={handleCreateSession} disabled={creating}
          style={{ width: "100%", justifyContent: "center", marginBottom: 12 }}
        >
          {creating ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Isi Saldo Awal"}
        </button>
        <button
          type="button" className="btn-ghost" onClick={handleFreshStart} disabled={goingFresh}
          style={{ width: "100%", justifyContent: "center" }}
        >
          {goingFresh ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Bengkel Baru — Tidak Ada Saldo Awal"}
        </button>
      </Overlay>
    );
  }

  const totalDebit = toNumber(session.total_debit);
  const totalCredit = toNumber(session.total_credit);
  const hasContent = totalDebit > 0 || totalCredit > 0;
  const canPost = session.is_balanced && hasContent && !posting;

  return (
    <Overlay width={760}>
      <StepBadge current={2} />
      <h1 className="display" style={{ fontSize: 24, marginBottom: 4, textTransform: "none" }}>
        Saldo Awal Bengkel
      </h1>
      <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
        Tanggal mulai: {new Date(session.start_date).toLocaleDateString("id-ID")}
      </p>

      {error && <ErrorBanner text={error} />}

      <div style={{ display: "flex", gap: 20, alignItems: "center", padding: "14px 16px", borderRadius: 8, background: "var(--paper-3)", marginBottom: 20 }}>
        <div>
          <div className="label">Total Debit</div>
          <div className="mono" style={{ fontSize: 17, fontWeight: 700 }}>{formatRupiah(totalDebit)}</div>
        </div>
        <div>
          <div className="label">Total Kredit</div>
          <div className="mono" style={{ fontSize: 17, fontWeight: 700 }}>{formatRupiah(totalCredit)}</div>
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div className="label">Status</div>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: !hasContent ? "var(--steel)" : session.is_balanced ? "var(--workshop)" : "var(--danger)" }}>
            {!hasContent ? "Belum ada data" : session.is_balanced ? "✓ Seimbang" : `Selisih ${formatRupiah(Math.abs(toNumber(session.difference)))}`}
          </div>
        </div>
      </div>

      <CashSection session={session} onChange={refresh} setError={setError} />
      <PartSection session={session} onChange={refresh} setError={setError} />
      <AssetSection session={session} onChange={refresh} setError={setError} />
      <ReceivableSection session={session} onChange={refresh} setError={setError} />
      <PayableSection session={session} onChange={refresh} setError={setError} />
      <OtherSection session={session} onChange={refresh} setError={setError} />

      <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
        <button
          type="button" className="btn-ghost" onClick={handleFreshStart} disabled={goingFresh || posting}
          style={{ flex: 1, justifyContent: "center" }}
        >
          {goingFresh ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Batal — Bengkel Baru Saja"}
        </button>
        <button
          type="button" className="btn-rust" onClick={handlePost} disabled={!canPost}
          style={{ flex: 2, justifyContent: "center" }}
        >
          {posting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Posting & Selesai"}
        </button>
      </div>
    </Overlay>
  );
}

// ── Root ─────────────────────────────────────────────────────────

export default function OnboardingOverlay({
  organization, onComplete,
}: {
  organization: Organization;
  onComplete: () => void;
}) {
  // Real resume logic — the fix for the mid-Step-2-refresh gap found
  // during the architecture review: if the profile is already saved
  // (Step 1 genuinely happened, even in an earlier, interrupted
  // session), skip straight to Step 2 rather than re-showing Step 1
  // from scratch.
  const [step, setStep] = useState<"profile" | "opening_balance">(
    organization.phone && organization.address ? "opening_balance" : "profile",
  );

  if (step === "profile") {
    return <ProfileStep organization={organization} onDone={() => setStep("opening_balance")} />;
  }
  return <OpeningBalanceStep onComplete={onComplete} />;
}
