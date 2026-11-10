"""Shared fixtures for the object-generation tests."""

from __future__ import annotations

import json
import struct

import numpy as np

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def build_glb_bytes(
    *,
    include_colors: bool = True,
    positions: np.ndarray | None = None,
    indices: np.ndarray | None = None,
) -> bytes:
    """Build a minimal, self-contained glTF 2.0 binary with one mesh."""
    if positions is None:
        positions = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
    if indices is None:
        indices = np.array([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3], dtype=np.uint16)
    colors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ][: len(positions)],
        dtype=np.float32,
    )
    if len(colors) < len(positions):
        colors = np.resize(colors, (len(positions), 3)).astype(np.float32)

    chunks: list[bytes] = [positions.astype(np.float32).tobytes()]
    buffer_views: list[dict] = [{"buffer": 0, "byteOffset": 0, "byteLength": positions.nbytes}]
    accessors: list[dict] = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": int(len(positions)),
            "type": "VEC3",
            "min": [float(value) for value in positions.min(axis=0)],
            "max": [float(value) for value in positions.max(axis=0)],
        }
    ]
    attributes = {"POSITION": 0}
    offset = positions.nbytes

    if include_colors:
        color_bytes = colors.astype(np.float32).tobytes()
        chunks.append(color_bytes)
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(color_bytes)})
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "componentType": 5126,
                "count": int(len(colors)),
                "type": "VEC3",
            }
        )
        attributes["COLOR_0"] = len(accessors) - 1
        offset += len(color_bytes)

    index_bytes = indices.astype(np.uint16).tobytes()
    chunks.append(index_bytes)
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(index_bytes)})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "componentType": 5123,
            "count": int(len(indices)),
            "type": "SCALAR",
        }
    )
    indices_accessor = len(accessors) - 1
    offset += len(index_bytes)

    binary = b"".join(chunks)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    document = {
        "asset": {"version": "2.0", "generator": "mogen-tests"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": attributes, "indices": indices_accessor}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)

    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    header = struct.pack("<III", GLB_MAGIC, 2, total)
    json_chunk = struct.pack("<II", len(json_bytes), JSON_CHUNK) + json_bytes
    bin_chunk = struct.pack("<II", len(binary), BIN_CHUNK) + binary
    return header + json_chunk + bin_chunk


def colored_box():
    """Return a small watertight trimesh with vertex colours."""
    import numpy as np
    import trimesh

    mesh = trimesh.creation.box(extents=(1.0, 0.8, 0.6))
    colors = np.tile(np.array([[200, 60, 30, 255]], dtype=np.uint8), (len(mesh.vertices), 1))
    mesh.visual.vertex_colors = colors
    return mesh
