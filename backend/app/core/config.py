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
