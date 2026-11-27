"""Stable scene-reconstruction error codes (07_scene_reconstruction.md Section 17.1).

A pipeline raises :class:`SceneReconstructionError` for an expected failure. The
worker records ``code`` and a user-safe message; tool output, commands and
tracebacks stay in the worker log and are never returned through the API
(07 Section 17.4).
"""

from __future__ import annotations

# Input dataset (07 Sections 4.5, 4.8 and 17.1)
INSUFFICIENT_IMAGES = "INSUFFICIENT_IMAGES"
IMAGE_DECODE_FAILED = "IMAGE_DECODE_FAILED"
DUPLICATE_IMAGES = "DUPLICATE_IMAGES"
INVALID_SCENE_DATASET = "INVALID_SCENE_DATASET"
SOURCE_IMAGE_NOT_FOUND = "SOURCE_IMAGE_NOT_FOUND"

# Advisory image-quality analysis (11_image_quality_analysis.md Section 8.3).
# This is a failure of the analysis stage, never an image-quality rejection.
QUALITY_ANALYSIS_FAILED = "QUALITY_ANALYSIS_FAILED"

# COLMAP stages (07 Sections 6, 7, 8, 9 and 17.1)
FEATURE_EXTRACTION_FAILED = "FEATURE_EXTRACTION_FAILED"
FEATURE_MATCHING_FAILED = "FEATURE_MATCHING_FAILED"
NO_VALID_MATCHES = "NO_VALID_MATCHES"

# Optional neural feature backends (12_advanced_feature_matching.md Section 9).
# These are internal stage codes; user-facing messages stay generic and no
# descriptor, tensor or path is attached to them.
NEURAL_RUNTIME_UNAVAILABLE = "NEURAL_RUNTIME_UNAVAILABLE"
NEURAL_MODEL_UNAVAILABLE = "NEURAL_MODEL_UNAVAILABLE"
NEURAL_CUDA_UNAVAILABLE = "NEURAL_CUDA_UNAVAILABLE"
NEURAL_FEATURE_EXTRACTION_FAILED = "NEURAL_FEATURE_EXTRACTION_FAILED"
NEURAL_MATCHING_FAILED = "NEURAL_MATCHING_FAILED"
NEURAL_VERIFICATION_FAILED = "NEURAL_VERIFICATION_FAILED"
COLMAP_DATABASE_INCOMPATIBLE = "COLMAP_DATABASE_INCOMPATIBLE"
NEURAL_RESOURCE_EXHAUSTED = "NEURAL_RESOURCE_EXHAUSTED"
# Deterministic configuration/data errors: never eligible for SIFT fallback.
FEATURE_PAIR_LIMIT_EXCEEDED = "FEATURE_PAIR_LIMIT_EXCEEDED"
INSUFFICIENT_FEATURES = "INSUFFICIENT_FEATURES"

SPARSE_RECONSTRUCTION_FAILED = "SPARSE_RECONSTRUCTION_FAILED"
INSUFFICIENT_REGISTERED_IMAGES = "INSUFFICIENT_REGISTERED_IMAGES"
INVALID_CAMERA_PARAMETERS = "INVALID_CAMERA_PARAMETERS"
IMAGE_UNDISTORTION_FAILED = "IMAGE_UNDISTORTION_FAILED"

# OpenMVS stages (07 Section 10)
OPENMVS_IMPORT_FAILED = "OPENMVS_IMPORT_FAILED"
DENSE_RECONSTRUCTION_FAILED = "DENSE_RECONSTRUCTION_FAILED"
INSUFFICIENT_DENSE_POINTS = "INSUFFICIENT_DENSE_POINTS"
MESH_GENERATION_FAILED = "MESH_GENERATION_FAILED"
MESH_REFINEMENT_FAILED = "MESH_REFINEMENT_FAILED"
TEXTURE_GENERATION_FAILED = "TEXTURE_GENERATION_FAILED"

# Export and validation (07 Sections 11 and 18)
GLB_EXPORT_FAILED = "GLB_EXPORT_FAILED"
GLB_VALIDATION_FAILED = "GLB_VALIDATION_FAILED"

# Optional neural scene representation (15_neural_scene_reconstruction.md
# Section 9). Neural failures never fall back to a mesh result: the
# representation is explicit, so a splat task fails honestly and the previous
# current result is preserved by the transactional result service.
SPLAT_RUNTIME_UNAVAILABLE = "SPLAT_RUNTIME_UNAVAILABLE"
SPLAT_MODEL_UNSUPPORTED = "SPLAT_MODEL_UNSUPPORTED"
SPLAT_CUDA_UNAVAILABLE = "SPLAT_CUDA_UNAVAILABLE"
SPLAT_DATASET_CONVERSION_FAILED = "SPLAT_DATASET_CONVERSION_FAILED"
SPLAT_INVALID_CAMERAS = "SPLAT_INVALID_CAMERAS"
SPLAT_INSUFFICIENT_POINTS = "SPLAT_INSUFFICIENT_POINTS"
SPLAT_INSUFFICIENT_IMAGES = "SPLAT_INSUFFICIENT_IMAGES"
SPLAT_TRAINING_FAILED = "SPLAT_TRAINING_FAILED"
SPLAT_CHECKPOINT_INVALID = "SPLAT_CHECKPOINT_INVALID"
SPLAT_EXPORT_FAILED = "SPLAT_EXPORT_FAILED"
SPLAT_PLY_INVALID = "SPLAT_PLY_INVALID"
SPLAT_ARTIFACT_TOO_LARGE = "SPLAT_ARTIFACT_TOO_LARGE"
SPLAT_RESOURCE_EXHAUSTED = "SPLAT_RESOURCE_EXHAUSTED"
SPLAT_TIMEOUT = "SPLAT_TIMEOUT"
SCENE_REPRESENTATION_UNSUPPORTED = "SCENE_REPRESENTATION_UNSUPPORTED"
SCENE_WORKER_INCOMPATIBLE = "SCENE_WORKER_INCOMPATIBLE"

# Optional post-reconstruction enhancement (14_mesh_texture_enhancement.md
# Section 9). Optional-stage failures fall back to the last valid scene asset;
# malformed source geometry still fails hard.
MESH_CLEANUP_FAILED = "MESH_CLEANUP_FAILED"
NORMAL_GENERATION_FAILED = "NORMAL_GENERATION_FAILED"
SIMPLIFICATION_FAILED = "SIMPLIFICATION_FAILED"
SIMPLIFIER_UNAVAILABLE = "SIMPLIFIER_UNAVAILABLE"
UV_GENERATION_FAILED = "UV_GENERATION_FAILED"
TEXTURE_BAKING_FAILED = "TEXTURE_BAKING_FAILED"
ENHANCEMENT_RESOURCE_EXHAUSTED = "ENHANCEMENT_RESOURCE_EXHAUSTED"
ENHANCEMENT_FAILED = "ENHANCEMENT_FAILED"

# Resources and external tools (07 Sections 14, 15 and 17.1)
INSUFFICIENT_STORAGE = "INSUFFICIENT_STORAGE"
MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
CUDA_EXECUTION_FAILED = "CUDA_EXECUTION_FAILED"
TOOL_TIMEOUT = "TOOL_TIMEOUT"
EXTERNAL_TOOL_UNAVAILABLE = "EXTERNAL_TOOL_UNAVAILABLE"


class SceneReconstructionError(Exception):
    """An expected pipeline failure with a stable, user-safe code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class SceneCancelled(Exception):
    """Raised when the worker observed a cooperative cancellation request.

    This is not a failure: the worker adapter maps it to
    ``GenerationCancelled`` so the task ends ``CANCELLED``.
    """


class DatasetError(SceneReconstructionError):
    """Input validation or workspace preparation failed."""


class ToolError(SceneReconstructionError):
    """An external tool is unavailable or failed to execute."""


class ReconstructionError(SceneReconstructionError):
    """A COLMAP or OpenMVS stage produced an unusable result."""


class SceneExportError(SceneReconstructionError):
    """GLB export or final asset validation failed."""


class SplatError(SceneReconstructionError):
    """Neural dataset conversion, training, checkpoint export or PLY validation failed."""


class ResourceError(SceneReconstructionError):
    """Storage, memory or CUDA resources are insufficient."""


class FeatureMatchError(SceneReconstructionError):
    """A feature backend failed; the pipeline may fall back to SIFT."""


# Recoverable neural-stage failures that may trigger the configured SIFT
# fallback. Dataset and deterministic configuration errors are deliberately
# absent: falling back would hide a problem the user must fix.
RECOVERABLE_FEATURE_FAILURES: frozenset[str] = frozenset(
    {
        NEURAL_RUNTIME_UNAVAILABLE,
        NEURAL_MODEL_UNAVAILABLE,
        NEURAL_CUDA_UNAVAILABLE,
        NEURAL_FEATURE_EXTRACTION_FAILED,
        NEURAL_MATCHING_FAILED,
        NEURAL_VERIFICATION_FAILED,
        COLMAP_DATABASE_INCOMPATIBLE,
        NEURAL_RESOURCE_EXHAUSTED,
        MEMORY_LIMIT_EXCEEDED,
        NO_VALID_MATCHES,
        INSUFFICIENT_FEATURES,
        FEATURE_EXTRACTION_FAILED,
        FEATURE_MATCHING_FAILED,
    }
)


def is_recoverable_feature_failure(error: BaseException) -> bool:
    """Return True when a feature-stage failure may fall back to SIFT."""
    code = getattr(error, "error_code", None)
    return isinstance(error, SceneReconstructionError) and code in RECOVERABLE_FEATURE_FAILURES


__all__ = [
    "COLMAP_DATABASE_INCOMPATIBLE",
    "CUDA_EXECUTION_FAILED",
    "DENSE_RECONSTRUCTION_FAILED",
    "DUPLICATE_IMAGES",
    "EXTERNAL_TOOL_UNAVAILABLE",
    "FEATURE_EXTRACTION_FAILED",
    "FEATURE_MATCHING_FAILED",
    "FEATURE_PAIR_LIMIT_EXCEEDED",
    "FeatureMatchError",
    "GLB_EXPORT_FAILED",
    "GLB_VALIDATION_FAILED",
    "IMAGE_DECODE_FAILED",
    "IMAGE_UNDISTORTION_FAILED",
    "INSUFFICIENT_DENSE_POINTS",
    "INSUFFICIENT_FEATURES",
    "INSUFFICIENT_IMAGES",
    "INSUFFICIENT_REGISTERED_IMAGES",
    "INSUFFICIENT_STORAGE",
    "INVALID_CAMERA_PARAMETERS",
    "INVALID_SCENE_DATASET",
    "MEMORY_LIMIT_EXCEEDED",
    "MESH_GENERATION_FAILED",
    "MESH_REFINEMENT_FAILED",
    "NEURAL_CUDA_UNAVAILABLE",
    "NEURAL_FEATURE_EXTRACTION_FAILED",
    "NEURAL_MATCHING_FAILED",
    "NEURAL_MODEL_UNAVAILABLE",
    "NEURAL_RESOURCE_EXHAUSTED",
    "NEURAL_RUNTIME_UNAVAILABLE",
    "NEURAL_VERIFICATION_FAILED",
    "NO_VALID_MATCHES",
    "OPENMVS_IMPORT_FAILED",
    "QUALITY_ANALYSIS_FAILED",
    "RECOVERABLE_FEATURE_FAILURES",
    "SOURCE_IMAGE_NOT_FOUND",
    "SPARSE_RECONSTRUCTION_FAILED",
    "SceneCancelled",
    "SceneExportError",
    "SceneReconstructionError",
    "SCENE_REPRESENTATION_UNSUPPORTED",
    "SCENE_WORKER_INCOMPATIBLE",
    "SPLAT_ARTIFACT_TOO_LARGE",
    "SPLAT_CHECKPOINT_INVALID",
    "SPLAT_CUDA_UNAVAILABLE",
    "SPLAT_DATASET_CONVERSION_FAILED",
    "SPLAT_EXPORT_FAILED",
    "SPLAT_INSUFFICIENT_IMAGES",
    "SPLAT_INSUFFICIENT_POINTS",
    "SPLAT_INVALID_CAMERAS",
    "SPLAT_MODEL_UNSUPPORTED",
    "SPLAT_PLY_INVALID",
    "SPLAT_RESOURCE_EXHAUSTED",
    "SPLAT_RUNTIME_UNAVAILABLE",
    "SPLAT_TIMEOUT",
    "SPLAT_TRAINING_FAILED",
    "SplatError",
    "TEXTURE_GENERATION_FAILED",
    "TOOL_TIMEOUT",
    "ToolError",
    "DatasetError",
    "ReconstructionError",
    "ResourceError",
    "is_recoverable_feature_failure",
]
