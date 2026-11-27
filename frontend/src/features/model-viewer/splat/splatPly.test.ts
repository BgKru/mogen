import { describe, expect, it } from "vitest";

import { MAX_SPLAT_ARTIFACT_BYTES, parseSplatPly } from "./splatPly";
import { ViewerLoadError } from "../types/viewer.types";

const PROPERTIES = [
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

function buildPly(
  count: number,
  options: { properties?: string[]; nanPosition?: boolean; format?: string } = {},
): ArrayBuffer {
  const properties = options.properties ?? PROPERTIES;
  const header = [
    "ply",
    `format ${options.format ?? "binary_little_endian 1.0"}`,
    "comment fixture",
    `element vertex ${count}`,
    ...properties.map((name) => `property float ${name}`),
    "end_header",
    "",
  ].join("\n");
  const headerBytes = new TextEncoder().encode(header);
  const stride = properties.length * 4;
  const buffer = new ArrayBuffer(headerBytes.length + count * stride);
  new Uint8Array(buffer).set(headerBytes);
  const view = new DataView(buffer);
  for (let vertex = 0; vertex < count; vertex += 1) {
    for (let property = 0; property < properties.length; property += 1) {
      const name = properties[property];
      let value = 0;
      if (name === "x") value = vertex - count / 2;
      if (name === "y") value = vertex * 0.25;
      if (name === "z") value = 1;
      if (name === "opacity") value = 2;
      if (name === "rot_0") value = 1;
      if (name.startsWith("scale_")) value = -2;
      if (options.nanPosition && name === "x" && vertex === 0) value = Number.NaN;
      view.setFloat32(headerBytes.length + vertex * stride + property * 4, value, true);
    }
  }
  return buffer;
}

describe("parseSplatPly", () => {
  it("reads the pinned Nerfstudio schema and measures the splat bounds", () => {
    const parsed = parseSplatPly(buildPly(4));

    expect(parsed.header.vertexCount).toBe(4);
    expect(parsed.header.shDegree).toBe(3);
    expect(parsed.stats).toMatchObject({
      gaussianCount: 4,
      shDegree: 3,
      propertyCount: PROPERTIES.length,
    });
    expect(parsed.bounds.center.x).toBeCloseTo(-0.5, 5);
    expect(parsed.bounds.size.z).toBe(0);
    expect(parsed.bounds.radius).toBeGreaterThan(0);
  });

  it("infers lower spherical-harmonics degrees", () => {
    const properties = ["x", "y", "z", "opacity", "scale_0", "rot_0", "f_dc_0", "f_dc_1", "f_dc_2"];
    const parsed = parseSplatPly(buildPly(2, { properties }));

    expect(parsed.header.shDegree).toBe(0);
  });

  it("rejects a non-binary or big-endian PLY", () => {
    expect(() => parseSplatPly(buildPly(2, { format: "ascii 1.0" }))).toThrow(ViewerLoadError);
    try {
      parseSplatPly(buildPly(2, { format: "binary_big_endian 1.0" }));
    } catch (error) {
      expect((error as ViewerLoadError).code).toBe("UNSUPPORTED_ASSET");
    }
  });

  it("rejects a point cloud without Gaussian properties", () => {
    const properties = ["x", "y", "z", "red", "green", "blue"];

    expect(() => parseSplatPly(buildPly(2, { properties }))).toThrow(ViewerLoadError);
  });

  it("rejects a truncated payload", () => {
    const buffer = buildPly(4);
    const truncated = buffer.slice(0, buffer.byteLength - 8);

    try {
      parseSplatPly(truncated);
      throw new Error("expected a parse failure");
    } catch (error) {
      expect((error as ViewerLoadError).code).toBe("PARSE_FAILED");
    }
  });

  it("rejects non-finite positions", () => {
    try {
      parseSplatPly(buildPly(4, { nanPosition: true }));
      throw new Error("expected a parse failure");
    } catch (error) {
      expect((error as ViewerLoadError).code).toBe("PARSE_FAILED");
    }
  });

  it("rejects an artifact above the viewer limit before parsing", () => {
    const oversized = { byteLength: MAX_SPLAT_ARTIFACT_BYTES + 1 } as unknown as ArrayBuffer;

    try {
      parseSplatPly(oversized);
      throw new Error("expected a size failure");
    } catch (error) {
      expect((error as ViewerLoadError).code).toBe("ASSET_TOO_LARGE");
    }
  });
});
