"""Validated scene-reconstruction configuration (07 Section 16).

The backend maps its ``SCENE_*`` settings onto :class:`SceneConfig` in one
place. The pipeline never reads environment variables itself, which keeps it
testable and prevents the API and worker defaults from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from image_quality import ImageQualityConfig, quality_config_from_settings

from .enhancement import SceneEnhancementConfig
from .feature_profiles import (
    BACKEND_COLMAP_SIFT,
    DEVICE_CHOICES,
    PAIR_STRATEGIES,
    PROFILE_SIFT_DEFAULT,
    FeatureProfile,
    FeatureProfileError,
    resolve_profile,
)
from .splat_config import (
    GLB_FORMAT,
    METHOD_MESH,
    METHOD_SPLATFACTO,
    REPRESENTATION_GAUSSIAN_SPLAT,
    REPRESENTATION_MESH,
    REPRESENTATIONS,
    SPLAT_FORMAT,
    SplatConfig,
)

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
# Optional neural representation (15 Section 7). These replace every
# OPENMVS_*/MESH_* stage for a splat task; they are never reported for mesh.
STAGE_SPLAT_DATASET_PREPARATION = "SPLAT_DATASET_PREPARATION"
STAGE_SPLAT_TRAINING = "SPLAT_TRAINING"
STAGE_SPLAT_EXPORT = "SPLAT_EXPORT"

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
    STAGE_SPLAT_DATASET_PREPARATION,
    STAGE_SPLAT_TRAINING,
    STAGE_SPLAT_EXPORT,
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
        STAGE_SPLAT_DATASET_PREPARATION: 1800,
        STAGE_SPLAT_TRAINING: 14400,
        STAGE_SPLAT_EXPORT: 1800,
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
    # Optional learned feature backend (12_advanced_feature_matching.md
    # Section 6). COLMAP SIFT remains the default; the neural backend is
    # explicitly opt-in and may fall back to SIFT.
    feature_backend: str = BACKEND_COLMAP_SIFT
    feature_profile: str = PROFILE_SIFT_DEFAULT
    feature_fallback_to_sift: bool = True
    feature_max_keypoints: int = 2048
    feature_image_max_size: int = 1600
    feature_pair_strategy: str = "EXHAUSTIVE"
    feature_sequential_overlap: int = 5
    feature_min_matches: int = 30
    feature_match_threshold: float = 0.1
    feature_device: str = "auto"
    feature_max_vram_mb: int = 9000
    feature_max_pairs: int = 20000
    # Resolved profile, kept out of equality/repr; set in __post_init__.
    _feature_profile: FeatureProfile | None = field(
        default=None, init=False, repr=False, compare=False
    )
    # Shared advisory image-quality analysis (11_image_quality_analysis.md).
    # Disabled analysis preserves the pre-increment pipeline behaviour.
    image_quality: ImageQualityConfig = field(default_factory=ImageQualityConfig)
    # Optional post-reconstruction mesh enhancement (14 Section 6). Off by
    # default; OpenMVS UVs/textures are never regenerated.
    enhancement: SceneEnhancementConfig = field(default_factory=SceneEnhancementConfig)
    # Optional neural representation (15 Section 4.2). ``MESH`` is the released
    # default; ``GAUSSIAN_SPLAT`` replaces the OpenMVS/GLB stages with Nerfstudio
    # Splatfacto training and a Gaussian PLY export.
    representation: str = REPRESENTATION_MESH
    splat: SplatConfig = field(default_factory=SplatConfig)

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
        representation = self.representation.strip().upper()
        if representation not in REPRESENTATIONS:
            raise ValueError(f"representation must be one of {REPRESENTATIONS}")
        object.__setattr__(self, "representation", representation)
        expected_format = GLB_FORMAT if representation == REPRESENTATION_MESH else SPLAT_FORMAT
        if self.output_format.upper() != expected_format:
            raise ValueError(
                f"output_format must be {expected_format} for representation {representation}"
            )
        object.__setattr__(self, "output_format", expected_format)
        self._validate_feature_settings()

    @property
    def is_gaussian_splat(self) -> bool:
        return self.representation == REPRESENTATION_GAUSSIAN_SPLAT

    @property
    def method(self) -> str:
        return METHOD_SPLATFACTO if self.is_gaussian_splat else METHOD_MESH

    def _validate_feature_settings(self) -> None:
        """Validate the feature backend/profile and its bounds (12 Section 6)."""
        try:
            backend = self.feature_backend.strip().upper()
            profile = self.feature_profile.strip().lower()
            resolved = resolve_profile(backend, profile)
        except FeatureProfileError as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "feature_backend", backend)
        object.__setattr__(self, "feature_profile", profile)
        object.__setattr__(self, "_feature_profile", resolved)
        if backend == BACKEND_COLMAP_SIFT and profile != PROFILE_SIFT_DEFAULT:
            raise ValueError("COLMAP_SIFT accepts only the sift_default profile")
        if not 128 <= self.feature_max_keypoints <= 20000:
            raise ValueError("feature_max_keypoints must be between 128 and 20000")
        if not 256 <= self.feature_image_max_size <= 8192:
            raise ValueError("feature_image_max_size must be between 256 and 8192")
        pair_strategy = self.feature_pair_strategy.strip().upper()
        if pair_strategy not in PAIR_STRATEGIES:
            raise ValueError(f"feature_pair_strategy must be one of {PAIR_STRATEGIES}")
        object.__setattr__(self, "feature_pair_strategy", pair_strategy)
        if not 1 <= self.feature_sequential_overlap <= 100:
            raise ValueError("feature_sequential_overlap must be between 1 and 100")
        if not 0 <= self.feature_min_matches <= 10000:
            raise ValueError("feature_min_matches must be between 0 and 10000")
        if not 0.0 <= self.feature_match_threshold <= 1.0:
            raise ValueError("feature_match_threshold must be in [0, 1]")
        device = self.feature_device.strip().lower()
        if device not in DEVICE_CHOICES:
            raise ValueError(f"feature_device must be one of {DEVICE_CHOICES}")
        object.__setattr__(self, "feature_device", device)
        if self.feature_max_vram_mb < 512:
            raise ValueError("feature_max_vram_mb must be at least 512")
        if self.feature_max_pairs < 1:
            raise ValueError("feature_max_pairs must be at least 1")

    @property
    def resolved_feature_profile(self) -> FeatureProfile:
        """Return the validated feature profile for this configuration."""
        return self._feature_profile

    def effective_max_keypoints(self) -> int:
        """Return the keypoint budget actually applied to the selected profile.

        The configured value is a ceiling; the fast profile keeps its own lower
        budget so selecting it cannot silently expand to the standard profile.
        """
        profile = self.resolved_feature_profile
        if not profile.is_neural:
            return 0
        if profile.max_keypoints <= 0:
            return self.feature_max_keypoints
        return min(profile.max_keypoints, self.feature_max_keypoints)

    def feature_parameters(self) -> dict[str, Any]:
        """Return every setting that affects neural feature/match outputs."""
        profile = self.resolved_feature_profile
        parameters = profile.parameters()
        parameters["max_keypoints"] = self.effective_max_keypoints()
        parameters.update(
            {
                "image_max_size": self.feature_image_max_size,
                "pair_strategy": self.feature_pair_strategy,
                "sequential_overlap": self.feature_sequential_overlap,
                "min_matches": self.feature_min_matches,
                "match_threshold": self.feature_match_threshold,
                "device": self.feature_device,
                "max_vram_mb": self.feature_max_vram_mb,
                "max_pairs": self.feature_max_pairs,
            }
        )
        return parameters

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
            "output_format": self.output_format,
            "representation": self.representation,
            "method": self.method,
            "splat": self.splat.as_manifest(),
            "features": {
                "backend": self.feature_backend,
                "profile": self.feature_profile,
                "fallback_to_sift": self.feature_fallback_to_sift,
                "max_keypoints": self.effective_max_keypoints(),
                "image_max_size": self.feature_image_max_size,
                "pair_strategy": self.feature_pair_strategy,
                "sequential_overlap": self.feature_sequential_overlap,
                "min_matches": self.feature_min_matches,
                "match_threshold": self.feature_match_threshold,
                "device": self.feature_device,
                "max_vram_mb": self.feature_max_vram_mb,
                "max_pairs": self.feature_max_pairs,
            },
            "image_quality": self.image_quality.as_metadata(),
            "enhancement": self.enhancement.as_manifest(),
        }


def build_config_from_settings(settings: Any, *, representation: str | None = None) -> SceneConfig:
    """Map validated backend settings onto the pipeline configuration.

    ``settings`` is duck-typed so this package stays independent of ``app``.
    The backend bounds every tool timeout; a stage additionally stays below the
    total task budget so a misconfiguration cannot outlive the Celery limit.

    ``representation`` overrides the deployment setting with the value persisted
    in the task, so a retry or recovery run executes the representation the API
    accepted even if the environment changed afterwards (15 Section 4.2).
    """
    stage_timeouts = _default_stage_timeouts()
    colmap_budget = int(getattr(settings, "scene_colmap_timeout_seconds", 3600))
    openmvs_budget = int(getattr(settings, "scene_openmvs_timeout_seconds", 5400))
    export_budget = int(getattr(settings, "scene_export_timeout_seconds", 1800))
    splat_budget = int(getattr(settings, "scene_splat_timeout_seconds", 7200))
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
    stage_timeouts[STAGE_SPLAT_TRAINING] = min(stage_timeouts[STAGE_SPLAT_TRAINING], splat_budget)

    chosen = (representation or getattr(settings, "scene_representation", "mesh") or "mesh").strip()
    chosen = chosen.upper()
    if chosen not in REPRESENTATIONS:
        raise ValueError(f"representation must be one of {REPRESENTATIONS}")
    splat = SplatConfig(
        enabled=bool(getattr(settings, "scene_splat_enabled", False)),
        model=getattr(settings, "scene_splat_model", "splatfacto"),
        max_iterations=int(getattr(settings, "scene_splat_max_iterations", 30000)),
        image_scale=float(getattr(settings, "scene_splat_image_scale", 1.0)),
        max_image_dimension=int(getattr(settings, "scene_splat_max_image_dimension", 1600)),
        checkpoint_interval=int(getattr(settings, "scene_splat_checkpoint_interval", 5000)),
        max_vram_mb=int(getattr(settings, "scene_splat_max_vram_mb", 9000)),
        device=getattr(settings, "scene_splat_device", "cuda"),
        max_artifact_bytes=int(
            getattr(settings, "scene_splat_max_artifact_bytes", 512 * 1024 * 1024)
        ),
        timeout_seconds=splat_budget,
        min_registered_images=int(getattr(settings, "scene_splat_min_registered_images", 8)),
        sh_degree=int(getattr(settings, "scene_splat_sh_degree", 3)),
        python_executable=Path(getattr(settings, "scene_splat_python", "/opt/venv/bin/python")),
        site_packages=Path(getattr(settings, "scene_splat_site_packages", "/opt/splat-site")),
    )

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
        representation=chosen,
        output_format=GLB_FORMAT if chosen == REPRESENTATION_MESH else SPLAT_FORMAT,
        splat=splat,
        feature_backend=getattr(settings, "scene_feature_backend", BACKEND_COLMAP_SIFT),
        feature_profile=getattr(settings, "scene_feature_profile", PROFILE_SIFT_DEFAULT),
        feature_fallback_to_sift=bool(getattr(settings, "scene_feature_fallback_to_sift", True)),
        feature_max_keypoints=int(getattr(settings, "scene_feature_max_keypoints", 2048)),
        feature_image_max_size=int(getattr(settings, "scene_feature_image_max_size", 1600)),
        feature_pair_strategy=getattr(settings, "scene_feature_pair_strategy", "EXHAUSTIVE"),
        feature_sequential_overlap=int(getattr(settings, "scene_feature_sequential_overlap", 5)),
        feature_min_matches=int(getattr(settings, "scene_feature_min_matches", 30)),
        feature_match_threshold=float(getattr(settings, "scene_feature_match_threshold", 0.1)),
        feature_device=getattr(settings, "scene_feature_device", "auto"),
        feature_max_vram_mb=int(getattr(settings, "scene_feature_max_vram_mb", 9000)),
        feature_max_pairs=int(getattr(settings, "scene_feature_max_pairs", 20000)),
        image_quality=quality_config_from_settings(settings),
        enhancement=SceneEnhancementConfig(
            postprocess_enabled=getattr(settings, "scene_mesh_postprocess_enabled", False),
            cleanup_enabled=getattr(settings, "scene_mesh_cleanup_enabled", True),
            normals_enabled=getattr(settings, "scene_normals_enabled", True),
            simplification_enabled=getattr(settings, "scene_mesh_simplification_enabled", False),
            target_faces=getattr(settings, "scene_mesh_target_faces", 0),
            max_deviation=getattr(settings, "scene_mesh_max_deviation", 0.01),
            generate_uv=getattr(settings, "scene_generate_uv", False),
            ai_texture_enabled=getattr(settings, "scene_ai_texture_enabled", False),
            fallback_to_original=getattr(settings, "enhancement_fallback_to_original", True),
            max_memory_mb=getattr(settings, "mesh_enhancement_max_memory_mb", 8192),
            device=getattr(settings, "texture_enhancement_device", "cpu"),
        ),
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
    "STAGE_SPLAT_DATASET_PREPARATION",
    "STAGE_SPLAT_EXPORT",
    "STAGE_SPLAT_TRAINING",
    "STAGE_TEXTURING",
    "SceneConfig",
    "build_config_from_settings",
]
