import type { Object3D, Vector3 } from "three";

/** Lifecycle of the authorized result download and parse. */
export type ModelLoadStatus = "idle" | "loading" | "loaded" | "error";

/** Representation of the loaded asset, selected from the result format. */
export type ViewerAssetKind = "MESH" | "SPLAT";

/** Stable failure categories shown to the user (03_frontend_specification.md 14.2). */
export type ViewerErrorCode =
  | "DOWNLOAD_FAILED"
  | "PARSE_FAILED"
  | "EMPTY_MODEL"
  | "UNSUPPORTED_ASSET"
  | "ASSET_TOO_LARGE"
  | "WEBGL_UNAVAILABLE";

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

/** Facts measured from a Gaussian-splat PLY; a splat is not a triangle mesh. */
export interface SplatStats {
  gaussianCount: number;
  shDegree: number;
  fileSizeBytes: number;
  propertyCount: number;
}

/** Imperative actions the toolbar invokes on the camera inside the canvas. */
export interface ViewerControlsHandle {
  fit: () => void;
  reset: () => void;
}

/** Loaded asset plus the measurements and failure state derived from it. */
export interface ModelLoadResult {
  status: ModelLoadStatus;
  kind: ViewerAssetKind | null;
  model: Object3D | null;
  stats: ModelStats | null;
  splatStats: SplatStats | null;
  bounds: ModelBounds | null;
  error: ViewerLoadError | null;
  reload: () => void;
}

/** Neutral background choices for the viewport. */
export type ViewerBackground = "dark" | "light";
