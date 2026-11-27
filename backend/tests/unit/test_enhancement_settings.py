"""Mesh/texture enhancement settings (14 Section 6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_enhancement_defaults_are_conservative() -> None:
    settings = Settings()

    assert settings.object_mesh_cleanup_enabled is True
    assert settings.object_mesh_normals_enabled is True
    assert settings.object_mesh_remove_small_components is False
    assert settings.object_mesh_simplification_enabled is False
    assert settings.object_mesh_target_faces == 0
    assert settings.object_generate_uv is False
    assert settings.object_bake_texture is False
    assert settings.object_ai_texture_enabled is False
    assert settings.scene_mesh_postprocess_enabled is False
    assert settings.scene_mesh_simplification_enabled is False
    assert settings.scene_generate_uv is False
    assert settings.scene_ai_texture_enabled is False
    assert settings.enhancement_fallback_to_original is True
    assert settings.texture_enhancement_device == "cpu"


def test_texture_baking_is_no_longer_rejected() -> None:
    settings = Settings(object_bake_texture=True, object_texture_resolution=1024)

    assert settings.object_bake_texture is True
    assert settings.redacted()["object_bake_texture"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"object_mesh_merge_tolerance": -0.1},
        {"object_mesh_target_faces": -1},
        {"object_mesh_simplification_enabled": True, "object_mesh_target_faces": 0},
        {"object_mesh_max_deviation": 0.0},
        {"object_mesh_smoothing_iterations": 1},
        {"object_uv_resolution": 32},
        {"object_texture_resolution": 8192},
        {"object_uv_padding": 65},
        {"object_ai_texture_enabled": True},
        {"object_ai_texture_backend": "other"},
        {"scene_mesh_target_faces": -1},
        {"scene_mesh_simplification_enabled": True, "scene_mesh_target_faces": 0},
        {"scene_mesh_max_deviation": 0.0},
        {"scene_generate_uv": True},
        {"scene_ai_texture_enabled": True},
        {"texture_enhancement_device": "cuda:0"},
        {"mesh_enhancement_max_memory_mb": 128},
        {"object_bake_texture": True, "object_ai_texture_enabled": True},
    ],
)
def test_invalid_enhancement_settings_are_rejected(overrides) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_enhancement_settings_are_redacted_safely() -> None:
    settings = Settings(object_mesh_target_faces=1000, scene_mesh_target_faces=5000)
    redacted = settings.redacted()

    assert redacted["object_mesh_target_faces"] == 1000
    assert redacted["scene_mesh_target_faces"] == 5000
    assert redacted["mesh_enhancement_max_memory_mb"] == 8192
    assert "object_ai_texture_backend" in redacted
