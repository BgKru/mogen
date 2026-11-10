import type { Object3D, Vector3 } from "three";

/** Lifecycle of the authorized GLB download and parse. */
export type ModelLoadStatus = "idle" | "loading" | "loaded" | "error";

/** Stable failure categories shown to the user (03_frontend_specification.md 14.2). */
export type ViewerErrorCode =
  "DOWNLOAD_FAILED" | "PARSE_FAILED" | "EMPTY_MODEL" | "UNSUPPORTED_ASSET";

export class ViewerLoadError extends Error {
  readonly code: ViewerErrorCode;

  constructor(code: ViewerErrorCode, message?: string) {
    super(message ?? code);
    this.name = "ViewerLoadError";
    this.code = code;
  }
}

/** Bounding box measurements of a loaded model, in its own coordinate space. */
export interface ModelBounds {
  center: Vector3;
  size: Vector3;
  radius: number;
}

/** Geometry and material facts measured from the parsed Three.js scene. */
export interface ModelStats {
  meshes: number;
  vertices: number;
  triangles: number;
  materials: number;
  textures: number;
  hasTextures: boolean;
  hasVertexColors: boolean;
}

/** Imperative actions the toolbar invokes on the camera inside the canvas. */
export interface ViewerControlsHandle {
  fit: () => void;
  reset: () => void;
}

/** Loaded model plus the measurements and failure state derived from it. */
export interface ModelLoadResult {
  status: ModelLoadStatus;
  model: Object3D | null;
  stats: ModelStats | null;
  error: ViewerLoadError | null;
  reload: () => void;
}

/** Neutral background choices for the viewport. */
export type ViewerBackground = "dark" | "light";
