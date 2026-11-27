"""Optional AI texture backend boundary (14 Section 5.6).

No AI texture model is selected or pinned in this delivery: the licence,
commercial-use, Python/CUDA compatibility, cache, VRAM and quality review has
not been completed, so the backend is explicitly disabled. The protocol and the
output validation boundary are implemented so a future verified model can be
added without changing the pipeline contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
import trimesh
from PIL import Image

AI_TEXTURE_DISABLED = "AI_TEXTURE_DISABLED"
AI_TEXTURE_UNAVAILABLE = "AI_TEXTURE_UNAVAILABLE"
AI_TEXTURE_INVALID_OUTPUT = "AI_TEXTURE_INVALID_OUTPUT"


class TextureGenerationError(Exception):
    """Stable error raised by an AI texture backend."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class TextureGenerationRequest:
    """Bounded inputs a backend may consume; never contains a storage path."""

    resolution: int
    prompt: str | None = None
    seed: int = 0
    texture_id: str = ""


@dataclass(frozen=True, slots=True)
class GeneratedTexture:
    """A validated texture map tied to the exact existing UV layout."""

    image: Image.Image
    uv_layout: str
    material_slot: str = "baseColorTexture"
    warnings: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class TextureGenerationBackend(Protocol):
    """Protocol implemented by a verified AI texture backend."""

    name: str
    version: str

    def available(self) -> bool: ...

    def generate(
        self,
        mesh: trimesh.Trimesh,
        request: TextureGenerationRequest,
        *,
        on_poll: Callable[[], None] | None = None,
    ) -> GeneratedTexture: ...


class DisabledTextureBackend:
    """The only backend shipped: explicit, lazy and unavailable."""

    name = "disabled"
    version = "0"
    reason = AI_TEXTURE_DISABLED

    def available(self) -> bool:
        return False

    def generate(
        self,
        mesh: trimesh.Trimesh,
        request: TextureGenerationRequest,
        *,
        on_poll: Callable[[], None] | None = None,
    ) -> GeneratedTexture:
        del mesh, request, on_poll
        raise TextureGenerationError(
            AI_TEXTURE_UNAVAILABLE,
            "No compliant AI texture model is installed in this build.",
        )

    def as_metadata(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "version": self.version,
            "available": False,
            "reason": self.reason,
        }


def create_texture_backend(name: str = "disabled") -> TextureGenerationBackend:
    """Return the configured backend; only the disabled backend exists."""
    normalized = (name or "disabled").strip().lower()
    if normalized != "disabled":
        raise TextureGenerationError(
            AI_TEXTURE_UNAVAILABLE,
            f"AI texture backend {name!r} is not installed; only 'disabled' is available.",
        )
    return DisabledTextureBackend()


def validate_generated_texture(
    texture: GeneratedTexture,
    *,
    resolution: int,
    uv_count: int,
) -> GeneratedTexture:
    """Validate dimensions, channels, finite values and material assignment."""
    image = texture.image
    if not isinstance(image, Image.Image):
        raise TextureGenerationError(AI_TEXTURE_INVALID_OUTPUT, "The texture is not an image.")
    if image.width < 1 or image.height < 1:
        raise TextureGenerationError(AI_TEXTURE_INVALID_OUTPUT, "The texture is empty.")
    if image.width > resolution or image.height > resolution:
        raise TextureGenerationError(
            AI_TEXTURE_INVALID_OUTPUT, "The texture exceeds the configured resolution."
        )
    if image.mode not in {"RGB", "RGBA"}:
        raise TextureGenerationError(AI_TEXTURE_INVALID_OUTPUT, "The texture must be RGB or RGBA.")
    values = np.asarray(image)
    if not np.isfinite(values.astype(np.float64)).all():
        raise TextureGenerationError(
            AI_TEXTURE_INVALID_OUTPUT, "The texture contains non-finite values."
        )
    if texture.material_slot != "baseColorTexture":
        raise TextureGenerationError(
            AI_TEXTURE_INVALID_OUTPUT,
            "AI textures may only fill baseColorTexture in this delivery.",
        )
    if uv_count < 1:
        raise TextureGenerationError(
            AI_TEXTURE_INVALID_OUTPUT, "The mesh has no UV layout for the texture."
        )
    return texture


__all__ = [
    "AI_TEXTURE_DISABLED",
    "AI_TEXTURE_INVALID_OUTPUT",
    "AI_TEXTURE_UNAVAILABLE",
    "DisabledTextureBackend",
    "GeneratedTexture",
    "TextureGenerationBackend",
    "TextureGenerationError",
    "TextureGenerationRequest",
    "create_texture_backend",
    "validate_generated_texture",
]
