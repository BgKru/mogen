import { useCallback, useEffect, useRef, useState } from "react";
import type { Object3D } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { collectModelStats, disposeModel } from "../utils/modelCleanup";
import { downloadModelBlob } from "../api/resultApi";
import { createSplatViewer, type SplatViewerHandle } from "../splat/splatAdapter";
import { parseSplatPly } from "../splat/splatPly";
import {
  ViewerLoadError,
  type ModelBounds,
  type ModelLoadResult,
  type ModelStats,
  type ModelLoadStatus,
  type SplatStats,
  type ViewerAssetKind,
} from "../types/viewer.types";

interface LoaderState {
  status: ModelLoadStatus;
  kind: ViewerAssetKind | null;
  model: Object3D | null;
  stats: ModelStats | null;
  splatStats: SplatStats | null;
  bounds: ModelBounds | null;
  error: ViewerLoadError | null;
}

const IDLE: LoaderState = {
  status: "idle",
  kind: null,
  model: null,
  stats: null,
  splatStats: null,
  bounds: null,
  error: null,
};

function asViewerError(error: unknown): ViewerLoadError {
  if (error instanceof ViewerLoadError) {
    return error;
  }
  return new ViewerLoadError("PARSE_FAILED", error instanceof Error ? error.message : undefined);
}

/**
 * Download and parse the authorized result asset for a project.
 *
 * The result `format` dispatches loading: GLB keeps the existing `GLTFLoader`
 * path, while a Gaussian PLY (increment 15) is validated by `parseSplatPly` and
 * rendered by the lazily imported splat renderer. In both cases the bytes are
 * fetched through the shared authenticated client, exposed through a temporary
 * object URL and revoked as soon as the asset is ready; the previous asset is
 * disposed before a new one is requested and on unmount
 * (03_frontend_specification.md 12.3/12.11, FE-AC-17, I15-AC-07).
 */
export function useModelLoader(
  projectId: string,
  enabled: boolean,
  resultId: string | undefined,
  format: string | undefined,
): ModelLoadResult {
  const [state, setState] = useState<LoaderState>(IDLE);
  const [attempt, setAttempt] = useState(0);
  const activeMesh = useRef<Object3D | null>(null);
  const activeSplat = useRef<SplatViewerHandle | null>(null);
  const isSplat = (format ?? "GLB").toUpperCase() === "PLY";

  const reload = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  const disposeActive = useCallback(() => {
    if (activeMesh.current) {
      disposeModel(activeMesh.current);
      activeMesh.current = null;
    }
    if (activeSplat.current) {
      const handle = activeSplat.current;
      activeSplat.current = null;
      void Promise.resolve(handle.dispose()).catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      disposeActive();
      setState(IDLE);
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;

    disposeActive();
    setState({ ...IDLE, status: "loading" });

    void (async () => {
      try {
        const blob = await downloadModelBlob(projectId);
        if (cancelled) {
          return;
        }
        if (isSplat) {
          const parsed = parseSplatPly(await blob.arrayBuffer());
          if (cancelled) {
            return;
          }
          objectUrl = URL.createObjectURL(blob);
          const handle = await createSplatViewer(objectUrl);
          if (cancelled) {
            await Promise.resolve(handle.dispose()).catch(() => undefined);
            return;
          }
          activeSplat.current = handle;
          setState({
            status: "loaded",
            kind: "SPLAT",
            model: handle.object,
            stats: null,
            splatStats: parsed.stats,
            bounds: parsed.bounds,
            error: null,
          });
          return;
        }

        objectUrl = URL.createObjectURL(blob);
        const loader = new GLTFLoader();
        let gltf;
        try {
          gltf = await loader.loadAsync(objectUrl);
        } catch (error) {
          throw new ViewerLoadError(
            "PARSE_FAILED",
            error instanceof Error ? error.message : undefined,
          );
        }
        if (cancelled) {
          disposeModel(gltf.scene);
          return;
        }
        const stats = collectModelStats(gltf.scene);
        if (stats.meshes < 1 || stats.vertices < 3) {
          disposeModel(gltf.scene);
          throw new ViewerLoadError("EMPTY_MODEL");
        }
        activeMesh.current = gltf.scene;
        setState({
          status: "loaded",
          kind: "MESH",
          model: gltf.scene,
          stats,
          splatStats: null,
          bounds: null,
          error: null,
        });
      } catch (error) {
        if (!cancelled) {
          setState({ ...IDLE, status: "error", error: asViewerError(error) });
        }
      } finally {
        if (objectUrl) {
          URL.revokeObjectURL(objectUrl);
          objectUrl = null;
        }
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    };
  }, [projectId, enabled, resultId, format, isSplat, attempt, disposeActive]);

  useEffect(() => disposeActive, [disposeActive]);

  return { ...state, reload };
}
