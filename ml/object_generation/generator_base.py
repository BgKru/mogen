"""Shared object-generator contract (13_advanced_object_generation.md Section 4.1).

The contract keeps model-specific behaviour behind a small, explicit boundary:
an adapter loads its weights once, turns one prepared photograph into a mesh
(plus any material/texture it produced) and reports what it did. Adapters never
touch storage, the database, Celery progress or cancellation — the existing
pipeline and worker adapter keep those responsibilities.

The pipeline deliberately passes the *prepared PIL image* that the adapter's
``PreprocessingCapabilities`` describe, because that is what the existing
preprocessing step already produces (06_object_generation.md Section 7). Raw
bytes are decoded once by the pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from PIL import Image

# How the pipeline must prepare the source photograph for an adapter.
#   rgb_composite   -> TripoSR: rembg -> crop -> pad -> ratio -> resize -> neutral gray
#   rgba_foreground -> SF3D: rembg -> crop -> pad -> ratio, alpha kept
PreprocessingMode = Literal["rgb_composite", "rgba_foreground"]


@dataclass(frozen=True, slots=True)
class PreprocessingCapabilities:
    """What an adapter expects from the shared preprocessing step.

    The flags prevent double work: an adapter that declares
    ``background_removal=True`` receives an image on which rembg already ran,
    so its own preprocessing must never call rembg again
    (13 Section 5.4).
    """

    mode: PreprocessingMode
    background_removal: bool
    alpha: bool
    foreground_crop: bool
    foreground_ratio: bool
    input_size: int | None
    color_mode: str

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSON-safe capability description recorded in the manifest."""
        return {
            "mode": self.mode,
            "background_removal": self.background_removal,
            "alpha": self.alpha,
            "foreground_crop": self.foreground_crop,
            "foreground_ratio": self.foreground_ratio,
            "input_size": self.input_size,
            "color_mode": self.color_mode,
        }


@dataclass(frozen=True, slots=True)
class GeneratorResult:
    """One normalized generation result plus model identity and measurements."""

    mesh: Any
    name: str
    revision: str
    model_id: str
    model_revision: str
    inference_seconds: float
    postprocessing_seconds: float = 0.0
    peak_cuda_allocated_bytes: int | None = None
    peak_cuda_reserved_bytes: int | None = None
    has_textures: bool = False
    texture_resolution: int | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        """Return the stable ``generator`` metadata block.

        Unavailable measurements are omitted rather than reported as zero
        (13 Section 5.5). Only JSON-safe facts are returned: no local paths,
        tensors, credentials or command lines.
        """
        block: dict[str, Any] = {
            "name": self.name,
            "revision": self.revision,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "inference_seconds": round(self.inference_seconds, 3),
            "postprocessing_seconds": round(self.postprocessing_seconds, 3),
            "has_textures": bool(self.has_textures),
        }
        if self.texture_resolution is not None:
            block["texture_resolution"] = int(self.texture_resolution)
        if self.peak_cuda_allocated_bytes is not None:
            block["peak_cuda_allocated_bytes"] = int(self.peak_cuda_allocated_bytes)
        if self.peak_cuda_reserved_bytes is not None:
            block["peak_cuda_reserved_bytes"] = int(self.peak_cuda_reserved_bytes)
        if self.diagnostics:
            block["diagnostics"] = _json_safe(self.diagnostics)
        return block


@runtime_checkable
class ObjectGenerator(Protocol):
    """A single-image object generator backed by one pinned model."""

    name: str
    revision: str
    model_id: str
    model_revision: str

    def capabilities(self) -> PreprocessingCapabilities:
        """Describe the prepared image this adapter expects."""
        ...

    def load(self) -> None:
        """Load and verify the model once; idempotent for a warm process."""
        ...

    def generate(self, image: Image.Image, *, started_at: float) -> GeneratorResult:
        """Run inference and postprocessing for one prepared photograph."""
        ...

    def unload(self) -> None:
        """Release the model and its device memory."""
        ...


def _json_safe(value: Any) -> Any:
    """Coerce diagnostics to JSON-safe primitives with one level of nesting."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    return str(value)


__all__ = [
    "GeneratorResult",
    "ObjectGenerator",
    "PreprocessingCapabilities",
    "PreprocessingMode",
]
