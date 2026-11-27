import type { Object3D } from "three";

import { ViewerLoadError } from "../types/viewer.types";

/** A loaded, disposable Gaussian-splat renderer attached to the R3F scene. */
export interface SplatViewerHandle {
  object: Object3D;
  dispose: () => Promise<void>;
}

interface DropInViewerLike extends Object3D {
  addSplatScene(
    path: string,
    options?: { format?: number; showLoadingUI?: boolean; splatAlphaRemovalThreshold?: number },
  ): Promise<void>;
  dispose(): Promise<void>;
}

/**
 * Create the Gaussian-splat renderer for one authorized artifact URL.
 *
 * The renderer package is imported lazily by `useModelLoader`, so GLB-only
 * routes never download or parse this bundle. The viewer is a Three.js
 * `Object3D` (drop-in mode): it sorts and draws splats inside the existing R3F
 * canvas and camera, which keeps OrbitControls, bounds and disposal shared with
 * the mesh path.
 */
export async function createSplatViewer(url: string): Promise<SplatViewerHandle> {
  let module: typeof import("@mkkellogg/gaussian-splats-3d");
  try {
    module = await import("@mkkellogg/gaussian-splats-3d");
  } catch {
    throw new ViewerLoadError("WEBGL_UNAVAILABLE", "The splat renderer could not be loaded.");
  }
  const { DropInViewer, SceneFormat } = module;
  let viewer: DropInViewerLike;
  try {
    viewer = new DropInViewer({
      gpuAcceleration: true,
      dynamicScene: false,
      sphericalHarmonicsDegree: 3,
      // SharedArrayBuffer requires COOP/COEP cross-origin isolation; the app
      // does not set those headers, so the sort worker uses transferable
      // buffers instead. The renderer still uses its own workers normally.
      sharedMemoryForWorkers: false,
    }) as unknown as DropInViewerLike;
  } catch (error) {
    throw new ViewerLoadError(
      "WEBGL_UNAVAILABLE",
      error instanceof Error ? error.message : undefined,
    );
  }
  try {
    await viewer.addSplatScene(url, {
      format: SceneFormat.Ply,
      showLoadingUI: false,
      splatAlphaRemovalThreshold: 1,
    });
  } catch (error) {
    await viewer.dispose().catch(() => undefined);
    throw new ViewerLoadError("PARSE_FAILED", error instanceof Error ? error.message : undefined);
  }
  return {
    object: viewer,
    dispose: async () => {
      await viewer.dispose();
    },
  };
}
