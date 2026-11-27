"""Optional post-reconstruction scene enhancement (14 Sections 3.2 and 4.2).

OpenMVS keeps ownership of photogrammetric refinement, texture projection and
atlas creation. This module runs only after those stages, mutates geometry in
place so node transforms and material-to-primitive associations survive, and
never unwraps or rebakes a textured OpenMVS mesh by default.
"""

from __future__ import annotations

import hashlib
import resource
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh
from mesh_enhancement import (
    build_enhancement_manifest,
    cleanup_mesh,
    ensure_normals,
    measure_mesh,
    mesh_fingerprint,
    simplify_mesh,
)

from .exceptions import (
    ENHANCEMENT_RESOURCE_EXHAUSTED,
    MEMORY_LIMIT_EXCEEDED,
    MESH_GENERATION_FAILED,
    SceneReconstructionError,
)

_POLL = Callable[[], None]


@dataclass(frozen=True, slots=True)
class SceneEnhancementConfig:
    """Validated scene enhancement policy; disabled by default."""

    postprocess_enabled: bool = False
    cleanup_enabled: bool = True
    normals_enabled: bool = True
    simplification_enabled: bool = False
    target_faces: int = 0
    max_deviation: float = 0.01
    generate_uv: bool = False
    ai_texture_enabled: bool = False
    fallback_to_original: bool = True
    max_memory_mb: int = 8192
    device: str = "cpu"

    def __post_init__(self) -> None:
        if self.target_faces < 0:
            message = "scene_mesh_target_faces must not be negative"
            raise ValueError(message)
        if self.simplification_enabled and self.target_faces <= 0:
            message = "scene_mesh_target_faces must be positive when simplification is enabled"
            raise ValueError(message)
        if not 0.0 < self.max_deviation <= 0.5:
            message = "scene_mesh_max_deviation must be in (0, 0.5]"
            raise ValueError(message)
        if self.generate_uv:
            message = (
                "scene UV regeneration is unavailable: OpenMVS UVs and atlases are "
                "preserved and must not be replaced by xatlas by default"
            )
            raise ValueError(message)
        if self.ai_texture_enabled:
            message = "scene AI texture generation is unavailable in this delivery"
            raise ValueError(message)
        if self.device.strip().lower() != "cpu":
            message = "texture_enhancement_device must be 'cpu' in this delivery"
            raise ValueError(message)
        if self.max_memory_mb < 256:
            message = "mesh_enhancement_max_memory_mb must be at least 256"
            raise ValueError(message)

    def as_manifest(self) -> dict[str, Any]:
        return {
            "postprocess_enabled": self.postprocess_enabled,
            "cleanup_enabled": self.cleanup_enabled,
            "normals_enabled": self.normals_enabled,
            "simplification_enabled": self.simplification_enabled,
            "target_faces": self.target_faces,
            "max_deviation": self.max_deviation,
            "generate_uv": False,
            "ai_texture_enabled": False,
            "fallback_to_original": self.fallback_to_original,
            "max_memory_mb": self.max_memory_mb,
            "device": self.device,
        }


@dataclass(slots=True)
class SceneEnhancementResult:
    """Enhanced scene plus compact per-geometry diagnostics."""

    scene: trimesh.Scene
    geometries: list[dict[str, Any]] = field(default_factory=list)
    before: dict[str, int] = field(default_factory=dict)
    after: dict[str, int] = field(default_factory=dict)
    operations: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normal_export: bool = False
    fallback_used: bool = False
    timings: dict[str, float] = field(default_factory=dict)
    peak_memory_mb: float | None = None
    manifest: dict[str, Any] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "scope": "scene",
            "operations": list(self.operations),
            "skipped": list(self.skipped),
            "warnings": sorted(set(self.warnings)),
            "fallback": {
                "used": self.fallback_used,
                "to": "original" if self.fallback_used else None,
            },
            "normal_export": self.normal_export,
            "before": dict(self.before),
            "after": dict(self.after),
            "geometries": list(self.geometries),
            "timings": dict(self.timings),
            "peak_memory_mb": self.peak_memory_mb,
            "manifest": dict(self.manifest),
        }


def _peak_rss_mb() -> float | None:
    try:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def scene_fingerprint(scene: trimesh.Scene) -> str:
    """Hash every geometry and the scene graph transforms."""
    digest = hashlib.sha256()
    for name in sorted(scene.geometry):
        geometry = scene.geometry[name]
        if isinstance(geometry, trimesh.Trimesh):
            digest.update(name.encode("utf-8", errors="replace"))
            digest.update(mesh_fingerprint(geometry).encode("ascii"))
    try:
        for node in sorted(scene.graph.nodes_geometry):
            transform, geometry_name = scene.graph[node]
            digest.update(f"{node}:{geometry_name}".encode("utf-8", errors="replace"))
            digest.update(np.ascontiguousarray(np.asarray(transform, dtype="<f8")).tobytes())
    except Exception:
        pass
    return digest.hexdigest()


def _totals(scene: trimesh.Scene) -> dict[str, Any]:
    totals: dict[str, int] = {
        "geometries": 0,
        "vertices_count": 0,
        "faces_count": 0,
        "components_count": 0,
        "degenerate_faces": 0,
        "duplicate_vertices": 0,
        "unreferenced_vertices": 0,
        "non_manifold_edges": 0,
    }
    for geometry in scene.geometry.values():
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        _accumulate_totals(totals, measure_mesh(geometry))
    return totals


def _empty_totals() -> dict[str, int]:
    return {
        "geometries": 0,
        "vertices_count": 0,
        "faces_count": 0,
        "components_count": 0,
        "degenerate_faces": 0,
        "duplicate_vertices": 0,
        "unreferenced_vertices": 0,
        "non_manifold_edges": 0,
    }


def _accumulate_totals(totals: dict[str, int], metrics: Any) -> None:
    totals["geometries"] += 1
    totals["vertices_count"] += metrics.vertices
    totals["faces_count"] += metrics.faces
    totals["components_count"] += metrics.components
    totals["degenerate_faces"] += metrics.degenerate_faces
    totals["duplicate_vertices"] += metrics.duplicate_vertices
    totals["unreferenced_vertices"] += metrics.unreferenced_vertices
    totals["non_manifold_edges"] += metrics.non_manifold_edges


def _is_textured(mesh: trimesh.Trimesh) -> bool:
    try:
        return getattr(mesh.visual, "kind", None) == "texture" and (
            getattr(mesh.visual, "material", None) is not None
        )
    except Exception:
        return False


def enhance_scene(
    scene: trimesh.Scene,
    config: SceneEnhancementConfig,
    *,
    on_poll: _POLL | None = None,
    simplifier: Callable[[trimesh.Trimesh, int], trimesh.Trimesh] | None = None,
) -> SceneEnhancementResult:
    """Apply conservative optional post-processing to a repacked scene.

    Geometry objects are replaced in ``scene.geometry``; nodes, transforms,
    materials and texture references are untouched. The caller exports the
    returned scene with the existing repack path.
    """
    poll = on_poll or (lambda: None)
    if not scene.geometry:
        raise SceneReconstructionError(MEMORY_LIMIT_EXCEEDED, "The scene contains no geometry.")
    result = SceneEnhancementResult(scene=scene, before=_empty_totals(), after=_empty_totals())
    result.peak_memory_mb = _peak_rss_mb()
    source_fingerprint = scene_fingerprint(scene)

    def budget_available(operation: str) -> bool:
        peak = _peak_rss_mb()
        result.peak_memory_mb = peak
        if peak is not None and peak > config.max_memory_mb:
            result.skipped.append(
                {"operation": operation, "reason": ENHANCEMENT_RESOURCE_EXHAUSTED}
            )
            result.warnings.append(ENHANCEMENT_RESOURCE_EXHAUSTED)
            return False
        return True

    for name in sorted(scene.geometry):
        geometry = scene.geometry[name]
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        current = geometry
        operations: list[str] = []
        skipped: list[dict[str, str]] = []
        record: dict[str, Any] = {"name": name}
        try:
            before = measure_mesh(current)
            record["before"] = before.as_metadata()
            record["textured"] = _is_textured(current)
            _accumulate_totals(result.before, before)
        except Exception as exc:
            if not config.fallback_to_original:
                raise SceneReconstructionError(
                    MESH_GENERATION_FAILED, f"Scene geometry {name!r} is unreadable."
                ) from exc
            skipped.append({"operation": "metrics", "reason": "GEOMETRY_UNREADABLE"})
            record["skipped"] = skipped
            result.geometries.append(record)
            continue

        if config.cleanup_enabled:
            if not budget_available("scene_mesh_cleanup"):
                skipped.append(
                    {"operation": "scene_mesh_cleanup", "reason": ENHANCEMENT_RESOURCE_EXHAUSTED}
                )
            else:
                poll()
                started = time.perf_counter()
                try:
                    outcome = cleanup_mesh(current)
                except Exception as exc:
                    if not config.fallback_to_original:
                        raise SceneReconstructionError(
                            MESH_GENERATION_FAILED,
                            f"Scene mesh cleanup failed for geometry {name!r}.",
                        ) from exc
                    result.fallback_used = True
                    skipped.append(
                        {"operation": "scene_mesh_cleanup", "reason": "MESH_CLEANUP_FAILED"}
                    )
                else:
                    current = outcome.mesh
                    result.timings["scene_mesh_cleanup"] = round(time.perf_counter() - started, 3)
                    operations.append("scene_mesh_cleanup")
                    record["cleanup"] = outcome.as_metadata()

        if config.normals_enabled:
            if not budget_available("scene_normal_correction"):
                skipped.append(
                    {
                        "operation": "scene_normal_correction",
                        "reason": ENHANCEMENT_RESOURCE_EXHAUSTED,
                    }
                )
            else:
                poll()
                started = time.perf_counter()
                try:
                    normal_outcome = ensure_normals(current)
                except Exception as exc:
                    if not config.fallback_to_original:
                        raise SceneReconstructionError(
                            MESH_GENERATION_FAILED,
                            f"Scene normal generation failed for geometry {name!r}.",
                        ) from exc
                    result.fallback_used = True
                    skipped.append(
                        {
                            "operation": "scene_normal_correction",
                            "reason": "NORMAL_GENERATION_FAILED",
                        }
                    )
                else:
                    result.timings["scene_normal_correction"] = round(
                        time.perf_counter() - started, 3
                    )
                    operations.append("scene_normal_correction")
                    record["normals"] = normal_outcome.as_metadata()
                    result.normal_export = True

        if config.simplification_enabled:
            if _is_textured(current):
                skipped.append(
                    {"operation": "scene_simplification", "reason": "TEXTURED_GEOMETRY_PRESERVED"}
                )
            elif not budget_available("scene_simplification"):
                skipped.append(
                    {"operation": "scene_simplification", "reason": ENHANCEMENT_RESOURCE_EXHAUSTED}
                )
            else:
                poll()
                started = time.perf_counter()
                outcome = simplify_mesh(
                    current,
                    target_faces=config.target_faces,
                    max_deviation_ratio=config.max_deviation,
                    simplifier=simplifier,
                )
                result.timings["scene_simplification"] = round(time.perf_counter() - started, 3)
                record["simplification"] = outcome.as_metadata()
                if outcome.applied and outcome.mesh is not None:
                    current = outcome.mesh
                    operations.append("scene_simplification")
                else:
                    skipped.append({"operation": "scene_simplification", "reason": outcome.reason})

        poll()
        scene.geometry[name] = current
        try:
            after = measure_mesh(current)
            record["after"] = after.as_metadata()
            _accumulate_totals(result.after, after)
        except Exception:
            record["after"] = None
        record["operations"] = operations
        record["skipped"] = skipped
        result.operations.extend(operations)
        result.skipped.extend(skipped)
        result.geometries.append(record)

    result.scene = scene
    result.peak_memory_mb = _peak_rss_mb()
    manifest = build_enhancement_manifest(
        scope="scene_reconstruction",
        settings=config.as_manifest(),
        source_fingerprint=source_fingerprint,
    )
    manifest["operations"] = sorted(set(result.operations))
    manifest["skipped"] = list(result.skipped)
    manifest["fallback_used"] = result.fallback_used
    result.manifest = manifest
    return result


__all__ = [
    "SceneEnhancementConfig",
    "SceneEnhancementResult",
    "enhance_scene",
    "scene_fingerprint",
]
