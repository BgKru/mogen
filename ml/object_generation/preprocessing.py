"""Image preprocessing for TripoSR (06_object_generation.md Section 7).

The implementation mirrors the official ``run.py`` pipeline at the pinned
TripoSR revision:

    decode -> EXIF orientation -> RGB/RGBA -> rembg -> crop foreground ->
    pad square -> pad to ``1 / foreground_ratio`` -> neutral gray composite

The original upload is never modified: the caller passes bytes and receives a
new RGB image plus metrics. Intermediate files are written by the orchestrator
into the task-specific working directory.
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .config import ObjectGenerationConfig
from .exceptions import (
    BACKGROUND_REMOVAL_FAILED,
    IMAGE_DECODE_FAILED,
    IMAGE_PREPROCESSING_FAILED,
    INVALID_FOREGROUND_MASK,
    INVALID_IMAGE_DIMENSIONS,
    ImagePreprocessingError,
)

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = frozenset({"JPEG", "PNG"})
# Official TripoSR composite background (run.py: blend over 0.5 gray).
NEUTRAL_BACKGROUND = 0.5
ALPHA_THRESHOLD = 0

_rembg_lock = threading.Lock()
_rembg_sessions: dict[str, Any] = {}


def get_rembg_session(model: str = "u2net") -> Any:
    """Return a process-wide rembg session (06 Section 7.4).

    The ONNX session is several hundred megabytes and safe to reuse, so it is
    initialized once per worker process instead of once per task.
    """
    with _rembg_lock:
        session = _rembg_sessions.get(model)
        if session is None:
            import rembg

            session = rembg.new_session(model)
            _rembg_sessions[model] = session
        return session


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    """The model input image and the facts observed while preparing it."""

    image: Image.Image
    width: int
    height: int
    source_width: int
    source_height: int
    source_format: str
    foreground_bbox: tuple[int, int, int, int]
    background_removed: bool


def decode_image(data: bytes, *, max_dimension: int = 8192) -> tuple[Image.Image, str]:
    """Decode a JPEG/PNG upload and apply EXIF orientation (06 Section 7.3).

    Only the decoded content is trusted: the container format must be JPEG or
    PNG, the image must actually decode, and its dimensions must be positive
    and within the configured limit.
    """
    if not data:
        raise ImagePreprocessingError(IMAGE_DECODE_FAILED, "The source image is empty.")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image_format = opened.format or ""
            opened.load()
            image = ImageOps.exif_transpose(opened)
    except ImagePreprocessingError:
        raise
    except Exception as exc:  # Pillow raises several unrelated subclasses
        raise ImagePreprocessingError(
            IMAGE_DECODE_FAILED, "The source image could not be decoded."
        ) from exc

    if image_format not in SUPPORTED_FORMATS:
        raise ImagePreprocessingError(
            IMAGE_DECODE_FAILED, "Only JPEG and PNG photographs are supported."
        )
    if image.width < 1 or image.height < 1:
        raise ImagePreprocessingError(
            INVALID_IMAGE_DIMENSIONS, "The source image has invalid dimensions."
        )
    if max(image.size) > max_dimension:
        raise ImagePreprocessingError(
            INVALID_IMAGE_DIMENSIONS,
            f"The source image exceeds the maximum dimension of {max_dimension} px.",
        )

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    return image, image_format


def _has_transparency(image: Image.Image) -> bool:
    """Return whether an RGBA image already carries a meaningful alpha mask."""
    if image.mode != "RGBA":
        return False
    alpha = np.asarray(image.getchannel("A"))
    return bool(alpha.min() < 255)


def remove_background(image: Image.Image, session: Any) -> Image.Image:
    """Run rembg and return an RGBA image with a non-empty alpha mask.

    A source PNG that already has transparency is respected, matching the
    official ``remove_background`` helper. An all-transparent result is
    rejected instead of feeding an empty foreground to the model.
    """
    if _has_transparency(image):
        return image.convert("RGBA")

    try:
        import rembg

        result = rembg.remove(image.convert("RGB"), session=session)
    except Exception as exc:
        raise ImagePreprocessingError(
            BACKGROUND_REMOVAL_FAILED, "Background removal failed."
        ) from exc

    result = result.convert("RGBA")
    alpha = np.asarray(result.getchannel("A"))
    if alpha.size == 0 or not np.any(alpha > ALPHA_THRESHOLD):
        raise ImagePreprocessingError(
            INVALID_FOREGROUND_MASK, "The background-removal mask is empty."
        )
    return result


def foreground_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """Return the inclusive-exclusive bounding box of non-transparent pixels."""
    alpha = np.asarray(image.convert("RGBA").getchannel("A"))
    rows, columns = np.where(alpha > ALPHA_THRESHOLD)
    if rows.size == 0:
        raise ImagePreprocessingError(
            INVALID_FOREGROUND_MASK, "The image contains no foreground object."
        )
    return int(columns.min()), int(rows.min()), int(columns.max()) + 1, int(rows.max()) + 1


def crop_foreground(image: Image.Image) -> Image.Image:
    """Crop to the foreground bounding box, preserving the alpha channel."""
    left, top, right, bottom = foreground_bbox(image)
    cropped = image.crop((left, top, right, bottom))
    if cropped.width < 1 or cropped.height < 1:
        raise ImagePreprocessingError(
            INVALID_FOREGROUND_MASK, "The foreground has invalid dimensions."
        )
    return cropped


def pad_to_square(image: Image.Image) -> Image.Image:
    """Centre a transparent image on a transparent square canvas."""
    size = max(image.width, image.height)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def apply_foreground_ratio(image: Image.Image, ratio: float) -> Image.Image:
    """Pad the square so the foreground occupies ``ratio`` of the final edge.

    This reproduces TripoSR's ``resize_foreground``: a foreground of size ``s``
    becomes an image of edge ``int(s / ratio)`` before the model's own 512 px
    normalization.
    """
    if not 0 < ratio <= 1:
        raise ImagePreprocessingError(
            IMAGE_PREPROCESSING_FAILED, "foreground_ratio must be in (0, 1]."
        )
    target = max(image.width, int(round(image.width / ratio)))
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    offset = ((target - image.width) // 2, (target - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


def composite_neutral_background(image: Image.Image) -> Image.Image:
    """Blend RGBA over the official neutral gray (0.5) background."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    alpha = rgba[:, :, 3:4]
    rgb = rgba[:, :, :3] * alpha + (1.0 - alpha) * NEUTRAL_BACKGROUND
    return Image.fromarray(np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="RGB")


def prepare_model_input(
    image: Image.Image,
    *,
    config: ObjectGenerationConfig,
    session: Any,
    source_format: str = "",
) -> PreprocessResult:
    """Run the full preprocessing pipeline and return a 512 px model input."""
    source_width, source_height = image.size
    background_removed = config.remove_background

    rgba = remove_background(image, session) if config.remove_background else image.convert("RGBA")

    bbox = foreground_bbox(rgba)
    cropped = crop_foreground(rgba)
    padded = pad_to_square(cropped)
    padded = apply_foreground_ratio(padded, config.foreground_ratio)
    # Normalize to the model's conditioning size once, with a high-quality
    # filter, instead of letting each inference resize a large array.
    resized = padded.resize((config.input_size, config.input_size), Image.Resampling.LANCZOS)
    model_input = composite_neutral_background(resized)

    return PreprocessResult(
        image=model_input,
        width=model_input.width,
        height=model_input.height,
        source_width=source_width,
        source_height=source_height,
        source_format=source_format,
        foreground_bbox=bbox,
        background_removed=background_removed,
    )


def save_intermediates(
    *, work_dir: Path, original_bytes: bytes, result: PreprocessResult, suffix: str
) -> Path:
    """Persist the untouched original and the preprocessed model input.

    The original is a byte-for-byte copy of the upload; preprocessing never
    rewrites it (OBJ-AC-05). The processed PNG is kept for diagnostics.
    """
    input_dir = work_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    original_path = input_dir / f"original{suffix}"
    original_path.write_bytes(original_bytes)
    processed_path = input_dir / "preprocessed.png"
    result.image.save(processed_path, format="PNG")
    return processed_path
