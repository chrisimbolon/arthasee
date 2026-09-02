"use client";
// =============================================================================
// === frontend/components/accounting/AccountingSubNav.tsx ===
// =============================================================================
import Link from "next/link";
import { usePathname } from "next/navigation";

// Task 5.2 — /journal now exists, extending the list per the comment
// this file shipped with in Task 5.1.
// 27 Aug 2026 — /operating-expenses added, Made's own confirmed real
// request: a guided alternative to the generic Manual Adjusting
// Journal for a recurring operating cost.
// 29 Aug 2026 — /assets added: real fixed asset register & automated
// depreciation, Made's own confirmed request.
// 1 Sep 2026 — /kas-harian added: Kas Harian, a plain-language daily
// cash view distinct from /journal (which stays exactly as-is,
// audit-grade, untouched) — Made's own confirmed real request.
const SUBNAV = [
  { href: "/dashboard/accounting/reports",  label: "Laporan" },
  { href: "/dashboard/accounting/accounts", label: "Daftar Akun" },
  { href: "/dashboard/accounting/journal",  label: "Jurnal" },
  { href: "/dashboard/accounting/kas-harian", label: "Kas Harian" },
  { href: "/dashboard/accounting/operating-expenses", label: "Beban Operasional" },
  { href: "/dashboard/accounting/assets", label: "Aset Tetap" },
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
