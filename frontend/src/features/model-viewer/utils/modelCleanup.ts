import { Texture, type Material, type Mesh, type Object3D } from "three";

import type { ModelStats } from "../types/viewer.types";

/** Material texture slots used by exported object and scene assets. */
const TEXTURE_SLOTS = [
  "map",
  "normalMap",
  "bumpMap",
  "roughnessMap",
  "metalnessMap",
  "aoMap",
  "emissiveMap",
  "alphaMap",
  "lightMap",
  "displacementMap",
  "specularMap",
  "clearcoatMap",
  "clearcoatNormalMap",
  "clearcoatRoughnessMap",
  "sheenColorMap",
  "sheenRoughnessMap",
  "transmissionMap",
  "thicknessMap",
  "iridescenceMap",
  "anisotropyMap",
] as const;

function materialTextures(material: Material): Texture[] {
  const record = material as unknown as Record<string, unknown>;
  const textures: Texture[] = [];
  for (const slot of TEXTURE_SLOTS) {
    const value = record[slot];
    if (value instanceof Texture) {
      textures.push(value);
    }
  }
  return textures;
}

/**
 * Release every GPU resource produced by the GLTFLoader for this model.
 *
 * Geometry, materials and textures created from the file are disposed exactly
 * once, even when primitives share them. Other rendered objects are untouched.
 * Called when the model is replaced, the viewer unmounts or a load is aborted
 * (03_frontend_specification.md 12.3 and 12.11).
 */
export function disposeModel(root: Object3D | null): void {
  if (!root) {
    return;
  }
  const geometries = new Set<Mesh["geometry"]>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();

  root.traverse((object) => {
    const mesh = object as Mesh;
    if (!mesh.isMesh || !mesh.geometry) {
      return;
    }
    geometries.add(mesh.geometry);
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of list) {
      if (!material) {
        continue;
      }
      materials.add(material);
      for (const texture of materialTextures(material)) {
        textures.add(texture);
      }
    }
  });

  for (const texture of textures) {
    texture.dispose();
  }
  for (const material of materials) {
    material.dispose();
  }
  for (const geometry of geometries) {
    geometry.dispose();
  }
}

/** Count the visible geometry and appearance facts of a loaded model. */
export function collectModelStats(root: Object3D): ModelStats {
  let meshes = 0;
  let vertices = 0;
  let triangles = 0;
  let hasTextures = false;
  let hasVertexColors = false;
  const materials = new Set<Material>();
  const textures = new Set<Texture>();

  root.traverse((object) => {
    const mesh = object as Mesh;
    if (!mesh.isMesh || !mesh.geometry) {
      return;
    }
    meshes += 1;
    const position = mesh.geometry.getAttribute("position");
    vertices += position?.count ?? 0;
    const index = mesh.geometry.getIndex();
    triangles += Math.round((index ? index.count : (position?.count ?? 0)) / 3);
    if (mesh.geometry.getAttribute("uv")) {
      hasTextures = true;
    }
    if (mesh.geometry.getAttribute("color")) {
      hasVertexColors = true;
    }
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of list) {
      if (!material) {
        continue;
      }
      materials.add(material);
      const maps = materialTextures(material);
      if (maps.length > 0) {
        hasTextures = true;
      }
      for (const texture of maps) {
        textures.add(texture);
      }
    }
  });

  return {
    meshes,
    vertices,
    triangles,
    materials: materials.size,
    textures: textures.size,
    hasTextures,
    hasVertexColors,
  };
}
