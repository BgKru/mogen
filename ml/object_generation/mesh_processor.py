"""Mesh validation and statistics (06_object_generation.md Section 9).

TripoSR returns a ``trimesh.Trimesh`` per scene code. A mesh is accepted only
when it has real geometry: at least one triangle, finite vertices, valid face
indices and a strictly positive bounding box. It does not need to be watertight
(06 Section 9.4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from .exceptions import INVALID_MESH, MESH_EXTRACTION_FAILED, MeshError

logger = logging.getLogger(__name__)

_MIN_EXTENT = 1e-6


@dataclass(frozen=True, slots=True)
class MeshStats:
    """Geometry facts recorded with the result metadata (06 Section 12.5)."""

    vertices_count: int
    faces_count: int
    bounding_box: dict[str, float]
    has_vertex_colors: bool
    is_watertight: bool
    has_textures: bool = False
    has_uvs: bool = False

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSONB-safe subset stored with the result."""
        return {
            "vertices_count": self.vertices_count,
            "faces_count": self.faces_count,
            "meshes_count": 1,
            "bounding_box": self.bounding_box,
            "has_vertex_colors": self.has_vertex_colors,
            "has_textures": self.has_textures,
            "has_uvs": self.has_uvs,
            "watertight": self.is_watertight,
        }


def _ensure_vertex_colors(mesh: Any) -> None:
    """Normalize TripoSR float colours (0..1) to the uint8 trimesh expects."""
    try:
        colors = np.asarray(mesh.visual.vertex_colors)
    except Exception:
        return
    if colors.size == 0:
        return
    if colors.dtype.kind == "f" and colors.max() <= 1.0 + 1e-6:
        mesh.visual.vertex_colors = np.clip(colors * 255.0, 0, 255).astype(np.uint8)


def validate_mesh(mesh: Any) -> MeshStats:
    """Validate reconstructed geometry and return its statistics.

    Raises :class:`MeshError` with ``INVALID_MESH`` when validation fails.
    """
    if mesh is None:
        raise MeshError(MESH_EXTRACTION_FAILED, "Mesh extraction returned no geometry.")

    try:
        vertices = np.asarray(mesh.vertices)
        faces = np.asarray(mesh.faces)
    except Exception as exc:
        raise MeshError(INVALID_MESH, "The reconstructed mesh is unreadable.") from exc

    if vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.shape[0] < 3:
        raise MeshError(INVALID_MESH, "The reconstructed mesh has no valid vertices.")
    if faces.ndim != 2 or faces.shape[1] != 3 or faces.shape[0] < 1:
        raise MeshError(INVALID_MESH, "The reconstructed mesh has no valid faces.")
    if not np.isfinite(vertices).all():
        raise MeshError(INVALID_MESH, "The reconstructed mesh contains non-finite vertices.")
    if not np.issubdtype(faces.dtype, np.integer):
        if not np.isfinite(faces).all():
            raise MeshError(INVALID_MESH, "The reconstructed mesh has invalid face indices.")
        faces = faces.astype(np.int64)
    if faces.min() < 0 or faces.max() >= vertices.shape[0]:
        raise MeshError(INVALID_MESH, "The reconstructed mesh has out-of-range face indices.")

    extents = vertices.max(axis=0) - vertices.min(axis=0)
    if not np.isfinite(extents).all() or np.any(extents <= _MIN_EXTENT):
        raise MeshError(INVALID_MESH, "The reconstructed mesh has a degenerate bounding box.")

    # TripoSR normally supplies vertex colours; ask trimesh to materialize the
    # visual only when it has not. Missing colours are not fatal here because
    # OBJ-AC-10 is checked on the exported GLB (validator), where a missing
    # COLOR_0 is a hard failure.
    _ensure_vertex_colors(mesh)
    try:
        has_colors = mesh.visual is not None and mesh.visual.kind in {"vertex", "face"}
    except Exception:
        has_colors = False
    try:
        kind = getattr(mesh.visual, "kind", None)
        has_textures = kind == "texture" and getattr(mesh.visual, "material", None) is not None
        uv = getattr(mesh.visual, "uv", None)
        has_uvs = has_textures and uv is not None and len(uv) == int(vertices.shape[0])
    except Exception:
        has_textures = False
        has_uvs = False

    # A missing normal cache is fine: the GLB exporter writes the geometry and
    # Three.js computes normals when they are absent (06 Section 9.5).
    try:
        watertight = bool(mesh.is_watertight)
    except Exception:
        watertight = False

    stats = MeshStats(
        vertices_count=int(vertices.shape[0]),
        faces_count=int(faces.shape[0]),
        bounding_box={
            "width": round(float(extents[0]), 6),
            "height": round(float(extents[1]), 6),
            "depth": round(float(extents[2]), 6),
        },
        has_vertex_colors=has_colors,
        is_watertight=watertight,
        has_textures=has_textures,
        has_uvs=has_uvs,
    )
    logger.info(
        "mesh_validated",
        extra={
            "operation": "object_generation",
            "vertices_count": stats.vertices_count,
            "faces_count": stats.faces_count,
        },
    )
    return stats
