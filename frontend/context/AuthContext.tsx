// =============================================================================
// === frontend/context/AuthContext.tsx ===
// =============================================================================
"use client";

import { authApi, RegisterPayload, User } from "@/lib/api/auth";
import { tokenStorage } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

interface AuthContextValue {
  user:      User | null;
  loading:   boolean;
  login:     (email: string, password: string) => Promise<void>;
  register:  (payload: RegisterPayload) => Promise<void>;
  logout:    () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser]       = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const token = tokenStorage.getAccess();
    if (!token) { setLoading(false); return; }
    authApi.me()
      .then(setUser)
      .catch(() => tokenStorage.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    await authApi.login(email, password);
    const me = await authApi.me();
    setUser(me);
    router.push("/dashboard");
  };

  const register = async (payload: RegisterPayload) => {
    const newUser = await authApi.register(payload);
    setUser(newUser);
    router.push("/dashboard");
  };

  const logout = () => {
    authApi.logout();
    setUser(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
