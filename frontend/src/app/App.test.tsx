import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../shared/api/errors";
import { AppProviders } from "./providers/AppProviders";

const authMocks = vi.hoisted(() => ({
  fetchCurrentUser: vi.fn(),
  fetchCsrfToken: vi.fn(),
}));

const projectMocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
}));

vi.mock("../features/auth/api/authApi", () => ({
  fetchCurrentUser: authMocks.fetchCurrentUser,
  fetchCsrfToken: authMocks.fetchCsrfToken,
  loginUser: vi.fn(),
  registerUser: vi.fn(),
  logoutUser: vi.fn(),
}));

vi.mock("../features/projects/api/projectsApi", () => ({
  listProjects: projectMocks.listProjects,
  getProject: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
}));

const USER = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  email: "user@example.com",
  createdAt: "2026-11-05T12:00:00Z",
};

function renderApp() {
  return render(<AppProviders />);
}

describe("application shell", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    authMocks.fetchCurrentUser.mockRejectedValue(
      new ApiError({ status: 401, code: "UNAUTHORIZED", message: "auth required" }),
    );
    authMocks.fetchCsrfToken.mockResolvedValue("csrf-token");
    projectMocks.listProjects.mockResolvedValue({
      items: [],
      totalCount: 0,
      limit: 20,
      offset: 0,
    });
  });

  it("renders the landing page at the root route", async () => {
    renderApp();

    expect(
      screen.getByRole("heading", { name: "Превратите фотографии в 3D-миры" }),
    ).toBeInTheDocument();
    await act(async () => {
      await Promise.resolve();
    });
  });

  it("renders the not-found page for an unknown route", async () => {
    window.history.pushState({}, "", "/this-route-does-not-exist");

    renderApp();

    expect(screen.getByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
    await act(async () => {
      await Promise.resolve();
    });
  });

  it("redirects an unauthenticated user from a protected route to login", async () => {
    window.history.pushState({}, "", "/dashboard");

    renderApp();

    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
  });

  it("renders the dashboard for an authenticated user", async () => {
    authMocks.fetchCurrentUser.mockResolvedValue(USER);
    window.history.pushState({}, "", "/dashboard");

    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Мои проекты", level: 1 }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Пока нет проектов")).toBeInTheDocument();
  });
});
