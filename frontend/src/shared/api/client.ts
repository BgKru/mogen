import axios from "axios";

/** In-memory CSRF token. Never persisted to localStorage or sessionStorage. */
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

/**
 * Centralised API client.
 *
 * The base URL is relative in development so requests go through the Vite
 * proxy and stay same-origin. Cookies carry the session; the signed CSRF token
 * is kept in memory and copied into the header of state-changing requests.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  withCredentials: true,
  timeout: 30_000,
  headers: { Accept: "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const method = (config.method ?? "get").toUpperCase();
  const isSafeMethod = method === "GET" || method === "HEAD" || method === "OPTIONS";
  if (!isSafeMethod && csrfToken) {
    config.headers.set("X-CSRF-Token", csrfToken);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const status = axios.isAxiosError(error) ? error.response?.status : undefined;
    if (status === 401) {
      // AuthProvider listens for this event and clears the session state.
      window.dispatchEvent(new CustomEvent("auth:unauthorized"));
    }
    return Promise.reject(error);
  },
);

/**
 * Build a same-origin URL for resources fetched outside Axios, such as the
 * authenticated GLB download that the browser streams directly.
 */
export function apiUrl(path: string): string {
  return apiClient.getUri({ url: path });
}
