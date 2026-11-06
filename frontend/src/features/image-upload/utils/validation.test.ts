import { describe, expect, it, vi } from "vitest";

import { fileExtension, validateImageFile } from "./validation";

function imageFile(name = "photo.jpg", type = "image/jpeg", bytes = [1, 2, 3]): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

const decode = vi.fn(async () => ({ width: 640, height: 480 }));

describe("fileExtension", () => {
  it.each([
    ["photo.jpg", ".jpg"],
    ["photo.JPEG", ".jpeg"],
    ["archive.tar.png", ".png"],
    ["no-extension", ""],
  ])("extracts the extension of %s", (name, expected) => {
    expect(fileExtension(name)).toBe(expected);
  });
});

describe("validateImageFile", () => {
  it("accepts a valid JPEG", async () => {
    const result = await validateImageFile(imageFile(), { decode });

    expect(result).toEqual({ ok: true, dimensions: { width: 640, height: 480 } });
  });

  it("accepts a valid PNG", async () => {
    const result = await validateImageFile(imageFile("scene.png", "image/png"), { decode });

    expect(result.ok).toBe(true);
  });

  it("rejects an unsupported extension", async () => {
    const result = await validateImageFile(imageFile("photo.gif", "image/gif"), { decode });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("JPEG");
    }
  });

  it("rejects an unsupported MIME type", async () => {
    const result = await validateImageFile(imageFile("photo.jpg", "image/webp"), { decode });

    expect(result.ok).toBe(false);
    expect(decode).not.toHaveBeenCalled();
  });

  it("rejects an empty file", async () => {
    const result = await validateImageFile(imageFile("empty.jpg", "image/jpeg", []), { decode });

    expect(result).toEqual({ ok: false, message: "Файл пуст." });
  });

  it("rejects a file above the size limit", async () => {
    const result = await validateImageFile(imageFile("big.jpg", "image/jpeg", [1, 2, 3]), {
      decode,
      maxSizeBytes: 2,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("превышает");
    }
  });

  it("reports a file that cannot be decoded", async () => {
    const failingDecode = vi.fn(async () => {
      throw new Error("decode failed");
    });

    const result = await validateImageFile(imageFile(), { decode: failingDecode });

    expect(result).toEqual({ ok: false, message: "Не удалось прочитать изображение." });
  });

  it("rejects zero dimensions", async () => {
    const zeroDecode = vi.fn(async () => ({ width: 0, height: 0 }));

    const result = await validateImageFile(imageFile(), { decode: zeroDecode });

    expect(result.ok).toBe(false);
  });
});
