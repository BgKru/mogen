"""Settings validation and secret redaction."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, redact_url


def test_cors_origins_are_split_and_trimmed() -> None:
    settings = Settings(cors_origins="http://localhost:5173, http://example.test")

    assert settings.allowed_origins == ["http://localhost:5173", "http://example.test"]


def test_api_prefix_is_normalized() -> None:
    assert Settings(api_v1_prefix="/api/v1/").api_v1_prefix == "/api/v1"


def test_api_prefix_requires_leading_slash() -> None:
    with pytest.raises(ValidationError):
        Settings(api_v1_prefix="api/v1")


def test_scene_image_limits_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Settings(min_scene_images=10, max_scene_images=5)


def test_max_page_size_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(max_page_size=0)

    assert Settings(max_page_size=25).max_page_size == 25


def test_storage_root_must_be_absolute() -> None:
    with pytest.raises(ValidationError):
        Settings(storage_root=Path("data"))

    assert Settings(storage_root=Path("/data")).storage_root == Path("/data")


def test_database_url_must_use_postgres_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///local.db")


def test_redacted_settings_hide_credentials() -> None:
    settings = Settings(database_url="postgresql+psycopg://user:secret@db:5432/app")

    redacted = settings.redacted()

    assert "secret" not in str(redacted["database_url"])
    assert "***" in str(redacted["database_url"])
    assert "secret" not in repr(settings)


def test_redact_url_without_password_is_unchanged() -> None:
    url = "postgresql+psycopg://user@db:5432/app"

    assert redact_url(url) == url


def test_cleanup_worker_defaults() -> None:
    settings = Settings()

    assert settings.cleanup_batch_size == 20
    assert settings.cleanup_poll_interval_seconds == 15
    assert settings.cleanup_max_attempts == 3
    assert settings.cleanup_task_time_limit_seconds == 600
    assert settings.celery_broker_url == "redis://redis:6379/1"
    assert settings.celery_task_ignore_result is True


@pytest.mark.parametrize(
    "field",
    [
        "cleanup_batch_size",
        "cleanup_poll_interval_seconds",
        "cleanup_max_attempts",
        "cleanup_task_time_limit_seconds",
    ],
)
def test_cleanup_worker_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})

    assert getattr(Settings(**{field: 1}), field) == 1


def test_redacted_settings_hide_the_broker_password() -> None:
    settings = Settings(celery_broker_url="redis://:secret@redis:6379/1")

    redacted = settings.redacted()

    assert "secret" not in str(redacted["celery_broker_url"])
    assert "***" in str(redacted["celery_broker_url"])
    assert redacted["cleanup_max_attempts"] == 3


def test_scene_workspace_retention_defaults_and_bounds() -> None:
    """Retention is configurable and 0 means "keep for diagnostics forever"."""
    settings = Settings()

    assert settings.scene_workspace_retention_hours == 168
    assert settings.scene_workspace_sweep_interval_seconds == 3600
    assert settings.redacted()["scene_workspace_retention_hours"] == 168
    assert Settings(scene_workspace_retention_hours=0).scene_workspace_retention_hours == 0

    with pytest.raises(ValidationError):
        Settings(scene_workspace_retention_hours=-1)
    with pytest.raises(ValidationError):
        Settings(scene_workspace_sweep_interval_seconds=59)
