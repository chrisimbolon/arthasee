// =============================================================================
// === frontend/context/AuthContext.tsx ===
// =============================================================================
"use client";

import { authApi, RegisterPayload, User } from "@/lib/api/auth";
import { Organization, organizationsApi } from "@/lib/api/organizations";
import { tokenStorage } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

interface AuthContextValue {
  user:      User | null;
  // 29 Aug 2026 — real onboarding gate, Chris's own confirmed
  // design. organization is fetched ALONGSIDE user, not lazily by
  // whichever page happens to need it — the mandatory first-login
  // gate lives in the shared dashboard layout and needs
  // organization.onboarding_completed available the moment loading
  // finishes, not after a second, page-specific fetch.
  organization: Organization | null;
  loading:   boolean;
  login:     (email: string, password: string) => Promise<void>;
  register:  (payload: RegisterPayload) => Promise<void>;
  logout:    () => void;
  // Real, explicit refresh — called once the onboarding overlay's
  // own form succeeds, so the gate can re-check
  // organization.onboarding_completed and dismiss itself without a
  // full page reload.
  refreshOrganization: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser]               = useState<User | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [loading, setLoading]         = useState(true);
  const router = useRouter();

  useEffect(() => {
    const token = tokenStorage.getAccess();
    if (!token) { setLoading(false); return; }
    // Fetched together, not sequentially — loading only clears once
    // BOTH are known, so the dashboard layout never briefly renders
    // real content before organization state arrives and then has
    // to yank the person into the gate a moment later.
    Promise.all([authApi.me(), organizationsApi.mine()])
      .then(([me, orgResult]) => {
        setUser(me);
        setOrganization(orgResult?.organization ?? null);
      })
      .catch(() => tokenStorage.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    await authApi.login(email, password);
    const [me, orgResult] = await Promise.all([authApi.me(), organizationsApi.mine()]);
    setUser(me);
    setOrganization(orgResult?.organization ?? null);
    router.push("/dashboard");
  };

  const register = async (payload: RegisterPayload) => {
    const newUser = await authApi.register(payload);
    setUser(newUser);
    // A brand-new registration always has a real, fresh Organization
    // (RegisterView.post() creates user/org/membership together, one
    // atomic transaction) — fetched here so the gate has real state
    // to check the moment the new owner lands on /dashboard, not
    // organization: null defaulting to "skip the gate" by accident.
    const orgResult = await organizationsApi.mine();
    setOrganization(orgResult?.organization ?? null);
    router.push("/dashboard");
  };

  const logout = () => {
    authApi.logout();
    setUser(null);
    setOrganization(null);
    router.push("/login");
  };

  const refreshOrganization = async () => {
    const orgResult = await organizationsApi.mine();
    setOrganization(orgResult?.organization ?? null);
  };

  return (
    <AuthContext.Provider value={{ user, organization, loading, login, register, logout, refreshOrganization }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
