"""TripoSR inference and mesh extraction (06_object_generation.md Sections 8-9).

Inference runs inside the worker process with ``torch.inference_mode``. CUDA
failures are translated into the stable error codes from 06 Section 8.6; raw
driver exceptions never reach a user.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from .config import ObjectGenerationConfig
from .exceptions import (
    CUDA_EXECUTION_FAILED,
    GPU_OUT_OF_MEMORY,
    MESH_EXTRACTION_FAILED,
    MODEL_INFERENCE_FAILED,
    MODEL_TIMEOUT,
    InferenceError,
    MeshError,
)
from .mesh_processor import MeshStats, validate_mesh
from .model_loader import ModelLoadResult, get_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GeneratedMesh:
    """Extracted geometry plus timing facts for diagnostics."""

    mesh: Any
    stats: MeshStats
    inference_seconds: float
    extraction_seconds: float


def _translate_inference_error(exc: Exception) -> InferenceError:
    """Map torch/CUDA exceptions to stable codes without leaking details."""
    try:
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return InferenceError(GPU_OUT_OF_MEMORY, "The GPU ran out of memory during inference.")
    except Exception:
        pass
    message = str(exc).lower()
    if "out of memory" in message:
        return InferenceError(GPU_OUT_OF_MEMORY, "The GPU ran out of memory during inference.")
    if "cuda" in message or "cudnn" in message or "cublas" in message:
        return InferenceError(CUDA_EXECUTION_FAILED, "CUDA execution failed during inference.")
    return InferenceError(MODEL_INFERENCE_FAILED, "Model inference failed.")


class TripoSRGenerator:
    """Run the pinned TripoSR model for one preprocessed image at a time."""

    def __init__(
        self,
        config: ObjectGenerationConfig,
        *,
        model_result: ModelLoadResult | None = None,
    ) -> None:
        self._config = config
        self._model_result = model_result or get_model(config)

    @property
    def device(self) -> str:
        """The device selected for inference."""
        return self._model_result.device.device

    def generate(self, image: Any, *, started_at: float | None = None) -> GeneratedMesh:
        """Run inference and marching-cubes extraction for one image."""
        import torch

        deadline = (started_at or time.monotonic()) + self._config.max_task_seconds
        model = self._model_result.model

        if time.monotonic() > deadline:
            raise InferenceError(MODEL_TIMEOUT, "Generation exceeded the configured time limit.")

        inference_started = time.perf_counter()
        try:
            with torch.inference_mode():
                scene_codes = model([image], device=self.device)
        except Exception as exc:
            raise _translate_inference_error(exc) from exc
        inference_seconds = time.perf_counter() - inference_started

        if time.monotonic() > deadline:
            raise InferenceError(MODEL_TIMEOUT, "Generation exceeded the configured time limit.")

        extraction_started = time.perf_counter()
        try:
            meshes = model.extract_mesh(scene_codes, True, resolution=self._config.mc_resolution)
        except Exception as exc:
            raise _translate_inference_error(exc) from exc
        extraction_seconds = time.perf_counter() - extraction_started

        if not meshes:
            raise MeshError(MESH_EXTRACTION_FAILED, "Mesh extraction returned no geometry.")
        stats = validate_mesh(meshes[0])

        logger.info(
            "triposr_inference_complete",
            extra={
                "operation": "object_generation",
                "device": self.device,
                "inference_seconds": round(inference_seconds, 3),
                "extraction_seconds": round(extraction_seconds, 3),
                "vertices_count": stats.vertices_count,
                "faces_count": stats.faces_count,
            },
        )
        return GeneratedMesh(
            mesh=meshes[0],
            stats=stats,
            inference_seconds=inference_seconds,
            extraction_seconds=extraction_seconds,
        )
