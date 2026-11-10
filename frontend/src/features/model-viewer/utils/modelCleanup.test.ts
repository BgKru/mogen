import { Mesh, MeshStandardMaterial, Texture } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { describe, expect, it, vi } from "vitest";

import { minimalGlbArrayBuffer } from "../test/fixtures/minimalModel";
import { collectModelStats, disposeModel } from "./modelCleanup";

async function loadFixture() {
  const loader = new GLTFLoader();
  return new Promise<Awaited<ReturnType<typeof loader.parseAsync>>>((resolve, reject) => {
    loader.parse(minimalGlbArrayBuffer(), "", resolve, reject);
  });
}

describe("modelCleanup", () => {
  it("counts geometry and materials of a valid GLB fixture", async () => {
    const gltf = await loadFixture();
    const stats = collectModelStats(gltf.scene);

    expect(stats.meshes).toBe(1);
    expect(stats.vertices).toBe(3);
    expect(stats.triangles).toBe(1);
    expect(stats.materials).toBe(1);
    expect(stats.textures).toBe(0);
    expect(stats.hasVertexColors).toBe(false);
    expect(stats.hasTextures).toBe(false);
  });

  it("rejects invalid GLB bytes with a clear parse failure", async () => {
    const loader = new GLTFLoader();
    const invalid = new Uint8Array([1, 2, 3, 4]).buffer;
    await expect(
      new Promise((resolve, reject) => {
        loader.parse(invalid, "", resolve, reject);
      }),
    ).rejects.toBeTruthy();
  });

  it("disposes geometry, materials and textures", async () => {
    const gltf = await loadFixture();
    let mesh: Mesh | null = null;
    gltf.scene.traverse((object) => {
      if (!mesh && (object as Mesh).isMesh) {
        mesh = object as Mesh;
      }
    });
    expect(mesh).not.toBeNull();
    const target = mesh as unknown as Mesh;
    const geometry = target.geometry;
    const material = target.material as MeshStandardMaterial;
    const texture = new Texture();
    material.map = texture;

    const geometryDispose = vi.spyOn(geometry, "dispose");
    const materialDispose = vi.spyOn(material, "dispose");
    const textureDispose = vi.spyOn(texture, "dispose");

    disposeModel(gltf.scene);

    expect(geometryDispose).toHaveBeenCalledTimes(1);
    expect(materialDispose).toHaveBeenCalledTimes(1);
    expect(textureDispose).toHaveBeenCalledTimes(1);
  });

  it("ignores an absent model", () => {
    expect(() => disposeModel(null)).not.toThrow();
  });
});
