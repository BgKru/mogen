"""Shared, deterministic image-quality analyzer (11_image_quality_analysis.md).

The analyzer is dependency-light (NumPy + Pillow), advisory by default and
never touches the source bytes. It is consumed by both ML pipelines:

* scene reconstruction analyzes every prepared photograph and adds perceptual
  near-duplicate candidates (never removals);
* object generation analyzes the decoded original photograph before TripoSR
  preprocessing.

The module does not import either pipeline package, and it never reads
environment variables: the caller passes a validated :class:`ImageQualityConfig`
built by its worker/config adapter (11 Sections 4.3 and 7).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from PIL import Image

from . import duplicates, metrics
from .models import (
    EXTREME_ASPECT_RATIO,
    FINDING_ORDER,
    HIGH_NOISE,
    HIGHLIGHT_CLIPPING,
    LIKELY_BLUR,
    LOW_CONTRAST,
    LOW_RESOLUTION,
    OVEREXPOSED,
    POSSIBLE_NEAR_DUPLICATE,
    SHADOW_CLIPPING,
    UNDEREXPOSED,
    ImageFinding,
    ImageQualityReport,
    MetricValue,
    NearDuplicates,
    QualityAnalysisResult,
)

# Bumped whenever a metric formula, its normalization or the finding semantics
# change. Reports are only comparable within one analyzer version.
ANALYZER_VERSION = "1.0.0"

# Recorded in diagnostics instead of a report when analysis is advisory and the
# analyzer itself failed (11 Section 8.3). It is deliberately not an
# ``ImageFinding``: it describes the analysis stage, not the photograph.
QUALITY_ANALYSIS_UNAVAILABLE = "QUALITY_ANALYSIS_UNAVAILABLE"

ProgressCallback = Callable[[int, "int | None"], None]


@dataclass(frozen=True, slots=True)
class ImageQualityConfig:
    """Validated analyzer configuration with documented units and defaults.

    Units:
    * ``*_threshold`` luminance/contrast/blur/noise values are 8-bit intensity
      units (0-255); blur is a Laplacian-response variance measured on a
      normalized 512 px long edge, and noise is the Immerkær high-frequency
      standard deviation on the same normalized copy.
    * ``clipping_ratio_threshold`` is a fraction (0-1) of analysed pixels.
    * ``min_short_edge`` is pixels.
    * ``aspect_ratio_min``/``aspect_ratio_max`` bound ``width / height``.
    * ``hash_distance_threshold`` is a Hamming distance over a 63-bit pHash.

    Defaults are provisional: they were chosen conservatively from a small
    repository-owned calibration set (see ``ml/image_quality/README.md``) and
    must be re-tuned for a different camera, dataset or resolution regime.
    """

    enabled: bool = True
    # When true, an analyzer failure fails the analysis stage with a stable
    # internal error; otherwise it is logged and recorded as unavailable.
    required: bool = False

    # Bounded analysis copy for exposure/contrast, in pixels.
    max_analysis_dimension: int = 1024
    # Long edge of the normalized grayscale copy used for blur/noise.
    blur_analysis_edge: int = 512

    min_short_edge: int = 640
    blur_threshold: float = 100.0
    underexposure_threshold: float = 40.0
    overexposure_threshold: float = 215.0
    shadow_clip_level: int = 5
    highlight_clip_level: int = 250
    clipping_ratio_threshold: float = 0.15
    contrast_threshold: float = 35.0
    noise_threshold: float = 15.0
    aspect_ratio_min: float = 0.2
    aspect_ratio_max: float = 5.0

    near_duplicate_enabled: bool = True
    near_duplicate_max_images: int = 100
    hash_distance_threshold: int = 10
    # ``None`` disables SSIM confirmation (pHash candidates are reported as-is).
    ssim_threshold: float | None = 0.92

    def __post_init__(self) -> None:
        if self.max_analysis_dimension < 32:
            message = "max_analysis_dimension must be at least 32 px"
            raise ValueError(message)
        if not 32 <= self.blur_analysis_edge <= 4096:
            message = "blur_analysis_edge must be between 32 and 4096 px"
            raise ValueError(message)
        if self.min_short_edge < 1:
            message = "min_short_edge must be at least 1 px"
            raise ValueError(message)
        if self.blur_threshold < 0:
            message = "blur_threshold must not be negative"
            raise ValueError(message)
        if not 0 < self.underexposure_threshold < self.overexposure_threshold <= 255:
            message = "exposure thresholds must satisfy 0 < under < over <= 255"
            raise ValueError(message)
        if not 0 <= self.shadow_clip_level < self.highlight_clip_level <= 255:
            message = "clip levels must satisfy 0 <= shadow < highlight <= 255"
            raise ValueError(message)
        if not 0 < self.clipping_ratio_threshold <= 1:
            message = "clipping_ratio_threshold must be in (0, 1]"
            raise ValueError(message)
        if self.contrast_threshold < 0:
            message = "contrast_threshold must not be negative"
            raise ValueError(message)
        if self.noise_threshold < 0:
            message = "noise_threshold must not be negative"
            raise ValueError(message)
        if not 0 < self.aspect_ratio_min <= 1 <= self.aspect_ratio_max:
            message = "aspect ratio bounds must satisfy 0 < min <= 1 <= max"
            raise ValueError(message)
        if self.near_duplicate_max_images < 2:
            message = "near_duplicate_max_images must be at least 2"
            raise ValueError(message)
        if not 0 <= self.hash_distance_threshold <= 63:
            message = "hash_distance_threshold must be between 0 and 63 bits"
            raise ValueError(message)
        if self.ssim_threshold is not None and not 0 < self.ssim_threshold <= 1:
            message = "ssim_threshold must be in (0, 1] or None"
            raise ValueError(message)

    def as_thresholds(self) -> dict[str, MetricValue]:
        """Return the thresholds recorded with every report."""
        return {
            "min_short_edge_px": self.min_short_edge,
            "blur_laplacian_variance": self.blur_threshold,
            "underexposure_mean_luminance": self.underexposure_threshold,
            "overexposure_mean_luminance": self.overexposure_threshold,
            "shadow_clip_level": self.shadow_clip_level,
            "highlight_clip_level": self.highlight_clip_level,
            "clipping_ratio": self.clipping_ratio_threshold,
            "contrast_luminance_range": self.contrast_threshold,
            "noise_sigma": self.noise_threshold,
            "aspect_ratio_min": self.aspect_ratio_min,
            "aspect_ratio_max": self.aspect_ratio_max,
            "near_duplicate_hash_distance": self.hash_distance_threshold,
            "near_duplicate_ssim": (
                self.ssim_threshold if self.ssim_threshold is not None else "disabled"
            ),
            "max_analysis_dimension_px": self.max_analysis_dimension,
            "blur_analysis_edge_px": self.blur_analysis_edge,
            "near_duplicate_max_images": self.near_duplicate_max_images,
        }

    def as_metadata(self) -> dict[str, Any]:
        """Return the configuration summary stored in pipeline metadata."""
        return {
            "enabled": self.enabled,
            "required": self.required,
            "near_duplicate_enabled": self.near_duplicate_enabled,
            "thresholds": self.as_thresholds(),
        }


@dataclass(frozen=True, slots=True)
class QualityInput:
    """One decoded photograph presented to the analyzer."""

    image: Image.Image
    image_id: str = ""
    filename: str = ""


def metric_algorithms() -> dict[str, str]:
    """Return the documented metric algorithms recorded in every report."""
    return dict(metrics.ALGORITHMS)


def _format_number(value: float) -> str:
    return f"{value:.1f}"


def _format_percent(value: float) -> str:
    return f"{value:.1%}"


def _finding(
    code: str,
    *,
    message: str,
    recommendation: str,
    metric_name: str,
    metric_value: MetricValue,
    threshold: MetricValue,
) -> ImageFinding:
    return ImageFinding(
        code=code,
        severity="WARNING",
        message=message,
        recommendation=recommendation,
        metric_name=metric_name,
        metric_value=metric_value,
        threshold=threshold,
    )


def _sort_findings(findings: list[ImageFinding]) -> tuple[ImageFinding, ...]:
    order = {code: index for index, code in enumerate(FINDING_ORDER)}
    return tuple(sorted(findings, key=lambda finding: order.get(finding.code, len(order))))


def analyze_image(
    image: Image.Image,
    *,
    image_id: str,
    filename: str,
    config: ImageQualityConfig,
) -> ImageQualityReport:
    """Analyze one decoded photograph and return explicit findings.

    A metric that raises is omitted from ``metrics`` and named in
    ``unavailable_metrics``; it is never replaced with a fabricated value.
    An image that cannot be converted at all propagates the exception so the
    pipeline can log it and apply its advisory/required failure policy.
    """
    width, height = image.size
    values: dict[str, MetricValue] = {}
    unavailable: list[str] = []

    def record(name: str, compute: Callable[[], float]) -> float | None:
        try:
            value = round(float(compute()), 4)
        except Exception:
            unavailable.append(name)
            return None
        values[name] = value
        return value

    def record_int(name: str, compute: Callable[[], int]) -> int:
        value = int(compute())
        values[name] = value
        return value

    short_edge = record_int("short_edge", lambda: min(width, height))
    aspect = record("aspect_ratio", lambda: metrics.aspect_ratio(width, height))

    analysis_cache: dict[str, Any] = {}
    fine_cache: dict[str, Any] = {}

    def analysis_gray() -> Any:
        if "gray" not in analysis_cache:
            analysis_cache["gray"] = metrics.luminance_array(
                metrics.bound_rgb(image, config.max_analysis_dimension)
            )
        return analysis_cache["gray"]

    def fine_gray() -> Any:
        if "gray" not in fine_cache:
            fine_cache["gray"] = metrics.normalized_gray(image, config.blur_analysis_edge)
        return fine_cache["gray"]

    blur = record("blur_laplacian_variance", lambda: metrics.laplacian_variance(fine_gray()))
    noise = record("noise_sigma", lambda: metrics.immerkaer_noise(fine_gray()))

    stats: dict[str, float] = {}
    try:
        stats = metrics.luminance_stats(
            analysis_gray(),
            shadow_level=config.shadow_clip_level,
            highlight_level=config.highlight_clip_level,
        )
    except Exception:
        unavailable.extend(
            [
                "mean_luminance",
                "luminance_std",
                "luminance_p05",
                "luminance_p95",
                "contrast_range",
                "shadow_clipped_ratio",
                "highlight_clipped_ratio",
            ]
        )
    for name, value in stats.items():
        values[name] = round(float(value), 4)

    findings: list[ImageFinding] = []
    if short_edge < config.min_short_edge:
        findings.append(
            _finding(
                LOW_RESOLUTION,
                message=(
                    f"The photograph is {width}x{height} px; its short edge is below "
                    f"{config.min_short_edge} px."
                ),
                recommendation=(
                    "Use a larger original photograph, or photograph the subject closer "
                    "so the camera captures more detail."
                ),
                metric_name="short_edge",
                metric_value=short_edge,
                threshold=config.min_short_edge,
            )
        )
    if blur is not None and blur < config.blur_threshold:
        findings.append(
            _finding(
                LIKELY_BLUR,
                message=(
                    "The image contains very little fine detail, which is typical of "
                    "motion blur or missed focus."
                ),
                recommendation=(
                    "Keep the camera steady, use a faster shutter speed or a tripod, and "
                    "refocus before taking the photograph."
                ),
                metric_name="blur_laplacian_variance",
                metric_value=blur,
                threshold=config.blur_threshold,
            )
        )
    mean_luminance = values.get("mean_luminance")
    if isinstance(mean_luminance, float) and mean_luminance < config.underexposure_threshold:
        findings.append(
            _finding(
                UNDEREXPOSED,
                message=(
                    f"The average brightness is {_format_number(mean_luminance)} of 255, "
                    "which is very dark."
                ),
                recommendation=(
                    "Add light or increase the exposure; an underexposed subject loses "
                    "colour and surface detail."
                ),
                metric_name="mean_luminance",
                metric_value=mean_luminance,
                threshold=config.underexposure_threshold,
            )
        )
    if isinstance(mean_luminance, float) and mean_luminance > config.overexposure_threshold:
        findings.append(
            _finding(
                OVEREXPOSED,
                message=(
                    f"The average brightness is {_format_number(mean_luminance)} of 255, "
                    "which is very bright."
                ),
                recommendation=(
                    "Reduce the exposure or move the subject out of direct light; "
                    "overexposure washes out surface detail."
                ),
                metric_name="mean_luminance",
                metric_value=mean_luminance,
                threshold=config.overexposure_threshold,
            )
        )
    shadow_ratio = values.get("shadow_clipped_ratio")
    if isinstance(shadow_ratio, float) and shadow_ratio > config.clipping_ratio_threshold:
        findings.append(
            _finding(
                SHADOW_CLIPPING,
                message=(
                    f"{_format_percent(shadow_ratio)} of pixels are at or below the "
                    "black clipping level."
                ),
                recommendation=(
                    "Add fill light or reduce the contrast so shadow detail is not "
                    "crushed to black."
                ),
                metric_name="shadow_clipped_ratio",
                metric_value=shadow_ratio,
                threshold=config.clipping_ratio_threshold,
            )
        )
    highlight_ratio = values.get("highlight_clipped_ratio")
    if isinstance(highlight_ratio, float) and highlight_ratio > config.clipping_ratio_threshold:
        findings.append(
            _finding(
                HIGHLIGHT_CLIPPING,
                message=(
                    f"{_format_percent(highlight_ratio)} of pixels are at or above the "
                    "white clipping level."
                ),
                recommendation=(
                    "Reduce the exposure or avoid direct light sources; clipped highlight "
                    "detail cannot be recovered afterwards."
                ),
                metric_name="highlight_clipped_ratio",
                metric_value=highlight_ratio,
                threshold=config.clipping_ratio_threshold,
            )
        )
    contrast = values.get("contrast_range")
    if isinstance(contrast, float) and contrast < config.contrast_threshold:
        findings.append(
            _finding(
                LOW_CONTRAST,
                message=(
                    f"The 5th-95th percentile brightness range is {_format_number(contrast)} "
                    "of 255, which is a narrow tonal range."
                ),
                recommendation=(
                    "Use more even lighting or a background that separates from the "
                    "subject; avoid photographing through haze or a washed-out scene."
                ),
                metric_name="contrast_range",
                metric_value=contrast,
                threshold=config.contrast_threshold,
            )
        )
    if noise is not None and noise > config.noise_threshold:
        findings.append(
            _finding(
                HIGH_NOISE,
                message=(
                    f"The high-frequency noise estimate is {_format_number(noise)}, which "
                    "suggests severe noise or heavy over-sharpening."
                ),
                recommendation=(
                    "Lower the ISO, improve the lighting, or use a cleaner original; avoid "
                    "heavy digital sharpening."
                ),
                metric_name="noise_sigma",
                metric_value=noise,
                threshold=config.noise_threshold,
            )
        )
    if aspect is not None and (
        aspect < config.aspect_ratio_min or aspect > config.aspect_ratio_max
    ):
        findings.append(
            _finding(
                EXTREME_ASPECT_RATIO,
                message=(
                    f"The aspect ratio is {aspect:.2f}, outside the usual "
                    f"{config.aspect_ratio_min}-{config.aspect_ratio_max} range."
                ),
                recommendation=(
                    "Frame the subject closer to a standard photograph shape and avoid "
                    "extreme panoramas or narrow crops."
                ),
                metric_name="aspect_ratio",
                metric_value=aspect,
                threshold=f"{config.aspect_ratio_min}-{config.aspect_ratio_max}",
            )
        )

    return ImageQualityReport(
        image_id=image_id,
        filename=filename,
        width=width,
        height=height,
        metrics=values,
        findings=_sort_findings(findings),
        analyzer_version=ANALYZER_VERSION,
        unavailable_metrics=tuple(dict.fromkeys(unavailable)),
    )


def _with_duplicate_findings(
    reports: list[ImageQualityReport],
    near: NearDuplicates,
    config: ImageQualityConfig,
) -> list[ImageQualityReport]:
    """Attach one ``POSSIBLE_NEAR_DUPLICATE`` finding per matched photograph."""
    best: dict[str, tuple[int, str]] = {}
    for pair in near.pairs:
        for own_id, other_name in (
            (pair.left_id, pair.right_filename),
            (pair.right_id, pair.left_filename),
        ):
            current = best.get(own_id)
            if current is None or pair.hash_distance < current[0]:
                best[own_id] = (pair.hash_distance, other_name)

    updated: list[ImageQualityReport] = []
    for report in reports:
        match = best.get(report.image_id)
        if match is None:
            updated.append(report)
            continue
        distance, other_name = match
        finding = _finding(
            POSSIBLE_NEAR_DUPLICATE,
            message=(
                f"This photograph is perceptually close to {other_name or 'another image'} "
                f"(hash distance {distance} of 63 bits)."
            ),
            recommendation=(
                "Keep it if it adds a new viewpoint or coverage; remove it only if it is an "
                "accidental duplicate. Similar photographs are reported for review and are "
                "never rejected automatically."
            ),
            metric_name="perceptual_hash_distance",
            metric_value=distance,
            threshold=config.hash_distance_threshold,
        )
        updated.append(
            replace(
                report,
                findings=_sort_findings([*report.findings, finding]),
            )
        )
    return updated


def analyze_images(
    items: Iterable[QualityInput],
    *,
    config: ImageQualityConfig,
    on_progress: ProgressCallback | None = None,
) -> QualityAnalysisResult:
    """Analyze a stream of photographs, optionally adding near-duplicates.

    ``items`` is consumed lazily so a scene adapter can open, analyze and close
    one original at a time; only bounded thumbnails are retained. Exceptions
    from the analyzer propagate: callers decide between advisory and required
    failure handling (11 Section 8.3).
    """
    if not config.enabled:
        return QualityAnalysisResult(
            enabled=False,
            analyzer_version=ANALYZER_VERSION,
            thresholds=config.as_thresholds(),
            algorithms=metric_algorithms(),
        )

    reports: list[ImageQualityReport] = []
    fingerprints: list[duplicates.ImageFingerprint] = []
    for index, item in enumerate(items):
        if on_progress is not None:
            on_progress(index, None)
        report = analyze_image(
            item.image,
            image_id=item.image_id,
            filename=item.filename,
            config=config,
        )
        reports.append(report)
        if config.near_duplicate_enabled:
            fingerprints.append(
                duplicates.fingerprint(item.image, image_id=item.image_id, filename=item.filename)
            )

    near: NearDuplicates | None = None
    if config.near_duplicate_enabled and len(fingerprints) >= 2:
        near = duplicates.find_near_duplicates(
            fingerprints,
            max_images=config.near_duplicate_max_images,
            hash_distance_threshold=config.hash_distance_threshold,
            ssim_threshold=config.ssim_threshold,
        )
        if near.pairs:
            reports = _with_duplicate_findings(reports, near, config)

    return QualityAnalysisResult(
        enabled=True,
        analyzer_version=ANALYZER_VERSION,
        reports=tuple(reports),
        near_duplicates=near,
        thresholds=config.as_thresholds(),
        algorithms=metric_algorithms(),
    )


__all__ = [
    "ANALYZER_VERSION",
    "ImageQualityConfig",
    "QUALITY_ANALYSIS_UNAVAILABLE",
    "QualityInput",
    "analyze_image",
    "analyze_images",
    "metric_algorithms",
]
