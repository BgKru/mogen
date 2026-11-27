"""Persisted scene representation and method selection (15 Section 4.2).

The representation is a *deployment* setting, but it must be frozen into the
generation task at creation time: worker routing, retries and recovery read the
persisted value, so changing ``SCENE_REPRESENTATION`` afterwards cannot make a
queued task run a different algorithm than the one the API accepted.

Only two representations are defined. ``MESH`` is the released COLMAP + OpenMVS
path and the default for every task that has no persisted value (including rows
created before increment 15). ``GAUSSIAN_SPLAT`` is the opt-in Nerfstudio
Splatfacto path.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.db.models.enums import TaskType

MESH = "MESH"
GAUSSIAN_SPLAT = "GAUSSIAN_SPLAT"
REPRESENTATIONS: tuple[str, ...] = (MESH, GAUSSIAN_SPLAT)

MESH_METHOD = "COLMAP_OPENMVS"
SPLAT_METHOD = "NERFSTUDIO_SPLATFACTO"
METHODS: tuple[str, ...] = (MESH_METHOD, SPLAT_METHOD)

MESH_ALGORITHM = "COLMAP_OPENMVS"
SPLAT_ALGORITHM = "COLMAP_SPLATFACTO"

GLB_FORMAT = "GLB"
PLY_FORMAT = "PLY"


class SceneRepresentation(StrEnum):
    """The two supported scene result representations."""

    MESH = MESH
    GAUSSIAN_SPLAT = GAUSSIAN_SPLAT


class SceneMethod(StrEnum):
    """The algorithm that produces one representation."""

    COLMAP_OPENMVS = MESH_METHOD
    NERFSTUDIO_SPLATFACTO = SPLAT_METHOD


def configured_representation(settings: Any) -> SceneRepresentation:
    """Return the validated deployment representation, ``MESH`` by default."""
    raw = getattr(settings, "scene_representation", "mesh") or "mesh"
    normalized = str(raw).strip().upper()
    if normalized not in REPRESENTATIONS:
        raise ValueError(f"scene_representation must be one of {REPRESENTATIONS}")
    if normalized == GAUSSIAN_SPLAT and not bool(getattr(settings, "scene_splat_enabled", False)):
        raise ValueError("scene_representation=gaussian_splat requires scene_splat_enabled=true")
    return SceneRepresentation(normalized)


def parameters_for_representation(representation: SceneRepresentation) -> dict[str, str]:
    """Return the logical task parameters for one representation."""
    if representation is SceneRepresentation.GAUSSIAN_SPLAT:
        return {
            "algorithm": SPLAT_ALGORITHM,
            "output_format": PLY_FORMAT,
            "representation": GAUSSIAN_SPLAT,
            "method": SPLAT_METHOD,
        }
    return {
        "algorithm": MESH_ALGORITHM,
        "output_format": GLB_FORMAT,
        "representation": MESH,
        "method": MESH_METHOD,
    }


def task_parameters_for(task_type: TaskType, settings: Any | None = None) -> dict[str, str]:
    """Return the generation parameters persisted with a new task.

    Object generation is unchanged. Scene tasks always carry an explicit
    representation and method; ``settings=None`` yields the mesh defaults so
    callers that only need the logical contract keep working.
    """
    if task_type is TaskType.OBJECT:
        return {"algorithm": "TripoSR", "output_format": GLB_FORMAT}
    representation = (
        configured_representation(settings) if settings is not None else SceneRepresentation.MESH
    )
    return parameters_for_representation(representation)


def persisted_representation(parameters: dict[str, Any] | None) -> SceneRepresentation:
    """Read the representation from a persisted task, defaulting to mesh.

    Rows created before increment 15 have no field and therefore resolve to the
    released mesh path, which is the documented backward-compatible behaviour.
    """
    value = (parameters or {}).get("representation")
    if value is None:
        return SceneRepresentation.MESH
    normalized = str(value).strip().upper()
    if normalized not in REPRESENTATIONS:
        raise ValueError(f"unknown persisted scene representation {value!r}")
    return SceneRepresentation(normalized)


def persisted_method(parameters: dict[str, Any] | None) -> str:
    """Return the persisted method, deriving it from the representation if absent."""
    value = (parameters or {}).get("method")
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    representation = persisted_representation(parameters)
    return SPLAT_METHOD if representation is SceneRepresentation.GAUSSIAN_SPLAT else MESH_METHOD


def result_format_for(representation: SceneRepresentation) -> str:
    """Return the asset format registered for a representation."""
    return PLY_FORMAT if representation is SceneRepresentation.GAUSSIAN_SPLAT else GLB_FORMAT


def task_matches_capability(parameters: dict[str, Any] | None, capability: str) -> bool:
    """Return True when a persisted task belongs to the worker's representation.

    A worker registers exactly one capability; executing the other
    representation would produce an artifact of the wrong type, so the adapter
    rejects it with ``SCENE_WORKER_INCOMPATIBLE`` (15 Section 4.2).
    """
    normalized = capability.strip().upper()
    if normalized not in REPRESENTATIONS:
        raise ValueError(f"unknown scene worker capability {capability!r}")
    return persisted_representation(parameters).value == normalized


__all__ = [
    "GAUSSIAN_SPLAT",
    "GLB_FORMAT",
    "MESH",
    "MESH_ALGORITHM",
    "MESH_METHOD",
    "METHODS",
    "PLY_FORMAT",
    "REPRESENTATIONS",
    "SPLAT_ALGORITHM",
    "SPLAT_METHOD",
    "SceneMethod",
    "SceneRepresentation",
    "configured_representation",
    "parameters_for_representation",
    "persisted_method",
    "persisted_representation",
    "result_format_for",
    "task_matches_capability",
    "task_parameters_for",
]
