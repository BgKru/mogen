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

# Advisory image-quality analysis (11_image_quality_analysis.md Section 8.3).
# This is a failure of the analysis stage, never an image-quality rejection.
QUALITY_ANALYSIS_FAILED = "QUALITY_ANALYSIS_FAILED"

# Model execution (06 Section 8.6)
MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
MODEL_WEIGHTS_MISSING = "MODEL_WEIGHTS_MISSING"
MODEL_WEIGHTS_CHECKSUM_MISMATCH = "MODEL_WEIGHTS_CHECKSUM_MISMATCH"
GPU_UNAVAILABLE = "GPU_UNAVAILABLE"
GPU_OUT_OF_MEMORY = "GPU_OUT_OF_MEMORY"
CUDA_EXECUTION_FAILED = "CUDA_EXECUTION_FAILED"
MODEL_INFERENCE_FAILED = "MODEL_INFERENCE_FAILED"
MODEL_TIMEOUT = "MODEL_TIMEOUT"

# Generator selection and gated model access (13 Sections 4.2, 6 and 9).
GENERATOR_NOT_AVAILABLE = "GENERATOR_NOT_AVAILABLE"
GENERATOR_LICENSE_GATE_FAILED = "GENERATOR_LICENSE_GATE_FAILED"
MODEL_ACCESS_DENIED = "MODEL_ACCESS_DENIED"

# Mesh, export and validation (06 Sections 9, 11 and 12)
MESH_EXTRACTION_FAILED = "MESH_EXTRACTION_FAILED"
INVALID_MESH = "INVALID_MESH"
UNSUPPORTED_MESH_OUTPUT = "UNSUPPORTED_MESH_OUTPUT"
GLB_EXPORT_FAILED = "GLB_EXPORT_FAILED"
GLB_VALIDATION_FAILED = "GLB_VALIDATION_FAILED"
STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
RESULT_PERSISTENCE_FAILED = "RESULT_PERSISTENCE_FAILED"

# Optional mesh/texture enhancement (14_mesh_texture_enhancement.md Section 9).
# Optional-stage failures fall back to the last valid asset by default; a hard
# source-geometry failure keeps using INVALID_MESH and never falls back.
MESH_CLEANUP_FAILED = "MESH_CLEANUP_FAILED"
NORMAL_GENERATION_FAILED = "NORMAL_GENERATION_FAILED"
SIMPLIFICATION_FAILED = "SIMPLIFICATION_FAILED"
SIMPLIFIER_UNAVAILABLE = "SIMPLIFIER_UNAVAILABLE"
UV_GENERATION_FAILED = "UV_GENERATION_FAILED"
TEXTURE_BAKING_FAILED = "TEXTURE_BAKING_FAILED"
PBR_MATERIAL_INVALID = "PBR_MATERIAL_INVALID"
AI_TEXTURE_UNAVAILABLE = "AI_TEXTURE_UNAVAILABLE"
AI_TEXTURE_INVALID_OUTPUT = "AI_TEXTURE_INVALID_OUTPUT"
ENHANCEMENT_RESOURCE_EXHAUSTED = "ENHANCEMENT_RESOURCE_EXHAUSTED"
ENHANCEMENT_FAILED = "ENHANCEMENT_FAILED"


class ObjectGenerationError(Exception):
    """An expected pipeline failure with a stable, user-safe code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ImagePreprocessingError(ObjectGenerationError):
    """Preprocessing failed before inference; no model work was attempted."""


class ImageQualityAnalysisError(ObjectGenerationError):
    """The explicitly required image-quality analysis stage failed."""


class ModelUnavailableError(ObjectGenerationError):
    """Weights or a compatible device are unavailable."""


class GeneratorUnavailableError(ObjectGenerationError):
    """The configured generator is unknown, disabled, gated or not installed."""


class InferenceError(ObjectGenerationError):
    """Inference failed after the model was initialized."""


class MeshError(ObjectGenerationError):
    """Mesh extraction or geometry validation failed."""


class NormalizationError(MeshError):
    """A generator output cannot be normalized without losing information."""


class EnhancementError(MeshError):
    """An optional enhancement stage failed and fallback is disabled."""


class ExportError(ObjectGenerationError):
    """GLB export or final asset validation failed."""
