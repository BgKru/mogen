import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Object3D } from "three";

import type {
  ModelLoadStatus,
  ModelStats,
  ViewerBackground,
  ViewerControlsHandle,
  ViewerLoadError,
} from "../types/viewer.types";
import { computeModelBounds } from "../utils/modelBounds";
import { ModelCanvas } from "./ModelCanvas";
import { ViewerError } from "./ViewerError";
import { ViewerLoading } from "./ViewerLoading";
import { ViewerToolbar } from "./ViewerToolbar";

interface ModelViewerProps {
  model: Object3D | null;
  status: ModelLoadStatus;
  stats: ModelStats | null;
  error: ViewerLoadError | null;
  onRetry: () => void;
  className?: string;
}

const IDLE_CONTROLS: ViewerControlsHandle = {
  fit: () => undefined,
  reset: () => undefined,
};

/**
 * The unified viewport for object and scene results.
 *
 * Owns only presentation state (grid, background, fullscreen); the model and
 * its lifecycle are provided by `useModelLoader`, which also disposes the
 * resources. The same component renders TripoSR objects (vertex colours) and
 * COLMAP/OpenMVS scenes (embedded textures).
 */
export function ModelViewer({
  model,
  status,
  stats,
  error,
  onRetry,
  className = "",
}: ModelViewerProps) {
  const [gridVisible, setGridVisible] = useState(true);
  const [background, setBackground] = useState<ViewerBackground>("dark");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const controller = useRef<ViewerControlsHandle>(IDLE_CONTROLS);

  const bounds = useMemo(() => (model ? computeModelBounds(model) : null), [model]);

  useEffect(() => {
    const handleChange = () => {
      setIsFullscreen(document.fullscreenElement === containerRef.current);
    };
    document.addEventListener("fullscreenchange", handleChange);
    return () => document.removeEventListener("fullscreenchange", handleChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    try {
      if (document.fullscreenElement) {
        void document.exitFullscreen?.();
      } else {
        void element.requestFullscreen?.();
      }
    } catch {
      // Fullscreen can be blocked by the browser or unsupported in tests; the
      // viewer keeps working in its normal layout.
    }
  }, []);

  const loaded = status === "loaded" && model !== null && bounds !== null;

  return (
    <div
      ref={containerRef}
      className={`relative h-full w-full overflow-hidden rounded-2xl border border-border bg-background ${className}`}
      data-viewer-state={status}
      data-model-meshes={stats?.meshes}
      data-model-vertices={stats?.vertices}
      data-model-triangles={stats?.triangles}
      data-model-materials={stats?.materials}
      data-model-textures={stats?.textures}
      data-model-textured={stats?.hasTextures}
      data-model-vertex-colors={stats?.hasVertexColors}
    >
      {loaded && model && bounds ? (
        <ModelCanvas
          model={model}
          bounds={bounds}
          showGrid={gridVisible}
          background={background}
          controller={controller}
        />
      ) : null}

      {status === "loading" || status === "idle" ? <ViewerLoading /> : null}
      {status === "error" ? <ViewerError error={error} onRetry={onRetry} /> : null}

      {loaded ? (
        <>
          <div className="absolute left-3 top-3 z-10">
            <ViewerToolbar
              gridVisible={gridVisible}
              background={background}
              isFullscreen={isFullscreen}
              onReset={() => controller.current.reset()}
              onFit={() => controller.current.fit()}
              onToggleGrid={() => setGridVisible((value) => !value)}
              onToggleBackground={() =>
                setBackground((value) => (value === "dark" ? "light" : "dark"))
              }
              onToggleFullscreen={toggleFullscreen}
            />
          </div>
          <p className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-md bg-background/60 px-2 py-1 text-[11px] text-text-secondary">
            ЛКМ — вращение · колесо — масштаб · ПКМ — перемещение
          </p>
        </>
      ) : null}
    </div>
  );
}
