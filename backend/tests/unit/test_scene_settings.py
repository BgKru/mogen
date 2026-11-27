"""Scene-reconstruction settings validation (07 Section 16)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"app_env": "test", "log_level": "WARNING"}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_scene_defaults_are_the_documented_ones() -> None:
    settings = _settings()
    assert settings.scene_reconstruction_enabled is True
    assert settings.scene_matching_strategy == "EXHAUSTIVE"
    assert settings.scene_max_image_size == 2000
    assert settings.scene_min_registered_images == 3
    assert settings.scene_min_registration_ratio == 0.5
    assert settings.scene_output_format == "GLB"
    assert settings.scene_feature_backend == "COLMAP_SIFT"
    assert settings.scene_feature_profile == "sift_default"
    assert settings.scene_feature_fallback_to_sift is True
    assert settings.scene_feature_pair_strategy == "EXHAUSTIVE"
    assert str(settings.scene_colmap_executable) == "/usr/local/bin/colmap"
    assert str(settings.scene_openmvs_bin_dir) == "/usr/local/bin/OpenMVS"


def test_scene_paths_must_be_absolute() -> None:
    with pytest.raises(ValidationError):
        _settings(scene_colmap_executable="colmap")
    with pytest.raises(ValidationError):
        _settings(scene_openmvs_bin_dir="OpenMVS")
    with pytest.raises(ValidationError):
        _settings(scene_work_dir="work")


def test_matching_strategy_is_normalised_and_validated() -> None:
    assert _settings(scene_matching_strategy="sequential").scene_matching_strategy == "SEQUENTIAL"
    with pytest.raises(ValidationError):
        _settings(scene_matching_strategy="RANDOM")


def test_quality_thresholds_are_validated() -> None:
    with pytest.raises(ValidationError):
        _settings(scene_min_registration_ratio=0)
    with pytest.raises(ValidationError):
        _settings(scene_min_registration_ratio=1.5)
    with pytest.raises(ValidationError):
        _settings(scene_min_registered_images=0)
    with pytest.raises(ValidationError):
        _settings(scene_min_dense_points=-1)


def test_timeouts_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _settings(scene_max_task_seconds=0)
    with pytest.raises(ValidationError):
        _settings(scene_colmap_timeout_seconds=0)
    with pytest.raises(ValidationError):
        _settings(scene_openmvs_timeout_seconds=0)
    with pytest.raises(ValidationError):
        _settings(scene_export_timeout_seconds=0)


def test_output_format_is_glb_only() -> None:
    assert _settings(scene_output_format="glb").scene_output_format == "GLB"
    with pytest.raises(ValidationError):
        _settings(scene_output_format="OBJ")


def test_scene_settings_are_redacted_in_logs() -> None:
    redacted = _settings(scene_colmap_use_gpu=True).redacted()
    assert redacted["scene_matching_strategy"] == "EXHAUSTIVE"
    assert redacted["scene_colmap_use_gpu"] is True
    assert redacted["scene_output_format"] == "GLB"
