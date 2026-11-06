import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useImageSelection } from "./useImageSelection";

const mocks = vi.hoisted(() => ({
  validate: vi.fn(),
}));

vi.mock("../utils/validation", () => ({
  validateImageFile: mocks.validate,
}));

function jpeg(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "image/jpeg" });
}

describe("useImageSelection", () => {
  it("adds a valid single image and replaces it on the next selection", async () => {
    mocks.validate.mockResolvedValue({ ok: true, dimensions: { width: 10, height: 10 } });
    const { result } = renderHook(() => useImageSelection({ mode: "single", maxFiles: 1 }));

    await act(async () => {
      await result.current.addFiles([jpeg("first.jpg")]);
    });
    expect(result.current.items).toHaveLength(1);
    expect(result.current.items[0].file.name).toBe("first.jpg");
    const firstUrl = result.current.items[0].previewUrl;

    await act(async () => {
      await result.current.addFiles([jpeg("second.jpg")]);
    });

    expect(result.current.items).toHaveLength(1);
    expect(result.current.items[0].file.name).toBe("second.jpg");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(firstUrl);
  });

  it("reports rejected files without adding them", async () => {
    mocks.validate.mockResolvedValue({ ok: false, message: "Плохой файл." });
    const { result } = renderHook(() => useImageSelection({ mode: "single", maxFiles: 1 }));

    await act(async () => {
      await result.current.addFiles([jpeg("bad.jpg")]);
    });

    expect(result.current.items).toHaveLength(0);
    expect(result.current.errors).toEqual(["Плохой файл."]);
  });

  it("enforces the maximum number of images", async () => {
    mocks.validate.mockResolvedValue({ ok: true, dimensions: { width: 10, height: 10 } });
    const { result } = renderHook(() => useImageSelection({ mode: "multiple", maxFiles: 1 }));

    await act(async () => {
      await result.current.addFiles([jpeg("one.jpg"), jpeg("two.jpg")]);
    });

    expect(result.current.items).toHaveLength(1);
    expect(result.current.errors.join(" ")).toContain("не более 1");
  });

  it("revokes the preview URL when an image is removed", async () => {
    mocks.validate.mockResolvedValue({ ok: true, dimensions: { width: 10, height: 10 } });
    const { result } = renderHook(() => useImageSelection({ mode: "single", maxFiles: 1 }));

    await act(async () => {
      await result.current.addFiles([jpeg("one.jpg")]);
    });
    const previewUrl = result.current.items[0].previewUrl;

    act(() => {
      result.current.remove(result.current.items[0].id);
    });

    expect(result.current.items).toHaveLength(0);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(previewUrl);
  });

  it("revokes remaining preview URLs on unmount", async () => {
    mocks.validate.mockResolvedValue({ ok: true, dimensions: { width: 10, height: 10 } });
    const { result, unmount } = renderHook(() =>
      useImageSelection({ mode: "single", maxFiles: 1 }),
    );

    await act(async () => {
      await result.current.addFiles([jpeg("one.jpg")]);
    });
    const previewUrl = result.current.items[0].previewUrl;

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(previewUrl);
  });
});
