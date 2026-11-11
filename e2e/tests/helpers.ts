import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";
export const PASSWORD = "SecurePassword123";
export const ORIGIN_HEADER = { Origin: BASE_URL };

const E2E_ROOT = fileURLToPath(new URL("..", import.meta.url));
const REPO_ROOT = join(E2E_ROOT, "..");

/** A committed object photograph used by the real TripoSR workflow. */
export const OBJECT_IMAGE = join(
  REPO_ROOT,
  "ml",
  "object_generation",
  "testdata",
  "car-1.jpg",
);

/** Three unrelated committed photographs: they cannot reconstruct one scene. */
export const UNRELATED_IMAGES = ["animal-2.jpg", "car-1.jpg", "car-2.jpg"].map((name) =>
  join(REPO_ROOT, "ml", "object_generation", "testdata", name),
);

/**
 * The real Sceaux Castle photographs (11 images, ~34 MB). They live outside the
 * repository (Phase 6 proof data), so the scene E2E test skips unless a dataset
 * is provided through E2E_SCENE_IMAGES (absolute path or repository-relative).
 */
export function sceneImages(): string[] {
  const configured = process.env.E2E_SCENE_IMAGES;
  const directory = configured
    ? configured.startsWith("/") || /^[A-Za-z]:/.test(configured)
      ? configured
      : join(REPO_ROOT, configured)
    : join(REPO_ROOT, ".proof", "sceaux");
  try {
    return readdirSync(directory)
      .filter((name) => /\.(jpe?g|png)$/i.test(name))
      .sort()
      .map((name) => join(directory, name));
  } catch {
    return [];
  }
}

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`;
}

export async function registerThroughUi(page: Page, email: string): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Повторите пароль").fill(PASSWORD);
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await page.waitForURL("**/dashboard");
}

export async function loginThroughUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/dashboard");
}

interface CreateProjectOptions {
  name: string;
  type: "OBJECT" | "SCENE";
  files: string[];
}

/** Create a project through the UI and return its identifier. */
export async function createProjectThroughUi(
  page: Page,
  { name, type, files }: CreateProjectOptions,
): Promise<string> {
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Создать проект" }).first().click();
  await page.waitForURL("**/projects/new");

  await page.getByLabel("Название проекта").fill(name);
  if (type === "SCENE") {
    await page.getByRole("radio", { name: /Реконструкция сцены/ }).click();
  }

  await page.locator('input[type="file"]').setInputFiles(files);
  const submit = page.getByRole("button", { name: "Создать проект" });
  await expect(submit).toBeEnabled({ timeout: 60_000 });
  await submit.click();

  await page.waitForURL(
    /\/projects\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    { timeout: 180_000 },
  );
  return page.url().split("/").pop() as string;
}

export async function deleteProjectThroughUi(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Удалить проект" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Удалить" }).click();
  await page.waitForURL("**/dashboard");
}

export async function deleteProjectThroughApi(page: Page, projectId: string): Promise<void> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "csrf_token")?.value ?? "";
  await page.request.delete(`/api/v1/projects/${projectId}`, {
    headers: { "X-CSRF-Token": csrf, Origin: BASE_URL },
  });
}

export async function startGeneration(page: Page, type: "OBJECT" | "SCENE"): Promise<void> {
  const label = type === "OBJECT" ? "Создать 3D-модель" : "Реконструировать сцену";
  await page.getByRole("button", { name: label }).click();
}

export async function waitForGenerationResult(
  page: Page,
  type: "OBJECT" | "SCENE",
  timeout = 15 * 60 * 1000,
): Promise<void> {
  const heading = type === "OBJECT" ? "3D-модель готова" : "Сцена готова";
  await expect(page.getByText(heading, { exact: true })).toBeVisible({ timeout });
}

export async function openViewer(page: Page) {
  await page.getByRole("link", { name: "Открыть в 3D" }).click();
  await page.waitForURL(/\/result$/);
  const viewport = page.locator("[data-viewer-state]");
  await expect(viewport).toHaveAttribute("data-viewer-state", "loaded", { timeout: 120_000 });
  // R3F measures its container asynchronously; wait for a real canvas size.
  await page.waitForFunction(
    () => {
      const canvas = document.querySelector("canvas");
      return canvas !== null && canvas.width > 300 && canvas.height > 300;
    },
    undefined,
    { timeout: 60_000 },
  );
  return viewport;
}

export async function readViewerStats(
  viewport: ReturnType<Page["locator"]>,
): Promise<{ meshes: number; vertices: number; triangles: number; textures: number }> {
  const attribute = async (name: string) =>
    Number((await viewport.getAttribute(`data-model-${name}`)) ?? "0");
  return {
    meshes: await attribute("meshes"),
    vertices: await attribute("vertices"),
    triangles: await attribute("triangles"),
    textures: await attribute("textures"),
  };
}

/**
 * Exercise the browser controls: orbit drag, wheel zoom, fit and reset.
 * The Phase 7 proof measured pixel changes; here the assertions are that the
 * controls stay usable and the canvas remains in the loaded state (E2E-13).
 */
export async function interactWithViewer(page: Page, viewport: ReturnType<Page["locator"]>) {
  const canvas = page.locator("canvas");
  const box = await canvas.boundingBox();
  if (!box) {
    throw new Error("the viewer canvas has no layout box");
  }
  const centreX = box.x + box.width / 2;
  const centreY = box.y + box.height / 2;

  await page.mouse.move(centreX, centreY);
  await page.mouse.down();
  await page.mouse.move(centreX + 90, centreY + 40, { steps: 10 });
  await page.mouse.up();
  await page.mouse.wheel(0, -240);

  await page.getByRole("button", { name: "Вписать модель в область просмотра" }).click();
  await page.getByRole("button", { name: "Показать или скрыть сетку" }).click();
  await page.getByRole("button", { name: "Сбросить камеру" }).click();

  await expect(viewport).toHaveAttribute("data-viewer-state", "loaded");
}

export async function downloadResult(page: Page): Promise<{
  bytes: Buffer;
  suggestedFilename: string;
}> {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Скачать GLB" }).click(),
  ]);
  const path = await download.path();
  if (!path) {
    throw new Error("the browser did not produce a download path");
  }
  return {
    bytes: readFileSync(path),
    suggestedFilename: download.suggestedFilename(),
  };
}

export function isGlb(bytes: Buffer): boolean {
  return bytes.length >= 12 && bytes.subarray(0, 4).toString("ascii") === "glTF";
}

/** CSRF token from an API request context's cookie jar. */
export async function csrfToken(context: APIRequestContext): Promise<string> {
  const state = await context.storageState();
  return state.cookies.find((cookie) => cookie.name === "csrf_token")?.value ?? "";
}

/** Register a user through the API and return that context (cookies retained). */
export async function registerThroughApi(
  context: APIRequestContext,
  email: string,
): Promise<void> {
  const response = await context.post("/api/v1/auth/register", {
    data: { email, password: PASSWORD },
    headers: ORIGIN_HEADER,
  });
  expect(response.status(), await response.text()).toBe(201);
}

export async function createProjectThroughApi(
  context: APIRequestContext,
  name: string,
  type: "OBJECT" | "SCENE" = "OBJECT",
): Promise<string> {
  const response = await context.post("/api/v1/projects", {
    data: { name, type },
    headers: { ...ORIGIN_HEADER, "X-CSRF-Token": await csrfToken(context) },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()).id as string;
}
