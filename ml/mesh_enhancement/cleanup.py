"""Conservative, deterministic mesh cleanup (14 Sections 5.1 and 3.1).

Only operations that cannot invent or remove intentional shape detail are
implemented: repeated-index/zero-area face removal, unreferenced-vertex removal,
bounded duplicate-vertex merging and optional small-component removal. Hole
filling, watertightness forcing and smoothing are deliberately absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

from .metrics import face_areas

_GEOMETRY_EPSILON = 1e-12


class CleanupError(Exception):
    """Raised when cleanup would leave no usable geometry."""

    error_code = "MESH_CLEANUP_FAILED"


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    """The cleaned mesh plus what changed."""

    mesh: trimesh.Trimesh
    faces_removed: int
    vertices_merged: int
    vertices_removed: int
    components_removed: int
    skipped: tuple[str, ...] = ()

    def as_metadata(self) -> dict[str, Any]:
        return {
            "faces_removed": self.faces_removed,
            "vertices_merged": self.vertices_merged,
            "vertices_removed": self.vertices_removed,
            "components_removed": self.components_removed,
            "skipped": list(self.skipped),
            "vertices_count": int(len(self.mesh.vertices)),
            "faces_count": int(len(self.mesh.faces)),
        }


def _visual_arrays(mesh: trimesh.Trimesh) -> tuple[np.ndarray | None, np.ndarray | None, Any]:
    """Return (vertex_colours, uv, material) without changing the mesh."""
    colors: np.ndarray | None = None
    uv: np.ndarray | None = None
    material = None
    try:
        kind = getattr(mesh.visual, "kind", None)
    except Exception:
        return None, None, None
    if kind in {"vertex", "face"}:
        try:
            raw = np.asarray(mesh.visual.vertex_colors)
            if raw.ndim == 2 and len(raw) == len(mesh.vertices):
                colors = raw.copy()
        except Exception:
            colors = None
    candidate_uv = getattr(mesh.visual, "uv", None)
    if candidate_uv is not None and len(candidate_uv) == len(mesh.vertices):
        uv = np.asarray(candidate_uv, dtype=np.float64).copy()
        material = getattr(mesh.visual, "material", None)
    return colors, uv, material


def _apply_cleanup_mask(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray | None,
    uv: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None, int]:
    """Remove repeated-index and zero-area faces, then unreferenced vertices."""
    if len(faces) == 0:
        return vertices, faces, colors, uv, 0
    repeated = (
        (faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2])
    )
    diagonal = bounding_diagonal_from_vertices(vertices)
    threshold = max(diagonal * diagonal * _GEOMETRY_EPSILON, _GEOMETRY_EPSILON)
    keep = ~repeated & (face_areas(vertices, faces) > threshold)
    removed = int(np.count_nonzero(~keep))
    faces = faces[keep]
    if len(faces) == 0:
        return vertices, faces, colors, uv, removed

    keep_indices = np.unique(faces)
    if len(keep_indices) != len(vertices):
        remap = np.full(len(vertices), -1, dtype=np.int64)
        remap[keep_indices] = np.arange(len(keep_indices), dtype=np.int64)
        faces = remap[faces]
        vertices = vertices[keep_indices]
        if colors is not None:
            colors = colors[keep_indices]
        if uv is not None:
            uv = uv[keep_indices]
    return vertices, faces, colors, uv, removed


def bounding_diagonal_from_vertices(vertices: np.ndarray) -> float:
    if len(vertices) == 0:
        return 0.0
    values = np.asarray(vertices, dtype=np.float64)
    return float(np.linalg.norm(values.max(axis=0) - values.min(axis=0)))


def _merge_duplicate_vertices(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray | None,
    *,
    tolerance: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, int]:
    """Merge vertices within ``tolerance``; positions/colours use group means."""
    if tolerance <= 0 or len(vertices) == 0:
        keys = np.asarray(vertices, dtype=np.float64)
    else:
        keys = np.round(np.asarray(vertices, dtype=np.float64) / tolerance).astype(np.int64)
    unique_keys, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    merged = int(len(vertices) - len(unique_keys))
    if merged <= 0:
        return vertices, faces, colors, 0

    sums = np.zeros((len(unique_keys), 3), dtype=np.float64)
    np.add.at(sums, inverse, np.asarray(vertices, dtype=np.float64))
    new_vertices = sums / counts[:, None]
    new_colors = None
    if colors is not None:
        if colors.dtype.kind == "f" and np.nanmax(colors) <= 1.0 + 1e-6:
            colors = np.clip(colors * 255.0, 0, 255)
        color_sums = np.zeros((len(unique_keys), colors.shape[1]), dtype=np.float64)
        np.add.at(color_sums, inverse, colors.astype(np.float64))
        new_colors = np.clip(color_sums / counts[:, None], 0, 255).astype(np.uint8)
    new_faces = inverse[faces]
    return new_vertices, new_faces, new_colors, merged


def cleanup_mesh(
    mesh: trimesh.Trimesh,
    *,
    merge_tolerance_ratio: float = 1e-6,
    remove_small_components: bool = False,
    small_component_faces: int = 32,
) -> CleanupOutcome:
    """Apply the conservative cleanup pass and return a new mesh.

    ``merge_tolerance_ratio`` is a fraction of the mesh bounding-box diagonal,
    never a fixed world-unit value, so the same setting works for a centimetre
    object and a metre-scale scene (14 Section 5.1).
    """
    if mesh is None or len(mesh.faces) == 0:
        raise CleanupError("The mesh has no faces to clean.")
    vertices = np.asarray(mesh.vertices, dtype=np.float64).copy()
    faces = np.asarray(mesh.faces, dtype=np.int64).reshape((-1, 3)).copy()
    colors, uv, material = _visual_arrays(mesh)
    skipped: list[str] = []

    vertices, faces, colors, uv, faces_removed = _apply_cleanup_mask(vertices, faces, colors, uv)
    if len(faces) == 0:
        raise CleanupError("Cleanup removed every face; the source mesh is not usable.")

    merged = 0
    if uv is not None:
        skipped.append("duplicate_merge_skipped_uv_seams")
    elif merge_tolerance_ratio > 0:
        diagonal = bounding_diagonal_from_vertices(vertices)
        vertices, faces, colors, merged = _merge_duplicate_vertices(
            vertices,
            faces,
            colors,
            tolerance=diagonal * float(merge_tolerance_ratio),
        )
        vertices, faces, colors, uv, extra_removed = _apply_cleanup_mask(
            vertices, faces, colors, uv
        )
        faces_removed += extra_removed

    components_removed = 0
    if remove_small_components:
        if uv is not None:
            skipped.append("component_removal_skipped_textured")
        else:
            current = _build_mesh(vertices, faces, colors, None, None)
            parts = current.split(only_watertight=False)
            keep = [part for part in parts if len(part.faces) >= int(small_component_faces)]
            components_removed = len(parts) - len(keep)
            if keep and components_removed:
                current = trimesh.util.concatenate(keep)
                vertices = np.asarray(current.vertices, dtype=np.float64)
                faces = np.asarray(current.faces, dtype=np.int64)
                colors = np.asarray(current.visual.vertex_colors).copy()
            elif not keep:
                raise CleanupError("Cleanup removed every connected component.")

    cleaned = _build_mesh(vertices, faces, colors, uv, material)
    skipped_tuple = tuple(skipped)
    return CleanupOutcome(
        mesh=cleaned,
        faces_removed=faces_removed,
        vertices_merged=merged,
        vertices_removed=int(len(mesh.vertices) - len(cleaned.vertices)),
        components_removed=components_removed,
        skipped=skipped_tuple,
    )


def _build_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray | None,
    uv: np.ndarray | None,
    material: Any,
) -> trimesh.Trimesh:
    cleaned = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
        validate=False,
    )
    if uv is not None:
        cleaned.visual = trimesh.visual.TextureVisuals(
            uv=np.asarray(uv, dtype=np.float64), material=material
        )
    elif colors is not None and len(colors) == len(vertices):
        cleaned.visual.vertex_colors = np.asarray(colors, dtype=np.uint8)
    return cleaned


__all__ = [
    "CleanupError",
    "CleanupOutcome",
    "bounding_diagonal_from_vertices",
    "cleanup_mesh",
]
