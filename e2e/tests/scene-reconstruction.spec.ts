import { expect, test } from "@playwright/test";

import {
  createProjectThroughUi,
  deleteProjectThroughApi,
  downloadResult,
  isGlb,
  openViewer,
  readViewerStats,
  registerThroughUi,
  sceneImages,
  startGeneration,
  uniqueEmail,
  waitForGenerationResult,
} from "./helpers";

test.describe("scene reconstruction workflow (E2E-08, E2E-13)", () => {
  test("a real COLMAP/OpenMVS reconstruction is started, visualized and downloaded", async ({
    page,
  }) => {
    test.setTimeout(20 * 60 * 1000);
    const images = sceneImages();
    test.skip(
      images.length < 3,
      "No scene dataset: set E2E_SCENE_IMAGES to a directory of overlapping photographs.",
    );

    await registerThroughUi(page, uniqueEmail("scene"));
    const projectId = await createProjectThroughUi(page, {
      name: `E2E сцена ${Date.now()}`,
      type: "SCENE",
      files: images,
    });

    try {
      await startGeneration(page, "SCENE");
      await waitForGenerationResult(page, "SCENE", 18 * 60 * 1000);

      const viewport = await openViewer(page);
      const stats = await readViewerStats(viewport);
      expect(stats.meshes).toBeGreaterThan(0);
      expect(stats.vertices).toBeGreaterThan(1000);
      expect(stats.triangles).toBeGreaterThan(1000);
      // The MVP scene output is textured; the viewer reports embedded textures.
      expect(stats.textures).toBeGreaterThan(0);

      const { bytes } = await downloadResult(page);
      expect(isGlb(bytes)).toBe(true);

      const metadataResponse = await page.request.get(`/api/v1/projects/${projectId}/result`);
      expect(metadataResponse.status()).toBe(200);
      const metadata = await metadataResponse.json();
      expect(metadata.file_size_bytes).toBe(bytes.length);
    } finally {
      await deleteProjectThroughApi(page, projectId);
    }
  });
});
