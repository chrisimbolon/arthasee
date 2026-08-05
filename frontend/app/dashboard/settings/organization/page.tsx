"use client";
// =============================================================================
// === frontend/app/settings/organization/page.tsx ===
// =============================================================================
// Chris's own explicit call, 5 Aug: registration stays completely
// frictionless (name, email, password, shop name only) — invoice_code
// never appears on the signup form. A real fallback gets
// auto-generated from the shop's own name at creation time instead
// (see Organization._generate_invoice_code() on the backend) — this
// page is where an owner customizes it whenever they actually want
// to, not a required setup step blocking anything.
import { organizationsApi, Organization } from "@/lib/api/organizations";
import { AlertTriangle, Check, Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";

export default function OrganizationSettingsPage() {
  const [org, setOrg] = useState<Organization | null>(null);
  const [form, setForm] = useState({ name: "", invoice_code: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Real role check already lives on the backend (owner-only PATCH)
  // — this is just the proactive layer, same discipline as every
  // other gate in this app: disable the action, don't just let a
  // non-owner submit and discover the 403 after the fact.
  const [isOwner, setIsOwner] = useState(true);

  useEffect(() => {
    organizationsApi.mine().then((res) => {
      if (res) {
        setOrg(res.organization);
        setForm({ name: res.organization.name, invoice_code: res.organization.invoice_code });
        setIsOwner(res.role === "owner");
      }
    }).finally(() => setLoading(false));
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null); setSaved(false);
    try {
      const updated = await organizationsApi.update({
        name: form.name,
        invoice_code: form.invoice_code,
      });
      setOrg(updated);
      setForm({ name: updated.name, invoice_code: updated.invoice_code });
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
        Nama tampilan dan kode invoice bengkel Anda.
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
        <div style={{ marginBottom: 18 }}>
          <label className="label">Nama Bengkel</label>
          <input
            className="input" required value={form.name} disabled={!isOwner}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
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

        <button className="btn-rust" type="submit" disabled={saving || !isOwner} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : saved ? <Check size={15} /> : <Save size={15} />}
          {saved ? "Tersimpan" : "Simpan Pengaturan"}
        </button>
      </form>
    </div>
  );
}
