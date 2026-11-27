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
from .generator_base import GeneratorResult, PreprocessingCapabilities
from .mesh_processor import MeshStats, validate_mesh
from .model_loader import ModelLoadResult, get_model, release_model

logger = logging.getLogger(__name__)

# The pinned TripoSR source commit from ml/object_generation/Dockerfile. It is
# recorded as the generator revision so a result can be traced to its code.
TRIPOSR_SOURCE_REVISION = "d26e33181947bbbc4c6fc0f5734e1ec6c080956e"


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


def cuda_peak_bytes(device: str) -> tuple[int | None, int | None]:
    """Return the peak allocated/reserved CUDA bytes, or ``None`` off-device.

    ``torch.cuda.reset_peak_memory_stats`` is called by the adapter before a
    task so the value describes this task, not the whole process lifetime.
    A CPU run reports nothing rather than a fabricated zero (13 Section 5.5).
    """
    try:
        import torch

        if not device.startswith("cuda") or not torch.cuda.is_available():
            return (None, None)
        index = int(device.split(":", 1)[1]) if ":" in device else 0
        return (
            int(torch.cuda.max_memory_allocated(index)),
            int(torch.cuda.max_memory_reserved(index)),
        )
    except Exception:  # measurement must never fail a task
        return (None, None)


def _reset_cuda_peak(device: str) -> None:
    try:
        import torch

        if device.startswith("cuda") and torch.cuda.is_available():
            index = int(device.split(":", 1)[1]) if ":" in device else 0
            torch.cuda.reset_peak_memory_stats(index)
    except Exception:  # measurement must never fail a task
        return


class TripoSRAdapter:
    """The TripoSR generator behind the shared :class:`ObjectGenerator` contract.

    Inference is delegated to :class:`TripoSRGenerator`, so the model call,
    mesh extraction, timing and error mapping are the existing Phase 5 code.
    """

    name = "triposr"
    revision = TRIPOSR_SOURCE_REVISION

    def __init__(
        self,
        config: ObjectGenerationConfig,
        *,
        model_result: ModelLoadResult | None = None,
    ) -> None:
        self._config = config
        self._model_result = model_result
        self.model_id = config.model_id
        self.model_revision = config.model_revision

    @property
    def device(self) -> str:
        """The device selected for inference (``cuda:0``/``cpu``)."""
        if self._model_result is not None:
            return self._model_result.device.device
        return self._config.device

    def capabilities(self) -> PreprocessingCapabilities:
        """TripoSR takes the 512 px RGB composite produced by the shared step."""
        return PreprocessingCapabilities(
            mode="rgb_composite",
            background_removal=self._config.remove_background,
            alpha=False,
            foreground_crop=True,
            foreground_ratio=True,
            input_size=self._config.input_size,
            color_mode="RGB",
        )

    def load(self) -> None:
        """Load and verify the pinned TripoSR model once per process."""
        if self._model_result is None:
            self._model_result = get_model(self._config)

    def generate(self, image: Any, *, started_at: float) -> GeneratorResult:
        """Run the existing TripoSR inference and return a contract result."""
        self.load()
        _reset_cuda_peak(self._config.device)
        generator = TripoSRGenerator(self._config, model_result=self._model_result)
        mesh = generator.generate(image, started_at=started_at)
        allocated, reserved = cuda_peak_bytes(generator.device)
        return GeneratorResult(
            mesh=mesh.mesh,
            name=self.name,
            revision=self.revision,
            model_id=self.model_id,
            model_revision=self.model_revision,
            inference_seconds=mesh.inference_seconds,
            postprocessing_seconds=mesh.extraction_seconds,
            peak_cuda_allocated_bytes=allocated,
            peak_cuda_reserved_bytes=reserved,
            has_textures=False,
            texture_resolution=None,
            diagnostics={
                "device": generator.device,
                "chunk_size": self._config.chunk_size,
                "mc_resolution": self._config.mc_resolution,
                "preprocessing_profile": "triposr_default",
                "mesh_stats": mesh.stats.as_metadata(),
            },
        )

    def unload(self) -> None:
        """Release the model and its device memory."""
        release_model(self._config)
        self._model_result = None

    @property
    def _generator(self) -> TripoSRGenerator:
        return TripoSRGenerator(self._config, model_result=self._model_result)
