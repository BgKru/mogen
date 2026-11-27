import { Vector3 } from "three";

import type { ModelBounds, SplatStats } from "../types/viewer.types";
import { ViewerLoadError } from "../types/viewer.types";

/**
 * Maximum Gaussian PLY the viewer will buffer in memory.
 *
 * Mirrors the server-side `SCENE_SPLAT_MAX_ARTIFACT_BYTES` default (512 MiB).
 * The renderer needs the whole file in memory, so an artifact above this bound
 * is rejected with an explicit message instead of crashing the tab.
 */
export const MAX_SPLAT_ARTIFACT_BYTES = 512 * 1024 * 1024;

const HEADER_MAX_BYTES = 64 * 1024;
const FLOAT_BYTES = 4;
const PROPERTY_RE = /^property\s+float\s+(\S+)$/;
const F_REST_COUNTS: Record<number, number> = { 0: 0, 1: 9, 2: 24, 3: 45 };

export interface SplatPlyHeader {
  properties: string[];
  vertexCount: number;
  dataOffset: number;
  shDegree: number;
}

/** Read a null-terminated ASCII header from the start of a binary PLY file. */
function readHeader(buffer: ArrayBuffer): SplatPlyHeader {
  const limit = Math.min(buffer.byteLength, HEADER_MAX_BYTES);
  const bytes = new Uint8Array(buffer, 0, limit);
  let end = -1;
  for (let index = 0; index + 10 <= bytes.length; index += 1) {
    if (
      bytes[index] === 0x65 &&
      bytes[index + 1] === 0x6e &&
      bytes[index + 2] === 0x64 &&
      bytes[index + 3] === 0x5f &&
      bytes[index + 4] === 0x68 &&
      bytes[index + 5] === 0x65 &&
      bytes[index + 6] === 0x61 &&
      bytes[index + 7] === 0x64 &&
      bytes[index + 8] === 0x65 &&
      bytes[index + 9] === 0x72
    ) {
      end = index + 10;
      break;
    }
  }
  if (end < 0) {
    throw new ViewerLoadError("PARSE_FAILED", "Splat PLY header is incomplete.");
  }
  const text = new TextDecoder("ascii").decode(bytes.subarray(0, end));
  const lines = text.split(/\r?\n/).map((line) => line.trim());
  const dataOffset = end + (bytes[end] === 0x0d ? 2 : 1);
  if (lines[0] !== "ply") {
    throw new ViewerLoadError("UNSUPPORTED_ASSET", "The asset is not a PLY file.");
  }
  if (lines[1] !== "format binary_little_endian 1.0") {
    throw new ViewerLoadError(
      "UNSUPPORTED_ASSET",
      "Only binary little-endian Gaussian PLY files are supported.",
    );
  }
  let vertexCount: number | null = null;
  const properties: string[] = [];
  for (const line of lines.slice(2)) {
    if (line === "end_header") {
      break;
    }
    if (!line || line.startsWith("comment") || line.startsWith("obj_info")) {
      continue;
    }
    const element = /^element\s+vertex\s+(\d+)$/.exec(line);
    if (element) {
      vertexCount = Number(element[1]);
      continue;
    }
    const property = PROPERTY_RE.exec(line);
    if (property) {
      properties.push(property[1]);
    } else if (line.startsWith("element ") || line.startsWith("property ")) {
      throw new ViewerLoadError("UNSUPPORTED_ASSET", "Unsupported PLY element or property type.");
    }
  }
  if (vertexCount === null || vertexCount < 1 || properties.length === 0) {
    throw new ViewerLoadError("PARSE_FAILED", "The Gaussian PLY declares no splats.");
  }
  const rest = properties.filter((name) => name.startsWith("f_rest_")).length;
  const shDegree = Object.entries(F_REST_COUNTS).find(([, count]) => count === rest)?.[0];
  if (shDegree === undefined) {
    throw new ViewerLoadError("UNSUPPORTED_ASSET", "Unsupported spherical-harmonics layout.");
  }
  for (const required of ["x", "y", "z", "opacity", "scale_0", "rot_0"]) {
    if (!properties.includes(required)) {
      throw new ViewerLoadError(
        "UNSUPPORTED_ASSET",
        "The PLY is a point cloud, not Gaussian splats.",
      );
    }
  }
  return { properties, vertexCount, dataOffset, shDegree: Number(shDegree) };
}

/**
 * Parse the header and positions of a Nerfstudio Gaussian PLY.
 *
 * This runs on the bytes the viewer already downloads; it is deliberately
 * independent of the renderer so the format, splat count and bounds can be
 * validated (and reported) before any WebGL work starts.
 */
export function parseSplatPly(buffer: ArrayBuffer): {
  header: SplatPlyHeader;
  stats: SplatStats;
  bounds: ModelBounds;
} {
  if (buffer.byteLength > MAX_SPLAT_ARTIFACT_BYTES) {
    throw new ViewerLoadError("ASSET_TOO_LARGE", "The Gaussian PLY exceeds the viewer limit.");
  }
  const header = readHeader(buffer);
  const stride = header.properties.length * FLOAT_BYTES;
  const expected = header.dataOffset + header.vertexCount * stride;
  if (buffer.byteLength !== expected) {
    throw new ViewerLoadError("PARSE_FAILED", "The Gaussian PLY size does not match its header.");
  }
  const xIndex = header.properties.indexOf("x") * FLOAT_BYTES;
  const yIndex = header.properties.indexOf("y") * FLOAT_BYTES;
  const zIndex = header.properties.indexOf("z") * FLOAT_BYTES;
  const view = new DataView(buffer);
  const min = new Vector3(
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
  );
  const max = new Vector3(
    Number.NEGATIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
  );
  for (let vertex = 0; vertex < header.vertexCount; vertex += 1) {
    const base = header.dataOffset + vertex * stride;
    const x = view.getFloat32(base + xIndex, true);
    const y = view.getFloat32(base + yIndex, true);
    const z = view.getFloat32(base + zIndex, true);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      throw new ViewerLoadError("PARSE_FAILED", "The Gaussian PLY contains non-finite positions.");
    }
    min.x = Math.min(min.x, x);
    min.y = Math.min(min.y, y);
    min.z = Math.min(min.z, z);
    max.x = Math.max(max.x, x);
    max.y = Math.max(max.y, y);
    max.z = Math.max(max.z, z);
  }
  const size = max.clone().sub(min);
  const center = min.clone().add(max).multiplyScalar(0.5);
  return {
    header,
    stats: {
      gaussianCount: header.vertexCount,
      shDegree: header.shDegree,
      fileSizeBytes: buffer.byteLength,
      propertyCount: header.properties.length,
    },
    bounds: {
      center,
      size,
      radius: Math.max(size.length() / 2, 0.001),
    },
  };
}
