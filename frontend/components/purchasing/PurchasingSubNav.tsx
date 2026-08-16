"use client";
// =============================================================================
// === frontend/components/purchasing/PurchasingSubNav.tsx ===
// =============================================================================
import Link from "next/link";
import { usePathname } from "next/navigation";

const SUBNAV = [
  { href: "/dashboard/purchasing/suppliers",         label: "Supplier" },
  { href: "/dashboard/purchasing/purchase-orders",   label: "Purchase Order" },
  { href: "/dashboard/purchasing/goods-received",    label: "Penerimaan Barang" },
  { href: "/dashboard/purchasing/supplier-invoices", label: "Invoice Supplier" },
  { href: "/dashboard/purchasing/purchase-returns",  label: "Retur Pembelian" },
];

export default function PurchasingSubNav() {
  const pathname = usePathname();

  return (
    <div style={{ display: "flex", gap: 20, marginBottom: 24, borderBottom: "1px solid var(--line)" }}>
      {SUBNAV.map((item) => {
        // startsWith, not exact match — any future detail page under
        // one of these sections should still show its own tab as
        // active, same prefix-matching reasoning the Sidebar itself
        // already uses for "Akuntansi".
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
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
