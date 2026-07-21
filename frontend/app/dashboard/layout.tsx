"use client";
// =============================================================================
// === frontend/app/dashboard/layout.tsx ===
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import Sidebar from "@/components/layout/Sidebar";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--steel)" }}>
        <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  return (
    <div style={{ display: "flex" }}>
      <Sidebar />
      <main style={{ flex: 1, padding: "32px 40px", maxWidth: 1100 }}>
        {children}
      </main>
    </div>
  );
}
