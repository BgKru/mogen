import { useCallback, useEffect, useRef, useState } from "react";
import type { Object3D } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { collectModelStats, disposeModel } from "../utils/modelCleanup";
import { downloadModelBlob } from "../api/resultApi";
import {
  ViewerLoadError,
  type ModelLoadResult,
  type ModelStats,
  type ModelLoadStatus,
} from "../types/viewer.types";

interface LoaderState {
  status: ModelLoadStatus;
  model: Object3D | null;
  stats: ModelStats | null;
  error: ViewerLoadError | null;
}

const IDLE: LoaderState = { status: "idle", model: null, stats: null, error: null };

function asViewerError(error: unknown): ViewerLoadError {
  if (error instanceof ViewerLoadError) {
    return error;
  }
  return new ViewerLoadError("PARSE_FAILED", error instanceof Error ? error.message : undefined);
}

/**
 * Download and parse the authorized GLB for a result.
 *
 * The bytes are fetched through the shared authenticated client, exposed to
 * GLTFLoader through a temporary object URL and revoked as soon as parsing
 * finishes. The previous model is disposed before a new one is requested and
 * on unmount, so changing projects or regenerating cannot leak GPU memory
 * (03_frontend_specification.md 12.3 and 12.11, FE-AC-17).
 */
export function useModelLoader(
  projectId: string,
  enabled: boolean,
  resultId: string | undefined,
): ModelLoadResult {
  const [state, setState] = useState<LoaderState>(IDLE);
  const [attempt, setAttempt] = useState(0);
  const activeModel = useRef<Object3D | null>(null);

  const reload = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!enabled) {
      if (activeModel.current) {
        disposeModel(activeModel.current);
        activeModel.current = null;
      }
      setState(IDLE);
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;

    if (activeModel.current) {
      disposeModel(activeModel.current);
      activeModel.current = null;
    }
    setState({ status: "loading", model: null, stats: null, error: null });

    void (async () => {
      try {
        const blob = await downloadModelBlob(projectId);
        if (cancelled) {
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
        activeModel.current = gltf.scene;
        setState({ status: "loaded", model: gltf.scene, stats, error: null });
      } catch (error) {
        if (!cancelled) {
          setState({ status: "error", model: null, stats: null, error: asViewerError(error) });
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
  }, [projectId, enabled, resultId, attempt]);

  useEffect(
    () => () => {
      if (activeModel.current) {
        disposeModel(activeModel.current);
        activeModel.current = null;
      }
    },
    [],
  );

  return { ...state, reload };
}
