"""Immutable, JSON-compatible result types for image-quality analysis.

The analyzer reports explicit findings instead of one opaque quality score
(docs/additions/11_image_quality_analysis.md Section 6). The objects in this
module are the shared contract between the scene-reconstruction adapter, the
object-generation adapter and their tests; they never carry pixel data, host
paths or additional copies of a source photograph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["INFO", "WARNING", "ERROR"]
MetricValue = float | int | str

# Stable finding codes. ``EXACT_DUPLICATE`` is intentionally not emitted by the
# analyzer: byte-identical photographs are rejected by the existing SHA-256
# dataset validation (07 Section 4.5) before the analyzer runs. The code is
# exported so the report can state the distinction explicitly, and so a future
# adapter can reference it without inventing a second spelling.
LOW_RESOLUTION = "LOW_RESOLUTION"
LIKELY_BLUR = "LIKELY_BLUR"
UNDEREXPOSED = "UNDEREXPOSED"
OVEREXPOSED = "OVEREXPOSED"
HIGHLIGHT_CLIPPING = "HIGHLIGHT_CLIPPING"
SHADOW_CLIPPING = "SHADOW_CLIPPING"
LOW_CONTRAST = "LOW_CONTRAST"
HIGH_NOISE = "HIGH_NOISE"
EXTREME_ASPECT_RATIO = "EXTREME_ASPECT_RATIO"
EXACT_DUPLICATE = "EXACT_DUPLICATE"
POSSIBLE_NEAR_DUPLICATE = "POSSIBLE_NEAR_DUPLICATE"

FINDING_CODES: frozenset[str] = frozenset(
    {
        LOW_RESOLUTION,
        LIKELY_BLUR,
        UNDEREXPOSED,
        OVEREXPOSED,
        HIGHLIGHT_CLIPPING,
        SHADOW_CLIPPING,
        LOW_CONTRAST,
        HIGH_NOISE,
        EXTREME_ASPECT_RATIO,
        POSSIBLE_NEAR_DUPLICATE,
    }
)

# Deterministic finding order for serialized reports.
FINDING_ORDER: tuple[str, ...] = (
    LOW_RESOLUTION,
    LIKELY_BLUR,
    UNDEREXPOSED,
    OVEREXPOSED,
    HIGHLIGHT_CLIPPING,
    SHADOW_CLIPPING,
    LOW_CONTRAST,
    HIGH_NOISE,
    EXTREME_ASPECT_RATIO,
    POSSIBLE_NEAR_DUPLICATE,
)


@dataclass(frozen=True, slots=True)
class ImageFinding:
    """One advisory finding with a stable code and an actionable remedy."""

    code: str
    severity: Severity
    message: str
    recommendation: str | None = None
    metric_name: str | None = None
    metric_value: MetricValue | None = None
    threshold: MetricValue | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "recommendation": self.recommendation,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class ImageQualityReport:
    """Deterministic diagnostics for one photograph.

    ``metrics`` is a plain dict so the serialized report stays JSON-compatible;
    callers must treat it as read-only.
    """

    image_id: str
    filename: str
    width: int
    height: int
    metrics: dict[str, MetricValue]
    findings: tuple[ImageFinding, ...]
    analyzer_version: str
    # Metrics that could not be computed are listed here instead of being
    # fabricated (11 Section 5.1).
    unavailable_metrics: tuple[str, ...] = ()

    @property
    def finding_codes(self) -> tuple[str, ...]:
        """Return the finding codes in deterministic order."""
        return tuple(finding.code for finding in self.findings)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "image_id": self.image_id,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "metrics": dict(self.metrics),
            "findings": [finding.as_dict() for finding in self.findings],
            "analyzer_version": self.analyzer_version,
            "unavailable_metrics": list(self.unavailable_metrics),
        }


@dataclass(frozen=True, slots=True)
class NearDuplicatePair:
    """One candidate perceptual duplicate pair with its measured distance."""

    left_id: str
    right_id: str
    left_filename: str
    right_filename: str
    hash_distance: int
    ssim: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "left_id": self.left_id,
            "right_id": self.right_id,
            "left_filename": self.left_filename,
            "right_filename": self.right_filename,
            "hash_distance": self.hash_distance,
            "ssim": self.ssim,
        }


@dataclass(frozen=True, slots=True)
class NearDuplicateCluster:
    """A connected group of perceptually similar photographs."""

    image_ids: tuple[str, ...]
    filenames: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {"image_ids": list(self.image_ids), "filenames": list(self.filenames)}


@dataclass(frozen=True, slots=True)
class NearDuplicates:
    """Bounded near-duplicate diagnostics for one scene dataset."""

    pairs: tuple[NearDuplicatePair, ...]
    clusters: tuple[NearDuplicateCluster, ...]
    images_compared: int
    hash_distance_threshold: int
    ssim_threshold: float | None
    ssim_applied: bool
    truncated: bool
    max_images: int

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "images_compared": self.images_compared,
            "pair_count": len(self.pairs),
            "cluster_count": len(self.clusters),
            "hash_distance_threshold": self.hash_distance_threshold,
            "ssim_threshold": self.ssim_threshold,
            "ssim_applied": self.ssim_applied,
            "truncated": self.truncated,
            "max_images": self.max_images,
            "pairs": [pair.as_dict() for pair in self.pairs],
            "clusters": [cluster.as_dict() for cluster in self.clusters],
        }


@dataclass(frozen=True, slots=True)
class QualityAnalysisResult:
    """Per-image reports plus scene-only duplicate diagnostics."""

    enabled: bool
    analyzer_version: str
    reports: tuple[ImageQualityReport, ...] = ()
    near_duplicates: NearDuplicates | None = None
    thresholds: dict[str, MetricValue] = field(default_factory=dict)
    algorithms: dict[str, str] = field(default_factory=dict)

    @property
    def finding_codes(self) -> tuple[str, ...]:
        """Return every finding code reported for the dataset, sorted."""
        return tuple(sorted({code for report in self.reports for code in report.finding_codes}))

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON document written to task diagnostics."""
        return {
            "enabled": self.enabled,
            "analyzer": {
                "version": self.analyzer_version,
                "algorithms": dict(self.algorithms),
                "thresholds": dict(self.thresholds),
            },
            # The exact/near distinction is explicit: byte-identical files are
            # handled by SHA-256 before analysis (07 Section 4.5), while the
            # analyzer only ever reports perceptual candidates.
            "duplicate_codes": {
                "exact": EXACT_DUPLICATE,
                "near": POSSIBLE_NEAR_DUPLICATE,
                "exact_detector": "sha256",
            },
            "images": [report.as_dict() for report in self.reports],
            "near_duplicates": (
                self.near_duplicates.as_dict() if self.near_duplicates is not None else None
            ),
        }


__all__ = [
    "EXACT_DUPLICATE",
    "EXTREME_ASPECT_RATIO",
    "FINDING_CODES",
    "FINDING_ORDER",
    "HIGH_NOISE",
    "HIGHLIGHT_CLIPPING",
    "ImageFinding",
    "ImageQualityReport",
    "LIKELY_BLUR",
    "LOW_CONTRAST",
    "LOW_RESOLUTION",
    "MetricValue",
    "NearDuplicateCluster",
    "NearDuplicatePair",
    "NearDuplicates",
    "OVEREXPOSED",
    "POSSIBLE_NEAR_DUPLICATE",
    "QualityAnalysisResult",
    "SHADOW_CLIPPING",
    "Severity",
    "UNDEREXPOSED",
]
