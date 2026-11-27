"""Scene representation and splat settings validation (increment 15 Section 6).

Traceability: I15-AC-02 (opt-in isolation), I15-AC-12 (resource bounds),
I15-AC-14 (validated settings), addendum Sections 5.1, 5.2, 6 and 8.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"app_env": "test", "log_level": "WARNING"}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _splat(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "scene_representation": "gaussian_splat",
        "scene_splat_enabled": True,
        "scene_output_format": "PLY",
    }
    values.update(overrides)
    return _settings(**values)


def test_splat_defaults_keep_mesh_as_the_default_representation() -> None:
    settings = _settings()
    assert settings.scene_representation == "mesh"
    assert settings.scene_splat_enabled is False
    assert settings.scene_output_format == "GLB"
    assert settings.scene_splat_model == "splatfacto"
    assert settings.scene_splat_worker_queue == "scene_gaussian_splat"
    assert settings.scene_splat_max_iterations == 30000
    assert settings.scene_splat_image_scale == 1.0
    assert settings.scene_splat_max_image_dimension == 1600
    assert settings.scene_splat_checkpoint_interval == 5000
    assert settings.scene_splat_max_vram_mb == 9000
    assert settings.scene_splat_device == "cuda"
    assert settings.scene_splat_max_artifact_bytes == 512 * 1024 * 1024
    assert settings.scene_splat_timeout_seconds == 7200
    assert settings.scene_splat_min_registered_images == 8
    assert settings.scene_splat_sh_degree == 3
    assert settings.scene_splat_worker is False
    assert str(settings.scene_splat_python) == "/opt/venv/bin/python"
    assert str(settings.scene_splat_site_packages) == "/opt/splat-site"


def test_representation_is_normalised() -> None:
    assert _settings(scene_representation="MESH").scene_representation == "mesh"
    assert _splat(scene_representation="GAUSSIAN_SPLAT").scene_representation == "gaussian_splat"


def test_gaussian_splat_requires_the_enabled_gate() -> None:
    with pytest.raises(ValidationError, match="scene_splat_enabled"):
        _settings(scene_representation="gaussian_splat", scene_output_format="PLY")


def test_representation_and_output_format_must_agree() -> None:
    with pytest.raises(ValidationError, match="scene_output_format"):
        _splat(scene_output_format="GLB")
    with pytest.raises(ValidationError, match="scene_output_format"):
        _settings(scene_output_format="PLY")
    assert _splat(scene_output_format="ply").scene_output_format == "PLY"


def test_unsupported_representation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(scene_representation="nerf")


def test_splatfacto_big_is_rejected_on_the_target_profile() -> None:
    with pytest.raises(ValidationError, match="splatfacto"):
        _splat(scene_splat_model="splatfacto-big")
    assert _splat(scene_splat_model="SplatFacto").scene_splat_model == "splatfacto"


def test_iteration_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError, match="max_iterations"):
        _splat(scene_splat_max_iterations=99)
    with pytest.raises(ValidationError, match="max_iterations"):
        _splat(scene_splat_max_iterations=200_001)
    assert (
        _splat(
            scene_splat_max_iterations=500, scene_splat_checkpoint_interval=100
        ).scene_splat_max_iterations
        == 500
    )


def test_image_scale_and_dimension_are_bounded() -> None:
    with pytest.raises(ValidationError, match="image_scale"):
        _splat(scene_splat_image_scale=0.05)
    with pytest.raises(ValidationError, match="image_scale"):
        _splat(scene_splat_image_scale=1.5)
    with pytest.raises(ValidationError, match="max_image_dimension"):
        _splat(scene_splat_max_image_dimension=128)
    with pytest.raises(ValidationError, match="max_image_dimension"):
        _splat(scene_splat_max_image_dimension=9000)


def test_checkpoint_interval_must_be_within_the_training_budget() -> None:
    with pytest.raises(ValidationError, match="checkpoint_interval"):
        _splat(scene_splat_checkpoint_interval=50)
    with pytest.raises(ValidationError, match="checkpoint_interval"):
        _splat(scene_splat_max_iterations=1000, scene_splat_checkpoint_interval=5000)
    assert (
        _splat(
            scene_splat_max_iterations=1000, scene_splat_checkpoint_interval=500
        ).scene_splat_checkpoint_interval
        == 500
    )


def test_vram_budget_is_bounded_for_a_12gb_card() -> None:
    with pytest.raises(ValidationError, match="max_vram_mb"):
        _splat(scene_splat_max_vram_mb=512)
    with pytest.raises(ValidationError, match="max_vram_mb"):
        _splat(scene_splat_max_vram_mb=20000)


def test_artifact_size_is_bounded() -> None:
    with pytest.raises(ValidationError, match="max_artifact_bytes"):
        _splat(scene_splat_max_artifact_bytes=1024)
    with pytest.raises(ValidationError, match="max_artifact_bytes"):
        _splat(scene_splat_max_artifact_bytes=5 * 1024 * 1024 * 1024)


def test_training_timeout_is_bounded_by_the_task_limit() -> None:
    with pytest.raises(ValidationError, match="timeout_seconds"):
        _splat(scene_splat_timeout_seconds=30)
    with pytest.raises(ValidationError, match="timeout_seconds"):
        _splat(scene_splat_timeout_seconds=9000, scene_task_time_limit_seconds=8000)
    assert _splat(scene_splat_timeout_seconds=8000, scene_task_time_limit_seconds=8000)


def test_registered_image_floor_is_consistent_with_the_scene_rules() -> None:
    with pytest.raises(ValidationError, match="min_registered_images"):
        _splat(scene_splat_min_registered_images=2)
    with pytest.raises(ValidationError, match="max_scene_images"):
        _splat(max_scene_images=10, scene_splat_min_registered_images=20)


def test_sh_degree_is_bounded() -> None:
    with pytest.raises(ValidationError, match="sh_degree"):
        _splat(scene_splat_sh_degree=4)
    assert _splat(scene_splat_sh_degree=0).scene_splat_sh_degree == 0


def test_device_choices_are_explicit() -> None:
    with pytest.raises(ValidationError, match="device"):
        _splat(scene_splat_device="mps")
    assert _splat(scene_splat_device="CPU").scene_splat_device == "cpu"


def test_worker_queue_must_not_merge_incompatible_workers() -> None:
    for queue in ("object_generation", "scene_reconstruction", "file_cleanup"):
        with pytest.raises(ValidationError, match="queue"):
            _splat(scene_splat_worker_queue=queue)
    with pytest.raises(ValidationError, match="queue"):
        _splat(scene_splat_worker_queue="Scene Splat")
    assert _splat(scene_splat_worker_queue="SCENE_SPLAT_2").scene_splat_worker_queue == (
        "scene_splat_2"
    )


def test_neural_python_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="scene_splat_python"):
        _splat(scene_splat_python="python")
    with pytest.raises(ValidationError, match="scene_splat_python"):
        _splat(scene_splat_site_packages="splat-site")


def test_redacted_settings_expose_the_active_representation_without_secrets() -> None:
    redacted = _splat(scene_splat_worker=True).redacted()
    assert redacted["scene_representation"] == "gaussian_splat"
    assert redacted["scene_splat_enabled"] is True
    assert redacted["scene_splat_worker_queue"] == "scene_gaussian_splat"
    assert redacted["scene_splat_max_vram_mb"] == 9000
    assert redacted["scene_splat_worker"] is True
    assert "scene_splat_python" not in redacted
