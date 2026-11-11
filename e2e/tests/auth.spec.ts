import { expect, test } from "@playwright/test";

import { PASSWORD, loginThroughUi, registerThroughUi, uniqueEmail } from "./helpers";

test.describe("authentication workflows (E2E-01..03)", () => {
  test("a new user can register and reaches the dashboard", async ({ page }) => {
    const email = uniqueEmail("register");

    await registerThroughUi(page, email);

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Мои проекты" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Создать проект" }).first()).toBeVisible();
  });

  test("logout terminates the session and protects the dashboard", async ({ page }) => {
    await registerThroughUi(page, uniqueEmail("logout"));

    await page.getByRole("button", { name: "Выйти" }).first().click();
    // Clearing the session unmounts the protected layout, so the router lands
    // on the public login page; either way the session is terminated.
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Вход" })).toBeVisible();
  });

  test("a registered user can log in again", async ({ page }) => {
    const email = uniqueEmail("login");
    await registerThroughUi(page, email);
    await page.getByRole("button", { name: "Выйти" }).first().click();
    // Clearing the session unmounts the protected layout, so the router lands
    // on the public login page; either way the session is terminated.
    await expect(page).toHaveURL(/\/login$/);

    await loginThroughUi(page, email);

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Мои проекты" })).toBeVisible();
  });

  test("a wrong password is rejected with a readable error", async ({ page }) => {
    const email = uniqueEmail("wrong-password");
    await registerThroughUi(page, email);
    await page.getByRole("button", { name: "Выйти" }).first().click();

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Пароль", { exact: true }).fill(`${PASSWORD}-wrong`);
    await page.getByRole("button", { name: "Войти" }).click();

    await expect(page.getByRole("alert").filter({ hasText: /Неверн|Ошибка|не удалось/i })).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });
});
