"""Optional quadric simplification guarded by attribute/deviation checks.

No quadric simplifier is pinned in the worker images in this delivery, so the
production path raises :class:`SimplifierUnavailable` and the caller records a
safe skip with the original mesh. The guard itself (attribute preservation and
sampled surface deviation) is exercised by tests with an injected simplifier,
so enabling the operation later cannot silently accept a corrupt candidate
(14 Sections 5.2 and 10.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

_MAX_DEVIATION_SAMPLES = 4000


class SimplifierUnavailable(Exception):
    """Raised when no simplifier backend is installed in this image."""

    error_code = "SIMPLIFIER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SimplificationOutcome:
    """Result of an optional simplification attempt."""

    mesh: trimesh.Trimesh | None
    applied: bool
    reason: str
    before_faces: int
    after_faces: int
    deviation_ratio: float | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "reason": self.reason,
            "before_faces": self.before_faces,
            "after_faces": self.after_faces,
            "deviation_ratio": self.deviation_ratio,
        }


def _default_simplifier(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Use trimesh's quadric decimation when its backend is installed."""
    try:
        candidate = mesh.simplify_quadric_decimation(face_count=int(target_faces))
    except ImportError as exc:
        raise SimplifierUnavailable("fast_simplification is not installed") from exc
    except ModuleNotFoundError as exc:
        raise SimplifierUnavailable("fast_simplification is not installed") from exc
    except Exception as exc:
        raise SimplifierUnavailable(f"quadric decimation is unavailable: {exc}") from exc
    if not isinstance(candidate, trimesh.Trimesh):
        raise SimplifierUnavailable("the simplifier returned an unsupported type")
    return candidate


def _deviation_ratio(source: trimesh.Trimesh, candidate: trimesh.Trimesh) -> float:
    """Return sampled surface deviation as a fraction of the source diagonal.

    A KD-tree over candidate vertices and triangle centroids is used instead of
    trimesh's proximity query, which needs the optional ``rtree`` package. The
    scene worker has no SciPy, where the measurement is reported as unavailable
    and simplification safely skips.
    """
    try:
        from scipy.spatial import cKDTree

        stride = max(1, len(source.vertices) // 2000)
        face_stride = max(1, len(source.faces) // 2000)
        points = np.vstack(
            [
                np.asarray(source.vertices, dtype=np.float64)[::stride],
                np.asarray(source.triangles_center, dtype=np.float64)[::face_stride],
            ]
        )
        if len(points) > _MAX_DEVIATION_SAMPLES:
            step = int(np.ceil(len(points) / _MAX_DEVIATION_SAMPLES))
            points = points[::step]
        reference = np.vstack(
            [
                np.asarray(candidate.vertices, dtype=np.float64),
                np.asarray(candidate.triangles_center, dtype=np.float64),
            ]
        )
        distance, _ = cKDTree(reference).query(points, k=1)
    except Exception as exc:
        raise SimplifierUnavailable(f"deviation measurement is unavailable: {exc}") from exc
    diagonal = float(np.linalg.norm(source.bounds[1] - source.bounds[0]))
    if diagonal <= 1e-12 or not np.isfinite(diagonal):
        return 1.0
    return float(np.max(np.asarray(distance, dtype=np.float64)) / diagonal)


def _attributes_preserved(source: trimesh.Trimesh, candidate: trimesh.Trimesh) -> bool:
    """Require colours/UVs to survive with matching per-vertex counts."""
    try:
        source_kind = getattr(source.visual, "kind", None)
        candidate_kind = getattr(candidate.visual, "kind", None)
    except Exception:
        return False
    if source_kind in {"vertex", "face"}:
        if candidate_kind not in {"vertex", "face"}:
            return False
        try:
            if len(candidate.visual.vertex_colors) != len(candidate.vertices):
                return False
        except Exception:
            return False
    if source_kind == "texture":
        if candidate_kind != "texture":
            return False
        uv = getattr(candidate.visual, "uv", None)
        if uv is None or len(uv) != len(candidate.vertices):
            return False
    return True


def simplify_mesh(
    mesh: trimesh.Trimesh,
    *,
    target_faces: int,
    max_deviation_ratio: float,
    simplifier: Callable[[trimesh.Trimesh, int], trimesh.Trimesh] | None = None,
) -> SimplificationOutcome:
    """Simplify above the target budget, or return a recorded skip.

    The caller treats ``mesh is None`` as "keep the valid source". The
    simplifier is injectable so the guard can be tested without adding a
    production dependency.
    """
    before = int(len(mesh.faces))
    if target_faces <= 0 or before <= target_faces:
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="below_target_faces",
            before_faces=before,
            after_faces=before,
        )
    engine = simplifier or _default_simplifier
    try:
        candidate = engine(mesh, target_faces)
    except SimplifierUnavailable as exc:
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason=exc.error_code,
            before_faces=before,
            after_faces=before,
        )
    except Exception:
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="SIMPLIFICATION_FAILED",
            before_faces=before,
            after_faces=before,
        )
    if candidate is None or len(candidate.faces) == 0:
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="SIMPLIFICATION_EMPTY",
            before_faces=before,
            after_faces=before,
        )
    if len(candidate.faces) > target_faces * 1.05:
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="TARGET_FACES_NOT_MET",
            before_faces=before,
            after_faces=int(len(candidate.faces)),
        )
    if not _attributes_preserved(mesh, candidate):
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="ATTRIBUTES_NOT_PRESERVED",
            before_faces=before,
            after_faces=int(len(candidate.faces)),
        )
    try:
        deviation = _deviation_ratio(mesh, candidate)
    except SimplifierUnavailable:
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="DEVIATION_UNMEASURABLE",
            before_faces=before,
            after_faces=int(len(candidate.faces)),
        )
    if deviation > float(max_deviation_ratio):
        return SimplificationOutcome(
            mesh=None,
            applied=False,
            reason="DEVIATION_BUDGET_EXCEEDED",
            before_faces=before,
            after_faces=int(len(candidate.faces)),
            deviation_ratio=round(deviation, 6),
        )
    return SimplificationOutcome(
        mesh=candidate,
        applied=True,
        reason="APPLIED",
        before_faces=before,
        after_faces=int(len(candidate.faces)),
        deviation_ratio=round(deviation, 6),
    )


__all__ = [
    "SimplificationOutcome",
    "SimplifierUnavailable",
    "simplify_mesh",
]
