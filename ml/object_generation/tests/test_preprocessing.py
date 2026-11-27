"""Preprocessing unit tests (06_object_generation.md Sections 7 and 17.1)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from object_generation.config import ObjectGenerationConfig
from object_generation.exceptions import ImagePreprocessingError
from object_generation.preprocessing import (
    apply_foreground_ratio,
    composite_neutral_background,
    crop_foreground,
    decode_image,
    foreground_bbox,
    pad_to_square,
    prepare_model_input,
    remove_background,
    save_intermediates,
)


def _config(tmp_path: Path, **overrides) -> ObjectGenerationConfig:
    values = {
        "model_dir": tmp_path / "model",
        "model_revision": "test",
        "model_sha256": "",
        "remove_background": False,
    }
    values.update(overrides)
    return ObjectGenerationConfig(**values)


def _encode(image: Image.Image, fmt: str, **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def test_decode_applies_exif_orientation() -> None:
    source = Image.new("RGB", (40, 20), color=(10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise on display
    data = _encode(source, "JPEG", exif=exif)

    image, image_format = decode_image(data)

    assert image_format == "JPEG"
    assert image.size == (20, 40)
    assert image.mode == "RGB"


def test_decode_preserves_png_alpha() -> None:
    source = Image.new("RGBA", (8, 8), color=(1, 2, 3, 0))
    image, image_format = decode_image(_encode(source, "PNG"))

    assert image_format == "PNG"
    assert image.mode == "RGBA"


def test_decode_rejects_empty_corrupt_and_unsupported_content() -> None:
    with pytest.raises(ImagePreprocessingError) as empty:
        decode_image(b"")
    assert empty.value.error_code == "IMAGE_DECODE_FAILED"

    with pytest.raises(ImagePreprocessingError) as corrupt:
        decode_image(b"not an image")
    assert corrupt.value.error_code == "IMAGE_DECODE_FAILED"

    gif = _encode(Image.new("RGB", (8, 8)), "GIF")
    with pytest.raises(ImagePreprocessingError) as unsupported:
        decode_image(gif)
    assert unsupported.value.error_code == "IMAGE_DECODE_FAILED"


def test_decode_rejects_oversized_images() -> None:
    data = _encode(Image.new("RGB", (12, 4)), "PNG")

    with pytest.raises(ImagePreprocessingError) as excinfo:
        decode_image(data, max_dimension=8)

    assert excinfo.value.error_code == "INVALID_IMAGE_DIMENSIONS"


def test_background_removal_returns_rgba(monkeypatch) -> None:
    import rembg

    source = Image.new("RGB", (10, 10), color=(50, 60, 70))
    expected = Image.new("RGBA", (10, 10), color=(50, 60, 70, 255))
    expected.putpixel((0, 0), (0, 0, 0, 0))

    monkeypatch.setattr(rembg, "remove", lambda image, session=None: expected)
    result = remove_background(source, session=object())

    assert result.mode == "RGBA"
    # Only (0, 0) is transparent; the rest of row 0 and column 0 are opaque, so
    # the inclusive-exclusive bounding box starts at the image origin.
    assert foreground_bbox(result) == (0, 0, 10, 10)


def test_background_removal_rejects_an_empty_mask(monkeypatch) -> None:
    import rembg

    source = Image.new("RGB", (10, 10), color=(50, 60, 70))
    empty = Image.new("RGBA", (10, 10), color=(0, 0, 0, 0))
    monkeypatch.setattr(rembg, "remove", lambda image, session=None: empty)

    with pytest.raises(ImagePreprocessingError) as excinfo:
        remove_background(source, session=object())

    assert excinfo.value.error_code == "INVALID_FOREGROUND_MASK"


def test_background_removal_failure_is_mapped(monkeypatch) -> None:
    import rembg

    def _boom(*_args, **_kwargs):
        raise RuntimeError("onnx failure")

    monkeypatch.setattr(rembg, "remove", _boom)

    with pytest.raises(ImagePreprocessingError) as excinfo:
        remove_background(Image.new("RGB", (10, 10)), session=object())

    assert excinfo.value.error_code == "BACKGROUND_REMOVAL_FAILED"


def test_foreground_bbox_crop_and_square_padding() -> None:
    image = Image.new("RGBA", (10, 10), color=(0, 0, 0, 0))
    for x in range(2, 8):
        for y in range(3, 9):
            image.putpixel((x, y), (255, 0, 0, 255))

    assert foreground_bbox(image) == (2, 3, 8, 9)
    cropped = crop_foreground(image)
    assert cropped.size == (6, 6)
    padded = pad_to_square(Image.new("RGBA", (4, 8), color=(1, 1, 1, 255)))
    assert padded.size == (8, 8)


def test_foreground_ratio_pads_without_distorting() -> None:
    image = Image.new("RGBA", (100, 100), color=(0, 0, 0, 0))
    for x in range(100):
        for y in range(50):
            image.putpixel((x, y), (255, 0, 0, 255))
    cropped = crop_foreground(image)  # 100 x 50
    square = pad_to_square(cropped)  # 100 x 100
    result = apply_foreground_ratio(square, 0.85)

    assert result.size == (118, 118)
    # The foreground remains 100 px in a 118 px canvas, centred.
    assert result.getchannel("A").getbbox() is not None


def test_composite_uses_the_official_neutral_background() -> None:
    image = Image.new("RGBA", (2, 1), color=(255, 0, 0, 255))
    image.putpixel((1, 0), (255, 0, 0, 0))

    result = composite_neutral_background(image)

    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 0, 0)
    assert result.getpixel((1, 0)) == (128, 128, 128)


def test_prepare_model_input_produces_a_512_px_neutral_composite(tmp_path: Path) -> None:
    image = Image.new("RGBA", (200, 200), color=(0, 0, 0, 0))
    for x in range(50, 150):
        for y in range(75, 125):
            image.putpixel((x, y), (200, 30, 30, 255))

    result = prepare_model_input(image, config=_config(tmp_path), session=None, source_format="PNG")

    assert result.image.size == (512, 512)
    assert result.image.mode == "RGB"
    pixels = np.asarray(result.image)
    non_gray = np.any(np.abs(pixels.astype(int) - 128) > 8, axis=2)
    columns = np.where(non_gray.any(axis=0))[0]
    rows = np.where(non_gray.any(axis=1))[0]
    # 100 px foreground in a 118 px canvas -> ~434 px in the 512 px model input.
    assert 425 <= columns.max() - columns.min() + 1 <= 445
    assert 205 <= rows.max() - rows.min() + 1 <= 225
    assert result.source_format == "PNG"
    assert result.foreground_bbox == (50, 75, 150, 125)


def test_save_intermediates_preserves_the_original_bytes(tmp_path: Path) -> None:
    original = b"\xff\xd8original-jpeg-bytes\xff\xd9"
    result = prepare_model_input(
        Image.new("RGBA", (32, 32), color=(10, 10, 10, 255)),
        config=_config(tmp_path),
        session=None,
    )

    processed = save_intermediates(
        work_dir=tmp_path / "task",
        original_bytes=original,
        result=result,
        suffix=".jpg",
    )

    assert (tmp_path / "task" / "input" / "original.jpg").read_bytes() == original
    assert processed.name == "preprocessed.png"
    assert processed.is_file()
