"""Perceptual near-duplicate candidates: bounded, advisory, never destructive."""

from __future__ import annotations

from PIL import Image

from image_quality import (
    EXACT_DUPLICATE,
    POSSIBLE_NEAR_DUPLICATE,
    QualityInput,
    analyze_images,
)

from .helpers import (
    coarse_texture,
    config,
    encode,
    flat,
    gradient,
    noisy,
    sharp_texture,
)


def _decode(data: bytes) -> Image.Image:
    import io

    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        return opened.convert("RGB")


def _report(result, image_id: str):
    return next(report for report in result.reports if report.image_id == image_id)


def test_resized_and_recompressed_copy_is_a_candidate() -> None:
    base = sharp_texture()
    resized = _decode(encode(base.resize((384, 384)), quality=60))
    result = analyze_images(
        [
            QualityInput(base, image_id="a", filename="a.jpg"),
            QualityInput(resized, image_id="b", filename="b.jpg"),
        ],
        config=config(),
    )

    assert result.near_duplicates is not None
    assert result.near_duplicates.images_compared == 2
    assert len(result.near_duplicates.pairs) == 1
    pair = result.near_duplicates.pairs[0]
    assert pair.hash_distance <= config().hash_distance_threshold
    assert pair.ssim is not None and pair.ssim >= 0.9
    assert POSSIBLE_NEAR_DUPLICATE in _report(result, "a").finding_codes
    assert POSSIBLE_NEAR_DUPLICATE in _report(result, "b").finding_codes


def test_identical_pixels_are_possible_near_duplicates_not_exact_duplicates() -> None:
    # Byte-identical files never reach the analyzer: the scene dataset rejects
    # them with DUPLICATE_IMAGES through its SHA-256 check (07 Section 4.5).
    # A different container with identical pixels is a *candidate*, not proof.
    base = sharp_texture()
    png = _decode(encode(base, fmt="PNG"))
    jpeg = _decode(encode(base, quality=95))
    result = analyze_images(
        [
            QualityInput(png, image_id="png", filename="a.png"),
            QualityInput(jpeg, image_id="jpeg", filename="b.jpg"),
        ],
        config=config(),
    )

    codes = {code for report in result.reports for code in report.finding_codes}
    assert POSSIBLE_NEAR_DUPLICATE in codes
    assert EXACT_DUPLICATE not in codes
    document = result.as_dict()
    assert document["duplicate_codes"]["exact"] == EXACT_DUPLICATE
    assert document["duplicate_codes"]["near"] == POSSIBLE_NEAR_DUPLICATE
    assert document["duplicate_codes"]["exact_detector"] == "sha256"


def test_unrelated_photographs_are_not_grouped() -> None:
    result = analyze_images(
        [
            QualityInput(gradient(), image_id="gradient", filename="gradient.jpg"),
            QualityInput(coarse_texture(), image_id="texture", filename="texture.jpg"),
            QualityInput(noisy(), image_id="noise", filename="noise.jpg"),
        ],
        config=config(),
    )

    assert result.near_duplicates is not None
    assert result.near_duplicates.pairs == ()
    assert result.near_duplicates.clusters == ()
    assert all(POSSIBLE_NEAR_DUPLICATE not in report.finding_codes for report in result.reports)


def test_ssim_confirmation_filters_a_degenerate_hash_match() -> None:
    black = QualityInput(flat(0), image_id="black", filename="black.jpg")
    white = QualityInput(flat(255), image_id="white", filename="white.jpg")

    confirmed = analyze_images([black, white], config=config())
    unconfirmed = analyze_images([black, white], config=config(ssim_threshold=None))

    assert confirmed.near_duplicates is not None
    assert unconfirmed.near_duplicates is not None
    assert unconfirmed.near_duplicates.ssim_applied is False
    assert confirmed.near_duplicates.ssim_applied is True
    # Both flat images share the same hash, but SSIM rejects the pair.
    assert confirmed.near_duplicates.pairs == ()
    assert len(unconfirmed.near_duplicates.pairs) == 1


def test_candidates_are_advisory_and_never_remove_images() -> None:
    base = sharp_texture()
    items = [
        QualityInput(base, image_id="a", filename="a.jpg"),
        QualityInput(base.resize((400, 400)), image_id="b", filename="b.jpg"),
        QualityInput(gradient(), image_id="c", filename="c.jpg"),
    ]
    result = analyze_images(items, config=config())

    assert len(result.reports) == 3
    for report in result.reports:
        for finding in report.findings:
            assert finding.severity == "WARNING"
            if finding.code == POSSIBLE_NEAR_DUPLICATE:
                assert finding.recommendation is not None
                assert "never rejected automatically" in finding.recommendation.lower()


def test_near_duplicate_detection_can_be_disabled() -> None:
    base = sharp_texture()
    result = analyze_images(
        [
            QualityInput(base, image_id="a", filename="a.jpg"),
            QualityInput(base.resize((400, 400)), image_id="b", filename="b.jpg"),
        ],
        config=config(near_duplicate_enabled=False),
    )

    assert result.near_duplicates is None
    assert all(POSSIBLE_NEAR_DUPLICATE not in report.finding_codes for report in result.reports)


def test_comparison_is_bounded_by_the_configured_maximum() -> None:
    base = sharp_texture()
    items = [
        QualityInput(
            base.resize((180 + index * 4, 180 + index * 4)),
            image_id=f"image-{index}",
            filename=f"image-{index}.jpg",
        )
        for index in range(30)
    ]
    result = analyze_images(items, config=config(near_duplicate_max_images=10))

    assert result.near_duplicates is not None
    assert len(result.reports) == 30
    assert result.near_duplicates.images_compared == 10
    assert result.near_duplicates.truncated is True
    assert len(result.near_duplicates.pairs) <= 10 * 9 // 2
