"""Stable Fast 3D generator adapter (13 Section 5.1).

The adapter consumes the RGBA foreground image prepared once by the shared
pipeline (decode -> rembg -> crop -> ratio) and calls the pinned upstream
``SF3D.run_image``. It never writes to storage, never touches the database and
never reports Celery progress; the pipeline and worker adapter own that.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from PIL import Image

from ..config import ObjectGenerationConfig
from ..exceptions import (
    GPU_OUT_OF_MEMORY,
    MODEL_INFERENCE_FAILED,
    InferenceError,
)
from ..generator import cuda_peak_bytes
from ..generator_base import GeneratorResult, PreprocessingCapabilities
from ..mesh_processor import validate_mesh
from ..model_loader import DeviceInfo, cleanup_gpu
from .loader import SF3DWeights, load_model

logger = logging.getLogger(__name__)

# The pinned upstream source commit (13 Section 2). Recorded with every result.
SF3D_SOURCE_REVISION = "ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2"


def _translate_inference_error(exc: Exception) -> InferenceError:
    """Map torch/CUDA failures to the stable generator-neutral codes."""
    try:
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return InferenceError(GPU_OUT_OF_MEMORY, "The GPU ran out of memory during inference.")
    except Exception:
        pass
    message = str(exc).lower()
    if "out of memory" in message:
        return InferenceError(GPU_OUT_OF_MEMORY, "The GPU ran out of memory during inference.")
    return InferenceError(MODEL_INFERENCE_FAILED, "SF3D inference failed.")


class SF3DAdapter:
    """Stable Fast 3D behind the shared :class:`ObjectGenerator` contract."""

    name = "sf3d"
    revision = SF3D_SOURCE_REVISION

    def __init__(self, config: ObjectGenerationConfig) -> None:
        self._config = config
        self._model: Any | None = None
        self._weights: SF3DWeights | None = None
        self._device: DeviceInfo | None = None
        self._load_seconds = 0.0
        self.model_id = config.sf3d.model_id
        self.model_revision = config.sf3d.model_revision

    def capabilities(self) -> PreprocessingCapabilities:
        """SF3D consumes the RGBA foreground; it never removes the background."""
        return PreprocessingCapabilities(
            mode="rgba_foreground",
            background_removal=self._config.remove_background,
            alpha=True,
            foreground_crop=True,
            foreground_ratio=True,
            input_size=None,
            color_mode="RGBA",
        )

    @property
    def device(self) -> str:
        """The device selected for inference (``cuda:0``/``cpu``)."""
        if self._device is not None:
            return self._device.device
        return self._config.device

    def load(self) -> None:
        """Verify the cache and load the pinned model once per process."""
        if self._model is not None:
            return
        model, weights, device, elapsed = load_model(self._config)
        if device.device == "cpu":
            # Upstream's texture baker chooses its own device from the
            # environment; keep it on CPU when the model was configured for CPU
            # so the two never disagree.
            os.environ.setdefault("SF3D_USE_CPU", "1")
        self._model = model
        self._weights = weights
        self._device = device
        self._load_seconds = elapsed

    def generate(self, image: Image.Image, *, started_at: float) -> GeneratorResult:
        """Run SF3D inference and return the contract result."""
        self.load()
        if not isinstance(image, Image.Image) or image.mode != "RGBA":
            raise InferenceError(
                MODEL_INFERENCE_FAILED,
                "SF3D requires the prepared RGBA foreground image.",
            )
        import torch

        device = self._device.device if self._device is not None else self._config.device
        self._reset_peak(device)
        settings = self._config.sf3d

        # Upstream run.py wraps inference in bf16 autocast on CUDA. That is the
        # pinned model's documented path; other adapters are unaffected.
        use_autocast = device.startswith("cuda")
        inference_started = time.perf_counter()
        try:
            context = (
                torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                if use_autocast
                else _null_context()
            )
            with torch.inference_mode(), context:
                mesh, _global = self._model.run_image(
                    image,
                    bake_resolution=settings.texture_resolution,
                    remesh=settings.remesh,
                    vertex_count=settings.target_vertex_count,
                )
        except Exception as exc:
            raise _translate_inference_error(exc) from exc
        inference_seconds = time.perf_counter() - inference_started

        postprocess_started = time.perf_counter()
        stats = validate_mesh(mesh)
        postprocessing_seconds = time.perf_counter() - postprocess_started
        allocated, reserved = cuda_peak_bytes(device)

        material = getattr(getattr(mesh, "visual", None), "material", None)
        texture = getattr(material, "baseColorTexture", None)
        texture_resolution = None
        if isinstance(texture, Image.Image):
            texture_resolution = int(max(texture.size))
        diagnostics: dict[str, Any] = {
            "device": device,
            "precision": "bf16" if use_autocast else "fp32",
            "preprocessing_profile": "sf3d_default",
            "texture_resolution": settings.texture_resolution,
            "remesh": settings.remesh,
            "target_vertex_count": settings.target_vertex_count,
            "model_background_removal": False,
            "load_seconds": round(self._load_seconds, 3),
            "mesh_stats": stats.as_metadata(),
            "has_normal_texture": bool(getattr(material, "normalTexture", None) is not None),
        }
        logger.info(
            "sf3d_inference_complete",
            extra={
                "operation": "object_generation",
                "generator": "sf3d",
                "device": device,
                "inference_seconds": round(inference_seconds, 3),
                "texture_resolution": settings.texture_resolution,
                "vertices_count": stats.vertices_count,
                "faces_count": stats.faces_count,
            },
        )
        return GeneratorResult(
            mesh=mesh,
            name=self.name,
            revision=self.revision,
            model_id=self.model_id,
            model_revision=self.model_revision,
            inference_seconds=inference_seconds,
            postprocessing_seconds=postprocessing_seconds,
            peak_cuda_allocated_bytes=allocated,
            peak_cuda_reserved_bytes=reserved,
            has_textures=bool(texture_resolution),
            texture_resolution=texture_resolution,
            diagnostics=diagnostics,
        )

    def unload(self) -> None:
        """Drop the model and release device memory."""
        self._model = None
        self._weights = None
        self._device = None
        cleanup_gpu()

    @staticmethod
    def _reset_peak(device: str) -> None:
        try:
            import torch

            if device.startswith("cuda") and torch.cuda.is_available():
                index = int(device.split(":", 1)[1]) if ":" in device else 0
                torch.cuda.reset_peak_memory_stats(index)
        except Exception:  # measurement must never fail a task
            return


class _null_context:
    """Tiny no-op context manager (avoids importing contextlib.nullcontext)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return False


__all__ = ["SF3DAdapter", "SF3D_SOURCE_REVISION"]
