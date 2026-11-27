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


def test_cleanup_worker_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped defaults, independent of the environment running the tests.

    CI exports ``CELERY_BROKER_URL`` so the integration tests reach the Redis
    container; that variable is meant for those tests, not for asserting the
    application default.
    """
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    settings = Settings(_env_file=None)

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


def test_session_cleanup_defaults_and_bounds() -> None:
    """The scheduled session cleanup runs hourly and cannot be sub-minute."""
    settings = Settings()

    assert settings.session_cleanup_interval_seconds == 3600
    assert settings.redacted()["session_cleanup_interval_seconds"] == 3600

    with pytest.raises(ValidationError):
        Settings(session_cleanup_interval_seconds=59)


def test_auth_rate_limit_defaults_and_bounds() -> None:
    """The MVP enables a 10-per-minute limiter and rejects invalid values."""
    settings = Settings()

    assert settings.auth_rate_limit_enabled is True
    assert settings.auth_rate_limit_attempts == 10
    assert settings.auth_rate_limit_window_seconds == 60
    assert settings.redacted()["auth_rate_limit_attempts"] == 10
    assert Settings(auth_rate_limit_enabled=False).auth_rate_limit_enabled is False

    with pytest.raises(ValidationError):
        Settings(auth_rate_limit_attempts=0)
    with pytest.raises(ValidationError):
        Settings(auth_rate_limit_window_seconds=0)


def test_image_quality_defaults_and_bounds() -> None:
    """The advisory analyzer is enabled with validated, documented defaults."""
    settings = Settings()

    assert settings.image_quality_enabled is True
    assert settings.image_quality_required is False
    assert settings.image_quality_blur_threshold == 100.0
    assert settings.image_quality_min_short_edge == 640
    assert settings.image_quality_hash_distance_threshold == 10
    assert settings.redacted()["image_quality_blur_threshold"] == 100.0
    assert Settings(image_quality_enabled=False).image_quality_enabled is False

    with pytest.raises(ValidationError):
        Settings(image_quality_blur_threshold=-1)
    with pytest.raises(ValidationError):
        Settings(
            image_quality_underexposure_threshold=220,
            image_quality_overexposure_threshold=210,
        )
    with pytest.raises(ValidationError):
        Settings(image_quality_clipping_ratio_threshold=0)
    with pytest.raises(ValidationError):
        Settings(image_quality_hash_distance_threshold=64)
    with pytest.raises(ValidationError):
        Settings(image_quality_ssim_threshold=1.5)


def test_scene_feature_defaults_keep_sift_opt_out() -> None:
    """Increment 12: SIFT stays default and neural matching is opt-in."""
    settings = Settings()

    assert settings.scene_feature_backend == "COLMAP_SIFT"
    assert settings.scene_feature_profile == "sift_default"
    assert settings.scene_feature_fallback_to_sift is True
    assert settings.scene_feature_max_keypoints == 2048
    assert settings.scene_feature_image_max_size == 1600
    assert settings.scene_feature_pair_strategy == "EXHAUSTIVE"
    assert settings.scene_feature_device == "auto"
    assert settings.redacted()["scene_feature_backend"] == "COLMAP_SIFT"


def test_scene_feature_names_are_normalized() -> None:
    settings = Settings(
        scene_feature_backend="aliked_lightglue",
        scene_feature_profile="ALIKED_LIGHTGLUE",
        scene_feature_pair_strategy="sequential",
        scene_feature_device="CUDA",
    )
    assert settings.scene_feature_backend == "ALIKED_LIGHTGLUE"
    assert settings.scene_feature_profile == "aliked_lightglue"
    assert settings.scene_feature_pair_strategy == "SEQUENTIAL"
    assert settings.scene_feature_device == "cuda"


@pytest.mark.parametrize(
    "overrides",
    [
        {"scene_feature_backend": "COLMAP_SIFT", "scene_feature_profile": "aliked_lightglue"},
        {
            "scene_feature_backend": "ALIKED_LIGHTGLUE",
            "scene_feature_profile": "sift_default",
        },
        {"scene_feature_backend": "SUPERGLUE"},
        {"scene_feature_profile": "superpoint"},
        {"scene_feature_pair_strategy": "RANDOM"},
        {"scene_feature_device": "tpu"},
        {"scene_feature_match_threshold": 1.5},
        {"scene_feature_max_keypoints": 16},
        {"scene_feature_image_max_size": 128},
        {"scene_feature_sequential_overlap": 0},
        {"scene_feature_min_matches": -1},
        {"scene_feature_max_vram_mb": 128},
        {"scene_feature_max_pairs": 0},
    ],
)
def test_scene_feature_settings_are_validated(overrides) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)
