"""Feature-backend contract, SIFT adapter and factory (increment 12).

The pipeline talks to one small interface. ``COLMAP_SIFT`` delegates to the
existing :class:`ColmapRunner` so its command arrays and stage semantics are
unchanged; ``ALIKED_LIGHTGLUE`` lives in :mod:`neural_features` and is imported
lazily, so a SIFT-only deployment never loads PyTorch, pycolmap or the models.

This module also owns the deterministic pair generator and the checkpoint
manifest shared by both backends (12 Sections 4.3 and 5.4).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .colmap_runner import ColmapRunner, StageOutcome
from .config import SceneConfig
from .dataset import SceneDataset
from .exceptions import (
    FEATURE_EXTRACTION_FAILED,
    FEATURE_PAIR_LIMIT_EXCEEDED,
    FeatureMatchError,
    SceneReconstructionError,
)
from .feature_profiles import (
    ALIKED_MODEL_NAME,
    ALIKED_WEIGHTS_FILENAME,
    ALIKED_WEIGHTS_SHA256,
    BACKEND_ALIKED_LIGHTGLUE,
    BACKEND_COLMAP_SIFT,
    LIGHTGLUE_FEATURES,
    LIGHTGLUE_REVISION,
    LIGHTGLUE_WEIGHTS_FILENAME,
    LIGHTGLUE_WEIGHTS_SHA256,
    VERIFICATION_MAX_TRIALS,
    VERIFICATION_MIN_INLIER_RATIO,
)

MANIFEST_SCHEMA_VERSION = 1
FEATURE_MANIFEST_NAME = "feature_manifest.json"
FEATURES_FILENAME = "features.npz"


@dataclass(frozen=True, slots=True)
class FeatureExtractionResult:
    """Measured outcome of one feature-extraction stage."""

    backend: str
    profile: str
    images: int
    keypoints_total: int
    keypoints_min: int
    keypoints_max: int
    seconds: float
    device: str | None = None
    precision: str | None = None
    peak_vram_mb: float | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "profile": self.profile,
            "images": self.images,
            "keypoints_total": self.keypoints_total,
            "keypoints_min": self.keypoints_min,
            "keypoints_max": self.keypoints_max,
            "seconds": round(self.seconds, 3),
            "device": self.device,
            "precision": self.precision,
            "peak_vram_mb": (
                round(self.peak_vram_mb, 1) if self.peak_vram_mb is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class FeatureMatchingResult:
    """Measured outcome of one feature-matching stage."""

    backend: str
    profile: str
    strategy: str
    pairs: int
    pairs_with_matches: int
    verified_pairs: int
    seconds: float
    device: str | None = None
    precision: str | None = None
    peak_vram_mb: float | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "profile": self.profile,
            "strategy": self.strategy,
            "pairs": self.pairs,
            "pairs_with_matches": self.pairs_with_matches,
            "verified_pairs": self.verified_pairs,
            "seconds": round(self.seconds, 3),
            "device": self.device,
            "precision": self.precision,
            "peak_vram_mb": (
                round(self.peak_vram_mb, 1) if self.peak_vram_mb is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """The result of checking one backend before expensive work starts."""

    backend: str
    available: bool
    device: str | None
    versions: dict[str, str]
    reason: str | None = None


class FeatureBackend(Protocol):
    """The only interface the pipeline uses for feature extraction/matching."""

    name: str

    def verify_runtime(self, config: SceneConfig) -> RuntimeInfo: ...

    def extract_features(
        self,
        dataset: SceneDataset,
        *,
        images_dir: Path,
        database_path: Path,
        work_dir: Path,
        on_poll: Callable[[], None],
    ) -> FeatureExtractionResult: ...

    def match_features(
        self,
        dataset: SceneDataset,
        *,
        images_dir: Path,
        database_path: Path,
        work_dir: Path,
        on_poll: Callable[[], None],
    ) -> FeatureMatchingResult: ...


class SiftBackend:
    """Existing COLMAP SIFT pipeline behind the shared backend contract."""

    name = BACKEND_COLMAP_SIFT

    def __init__(self, config: SceneConfig, *, colmap: ColmapRunner | None = None) -> None:
        self._config = config
        self._colmap = colmap or ColmapRunner(config)

    def verify_runtime(self, config: SceneConfig) -> RuntimeInfo:
        return RuntimeInfo(
            backend=self.name,
            available=True,
            device="cpu" if not config.colmap_use_gpu else "cuda",
            versions={"extractor": "COLMAP SIFT", "matcher": "COLMAP"},
        )

    def extract_features(
        self,
        dataset: SceneDataset,
        *,
        images_dir: Path,
        database_path: Path,
        work_dir: Path,
        on_poll: Callable[[], None],
    ) -> FeatureExtractionResult:
        outcome: StageOutcome = self._colmap.extract_features(
            images_dir=images_dir,
            database_path=database_path,
            log_path=work_dir / "logs" / "feature_extraction.log",
            expected_images=dataset.image_count,
            on_poll=on_poll,
        )
        stats = outcome.database
        if stats is None:
            raise FeatureMatchError(
                FEATURE_EXTRACTION_FAILED, "COLMAP did not produce a usable feature database."
            )
        return FeatureExtractionResult(
            backend=self.name,
            profile=self._config.feature_profile,
            images=stats.images,
            keypoints_total=stats.keypoints,
            keypoints_min=0,
            keypoints_max=0,
            seconds=outcome.duration_seconds,
            device="cpu" if not self._config.colmap_use_gpu else "cuda",
            precision="fp32",
        )

    def match_features(
        self,
        dataset: SceneDataset,
        *,
        images_dir: Path,
        database_path: Path,
        work_dir: Path,
        on_poll: Callable[[], None],
    ) -> FeatureMatchingResult:
        outcome = self._colmap.match_features(
            database_path=database_path,
            log_path=work_dir / "logs" / "feature_matching.log",
            on_poll=on_poll,
        )
        stats = outcome.database
        return FeatureMatchingResult(
            backend=self.name,
            profile=self._config.feature_profile,
            strategy=self._config.matching_strategy,
            pairs=stats.matched_pairs if stats else 0,
            pairs_with_matches=stats.matched_pairs if stats else 0,
            verified_pairs=stats.verified_pairs if stats else 0,
            seconds=outcome.duration_seconds,
            device="cpu" if not self._config.colmap_use_gpu else "cuda",
            precision="fp32",
        )


def build_feature_backend(
    config: SceneConfig, *, colmap_runner: ColmapRunner | None = None
) -> FeatureBackend:
    """Return the configured backend; the neural import stays lazy."""
    if config.feature_backend == BACKEND_COLMAP_SIFT:
        return SiftBackend(config, colmap=colmap_runner)
    if config.feature_backend == BACKEND_ALIKED_LIGHTGLUE:
        from .neural_features import AlikedLightGlueBackend

        return AlikedLightGlueBackend(config, colmap=colmap_runner)
    raise FeatureMatchError(
        FEATURE_EXTRACTION_FAILED, "The configured feature backend is not available."
    )


def generate_pairs(
    names: Sequence[str],
    *,
    strategy: str,
    sequential_overlap: int,
    max_pairs: int,
) -> list[tuple[str, str]]:
    """Generate deterministic image pairs before any inference.

    ``EXHAUSTIVE`` uses every unordered pair of the sorted names.
    ``SEQUENTIAL`` preserves the supplied dataset order and pairs each image with
    the next ``sequential_overlap`` images. The pair-count limit is enforced
    before a model is loaded.
    """
    ordered = list(names)
    if len(set(ordered)) != len(ordered):
        raise FeatureMatchError(
            FEATURE_EXTRACTION_FAILED, "The dataset contains ambiguous image names."
        )
    pairs: list[tuple[str, str]] = []
    normalized = strategy.strip().upper()
    if normalized == "EXHAUSTIVE":
        ordered = sorted(ordered)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                pairs.append((left, right))
    elif normalized == "SEQUENTIAL":
        for left_index, left in enumerate(ordered):
            for offset in range(1, sequential_overlap + 1):
                right_index = left_index + offset
                if right_index < len(ordered):
                    pairs.append((left, ordered[right_index]))
    else:
        raise FeatureMatchError(
            FEATURE_EXTRACTION_FAILED, "The configured pair strategy is not supported."
        )
    if len(pairs) > max_pairs:
        raise FeatureMatchError(
            FEATURE_PAIR_LIMIT_EXCEEDED,
            "The configured matching strategy produces too many image pairs.",
        )
    return pairs


def feature_manifest_path(colmap_dir: Path) -> Path:
    return Path(colmap_dir) / FEATURE_MANIFEST_NAME


def features_path(colmap_dir: Path) -> Path:
    return Path(colmap_dir) / FEATURES_FILENAME


def build_feature_manifest(
    dataset: SceneDataset,
    config: SceneConfig,
    *,
    backend: str,
    colmap_version: str,
) -> dict[str, Any]:
    """Build the canonical input/output fingerprint for feature checkpoints.

    Every value that can change the keypoints, matches or verified geometries is
    included. Timings, absolute paths and runtime-only state are excluded so the
    manifest is stable across workers.
    """
    profile = config.resolved_feature_profile
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "backend": backend,
        "profile": profile.name,
        "dataset": {
            "images": [
                {
                    "name": image.filename,
                    "sha256": image.sha256,
                    "size_bytes": image.size_bytes,
                    "width": image.width,
                    "height": image.height,
                }
                for image in dataset.images
            ]
        },
        "parameters": config.feature_parameters(),
        "colmap_version": colmap_version,
    }
    if profile.is_neural:
        # Imported lazily: a SIFT-only configuration never loads the neural
        # runtime just to compute a checkpoint fingerprint.
        from .neural_features import runtime_versions

        manifest["models"] = {
            "extractor": ALIKED_MODEL_NAME,
            "extractor_weights": ALIKED_WEIGHTS_FILENAME,
            "extractor_sha256": ALIKED_WEIGHTS_SHA256,
            "matcher": LIGHTGLUE_FEATURES,
            "matcher_revision": LIGHTGLUE_REVISION,
            "matcher_weights": LIGHTGLUE_WEIGHTS_FILENAME,
            "matcher_sha256": LIGHTGLUE_WEIGHTS_SHA256,
        }
        try:
            manifest["runtime"] = runtime_versions().as_dict()
        except SceneReconstructionError:
            # Reuse must remain a pure local decision: a worker without the
            # neural runtime discards neural checkpoints instead of crashing
            # while computing the fingerprint. The stage itself still reports
            # NEURAL_RUNTIME_UNAVAILABLE and follows the fallback policy.
            manifest["runtime"] = {"available": False}
        manifest["verification"] = {
            "library": "pycolmap.verify_matches",
            "max_num_trials": VERIFICATION_MAX_TRIALS,
            "min_inlier_ratio": VERIFICATION_MIN_INLIER_RATIO,
        }
    else:
        manifest["models"] = {"extractor": "COLMAP SIFT", "matcher": "COLMAP"}
        manifest["verification"] = {
            "library": "COLMAP matcher",
            "strategy": config.matching_strategy,
            "max_num_features": config.colmap_max_features,
        }
    return manifest


def read_feature_manifest(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def write_feature_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest atomically so reuse never sees a partial file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def manifest_matches(path: Path, expected: dict[str, Any]) -> bool:
    """Return True only when the stored manifest equals the expected one."""
    stored = read_feature_manifest(path)
    return stored == expected


__all__ = [
    "FEATURES_FILENAME",
    "FEATURE_MANIFEST_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "FeatureBackend",
    "FeatureExtractionResult",
    "FeatureMatchingResult",
    "RuntimeInfo",
    "SiftBackend",
    "build_feature_backend",
    "build_feature_manifest",
    "feature_manifest_path",
    "features_path",
    "generate_pairs",
    "manifest_matches",
    "read_feature_manifest",
    "write_feature_manifest",
]
