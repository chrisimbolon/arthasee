"use client";
// =============================================================================
// === frontend/components/settings/SettingsSubNav.tsx ===
// =============================================================================
// 8 Oct 2026 — Pengaturan Periode Akuntansi. Before this, /dashboard/settings/
// only ever had one real page (Pengaturan Bengkel), so there was nothing to
// switch between — adding a second settings destination is the reason this
// now needs its own nav, same pattern AccountingSubNav already established
// for /dashboard/accounting's own several pages.
import Link from "next/link";
import { usePathname } from "next/navigation";

const SUBNAV = [
  { href: "/dashboard/settings/organization", label: "Profil Bengkel" },
  { href: "/dashboard/settings/accounting-period", label: "Periode Akuntansi" },
];

export default function SettingsSubNav() {
  const pathname = usePathname();

  return (
    <div style={{ display: "flex", gap: 20, marginBottom: 24, borderBottom: "1px solid var(--line)" }}>
      {SUBNAV.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            style={{
              fontSize: 13.5, fontWeight: active ? 600 : 500, padding: "0 2px 10px",
              color: active ? "var(--rust)" : "var(--steel)",
              borderBottom: active ? "2px solid var(--rust)" : "2px solid transparent",
              marginBottom: -1,
            }}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
