"""Stable object-generation error codes (06_object_generation.md Sections 7.8,
8.6, 12.4 and 14.1).

A pipeline raises :class:`ObjectGenerationError` for an expected failure. The
worker records ``code`` and a user-safe message; the traceback stays in the
worker log and is never returned through the API.
"""

from __future__ import annotations

# Preprocessing (06 Section 7.8)
SOURCE_IMAGE_NOT_FOUND = "SOURCE_IMAGE_NOT_FOUND"
IMAGE_DECODE_FAILED = "IMAGE_DECODE_FAILED"
INVALID_IMAGE_DIMENSIONS = "INVALID_IMAGE_DIMENSIONS"
BACKGROUND_REMOVAL_FAILED = "BACKGROUND_REMOVAL_FAILED"
INVALID_FOREGROUND_MASK = "INVALID_FOREGROUND_MASK"
IMAGE_PREPROCESSING_FAILED = "IMAGE_PREPROCESSING_FAILED"

# Model execution (06 Section 8.6)
MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
MODEL_WEIGHTS_MISSING = "MODEL_WEIGHTS_MISSING"
MODEL_WEIGHTS_CHECKSUM_MISMATCH = "MODEL_WEIGHTS_CHECKSUM_MISMATCH"
GPU_UNAVAILABLE = "GPU_UNAVAILABLE"
GPU_OUT_OF_MEMORY = "GPU_OUT_OF_MEMORY"
CUDA_EXECUTION_FAILED = "CUDA_EXECUTION_FAILED"
MODEL_INFERENCE_FAILED = "MODEL_INFERENCE_FAILED"
MODEL_TIMEOUT = "MODEL_TIMEOUT"

# Mesh, export and validation (06 Sections 9, 11 and 12)
MESH_EXTRACTION_FAILED = "MESH_EXTRACTION_FAILED"
INVALID_MESH = "INVALID_MESH"
GLB_EXPORT_FAILED = "GLB_EXPORT_FAILED"
GLB_VALIDATION_FAILED = "GLB_VALIDATION_FAILED"
STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
RESULT_PERSISTENCE_FAILED = "RESULT_PERSISTENCE_FAILED"


class ObjectGenerationError(Exception):
    """An expected pipeline failure with a stable, user-safe code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ImagePreprocessingError(ObjectGenerationError):
    """Preprocessing failed before inference; no model work was attempted."""


class ModelUnavailableError(ObjectGenerationError):
    """Weights or a compatible device are unavailable."""


class InferenceError(ObjectGenerationError):
    """Inference failed after the model was initialized."""


class MeshError(ObjectGenerationError):
    """Mesh extraction or geometry validation failed."""


class ExportError(ObjectGenerationError):
    """GLB export or final asset validation failed."""
