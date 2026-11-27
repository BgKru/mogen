import { act, renderHook, waitFor } from "@testing-library/react";
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial } from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ViewerLoadError } from "../types/viewer.types";
import { useModelLoader } from "./useModelLoader";

const loaderMocks = vi.hoisted(() => ({ loadAsync: vi.fn() }));
const apiMocks = vi.hoisted(() => ({ downloadModelBlob: vi.fn() }));
const splatMocks = vi.hoisted(() => ({ createSplatViewer: vi.fn(), dispose: vi.fn() }));

vi.mock("three/examples/jsm/loaders/GLTFLoader.js", () => ({
  GLTFLoader: class {
    loadAsync(...args: unknown[]) {
      return loaderMocks.loadAsync(...args);
    }
  },
}));

vi.mock("../api/resultApi", () => ({
  downloadModelBlob: apiMocks.downloadModelBlob,
}));

vi.mock("../splat/splatAdapter", () => ({
  createSplatViewer: splatMocks.createSplatViewer,
}));

function triangleScene() {
  const scene = new Group();
  const geometry = new BufferGeometry();
  geometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3),
  );
  const mesh = new Mesh(geometry, new MeshStandardMaterial());
  scene.add(mesh);
  return { scene, geometry };
}

const PLY_PROPERTIES = [
  "x",
  "y",
  "z",
  "nx",
  "ny",
  "nz",
  "f_dc_0",
  "f_dc_1",
  "f_dc_2",
  ...Array.from({ length: 45 }, (_, index) => `f_rest_${index}`),
  "opacity",
  "scale_0",
  "scale_1",
  "scale_2",
  "rot_0",
  "rot_1",
  "rot_2",
  "rot_3",
];

function splatPlyBuffer(count = 4): ArrayBuffer {
  const header = [
    "ply",
    "format binary_little_endian 1.0",
    "comment MOGEN test fixture",
    `element vertex ${count}`,
    ...PLY_PROPERTIES.map((name) => `property float ${name}`),
    "end_header",
    "",
  ].join("\n");
  const headerBytes = new TextEncoder().encode(header);
  const stride = PLY_PROPERTIES.length * 4;
  const buffer = new ArrayBuffer(headerBytes.length + count * stride);
  new Uint8Array(buffer).set(headerBytes);
  const view = new DataView(buffer);
  for (let vertex = 0; vertex < count; vertex += 1) {
    for (let property = 0; property < PLY_PROPERTIES.length; property += 1) {
      const name = PLY_PROPERTIES[property];
      let value = 0;
      if (name === "x") value = vertex * 0.5;
      if (name === "opacity") value = 2;
      if (name === "rot_0") value = 1;
      if (name.startsWith("scale_")) value = -2;
      view.setFloat32(headerBytes.length + vertex * stride + property * 4, value, true);
    }
  }
  return buffer;
}

function plyBlob(count = 4): Blob {
  return new Blob([splatPlyBuffer(count)], { type: "application/octet-stream" });
}

describe("useModelLoader", () => {
  beforeEach(() => {
    apiMocks.downloadModelBlob.mockResolvedValue(new Blob(["glb"], { type: "model/gltf-binary" }));
    const { scene } = triangleScene();
    loaderMocks.loadAsync.mockResolvedValue({ scene });
    splatMocks.createSplatViewer.mockResolvedValue({
      object: new Group(),
      dispose: splatMocks.dispose,
    });
  });

  it("downloads through the authorized API and exposes the parsed model", async () => {
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "GLB"));

    await waitFor(() => expect(result.current.status).toBe("loaded"));

    expect(apiMocks.downloadModelBlob).toHaveBeenCalledWith("project-1");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(result.current.kind).toBe("MESH");
    expect(result.current.model).not.toBeNull();
    expect(result.current.stats).toMatchObject({ meshes: 1, vertices: 3, triangles: 1 });
    expect(result.current.splatStats).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("reports a download failure with a stable code", async () => {
    apiMocks.downloadModelBlob.mockRejectedValue(new ViewerLoadError("DOWNLOAD_FAILED"));
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "GLB"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("DOWNLOAD_FAILED");
    expect(result.current.model).toBeNull();
  });

  it("reports a parse failure and revokes the object URL", async () => {
    loaderMocks.loadAsync.mockRejectedValue(new Error("invalid glb"));
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "GLB"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("PARSE_FAILED");
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("rejects a model without usable geometry", async () => {
    loaderMocks.loadAsync.mockResolvedValue({ scene: new Group() });
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "GLB"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("EMPTY_MODEL");
  });

  it("retries after a failure", async () => {
    loaderMocks.loadAsync.mockRejectedValueOnce(new Error("temporary"));
    const { scene } = triangleScene();
    loaderMocks.loadAsync.mockResolvedValueOnce({ scene });

    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "GLB"));
    await waitFor(() => expect(result.current.status).toBe("error"));

    act(() => result.current.reload());

    await waitFor(() => expect(result.current.status).toBe("loaded"));
    expect(loaderMocks.loadAsync).toHaveBeenCalledTimes(2);
  });

  it("does not load while disabled", () => {
    const { result } = renderHook(() => useModelLoader("project-1", false, undefined, undefined));

    expect(result.current.status).toBe("idle");
    expect(apiMocks.downloadModelBlob).not.toHaveBeenCalled();
  });

  it("disposes the model geometry when unmounted", async () => {
    const { scene, geometry } = triangleScene();
    loaderMocks.loadAsync.mockResolvedValue({ scene });
    const dispose = vi.spyOn(geometry, "dispose");

    const { result, unmount } = renderHook(() =>
      useModelLoader("project-1", true, "result-1", "GLB"),
    );
    await waitFor(() => expect(result.current.status).toBe("loaded"));

    unmount();

    expect(dispose).toHaveBeenCalledTimes(1);
  });

  it("disposes the previous model when the result changes", async () => {
    const first = triangleScene();
    const second = triangleScene();
    loaderMocks.loadAsync
      .mockResolvedValueOnce({ scene: first.scene })
      .mockResolvedValueOnce({ scene: second.scene });
    const firstDispose = vi.spyOn(first.geometry, "dispose");
    const secondDispose = vi.spyOn(second.geometry, "dispose");

    const { result, rerender } = renderHook(
      ({ resultId }) => useModelLoader("project-1", true, resultId, "GLB"),
      { initialProps: { resultId: "result-1" } },
    );
    await waitFor(() => expect(result.current.status).toBe("loaded"));
    expect(result.current.model).toBe(first.scene);

    rerender({ resultId: "result-2" });

    await waitFor(() => expect(result.current.model).toBe(second.scene));
    expect(firstDispose).toHaveBeenCalledTimes(1);
    expect(secondDispose).not.toHaveBeenCalled();
  });

  it("loads a Gaussian PLY through the splat adapter and reports splat facts", async () => {
    apiMocks.downloadModelBlob.mockResolvedValue(plyBlob(4));

    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "PLY"));

    await waitFor(() => expect(result.current.status).toBe("loaded"));

    expect(result.current.kind).toBe("SPLAT");
    expect(result.current.stats).toBeNull();
    expect(result.current.splatStats).toMatchObject({ gaussianCount: 4, shDegree: 3 });
    expect(result.current.bounds?.radius ?? 0).toBeGreaterThan(0);
    expect(loaderMocks.loadAsync).not.toHaveBeenCalled();
    expect(splatMocks.createSplatViewer).toHaveBeenCalledTimes(1);
    expect(splatMocks.createSplatViewer).toHaveBeenCalledWith("blob:preview");
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("disposes the splat renderer on unmount and on result switch", async () => {
    apiMocks.downloadModelBlob.mockResolvedValue(plyBlob(4));
    const { result, unmount } = renderHook(() =>
      useModelLoader("project-1", true, "result-1", "PLY"),
    );
    await waitFor(() => expect(result.current.status).toBe("loaded"));

    unmount();
    await waitFor(() => expect(splatMocks.dispose).toHaveBeenCalledTimes(1));
  });

  it("rejects a malformed Gaussian PLY before creating a renderer", async () => {
    apiMocks.downloadModelBlob.mockResolvedValue(
      new Blob(["not a ply"], { type: "application/octet-stream" }),
    );

    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "PLY"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("PARSE_FAILED");
    expect(splatMocks.createSplatViewer).not.toHaveBeenCalled();
  });

  it("propagates an unsupported splat renderer state", async () => {
    apiMocks.downloadModelBlob.mockResolvedValue(plyBlob(2));
    splatMocks.createSplatViewer.mockRejectedValue(
      new ViewerLoadError("WEBGL_UNAVAILABLE", "no webgl"),
    );

    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1", "PLY"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("WEBGL_UNAVAILABLE");
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});
