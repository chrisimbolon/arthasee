"use client";
// =============================================================================
// === frontend/app/page.tsx ===
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function RootPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading) router.replace(user ? "/dashboard" : "/login");
  }, [loading, user, router]);

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--steel)" }}>
      <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
    </div>
  );
}
