import { describe, expect, it } from "vitest";

import { formatDate, formatFileSize, pluralizeImages } from "./format";

describe("formatFileSize", () => {
  it("uses bytes for small files", () => {
    expect(formatFileSize(512)).toBe("512 Б");
  });

  it("uses kilobytes for medium files", () => {
    expect(formatFileSize(2048)).toBe("2 КБ");
  });

  it("uses megabytes for large files", () => {
    expect(formatFileSize(1.5 * 1024 * 1024)).toBe("1.5 МБ");
  });

  it("handles invalid values", () => {
    expect(formatFileSize(Number.NaN)).toBe("—");
    expect(formatFileSize(-1)).toBe("—");
  });
});

describe("pluralizeImages", () => {
  it.each([
    [1, "1 изображение"],
    [2, "2 изображения"],
    [4, "4 изображения"],
    [5, "5 изображений"],
    [11, "11 изображений"],
    [21, "21 изображение"],
  ])("formats %i images", (count, expected) => {
    expect(pluralizeImages(count)).toBe(expected);
  });
});

describe("formatDate", () => {
  it("formats an ISO timestamp", () => {
    expect(formatDate("2026-11-05T12:00:00Z")).toMatch(/2026/);
  });

  it("handles an invalid timestamp", () => {
    expect(formatDate("not-a-date")).toBe("—");
  });
});
