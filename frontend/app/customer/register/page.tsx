"use client";
// =============================================================================
// === frontend/app/customer/register/page.tsx ===
// =============================================================================
// Fase 2.5 — the missing path for a genuine first-time visitor.
// Mandatory login (confirmed directly) meant CustomerLoginPage alone
// couldn't onboard anyone who's never been to the shop before. A
// real sibling entry point, not something the system tries to
// auto-detect — the backend deliberately returns the SAME response
// whether an email is registered or not (see
// CustomerMagicLinkRequestView's own "never confirm or deny"
// security property), so the frontend has nothing to branch on.
// Same "Log in / Sign up" pattern most real apps use instead.
import { customerAuthApi } from "@/lib/api/customerAuth";
import { Car, Loader2, Mail, Phone, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function CustomerRegisterPage() {
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [plateNumber, setPlateNumber] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSending(true); setError(null);
    try {
      const res = await customerAuthApi.register({
        full_name: fullName.trim(), phone: phone.trim(),
        email: email.trim(), plate_number: plateNumber.trim(),
      });
      setSent(true);
      // Same self-eliminating dev_token passthrough as
      // CustomerLoginPage — disappears on its own once real sending
      // is genuinely wired in, no further code change needed then.
      if (res.dev_token) setDevToken(res.dev_token);
    } catch (err) {
      // A real, specific error CAN surface here (e.g. a genuine
      // plate conflict) — customerFetch() throws the backend's own
      // message, unlike the login flow, which never has anything
      // specific to say either way.
      setError(err instanceof Error ? err.message : "Gagal mendaftar. Coba lagi.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: "100px auto", padding: "0 20px" }}>
      <div className="card">
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>Daftar Akun Baru</h1>
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 20 }}>
          Pelanggan baru? Daftar di sini untuk membuat janji servis online.
        </p>

        {sent ? (
          <div>
            <p style={{ fontSize: 14 }}>
              Pendaftaran berhasil — link masuk sudah dikirim ke <strong>{email}</strong>.
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
          <>
            <form onSubmit={handleSubmit}>
              <div style={{ position: "relative", marginBottom: 12 }}>
                <User size={15} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--steel)" }} />
                <input
                  type="text" required autoFocus value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Nama Lengkap"
                  className="input" style={{ width: "100%", paddingLeft: 32 }}
                />
              </div>
              <div style={{ position: "relative", marginBottom: 12 }}>
                <Phone size={15} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--steel)" }} />
                <input
                  type="tel" required value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="Nomor WhatsApp"
                  className="input" style={{ width: "100%", paddingLeft: 32 }}
                />
              </div>
              <div style={{ position: "relative", marginBottom: 12 }}>
                <Mail size={15} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--steel)" }} />
                <input
                  type="email" required value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="nama@email.com"
                  className="input" style={{ width: "100%", paddingLeft: 32 }}
                />
              </div>
              <div style={{ position: "relative", marginBottom: 14 }}>
                <Car size={15} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--steel)" }} />
                <input
                  type="text" required value={plateNumber}
                  onChange={(e) => setPlateNumber(e.target.value)}
                  placeholder="Nomor Plat Kendaraan"
                  className="input" style={{ width: "100%", paddingLeft: 32 }}
                />
              </div>
              {error && (
                <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "8px 10px", borderRadius: 5, fontSize: 12.5, marginBottom: 12 }}>
                  {error}
                </div>
              )}
              <button type="submit" className="btn-rust" style={{ width: "100%", justifyContent: "center" }} disabled={sending}>
                {sending ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Daftar & Kirim Link Masuk"}
              </button>
            </form>
            <p style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 16, textAlign: "center" }}>
              Sudah punya akun? <Link href="/customer/login" style={{ color: "var(--rust)" }}>Masuk di sini</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
