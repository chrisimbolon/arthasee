"use client";
// =============================================================================
// === frontend/app/page.tsx ===
// The public marketing landing page — now the real root route.
//
// Auth behavior preserved from the previous version of this file:
// an already-logged-in visitor still gets bounced straight to
// /dashboard, same as before. The difference is everyone else no
// longer sees a bare loading spinner — they see the actual landing
// page, which is the whole point of putting it here. Rendered
// immediately rather than gated behind the auth check, since a
// public marketing page shouldn't block on a login lookup nobody
// asked for.
//
// Styling: relies entirely on the shared tokens/classes already in
// globals.css (--ink, --paper, --rust, .display, .mono, .btn-rust,
// .btn-ghost, :focus-visible, @keyframes spin, etc.) rather than
// redefining them — globals.css's own header comment says this page
// and the app were always meant to share one token system, so this
// keeps that true instead of drifting into two copies that could
// silently diverge. The <style> block below only adds what's
// genuinely unique to this page (hero, service-sticker signature,
// section scaffolding, card grids) — nothing already covered
// globally is repeated here.
//
// One deliberate exception: .btn-hero-rust / .btn-hero-ghost are
// NOT the same as globals.css's .btn-rust/.btn-ghost, on purpose —
// this page's CTAs use slightly larger padding and a hover lift
// that suit a marketing hero, and reusing the dashboard's exact
// button class names for a visually different treatment would mean
// two different button styles silently fighting over the same class name depending on load order.
//  Renaming avoids that outright instead of relying on the cascade to sort it out.
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function RootPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return (
    <>
      <style>{`
        /* Only what globals.css doesn't already cover. */
        body { overflow-x: hidden; }
        a { text-decoration: none; }
        html { scroll-behavior: smooth; }

        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
        }

        /* This page's own tighter heading leading for the stacked
           3-line hero treatment — globals.css's .display intentionally
           leaves line-height at browser default since most uses
           elsewhere are single-line. */
        .hero h1.display { line-height: 0.92; }

        .wrap { max-width: 1180px; margin: 0 auto; padding: 0 32px; }

        /* Deliberately separate from globals.css's .btn-rust/.btn-ghost
           — see file header comment. */
        .btn-hero-rust {
          background: var(--rust); color: var(--paper-3);
          padding: 11px 22px; font-weight: 600; font-size: 14.5px;
          border-radius: 4px; display: inline-flex; align-items: center; gap: 8px;
          transition: background 0.15s ease, transform 0.15s ease;
          border: none; cursor: pointer;
        }
        .btn-hero-rust:hover { background: var(--rust-dark); transform: translateY(-1px); }
        .btn-hero-ghost {
          padding: 11px 20px; font-weight: 600; font-size: 14.5px;
          border: 1.5px solid var(--ink); border-radius: 4px;
          transition: background 0.15s ease;
        }
        .btn-hero-ghost:hover { background: var(--ink); color: var(--paper); }

        /* ── Hero ────────────────────────────────────────── */
        .hero {
          padding: 88px 0 60px;
          display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 56px; align-items: center;
        }
        .eyebrow {
          display: inline-flex; align-items: center; gap: 8px;
          background: var(--paper-3); border: 1px solid var(--line);
          padding: 7px 14px; border-radius: 999px;
          font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 500;
          letter-spacing: 0.06em; text-transform: uppercase; color: var(--workshop);
          margin-bottom: 26px;
        }
        .eyebrow::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--rust); }

        .hero h1 {
          font-size: clamp(42px, 5.2vw, 68px);
          margin-bottom: 22px;
        }
        .hero h1 em {
          font-style: normal; color: var(--rust);
        }
        .hero-sub {
          font-size: 18px; line-height: 1.6; color: var(--ink-soft);
          max-width: 480px; margin-bottom: 34px;
        }
        .hero-ctas { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 22px; }
        .hero-note {
          font-size: 13.5px; color: var(--steel); display: flex; align-items: center; gap: 8px;
        }
        .hero-note svg { flex-shrink: 0; }

        /* ── Signature: the service sticker ─────────────── */
        .sticker-stage {
          position: relative; height: 460px; display: flex; align-items: center; justify-content: center;
        }
        .sticker {
          width: 320px; background: var(--paper-3);
          border: 2px solid var(--ink);
          border-radius: 6px;
          padding: 24px 22px 20px;
          transform: rotate(-4deg);
          box-shadow: 10px 14px 0 rgba(23,24,26,0.12);
          position: relative;
          animation: sticker-in 0.7s cubic-bezier(0.16,1,0.3,1) both;
        }
        @keyframes sticker-in {
          from { opacity: 0; transform: rotate(-4deg) translateY(16px); }
          to   { opacity: 1; transform: rotate(-4deg) translateY(0); }
        }
        .sticker::before {
          content: '';
          position: absolute; inset: 8px;
          border: 1px dashed var(--steel-lt);
          border-radius: 3px;
          pointer-events: none;
        }
        .sticker-head {
          display: flex; justify-content: space-between; align-items: flex-start;
          font-family: 'IBM Plex Mono', monospace; font-size: 11px; text-transform: uppercase;
          letter-spacing: 0.05em; color: var(--steel); margin-bottom: 14px;
        }
        .sticker-shop { color: var(--ink); font-weight: 600; }
        .sticker-plate {
          font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 22px;
          background: var(--ink); color: var(--paper); padding: 6px 12px;
          border-radius: 3px; display: inline-block; letter-spacing: 0.04em; margin-bottom: 16px;
        }
        .sticker-row {
          display: flex; justify-content: space-between; align-items: baseline;
          padding: 9px 0; border-top: 1px solid var(--line);
          font-size: 13.5px; color: var(--ink-soft);
        }
        .sticker-row:first-of-type { border-top: none; }
        .sticker-row .val { font-family: 'IBM Plex Mono', monospace; font-weight: 600; color: var(--ink); }
        .sticker-status {
          margin-top: 14px; padding: 10px 12px; border-radius: 4px;
          background: var(--hazard); color: var(--ink);
          font-weight: 700; font-size: 13px; text-align: center;
          display: flex; align-items: center; justify-content: center; gap: 8px;
        }
        .sticker-status .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--rust-dark); animation: pulse 1.8s ease-in-out infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }

        .float-tag {
          position: absolute; background: var(--workshop); color: var(--paper-3);
          padding: 9px 14px; border-radius: 5px; font-size: 12.5px; font-weight: 600;
          display: flex; align-items: center; gap: 7px; box-shadow: 5px 6px 0 rgba(23,24,26,0.1);
        }
        .float-tag.t1 { top: 18px; right: 4px; transform: rotate(3deg); }
        .float-tag.t2 { bottom: 30px; left: -6px; transform: rotate(-2deg); background: var(--ink); }

        @media (max-width: 900px) {
          .hero { grid-template-columns: 1fr; padding-top: 48px; }
          .sticker-stage { height: 380px; }
        }

        /* ── Section scaffolding ─────────────────────────── */
        section { padding: 92px 0; }
        .section-head { max-width: 620px; margin-bottom: 52px; }
        .section-kicker {
          font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; font-weight: 500;
          letter-spacing: 0.08em; text-transform: uppercase; color: var(--rust); margin-bottom: 12px;
          display: flex; align-items: center; gap: 10px;
        }
        .section-kicker::before { content: ''; width: 22px; height: 2px; background: var(--rust); }
        .section-head h2 { font-size: clamp(30px, 3.4vw, 42px); margin-bottom: 14px; }
        .section-head p { font-size: 16.5px; color: var(--ink-soft); line-height: 1.6; }

        /* ── Live today cards ─────────────────────────────── */
        .live-band { background: var(--paper-3); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
        .card-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; }
        .live-card {
          background: var(--paper); border: 1.5px solid var(--ink); border-radius: 6px;
          padding: 22px 20px; position: relative;
          transition: transform 0.18s ease, box-shadow 0.18s ease;
        }
        .live-card:hover { transform: translateY(-4px); box-shadow: 6px 8px 0 rgba(23,24,26,0.12); }
        .live-card .tag {
          position: absolute; top: -11px; left: 18px;
          background: var(--workshop); color: var(--paper-3);
          font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600;
          letter-spacing: 0.06em; text-transform: uppercase;
          padding: 4px 9px; border-radius: 3px;
        }
        .live-card h3 { font-family: 'Big Shoulders Display', sans-serif; font-weight: 700; font-size: 18px; text-transform: uppercase; margin: 12px 0 8px; }
        .live-card p { font-size: 13.5px; color: var(--ink-soft); line-height: 1.55; }
        .live-icon {
          width: 36px; height: 36px; border-radius: 50%; background: var(--ink);
          display: flex; align-items: center; justify-content: center; color: var(--paper);
        }

        @media (max-width: 1080px) { .card-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 560px)  { .card-grid { grid-template-columns: 1fr; } }

        /* ── Reminder demo strip ─────────────────────────── */
        .demo-strip { display: flex; gap: 18px; overflow-x: auto; padding: 6px 2px 18px; }
        .mini-sticker {
          flex: 0 0 220px; background: var(--paper-3); border: 1.5px solid var(--ink);
          border-radius: 5px; padding: 16px 16px 14px;
        }
        .mini-sticker .plate {
          font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 14px;
          background: var(--ink); color: var(--paper); padding: 4px 8px; border-radius: 3px;
          display: inline-block; margin-bottom: 10px;
        }
        .mini-sticker .km { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: var(--ink-soft); margin-bottom: 8px; }
        .mini-sticker .km b { color: var(--ink); }
        .status-pill {
          display: inline-flex; align-items: center; gap: 6px;
          font-size: 11.5px; font-weight: 700; padding: 5px 10px; border-radius: 999px;
          text-transform: uppercase; letter-spacing: 0.03em;
        }
        .status-pill.ok      { background: var(--workshop-lt); color: var(--workshop); }
        .status-pill.soon    { background: var(--hazard-light); color: var(--hazard-dark); }
        .status-pill.due     { background: var(--rust-light); color: var(--rust-dark); }
        .status-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

        /* ── Building next ────────────────────────────────── */
        .next-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; max-width: 780px; }
        .next-card {
          border: 1.5px dashed var(--steel-lt); border-radius: 6px;
          padding: 24px 22px; background: transparent;
        }
        .next-card .badge {
          font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; font-weight: 600;
          color: var(--steel); text-transform: uppercase; letter-spacing: 0.06em;
          border: 1px solid var(--steel-lt); border-radius: 3px; padding: 3px 8px;
          display: inline-block; margin-bottom: 14px;
        }
        .next-card h4 { font-family: 'Big Shoulders Display', sans-serif; font-weight: 700; font-size: 19px; text-transform: uppercase; margin-bottom: 8px; color: var(--ink-soft); }
        .next-card p { font-size: 13.5px; color: var(--steel); line-height: 1.55; }

        @media (max-width: 700px) { .next-grid { grid-template-columns: 1fr; } }

        /* ── Pilot / trust ────────────────────────────────── */
        .pilot {
          background: var(--ink); color: var(--paper);
          border-radius: 10px; padding: 52px 48px;
          display: grid; grid-template-columns: auto 1fr; gap: 40px; align-items: center;
        }
        .pilot-mark {
          width: 84px; height: 84px; border-radius: 50%;
          background: var(--rust); display: flex; align-items: center; justify-content: center;
          font-family: 'Big Shoulders Display', sans-serif; font-weight: 900; font-size: 30px;
        }
        .pilot blockquote { font-size: 21px; line-height: 1.5; margin-bottom: 14px; }
        .pilot cite { font-style: normal; font-size: 14px; color: var(--steel-lt); font-family: 'IBM Plex Mono', monospace; }

        @media (max-width: 700px) { .pilot { grid-template-columns: 1fr; text-align: center; padding: 40px 26px; } .pilot-mark { margin: 0 auto; } }

        /* ── Final CTA ─────────────────────────────────────── */
        .final-cta { text-align: center; padding: 100px 0; }
        .final-cta h2 { font-size: clamp(34px, 4.6vw, 54px); margin-bottom: 18px; }
        .final-cta p { font-size: 17px; color: var(--ink-soft); margin-bottom: 34px; }
        .final-ctas { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; }

        footer {
          border-top: 1px solid var(--line); padding: 34px 0;
          display: flex; justify-content: space-between; align-items: center;
          font-size: 13px; color: var(--steel); flex-wrap: wrap; gap: 12px;
        }
      `}</style>

<nav className="h-[74px] w-full bg-[#111111]">
  <div className="mx-auto flex h-full w-full max-w-[1440px] items-center px-[120px]">

    <Link href="/" className="flex shrink-0 items-center">
      <Image
        src="/Logo-teks.png"
        alt="Arthasee"
        width={190}
        height={40}
        className="block h-10 w-auto object-contain"
        priority
      />
    </Link>

    <div className="ml-auto flex items-center gap-8">
      <a
        href="#home"
        className="text-[13px] font-medium text-white transition-opacity hover:opacity-70"
      >
        HOME
      </a>

      <a
        href="#services"
        className="text-[13px] font-medium text-white transition-opacity hover:opacity-70"
      >
        SERVICES
      </a>

      <a
        href="#about"
        className="text-[13px] font-medium text-white transition-opacity hover:opacity-70"
      >
        ABOUT
      </a>

      <a
        href="#pricing"
        className="text-[13px] font-medium text-white transition-opacity hover:opacity-70"
      >
        PRICING
      </a>

      <a
        href="#pages"
        className="text-[13px] font-medium text-white transition-opacity hover:opacity-70"
      >
        PAGES
      </a>

      <a
        href="#contact"
        className="text-[13px] font-medium text-white transition-opacity hover:opacity-70"
      >
        CONTACT
      </a>
    </div>

     <Link
      href="/register"
      className="ml-[168px] flex h-10 shrink-0 items-center justify-center rounded-[4px] bg-[#096b3b] px-[26px] text-[13px] font-semibold text-white transition-colors hover:bg-[#075c32]"
    >
      GET IN TOUCH
    </Link>

  </div>
</nav>

<section
  id="home"
  className="relative min-h-[calc(100vh-74px)] overflow-hidden bg-[#EDEBE5]"
>
  {/* Background image */}
    <div
  className="absolute inset-0 bg-cover bg-center"
  style={{ backgroundImage: "url('/hero-workshop.webp')" }}
/>

  {/* Content */}
  <div className="relative mx-auto flex min-h-[calc(100vh-74px)] w-full max-w-[1440px] items-center px-[120px]">
    <div className="max-w-[650px]">

      {/* Badge */}
      <div className="mb-8 inline-flex items-center gap-3 rounded-full border border-black/10 bg-[#F8F7F3]/90 px-4 py-2">
        <span className="h-2 w-2 rounded-full bg-[#C1401C]" />
        <span className="font-mono text-[13px] font-medium tracking-[0.08em] text-[#2F4A3C]">
          CRM BENGKEL
        </span>
        <span className="text-black/30">·</span>
        <span className="font-mono text-[13px] font-medium tracking-[0.08em] text-[#2F4A3C]">
          FASE 1
        </span>
      </div>

      {/* Heading */}
<h1 className="w-[635px] max-w-full font-['Montserrat'] text-[56px] font-bold italic uppercase leading-none tracking-[0] text-white">
  <span className="block whitespace-nowrap">
    SISTEM MANAJEMEN
  </span>
  <span className="block whitespace-nowrap">
    BENGKEL TERINTEGRASI
  </span>
</h1>        

      {/* Description */}
      <p className="mt-8 max-w-[610px] text-[18px] leading-[1.65] text-[#3C3C38]">
        Arthasee menyimpan data pelanggan, riwayat kendaraan,
        dan catatan servis bengkel Anda di satu tempat — lalu
        memberi tahu unit mana yang sudah waktunya servis lagi.
        Sesederhana itu, dan sudah bisa dipakai hari ini.
      </p>

      {/* Buttons */}
      <div className="mt-10 flex items-center gap-4">
        <a
          href="/register"
          className="inline-flex h-[54px] items-center justify-center rounded-[5px] bg-[#C1401C] px-7 text-[15px] font-semibold text-white transition-colors hover:bg-[#9A3116]"
        >
          Mulai Gratis →
        </a>

        <a
          href="#live"
          className="inline-flex h-[54px] items-center justify-center rounded-[5px] border-[1.5px] border-[#17181A] bg-[#F8F7F3]/80 px-7 text-[15px] font-semibold text-[#17181A] transition-colors hover:bg-[#17181A] hover:text-white"
        >
          Lihat Yang Sudah Jalan
        </a>
      </div>

      {/* Trust line */}
      <div className="mt-8 flex items-center gap-3 text-[14px] text-[#5B6670]">
        <span className="text-[18px]">✓</span>
        <span>
          Dibangun bareng bengkel sungguhan di Batam — bukan mockup.
        </span>
      </div>

    </div>
  </div>
</section>

      <section id="live" className="live-band">
        <div className="wrap">
          <div className="section-head">
            <div className="section-kicker">Aktif Hari Ini</div>
            <h2 className="display" style={{ textTransform: "none", fontSize: 38 }}>Yang benar-benar sudah bisa dipakai.</h2>
            <p>Tidak ada yang dijanjikan di sini yang belum jadi. Semua bagian di bawah ini sudah berjalan, sudah diuji, dan sudah dipakai langsung oleh bengkel sungguhan — bukan demo.</p>
          </div>

          <div className="card-grid">
            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" /></svg>
              </div>
              <h3>Leads</h3>
              <p>Catat calon pelanggan yang belum jadi servis — harga kemahalan, pikir-pikir dulu, dll. Jadi daftar follow-up, bukan hilang begitu saja.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4" /><path d="M4 21v-1a8 8 0 0116 0v1" /></svg>
              </div>
              <h3>Data Pelanggan &amp; Kendaraan</h3>
              <p>Simpan nama pelanggan, nomor STNK — bisa beda dari nama pelanggan — dan semua kendaraan yang pernah mereka bawa. Satu pelanggan, banyak kendaraan, tidak masalah.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6M9 15l2 2 4-4" /></svg>
              </div>
              <h3>Estimasi</h3>
              <p>Buat perkiraan harga sebelum kerja dimulai — belum menyentuh stok sama sekali sampai pelanggan benar-benar setuju.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" /><rect x="9" y="3" width="6" height="4" rx="1" /><path d="M9 12l2 2 4-4" /></svg>
              </div>
              <h3>Work Order</h3>
              <p>Setelah disetujui, jadi pekerjaan nyata — daftar tugas, sparepart yang dipakai, semua tercatat berjalannya waktu, sesuai proses bengkel yang sebenarnya.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" /><rect x="9" y="3" width="6" height="4" rx="1" /></svg>
              </div>
              <h3>Riwayat Servis</h3>
              <p>Setiap kendaraan masuk, catat kerusakan dan sparepart yang diganti. Riwayat tersimpan permanen — tinggal buka, langsung kelihatan pernah diapain saja mobilnya.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 2h13l3 3v17H4z" /><path d="M8 7h8M8 11h8M8 15h5" /></svg>
              </div>
              <h3>Invoice</h3>
              <p>Nomor otomatis, rincian sparepart dan jasa, siap cetak untuk pelanggan. Sekali terbit, tidak bisa diubah-ubah lagi — angka yang tercetak aman.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 8l-9-5-9 5v8l9 5 9-5z" /><path d="M3 8l9 5 9-5M12 13v8" /></svg>
              </div>
              <h3>Stok Sparepart</h3>
              <p>Stok gudang otomatis berkurang persis saat sparepart benar-benar dipakai untuk servis — bukan belakangan, bukan tebak-tebakan.</p>
            </div>

            <div className="live-card">
              <span className="tag">Live</span>
              <div className="live-icon">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 8v4l3 3" /><circle cx="12" cy="12" r="9" /></svg>
              </div>
              <h3>Pengingat 5.000 KM</h3>
              <p>Sistem otomatis menandai kendaraan mana yang sudah lewat 5.000 KM sejak servis terakhir — Anda tinggal lihat daftarnya dan hubungi pelanggan sendiri.</p>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <div className="section-head">
            <div className="section-kicker">Contoh Nyata</div>
            <h2 className="display" style={{ textTransform: "none", fontSize: 34 }}>Begini tampilannya di daftar Anda.</h2>
            <p>Setiap kendaraan otomatis dapat status — hijau berarti masih aman, kuning mendekati waktunya, merah sudah harus balik.</p>
          </div>
          <div className="demo-strip">
            <div className="mini-sticker">
              <div className="plate">BP 2210 AZ</div>
              <div className="km">Sisa <b>1.200 KM</b> lagi</div>
              <span className="status-pill ok"><span className="dot"></span>Aman</span>
            </div>
            <div className="mini-sticker">
              <div className="plate">BP 1055 QR</div>
              <div className="km">Sisa <b>310 KM</b> lagi</div>
              <span className="status-pill soon"><span className="dot"></span>Mendekati</span>
            </div>
            <div className="mini-sticker">
              <div className="plate">BP 1892 KL</div>
              <div className="km"><b>300 KM</b> lewat batas</div>
              <span className="status-pill due"><span className="dot"></span>Harus Balik</span>
            </div>
            <div className="mini-sticker">
              <div className="plate">BP 7788 MN</div>
              <div className="km">Sisa <b>4.100 KM</b> lagi</div>
              <span className="status-pill ok"><span className="dot"></span>Aman</span>
            </div>
          </div>
        </div>
      </section>

      <section id="next" className="live-band">
        <div className="wrap">
          <div className="section-head">
            <div className="section-kicker">Rencana Berikutnya</div>
            <h2 className="display" style={{ textTransform: "none", fontSize: 38 }}>Sedang dibangun — belum live.</h2>
            <p>Kami lebih pilih jujur soal apa yang belum ada daripada menjanjikan sesuatu yang belum bisa dipakai. Ini nyata, tapi belum jadi.</p>
          </div>
          <div className="next-grid">
            <div className="next-card">
              <span className="badge">Segera</span>
              <h4>Pengingat Otomatis</h4>
              <p>Kirim WhatsApp otomatis ke pelanggan saat kendaraan mereka sudah waktunya servis — bukan cuma ditandai di daftar.</p>
            </div>
            <div className="next-card">
              <span className="badge">Suatu Hari</span>
              <h4>Multi-Cabang</h4>
              <p>Untuk bengkel dengan lebih dari satu lokasi. Belum jadi prioritas saat ini — dipikirkan lagi kalau memang dibutuhkan.</p>
            </div>
          </div>
        </div>
      </section>

      <section id="pilot">
        <div className="wrap">
          <div className="pilot">
            <div className="pilot-mark">AM</div>
            <div>
              <blockquote>&quot;Pelanggan itu aset kami. Tanpa pelanggan dan sistem yang mengurus mereka, gudang dan montir sebanyak apa pun tidak ada gunanya.&quot;</blockquote>
              <cite>— I Made Sudarta, CV. Arya Motor, Batam</cite>
            </div>
          </div>
        </div>
      </section>

      <section className="final-cta">
        <div className="wrap">
          <h2 className="display">Coba di bengkel Anda.</h2>
          <p>Gratis untuk mulai. Tidak perlu kartu kredit.</p>
          <div className="final-ctas">
            <Link href="/register" className="btn-hero-rust">Mulai Gratis →</Link>
            <a href="#" className="btn-hero-ghost">Hubungi Kami</a>
          </div>
        </div>
      </section>

      <footer className="wrap">
        <div>© 2026 Arthasee. Dibuat di Batam.</div>
        <div className="mono">Fase 1 — CRM Bengkel</div>
      </footer>
    </>
  );
}
