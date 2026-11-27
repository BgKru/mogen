"""Normal validation and correction (14 Section 5.3).

Normals are derived from valid faces, never from a global "flip everything"
heuristic. Winding correction is limited to a watertight single component where
a reliable orientation can be inferred; open meshes keep their winding and the
skip is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh


class NormalError(Exception):
    """Raised when usable normals cannot be produced."""

    error_code = "NORMAL_GENERATION_FAILED"


@dataclass(frozen=True, slots=True)
class NormalOutcome:
    """What the normal stage did."""

    normals: np.ndarray
    computed: bool
    winding_corrected: bool
    skipped: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "computed": self.computed,
            "winding_corrected": self.winding_corrected,
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "vectors_count": int(len(self.normals)),
        }


def _cached_normals(mesh: trimesh.Trimesh) -> Any:
    """Return the cached normal array without triggering trimesh's slow path."""
    try:
        cache = getattr(mesh, "_cache", None)
        values = getattr(cache, "cache", None)
        if isinstance(values, dict):
            return values.get("vertex_normals")
    except Exception:
        return None
    return None


def _normals_are_valid(normals: Any, vertex_count: int) -> bool:
    try:
        values = np.asarray(normals, dtype=np.float64)
    except Exception:
        return False
    if values.ndim != 2 or values.shape[1] != 3 or len(values) != vertex_count:
        return False
    if not np.isfinite(values).all():
        return False
    return bool((np.linalg.norm(values, axis=1) > 1e-9).all())


def validate_normals(mesh: trimesh.Trimesh) -> bool:
    """Return whether the mesh currently exposes finite, non-zero normals.

    Only an already-materialised cache counts. Trimesh's lazy normal path falls
    back to a dense O(vertices x faces) computation when SciPy is absent (the
    scene worker), which is far too slow for large scenes.
    """
    return _normals_are_valid(_cached_normals(mesh), len(mesh.vertices))


def _fast_vertex_normals(mesh: trimesh.Trimesh) -> np.ndarray:
    """Area-weighted vertex normals without trimesh's sparse/Scipy fallback."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    triangles = vertices[faces]
    face_normals = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )
    summed = np.zeros_like(vertices)
    np.add.at(summed, faces[:, 0], face_normals)
    np.add.at(summed, faces[:, 1], face_normals)
    np.add.at(summed, faces[:, 2], face_normals)
    lengths = np.linalg.norm(summed, axis=1)
    if not np.isfinite(lengths).all() or bool((lengths <= 1e-12).any()):
        raise NormalError("Computed vertex normals are non-finite or zero-length.")
    return summed / lengths[:, None]


def ensure_normals(
    mesh: trimesh.Trimesh,
    *,
    allow_winding_correction: bool = True,
) -> NormalOutcome:
    """Compute valid vertex normals, correcting winding only when safe.

    A missing normal cache is not a failure: normals are derived from the faces
    with an area-weighted NumPy pass. A mesh whose faces cannot produce finite
    non-zero normals raises :class:`NormalError`.
    """
    skipped: list[str] = []
    warnings: list[str] = []
    if len(mesh.faces) == 0:
        raise NormalError("The mesh has no faces from which to derive normals.")

    winding_corrected = False
    if allow_winding_correction:
        try:
            watertight = bool(mesh.is_watertight)
            body_count = int(mesh.body_count)
        except Exception:
            watertight = False
            body_count = 0
        if watertight and body_count <= 1:
            try:
                if not bool(mesh.is_winding_consistent):
                    trimesh.repair.fix_normals(mesh, multibody=False)
                    winding_corrected = True
            except Exception as exc:  # repair is optional; never invent a shape
                warnings.append(f"winding_correction_failed:{type(exc).__name__}")
        else:
            skipped.append("open_or_multibody_winding_unverified")

    normals = _fast_vertex_normals(mesh)
    mesh.vertex_normals = normals
    return NormalOutcome(
        normals=normals,
        computed=True,
        winding_corrected=winding_corrected,
        skipped=tuple(skipped),
        warnings=tuple(warnings),
    )


__all__ = ["NormalError", "NormalOutcome", "ensure_normals", "validate_normals"]
