import { Box3, Vector3, type Object3D } from "three";

import type { ModelBounds } from "../types/viewer.types";

/** Direction from the model centre to the initial camera position. */
const CAMERA_DIRECTION = new Vector3(1, 0.7, 1.2).normalize();

/** Extra space around the model so the silhouette never touches the frame. */
const FRAMING_MARGIN = 1.15;

/**
 * Measure a loaded model without changing it.
 *
 * The exporter's own coordinates are preserved; the viewer only offsets the
 * object for display (03_frontend_specification.md 12.7).
 */
export function computeModelBounds(object: Object3D): ModelBounds {
  const box = new Box3().setFromObject(object);
  if (box.isEmpty()) {
    return {
      center: new Vector3(),
      size: new Vector3(),
      radius: 0.001,
    };
  }
  const size = box.getSize(new Vector3());
  const center = box.getCenter(new Vector3());
  const radius = Math.max(size.length() / 2, 0.001);
  return { center, size, radius };
}

/** Distance at which a sphere of `radius` fits the vertical field of view. */
export function cameraDistanceForBounds(radius: number, fovDegrees: number): number {
  const safeRadius = Math.max(radius, 0.001);
  const fov = (fovDegrees * Math.PI) / 180;
  const halfFov = Math.min(Math.max(fov / 2, 0.01), Math.PI / 2 - 0.01);
  return (safeRadius / Math.sin(halfFov)) * FRAMING_MARGIN;
}

/** Initial camera position for a model, relative to its centred origin. */
export function cameraPositionForBounds(bounds: ModelBounds, fovDegrees: number): Vector3 {
  return CAMERA_DIRECTION.clone().multiplyScalar(
    cameraDistanceForBounds(bounds.radius, fovDegrees),
  );
}

/** Clipping planes proportional to the model size, avoiding z-fighting or clipping. */
export function clippingPlanesForRadius(radius: number): { near: number; far: number } {
  const safeRadius = Math.max(radius, 0.001);
  return {
    near: Math.max(safeRadius / 100, 0.0001),
    far: Math.max(safeRadius * 100, 10),
  };
}
