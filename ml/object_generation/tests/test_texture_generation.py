"""AI texture backend boundary tests (14 Section 5.6)."""

from __future__ import annotations

import pytest
from PIL import Image

from object_generation.texture_generation import (
    AI_TEXTURE_DISABLED,
    AI_TEXTURE_INVALID_OUTPUT,
    AI_TEXTURE_UNAVAILABLE,
    DisabledTextureBackend,
    GeneratedTexture,
    TextureGenerationError,
    TextureGenerationRequest,
    create_texture_backend,
    validate_generated_texture,
)


def test_the_only_shipped_backend_is_explicitly_disabled() -> None:
    backend = create_texture_backend()
    assert isinstance(backend, DisabledTextureBackend)
    assert backend.available() is False
    assert backend.as_metadata() == {
        "backend": "disabled",
        "version": "0",
        "available": False,
        "reason": AI_TEXTURE_DISABLED,
    }


def test_the_disabled_backend_never_generates() -> None:
    with pytest.raises(TextureGenerationError) as excinfo:
        DisabledTextureBackend().generate(None, TextureGenerationRequest(resolution=1024))
    assert excinfo.value.error_code == AI_TEXTURE_UNAVAILABLE


def test_an_unknown_backend_is_rejected_without_importing_it() -> None:
    with pytest.raises(TextureGenerationError) as excinfo:
        create_texture_backend("some-unverified-model")
    assert excinfo.value.error_code == AI_TEXTURE_UNAVAILABLE


def test_a_valid_generated_texture_passes_the_output_boundary() -> None:
    texture = GeneratedTexture(
        image=Image.new("RGB", (128, 128), (10, 20, 30)),
        uv_layout="generated-atlas",
        material_slot="baseColorTexture",
    )

    validated = validate_generated_texture(texture, resolution=256, uv_count=100)

    assert validated is texture


@pytest.mark.parametrize(
    ("texture", "resolution", "uv_count"),
    [
        (GeneratedTexture(Image.new("L", (128, 128)), "atlas"), 256, 10),
        (GeneratedTexture(Image.new("RGB", (512, 512)), "atlas"), 256, 10),
        (GeneratedTexture(Image.new("RGB", (128, 128)), "atlas", "normalTexture"), 256, 10),
        (GeneratedTexture(Image.new("RGB", (128, 128)), "atlas"), 256, 0),
    ],
)
def test_invalid_generated_textures_are_rejected(texture, resolution, uv_count) -> None:
    with pytest.raises(TextureGenerationError) as excinfo:
        validate_generated_texture(texture, resolution=resolution, uv_count=uv_count)
    assert excinfo.value.error_code == AI_TEXTURE_INVALID_OUTPUT


def test_a_non_rgb_texture_is_rejected() -> None:
    texture = GeneratedTexture(image=Image.new("F", (8, 8)), uv_layout="atlas")
    with pytest.raises(TextureGenerationError) as excinfo:
        validate_generated_texture(texture, resolution=64, uv_count=4)
    assert excinfo.value.error_code == AI_TEXTURE_INVALID_OUTPUT
