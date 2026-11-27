"""Metric algorithms: ranges, invariance and failure behaviour."""

from __future__ import annotations

import numpy as np
import pytest

from image_quality import metrics

from .helpers import (
    blurred,
    clipped,
    coarse_texture,
    flat,
    gradient,
    noisy,
    sharp_texture,
)


def test_laplacian_variance_separates_sharp_from_blurred_images() -> None:
    sharp = metrics.laplacian_variance(metrics.normalized_gray(sharp_texture(), 512))
    smoothed = metrics.laplacian_variance(metrics.normalized_gray(blurred(sharp_texture()), 512))

    assert sharp > 500
    assert smoothed < sharp / 10


def test_luminance_statistics_report_clipping_and_contrast() -> None:
    dark = metrics.luminance_stats(
        metrics.luminance_array(clipped(black_fraction=0.4)),
        shadow_level=5,
        highlight_level=250,
    )
    bright = metrics.luminance_stats(
        metrics.luminance_array(clipped(white_fraction=0.3)),
        shadow_level=5,
        highlight_level=250,
    )

    assert 0.35 <= dark["shadow_clipped_ratio"] <= 0.45
    assert bright["highlight_clipped_ratio"] >= 0.29
    assert dark["highlight_clipped_ratio"] == 0.0
    assert (
        metrics.luminance_stats(
            metrics.luminance_array(gradient()),
            shadow_level=5,
            highlight_level=250,
        )["contrast_range"]
        > 150
    )


def test_noise_estimate_is_higher_for_noise_than_for_a_clean_texture() -> None:
    noisy_sigma = metrics.immerkaer_noise(metrics.normalized_gray(noisy(sigma=40), 512))
    texture_sigma = metrics.immerkaer_noise(metrics.normalized_gray(coarse_texture(), 512))
    flat_sigma = metrics.immerkaer_noise(metrics.normalized_gray(flat(128), 512))

    assert noisy_sigma > texture_sigma
    assert flat_sigma < texture_sigma


def test_perceptual_hash_is_close_for_resized_and_recompressed_images() -> None:
    base = metrics.perceptual_hash(metrics.square_gray(sharp_texture(), 32))
    resized = metrics.perceptual_hash(metrics.square_gray(sharp_texture().resize((384, 384)), 32))
    recompressed = metrics.perceptual_hash(
        metrics.square_gray(sharp_texture().resize((512, 512)), 32)
    )
    unrelated = metrics.perceptual_hash(metrics.square_gray(gradient(), 32))

    assert metrics.hamming_distance(base, resized) <= 10
    assert metrics.hamming_distance(base, recompressed) <= 10
    assert metrics.hamming_distance(base, unrelated) >= 5


def test_structural_similarity_is_high_for_an_identical_copy() -> None:
    array = metrics.square_gray(sharp_texture(), 256)
    different = metrics.square_gray(gradient(), 256)

    assert metrics.structural_similarity(array, array) == pytest.approx(1.0, abs=1e-6)
    assert metrics.structural_similarity(array, different) < 0.9


def test_square_gray_always_returns_the_requested_shape() -> None:
    array = metrics.square_gray(gradient((900, 300)), 32)

    assert array.shape == (32, 32)
    assert np.isfinite(array).all()


def test_aspect_ratio_and_metric_guards() -> None:
    assert metrics.aspect_ratio(1200, 300) == 4.0
    with pytest.raises(ValueError):
        metrics.aspect_ratio(0, 100)
    with pytest.raises(ValueError):
        metrics.laplacian_variance(np.zeros((2, 2)))
    with pytest.raises(ValueError):
        metrics.immerkaer_noise(np.zeros((2, 2)))
    with pytest.raises(ValueError):
        metrics.perceptual_hash(np.zeros((16, 16)))
    with pytest.raises(ValueError):
        metrics.structural_similarity(np.zeros((4, 4)), np.zeros((4, 4)))
