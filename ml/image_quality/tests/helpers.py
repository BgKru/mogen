"""Synthetic fixtures for the image-quality unit tests.

Everything is generated with NumPy/Pillow, so the suite is deterministic and
needs no downloaded dataset (11 Section 10.2).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter

from image_quality import ImageQualityConfig


def gradient(size: tuple[int, int] = (512, 512), low: int = 12, high: int = 240) -> Image.Image:
    """Return a smooth, deterministic luminance ramp with mild vertical falloff."""
    width, height = size
    rows = np.linspace(0.0, 1.0, height)[:, None]
    columns = np.linspace(low, high, width)[None, :]
    array = np.clip(columns * (1.0 - 0.25 * rows), 0, 255)
    return Image.fromarray(np.repeat(array[:, :, None], 3, axis=2).astype(np.uint8), mode="RGB")


def sharp_texture(size: tuple[int, int] = (512, 512), seed: int = 7) -> Image.Image:
    """Return a sharp image with strong fine edges (high Laplacian variance)."""
    width, height = size
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 200, size=(height, width, 3), dtype=np.uint8)
    x = np.arange(width)[None, :]
    y = np.arange(height)[:, None]
    stripes = (((x // 3) + (y // 3)) % 2) * 70 - 35
    array = np.clip(base.astype(np.int16) + stripes[:, :, None], 0, 255).astype(np.uint8)
    return Image.fromarray(array, mode="RGB")


def blurred(image: Image.Image, radius: float = 8.0) -> Image.Image:
    """Return a heavily blurred copy, as produced by motion blur or missed focus."""
    return image.filter(ImageFilter.GaussianBlur(radius))


def flat(value: int, size: tuple[int, int] = (512, 512)) -> Image.Image:
    """Return a uniform gray image."""
    return Image.new("RGB", size, color=(value, value, value))


def low_contrast(size: tuple[int, int] = (512, 512)) -> Image.Image:
    """Return a narrow tonal range (roughly 118-132 of 255)."""
    width, height = size
    ramp = np.linspace(118, 132, width)[None, :]
    array = np.repeat(ramp, height, axis=0)
    return Image.fromarray(np.repeat(array[:, :, None], 3, axis=2).astype(np.uint8), mode="RGB")


def clipped(
    *, black_fraction: float = 0.5, white_fraction: float = 0.0, size: tuple[int, int] = (512, 512)
) -> Image.Image:
    """Return an image with a chosen fraction of pure-black or pure-white pixels."""
    width, height = size
    array = np.full((height, width, 3), 128, dtype=np.uint8)
    rows = int(round(height * black_fraction))
    array[:rows] = 0
    white_rows = int(round(height * white_fraction))
    if white_rows:
        array[height - white_rows :] = 255
    return Image.fromarray(array, mode="RGB")


def noisy(size: tuple[int, int] = (512, 512), sigma: float = 40.0, seed: int = 11) -> Image.Image:
    """Return a smooth gradient plus strong per-pixel noise."""
    base = np.asarray(gradient(size), dtype=np.float64)
    rng = np.random.default_rng(seed)
    array = np.clip(base + rng.normal(0.0, sigma, size=base.shape), 0, 255)
    return Image.fromarray(array.astype(np.uint8), mode="RGB")


def coarse_texture(size: tuple[int, int] = (512, 512), block: int = 48) -> Image.Image:
    """Return a clean, coarse texture without pixel-level noise."""
    width, height = size
    x = np.arange(width)[None, :]
    y = np.arange(height)[:, None]
    checker = (((x // block) + (y // block)) % 2) * 110 + 70
    array = np.repeat(checker[:, :, None], 3, axis=2).astype(np.uint8)
    return Image.fromarray(array, mode="RGB")


def encode(image: Image.Image, *, fmt: str = "JPEG", quality: int = 90) -> bytes:
    """Encode an image to bytes, so near-duplicate tests use real containers."""
    buffer = io.BytesIO()
    if fmt.upper() == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


def config(**overrides: object) -> ImageQualityConfig:
    """Return a test configuration without the production resolution floor."""
    defaults: dict[str, object] = {"min_short_edge": 64}
    defaults.update(overrides)
    return ImageQualityConfig(**defaults)  # type: ignore[arg-type]
