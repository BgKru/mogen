"""Shared deterministic image-quality analysis for the ML pipelines.

Public API (see ``docs/additions/11_image_quality_analysis.md``):

* :class:`ImageQualityConfig` -- validated thresholds in documented units.
* :func:`analyze_image` -- per-photograph technical findings.
* :func:`analyze_images` -- bounded dataset analysis plus perceptual
  near-duplicate candidates (scene datasets only).
* :func:`quality_config_from_settings` -- duck-typed worker/config adapter.

The package must not import ``object_generation`` or ``scene_reconstruction``;
the pipelines translate these results into their own diagnostics formats.
"""

from __future__ import annotations

from .analyzer import (
    ANALYZER_VERSION,
    QUALITY_ANALYSIS_UNAVAILABLE,
    ImageQualityConfig,
    QualityInput,
    analyze_image,
    analyze_images,
    metric_algorithms,
)
from .models import (
    EXACT_DUPLICATE,
    FINDING_CODES,
    FINDING_ORDER,
    POSSIBLE_NEAR_DUPLICATE,
    ImageFinding,
    ImageQualityReport,
    NearDuplicateCluster,
    NearDuplicatePair,
    NearDuplicates,
    QualityAnalysisResult,
)
from .settings import quality_config_from_settings

__all__ = [
    "ANALYZER_VERSION",
    "EXACT_DUPLICATE",
    "FINDING_CODES",
    "FINDING_ORDER",
    "ImageFinding",
    "ImageQualityConfig",
    "ImageQualityReport",
    "NearDuplicateCluster",
    "NearDuplicatePair",
    "NearDuplicates",
    "POSSIBLE_NEAR_DUPLICATE",
    "QUALITY_ANALYSIS_UNAVAILABLE",
    "QualityAnalysisResult",
    "QualityInput",
    "analyze_image",
    "analyze_images",
    "metric_algorithms",
    "quality_config_from_settings",
]
