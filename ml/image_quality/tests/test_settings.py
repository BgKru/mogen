"""The duck-typed settings adapter keeps worker configuration in one place."""

from __future__ import annotations

import pytest

from image_quality import ImageQualityConfig, quality_config_from_settings


class _Settings:
    """Stand-in for the backend Settings object (no backend import)."""

    image_quality_enabled = False
    image_quality_required = True
    image_quality_max_analysis_dimension = 768
    image_quality_blur_analysis_edge = 384
    image_quality_min_short_edge = 500
    image_quality_blur_threshold = 80.5
    image_quality_underexposure_threshold = 30.0
    image_quality_overexposure_threshold = 225.0
    image_quality_shadow_clip_level = 4
    image_quality_highlight_clip_level = 251
    image_quality_clipping_ratio_threshold = 0.2
    image_quality_contrast_threshold = 40.0
    image_quality_noise_threshold = 12.0
    image_quality_aspect_ratio_min = 0.25
    image_quality_aspect_ratio_max = 4.0
    image_quality_near_duplicate_enabled = False
    image_quality_near_duplicate_max_images = 50
    image_quality_hash_distance_threshold = 8
    image_quality_ssim_enabled = False
    image_quality_ssim_threshold = 0.9


def test_missing_attributes_fall_back_to_the_dataclass_defaults() -> None:
    assert quality_config_from_settings(object()) == ImageQualityConfig()


def test_every_documented_setting_is_mapped() -> None:
    config = quality_config_from_settings(_Settings())

    assert config.enabled is False
    assert config.required is True
    assert config.max_analysis_dimension == 768
    assert config.blur_analysis_edge == 384
    assert config.min_short_edge == 500
    assert config.blur_threshold == 80.5
    assert config.underexposure_threshold == 30.0
    assert config.overexposure_threshold == 225.0
    assert config.shadow_clip_level == 4
    assert config.highlight_clip_level == 251
    assert config.clipping_ratio_threshold == 0.2
    assert config.contrast_threshold == 40.0
    assert config.noise_threshold == 12.0
    assert config.aspect_ratio_min == 0.25
    assert config.aspect_ratio_max == 4.0
    assert config.near_duplicate_enabled is False
    assert config.near_duplicate_max_images == 50
    assert config.hash_distance_threshold == 8
    assert config.ssim_threshold is None
    assert config.as_thresholds()["near_duplicate_ssim"] == "disabled"


def test_adapter_still_rejects_invalid_values() -> None:
    class Broken(_Settings):
        image_quality_hash_distance_threshold = 99

    with pytest.raises(ValueError):
        quality_config_from_settings(Broken())
