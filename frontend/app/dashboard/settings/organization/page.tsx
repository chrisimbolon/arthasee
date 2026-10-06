"use client";
// =============================================================================
// === frontend/app/dashboard/settings/organization/page.tsx ===
// =============================================================================
// Chris's own explicit call, 5 Aug: registration stays completely
// frictionless (name, email, password, shop name only) — invoice_code
// never appears on the signup form. A real fallback gets
// auto-generated from the shop's own name at creation time instead
// (see Organization._generate_invoice_code() on the backend) — this
// page is where an owner customizes it whenever they actually want
// to, not a required setup step blocking anything.
import { Organization, organizationsApi } from "@/lib/api/organizations";
import { AlertTriangle, Check, Loader2, Save, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

// 6 Oct 2026 — Organization Logo. Same allowlist OrganizationLogoView
// enforces server-side (views.py) — narrowing the file picker here is
// a real UX courtesy, not the actual enforcement, which stays
// entirely server-side.
const LOGO_ACCEPT = "image/png,image/jpeg,image/webp";
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

export default function OrganizationSettingsPage() {
  const [org, setOrg] = useState<Organization | null>(null);
  // 29 Aug 2026 — phone/address added, same "everything gathered at
  // onboarding stays editable in Settings afterward" philosophy
  // already established for invoice_code above.
  //
  // 9 Sep 2026 — Phase 18, Task 18.6. requires_sequential_period_
  // closing added — defaults true here purely as a sane placeholder
  // before the real fetched value loads below (matches the backend's
  // own default=True) — never actually saved at this initial value,
  // since the form is fully repopulated from the real org the moment
  // mine() resolves.
  const [form, setForm] = useState({
    name: "", invoice_code: "", phone: "", address: "",
    requires_sequential_period_closing: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Real role check already lives on the backend (owner-only PATCH)
  // — this is just the proactive layer, same discipline as every
  // other gate in this app: disable the action, don't just let a
  // non-owner submit and discover the 403 after the fact.
  const [isOwner, setIsOwner] = useState(true);
  // 6 Oct 2026 — Organization Logo. Its own independent loading/error
  // state, deliberately separate from the rest of the form's saving/
  // saved/error above — uploading or removing a logo is its own
  // action with its own request, not bundled into handleSave().
  const [logoUploading, setLogoUploading] = useState(false);
  const [logoError, setLogoError] = useState<string | null>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    organizationsApi.mine().then((res) => {
      if (res) {
        setOrg(res.organization);
        setForm({
          name: res.organization.name, invoice_code: res.organization.invoice_code,
          phone: res.organization.phone, address: res.organization.address,
          requires_sequential_period_closing: res.organization.requires_sequential_period_closing,
        });
        setIsOwner(res.role === "owner");
      }
    }).finally(() => setLoading(false));
  }, []);

  const handleLogoChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > LOGO_MAX_BYTES) {
      setLogoError("Ukuran file maksimal 2 MB.");
      return;
    }
    setLogoUploading(true); setLogoError(null);
    try {
      const updated = await organizationsApi.uploadLogo(file);
      setOrg(updated);
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data;
      setLogoError(apiMessage?.message || "Gagal mengunggah logo.");
    } finally {
      setLogoUploading(false);
    }
  };

  const handleLogoDelete = async () => {
    if (!window.confirm("Hapus logo bengkel?")) return;
    setLogoUploading(true); setLogoError(null);
    try {
      const updated = await organizationsApi.deleteLogo();
      setOrg(updated);
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data;
      setLogoError(apiMessage?.message || "Gagal menghapus logo.");
    } finally {
      setLogoUploading(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null); setSaved(false);
    try {
      const updated = await organizationsApi.update({
        name: form.name,
        invoice_code: form.invoice_code,
        phone: form.phone,
        address: form.address,
        requires_sequential_period_closing: form.requires_sequential_period_closing,
      });
      setOrg(updated);
      setForm({
        name: updated.name, invoice_code: updated.invoice_code,
        phone: updated.phone, address: updated.address,
        requires_sequential_period_closing: updated.requires_sequential_period_closing,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string; errors?: Record<string, string[]> } } })?.response?.data;
      setError(apiMessage?.message || apiMessage?.errors?.invoice_code?.[0] || "Gagal menyimpan pengaturan.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  if (!org) {
    return <div style={{ color: "var(--danger)" }}>Anda belum tergabung dalam bengkel manapun.</div>;
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h1 className="display" style={{ fontSize: 26, marginBottom: 4, textTransform: "none" }}>Pengaturan Bengkel</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 24 }}>
        Profil bengkel Anda — nama, kontak, dan kode invoice.
      </p>

      {!isOwner && (
        <div style={{ background: "var(--paper-3)", color: "var(--steel)", padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={15} /> Hanya pemilik bengkel yang bisa mengubah pengaturan ini.
        </div>
      )}

      {error && (
        <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}

      <form onSubmit={handleSave} className="card">
        {/* 6 Oct 2026 — Organization Logo. Its own section, above the
            rest of the form fields and outside <form>'s own submit
            cycle — uploading/removing happens immediately on choice,
            not deferred until "Simpan Pengaturan" is clicked, same
            "a real file doesn't mix with a JSON body" split the
            backend already enforces (OrganizationLogoView is a
            separate endpoint from this form's own PATCH). */}
        <div style={{ marginBottom: 22, display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{
            width: 72, height: 72, borderRadius: 8, border: "1px solid var(--line)",
            display: "flex", alignItems: "center", justifyContent: "center",
            overflow: "hidden", background: "var(--paper-3)", flexShrink: 0,
          }}>
            {org.logo ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={org.logo} alt="Logo bengkel" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
            ) : (
              <span style={{ fontSize: 10, color: "var(--steel)", textAlign: "center", padding: 4 }}>Belum ada logo</span>
            )}
          </div>
          <div>
            <label className="label">Logo Bengkel</label>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <button
                type="button" className="btn-ghost" disabled={!isOwner || logoUploading}
                onClick={() => logoInputRef.current?.click()}
                style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}
              >
                {logoUploading ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Upload size={14} />}
                {org.logo ? "Ganti Logo" : "Unggah Logo"}
              </button>
              {org.logo && (
                <button
                  type="button" className="btn-ghost" disabled={!isOwner || logoUploading}
                  onClick={handleLogoDelete}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--danger)" }}
                >
                  <Trash2 size={14} /> Hapus
                </button>
              )}
            </div>
            <input
              ref={logoInputRef} type="file" accept={LOGO_ACCEPT} hidden
              onChange={handleLogoChange}
            />
            <p style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6 }}>
              PNG, JPEG, atau WEBP, maksimal 2 MB. Tampil di halaman ini dan di invoice PDF.
            </p>
            {logoError && (
              <p style={{ fontSize: 12, color: "var(--danger)", marginTop: 4 }}>{logoError}</p>
            )}
          </div>
        </div>

        <div style={{ marginBottom: 18 }}>
          <label className="label">Nama Bengkel</label>
          <input
            className="input" required value={form.name} disabled={!isOwner}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>

        <div style={{ marginBottom: 18 }}>
          <label className="label">Nomor Telepon Bengkel</label>
          <input
            className="input" value={form.phone} disabled={!isOwner}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            placeholder="cth. 0812-3456-7890"
          />
        </div>

        <div style={{ marginBottom: 18 }}>
          <label className="label">Alamat Bengkel</label>
          <textarea
            className="input" rows={3} value={form.address} disabled={!isOwner}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
            placeholder="Alamat lengkap untuk ditampilkan di invoice"
            style={{ resize: "vertical", fontFamily: "inherit" }}
          />
        </div>

        <div style={{ marginBottom: 6 }}>
          <label className="label">Kode Invoice</label>
          <input
            className="input mono" value={form.invoice_code} disabled={!isOwner}
            onChange={(e) => setForm({ ...form, invoice_code: e.target.value.toUpperCase() })}
            placeholder="mis. AM" maxLength={10}
            style={{ textTransform: "uppercase" }}
          />
        </div>
        <p style={{ fontSize: 12, color: "var(--steel)", marginBottom: 20 }}>
          Muncul di setiap nomor invoice, mis. <span className="mono">INV/REG/{form.invoice_code || "XX"}/0001/2026</span>.
          {" "}Dibuat otomatis dari nama bengkel Anda saat pendaftaran — ubah kapan saja di sini.
        </p>

        {/* 9 Sep 2026 — Phase 18, Task 18.6. Real, owner-configurable
            business-rule toggle — default true, same "off by default
            risk, on by default safety" posture as the backend field
            itself. Unlike every text field above, this one has a
            real, meaningful accounting consequence, so it gets its
            own explanatory paragraph underneath, same pattern as
            Kode Invoice's own. */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, opacity: isOwner ? 1 : 0.6 }}>
            <input
              type="checkbox" checked={form.requires_sequential_period_closing} disabled={!isOwner}
              onChange={(e) => setForm({ ...form, requires_sequential_period_closing: e.target.checked })}
            />
            Wajib Tutup Buku Berurutan
          </label>
          <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>
            Jika aktif (disarankan), periode akuntansi harus ditutup secara berurutan —
            periode sebelumnya harus ditutup dulu sebelum periode berikutnya bisa ditutup.
          </p>
        </div>

        <button className="btn-rust" type="submit" disabled={saving || !isOwner} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : saved ? <Check size={15} /> : <Save size={15} />}
          {saved ? "Tersimpan" : "Simpan Pengaturan"}
        </button>
      </form>
    </div>
  );
}
