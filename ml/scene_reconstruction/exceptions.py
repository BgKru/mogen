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

# COLMAP stages (07 Sections 6, 7, 8, 9 and 17.1)
FEATURE_EXTRACTION_FAILED = "FEATURE_EXTRACTION_FAILED"
FEATURE_MATCHING_FAILED = "FEATURE_MATCHING_FAILED"
NO_VALID_MATCHES = "NO_VALID_MATCHES"
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


class ResourceError(SceneReconstructionError):
    """Storage, memory or CUDA resources are insufficient."""


__all__ = [
    "CUDA_EXECUTION_FAILED",
    "DENSE_RECONSTRUCTION_FAILED",
    "DUPLICATE_IMAGES",
    "EXTERNAL_TOOL_UNAVAILABLE",
    "FEATURE_EXTRACTION_FAILED",
    "FEATURE_MATCHING_FAILED",
    "GLB_EXPORT_FAILED",
    "GLB_VALIDATION_FAILED",
    "IMAGE_DECODE_FAILED",
    "IMAGE_UNDISTORTION_FAILED",
    "INSUFFICIENT_DENSE_POINTS",
    "INSUFFICIENT_IMAGES",
    "INSUFFICIENT_REGISTERED_IMAGES",
    "INSUFFICIENT_STORAGE",
    "INVALID_CAMERA_PARAMETERS",
    "INVALID_SCENE_DATASET",
    "MEMORY_LIMIT_EXCEEDED",
    "MESH_GENERATION_FAILED",
    "MESH_REFINEMENT_FAILED",
    "NO_VALID_MATCHES",
    "OPENMVS_IMPORT_FAILED",
    "SOURCE_IMAGE_NOT_FOUND",
    "SPARSE_RECONSTRUCTION_FAILED",
    "SceneCancelled",
    "SceneExportError",
    "SceneReconstructionError",
    "TEXTURE_GENERATION_FAILED",
    "TOOL_TIMEOUT",
    "ToolError",
    "DatasetError",
    "ReconstructionError",
    "ResourceError",
]
