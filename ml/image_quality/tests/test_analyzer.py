"""Analyzer findings, thresholds, omission, determinism and failure behaviour."""

from __future__ import annotations

import json

import pytest

from image_quality import (
    FINDING_CODES,
    ImageQualityConfig,
    QualityInput,
    analyze_image,
    analyze_images,
)
from image_quality import analyzer as analyzer_module
from image_quality import metrics as metrics_module

from .helpers import (
    blurred,
    clipped,
    coarse_texture,
    config,
    flat,
    gradient,
    low_contrast,
    noisy,
    sharp_texture,
)


def _codes(image, **overrides) -> tuple[str, ...]:
    return analyze_image(
        image, image_id="image", filename="image.jpg", config=config(**overrides)
    ).finding_codes


def test_a_clean_sharp_photograph_produces_no_findings() -> None:
    report = analyze_image(coarse_texture(), image_id="a", filename="a.jpg", config=config())

    assert report.findings == ()
    assert report.metrics["blur_laplacian_variance"] > 100
    assert report.metrics["noise_sigma"] < 15


def test_blurred_image_is_flagged_as_likely_blur() -> None:
    assert "LIKELY_BLUR" not in _codes(coarse_texture())
    assert "LIKELY_BLUR" in _codes(blurred(sharp_texture(), radius=10))


def test_dark_bright_and_clipped_images_get_exposure_codes() -> None:
    assert "UNDEREXPOSED" in _codes(flat(30))
    assert "OVEREXPOSED" in _codes(flat(240))
    assert "SHADOW_CLIPPING" in _codes(clipped(black_fraction=0.4))
    assert "HIGHLIGHT_CLIPPING" in _codes(clipped(white_fraction=0.3))


def test_low_contrast_image_is_flagged() -> None:
    assert "LOW_CONTRAST" in _codes(low_contrast())
    assert "LOW_CONTRAST" not in _codes(gradient())


def test_high_noise_is_flagged_but_clean_texture_is_not() -> None:
    assert "HIGH_NOISE" in _codes(noisy(sigma=40))
    assert "HIGH_NOISE" not in _codes(coarse_texture())


def test_extreme_aspect_ratio_is_flagged() -> None:
    assert "EXTREME_ASPECT_RATIO" in _codes(gradient((1200, 200)))
    assert "EXTREME_ASPECT_RATIO" not in _codes(gradient((800, 600)))


def test_low_resolution_boundary_is_strict() -> None:
    image = gradient((512, 512))

    assert "LOW_RESOLUTION" not in _codes(image, min_short_edge=512)
    assert "LOW_RESOLUTION" in _codes(image, min_short_edge=513)


def test_blur_threshold_boundary_uses_the_measured_metric() -> None:
    image = coarse_texture()
    measured = analyze_image(image, image_id="a", filename="a.jpg", config=config()).metrics[
        "blur_laplacian_variance"
    ]

    below = _codes(image, blur_threshold=float(measured) * 0.5)
    above = _codes(image, blur_threshold=float(measured) * 2.0)

    assert "LIKELY_BLUR" not in below
    assert "LIKELY_BLUR" in above


def test_clipping_ratio_boundary_uses_the_measured_ratio() -> None:
    image = clipped(black_fraction=0.4)

    assert "SHADOW_CLIPPING" in _codes(image, clipping_ratio_threshold=0.2)
    assert "SHADOW_CLIPPING" not in _codes(image, clipping_ratio_threshold=0.6)


def test_contrast_and_aspect_boundaries_use_the_measured_values() -> None:
    assert "LOW_CONTRAST" not in _codes(gradient(), contrast_threshold=92.0)
    assert "LOW_CONTRAST" in _codes(gradient(), contrast_threshold=368.0)
    assert "EXTREME_ASPECT_RATIO" in _codes(gradient((1200, 200)))
    assert "EXTREME_ASPECT_RATIO" not in _codes(gradient((1200, 200)), aspect_ratio_max=7.0)


def test_exposure_threshold_boundary() -> None:
    assert "UNDEREXPOSED" not in _codes(flat(30), underexposure_threshold=20.0)
    assert "OVEREXPOSED" not in _codes(flat(240), overexposure_threshold=250.0)


def test_noise_threshold_boundary_uses_the_measured_value() -> None:
    image = noisy(sigma=40)
    measured = analyze_image(image, image_id="a", filename="a.jpg", config=config()).metrics[
        "noise_sigma"
    ]

    assert "HIGH_NOISE" not in _codes(image, noise_threshold=float(measured) * 2.0)
    assert "HIGH_NOISE" in _codes(image, noise_threshold=float(measured) * 0.5)


def test_a_metric_that_cannot_be_computed_is_omitted_not_fabricated(monkeypatch) -> None:
    def broken(_gray):
        raise RuntimeError("metric unavailable")

    monkeypatch.setattr(metrics_module, "laplacian_variance", broken)

    report = analyze_image(coarse_texture(), image_id="a", filename="a.jpg", config=config())

    assert "blur_laplacian_variance" not in report.metrics
    assert "blur_laplacian_variance" in report.unavailable_metrics
    assert "LIKELY_BLUR" not in report.finding_codes


def test_reports_are_deterministic_and_json_serialisable() -> None:
    items = [
        QualityInput(coarse_texture(), image_id="a", filename="a.jpg"),
        QualityInput(noisy(), image_id="b", filename="b.jpg"),
        QualityInput(low_contrast(), image_id="c", filename="c.jpg"),
    ]
    first = analyze_images(items, config=config())
    second = analyze_images(items, config=config())

    assert first.as_dict() == second.as_dict()
    document = first.as_dict()
    encoded = json.dumps(document, sort_keys=True)
    json.loads(encoded)
    codes = {finding["code"] for report in document["images"] for finding in report["findings"]}
    assert codes
    assert all(
        finding["code"] in FINDING_CODES
        for report in document["images"]
        for finding in report["findings"]
    )
    assert "OVERALL_QUALITY_SCORE" not in encoded
    assert document["duplicate_codes"]["exact"] != document["duplicate_codes"]["near"]


def test_no_aggregate_score_finding_is_ever_emitted() -> None:
    report = analyze_image(low_contrast(), image_id="a", filename="a.jpg", config=config())

    assert "OVERALL_QUALITY_SCORE" not in report.finding_codes
    assert all(finding.metric_name != "overall_quality" for finding in report.findings)


def test_disabled_analyzer_does_no_work(monkeypatch) -> None:
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("analyze_image must not run when disabled")

    monkeypatch.setattr(analyzer_module, "analyze_image", should_not_run)

    result = analyze_images(
        [QualityInput(coarse_texture(), image_id="a", filename="a.jpg")],
        config=ImageQualityConfig(enabled=False),
    )

    assert result.enabled is False
    assert result.reports == ()
    assert result.near_duplicates is None
    assert result.as_dict()["enabled"] is False


def test_analyzer_exceptions_propagate_instead_of_producing_a_clean_report(monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("analysis crashed")

    monkeypatch.setattr(analyzer_module, "analyze_image", broken)

    with pytest.raises(RuntimeError, match="analysis crashed"):
        analyze_images(
            [QualityInput(coarse_texture(), image_id="a", filename="a.jpg")],
            config=config(),
        )


def test_progress_callback_runs_once_per_image() -> None:
    seen: list[int] = []

    analyze_images(
        [
            QualityInput(coarse_texture(), image_id="a", filename="a.jpg"),
            QualityInput(gradient(), image_id="b", filename="b.jpg"),
        ],
        config=config(),
        on_progress=lambda index, _total: seen.append(index),
    )

    assert seen == [0, 1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"blur_threshold": -1},
        {"underexposure_threshold": 0},
        {"overexposure_threshold": 300},
        {"clipping_ratio_threshold": 0},
        {"contrast_threshold": -1},
        {"aspect_ratio_min": 2.0},
        {"aspect_ratio_max": 0.5},
        {"hash_distance_threshold": 64},
        {"ssim_threshold": 1.5},
        {"near_duplicate_max_images": 1},
        {"min_short_edge": 0},
        {"max_analysis_dimension": 8},
    ],
)
def test_invalid_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ImageQualityConfig(**overrides)
