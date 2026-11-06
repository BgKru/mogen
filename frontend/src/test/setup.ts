import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

// jsdom does not implement object URLs; components use them for previews.
Object.defineProperty(URL, "createObjectURL", {
  writable: true,
  value: vi.fn(() => "blob:preview"),
});
Object.defineProperty(URL, "revokeObjectURL", {
  writable: true,
  value: vi.fn(),
});

beforeEach(() => {
  vi.clearAllMocks();
});
