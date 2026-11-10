"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
SUPPORTED_DRIVERS = ("postgresql+psycopg://", "postgresql://")
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
    version: str = "0.1.0"
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

    # Cleanup worker (08 Section 3.7, 05 Section 12.3).
    cleanup_batch_size: int = 20
    cleanup_poll_interval_seconds: int = 15
    cleanup_max_attempts: int = 3
    cleanup_task_time_limit_seconds: int = 600

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
    object_texture_resolution: int = 2048
    object_max_task_seconds: int = 600
    object_worker_concurrency: int = 1
    object_rembg_model: str = "u2net"
    object_input_size: int = 512
    object_generation_enabled: bool = True

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
    # Scene workspace retention (07 Section 15.7). A failed reconstruction keeps
    # its workspace for diagnostics; the cleanup sweep prunes terminal
    # workspaces older than this many hours. 0 disables pruning.
    scene_workspace_retention_hours: int = 168
    scene_workspace_sweep_interval_seconds: int = 3600

    # Name reported in structured worker logs; Compose sets it per service.
    worker_service_name: str = "cleanup-worker"

    storage_root: Path = Path("/data")

    session_ttl_hours: int = 24
    session_cookie_secure: bool = False
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
        if value.strip().upper() != "GLB":
            message = "scene_output_format must be 'GLB' for the MVP"
            raise ValueError(message)
        return "GLB"

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
        if self.object_bake_texture:
            message = "object_bake_texture is not implemented in the MVP and must be false"
            raise ValueError(message)
        if self.object_texture_resolution < 1:
            message = "object_texture_resolution must be at least 1"
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
        if not self.worker_service_name.strip():
            message = "worker_service_name must not be empty"
            raise ValueError(message)
        if self.session_ttl_hours < 1:
            message = "session_ttl_hours must be at least 1"
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
            "object_max_task_seconds": self.object_max_task_seconds,
            "object_worker_concurrency": self.object_worker_concurrency,
            "object_rembg_model": self.object_rembg_model,
            "object_input_size": self.object_input_size,
            "object_generation_enabled": self.object_generation_enabled,
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
            "scene_workspace_retention_hours": self.scene_workspace_retention_hours,
            "scene_workspace_sweep_interval_seconds": self.scene_workspace_sweep_interval_seconds,
            "worker_service_name": self.worker_service_name,
            "storage_root": str(self.storage_root),
            "session_ttl_hours": self.session_ttl_hours,
            "session_cookie_secure": self.session_cookie_secure,
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
