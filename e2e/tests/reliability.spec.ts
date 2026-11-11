import { expect, test } from "@playwright/test";

import {
  UNRELATED_IMAGES,
  createProjectThroughUi,
  deleteProjectThroughApi,
  deleteProjectThroughUi,
  registerThroughUi,
  startGeneration,
  uniqueEmail,
} from "./helpers";

/**
 * User-visible failure and cancellation paths (E2E-10, E2E-11, roadmap 9.4).
 *
 * Parallel recovery scenarios (expired lease, duplicate delivery, database
 * failure during result registration) are deterministic backend integration
 * tests; the Phase 8 live drills cover infrastructure interruptions. This spec
 * proves the two paths a browser user can actually drive.
 */
test.describe("failure workflows", () => {
  test("a failed reconstruction is reported and can be retried", async ({ page }) => {
    test.setTimeout(10 * 60 * 1000);
    await registerThroughUi(page, uniqueEmail("failure"));
    const projectId = await createProjectThroughUi(page, {
      name: `E2E отказ ${Date.now()}`,
      type: "SCENE",
      files: UNRELATED_IMAGES,
    });

    try {
      await startGeneration(page, "SCENE");

      const failure = page.getByRole("alert").filter({ hasText: "Генерация не удалась" });
      await expect(failure).toBeVisible({ timeout: 5 * 60 * 1000 });
      await expect(page.getByRole("button", { name: "Повторить генерацию" })).toBeVisible();

      await page.getByRole("button", { name: "Повторить генерацию" }).click();
      await expect(page.getByRole("button", { name: "Идёт генерация…" })).toBeVisible({
        timeout: 60 * 1000,
      });
      // The retry is a new task and fails for the same input-quality reason.
      await expect(page.getByRole("button", { name: "Идёт генерация…" })).toBeHidden({
        timeout: 5 * 60 * 1000,
      });
      await expect(failure).toBeVisible({ timeout: 5 * 60 * 1000 });
    } finally {
      await deleteProjectThroughApi(page, projectId);
    }
  });

  test("a project can be deleted while reconstruction is running", async ({ page }) => {
    test.setTimeout(10 * 60 * 1000);
    await registerThroughUi(page, uniqueEmail("delete-during"));
    const projectId = await createProjectThroughUi(page, {
      name: `E2E удаление ${Date.now()}`,
      type: "SCENE",
      files: UNRELATED_IMAGES,
    });

    await startGeneration(page, "SCENE");
    await deleteProjectThroughUi(page);

    await expect(page).toHaveURL(/\/dashboard$/);
    const response = await page.request.get(`/api/v1/projects/${projectId}`);
    expect(response.status()).toBe(404);
  });
});
