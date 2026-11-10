"""Mesh loading, geometry validation and scene statistics (07 Sections 10.9 and 18).

trimesh is used only in the scene worker; the API image never imports it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import trimesh

from .exceptions import (
    GLB_VALIDATION_FAILED,
    MESH_GENERATION_FAILED,
    SceneReconstructionError,
)

_PLY_VERTEX = re.compile(r"^element\s+vertex\s+(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class MeshStats:
    """Geometry facts used to reject an unusable mesh."""

    vertices: int
    faces: int
    bounds: dict[str, float] = field(default_factory=dict)
    watertight: bool = False
    source: str = ""

    def as_metadata(self) -> dict[str, Any]:
        return {
            "vertices_count": self.vertices,
            "faces_count": self.faces,
            "bounding_box": self.bounds,
            "watertight": self.watertight,
        }


def count_ply_vertices(path: Path) -> int | None:
    """Read the vertex count from a PLY header without loading the data."""
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(8192).decode("ascii", errors="replace")
    except OSError:
        return None
    match = _PLY_VERTEX.search(header)
    if match is None:
        return None
    return int(match.group(1))


def load_scene(path: Path) -> trimesh.Scene:
    """Load an OBJ/GLB/PLY asset as a trimesh scene."""
    try:
        loaded = trimesh.load(str(path), force="scene")
    except Exception as exc:  # trimesh raises several unrelated types
        raise SceneReconstructionError(
            GLB_VALIDATION_FAILED, "The generated mesh could not be parsed."
        ) from exc
    if not isinstance(loaded, trimesh.Scene):
        scene = trimesh.Scene()
        scene.add_geometry(loaded)
        return scene
    return loaded


def _geometry_stats(geometry: trimesh.Trimesh) -> tuple[int, int, list[float], list[float], bool]:
    vertices = int(len(geometry.vertices))
    faces = int(len(geometry.faces))
    bounds = geometry.bounds
    if bounds is None:
        return vertices, faces, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], False
    lower = [float(value) for value in bounds[0]]
    upper = [float(value) for value in bounds[1]]
    return vertices, faces, lower, upper, bool(geometry.is_watertight)


def scene_mesh_stats(scene: trimesh.Scene, *, source: str = "") -> MeshStats:
    """Sum geometry facts over every mesh in a scene."""
    vertices = 0
    faces = 0
    lowest = [math.inf, math.inf, math.inf]
    highest = [-math.inf, -math.inf, -math.inf]
    watertight = True
    geometry_count = 0
    for geometry in scene.geometry.values():
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        geometry_count += 1
        v, f, lower, upper, tight = _geometry_stats(geometry)
        vertices += v
        faces += f
        watertight = watertight and tight
        for axis in range(3):
            lowest[axis] = min(lowest[axis], lower[axis])
            highest[axis] = max(highest[axis], upper[axis])
    extents = (
        [round(highest[axis] - lowest[axis], 6) for axis in range(3)]
        if geometry_count
        else [0.0, 0.0, 0.0]
    )
    if not all(math.isfinite(value) for value in extents):
        extents = [0.0, 0.0, 0.0]
    return MeshStats(
        vertices=vertices,
        faces=faces,
        bounds={"width": extents[0], "height": extents[1], "depth": extents[2]},
        watertight=watertight and geometry_count > 0,
        source=source,
    )


def inspect_mesh(path: Path, *, error_code: str = MESH_GENERATION_FAILED) -> MeshStats:
    """Load a mesh file and reject empty or degenerate geometry."""
    target = Path(path)
    if not target.is_file() or target.stat().st_size <= 0:
        raise SceneReconstructionError(error_code, "The generated mesh is missing or empty.")
    try:
        loaded = trimesh.load(str(target), force="scene")
    except Exception as exc:
        raise SceneReconstructionError(
            error_code, "The generated mesh could not be parsed."
        ) from exc
    scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
    stats = scene_mesh_stats(scene, source=str(target))
    validate_mesh_stats(stats, error_code=error_code)
    return stats


def validate_mesh_stats(stats: MeshStats, *, error_code: str = MESH_GENERATION_FAILED) -> None:
    """Apply the mesh checks from 07 Sections 10.9 and 18.3."""
    if stats.vertices < 3 or stats.faces < 1:
        raise SceneReconstructionError(
            error_code, "The generated mesh contains no usable polygon geometry."
        )
    extents = stats.bounds or {}
    if not all(float(extents.get(axis, 0.0)) > 1e-6 for axis in ("width", "height", "depth")):
        raise SceneReconstructionError(error_code, "The generated mesh bounding box is degenerate.")


__all__ = [
    "MeshStats",
    "count_ply_vertices",
    "inspect_mesh",
    "load_scene",
    "scene_mesh_stats",
    "validate_mesh_stats",
]
