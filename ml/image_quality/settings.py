"""Worker/config adapter helper for the shared analyzer.

``Settings`` lives in the backend image and the analyzer must not import it, so
this module only uses duck-typed attributes. Missing attributes fall back to the
validated dataclass defaults, which keeps a standalone caller working without
duplicating the default values.
"""

from __future__ import annotations

from typing import Any

from .analyzer import ImageQualityConfig


def quality_config_from_settings(settings: Any) -> ImageQualityConfig:
    """Map the backend ``IMAGE_QUALITY_*`` settings onto the analyzer config."""
    defaults = ImageQualityConfig()
    ssim_enabled = bool(
        getattr(settings, "image_quality_ssim_enabled", defaults.ssim_threshold is not None)
    )
    ssim_threshold = getattr(
        settings,
        "image_quality_ssim_threshold",
        defaults.ssim_threshold if defaults.ssim_threshold is not None else 0.92,
    )
    return ImageQualityConfig(
        enabled=bool(getattr(settings, "image_quality_enabled", defaults.enabled)),
        required=bool(getattr(settings, "image_quality_required", defaults.required)),
        max_analysis_dimension=int(
            getattr(
                settings,
                "image_quality_max_analysis_dimension",
                defaults.max_analysis_dimension,
            )
        ),
        blur_analysis_edge=int(
            getattr(settings, "image_quality_blur_analysis_edge", defaults.blur_analysis_edge)
        ),
        min_short_edge=int(
            getattr(settings, "image_quality_min_short_edge", defaults.min_short_edge)
        ),
        blur_threshold=float(
            getattr(settings, "image_quality_blur_threshold", defaults.blur_threshold)
        ),
        underexposure_threshold=float(
            getattr(
                settings,
                "image_quality_underexposure_threshold",
                defaults.underexposure_threshold,
            )
        ),
        overexposure_threshold=float(
            getattr(
                settings,
                "image_quality_overexposure_threshold",
                defaults.overexposure_threshold,
            )
        ),
        shadow_clip_level=int(
            getattr(settings, "image_quality_shadow_clip_level", defaults.shadow_clip_level)
        ),
        highlight_clip_level=int(
            getattr(settings, "image_quality_highlight_clip_level", defaults.highlight_clip_level)
        ),
        clipping_ratio_threshold=float(
            getattr(
                settings,
                "image_quality_clipping_ratio_threshold",
                defaults.clipping_ratio_threshold,
            )
        ),
        contrast_threshold=float(
            getattr(settings, "image_quality_contrast_threshold", defaults.contrast_threshold)
        ),
        noise_threshold=float(
            getattr(settings, "image_quality_noise_threshold", defaults.noise_threshold)
        ),
        aspect_ratio_min=float(
            getattr(settings, "image_quality_aspect_ratio_min", defaults.aspect_ratio_min)
        ),
        aspect_ratio_max=float(
            getattr(settings, "image_quality_aspect_ratio_max", defaults.aspect_ratio_max)
        ),
        near_duplicate_enabled=bool(
            getattr(
                settings,
                "image_quality_near_duplicate_enabled",
                defaults.near_duplicate_enabled,
            )
        ),
        near_duplicate_max_images=int(
            getattr(
                settings,
                "image_quality_near_duplicate_max_images",
                defaults.near_duplicate_max_images,
            )
        ),
        hash_distance_threshold=int(
            getattr(
                settings,
                "image_quality_hash_distance_threshold",
                defaults.hash_distance_threshold,
            )
        ),
        ssim_threshold=float(ssim_threshold) if ssim_enabled else None,
    )


__all__ = ["quality_config_from_settings"]
