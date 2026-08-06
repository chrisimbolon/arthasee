"use client";
// =============================================================================
// === frontend/app/customer/login/page.tsx ===
// =============================================================================
// Fase 2.5 — top-level route (sibling of /login, the internal-staff
// one), NOT under /dashboard. Deliberately not the same page as
// internal /login — different identity system entirely (Customer,
// not CustomUser), different token (see lib/api/customerAuth.ts).
import { customerAuthApi } from "@/lib/api/customerAuth";
import { Loader2, Mail } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function CustomerLoginPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSending(true); setError(null);
    try {
      const res = await customerAuthApi.requestMagicLink(email.trim());
      setSent(true);
      // Only ever present when the backend is running in DEBUG and a
      // real email provider isn't wired in yet (Fase 2.5's own deliberately deferred half — see
      // CustomerMagicLinkRequestView's own docstring). Once a real
      // provider is chosen, this whole dev_token path disappears —
      // nothing else about this page needs to change.
      if (res.dev_token) setDevToken(res.dev_token);
    } catch {
      setError("Gagal mengirim link. Coba lagi.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: "100px auto", padding: "0 20px" }}>
      <div className="card">
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>Masuk ke Akun Anda</h1>
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 20 }}>
          Masukkan email yang terdaftar di bengkel — kami akan mengirimkan link masuk.
        </p>

        {sent ? (
          <div>
            <p style={{ fontSize: 14 }}>
              Jika email <strong>{email}</strong> terdaftar, link masuk sudah dikirim.
              Periksa kotak masuk Anda.
            </p>
            {devToken && (
              <div style={{ marginTop: 16, padding: 12, background: "var(--paper-3)", borderRadius: 6 }}>
                <p style={{ fontSize: 11.5, color: "var(--steel)", marginBottom: 6, textTransform: "uppercase" }}>
                  Mode Pengembangan — belum ada pengiriman email nyata
                </p>
                <Link href={`/customer/verify?token=${devToken}`} className="mono" style={{ fontSize: 12.5, color: "var(--rust)", wordBreak: "break-all" }}>
                  /customer/verify?token={devToken}
                </Link>
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div style={{ position: "relative", marginBottom: 14 }}>
              <Mail size={15} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--steel)" }} />
              <input
                type="email" required autoFocus value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nama@email.com"
                className="input" style={{ width: "100%", paddingLeft: 32 }}
              />
            </div>
            {error && (
              <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "8px 10px", borderRadius: 5, fontSize: 12.5, marginBottom: 12 }}>
                {error}
              </div>
            )}
            <button type="submit" className="btn-rust" style={{ width: "100%", justifyContent: "center" }} disabled={sending}>
              {sending ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Kirim Link Masuk"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
