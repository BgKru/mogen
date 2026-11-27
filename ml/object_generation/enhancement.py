"""Object mesh/texture enhancement orchestration (14 Sections 3.1 and 4.1).

Enhancement sits between the selected generator's normalized output and the
existing GLB export. Every optional operation is independently configurable;
with the default policy only conservative cleanup and normal validation run.
A failed optional operation preserves the last validated mesh and is recorded
when ``fallback_to_original`` is true; source-geometry validation never falls
back.
"""

from __future__ import annotations

import resource
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import trimesh
from mesh_enhancement import (
    CleanupError,
    build_enhancement_manifest,
    cleanup_mesh,
    ensure_normals,
    measure_mesh,
    mesh_fingerprint,
    simplify_mesh,
)

from .exceptions import (
    AI_TEXTURE_UNAVAILABLE,
    ENHANCEMENT_FAILED,
    ENHANCEMENT_RESOURCE_EXHAUSTED,
    EnhancementError,
)
from .mesh_processor import validate_mesh
from .texture_baking import (
    bake_vertex_colors,
    generate_uvs,
    has_texture_image,
    has_usable_uvs,
    normalize_pbr_material,
)
from .texture_generation import (
    TextureGenerationRequest,
    create_texture_backend,
    validate_generated_texture,
)

_POLL = Callable[[], None]


@dataclass(frozen=True, slots=True)
class EnhancementConfig:
    """Validated enhancement policy for one object-generation task."""

    cleanup_enabled: bool = True
    merge_tolerance: float = 1e-6
    remove_small_components: bool = False
    small_component_faces: int = 32
    normals_enabled: bool = True
    simplification_enabled: bool = False
    target_faces: int = 0
    max_deviation: float = 0.01
    smoothing_iterations: int = 0
    generate_uv: bool = False
    uv_resolution: int = 1024
    uv_padding: int = 2
    bake_texture: bool = False
    texture_resolution: int = 1024
    texture_padding: int = 4
    ai_texture_enabled: bool = False
    ai_texture_backend: str = "disabled"
    fallback_to_original: bool = True
    max_memory_mb: int = 8192
    device: str = "cpu"

    def __post_init__(self) -> None:
        if not 0.0 <= self.merge_tolerance <= 0.1:
            message = "mesh_merge_tolerance must be between 0 and 0.1"
            raise ValueError(message)
        if self.small_component_faces < 1:
            message = "mesh_small_component_faces must be at least 1"
            raise ValueError(message)
        if self.target_faces < 0:
            message = "mesh_target_faces must not be negative"
            raise ValueError(message)
        if self.simplification_enabled and self.target_faces <= 0:
            message = "mesh_target_faces must be positive when simplification is enabled"
            raise ValueError(message)
        if not 0.0 < self.max_deviation <= 0.5:
            message = "mesh_max_deviation must be in (0, 0.5]"
            raise ValueError(message)
        if self.smoothing_iterations != 0:
            message = "mesh smoothing is not implemented in this delivery; keep 0"
            raise ValueError(message)
        if not 64 <= self.uv_resolution <= 4096:
            message = "uv_resolution must be between 64 and 4096"
            raise ValueError(message)
        if not 64 <= self.texture_resolution <= 4096:
            message = "texture_resolution must be between 64 and 4096"
            raise ValueError(message)
        if not 0 <= self.uv_padding <= 64 or not 0 <= self.texture_padding <= 64:
            message = "UV/texture padding must be between 0 and 64"
            raise ValueError(message)
        if self.device.strip().lower() != "cpu":
            message = "texture_enhancement_device must be 'cpu' in this delivery"
            raise ValueError(message)
        if self.max_memory_mb < 256:
            message = "mesh_enhancement_max_memory_mb must be at least 256"
            raise ValueError(message)
        backend = (self.ai_texture_backend or "disabled").strip().lower()
        if backend != "disabled":
            message = "no compliant AI texture backend is installed; use 'disabled'"
            raise ValueError(message)
        if self.ai_texture_enabled:
            message = (
                "AI texture generation is unavailable: no model has passed the "
                "licence, compatibility, cache and 12 GB feasibility review"
            )
            raise ValueError(message)

    def as_manifest(self) -> dict[str, Any]:
        return {
            "cleanup_enabled": self.cleanup_enabled,
            "merge_tolerance": self.merge_tolerance,
            "remove_small_components": self.remove_small_components,
            "small_component_faces": self.small_component_faces,
            "normals_enabled": self.normals_enabled,
            "simplification_enabled": self.simplification_enabled,
            "target_faces": self.target_faces,
            "max_deviation": self.max_deviation,
            "smoothing_iterations": self.smoothing_iterations,
            "generate_uv": self.generate_uv,
            "uv_resolution": self.uv_resolution,
            "uv_padding": self.uv_padding,
            "bake_texture": self.bake_texture,
            "texture_resolution": self.texture_resolution,
            "texture_padding": self.texture_padding,
            "ai_texture": {"enabled": self.ai_texture_enabled, "backend": "disabled"},
            "fallback_to_original": self.fallback_to_original,
            "max_memory_mb": self.max_memory_mb,
            "device": self.device,
        }


@dataclass(slots=True)
class EnhancementResult:
    """The enhanced mesh plus compact, path-free diagnostics."""

    mesh: trimesh.Trimesh
    operations: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    before: Any = None
    after: Any = None
    cleanup: dict[str, Any] | None = None
    normals: dict[str, Any] | None = None
    simplification: dict[str, Any] | None = None
    uv: dict[str, Any] | None = None
    baking: dict[str, Any] | None = None
    pbr: dict[str, Any] | None = None
    fallback_used: bool = False
    normal_export: bool = False
    appearance_mode: str = "none"
    timings: dict[str, float] = field(default_factory=dict)
    peak_memory_mb: float | None = None
    manifest: dict[str, Any] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "scope": "object",
            "operations": list(self.operations),
            "skipped": list(self.skipped),
            "warnings": sorted(set(self.warnings)),
            "fallback": {
                "used": self.fallback_used,
                "to": "original" if self.fallback_used else None,
            },
            "appearance_mode": self.appearance_mode,
            "normal_export": self.normal_export,
            "before": self.before.as_metadata() if self.before is not None else None,
            "after": self.after.as_metadata() if self.after is not None else None,
            "cleanup": self.cleanup,
            "normals": self.normals,
            "simplification": self.simplification,
            "uv": self.uv,
            "baking": self.baking,
            "pbr": self.pbr,
            "timings": dict(self.timings),
            "peak_memory_mb": self.peak_memory_mb,
            "manifest": dict(self.manifest),
        }

    def disabled_metadata(self, reason: str = "disabled") -> dict[str, Any]:
        """Return the metadata used when enhancement is configured off."""
        return {
            "enabled": False,
            "scope": "object",
            "operations": [],
            "skipped": [{"operation": "enhancement", "reason": reason}],
            "warnings": [],
            "fallback": {"used": False, "to": None},
            "appearance_mode": None,
            "normal_export": False,
            "before": None,
            "after": None,
            "timings": {},
            "peak_memory_mb": self.peak_memory_mb,
        }


def _peak_rss_mb() -> float | None:
    """Return the process peak RSS; the per-task peak is the process peak."""
    try:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def _is_textured(mesh: trimesh.Trimesh) -> bool:
    return has_texture_image(mesh)


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "error_code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, (CleanupError, np.linalg.LinAlgError)):
        return getattr(exc, "error_code", ENHANCEMENT_FAILED)
    return ENHANCEMENT_FAILED


def enhance_object(
    mesh: trimesh.Trimesh,
    config: EnhancementConfig,
    *,
    on_poll: _POLL | None = None,
    simplifier: Callable[[trimesh.Trimesh, int], trimesh.Trimesh] | None = None,
) -> EnhancementResult:
    """Run the configured enhancement sequence on a normalized generator mesh.

    The incoming mesh is validated with the existing source-geometry rules first.
    The returned mesh is the only asset the exporter may consume.
    """
    poll = on_poll or (lambda: None)
    # Hard source validation: never eligible for fallback (14 Section 9).
    validate_mesh(mesh)
    source_fingerprint = mesh_fingerprint(mesh)
    before = measure_mesh(mesh)
    current = mesh
    result = EnhancementResult(mesh=mesh, before=before)
    result.peak_memory_mb = _peak_rss_mb()

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

    def attempt(operation: str, function: Callable[[], Any]) -> tuple[bool, Any]:
        if not budget_available(operation):
            return False, None
        poll()
        started = time.perf_counter()
        try:
            value = function()
        except Exception as exc:
            reason = _error_code(exc)
            if not config.fallback_to_original:
                message = f"The optional {operation} enhancement step failed."
                raise EnhancementError(reason, message) from exc
            result.fallback_used = True
            result.skipped.append({"operation": operation, "reason": reason})
            return False, None
        result.timings[operation] = round(time.perf_counter() - started, 3)
        result.operations.append(operation)
        return True, value

    if config.cleanup_enabled:
        ok, outcome = attempt(
            "mesh_cleanup",
            lambda: cleanup_mesh(
                current,
                merge_tolerance_ratio=config.merge_tolerance,
                remove_small_components=config.remove_small_components,
                small_component_faces=config.small_component_faces,
            ),
        )
        if ok:
            current = outcome.mesh
            result.cleanup = outcome.as_metadata()
            result.warnings.extend(outcome.skipped)

    if config.normals_enabled:

        def _normals() -> Any:
            outcome = ensure_normals(current)
            return current, outcome

        ok, value = attempt("normal_correction", _normals)
        if ok:
            current, normal_outcome = value
            result.normals = normal_outcome.as_metadata()
            result.normal_export = True
            result.warnings.extend(normal_outcome.skipped)
            result.warnings.extend(normal_outcome.warnings)

    if config.simplification_enabled:
        ok, outcome = attempt(
            "simplification",
            lambda: simplify_mesh(
                current,
                target_faces=config.target_faces,
                max_deviation_ratio=config.max_deviation,
                simplifier=simplifier,
            ),
        )
        if ok:
            result.simplification = outcome.as_metadata()
            if outcome.applied and outcome.mesh is not None:
                current = outcome.mesh
            else:
                result.warnings.append(outcome.reason)

    source_textured = _is_textured(current)
    if config.bake_texture and source_textured:
        result.skipped.append({"operation": "texture_baking", "reason": "source_texture_preserved"})
    needs_uv = config.generate_uv or (config.bake_texture and not source_textured)
    if needs_uv and not has_usable_uvs(current):

        def _unwrap() -> Any:
            outcome = generate_uvs(current, padding=config.uv_padding)
            return outcome

        ok, uv_outcome = attempt("uv_generation", _unwrap)
        if ok:
            current = uv_outcome.mesh
            result.uv = uv_outcome.as_metadata()
            result.warnings.extend(uv_outcome.warnings)
    elif needs_uv and has_usable_uvs(current):
        result.skipped.append({"operation": "uv_generation", "reason": "valid_uvs_preserved"})

    if config.bake_texture and not source_textured:

        def _bake() -> Any:
            return bake_vertex_colors(
                current,
                resolution=config.texture_resolution,
                padding=config.texture_padding,
            )

        ok, bake_outcome = attempt("texture_baking", _bake)
        if ok:
            current = bake_outcome.mesh
            result.baking = bake_outcome.as_metadata()
            result.warnings.extend(bake_outcome.warnings)

    textured = _is_textured(current)

    if config.ai_texture_enabled:  # pragma: no cover - config rejects enabling today
        try:
            backend = create_texture_backend(config.ai_texture_backend)
        except Exception as exc:
            result.skipped.append(
                {
                    "operation": "ai_texture",
                    "reason": getattr(exc, "error_code", AI_TEXTURE_UNAVAILABLE),
                }
            )
        else:
            if not backend.available():
                result.skipped.append({"operation": "ai_texture", "reason": AI_TEXTURE_UNAVAILABLE})
            else:
                ok, generated = attempt(
                    "ai_texture",
                    lambda: validate_generated_texture(
                        backend.generate(
                            current,
                            TextureGenerationRequest(
                                resolution=config.texture_resolution,
                                texture_id=source_fingerprint[:16],
                            ),
                            on_poll=poll,
                        ),
                        resolution=config.texture_resolution,
                        uv_count=len(current.visual.uv) if has_usable_uvs(current) else 0,
                    ),
                )
                if ok:
                    material = trimesh.visual.material.PBRMaterial(
                        baseColorTexture=generated.image,
                        baseColorFactor=[1.0, 1.0, 1.0, 1.0],
                        metallicFactor=0.0,
                        roughnessFactor=0.9,
                    )
                    current.visual = trimesh.visual.TextureVisuals(
                        uv=np.asarray(current.visual.uv, dtype=np.float64), material=material
                    )
                    textured = True

    if textured:
        ok, pbr = attempt(
            "pbr_material",
            lambda: normalize_pbr_material(current),
        )
        if ok:
            result.pbr = pbr

    poll()
    result.mesh = current
    result.after = measure_mesh(current)
    if _is_textured(current):
        appearance = "texture"
    elif result.after.has_vertex_colors:
        appearance = "vertex_colors"
    else:
        appearance = "none"
    result.appearance_mode = appearance
    manifest = build_enhancement_manifest(
        scope="object_generation",
        settings=config.as_manifest(),
        source_fingerprint=source_fingerprint,
    )
    manifest["operations"] = list(result.operations)
    manifest["skipped"] = list(result.skipped)
    manifest["fallback_used"] = result.fallback_used
    result.manifest = manifest
    result.peak_memory_mb = _peak_rss_mb()
    return result


def disabled_enhancement_config(config: EnhancementConfig) -> EnhancementConfig:
    """Return a configuration with every optional operation disabled."""
    return replace(
        config,
        cleanup_enabled=False,
        normals_enabled=False,
        simplification_enabled=False,
        generate_uv=False,
        bake_texture=False,
    )


__all__ = [
    "EnhancementConfig",
    "EnhancementResult",
    "disabled_enhancement_config",
    "enhance_object",
]
