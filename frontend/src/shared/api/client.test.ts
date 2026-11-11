import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient, apiUrl, getCsrfToken, setCsrfToken } from "./client";

interface AdapterSpy {
  adapter: AxiosAdapter;
  spy: ReturnType<typeof vi.fn>;
}

function okAdapter(): AdapterSpy {
  const spy = vi.fn(async (config: InternalAxiosRequestConfig) => ({
    data: null,
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  }));
  return { adapter: spy as unknown as AxiosAdapter, spy };
}

function failingAdapter(status: number): AdapterSpy {
  const spy = vi.fn(async (config: InternalAxiosRequestConfig) => {
    throw new AxiosError("Request failed", "ERR_BAD_RESPONSE", config, undefined, {
      data: null,
      status,
      statusText: "Error",
      headers: {},
      config,
    });
  });
  return { adapter: spy as unknown as AxiosAdapter, spy };
}

describe("centralised API client", () => {
  afterEach(() => {
    setCsrfToken(null);
  });

  it("keeps the CSRF token in memory only", () => {
    expect(getCsrfToken()).toBeNull();
    setCsrfToken("token-1");
    expect(getCsrfToken()).toBe("token-1");
    expect(window.localStorage.getItem("csrf")).toBeNull();
    expect(window.sessionStorage.getItem("csrf")).toBeNull();
  });

  it("attaches the token to state-changing requests", async () => {
    setCsrfToken("token-1");
    const { adapter, spy } = okAdapter();

    await apiClient.request({ method: "post", url: "/projects", adapter });

    const config = spy.mock.calls[0][0] as InternalAxiosRequestConfig;
    expect(config.headers.get("X-CSRF-Token")).toBe("token-1");
  });

  it("does not attach the token to safe requests", async () => {
    setCsrfToken("token-1");
    const { adapter, spy } = okAdapter();

    await apiClient.request({ method: "get", url: "/projects", adapter });

    const config = spy.mock.calls[0][0] as InternalAxiosRequestConfig;
    expect(config.headers.get("X-CSRF-Token")).toBeUndefined();
  });

  it("omits the header when no token is available", async () => {
    const { adapter, spy } = okAdapter();

    await apiClient.request({ method: "delete", url: "/projects/1", adapter });

    const config = spy.mock.calls[0][0] as InternalAxiosRequestConfig;
    expect(config.headers.get("X-CSRF-Token")).toBeUndefined();
  });

  it("announces a 401 so the auth provider can clear the session", async () => {
    const listener = vi.fn();
    window.addEventListener("auth:unauthorized", listener);

    await expect(
      apiClient.request({ url: "/auth/me", adapter: failingAdapter(401).adapter }),
    ).rejects.toBeInstanceOf(AxiosError);

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("auth:unauthorized", listener);
  });

  it("does not announce other failures", async () => {
    const listener = vi.fn();
    window.addEventListener("auth:unauthorized", listener);

    await expect(
      apiClient.request({ url: "/projects", adapter: failingAdapter(500).adapter }),
    ).rejects.toBeInstanceOf(AxiosError);

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener("auth:unauthorized", listener);
  });

  it("builds same-origin resource URLs from the API base", () => {
    expect(apiUrl("/projects/1/download")).toMatch(/\/api\/v1\/projects\/1\/download$/);
  });
});
