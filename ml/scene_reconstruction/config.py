"""Validated scene-reconstruction configuration (07 Section 16).

The backend maps its ``SCENE_*`` settings onto :class:`SceneConfig` in one
place. The pipeline never reads environment variables itself, which keeps it
testable and prevents the API and worker defaults from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Persistent stage identifiers (07 Section 13.3). They are the only values a
# pipeline may write to GenerationTask.stage; COMPLETED/FAILED/CANCELLED are
# task statuses and must never appear here.
STAGE_IMAGE_PREPARATION = "IMAGE_PREPARATION"
STAGE_FEATURE_EXTRACTION = "FEATURE_EXTRACTION"
STAGE_FEATURE_MATCHING = "FEATURE_MATCHING"
STAGE_SPARSE_RECONSTRUCTION = "SPARSE_RECONSTRUCTION"
STAGE_RECONSTRUCTION_VALIDATION = "RECONSTRUCTION_VALIDATION"
STAGE_IMAGE_UNDISTORTION = "IMAGE_UNDISTORTION"
STAGE_OPENMVS_IMPORT = "OPENMVS_IMPORT"
STAGE_DENSE_RECONSTRUCTION = "DENSE_RECONSTRUCTION"
STAGE_MESH_GENERATION = "MESH_GENERATION"
STAGE_MESH_REFINEMENT = "MESH_REFINEMENT"
STAGE_TEXTURING = "TEXTURING"
STAGE_ASSET_EXPORT = "ASSET_EXPORT"
STAGE_RESULT_VALIDATION = "RESULT_VALIDATION"

STAGES: tuple[str, ...] = (
    STAGE_IMAGE_PREPARATION,
    STAGE_FEATURE_EXTRACTION,
    STAGE_FEATURE_MATCHING,
    STAGE_SPARSE_RECONSTRUCTION,
    STAGE_RECONSTRUCTION_VALIDATION,
    STAGE_IMAGE_UNDISTORTION,
    STAGE_OPENMVS_IMPORT,
    STAGE_DENSE_RECONSTRUCTION,
    STAGE_MESH_GENERATION,
    STAGE_MESH_REFINEMENT,
    STAGE_TEXTURING,
    STAGE_ASSET_EXPORT,
    STAGE_RESULT_VALIDATION,
)

MATCHING_STRATEGIES = ("EXHAUSTIVE", "SEQUENTIAL")


def _default_stage_timeouts() -> dict[str, int]:
    """Per-stage process timeouts in seconds (07 Sections 6.6 and 15)."""
    return {
        STAGE_IMAGE_PREPARATION: 600,
        STAGE_FEATURE_EXTRACTION: 3600,
        STAGE_FEATURE_MATCHING: 3600,
        STAGE_SPARSE_RECONSTRUCTION: 3600,
        STAGE_RECONSTRUCTION_VALIDATION: 600,
        STAGE_IMAGE_UNDISTORTION: 3600,
        STAGE_OPENMVS_IMPORT: 1800,
        STAGE_DENSE_RECONSTRUCTION: 5400,
        STAGE_MESH_GENERATION: 3600,
        STAGE_MESH_REFINEMENT: 3600,
        STAGE_TEXTURING: 3600,
        STAGE_ASSET_EXPORT: 1800,
        STAGE_RESULT_VALIDATION: 600,
    }


@dataclass(frozen=True, slots=True)
class SceneConfig:
    """Everything the pipeline needs to run one reconstruction."""

    colmap_executable: Path = Path("/usr/local/bin/colmap")
    openmvs_bin_dir: Path = Path("/usr/local/bin/OpenMVS")
    matching_strategy: str = "EXHAUSTIVE"
    colmap_use_gpu: bool = True
    colmap_max_features: int = 8192
    colmap_camera_model: str = "SIMPLE_RADIAL"
    max_image_size: int = 2000
    max_threads: int = 4
    openmvs_use_cuda: bool = False
    enable_mesh_refinement: bool = True
    enable_texture_generation: bool = True
    min_registered_images: int = 3
    min_registration_ratio: float = 0.5
    min_sparse_points: int = 100
    min_dense_points: int = 100
    max_task_seconds: int = 14400
    # Per-stage values from _default_stage_timeouts(), narrowed by the backend
    # tool budgets in build_config_from_settings().
    stage_timeouts: dict[str, int] = field(default_factory=_default_stage_timeouts)
    min_free_disk_bytes: int = 2 * 1024 * 1024 * 1024
    output_format: str = "GLB"
    work_root: Path = Path("/data/work/scene")

    def __post_init__(self) -> None:
        strategy = self.matching_strategy.strip().upper()
        if strategy not in MATCHING_STRATEGIES:
            raise ValueError(f"matching_strategy must be one of {MATCHING_STRATEGIES}")
        object.__setattr__(self, "matching_strategy", strategy)
        if self.max_threads < 1:
            raise ValueError("max_threads must be at least 1")
        if self.max_image_size < 1:
            raise ValueError("max_image_size must be at least 1")
        if self.colmap_max_features < 1:
            raise ValueError("colmap_max_features must be at least 1")
        if not 0 < self.min_registration_ratio <= 1:
            raise ValueError("min_registration_ratio must be in (0, 1]")
        if self.min_registered_images < 1:
            raise ValueError("min_registered_images must be at least 1")
        if self.min_sparse_points < 0 or self.min_dense_points < 0:
            raise ValueError("point thresholds must not be negative")
        if self.output_format.upper() != "GLB":
            raise ValueError("output_format must be 'glb' for the MVP")

    def tool(self, name: str) -> Path:
        """Return the absolute path of a COLMAP or OpenMVS executable."""
        return self.colmap_executable if name == "colmap" else self.openmvs_bin_dir / name

    def timeout_for(self, stage: str) -> int:
        """Return the process timeout for a stage, with a safe default."""
        return int(self.stage_timeouts.get(stage, 3600))

    def as_manifest(self) -> dict[str, Any]:
        """Return the JSON-safe configuration recorded with each task."""
        return {
            "matching_strategy": self.matching_strategy,
            "colmap_use_gpu": self.colmap_use_gpu,
            "colmap_max_features": self.colmap_max_features,
            "colmap_camera_model": self.colmap_camera_model,
            "max_image_size": self.max_image_size,
            "max_threads": self.max_threads,
            "openmvs_use_cuda": self.openmvs_use_cuda,
            "enable_mesh_refinement": self.enable_mesh_refinement,
            "enable_texture_generation": self.enable_texture_generation,
            "min_registered_images": self.min_registered_images,
            "min_registration_ratio": self.min_registration_ratio,
            "min_sparse_points": self.min_sparse_points,
            "min_dense_points": self.min_dense_points,
            "output_format": "GLB",
        }


def build_config_from_settings(settings: Any) -> SceneConfig:
    """Map validated backend settings onto the pipeline configuration.

    ``settings`` is duck-typed so this package stays independent of ``app``.
    The backend bounds every tool timeout; a stage additionally stays below the
    total task budget so a misconfiguration cannot outlive the Celery limit.
    """
    stage_timeouts = _default_stage_timeouts()
    colmap_budget = int(getattr(settings, "scene_colmap_timeout_seconds", 3600))
    openmvs_budget = int(getattr(settings, "scene_openmvs_timeout_seconds", 5400))
    export_budget = int(getattr(settings, "scene_export_timeout_seconds", 1800))
    for stage in (
        STAGE_FEATURE_EXTRACTION,
        STAGE_FEATURE_MATCHING,
        STAGE_SPARSE_RECONSTRUCTION,
        STAGE_IMAGE_UNDISTORTION,
    ):
        stage_timeouts[stage] = min(stage_timeouts[stage], colmap_budget)
    for stage in (
        STAGE_OPENMVS_IMPORT,
        STAGE_DENSE_RECONSTRUCTION,
        STAGE_MESH_GENERATION,
        STAGE_MESH_REFINEMENT,
        STAGE_TEXTURING,
    ):
        stage_timeouts[stage] = min(stage_timeouts[stage], openmvs_budget)
    stage_timeouts[STAGE_ASSET_EXPORT] = min(stage_timeouts[STAGE_ASSET_EXPORT], export_budget)

    return SceneConfig(
        colmap_executable=Path(settings.scene_colmap_executable),
        openmvs_bin_dir=Path(settings.scene_openmvs_bin_dir),
        matching_strategy=settings.scene_matching_strategy,
        colmap_use_gpu=settings.scene_colmap_use_gpu,
        colmap_max_features=settings.scene_colmap_max_features,
        colmap_camera_model=settings.scene_colmap_camera_model,
        max_image_size=settings.scene_max_image_size,
        max_threads=settings.scene_max_threads,
        openmvs_use_cuda=settings.scene_openmvs_use_cuda,
        enable_mesh_refinement=settings.scene_enable_mesh_refinement,
        enable_texture_generation=settings.scene_enable_texture_generation,
        min_registered_images=settings.scene_min_registered_images,
        min_registration_ratio=settings.scene_min_registration_ratio,
        min_sparse_points=settings.scene_min_sparse_points,
        min_dense_points=settings.scene_min_dense_points,
        max_task_seconds=settings.scene_max_task_seconds,
        stage_timeouts=stage_timeouts,
        work_root=Path(settings.scene_work_dir),
    )


__all__ = [
    "MATCHING_STRATEGIES",
    "STAGES",
    "STAGE_ASSET_EXPORT",
    "STAGE_DENSE_RECONSTRUCTION",
    "STAGE_FEATURE_EXTRACTION",
    "STAGE_FEATURE_MATCHING",
    "STAGE_IMAGE_PREPARATION",
    "STAGE_IMAGE_UNDISTORTION",
    "STAGE_MESH_GENERATION",
    "STAGE_MESH_REFINEMENT",
    "STAGE_OPENMVS_IMPORT",
    "STAGE_RECONSTRUCTION_VALIDATION",
    "STAGE_RESULT_VALIDATION",
    "STAGE_SPARSE_RECONSTRUCTION",
    "STAGE_TEXTURING",
    "SceneConfig",
    "build_config_from_settings",
]
