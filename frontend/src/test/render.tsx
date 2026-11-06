import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { AuthContext, type AuthContextValue } from "../app/providers/auth-context";
import { ToastProvider } from "../app/providers/ToastProvider";
import type { User } from "../shared/types/api";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

const DEFAULT_USER: User = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  email: "user@example.com",
  createdAt: "2026-11-05T12:00:00Z",
};

export function createAuthValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    user: DEFAULT_USER,
    status: "authenticated",
    isAuthenticated: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  };
}

interface RenderOptions {
  route?: string;
  auth?: AuthContextValue;
  queryClient?: QueryClient;
}

/** Render a component with the query client, toasts, router and optional auth. */
export function renderWithProviders(
  ui: ReactElement,
  { route = "/", auth, queryClient }: RenderOptions = {},
) {
  const client = queryClient ?? createTestQueryClient();
  const content = auth ? <AuthContext.Provider value={auth}>{ui}</AuthContext.Provider> : ui;

  return {
    queryClient: client,
    ...render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={[route]}>{content}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    ),
  };
}
