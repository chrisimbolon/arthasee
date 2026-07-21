// =============================================================================
// === frontend/lib/api.ts ===
// =============================================================================
import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { tokenStorage } from "./auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({ baseURL: API_BASE_URL });

api.interceptors.request.use((config) => {
  const token = tokenStorage.getAccess();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Extends the request config with a marker so a failed-refresh retry
// never loops forever — without this, a genuinely expired refresh
// token would keep re-triggering itself on every retried request.
interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStorage.getRefresh();
  if (!refresh) throw new Error("No refresh token available");

  // Concurrent 401s (several requests in flight at once) share one
  // in-flight refresh call instead of each independently hitting
  // /api/auth/refresh/ — avoids a thundering-herd of refresh requests.
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE_URL}/api/auth/refresh/`, { refresh })
      .then((res) => {
        const newAccess = res.data.access as string;
        tokenStorage.setAccess(newAccess);
        return newAccess;
      })
      .finally(() => { refreshPromise = null; });
  }
  // Non-null assertion, not a shortcut around a real gap: at this
  // point refreshPromise was either just assigned above, or was
  // already non-null when the `if` check ran. TypeScript can't
  // prove this on its own because the value is reassigned inside a
  // .finally() closure, which breaks its control-flow narrowing —
  // the logic itself is sound, the type system just can't see it.
  return refreshPromise!;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined;
    if (error.response?.status === 401 && config && !config._retried) {
      config._retried = true;
      try {
        const newAccess = await refreshAccessToken();
        config.headers = config.headers ?? {};
        config.headers.Authorization = `Bearer ${newAccess}`;
        return api(config);
      } catch {
        tokenStorage.clear();
        if (typeof window !== "undefined") window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;
