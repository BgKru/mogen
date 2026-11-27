"""Object generator policy settings (increment 13, 13 Section 6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_triposr_is_the_default_generator_policy() -> None:
    settings = Settings()

    assert settings.object_generator == "triposr"
    assert settings.object_generator_fallback is False
    assert settings.object_sf3d_enabled is False
    # The revision is only required when SF3D is enabled; compose and the env
    # examples supply the pinned value.
    assert settings.object_sf3d_model_revision == ""
    assert settings.object_sf3d_texture_resolution == 1024
    assert settings.object_sf3d_remesh == "none"
    assert settings.object_hunyuan3d_enabled is False


def test_unknown_and_blocked_generators_are_rejected() -> None:
    with pytest.raises(ValidationError, match="object_generator"):
        Settings(object_generator="magic")

    with pytest.raises(ValidationError, match="Hunyuan3D"):
        Settings(object_generator="hunyuan3d")


def test_sf3d_requires_an_explicit_enable_and_pinned_revision() -> None:
    with pytest.raises(ValidationError, match="object_sf3d_enabled"):
        Settings(object_generator="sf3d")

    with pytest.raises(ValidationError, match="immutable revision"):
        Settings(
            object_generator="sf3d",
            object_sf3d_enabled=True,
            object_sf3d_model_revision="main",
        )

    settings = Settings(
        object_generator="sf3d",
        object_sf3d_enabled=True,
        object_sf3d_model_revision="f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778",
    )
    assert settings.object_generator == "sf3d"


@pytest.mark.parametrize(
    "overrides",
    [
        {"object_sf3d_texture_resolution": 64},
        {"object_sf3d_texture_resolution": 8192},
        {"object_sf3d_remesh": "smooth"},
        {"object_sf3d_target_vertex_count": 10},
        {"object_sf3d_model_dir": Path("models/sf3d")},
        {"object_sf3d_manifest_path": Path("manifest.json")},
    ],
)
def test_sf3d_settings_are_validated(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_hunyuan3d_license_gate_is_enforced() -> None:
    base = {
        "object_hunyuan3d_enabled": True,
        "object_hunyuan3d_model_revision": "abc123",
    }

    with pytest.raises(ValidationError, match="licence acknowledgement"):
        Settings(**base)

    with pytest.raises(ValidationError, match="territory"):
        Settings(**base, object_hunyuan3d_license_acknowledged=True)

    with pytest.raises(ValidationError, match="excludes"):
        Settings(
            **base,
            object_hunyuan3d_license_acknowledged=True,
            object_hunyuan3d_territory="DE",
        )

    with pytest.raises(ValidationError, match="texture generation is disabled"):
        Settings(
            **base,
            object_hunyuan3d_license_acknowledged=True,
            object_hunyuan3d_territory="RU",
            object_hunyuan3d_texture_enabled=True,
        )

    with pytest.raises(ValidationError, match="shape generation"):
        Settings(
            **base,
            object_hunyuan3d_license_acknowledged=True,
            object_hunyuan3d_territory="RU",
            object_hunyuan3d_mode="shape_texture",
        )

    # Even a complete, permitted configuration cannot initialise the blocked
    # adapter; the failure is explicit rather than a silent substitution.
    with pytest.raises(ValidationError, match="not available in this build"):
        Settings(
            **base,
            object_hunyuan3d_license_acknowledged=True,
            object_hunyuan3d_territory="RU",
        )


def test_redacted_settings_expose_the_generator_policy_without_paths_leaking_secrets() -> None:
    redacted = Settings().redacted()

    assert redacted["object_generator"] == "triposr"
    assert redacted["object_sf3d_enabled"] is False
    assert redacted["object_hunyuan3d_enabled"] is False
    assert "object_sf3d_model_dir" in redacted
