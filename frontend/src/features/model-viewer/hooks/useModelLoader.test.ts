import { act, renderHook, waitFor } from "@testing-library/react";
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial } from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ViewerLoadError } from "../types/viewer.types";
import { useModelLoader } from "./useModelLoader";

const loaderMocks = vi.hoisted(() => ({ loadAsync: vi.fn() }));
const apiMocks = vi.hoisted(() => ({ downloadModelBlob: vi.fn() }));

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

describe("useModelLoader", () => {
  beforeEach(() => {
    apiMocks.downloadModelBlob.mockResolvedValue(new Blob(["glb"], { type: "model/gltf-binary" }));
    const { scene } = triangleScene();
    loaderMocks.loadAsync.mockResolvedValue({ scene });
  });

  it("downloads through the authorized API and exposes the parsed model", async () => {
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1"));

    await waitFor(() => expect(result.current.status).toBe("loaded"));

    expect(apiMocks.downloadModelBlob).toHaveBeenCalledWith("project-1");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(result.current.model).not.toBeNull();
    expect(result.current.stats).toMatchObject({ meshes: 1, vertices: 3, triangles: 1 });
    expect(result.current.error).toBeNull();
  });

  it("reports a download failure with a stable code", async () => {
    apiMocks.downloadModelBlob.mockRejectedValue(new ViewerLoadError("DOWNLOAD_FAILED"));
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("DOWNLOAD_FAILED");
    expect(result.current.model).toBeNull();
  });

  it("reports a parse failure and revokes the object URL", async () => {
    loaderMocks.loadAsync.mockRejectedValue(new Error("invalid glb"));
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("PARSE_FAILED");
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("rejects a model without usable geometry", async () => {
    loaderMocks.loadAsync.mockResolvedValue({ scene: new Group() });
    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.code).toBe("EMPTY_MODEL");
  });

  it("retries after a failure", async () => {
    loaderMocks.loadAsync.mockRejectedValueOnce(new Error("temporary"));
    const { scene } = triangleScene();
    loaderMocks.loadAsync.mockResolvedValueOnce({ scene });

    const { result } = renderHook(() => useModelLoader("project-1", true, "result-1"));
    await waitFor(() => expect(result.current.status).toBe("error"));

    act(() => result.current.reload());

    await waitFor(() => expect(result.current.status).toBe("loaded"));
    expect(loaderMocks.loadAsync).toHaveBeenCalledTimes(2);
  });

  it("does not load while disabled", () => {
    const { result } = renderHook(() => useModelLoader("project-1", false, undefined));

    expect(result.current.status).toBe("idle");
    expect(apiMocks.downloadModelBlob).not.toHaveBeenCalled();
  });

  it("disposes the model geometry when unmounted", async () => {
    const { scene, geometry } = triangleScene();
    loaderMocks.loadAsync.mockResolvedValue({ scene });
    const dispose = vi.spyOn(geometry, "dispose");

    const { result, unmount } = renderHook(() => useModelLoader("project-1", true, "result-1"));
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
      ({ resultId }) => useModelLoader("project-1", true, resultId),
      { initialProps: { resultId: "result-1" } },
    );
    await waitFor(() => expect(result.current.status).toBe("loaded"));
    expect(result.current.model).toBe(first.scene);

    rerender({ resultId: "result-2" });

    await waitFor(() => expect(result.current.model).toBe(second.scene));
    expect(firstDispose).toHaveBeenCalledTimes(1);
    expect(secondDispose).not.toHaveBeenCalled();
  });
});
