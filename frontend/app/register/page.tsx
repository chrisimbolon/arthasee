"use client";
// =============================================================================
// === frontend/app/register/page.tsx ===
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import { Loader2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function RegisterPage() {
  const { register } = useAuth();
  const [form, setForm] = useState({
    full_name: "", email: "", phone: "", organization_name: "", password: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await register(form);
    } catch (err: unknown) {
      const errors = (err as { response?: { data?: { errors?: Record<string, string[]> } } })
        ?.response?.data?.errors;
      setError(errors ? Object.values(errors).flat().join(", ") : "Gagal mendaftar. Coba lagi.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 36, justifyContent: "center" }}>
          <div style={{ width: 34, height: 34, background: "var(--ink)", borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--paper)", fontFamily: "'Big Shoulders Display', sans-serif", fontWeight: 900, fontSize: 18, transform: "rotate(-2deg)" }}>A</div>
          <div className="display" style={{ fontSize: 22 }}>Arthasee</div>
        </div>

        <div className="card">
          <h1 className="display" style={{ fontSize: 24, marginBottom: 6, textTransform: "none" }}>Daftarkan Bengkel</h1>
          <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 22 }}>Mulai gratis — tidak perlu kartu kredit.</p>

          {error && (
            <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 14 }}>
              <label className="label">Nama Bengkel</label>
              <input className="input" required value={form.organization_name}
                onChange={(e) => setForm({ ...form, organization_name: e.target.value })}
                placeholder="mis. CV. Arya Motor" />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label className="label">Nama Anda</label>
              <input className="input" required value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                placeholder="Nama lengkap" />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label className="label">Email</label>
              <input className="input" type="email" required value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="anda@bengkel.com" />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label className="label">Nomor Telepon <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <input className="input" value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="08xxxxxxxxxx" />
            </div>
            <div style={{ marginBottom: 22 }}>
              <label className="label">Kata Sandi</label>
              <input className="input" type="password" required minLength={8} value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="Minimal 8 karakter" />
            </div>
            <button className="btn-rust" type="submit" disabled={loading} style={{ width: "100%", justifyContent: "center", padding: "11px 0" }}>
              {loading ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <UserPlus size={16} />}
              Daftar
            </button>
          </form>
        </div>

        <p style={{ textAlign: "center", fontSize: 13.5, color: "var(--steel)", marginTop: 20 }}>
          Sudah punya akun? <Link href="/login" style={{ color: "var(--rust)", fontWeight: 600 }}>Masuk</Link>
        </p>
      </div>
    </div>
  );
}
