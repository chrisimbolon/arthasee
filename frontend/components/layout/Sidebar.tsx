"use client";
// =============================================================================
// === frontend/components/layout/Sidebar.tsx ===
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import { organizationsApi } from "@/lib/api/organizations";
import { Activity, Briefcase, Calculator, Calendar, Car, LayoutDashboard, LogOut, Mail, Package, Phone, Settings, ShoppingCart, TrendingUp, Users, Wrench } from "lucide-react";
// import { Activity, Briefcase, Car, LayoutDashboard, LogOut, Mail, Package, Phone, Settings, Users, Wrench } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/dashboard",           icon: LayoutDashboard, label: "Ringkasan" },
  { href: "/dashboard/active-jobs", icon: Activity,       label: "Pekerjaan Aktif" },
  { href: "/dashboard/appointments", icon: Calendar,      label: "Janji Temu" },  
  { href: "/dashboard/customers", icon: Users,            label: "Pelanggan" },
  { href: "/dashboard/vehicles",  icon: Car,              label: "Kendaraan" },
  { href: "/dashboard/inventory", icon: Package,          label: "Spare Parts & Fluids" },
  { href: "/dashboard/purchasing/suppliers", icon: ShoppingCart, label: "Pembelian" },  
  { href: "/dashboard/leads",     icon: Phone,            label: "Leads" },
  { href: "/dashboard/contracts", icon: Briefcase,        label: "Kontrak" },
  { href: "/dashboard/mechanics", icon: Wrench,           label: "Mekanik" },
   // Task 4.2 — points at /reports for now, the only page built so
  // far; /accounts and /journal are queued as separate, later
  // deliveries per Chris's own "step by step" call. Placed here,
  // not grouped with Pengaturan below — financial reporting is a
  // real operational screen someone checks regularly, not an
  // occasional admin task.
  { href: "/dashboard/accounting/reports", icon: Calculator, label: "Akuntansi" },
  { href: "/dashboard/analytics",          icon: TrendingUp, label: "Pertumbuhan" },  

  // D1, 6 Aug — Made's own confirmed answer: a real, day-to-day
  // operational feature (an official letter registry), not an
  // occasional admin task like Pengaturan below — belongs in the
  // main nav, not the account section.
  { href: "/dashboard/letters",   icon: Mail,             label: "Surat Masuk/Keluar" },
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

  const settingsActive = pathname === "/dashboard/settings/organization";

  return (
    <aside style={{ width: 240, minHeight: "100vh", background: "var(--paper-3)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", padding: "22px 16px" }}>
        
  
        <div
          style={{
          display: "flex",
          alignItems: "center",
          padding: "0 8px",
          marginBottom: 28,
          }}
        >
        <Image
            src="/Logo-teks-dark.png"
            alt="Arthasee"
    width={150}
    height={40}
    priority
    style={{
      width: "150px",
      height: "auto",
    }}
  />
</div>      
      {/* <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 8px", marginBottom: 28 }}>
        <div style={{ width: 30, height: 30, background: "var(--ink)", borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--paper)", fontFamily: "'Big Shoulders Display', sans-serif", fontWeight: 900, fontSize: 16, transform: "rotate(-2deg)" }}>A</div>
        <div className="display" style={{ fontSize: 18 }}>Arthasee</div>
      </div> */}

      {orgName && (
        <div style={{ padding: "10px 12px", background: "var(--paper)", borderRadius: 6, marginBottom: 20 }}>
          <div style={{ fontSize: 10.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 2 }}>Bengkel Aktif</div>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{orgName}</div>
        </div>
      )}

      <nav style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
        {NAV.map((item) => {
          // Every other nav item maps to exactly one page, so exact
          // match is correct and stays unchanged. Accounting is the
          // first section with multiple pages under one nav entry
          // (/reports now, /accounts and /journal later) — without
          // this, visiting those future pages would show NO nav item
          // as active at all. Scoped to this one item specifically,
          // not a blanket startsWith() for everyone, since I can't
          // verify every other existing page doesn't rely on the
          // exact-match quirk in some way not visible here.
          const active = (item.href.startsWith("/dashboard/accounting") || item.href.startsWith("/dashboard/purchasing"))
            ? pathname.startsWith(item.href.startsWith("/dashboard/accounting") ? "/dashboard/accounting" : "/dashboard/purchasing")
            : pathname === item.href;
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
        <Link href="/dashboard/settings/organization"
          style={{
            display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", borderRadius: 6,
            fontSize: 13.5, fontWeight: settingsActive ? 600 : 500,
            color: settingsActive ? "var(--rust)" : "var(--ink-soft)",
            background: settingsActive ? "var(--rust-light)" : "transparent",
            marginBottom: 10,
          }}>
          <Settings size={16} /> Pengaturan Bengkel
        </Link>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{user?.full_name}</div>
        <div style={{ fontSize: 12, color: "var(--steel)", marginBottom: 10 }}>{user?.email}</div>
        <button onClick={logout} className="btn-ghost" style={{ width: "100%", justifyContent: "center", display: "flex", alignItems: "center", gap: 7, fontSize: 13 }}>
          <LogOut size={14} /> Keluar
        </button>
      </div>
    </aside>
  );
}
