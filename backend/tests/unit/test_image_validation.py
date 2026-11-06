"""Unit tests for image validation helpers (no database required).

Traceability: BE-AC-09, BE-AC-10 (validation), API-AC-16 (no exposed paths),
09_testing.md Section 7.4, TEST-AC-02.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.exceptions import AppError
from app.services.image_service import clean_filename, content_disposition, validate_image_bytes

pytestmark = pytest.mark.unit


def _image_bytes(*, image_format: str = "JPEG", size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(12, 34, 56)).save(buffer, format=image_format)
    return buffer.getvalue()


def _validate(
    data: bytes,
    *,
    filename: str = "photo.jpg",
    content_type: str | None = "image/jpeg",
    max_dimension: int = 8192,
):
    return validate_image_bytes(
        data=data,
        filename=filename,
        declared_content_type=content_type,
        max_dimension=max_dimension,
    )


@pytest.mark.parametrize(
    ("filename", "image_format", "content_type", "mime_type", "extension"),
    [
        ("photo.jpg", "JPEG", "image/jpeg", "image/jpeg", "jpg"),
        ("photo.jpeg", "JPEG", "image/jpeg", "image/jpeg", "jpg"),
        ("photo.PNG", "PNG", "image/png", "image/png", "png"),
    ],
)
def test_valid_images_are_accepted(
    filename: str,
    image_format: str,
    content_type: str,
    mime_type: str,
    extension: str,
) -> None:
    validated = _validate(
        _image_bytes(image_format=image_format),
        filename=filename,
        content_type=content_type,
    )

    assert validated.mime_type == mime_type
    assert validated.extension == extension
    assert (validated.width, validated.height) == (8, 8)


def test_unsupported_extension_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(_image_bytes(image_format="PNG"), filename="photo.gif", content_type="image/png")

    assert exc_info.value.status_code == 415
    assert exc_info.value.code == "INVALID_IMAGE_FORMAT"


def test_missing_extension_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(_image_bytes(), filename="photo", content_type="image/jpeg")

    assert exc_info.value.status_code == 415


def test_unsupported_declared_content_type_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(_image_bytes(), content_type="text/plain")

    assert exc_info.value.status_code == 415
    assert exc_info.value.code == "INVALID_IMAGE_FORMAT"


def test_actual_format_must_match_the_extension() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(
            _image_bytes(image_format="PNG"),
            filename="photo.jpg",
            content_type="image/jpeg",
        )

    assert exc_info.value.status_code == 415


def test_actual_format_must_match_the_declared_type() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(
            _image_bytes(image_format="PNG"),
            filename="photo.png",
            content_type="image/jpeg",
        )

    assert exc_info.value.status_code == 415


def test_corrupt_content_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(b"this is not an image")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_IMAGE_CONTENT"


def test_empty_content_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(b"")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_IMAGE_CONTENT"


def test_image_at_the_dimension_limit_is_accepted() -> None:
    validated = _validate(_image_bytes(size=(8, 8)), max_dimension=8)

    assert (validated.width, validated.height) == (8, 8)


def test_decompression_bomb_is_reported_as_dimensions_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_open(*args: object, **kwargs: object) -> None:
        raise Image.DecompressionBombError("image is too large")

    monkeypatch.setattr(Image, "open", failing_open)

    with pytest.raises(AppError) as exc_info:
        _validate(_image_bytes())

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "IMAGE_DIMENSIONS_EXCEEDED"


@pytest.mark.parametrize("size", [(9, 8), (8, 9), (100, 200)])
def test_images_above_the_dimension_limit_are_rejected(size: tuple[int, int]) -> None:
    with pytest.raises(AppError) as exc_info:
        _validate(_image_bytes(size=size), max_dimension=8)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "IMAGE_DIMENSIONS_EXCEEDED"


def test_clean_filename_keeps_only_the_base_name() -> None:
    assert clean_filename("C:\\fakepath\\photo.jpg") == "photo.jpg"
    assert clean_filename("../../etc/photo.jpg") == "photo.jpg"
    assert clean_filename("photo.jpg") == "photo.jpg"


def test_clean_filename_bounds_the_length() -> None:
    cleaned = clean_filename("a" * 400 + ".jpg")

    assert len(cleaned) == 255
    assert cleaned.endswith(".jpg")


# --- Content-Disposition (api_contracts 8.3) ------------------------------


def test_content_disposition_uses_the_stored_name() -> None:
    assert content_disposition("photo.jpg") == 'inline; filename="photo.jpg"'


def test_content_disposition_reduces_paths_to_the_base_name() -> None:
    assert content_disposition("../../etc/photo.jpg") == 'inline; filename="photo.jpg"'


def test_content_disposition_replaces_quotes() -> None:
    disposition = content_disposition('ph"oto.jpg')

    # The quoted fallback is sanitised; the encoded original stays available.
    assert disposition == ("inline; filename=\"ph_oto.jpg\"; filename*=UTF-8''ph%22oto.jpg")
    assert disposition.count('"') == 2


@pytest.mark.parametrize(
    "filename",
    ["evil\r\nX-Injected: yes.jpg", "tab\tname.jpg", "null\x00name.jpg"],
)
def test_content_disposition_cannot_inject_a_header(filename: str) -> None:
    disposition = content_disposition(filename)

    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "\x00" not in disposition
    assert "\t" not in disposition
    assert disposition.startswith("inline; filename=")


def test_content_disposition_falls_back_for_an_unusable_name() -> None:
    assert content_disposition("") == 'inline; filename="image"'
    assert content_disposition("   ") == 'inline; filename="image"'


def test_content_disposition_keeps_a_non_ascii_name_in_filename_star() -> None:
    disposition = content_disposition("селфи.jpg")

    assert disposition.startswith('inline; filename="')
    assert ".jpg" in disposition
    assert "filename*=UTF-8''%D1%81%D0%B5%D0%BB%D1%84%D0%B8.jpg" in disposition
    # The header itself stays ASCII, so it cannot break the HTTP framing.
    assert disposition.isascii() is True
