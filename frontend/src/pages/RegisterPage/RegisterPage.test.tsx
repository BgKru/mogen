import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/errors";
import { createAuthValue, renderWithProviders } from "../../test/render";
import { RegisterPage } from "./RegisterPage";

function renderRegister(
  auth = createAuthValue({ status: "unauthenticated", isAuthenticated: false, user: null }),
) {
  return renderWithProviders(
    <Routes>
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/dashboard" element={<div>Панель проектов</div>} />
    </Routes>,
    { route: "/register", auth },
  );
}

function fillForm(password = "password123", confirmation = "password123") {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("Повторите пароль"), {
    target: { value: confirmation },
  });
}

describe("RegisterPage", () => {
  it("requires a password of at least eight characters", async () => {
    renderRegister();
    fillForm("short", "short");

    fireEvent.click(screen.getByRole("button", { name: "Создать аккаунт" }));

    expect(
      await screen.findByText("Пароль должен содержать минимум 8 символов."),
    ).toBeInTheDocument();
  });

  it("rejects mismatched passwords", async () => {
    renderRegister();
    fillForm("password123", "password124");

    fireEvent.click(screen.getByRole("button", { name: "Создать аккаунт" }));

    expect(await screen.findByText("Пароли не совпадают.")).toBeInTheDocument();
  });

  it("registers without sending the confirmation field and navigates to the dashboard", async () => {
    const register = vi.fn().mockResolvedValue({ id: "user-1", email: "user@example.com" });
    renderRegister(
      createAuthValue({ status: "unauthenticated", isAuthenticated: false, user: null, register }),
    );
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: "Создать аккаунт" }));

    expect(await screen.findByText("Панель проектов")).toBeInTheDocument();
    await waitFor(() =>
      expect(register).toHaveBeenCalledWith({
        email: "user@example.com",
        password: "password123",
      }),
    );
  });

  it("shows a duplicate-email error from the API", async () => {
    const register = vi
      .fn()
      .mockRejectedValue(
        new ApiError({ status: 400, code: "EMAIL_ALREADY_REGISTERED", message: "exists" }),
      );
    renderRegister(
      createAuthValue({ status: "unauthenticated", isAuthenticated: false, user: null, register }),
    );
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: "Создать аккаунт" }));

    expect(await screen.findByText("Аккаунт с таким email уже существует.")).toBeInTheDocument();
  });
});
