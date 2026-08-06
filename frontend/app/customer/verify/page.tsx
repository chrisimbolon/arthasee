"use client";
// =============================================================================
// === frontend/app/customer/verify/page.tsx ===
// =============================================================================
// The page a customer actually lands on after clicking the magic
// link. Query-param routing (?token=), same static-export reasoning as every other param-driven page in this app.
import { customerAuthApi, customerTokenStorage } from "@/lib/api/customerAuth";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function VerifyContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [status, setStatus] = useState<"verifying" | "success" | "error">("verifying");

  useEffect(() => {
    if (!token) { setStatus("error"); return; }
    customerAuthApi.verifyMagicLink(token)
      .then((session) => {
        customerTokenStorage.set(session.access);
        setStatus("success");
        // Real navigation, not router.push — this page has no
        // guaranteed router context outside the Suspense boundary,
        // and a hard redirect is simpler and just as correct here
        // since this page has nothing worth keeping in history.
        window.location.href = "/customer/dashboard";
      })
      .catch(() => setStatus("error"));
  }, [token]);

  if (status === "error") {
    return (
      <div style={{ maxWidth: 400, margin: "100px auto", textAlign: "center", padding: "0 20px" }}>
        <p style={{ fontSize: 15 }}>Link tidak valid atau sudah kadaluarsa.</p>
        <Link href="/customer/login" style={{ color: "var(--rust)", fontSize: 13.5, marginTop: 10, display: "inline-block" }}>
          Kirim link baru
        </Link>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "60vh", gap: 8, color: "var(--steel)" }}>
      <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> Memverifikasi…
    </div>
  );
}

export default function CustomerVerifyPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>Memuat…</div>}>
      <VerifyContent />
    </Suspense>
  );
}
