// =============================================================================
// === frontend/lib/auth.ts ===
// =============================================================================
const ACCESS_KEY  = "arthasee_access";
const REFRESH_KEY = "arthasee_refresh";

export const tokenStorage = {
  getAccess():  string | null { return typeof window === "undefined" ? null : localStorage.getItem(ACCESS_KEY); },
  getRefresh(): string | null { return typeof window === "undefined" ? null : localStorage.getItem(REFRESH_KEY); },
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  setAccess(access: string) {
    localStorage.setItem(ACCESS_KEY, access);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};
