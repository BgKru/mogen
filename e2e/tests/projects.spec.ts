import { expect, test } from "@playwright/test";

import {
  OBJECT_IMAGE,
  createProjectThroughUi,
  deleteProjectThroughUi,
  registerThroughUi,
  uniqueEmail,
} from "./helpers";

test.describe("project management workflows (E2E-04..06)", () => {
  test("an object project is created, listed and deleted", async ({ page }) => {
    const projectName = `E2E проект ${Date.now()}`;
    await registerThroughUi(page, uniqueEmail("projects"));

    await createProjectThroughUi(page, {
      name: projectName,
      type: "OBJECT",
      files: [OBJECT_IMAGE],
    });

    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    await expect(page.getByText("1 изображение", { exact: true })).toBeVisible();

    await page.goto("/dashboard");
    await expect(page.getByRole("link", { name: `Открыть проект ${projectName}` })).toBeVisible();

    await page.getByRole("link", { name: `Открыть проект ${projectName}` }).click();
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

    await deleteProjectThroughUi(page);

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("link", { name: `Открыть проект ${projectName}` })).toHaveCount(0);
  });

  test("invalid content is rejected before a project is created", async ({ page }) => {
    await registerThroughUi(page, uniqueEmail("invalid-upload"));
    await page.goto("/projects/new");

    await page.locator('input[type="file"]').setInputFiles({
      name: "not-an-image.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("this is definitely not a JPEG"),
    });

    await expect(page.getByRole("alert").filter({ hasText: /JPG|PNG|изображен/i })).toBeVisible();
    await expect(page.getByRole("button", { name: "Создать проект" })).toBeDisabled();
  });
});
