"use client";
// =============================================================================
// === frontend/components/accounting/AccountingSubNav.tsx ===
// =============================================================================
import Link from "next/link";
import { usePathname } from "next/navigation";

// Task 5.2 — /journal now exists, extending the list per the comment
// this file shipped with in Task 5.1.
const SUBNAV = [
  { href: "/dashboard/accounting/reports",  label: "Laporan" },
  { href: "/dashboard/accounting/accounts", label: "Daftar Akun" },
  { href: "/dashboard/accounting/journal",  label: "Jurnal" },
];

export default function AccountingSubNav() {
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
