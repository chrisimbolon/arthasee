// =============================================================================
// === frontend/lib/api/auth.ts ===
// =============================================================================
import api from "@/lib/api";
import { tokenStorage } from "@/lib/auth";

export interface User {
  id:        string;
  email:     string;
  full_name: string;
  phone:     string;
  role:      "owner" | "super_admin";
}

export interface RegisterPayload {
  email:             string;
  password:          string;
  full_name:         string;
  phone?:            string;
  organization_name: string;
}

export const authApi = {
  async login(email: string, password: string): Promise<void> {
    const { data } = await api.post("/api/auth/login/", { email, password });
    tokenStorage.set(data.access, data.refresh);
  },

  async register(payload: RegisterPayload): Promise<User> {
    const { data } = await api.post("/api/auth/register/", payload);
    tokenStorage.set(data.tokens.access, data.tokens.refresh);
    return data.user;
  },

  async me(): Promise<User> {
    const { data } = await api.get("/api/auth/me/");
    return data.user;
  },

  logout() {
    tokenStorage.clear();
  },
};
