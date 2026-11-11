import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:5173";
// The production deployment uses a self-signed certificate for local
// verification. Set this only for such a run; a real deployment uses a
// trusted certificate and leaves it unset.
const ignoreHTTPSErrors = process.env.E2E_IGNORE_HTTPS_ERRORS === "true";
// Local development drives the installed Microsoft Edge, matching the Phase 7
// browser proof. CI installs Chromium and sets E2E_BROWSER_CHANNEL=chromium.
const channel = process.env.E2E_BROWSER_CHANNEL ?? "msedge";

export default defineConfig({
  testDir: "./tests",
  outputDir: "test-results",
  timeout: 15 * 60 * 1000,
  expect: { timeout: 15 * 1000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results/results.json" }],
    ["html", { open: "never" }],
  ],
  use: {
    baseURL,
    channel,
    headless: true,
    ignoreHTTPSErrors,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    acceptDownloads: true,
    viewport: { width: 1440, height: 900 },
  },
});
