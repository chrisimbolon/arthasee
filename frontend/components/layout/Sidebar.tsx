"use client";
// =============================================================================
// === frontend/components/layout/Sidebar.tsx ===
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import { organizationsApi } from "@/lib/api/organizations";
import { Car, LayoutDashboard, LogOut, Package, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/dashboard",           icon: LayoutDashboard, label: "Ringkasan" },
  { href: "/dashboard/customers", icon: Users,            label: "Pelanggan" },
  { href: "/dashboard/vehicles",  icon: Car,              label: "Kendaraan" },
  { href: "/dashboard/inventory", icon: Package,          label: "Inventaris" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [orgName, setOrgName] = useState<string | null>(null);

  useEffect(() => {
    organizationsApi.mine().then((res) => {
      if (res) setOrgName(res.organization.name);
    });
  }, []);

  return (
    <aside style={{ width: 240, minHeight: "100vh", background: "var(--paper-3)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", padding: "22px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 8px", marginBottom: 28 }}>
        <div style={{ width: 30, height: 30, background: "var(--ink)", borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--paper)", fontFamily: "'Big Shoulders Display', sans-serif", fontWeight: 900, fontSize: 16, transform: "rotate(-2deg)" }}>A</div>
        <div className="display" style={{ fontSize: 18 }}>Arthasee</div>
      </div>

      {orgName && (
        <div style={{ padding: "10px 12px", background: "var(--paper)", borderRadius: 6, marginBottom: 20 }}>
          <div style={{ fontSize: 10.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 2 }}>Bengkel Aktif</div>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{orgName}</div>
        </div>
      )}

      <nav style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
        {NAV.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link key={item.href} href={item.href}
              style={{
                display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", borderRadius: 6,
                fontSize: 14, fontWeight: active ? 600 : 500,
                color: active ? "var(--rust)" : "var(--ink-soft)",
                background: active ? "var(--rust-light)" : "transparent",
              }}>
              <Icon size={17} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14, marginTop: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{user?.full_name}</div>
        <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 10 }}>{user?.email}</div>
        <button onClick={logout} className="btn-ghost" style={{ width: "100%", justifyContent: "center", display: "flex", alignItems: "center", gap: 7, fontSize: 13 }}>
          <LogOut size={14} /> Keluar
        </button>
      </div>
    </aside>
  );
}
