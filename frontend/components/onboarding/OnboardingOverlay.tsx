"use client";
// =============================================================================
// === frontend/components/onboarding/OnboardingOverlay.tsx ===
// 29 Aug 2026 — the real, un-skippable first-login welcome gate,
// Chris's own confirmed design. Rendered by dashboard/layout.tsx
// itself whenever organization.onboarding_completed is false —
// blocks every real dashboard page until a shop's profile is
// genuinely complete (phone, address, and a confirmed invoice
// prefix), since an invoice printing without those looks
// unprofessional the moment real customers see it.
// =============================================================================
import { CompleteOnboardingPayload, Organization, organizationsApi } from "@/lib/api/organizations";
import { Loader2 } from "lucide-react";
import { FormEvent, useState } from "react";

export default function OnboardingOverlay({
  organization, onComplete,
}: {
  organization: Organization;
  onComplete: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  // Pre-filled with the real, already-generated code —
  // Organization._generate_invoice_code() already ran at signup —
  // Chris's own confirmed UX: "We generated '{code}' for you — look
  // good, or want to change it?" The owner reviews and confirms/
  // overrides, rather than starting from a blank field.
  const [invoiceCode, setInvoiceCode] = useState(organization.invoice_code);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = phone.trim() && address.trim() && invoiceCode.trim() && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true); setError(null);
    try {
      const payload: CompleteOnboardingPayload = {
        phone: phone.trim(), address: address.trim(), invoice_code: invoiceCode.trim().toUpperCase(),
      };
      await organizationsApi.completeOnboarding(payload);
      onComplete();
    } catch (err) {
      const data = (err as { response?: { data?: { message?: string; errors?: Record<string, string[]> } } })?.response?.data;
      const firstFieldError = data?.errors ? Object.values(data.errors)[0]?.[0] : undefined;
      setError(data?.message || firstFieldError || "Gagal menyimpan pengaturan awal.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "var(--paper)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 20 }}>
      <div className="card" style={{ width: 480, maxHeight: "90vh", overflowY: "auto" }}>
        <h1 className="display" style={{ fontSize: 24, marginBottom: 8, textTransform: "none" }}>
          Selamat Datang di Arthasee!
        </h1>
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 22, lineHeight: 1.5 }}>
          Lengkapi profil bengkel Anda dulu — data ini akan muncul di invoice dan dokumen resmi lainnya yang dilihat langsung oleh pelanggan.
        </p>

        {error && (
          <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 18 }}>
            {error}
          </div>
        )}

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
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Mulai Gunakan Arthasee"}
          </button>
        </form>
      </div>
    </div>
  );
}
