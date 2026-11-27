"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
SUPPORTED_DRIVERS = ("postgresql+psycopg://", "postgresql://")
# Hunyuan3D-2.1 published licence exclusion list (EU member states plus the
# United Kingdom and South Korea). This is a licence policy, not a geographic
# inference: the operator declares the deployment territory explicitly.
HUNYUAN3D_EXCLUDED_TERRITORIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
        "GB",
        "KR",
    }
)
# Development-only default. Production startup rejects it (Section 17.2).
DEFAULT_DEV_CSRF_SECRET = "dev-only-csrf-secret-change-before-production"


def redact_url(url: str) -> str:
    """Return a URL with any password replaced, safe for logs."""
    parts = urlsplit(url)
    if not parts.password:
        return url
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables, optionally from a local
    ``.env`` file. Unknown variables are ignored so that a single environment
    file can be shared by several services.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "3D Generation Service"
    app_env: str = "development"
    version: str = "1.0.0"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"
    enable_api_docs: bool = True

    database_url: str = Field(
        default="postgresql+psycopg://app:change_me@db:5432/app",
        repr=False,
    )
    redis_url: str = Field(default="redis://redis:6379/0", repr=False)

    # Celery broker. Database 1 is reserved for the broker, database 0 serves
    # direct Redis access (08_infrastructure.md Section 9.2).
    celery_broker_url: str = Field(default="redis://redis:6379/1", repr=False)
    celery_task_ignore_result: bool = True

    # Cleanup worker (08 Section 3.7, 05 Section 12.3). The same worker owns the
    # hourly scene-workspace retention sweep and the session-cleanup job.
    cleanup_batch_size: int = 20
    cleanup_poll_interval_seconds: int = 15
    cleanup_max_attempts: int = 3
    cleanup_task_time_limit_seconds: int = 600
    session_cleanup_interval_seconds: int = 3600

    # Transactional outbox dispatcher (05 Section 13.6, 08 Section 3.9).
    outbox_batch_size: int = 50
    outbox_poll_interval_seconds: int = 2
    outbox_retry_base_seconds: int = 2
    outbox_retry_max_seconds: int = 300
    outbox_max_attempts: int = 10
    outbox_lock_timeout_seconds: int = 60

    # Worker leases and stale-task recovery (08 Section 9.2, 05 Section 9.11).
    task_lease_seconds: int = 300
    task_heartbeat_seconds: int = 30
    task_stale_threshold_seconds: int = 900
    dispatch_stall_timeout_seconds: int = 900
    task_recovery_max_attempts: int = 3
    recovery_batch_size: int = 50
    recovery_poll_interval_seconds: int = 30

    # Per-pipeline Celery time limits (04 Section 18.5).
    object_task_time_limit_seconds: int = 3600
    scene_task_time_limit_seconds: int = 7200

    # Object generation / TripoSR (06_object_generation.md Section 16). The
    # API image never imports torch; these values are consumed by the object
    # worker, and the model cache is a persistent Compose volume.
    object_model_id: str = "stabilityai/TripoSR"
    object_model_revision: str = "5b521936b01fbe1890f6f9baed0254ab6351c04a"
    object_model_dir: Path = Path("/models/triposr")
    object_model_sha256: str = "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee"
    # Task-specific intermediate directories (06 Section 7.7). Ephemeral, never
    # served to clients and removed after the asset is stored.
    object_work_dir: Path = Path("/tmp/mogen-object-generation")
    object_dino_model_id: str = "facebook/dino-vitb16"
    object_dino_revision: str = "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2"
    object_device: str = "cuda:0"
    object_allow_cpu_fallback: bool = False
    object_chunk_size: int = 8192
    object_mc_resolution: int = 256
    object_remove_background: bool = True
    object_foreground_ratio: float = 0.85
    object_output_format: str = "glb"
    object_bake_texture: bool = False
    object_texture_resolution: int = 1024
    object_max_task_seconds: int = 600
    object_worker_concurrency: int = 1
    object_rembg_model: str = "u2net"
    object_input_size: int = 512
    object_generation_enabled: bool = True

    # Optional mesh/texture enhancement (docs/additions/14_mesh_texture_enhancement.md
    # Section 6). Conservative cleanup and normal validation are on; every
    # destructive or generative operation is opt-in.
    object_mesh_cleanup_enabled: bool = True
    object_mesh_merge_tolerance: float = 1e-6
    object_mesh_remove_small_components: bool = False
    object_mesh_small_component_faces: int = 32
    object_mesh_normals_enabled: bool = True
    object_mesh_simplification_enabled: bool = False
    object_mesh_target_faces: int = 0
    object_mesh_max_deviation: float = 0.01
    object_mesh_smoothing_iterations: int = 0
    object_generate_uv: bool = False
    object_uv_resolution: int = 1024
    object_uv_padding: int = 2
    object_texture_padding: int = 4
    object_ai_texture_enabled: bool = False
    object_ai_texture_backend: str = "disabled"

    # Generator selection (13_advanced_object_generation.md Section 6). TripoSR
    # remains the default; SF3D is opt-in with its own cache and manifest, and
    # Hunyuan3D is gated and unavailable in this build. These are deployment
    # settings, never per-request fields.
    object_generator: str = "triposr"
    object_generator_fallback: bool = False
    object_sf3d_enabled: bool = False
    object_sf3d_model_id: str = "stabilityai/stable-fast-3d"
    object_sf3d_model_revision: str = ""
    object_sf3d_model_dir: Path = Path("/models/sf3d")
    object_sf3d_manifest_path: Path = Path("/models/sf3d/model-manifest.json")
    object_sf3d_texture_resolution: int = 1024
    object_sf3d_remesh: str = "none"
    object_sf3d_target_vertex_count: int = -1
    object_hunyuan3d_enabled: bool = False
    object_hunyuan3d_license_acknowledged: bool = False
    object_hunyuan3d_territory: str = ""
    object_hunyuan3d_model_revision: str = ""
    object_hunyuan3d_model_dir: Path = Path("/models/hunyuan3d")
    object_hunyuan3d_mode: str = "shape"
    object_hunyuan3d_low_vram: bool = False
    object_hunyuan3d_texture_enabled: bool = False

    # Scene reconstruction / COLMAP + OpenMVS (07_scene_reconstruction.md
    # Section 16). The API image never imports these tools; the values are
    # consumed by the scene worker and mirrored by ml/scene_reconstruction.
    scene_reconstruction_enabled: bool = True
    scene_colmap_executable: Path = Path("/usr/local/bin/colmap")
    scene_openmvs_bin_dir: Path = Path("/usr/local/bin/OpenMVS")
    # Task-specific intermediate directories (07 Section 4.7). They live on the
    # shared data volume so a restarted worker can reuse validated checkpoints;
    # they are never served to clients and are removed after the asset is stored.
    scene_work_dir: Path = Path("/data/work/scene")
    scene_matching_strategy: str = "EXHAUSTIVE"
    scene_colmap_use_gpu: bool = True
    scene_colmap_max_features: int = 8192
    scene_colmap_camera_model: str = "SIMPLE_RADIAL"
    scene_max_image_size: int = 2000
    scene_max_threads: int = 4
    scene_openmvs_use_cuda: bool = False
    scene_enable_mesh_refinement: bool = True
    scene_enable_texture_generation: bool = True
    scene_min_registered_images: int = 3
    scene_min_registration_ratio: float = 0.5
    scene_min_sparse_points: int = 100
    scene_min_dense_points: int = 100
    scene_max_task_seconds: int = 14400
    scene_colmap_timeout_seconds: int = 3600
    scene_openmvs_timeout_seconds: int = 5400
    scene_export_timeout_seconds: int = 1800
    scene_output_format: str = "GLB"
    # Optional learned feature matching (docs/additions/12_advanced_feature_matching.md).
    # COLMAP SIFT remains the default; the neural backend is opt-in and may fall
    # back to SIFT before the mapper runs.
    scene_feature_backend: str = "COLMAP_SIFT"
    scene_feature_profile: str = "sift_default"
    scene_feature_fallback_to_sift: bool = True
    scene_feature_max_keypoints: int = 2048
    scene_feature_image_max_size: int = 1600
    scene_feature_pair_strategy: str = "EXHAUSTIVE"
    scene_feature_sequential_overlap: int = 5
    scene_feature_min_matches: int = 30
    scene_feature_match_threshold: float = 0.1
    scene_feature_device: str = "auto"
    scene_feature_max_vram_mb: int = 9000
    scene_feature_max_pairs: int = 20000
    # Optional post-reconstruction scene enhancement (14 Section 6). Off by
    # default; OpenMVS UVs/textures are preserved and never regenerated.
    scene_mesh_postprocess_enabled: bool = False
    scene_mesh_cleanup_enabled: bool = True
    scene_normals_enabled: bool = True
    scene_mesh_simplification_enabled: bool = False
    scene_mesh_target_faces: int = 0
    scene_mesh_max_deviation: float = 0.01
    scene_generate_uv: bool = False
    scene_ai_texture_enabled: bool = False
    # Shared enhancement budgets/fallback. CPU is the only verified device for
    # deterministic atlas/material operations; AI texture generation is off.
    enhancement_fallback_to_original: bool = True
    mesh_enhancement_max_memory_mb: int = 8192
    texture_enhancement_device: str = "cpu"
    # Scene workspace retention (07 Section 15.7). A failed reconstruction keeps
    # its workspace for diagnostics; the cleanup sweep prunes terminal
    # workspaces older than this many hours. 0 disables pruning.
    scene_workspace_retention_hours: int = 168
    scene_workspace_sweep_interval_seconds: int = 3600
    # Optional neural scene representation (docs/additions/15_neural_scene_reconstruction.md
    # Section 6). COLMAP + OpenMVS remains the default; `gaussian_splat` selects
    # Nerfstudio Splatfacto on the same COLMAP cameras and is only
    # reachable when the dedicated neural worker image is deployed. The selected
    # representation is persisted in the task, so these values never re-target a
    # queued task.
    scene_representation: str = "mesh"
    scene_splat_enabled: bool = False
    scene_splat_worker_queue: str = "scene_gaussian_splat"
    scene_splat_model: str = "splatfacto"
    scene_splat_max_iterations: int = 30000
    scene_splat_image_scale: float = 1.0
    scene_splat_max_image_dimension: int = 1600
    scene_splat_checkpoint_interval: int = 5000
    scene_splat_max_vram_mb: int = 9000
    scene_splat_device: str = "cuda"
    # Provisional bound until the first measured export sets the documented
    # default; the validator rejects any configured value outside the range.
    scene_splat_max_artifact_bytes: int = 512 * 1024 * 1024
    scene_splat_timeout_seconds: int = 7200
    scene_splat_min_registered_images: int = 8
    scene_splat_sh_degree: int = 3
    scene_splat_python: Path = Path("/opt/venv/bin/python")
    scene_splat_site_packages: Path = Path("/opt/splat-site")
    # Set only on the dedicated neural worker container. A worker registers one
    # capability and rejects tasks persisted for the other representation.
    scene_splat_worker: bool = False

    # Shared advisory image-quality analysis
    # (docs/additions/11_image_quality_analysis.md Section 7). Thresholds are
    # consumed by both ML workers; analysis is advisory and never rejects an
    # image by default. Units: 8-bit intensity values (0-255) for luminance,
    # blur (Laplacian variance on a normalized copy) and noise (Immerkaer
    # sigma); fractions for clipping; pixels for the resolution floor.
    image_quality_enabled: bool = True
    image_quality_required: bool = False
    image_quality_max_analysis_dimension: int = 1024
    image_quality_blur_analysis_edge: int = 512
    image_quality_min_short_edge: int = 640
    image_quality_blur_threshold: float = 100.0
    image_quality_underexposure_threshold: float = 40.0
    image_quality_overexposure_threshold: float = 215.0
    image_quality_shadow_clip_level: int = 5
    image_quality_highlight_clip_level: int = 250
    image_quality_clipping_ratio_threshold: float = 0.15
    image_quality_contrast_threshold: float = 35.0
    image_quality_noise_threshold: float = 15.0
    image_quality_aspect_ratio_min: float = 0.2
    image_quality_aspect_ratio_max: float = 5.0
    image_quality_near_duplicate_enabled: bool = True
    image_quality_near_duplicate_max_images: int = 100
    image_quality_hash_distance_threshold: int = 10
    image_quality_ssim_enabled: bool = True
    image_quality_ssim_threshold: float = 0.92

    # Name reported in structured worker logs; Compose sets it per service.
    worker_service_name: str = "cleanup-worker"

    storage_root: Path = Path("/data")

    session_ttl_hours: int = 24
    session_cookie_secure: bool = False
    # In-process fixed-window limiter for the unauthenticated auth endpoints.
    # It protects the password-verification endpoint from online guessing and
    # the registration endpoint from bulk account creation. Counters are
    # per-process; see docs/reviews/phase9_closeout.md Section 7 for the
    # single-instance scope.
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_seconds: int = 60
    # Signs the session-bound CSRF token. Must be overridden in production.
    csrf_secret: str = Field(default=DEFAULT_DEV_CSRF_SECRET, repr=False)
    password_min_length: int = 8
    password_max_length: int = 128
    max_upload_size_mb: int = 20
    # Longest accepted image edge, in pixels (04 Section 10.3 step 8).
    max_image_dimension: int = 8192
    min_scene_images: int = 3
    max_scene_images: int = 100
    # Upper bound for offset pagination on project listings (api_contracts 7.2).
    max_page_size: int = 100

    cors_origins: str = ""
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"

    @property
    def allowed_origins(self) -> list[str]:
        """CORS origins as a list, parsed from a comma-separated value."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("api_v1_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            message = "api_v1_prefix must start with '/'"
            raise ValueError(message)
        normalized = value.rstrip("/")
        return normalized or "/"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in LOG_LEVELS:
            message = f"log_level must be one of {sorted(LOG_LEVELS)}"
            raise ValueError(message)
        return level

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value.startswith(SUPPORTED_DRIVERS):
            message = "database_url must use a PostgreSQL driver"
            raise ValueError(message)
        return value

    @field_validator("storage_root")
    @classmethod
    def _validate_storage_root(cls, value: Path) -> Path:
        # A relative root would resolve against the process working directory,
        # which differs between the API and worker containers.
        if not value.is_absolute():
            message = "storage_root must be an absolute path"
            raise ValueError(message)
        return value

    @field_validator("object_model_dir")
    @classmethod
    def _validate_object_model_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            message = "object_model_dir must be an absolute path"
            raise ValueError(message)
        return value

    @field_validator("object_work_dir")
    @classmethod
    def _validate_object_work_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            message = "object_work_dir must be an absolute path"
            raise ValueError(message)
        return value

    @field_validator("scene_colmap_executable", "scene_openmvs_bin_dir", "scene_work_dir")
    @classmethod
    def _validate_scene_paths(cls, value: Path) -> Path:
        if not value.is_absolute():
            message = "scene tool and workspace paths must be absolute"
            raise ValueError(message)
        return value

    @field_validator("scene_matching_strategy")
    @classmethod
    def _validate_scene_matching_strategy(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"EXHAUSTIVE", "SEQUENTIAL"}:
            message = "scene_matching_strategy must be EXHAUSTIVE or SEQUENTIAL"
            raise ValueError(message)
        return normalized

    @field_validator("scene_output_format")
    @classmethod
    def _validate_scene_output_format(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"GLB", "PLY"}:
            message = "scene_output_format must be 'GLB' (mesh) or 'PLY' (gaussian splat)"
            raise ValueError(message)
        return normalized

    @field_validator("scene_representation")
    @classmethod
    def _validate_scene_representation(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mesh", "gaussian_splat"}:
            message = "scene_representation must be 'mesh' or 'gaussian_splat'"
            raise ValueError(message)
        return normalized

    @field_validator("scene_splat_worker_queue")
    @classmethod
    def _validate_scene_splat_worker_queue(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or any(
            c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in normalized
        ):
            message = "scene_splat_worker_queue must be a non-empty lowercase queue name"
            raise ValueError(message)
        if normalized in {"object_generation", "scene_reconstruction", "file_cleanup"}:
            message = "scene_splat_worker_queue must be distinct from the existing queues"
            raise ValueError(message)
        return normalized

    @field_validator("scene_splat_model")
    @classmethod
    def _validate_scene_splat_model(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "splatfacto":
            message = (
                "scene_splat_model must be 'splatfacto': the big variant does not fit "
                "the 12 GB target profile"
            )
            raise ValueError(message)
        return normalized

    @field_validator("scene_splat_device")
    @classmethod
    def _validate_scene_splat_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"cuda", "cpu"}:
            message = "scene_splat_device must be 'cuda' or 'cpu'"
            raise ValueError(message)
        return normalized

    @field_validator("scene_splat_python", "scene_splat_site_packages")
    @classmethod
    def _validate_scene_splat_python(cls, value: Path) -> Path:
        if not value.is_absolute():
            message = "scene_splat_python and scene_splat_site_packages must be absolute paths"
            raise ValueError(message)
        return value

    @field_validator("scene_feature_backend")
    @classmethod
    def _validate_scene_feature_backend(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"COLMAP_SIFT", "ALIKED_LIGHTGLUE"}:
            message = "scene_feature_backend must be COLMAP_SIFT or ALIKED_LIGHTGLUE"
            raise ValueError(message)
        return normalized

    @field_validator("scene_feature_profile")
    @classmethod
    def _validate_scene_feature_profile(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {
            "sift_default",
            "aliked_lightglue",
            "aliked_lightglue_fast",
        }:
            message = (
                "scene_feature_profile must be sift_default, aliked_lightglue "
                "or aliked_lightglue_fast"
            )
            raise ValueError(message)
        return normalized

    @field_validator("scene_feature_pair_strategy")
    @classmethod
    def _validate_scene_feature_pair_strategy(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"EXHAUSTIVE", "SEQUENTIAL"}:
            message = "scene_feature_pair_strategy must be EXHAUSTIVE or SEQUENTIAL"
            raise ValueError(message)
        return normalized

    @field_validator("scene_feature_device")
    @classmethod
    def _validate_scene_feature_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cuda", "cpu"}:
            message = "scene_feature_device must be auto, cuda or cpu"
            raise ValueError(message)
        return normalized

    @field_validator("scene_feature_match_threshold")
    @classmethod
    def _validate_scene_feature_match_threshold(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            message = "scene_feature_match_threshold must be in [0, 1]"
            raise ValueError(message)
        return value

    @field_validator("object_model_sha256")
    @classmethod
    def _validate_object_model_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized and (
            len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized)
        ):
            message = "object_model_sha256 must be a 64-character hexadecimal SHA-256"
            raise ValueError(message)
        return normalized

    @model_validator(mode="after")
    def _validate_limits(self) -> Settings:
        if self.min_scene_images < 1:
            message = "min_scene_images must be at least 1"
            raise ValueError(message)
        if self.min_scene_images > self.max_scene_images:
            message = "min_scene_images must not exceed max_scene_images"
            raise ValueError(message)
        if self.max_upload_size_mb < 1:
            message = "max_upload_size_mb must be at least 1"
            raise ValueError(message)
        if self.max_image_dimension < 1:
            message = "max_image_dimension must be at least 1"
            raise ValueError(message)
        if self.max_page_size < 1:
            message = "max_page_size must be at least 1"
            raise ValueError(message)
        if self.cleanup_batch_size < 1:
            message = "cleanup_batch_size must be at least 1"
            raise ValueError(message)
        if self.cleanup_poll_interval_seconds < 1:
            message = "cleanup_poll_interval_seconds must be at least 1"
            raise ValueError(message)
        if self.cleanup_max_attempts < 1:
            message = "cleanup_max_attempts must be at least 1"
            raise ValueError(message)
        if self.cleanup_task_time_limit_seconds < 1:
            message = "cleanup_task_time_limit_seconds must be at least 1"
            raise ValueError(message)
        if self.session_cleanup_interval_seconds < 60:
            message = "session_cleanup_interval_seconds must be at least 60"
            raise ValueError(message)
        if self.outbox_batch_size < 1:
            message = "outbox_batch_size must be at least 1"
            raise ValueError(message)
        if self.outbox_poll_interval_seconds < 1:
            message = "outbox_poll_interval_seconds must be at least 1"
            raise ValueError(message)
        if self.outbox_retry_base_seconds < 1:
            message = "outbox_retry_base_seconds must be at least 1"
            raise ValueError(message)
        if self.outbox_retry_max_seconds < self.outbox_retry_base_seconds:
            message = "outbox_retry_max_seconds must not be less than outbox_retry_base_seconds"
            raise ValueError(message)
        if self.outbox_max_attempts < 1:
            message = "outbox_max_attempts must be at least 1"
            raise ValueError(message)
        if self.outbox_lock_timeout_seconds < 1:
            message = "outbox_lock_timeout_seconds must be at least 1"
            raise ValueError(message)
        if self.task_lease_seconds < 1:
            message = "task_lease_seconds must be at least 1"
            raise ValueError(message)
        if self.task_heartbeat_seconds < 1:
            message = "task_heartbeat_seconds must be at least 1"
            raise ValueError(message)
        if self.task_heartbeat_seconds > self.task_lease_seconds:
            message = "task_heartbeat_seconds must not exceed task_lease_seconds"
            raise ValueError(message)
        if self.task_stale_threshold_seconds < self.task_lease_seconds:
            message = "task_stale_threshold_seconds must not be less than task_lease_seconds"
            raise ValueError(message)
        if self.dispatch_stall_timeout_seconds < 1:
            message = "dispatch_stall_timeout_seconds must be at least 1"
            raise ValueError(message)
        if self.task_recovery_max_attempts < 1:
            message = "task_recovery_max_attempts must be at least 1"
            raise ValueError(message)
        if self.recovery_batch_size < 1:
            message = "recovery_batch_size must be at least 1"
            raise ValueError(message)
        if self.recovery_poll_interval_seconds < 1:
            message = "recovery_poll_interval_seconds must be at least 1"
            raise ValueError(message)
        if self.object_task_time_limit_seconds < 1:
            message = "object_task_time_limit_seconds must be at least 1"
            raise ValueError(message)
        if self.scene_task_time_limit_seconds < 1:
            message = "scene_task_time_limit_seconds must be at least 1"
            raise ValueError(message)
        if not self.object_device.strip():
            message = "object_device must not be empty"
            raise ValueError(message)
        if self.object_chunk_size < 1:
            message = "object_chunk_size must be at least 1"
            raise ValueError(message)
        if not 32 <= self.object_mc_resolution <= 512:
            message = "object_mc_resolution must be between 32 and 512"
            raise ValueError(message)
        if not 0 < self.object_foreground_ratio <= 1:
            message = "object_foreground_ratio must be in (0, 1]"
            raise ValueError(message)
        if self.object_output_format.lower() != "glb":
            message = "object_output_format must be 'glb' for the MVP"
            raise ValueError(message)
        if self.object_bake_texture and self.object_ai_texture_enabled:
            message = "texture baking and AI texture generation are mutually exclusive"
            raise ValueError(message)
        if not 64 <= self.object_texture_resolution <= 4096:
            message = "object_texture_resolution must be between 64 and 4096"
            raise ValueError(message)
        if not 0.0 <= self.object_mesh_merge_tolerance <= 0.1:
            message = "object_mesh_merge_tolerance must be between 0 and 0.1"
            raise ValueError(message)
        if self.object_mesh_small_component_faces < 1:
            message = "object_mesh_small_component_faces must be at least 1"
            raise ValueError(message)
        if self.object_mesh_target_faces < 0:
            message = "object_mesh_target_faces must not be negative"
            raise ValueError(message)
        if self.object_mesh_simplification_enabled and self.object_mesh_target_faces <= 0:
            message = "object_mesh_target_faces must be positive when simplification is enabled"
            raise ValueError(message)
        if not 0.0 < self.object_mesh_max_deviation <= 0.5:
            message = "object_mesh_max_deviation must be in (0, 0.5]"
            raise ValueError(message)
        if self.object_mesh_smoothing_iterations != 0:
            message = "object mesh smoothing is not implemented; keep it at 0"
            raise ValueError(message)
        if not 64 <= self.object_uv_resolution <= 4096:
            message = "object_uv_resolution must be between 64 and 4096"
            raise ValueError(message)
        if not 0 <= self.object_uv_padding <= 64 or not 0 <= self.object_texture_padding <= 64:
            message = "object UV/texture padding must be between 0 and 64"
            raise ValueError(message)
        if self.object_ai_texture_enabled:
            message = (
                "object AI texture generation is unavailable: no model has passed the "
                "licence, compatibility, cache and 12 GB feasibility review"
            )
            raise ValueError(message)
        if self.object_ai_texture_backend.strip().lower() != "disabled":
            message = "object_ai_texture_backend must be 'disabled' in this build"
            raise ValueError(message)
        if self.object_max_task_seconds < 1:
            message = "object_max_task_seconds must be at least 1"
            raise ValueError(message)
        if self.object_worker_concurrency < 1:
            message = "object_worker_concurrency must be at least 1"
            raise ValueError(message)
        if self.object_input_size < 32:
            message = "object_input_size must be at least 32"
            raise ValueError(message)
        self._validate_object_generator()
        if self.scene_colmap_max_features < 1:
            message = "scene_colmap_max_features must be at least 1"
            raise ValueError(message)
        if self.scene_max_image_size < 1:
            message = "scene_max_image_size must be at least 1"
            raise ValueError(message)
        if self.scene_max_threads < 1:
            message = "scene_max_threads must be at least 1"
            raise ValueError(message)
        if self.scene_min_registered_images < 1:
            message = "scene_min_registered_images must be at least 1"
            raise ValueError(message)
        if not 0 < self.scene_min_registration_ratio <= 1:
            message = "scene_min_registration_ratio must be in (0, 1]"
            raise ValueError(message)
        if self.scene_min_sparse_points < 0 or self.scene_min_dense_points < 0:
            message = "scene point thresholds must not be negative"
            raise ValueError(message)
        if self.scene_max_task_seconds < 1:
            message = "scene_max_task_seconds must be at least 1"
            raise ValueError(message)
        if self.scene_colmap_timeout_seconds < 1:
            message = "scene_colmap_timeout_seconds must be at least 1"
            raise ValueError(message)
        if self.scene_openmvs_timeout_seconds < 1:
            message = "scene_openmvs_timeout_seconds must be at least 1"
            raise ValueError(message)
        if self.scene_export_timeout_seconds < 1:
            message = "scene_export_timeout_seconds must be at least 1"
            raise ValueError(message)
        if self.scene_workspace_retention_hours < 0:
            message = "scene_workspace_retention_hours must not be negative"
            raise ValueError(message)
        if self.scene_workspace_sweep_interval_seconds < 60:
            message = "scene_workspace_sweep_interval_seconds must be at least 60"
            raise ValueError(message)
        if self.scene_representation == "gaussian_splat" and not self.scene_splat_enabled:
            message = "scene_representation=gaussian_splat requires scene_splat_enabled=true"
            raise ValueError(message)
        expected_format = "PLY" if self.scene_representation == "gaussian_splat" else "GLB"
        if self.scene_output_format != expected_format:
            message = (
                f"scene_output_format must be {expected_format} for "
                f"scene_representation={self.scene_representation}"
            )
            raise ValueError(message)
        if not 100 <= self.scene_splat_max_iterations <= 200_000:
            message = "scene_splat_max_iterations must be between 100 and 200000"
            raise ValueError(message)
        if not 0.1 <= self.scene_splat_image_scale <= 1.0:
            message = "scene_splat_image_scale must be in (0.1, 1.0]"
            raise ValueError(message)
        if not 256 <= self.scene_splat_max_image_dimension <= 8192:
            message = "scene_splat_max_image_dimension must be between 256 and 8192"
            raise ValueError(message)
        if not 100 <= self.scene_splat_checkpoint_interval <= self.scene_splat_max_iterations:
            message = "scene_splat_checkpoint_interval must be between 100 and max iterations"
            raise ValueError(message)
        if not 1024 <= self.scene_splat_max_vram_mb <= 16384:
            message = "scene_splat_max_vram_mb must be between 1024 and 16384"
            raise ValueError(message)
        if not 1024 * 1024 <= self.scene_splat_max_artifact_bytes <= 4 * 1024 * 1024 * 1024:
            message = "scene_splat_max_artifact_bytes must be between 1 MiB and 4 GiB"
            raise ValueError(message)
        if not 60 <= self.scene_splat_timeout_seconds <= self.scene_task_time_limit_seconds:
            message = (
                "scene_splat_timeout_seconds must be between 60 and scene_task_time_limit_seconds"
            )
            raise ValueError(message)
        if self.scene_splat_enabled or self.scene_representation == "gaussian_splat":
            if not self.scene_min_registered_images <= self.scene_splat_min_registered_images:
                message = (
                    "scene_splat_min_registered_images must not be below min registered images"
                )
                raise ValueError(message)
            if self.scene_splat_min_registered_images > self.max_scene_images:
                message = "scene_splat_min_registered_images must not exceed max_scene_images"
                raise ValueError(message)
        if not 0 <= self.scene_splat_sh_degree <= 3:
            message = "scene_splat_sh_degree must be between 0 and 3"
            raise ValueError(message)
        if not 128 <= self.scene_feature_max_keypoints <= 20000:
            message = "scene_feature_max_keypoints must be between 128 and 20000"
            raise ValueError(message)
        if not 256 <= self.scene_feature_image_max_size <= 8192:
            message = "scene_feature_image_max_size must be between 256 and 8192"
            raise ValueError(message)
        if not 1 <= self.scene_feature_sequential_overlap <= 100:
            message = "scene_feature_sequential_overlap must be between 1 and 100"
            raise ValueError(message)
        if not 0 <= self.scene_feature_min_matches <= 10000:
            message = "scene_feature_min_matches must be between 0 and 10000"
            raise ValueError(message)
        if self.scene_feature_max_vram_mb < 512:
            message = "scene_feature_max_vram_mb must be at least 512"
            raise ValueError(message)
        if self.scene_feature_max_pairs < 1:
            message = "scene_feature_max_pairs must be at least 1"
            raise ValueError(message)
        if self.scene_mesh_target_faces < 0:
            message = "scene_mesh_target_faces must not be negative"
            raise ValueError(message)
        if self.scene_mesh_simplification_enabled and self.scene_mesh_target_faces <= 0:
            message = "scene_mesh_target_faces must be positive when simplification is enabled"
            raise ValueError(message)
        if not 0.0 < self.scene_mesh_max_deviation <= 0.5:
            message = "scene_mesh_max_deviation must be in (0, 0.5]"
            raise ValueError(message)
        if self.scene_generate_uv:
            message = (
                "scene UV regeneration is unavailable: OpenMVS UVs/atlases are preserved "
                "and must not be replaced by xatlas by default"
            )
            raise ValueError(message)
        if self.scene_ai_texture_enabled:
            message = "scene AI texture generation is unavailable in this build"
            raise ValueError(message)
        if self.texture_enhancement_device.strip().lower() != "cpu":
            message = "texture_enhancement_device must be 'cpu' in this build"
            raise ValueError(message)
        if self.mesh_enhancement_max_memory_mb < 256:
            message = "mesh_enhancement_max_memory_mb must be at least 256"
            raise ValueError(message)
        sift_profile = self.scene_feature_profile == "sift_default"
        if self.scene_feature_backend == "COLMAP_SIFT" and not sift_profile:
            message = "COLMAP_SIFT accepts only the sift_default feature profile"
            raise ValueError(message)
        if self.scene_feature_backend == "ALIKED_LIGHTGLUE" and sift_profile:
            message = "ALIKED_LIGHTGLUE requires an aliked_lightglue profile"
            raise ValueError(message)
        if self.image_quality_max_analysis_dimension < 32:
            message = "image_quality_max_analysis_dimension must be at least 32"
            raise ValueError(message)
        if not 32 <= self.image_quality_blur_analysis_edge <= 4096:
            message = "image_quality_blur_analysis_edge must be between 32 and 4096"
            raise ValueError(message)
        if self.image_quality_min_short_edge < 1:
            message = "image_quality_min_short_edge must be at least 1"
            raise ValueError(message)
        if self.image_quality_blur_threshold < 0:
            message = "image_quality_blur_threshold must not be negative"
            raise ValueError(message)
        if not (
            0
            < self.image_quality_underexposure_threshold
            < self.image_quality_overexposure_threshold
            <= 255
        ):
            message = "image quality exposure thresholds must satisfy 0 < under < over <= 255"
            raise ValueError(message)
        if not (
            0
            <= self.image_quality_shadow_clip_level
            < self.image_quality_highlight_clip_level
            <= 255
        ):
            message = "image quality clip levels must satisfy 0 <= shadow < highlight <= 255"
            raise ValueError(message)
        if not 0 < self.image_quality_clipping_ratio_threshold <= 1:
            message = "image_quality_clipping_ratio_threshold must be in (0, 1]"
            raise ValueError(message)
        if self.image_quality_contrast_threshold < 0:
            message = "image_quality_contrast_threshold must not be negative"
            raise ValueError(message)
        if self.image_quality_noise_threshold < 0:
            message = "image_quality_noise_threshold must not be negative"
            raise ValueError(message)
        if not (
            0 < self.image_quality_aspect_ratio_min <= 1 <= self.image_quality_aspect_ratio_max
        ):
            message = "image quality aspect ratio bounds must satisfy 0 < min <= 1 <= max"
            raise ValueError(message)
        if self.image_quality_near_duplicate_max_images < 2:
            message = "image_quality_near_duplicate_max_images must be at least 2"
            raise ValueError(message)
        if not 0 <= self.image_quality_hash_distance_threshold <= 63:
            message = "image_quality_hash_distance_threshold must be between 0 and 63"
            raise ValueError(message)
        if not 0 < self.image_quality_ssim_threshold <= 1:
            message = "image_quality_ssim_threshold must be in (0, 1]"
            raise ValueError(message)
        if not self.worker_service_name.strip():
            message = "worker_service_name must not be empty"
            raise ValueError(message)
        if self.session_ttl_hours < 1:
            message = "session_ttl_hours must be at least 1"
            raise ValueError(message)
        if self.auth_rate_limit_attempts < 1:
            message = "auth_rate_limit_attempts must be at least 1"
            raise ValueError(message)
        if self.auth_rate_limit_window_seconds < 1:
            message = "auth_rate_limit_window_seconds must be at least 1"
            raise ValueError(message)
        if self.password_min_length < 8:
            message = "password_min_length must be at least 8"
            raise ValueError(message)
        if self.password_max_length < self.password_min_length:
            message = "password_max_length must not be less than password_min_length"
            raise ValueError(message)
        if self.password_max_length > 1024:
            message = "password_max_length must not exceed 1024"
            raise ValueError(message)
        if self.app_env == "production":
            if self.csrf_secret == DEFAULT_DEV_CSRF_SECRET or len(self.csrf_secret) < 32:
                message = "csrf_secret must be set to at least 32 characters in production"
                raise ValueError(message)
            if not self.session_cookie_secure:
                message = "session_cookie_secure must be enabled in production"
                raise ValueError(message)
        return self

    def _validate_object_generator(self) -> None:
        """Validate the generator policy (13 Section 6).

        TripoSR stays the default. SF3D is opt-in and needs a pinned revision
        plus a checksum manifest. Hunyuan3D is recognised only so the failure is
        explicit: the adapter is blocked (licence/territory, 12 GB VRAM and a
        conflicting PyTorch stack), and it must never initialise silently.
        """
        generator = (self.object_generator or "").strip().lower()
        if generator not in {"triposr", "sf3d"}:
            message = (
                "object_generator must be 'triposr' or 'sf3d'; the Hunyuan3D "
                "adapter is not available in this build"
                if generator == "hunyuan3d"
                else "object_generator must be 'triposr' or 'sf3d'"
            )
            raise ValueError(message)

        if not self.object_sf3d_model_dir.is_absolute():
            message = "object_sf3d_model_dir must be an absolute path"
            raise ValueError(message)
        if not self.object_sf3d_manifest_path.is_absolute():
            message = "object_sf3d_manifest_path must be an absolute path"
            raise ValueError(message)
        if not 128 <= self.object_sf3d_texture_resolution <= 4096:
            message = "object_sf3d_texture_resolution must be between 128 and 4096"
            raise ValueError(message)
        if self.object_sf3d_remesh not in {"none", "triangle", "quad"}:
            message = "object_sf3d_remesh must be 'none', 'triangle' or 'quad'"
            raise ValueError(message)
        if (
            self.object_sf3d_target_vertex_count != -1
            and self.object_sf3d_target_vertex_count < 100
        ):
            message = "object_sf3d_target_vertex_count must be -1 or at least 100"
            raise ValueError(message)

        if generator == "sf3d":
            if not self.object_sf3d_enabled:
                message = "object_generator=sf3d requires object_sf3d_enabled=true"
                raise ValueError(message)
            revision = self.object_sf3d_model_revision.strip()
            if not revision or revision.lower() in {"main", "master", "head"}:
                message = (
                    "object_sf3d_model_revision must be an immutable revision when SF3D is enabled"
                )
                raise ValueError(message)

        if not self.object_hunyuan3d_model_dir.is_absolute():
            message = "object_hunyuan3d_model_dir must be an absolute path"
            raise ValueError(message)
        if self.object_hunyuan3d_enabled:
            # The gates are evaluated in order so the diagnostic names the exact
            # condition that failed. Tests use deterministic fixtures and never
            # infer a location from the host.
            if not self.object_hunyuan3d_license_acknowledged:
                message = (
                    "Hunyuan3D requires explicit licence acknowledgement "
                    "(object_hunyuan3d_license_acknowledged=true)"
                )
                raise ValueError(message)
            territory = self.object_hunyuan3d_territory.strip().upper()
            if not territory:
                message = "Hunyuan3D requires object_hunyuan3d_territory (ISO code)"
                raise ValueError(message)
            if territory in HUNYUAN3D_EXCLUDED_TERRITORIES:
                message = (
                    "The Hunyuan3D-2.1 licence excludes the European Union, the "
                    f"United Kingdom and South Korea; territory {territory} is not permitted"
                )
                raise ValueError(message)
            if self.object_hunyuan3d_mode != "shape":
                message = (
                    "Only Hunyuan3D shape generation is permitted; texture generation "
                    "is disabled for the 12 GB hardware profile"
                )
                raise ValueError(message)
            if self.object_hunyuan3d_texture_enabled:
                message = "Hunyuan3D texture generation is disabled for the 12 GB profile"
                raise ValueError(message)
            if not self.object_hunyuan3d_model_revision.strip():
                message = "object_hunyuan3d_model_revision is required when enabled"
                raise ValueError(message)
            message = (
                "The Hunyuan3D adapter is not available in this build: licence, "
                "hardware and dependency checks were not satisfied"
            )
            raise ValueError(message)

    def redacted(self) -> dict[str, object]:
        """Return a log-safe representation of the settings."""
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "version": self.version,
            "debug": self.debug,
            "api_v1_prefix": self.api_v1_prefix,
            "database_url": redact_url(self.database_url),
            "redis_url": redact_url(self.redis_url),
            "celery_broker_url": redact_url(self.celery_broker_url),
            "celery_task_ignore_result": self.celery_task_ignore_result,
            "cleanup_batch_size": self.cleanup_batch_size,
            "cleanup_poll_interval_seconds": self.cleanup_poll_interval_seconds,
            "cleanup_max_attempts": self.cleanup_max_attempts,
            "cleanup_task_time_limit_seconds": self.cleanup_task_time_limit_seconds,
            "session_cleanup_interval_seconds": self.session_cleanup_interval_seconds,
            "outbox_batch_size": self.outbox_batch_size,
            "outbox_poll_interval_seconds": self.outbox_poll_interval_seconds,
            "outbox_retry_base_seconds": self.outbox_retry_base_seconds,
            "outbox_retry_max_seconds": self.outbox_retry_max_seconds,
            "outbox_max_attempts": self.outbox_max_attempts,
            "outbox_lock_timeout_seconds": self.outbox_lock_timeout_seconds,
            "task_lease_seconds": self.task_lease_seconds,
            "task_heartbeat_seconds": self.task_heartbeat_seconds,
            "task_stale_threshold_seconds": self.task_stale_threshold_seconds,
            "dispatch_stall_timeout_seconds": self.dispatch_stall_timeout_seconds,
            "task_recovery_max_attempts": self.task_recovery_max_attempts,
            "recovery_batch_size": self.recovery_batch_size,
            "recovery_poll_interval_seconds": self.recovery_poll_interval_seconds,
            "object_task_time_limit_seconds": self.object_task_time_limit_seconds,
            "scene_task_time_limit_seconds": self.scene_task_time_limit_seconds,
            "object_model_id": self.object_model_id,
            "object_model_revision": self.object_model_revision,
            "object_model_dir": str(self.object_model_dir),
            "object_model_sha256": self.object_model_sha256,
            "object_work_dir": str(self.object_work_dir),
            "object_dino_model_id": self.object_dino_model_id,
            "object_dino_revision": self.object_dino_revision,
            "object_device": self.object_device,
            "object_allow_cpu_fallback": self.object_allow_cpu_fallback,
            "object_chunk_size": self.object_chunk_size,
            "object_mc_resolution": self.object_mc_resolution,
            "object_remove_background": self.object_remove_background,
            "object_foreground_ratio": self.object_foreground_ratio,
            "object_output_format": self.object_output_format,
            "object_bake_texture": self.object_bake_texture,
            "object_texture_resolution": self.object_texture_resolution,
            "object_mesh_cleanup_enabled": self.object_mesh_cleanup_enabled,
            "object_mesh_merge_tolerance": self.object_mesh_merge_tolerance,
            "object_mesh_remove_small_components": self.object_mesh_remove_small_components,
            "object_mesh_small_component_faces": self.object_mesh_small_component_faces,
            "object_mesh_normals_enabled": self.object_mesh_normals_enabled,
            "object_mesh_simplification_enabled": self.object_mesh_simplification_enabled,
            "object_mesh_target_faces": self.object_mesh_target_faces,
            "object_mesh_max_deviation": self.object_mesh_max_deviation,
            "object_mesh_smoothing_iterations": self.object_mesh_smoothing_iterations,
            "object_generate_uv": self.object_generate_uv,
            "object_uv_resolution": self.object_uv_resolution,
            "object_uv_padding": self.object_uv_padding,
            "object_texture_padding": self.object_texture_padding,
            "object_ai_texture_enabled": self.object_ai_texture_enabled,
            "object_ai_texture_backend": self.object_ai_texture_backend,
            "object_max_task_seconds": self.object_max_task_seconds,
            "object_worker_concurrency": self.object_worker_concurrency,
            "object_rembg_model": self.object_rembg_model,
            "object_input_size": self.object_input_size,
            "object_generation_enabled": self.object_generation_enabled,
            "object_generator": self.object_generator,
            "object_generator_fallback": self.object_generator_fallback,
            "object_sf3d_enabled": self.object_sf3d_enabled,
            "object_sf3d_model_id": self.object_sf3d_model_id,
            "object_sf3d_model_revision": self.object_sf3d_model_revision,
            "object_sf3d_model_dir": str(self.object_sf3d_model_dir),
            "object_sf3d_texture_resolution": self.object_sf3d_texture_resolution,
            "object_sf3d_remesh": self.object_sf3d_remesh,
            "object_sf3d_target_vertex_count": self.object_sf3d_target_vertex_count,
            "object_hunyuan3d_enabled": self.object_hunyuan3d_enabled,
            "object_hunyuan3d_mode": self.object_hunyuan3d_mode,
            "scene_reconstruction_enabled": self.scene_reconstruction_enabled,
            "scene_colmap_executable": str(self.scene_colmap_executable),
            "scene_openmvs_bin_dir": str(self.scene_openmvs_bin_dir),
            "scene_work_dir": str(self.scene_work_dir),
            "scene_matching_strategy": self.scene_matching_strategy,
            "scene_colmap_use_gpu": self.scene_colmap_use_gpu,
            "scene_colmap_max_features": self.scene_colmap_max_features,
            "scene_colmap_camera_model": self.scene_colmap_camera_model,
            "scene_max_image_size": self.scene_max_image_size,
            "scene_max_threads": self.scene_max_threads,
            "scene_openmvs_use_cuda": self.scene_openmvs_use_cuda,
            "scene_enable_mesh_refinement": self.scene_enable_mesh_refinement,
            "scene_enable_texture_generation": self.scene_enable_texture_generation,
            "scene_min_registered_images": self.scene_min_registered_images,
            "scene_min_registration_ratio": self.scene_min_registration_ratio,
            "scene_min_sparse_points": self.scene_min_sparse_points,
            "scene_min_dense_points": self.scene_min_dense_points,
            "scene_max_task_seconds": self.scene_max_task_seconds,
            "scene_colmap_timeout_seconds": self.scene_colmap_timeout_seconds,
            "scene_openmvs_timeout_seconds": self.scene_openmvs_timeout_seconds,
            "scene_export_timeout_seconds": self.scene_export_timeout_seconds,
            "scene_output_format": self.scene_output_format,
            "scene_representation": self.scene_representation,
            "scene_splat_enabled": self.scene_splat_enabled,
            "scene_splat_worker_queue": self.scene_splat_worker_queue,
            "scene_splat_model": self.scene_splat_model,
            "scene_splat_max_iterations": self.scene_splat_max_iterations,
            "scene_splat_image_scale": self.scene_splat_image_scale,
            "scene_splat_max_image_dimension": self.scene_splat_max_image_dimension,
            "scene_splat_max_vram_mb": self.scene_splat_max_vram_mb,
            "scene_splat_device": self.scene_splat_device,
            "scene_splat_max_artifact_bytes": self.scene_splat_max_artifact_bytes,
            "scene_splat_timeout_seconds": self.scene_splat_timeout_seconds,
            "scene_splat_worker": self.scene_splat_worker,
            "scene_feature_backend": self.scene_feature_backend,
            "scene_feature_profile": self.scene_feature_profile,
            "scene_feature_fallback_to_sift": self.scene_feature_fallback_to_sift,
            "scene_feature_max_keypoints": self.scene_feature_max_keypoints,
            "scene_feature_image_max_size": self.scene_feature_image_max_size,
            "scene_feature_pair_strategy": self.scene_feature_pair_strategy,
            "scene_feature_sequential_overlap": self.scene_feature_sequential_overlap,
            "scene_feature_min_matches": self.scene_feature_min_matches,
            "scene_feature_match_threshold": self.scene_feature_match_threshold,
            "scene_feature_device": self.scene_feature_device,
            "scene_feature_max_vram_mb": self.scene_feature_max_vram_mb,
            "scene_feature_max_pairs": self.scene_feature_max_pairs,
            "scene_mesh_postprocess_enabled": self.scene_mesh_postprocess_enabled,
            "scene_mesh_cleanup_enabled": self.scene_mesh_cleanup_enabled,
            "scene_normals_enabled": self.scene_normals_enabled,
            "scene_mesh_simplification_enabled": self.scene_mesh_simplification_enabled,
            "scene_mesh_target_faces": self.scene_mesh_target_faces,
            "scene_mesh_max_deviation": self.scene_mesh_max_deviation,
            "scene_generate_uv": self.scene_generate_uv,
            "scene_ai_texture_enabled": self.scene_ai_texture_enabled,
            "enhancement_fallback_to_original": self.enhancement_fallback_to_original,
            "mesh_enhancement_max_memory_mb": self.mesh_enhancement_max_memory_mb,
            "texture_enhancement_device": self.texture_enhancement_device,
            "scene_workspace_retention_hours": self.scene_workspace_retention_hours,
            "scene_workspace_sweep_interval_seconds": self.scene_workspace_sweep_interval_seconds,
            "image_quality_enabled": self.image_quality_enabled,
            "image_quality_required": self.image_quality_required,
            "image_quality_max_analysis_dimension": self.image_quality_max_analysis_dimension,
            "image_quality_blur_analysis_edge": self.image_quality_blur_analysis_edge,
            "image_quality_min_short_edge": self.image_quality_min_short_edge,
            "image_quality_blur_threshold": self.image_quality_blur_threshold,
            "image_quality_underexposure_threshold": self.image_quality_underexposure_threshold,
            "image_quality_overexposure_threshold": self.image_quality_overexposure_threshold,
            "image_quality_shadow_clip_level": self.image_quality_shadow_clip_level,
            "image_quality_highlight_clip_level": self.image_quality_highlight_clip_level,
            "image_quality_clipping_ratio_threshold": (self.image_quality_clipping_ratio_threshold),
            "image_quality_contrast_threshold": self.image_quality_contrast_threshold,
            "image_quality_noise_threshold": self.image_quality_noise_threshold,
            "image_quality_aspect_ratio_min": self.image_quality_aspect_ratio_min,
            "image_quality_aspect_ratio_max": self.image_quality_aspect_ratio_max,
            "image_quality_near_duplicate_enabled": (self.image_quality_near_duplicate_enabled),
            "image_quality_near_duplicate_max_images": (
                self.image_quality_near_duplicate_max_images
            ),
            "image_quality_hash_distance_threshold": (self.image_quality_hash_distance_threshold),
            "image_quality_ssim_enabled": self.image_quality_ssim_enabled,
            "image_quality_ssim_threshold": self.image_quality_ssim_threshold,
            "worker_service_name": self.worker_service_name,
            "storage_root": str(self.storage_root),
            "session_ttl_hours": self.session_ttl_hours,
            "session_cookie_secure": self.session_cookie_secure,
            "auth_rate_limit_enabled": self.auth_rate_limit_enabled,
            "auth_rate_limit_attempts": self.auth_rate_limit_attempts,
            "auth_rate_limit_window_seconds": self.auth_rate_limit_window_seconds,
            "password_min_length": self.password_min_length,
            "password_max_length": self.password_max_length,
            "max_upload_size_mb": self.max_upload_size_mb,
            "max_image_dimension": self.max_image_dimension,
            "min_scene_images": self.min_scene_images,
            "max_scene_images": self.max_scene_images,
            "max_page_size": self.max_page_size,
            "cors_origins": self.allowed_origins,
            "log_level": self.log_level,
        }


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
