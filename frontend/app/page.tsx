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
        <p className="mt-8 max-w-[610px] text-[18px] leading-[1.65] text-white/80">
          Arthasee menyimpan data pelanggan, riwayat kendaraan,
          dan catatan servis bengkel Anda di satu tempat — lalu
          memberi tahu unit mana yang sudah waktunya servis lagi.
          Sesederhana itu, dan sudah bisa dipakai hari ini.
        </p>

      {/* Buttons */}
{/* CTA Buttons */}
<div className="mt-8 flex items-center gap-4">
  <a
    href="#contact"
    className="inline-flex h-[48px] items-center justify-center rounded-[4px] bg-[#D9471F] px-7 text-[16px] font-semibold text-white transition-colors hover:bg-[#C43D1B]"
  >
    Mulai Gratis →
  </a>

  <a
    href="#about"
    className="inline-flex h-[48px] items-center justify-center rounded-[4px] border-2 border-white px-7 text-[16px] font-semibold text-white transition-colors hover:bg-white hover:text-[#17181A]"
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

        {/* Services Section */}
<section
  id="services"
  className="relative bg-white px-6 py-[72px] md:px-[60px] lg:px-[120px]"
>
  <div className="mx-auto w-full max-w-[1200px]">

    {/* Stats */}
    <div className="grid grid-cols-3 gap-8 pb-[72px]">
      <div>
        <div className="font-['Montserrat'] text-[42px] font-bold italic leading-none text-[#17181A]">
          10<span className="text-[#096B3B]">+</span>
        </div>

        <div className="mt-2 text-[11px] font-medium uppercase tracking-[0.04em] text-[#17181A]">
          YEARS OF SERVICE
        </div>
      </div>

      <div>
        <div className="font-['Montserrat'] text-[42px] font-bold italic leading-none text-[#17181A]">
          50K<span className="text-[#096B3B]">+</span>
        </div>

        <div className="mt-2 text-[11px] font-medium uppercase tracking-[0.04em] text-[#17181A]">
          HAPPY CUSTOMERS
        </div>
      </div>

      <div>
        <div className="font-['Montserrat'] text-[42px] font-bold italic leading-none text-[#17181A]">
          99<span className="text-[#096B3B]">%</span>
        </div>

        <div className="mt-2 text-[11px] font-medium uppercase tracking-[0.04em] text-[#17181A]">
          CLIENT SATISFACTION
        </div>
      </div>
    </div>

    {/* Services Header */}
    <div className="relative mb-10">

      <div>
        <div className="mb-2 font-mono text-[12px] font-medium uppercase tracking-[0.08em] text-[#096B3B]">
          OUR SERVICES
        </div>

        <h2 className="font-['Montserrat'] text-[40px] font-bold uppercase leading-none tracking-[-0.02em] text-[#17181A]">
          SOLUSI LENGKAP
          <br />
          UNTUK BENGKEL ANDA
        </h2>
      </div>

      {/* Decorative Heading */}
      <div className="pointer-events-none absolute right-0 top-0 hidden select-none font-['Montserrat'] text-[52px] font-bold italic uppercase leading-none tracking-[-0.03em] text-transparent [-webkit-text-stroke:1px_#E5E5E5] lg:block">
        OUR SERVICES
      </div>

      {/* Arrows */}
      <div className="absolute right-0 bottom-0 flex items-center gap-3 text-[25px] leading-none text-[#17181A]">
        <button
          type="button"
          aria-label="Previous services"
          className="leading-none transition-opacity hover:opacity-50"
        >
          ←
        </button>

        <button
          type="button"
          aria-label="Next services"
          className="leading-none transition-opacity hover:opacity-50"
        >
          →
        </button>
      </div>
    </div>

    {/* Service Cards */}
    <div className="grid grid-cols-1 gap-5 md:grid-cols-3">

      {/* Leads */}
      <article className="group relative h-[360px] overflow-hidden rounded-[6px]">
        <div
          className="absolute inset-0 bg-cover bg-center transition-transform duration-500 group-hover:scale-105"
          style={{ backgroundImage: "url('/services/Service-lead.webp')" }}
        />

        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />

        <div className="relative flex h-full flex-col justify-end p-5 text-white">
          <h3 className="font-['Montserrat'] text-[18px] font-bold uppercase leading-tight">
            LEADS
          </h3>

          <p className="mt-2 max-w-[310px] text-[13px] leading-[1.45] text-white/90">
            Catat calon pelanggan yang belum jadi servis —
            harga kemahalan, pikir-pikir dulu, dll. Jadi daftar
            follow-up, bukan hilang begitu saja.
          </p>

          <a
            href="#contact"
            className="mt-4 inline-flex w-fit text-[12px] font-semibold uppercase text-white transition-opacity hover:opacity-70"
          >
            READ MORE →
          </a>
        </div>
      </article>

      {/* Customer & Vehicle Data */}
      <article className="group relative h-[360px] overflow-hidden rounded-[6px]">
        <div
          className="absolute inset-0 bg-cover bg-center transition-transform duration-500 group-hover:scale-105"
          style={{ backgroundImage: "url('/services/service-customer.webp')" }}
        />

        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />

        <div className="relative flex h-full flex-col justify-end p-5 text-white">
          <h3 className="font-['Montserrat'] text-[18px] font-bold uppercase leading-tight">
            DATA PELANGGAN &amp; KENDARAAN
          </h3>

          <p className="mt-2 max-w-[310px] text-[13px] leading-[1.45] text-white/90">
            Simpan nama pelanggan, nomor STNK, dan semua
            kendaraan yang pernah mereka bawa.
          </p>

          <a
            href="#contact"
            className="mt-4 inline-flex w-fit text-[12px] font-semibold uppercase text-white transition-opacity hover:opacity-70"
          >
            READ MORE →
          </a>
        </div>
      </article>

      {/* Estimasi */}
      <article className="group relative h-[360px] overflow-hidden rounded-[6px]">
        <div
          className="absolute inset-0 bg-cover bg-center transition-transform duration-500 group-hover:scale-105"
          style={{ backgroundImage: "url('/services/service-estimasi.webp')" }}
        />

        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />

        <div className="relative flex h-full flex-col justify-end p-5 text-white">
          <h3 className="font-['Montserrat'] text-[18px] font-bold uppercase leading-tight">
            ESTIMASI
          </h3>

          <p className="mt-2 max-w-[310px] text-[13px] leading-[1.45] text-white/90">
            Buat perkiraan harga sebelum kerja dimulai —
            belum menyentuh stok sampai pelanggan benar-benar setuju.
          </p>

          <a
            href="#contact"
            className="mt-4 inline-flex w-fit text-[12px] font-semibold uppercase text-white transition-opacity hover:opacity-70"
          >
            READ MORE →
          </a>
        </div>
      </article>

    </div>

    {/* Service Buttons */}
    <div className="mt-6 flex justify-center gap-3">
      <a
        href="#services"
        className="inline-flex h-[38px] items-center justify-center rounded-[4px] bg-[#096B3B] px-5 text-[11px] font-semibold uppercase text-white transition-colors hover:bg-[#075C32]"
      >
        BROWSE ALL SERVICES
      </a>

      <a
        href="#services"
        className="inline-flex h-[38px] items-center justify-center rounded-[4px] bg-[#17181A] px-5 text-[11px] font-semibold uppercase text-white transition-colors hover:bg-black"
      >
        BROWSE SERVICES
      </a>
    </div>

  </div>
</section>

      {/* Feature / Why Choose Us Section */}
      <section className="bg-[#111111]">
        <div className="mx-auto flex min-h-[591px] w-full max-w-[1200px] items-center px-6 md:px-10 lg:px-0">
          <div className="grid w-full items-center gap-12 md:grid-cols-2 lg:gap-[72px]">

            {/* Feature Image */}
            <div className="relative flex justify-center md:justify-start">
              {/* Green decorative shape */}
              <div className="absolute bottom-[18px] left-[20px] z-0 h-[112px] w-[190px] bg-[#096B3B]" />

              <div className="relative z-10 h-[407px] w-full max-w-[430px] overflow-hidden">
                <Image
                  src="/features/why-choose-us.webp"
                  alt="Mechanic using Arthasee workshop system"
                  fill
                  className="object-cover"
                  sizes="(max-width: 768px) 100vw, 430px"
                />
              </div>
            </div>

            {/* Feature Content */}
            <div className="text-white">

              {/* Kicker */}
              <div className="mb-2 font-mono text-[12px] font-medium uppercase tracking-[0.08em] text-[#096B3B]">
                WHY CHOOSE US
              </div>

              {/* Heading */}
              <h2 className="font-['Montserrat'] text-[40px] font-bold uppercase leading-[0.95] tracking-[-0.02em] text-white">
                WHAT MAKES US
                <br />
                DIFFERENT
              </h2>

              {/* Feature List */}
              <div className="mt-8 space-y-6">

                {/* Quality Parts */}
                <div className="flex items-start gap-4">
                  <div className="mt-[2px] flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-full bg-[#096B3B] text-[12px] font-bold leading-none text-white">
                    ✓
                  </div>

                  <div>
                    <h3 className="font-['Montserrat'] text-[12px] font-bold uppercase leading-none text-white">
                      100% QUALITY PARTS
                    </h3>

                    <p className="mt-2 max-w-[430px] text-[11px] leading-[1.45] text-white/65">
                      We use only the highest quality parts for all repairs to
                      ensure durability.
                    </p>
                  </div>
                </div>

                {/* Certified Mechanics */}
                <div className="flex items-start gap-4">
                  <div className="mt-[2px] flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-full bg-[#096B3B] text-[12px] font-bold leading-none text-white">
                    ✓
                  </div>

                  <div>
                    <h3 className="font-['Montserrat'] text-[12px] font-bold uppercase leading-none text-white">
                      CERTIFIED MECHANICS
                    </h3>

                    <p className="mt-2 max-w-[430px] text-[11px] leading-[1.45] text-white/65">
                      Our team consists of certified professionals with years
                      of experience.
                    </p>
                  </div>
                </div>

                {/* Satisfaction Guarantee */}
                <div className="flex items-start gap-4">
                  <div className="mt-[2px] flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-full bg-[#096B3B] text-[12px] font-bold leading-none text-white">
                    ✓
                  </div>

                  <div>
                    <h3 className="font-['Montserrat'] text-[12px] font-bold uppercase leading-none text-white">
                      SATISFACTION GUARANTEE
                    </h3>

                    <p className="mt-2 max-w-[430px] text-[11px] leading-[1.45] text-white/65">
                      We guarantee our work. If you're not satisfied, we'll
                      make it right.
                    </p>
                  </div>
                </div>

              </div>

              {/* CTA */}
              <a
                href="#about"
                className="mt-8 inline-flex h-[38px] items-center justify-center rounded-[4px] bg-[#096B3B] px-5 font-['Montserrat'] text-[11px] font-semibold uppercase text-white transition-colors hover:bg-[#075C32]"
              >
                LEARN ABOUT MORE
              </a>

            </div>
          </div>
        </div>
      </section>

      {/* About Us Section */}
      <section
        id="about"
        className="relative bg-white px-[120px] py-[80px]"
      >
        <div className="mx-auto flex min-h-[454px] w-full max-w-[1200px] items-center">
          <div className="grid w-full items-center gap-[72px] md:grid-cols-[1fr_1fr]">

            {/* About Content */}
            <div className="relative pl-[140px]">

              {/* Decorative "ABOUT US" */}
              <div className="pointer-events-none absolute -left-[2px] top-[-58px] select-none font-['Montserrat'] text-[78px] font-bold italic uppercase leading-none tracking-[-0.04em] text-transparent [-webkit-text-stroke:1px_#E5E5E5]">
                ABOUT US
              </div>

              {/* Green decorative block */}
              <div className="absolute left-[51px] top-[24px] h-[73px] w-[170px] bg-[#096B3B]" />

              {/* Kicker */}
              <div className="relative mb-2 font-mono text-[12px] font-medium uppercase tracking-[0.08em] text-[#096B3B]">
                ABOUT US
              </div>

              {/* Heading */}
              <h2 className="relative max-w-[430px] font-['Montserrat'] text-[40px] font-bold uppercase leading-[0.95] tracking-[-0.02em] text-[#17181A]">
                THE STORY BEHIND
                <br />
                OUR SYSTEM WORKSHOP
              </h2>

              {/* Quote */}
              <p className="relative mt-4 max-w-[410px] text-[13px] font-semibold leading-[1.45] text-[#5B5B5B]">
                "Pelanggan adalah aset kami. Tanpa pelanggan dan sistem
                yang mengurus mereka, gudang dan montir sebanyak apa pun
                tidak ada gunanya."
              </p>

              {/* Description */}
              <p className="relative mt-5 max-w-[410px] text-[13px] leading-[1.6] text-[#6B6B6B]">
                Pelanggan itu aset kami. Tanpa pelanggan dan sistem yang
                mengurus mereka, gudang dan montir sebanyak apa pun tidak
                ada gunanya.
              </p>
            </div>

            {/* About Image */}
            <div className="relative h-[360px] w-full overflow-hidden">
              <Image
                src="/about/about-workshop.webp"
                alt="Mechanic working on a vehicle at an Arthasee workshop"
                fill
                className="object-cover"
                sizes="(max-width: 768px) 100vw, 446px"
              />

              {/* Green decorative shape */}
              <div className="absolute right-[-1px] top-[72px] h-[170px] w-[72px] bg-[#096B3B]" />
            </div>

          </div>
        </div>
      </section>

        {/* CTA Banner */}
        <section
          id="contact"
          className="relative h-[303px] w-full overflow-hidden bg-[#000000]"
        >
          {/* Background image */}
          <div
            className="absolute inset-0 bg-cover bg-center"
            style={{
              backgroundImage: "url('/cta-banner/cta-banner.webp')",
            }}
          />

          {/* Dark overlay */}
          <div className="absolute inset-0 bg-black/80" />

          {/* CTA Content */}
          <div className="relative mx-auto flex h-full w-full max-w-[1440px] items-center justify-center px-[120px]">
            <div className="flex flex-col items-center text-center">

              {/* Heading */}
              <h2 className="font-['Montserrat'] text-[28px] font-bold uppercase leading-none text-white">
                COBA DI BENGKEL ANDA
              </h2>

              {/* Supporting text */}
              <p className="mt-2 text-[11px] font-medium text-white/70">
                Gratis Untuk Mulai. Tidak Perlu Kartu Kredit.
              </p>

              {/* CTA */}
              <Link
                href="/register"
                className="mt-4 inline-flex h-[34px] items-center justify-center rounded-[3px] bg-[#096B3B] px-5 text-[10px] font-semibold uppercase tracking-[0.02em] text-white transition-colors hover:bg-[#075C32]"
              >
                UJI COBA GRATIS
              </Link>

            </div>
          </div>
        </section>

        {/* Testimonials Section */}
        <section
          id="testimonials"
          className="bg-[#111111] px-[120px] py-[80px]"
        >
          <div className="mx-auto w-full max-w-[1200px]">

            {/* Header */}
            <div className="relative mb-8">

              <div>
                <div className="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-[#096B3B]">
                  TESTIMONIALS
                </div>

                <h2 className="font-['Montserrat'] text-[28px] font-bold uppercase leading-[0.95] tracking-[-0.02em] text-white">
                  WHAT OUR CLIENTS
                  <br />
                  SAY ABOUT US
                </h2>
              </div>

              {/* Navigation */}
              <div className="absolute right-0 bottom-0 flex items-center gap-2">
                <button
                  type="button"
                  aria-label="Previous testimonial"
                  className="flex h-[28px] w-[28px] items-center justify-center rounded-[3px] bg-[#242424] text-[13px] text-white transition-colors hover:bg-[#096B3B]"
                >
                  ←
                </button>

                <button
                  type="button"
                  aria-label="Next testimonial"
                  className="flex h-[28px] w-[28px] items-center justify-center rounded-[3px] bg-[#242424] text-[13px] text-white transition-colors hover:bg-[#096B3B]"
                >
                  →
                </button>
              </div>

            </div>

            {/* Testimonial */}
            <article className="w-full rounded-[4px] bg-white p-5">

              {/* Stars */}
              <div className="text-[10px] tracking-[0.08em] text-[#F5A623]">
                ★★★★★
              </div>

              {/* Quote */}
              <p className="mt-3 max-w-[950px] text-[17px] font-medium leading-[1.6] text-[#444444] md:text-[18px] lg:text-[20px]">
                &quot;Pelanggan itu aset kami. Tanpa pelanggan dan sistem yang
                mengurus mereka, gudang dan montir sebanyak apa pun tidak ada
                gunanya. Arthasee mewujudkan impian saya untuk pelanggan dengan sistem yang handal &quot;
              </p>

              {/* Customer */}
              <div className="mt-4 flex items-center gap-3">

                <div className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full bg-[#D9471F] font-['Montserrat'] text-[12px] font-bold text-white">
                  AM
                </div>

                <div>
                  <div className="font-['Montserrat'] text-[10px] font-bold uppercase leading-none text-[#17181A]">
                    I MADE SUDARTA
                  </div>

                  <div className="mt-1 font-mono text-[8px] text-[#777777]">
                    CV. Arya Motor · Batam
                  </div>
                </div>

              </div>

            </article>

          </div>
        </section>

      <footer className="wrap">
        <div>© 2026 Arthasee. Dibuat di Batam.</div>
        <div className="mono">Fase 1 — CRM Bengkel</div>
      </footer>
    </>
  );
}
