"""Feature-backend profiles (docs/additions/12_advanced_feature_matching.md).

A profile is a small, validated description of one feature extractor/matcher
combination. It is not a plugin system: only the profiles in ``PROFILES`` are
accepted, and each maps to a backend implementation in
:mod:`scene_reconstruction.feature_matching`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Backend identifiers persisted in diagnostics and checkpoint manifests.
BACKEND_COLMAP_SIFT = "COLMAP_SIFT"
BACKEND_ALIKED_LIGHTGLUE = "ALIKED_LIGHTGLUE"
FEATURE_BACKENDS: tuple[str, ...] = (BACKEND_COLMAP_SIFT, BACKEND_ALIKED_LIGHTGLUE)

PROFILE_SIFT_DEFAULT = "sift_default"
PROFILE_ALIKED = "aliked_lightglue"
PROFILE_ALIKED_FAST = "aliked_lightglue_fast"
FEATURE_PROFILES: tuple[str, ...] = (
    PROFILE_SIFT_DEFAULT,
    PROFILE_ALIKED,
    PROFILE_ALIKED_FAST,
)

DEVICE_CHOICES: tuple[str, ...] = ("auto", "cuda", "cpu")

# Pair strategies accepted for neural matching. SIFT keeps using the existing
# ``matching_strategy`` setting so its command sequence is unchanged.
PAIR_STRATEGIES: tuple[str, ...] = ("EXHAUSTIVE", "SEQUENTIAL")

# The ALIKED model and its pinned checkpoint (12 Section 5.1). The checkpoint is
# baked into the worker image by ``download_neural_models.py`` and verified
# before every neural stage.
ALIKED_MODEL_NAME = "aliked-n16"
ALIKED_WEIGHTS_FILENAME = "aliked-n16.pth"
ALIKED_WEIGHTS_SHA256 = "5be8704840ed662d9d8c561bf7279c222092674e7eb05fd0feab94899e9d82f2"
ALIKED_DESCRIPTOR_DIM = 128

LIGHTGLUE_FEATURES = "aliked"
LIGHTGLUE_WEIGHTS_FILENAME = "aliked_lightglue_v0-1_arxiv.pth"
LIGHTGLUE_WEIGHTS_SHA256 = "d975e965b105311a6143194852297dff4f02aea5cc2e10cecfed966ca0e22503"
LIGHTGLUE_REVISION = "5a650c444718caffc2669dc0094cde908f42dd73"

# Geometric verification settings used by ``pycolmap.verify_matches``. They
# mirror HLoc's defaults and are part of the checkpoint manifest.
VERIFICATION_MAX_TRIALS = 20000
VERIFICATION_MIN_INLIER_RATIO = 0.1


@dataclass(frozen=True, slots=True)
class FeatureProfile:
    """One validated extractor/matcher configuration."""

    name: str
    backend: str
    extractor: str
    matcher: str
    max_keypoints: int
    detection_threshold: float
    nms_radius: int
    match_threshold: float
    depth_confidence: float
    width_confidence: float
    description: str

    @property
    def is_neural(self) -> bool:
        return self.backend == BACKEND_ALIKED_LIGHTGLUE

    def parameters(self) -> dict[str, Any]:
        """Return the output-affecting parameters for the checkpoint manifest."""
        return {
            "extractor": self.extractor,
            "matcher": self.matcher,
            "max_keypoints": self.max_keypoints,
            "detection_threshold": self.detection_threshold,
            "nms_radius": self.nms_radius,
            "match_threshold": self.match_threshold,
            "depth_confidence": self.depth_confidence,
            "width_confidence": self.width_confidence,
        }


PROFILES: dict[str, FeatureProfile] = {
    PROFILE_SIFT_DEFAULT: FeatureProfile(
        name=PROFILE_SIFT_DEFAULT,
        backend=BACKEND_COLMAP_SIFT,
        extractor="COLMAP SIFT",
        matcher="COLMAP exhaustive/sequential",
        max_keypoints=0,
        detection_threshold=0.0,
        nms_radius=0,
        match_threshold=0.0,
        depth_confidence=0.0,
        width_confidence=0.0,
        description="Existing COLMAP SIFT baseline; production default and fallback.",
    ),
    PROFILE_ALIKED: FeatureProfile(
        name=PROFILE_ALIKED,
        backend=BACKEND_ALIKED_LIGHTGLUE,
        extractor=f"{ALIKED_MODEL_NAME} (ALIKED)",
        matcher="LightGlue (ALIKED weights)",
        max_keypoints=2048,
        detection_threshold=0.2,
        nms_radius=2,
        match_threshold=0.1,
        depth_confidence=-1.0,
        width_confidence=-1.0,
        description="Primary learned configuration: ALIKED-N16 + LightGlue.",
    ),
    PROFILE_ALIKED_FAST: FeatureProfile(
        name=PROFILE_ALIKED_FAST,
        backend=BACKEND_ALIKED_LIGHTGLUE,
        extractor=f"{ALIKED_MODEL_NAME} (ALIKED)",
        matcher="LightGlue (ALIKED weights)",
        max_keypoints=1024,
        detection_threshold=0.2,
        nms_radius=2,
        match_threshold=0.1,
        depth_confidence=-1.0,
        width_confidence=-1.0,
        description=(
            "Same ALIKED-N16 + LightGlue models with a reduced 1024-keypoint budget; "
            "not a separately trained model."
        ),
    ),
}


class FeatureProfileError(ValueError):
    """A backend/profile combination is not supported."""


def normalize_backend(value: str) -> str:
    """Return the canonical backend identifier or raise."""
    normalized = str(value).strip().upper()
    if normalized not in FEATURE_BACKENDS:
        raise FeatureProfileError(f"feature backend must be one of {FEATURE_BACKENDS}")
    return normalized


def normalize_profile(value: str) -> str:
    """Return the canonical profile name or raise."""
    normalized = str(value).strip().lower()
    if normalized not in PROFILES:
        raise FeatureProfileError(f"feature profile must be one of {FEATURE_PROFILES}")
    return normalized


def resolve_profile(backend: str, profile: str) -> FeatureProfile:
    """Resolve and cross-check a backend/profile pair.

    The backend selects the implementation; the profile selects model
    parameters. A mismatched pair (for example ``COLMAP_SIFT`` with
    ``aliked_lightglue``) is rejected instead of silently using one of them.
    """
    canonical_backend = normalize_backend(backend)
    canonical_profile = normalize_profile(profile)
    resolved = PROFILES[canonical_profile]
    if resolved.backend != canonical_backend:
        raise FeatureProfileError(
            f"profile {canonical_profile!r} belongs to backend {resolved.backend}, "
            f"not {canonical_backend}"
        )
    return resolved


def model_manifest() -> dict[str, Any]:
    """Return the model/revision identifiers recorded in diagnostics/manifests."""
    return {
        "extractor": ALIKED_MODEL_NAME,
        "extractor_weights": ALIKED_WEIGHTS_FILENAME,
        "extractor_sha256": ALIKED_WEIGHTS_SHA256,
        "matcher": "LightGlue",
        "matcher_revision": LIGHTGLUE_REVISION,
        "matcher_weights": LIGHTGLUE_WEIGHTS_FILENAME,
        "matcher_sha256": LIGHTGLUE_WEIGHTS_SHA256,
        "descriptor_dim": ALIKED_DESCRIPTOR_DIM,
    }


__all__ = [
    "ALIKED_DESCRIPTOR_DIM",
    "ALIKED_MODEL_NAME",
    "ALIKED_WEIGHTS_FILENAME",
    "ALIKED_WEIGHTS_SHA256",
    "BACKEND_ALIKED_LIGHTGLUE",
    "BACKEND_COLMAP_SIFT",
    "DEVICE_CHOICES",
    "FEATURE_BACKENDS",
    "FEATURE_PROFILES",
    "FeatureProfile",
    "FeatureProfileError",
    "LIGHTGLUE_FEATURES",
    "LIGHTGLUE_REVISION",
    "LIGHTGLUE_WEIGHTS_FILENAME",
    "LIGHTGLUE_WEIGHTS_SHA256",
    "PAIR_STRATEGIES",
    "PROFILES",
    "PROFILE_ALIKED",
    "PROFILE_ALIKED_FAST",
    "PROFILE_SIFT_DEFAULT",
    "VERIFICATION_MAX_TRIALS",
    "VERIFICATION_MIN_INLIER_RATIO",
    "model_manifest",
    "normalize_backend",
    "normalize_profile",
    "resolve_profile",
]
