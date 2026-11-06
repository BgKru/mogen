import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../../test/render";
import { useAuth } from "./auth-context";
import { AuthProvider } from "./AuthProvider";

const mocks = vi.hoisted(() => ({
  fetchCurrentUser: vi.fn(),
  fetchCsrfToken: vi.fn(),
  loginUser: vi.fn(),
  registerUser: vi.fn(),
  logoutUser: vi.fn(),
}));

vi.mock("../../features/auth/api/authApi", () => ({
  fetchCurrentUser: mocks.fetchCurrentUser,
  fetchCsrfToken: mocks.fetchCsrfToken,
  loginUser: mocks.loginUser,
  registerUser: mocks.registerUser,
  logoutUser: mocks.logoutUser,
}));

function Probe() {
  const { status, logout } = useAuth();
  return (
    <div>
      <span>{status}</span>
      <button type="button" onClick={() => void logout()}>
        logout
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("initialises an existing session and clears it on logout", async () => {
    mocks.fetchCurrentUser.mockResolvedValue({
      id: "user-1",
      email: "user@example.com",
      createdAt: "2026-11-05T12:00:00Z",
    });
    mocks.fetchCsrfToken.mockResolvedValue("csrf-token");
    mocks.logoutUser.mockResolvedValue(undefined);

    renderWithProviders(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(await screen.findByText("authenticated")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(await screen.findByText("unauthenticated")).toBeInTheDocument();
    expect(mocks.logoutUser).toHaveBeenCalledTimes(1);
  });

  it("starts unauthenticated when no session exists", async () => {
    mocks.fetchCurrentUser.mockRejectedValue(new Error("unauthorized"));

    renderWithProviders(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(await screen.findByText("unauthenticated")).toBeInTheDocument();
  });
});
