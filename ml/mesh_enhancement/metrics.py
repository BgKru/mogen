"""Mesh metrics used for before/after enhancement diagnostics (14 Section 3.1).

The metrics are deliberately descriptive: they are recorded in the run
manifest and result metadata, never used to silently reject a valid asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

_GEOMETRY_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class MeshMetrics:
    """JSON-safe geometry and appearance facts for one mesh."""

    vertices: int
    faces: int
    components: int
    degenerate_faces: int
    duplicate_vertices: int
    unreferenced_vertices: int
    non_manifold_edges: int
    boundary_edges: int
    has_vertex_colors: bool
    has_uvs: bool
    has_textures: bool
    has_normals: bool
    bounding_box: dict[str, float]
    is_watertight: bool = False

    @property
    def degenerate_face_ratio(self) -> float:
        """Return the fraction of faces that are degenerate."""
        if self.faces <= 0:
            return 0.0
        return round(self.degenerate_faces / self.faces, 6)

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSONB-safe subset stored with the result."""
        return {
            "vertices_count": self.vertices,
            "faces_count": self.faces,
            "components_count": self.components,
            "degenerate_faces": self.degenerate_faces,
            "degenerate_face_ratio": self.degenerate_face_ratio,
            "duplicate_vertices": self.duplicate_vertices,
            "unreferenced_vertices": self.unreferenced_vertices,
            "non_manifold_edges": self.non_manifold_edges,
            "boundary_edges": self.boundary_edges,
            "has_vertex_colors": self.has_vertex_colors,
            "has_uvs": self.has_uvs,
            "has_textures": self.has_textures,
            "has_normals": self.has_normals,
            "bounding_box": self.bounding_box,
            "watertight": self.is_watertight,
        }


def _bounding_box(vertices: np.ndarray) -> dict[str, float]:
    if len(vertices) == 0:
        return {"width": 0.0, "height": 0.0, "depth": 0.0}
    extents = np.asarray(vertices, dtype=np.float64).max(axis=0) - np.asarray(
        vertices, dtype=np.float64
    ).min(axis=0)
    return {
        "width": round(float(extents[0]), 6),
        "height": round(float(extents[1]), 6),
        "depth": round(float(extents[2]), 6),
    }


def _bounding_diagonal(vertices: np.ndarray) -> float:
    if len(vertices) == 0:
        return 0.0
    extents = np.asarray(vertices, dtype=np.float64).max(axis=0) - np.asarray(
        vertices, dtype=np.float64
    ).min(axis=0)
    return float(np.linalg.norm(extents))


def _face_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    triangles = np.asarray(vertices, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return 0.5 * np.linalg.norm(cross, axis=1)


def _degenerate_faces(vertices: np.ndarray, faces: np.ndarray) -> int:
    if len(faces) == 0:
        return 0
    repeated = (
        (faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2])
    )
    diagonal = _bounding_diagonal(vertices)
    threshold = max(diagonal * diagonal * _GEOMETRY_EPSILON, _GEOMETRY_EPSILON)
    areas = _face_areas(vertices, faces)
    return int(np.count_nonzero(repeated | (areas <= threshold)))


def _edge_counts(faces: np.ndarray) -> tuple[int, int]:
    """Return (non-manifold edges, boundary edges) from triangle edges."""
    if len(faces) == 0:
        return 0, 0
    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]],
        axis=0,
    )
    edges = np.sort(edges, axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    return int(np.count_nonzero(counts > 2)), int(np.count_nonzero(counts == 1))


def _components(mesh: trimesh.Trimesh) -> int:
    if len(mesh.faces) == 0:
        return 0
    try:
        parts = trimesh.graph.connected_components(
            mesh.face_adjacency, nodes=np.arange(len(mesh.faces))
        )
        return len(parts)
    except Exception:
        try:
            parts = mesh.split(only_watertight=False)
        except Exception:
            return 1
        return len(parts) if parts else 0


def _duplicate_vertices(vertices: np.ndarray, tolerance: float) -> int:
    if len(vertices) == 0:
        return 0
    if tolerance <= 0:
        unique = np.unique(np.asarray(vertices, dtype=np.float64), axis=0)
    else:
        keys = np.round(np.asarray(vertices, dtype=np.float64) / tolerance).astype(np.int64)
        unique = np.unique(keys, axis=0)
    return int(len(vertices) - len(unique))


def _visual_facts(mesh: trimesh.Trimesh) -> tuple[bool, bool, bool]:
    try:
        kind = getattr(mesh.visual, "kind", None)
    except Exception:
        return False, False, False
    uv = getattr(mesh.visual, "uv", None)
    has_uvs = uv is not None and len(uv) == len(mesh.vertices)
    colors = getattr(mesh.visual, "vertex_colors", None)
    has_colors = kind in {"vertex", "face"} or (
        colors is not None and len(colors) == len(mesh.vertices)
    )
    material = getattr(mesh.visual, "material", None)
    has_textures = False
    if kind == "texture" and material is not None:
        image = getattr(material, "baseColorTexture", None)
        if image is None:
            image = getattr(material, "image", None)
        has_textures = image is not None and (
            int(getattr(image, "width", 0)) > 2 or int(getattr(image, "height", 0)) > 2
        )
    return has_colors, bool(has_uvs), bool(has_textures)


def measure_mesh(mesh: trimesh.Trimesh, *, duplicate_tolerance: float = 1e-6) -> MeshMetrics:
    """Measure one mesh; never mutates it."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    faces = faces.reshape((-1, 3)) if faces.size else np.zeros((0, 3), dtype=np.int64)
    referenced = np.unique(faces) if len(faces) else np.zeros(0, dtype=np.int64)
    unreferenced = int(len(vertices) - len(referenced))
    non_manifold, boundary = _edge_counts(faces)
    has_colors, has_uvs, has_textures = _visual_facts(mesh)
    diagonal = _bounding_diagonal(vertices)
    tolerance = max(diagonal * float(duplicate_tolerance), 0.0)
    try:
        cache = getattr(mesh, "_cache", None)
        cached = getattr(cache, "cache", None)
        values = cached.get("vertex_normals") if isinstance(cached, dict) else None
        normals = np.asarray(values, dtype=np.float64) if values is not None else None
        has_normals = (
            normals is not None
            and normals.ndim == 2
            and normals.shape[1] == 3
            and len(normals) == len(vertices)
            and bool(np.isfinite(normals).all())
            and bool((np.linalg.norm(normals, axis=1) > 1e-9).all())
        )
    except Exception:
        has_normals = False
    try:
        watertight = bool(mesh.is_watertight)
    except Exception:
        watertight = False
    return MeshMetrics(
        vertices=int(len(vertices)),
        faces=int(len(faces)),
        components=_components(mesh),
        degenerate_faces=_degenerate_faces(vertices, faces),
        duplicate_vertices=_duplicate_vertices(vertices, tolerance),
        unreferenced_vertices=unreferenced,
        non_manifold_edges=non_manifold,
        boundary_edges=boundary,
        has_vertex_colors=has_colors,
        has_uvs=has_uvs,
        has_textures=has_textures,
        has_normals=has_normals,
        bounding_box=_bounding_box(vertices),
        is_watertight=watertight,
    )


def bounding_diagonal(mesh: trimesh.Trimesh) -> float:
    """Return the scale used by tolerance and deviation checks."""
    return _bounding_diagonal(np.asarray(mesh.vertices, dtype=np.float64))


def face_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Expose the area helper for cleanup/tests."""
    return _face_areas(vertices, faces)


__all__ = ["MeshMetrics", "bounding_diagonal", "face_areas", "measure_mesh"]
