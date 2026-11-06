import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/errors";
import { createAuthValue, renderWithProviders } from "../../test/render";
import { LoginPage } from "./LoginPage";

function renderLogin(
  auth = createAuthValue({ status: "unauthenticated", isAuthenticated: false, user: null }),
) {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/dashboard" element={<div>Панель проектов</div>} />
    </Routes>,
    { route: "/login", auth },
  );
}

describe("LoginPage", () => {
  it("shows client-side validation messages", async () => {
    renderLogin();

    fireEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Введите email.")).toBeInTheDocument();
    expect(await screen.findByText("Введите пароль.")).toBeInTheDocument();
  });

  it("shows the authentication error from the API", async () => {
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "Invalid" }),
      );
    renderLogin(
      createAuthValue({ status: "unauthenticated", isAuthenticated: false, user: null, login }),
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Неверный email или пароль.")).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith({ email: "user@example.com", password: "password123" });
  });

  it("navigates to the dashboard after a successful login", async () => {
    const login = vi.fn().mockResolvedValue({ id: "user-1", email: "user@example.com" });
    renderLogin(
      createAuthValue({ status: "unauthenticated", isAuthenticated: false, user: null, login }),
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Панель проектов")).toBeInTheDocument();
    await waitFor(() => expect(login).toHaveBeenCalledTimes(1));
  });

  it("redirects an authenticated user to the dashboard", () => {
    renderLogin(createAuthValue());

    expect(screen.getByText("Панель проектов")).toBeInTheDocument();
  });
});
