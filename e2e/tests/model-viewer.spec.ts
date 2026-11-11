import { expect, test } from "@playwright/test";

import { createProjectThroughApi, deleteProjectThroughApi, registerThroughUi, uniqueEmail } from "./helpers";

test.describe("result workspace states (E2E-12, E2E-13)", () => {
  test("a project without a result explains what to do instead of showing an empty canvas", async ({
    page,
  }) => {
    await registerThroughUi(page, uniqueEmail("viewer-empty"));
    const projectId = await createProjectThroughApi(page.request, "No result project", "OBJECT");

    await page.goto(`/projects/${projectId}/result`);

    await expect(
      page.getByText("3D-результат ещё не создан", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("canvas")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Перейти к проекту" })).toBeVisible();
    await deleteProjectThroughApi(page, projectId);
  });

  test("the result route is protected", async ({ page }) => {
    await page.goto("/projects/00000000-0000-4000-8000-000000000000/result");

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Вход" })).toBeVisible();
  });
});
