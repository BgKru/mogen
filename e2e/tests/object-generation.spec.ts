import { expect, test } from "@playwright/test";

import {
  OBJECT_IMAGE,
  createProjectThroughUi,
  deleteProjectThroughApi,
  downloadResult,
  interactWithViewer,
  isGlb,
  openViewer,
  readViewerStats,
  registerThroughUi,
  startGeneration,
  uniqueEmail,
  waitForGenerationResult,
} from "./helpers";

test.describe("object generation workflow (E2E-07, E2E-13)", () => {
  test("a real TripoSR generation is started, visualized and downloaded", async ({ page }) => {
    test.setTimeout(15 * 60 * 1000);
    await registerThroughUi(page, uniqueEmail("object"));

    const projectId = await createProjectThroughUi(page, {
      name: `E2E объект ${Date.now()}`,
      type: "OBJECT",
      files: [OBJECT_IMAGE],
    });

    try {
      await startGeneration(page, "OBJECT");
      await waitForGenerationResult(page, "OBJECT");

      const viewport = await openViewer(page);
      const stats = await readViewerStats(viewport);
      expect(stats.meshes).toBeGreaterThan(0);
      expect(stats.vertices).toBeGreaterThan(1000);
      expect(stats.triangles).toBeGreaterThan(1000);

      await interactWithViewer(page, viewport);

      const { bytes, suggestedFilename } = await downloadResult(page);
      expect(suggestedFilename.toLowerCase()).toMatch(/\.glb$/);
      expect(isGlb(bytes)).toBe(true);

      const metadataResponse = await page.request.get(`/api/v1/projects/${projectId}/result`);
      expect(metadataResponse.status()).toBe(200);
      const metadata = await metadataResponse.json();
      expect(metadata.file_size_bytes).toBe(bytes.length);
      expect(metadata.mime_type).toBe("model/gltf-binary");
    } finally {
      await deleteProjectThroughApi(page, projectId);
    }
  });
});
