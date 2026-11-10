"""TripoSR model loading and device management (06_object_generation.md 4.4-4.5).

The model is loaded once per worker process and kept in memory between tasks.
Weights are verified before use and never downloaded during a task: the
``model-init`` service populates the persistent cache offline
(06 Sections 4.5, 16).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ObjectGenerationConfig
from .exceptions import (
    GPU_UNAVAILABLE,
    MODEL_LOAD_FAILED,
    MODEL_WEIGHTS_CHECKSUM_MISMATCH,
    MODEL_WEIGHTS_MISSING,
    ModelUnavailableError,
)

logger = logging.getLogger(__name__)

# The official README reports ~6 GB for a default single-image run. Warn below
# that; do not hard-fail, because the reference is not a universal minimum.
_RECOMMENDED_VRAM_BYTES = 6 * 1024**3

_model_lock = threading.Lock()
_model_cache: dict[tuple[str, str], Any] = {}


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """The device actually selected for inference."""

    device: str
    name: str
    total_memory_bytes: int | None
    cuda_available: bool


@dataclass(frozen=True, slots=True)
class ModelLoadResult:
    """A loaded model and the initialization metrics (06 Section 15.5)."""

    model: Any
    device: DeviceInfo
    load_seconds: float


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file, streaming it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_files(config: ObjectGenerationConfig) -> str:
    """Verify that the cached weights exist and match the pinned checksum."""
    config_path = config.model_dir / "config.yaml"
    weight_path = config.model_dir / "model.ckpt"
    if not config_path.is_file() or not weight_path.is_file():
        raise ModelUnavailableError(
            MODEL_WEIGHTS_MISSING,
            "The TripoSR weights are not available in the model cache.",
        )
    if weight_path.stat().st_size < 1024 * 1024:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_MISSING, "The cached TripoSR checkpoint is incomplete."
        )

    checksum = sha256_file(weight_path)
    if config.model_sha256 and checksum != config.model_sha256.strip().lower():
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The cached TripoSR checkpoint does not match the pinned checksum.",
        )
    return checksum


def resolve_device(*, preferred: str, allow_cpu_fallback: bool) -> DeviceInfo:
    """Select the configured CUDA device or explain why it is unavailable.

    CPU is used only when it is explicitly allowed; a worker that was asked to
    use CUDA never silently switches to CPU (06 Section 5.3).
    """
    import torch

    cuda_available = bool(torch.cuda.is_available())
    requested = preferred.strip() or "cuda:0"

    if requested == "cpu":
        return DeviceInfo(
            device="cpu", name="cpu", total_memory_bytes=None, cuda_available=cuda_available
        )

    if not requested.startswith("cuda"):
        raise ModelUnavailableError(GPU_UNAVAILABLE, f"Unsupported device {requested!r}.")
    if not cuda_available:
        if allow_cpu_fallback:
            logger.warning(
                "object_gpu_unavailable_cpu_fallback",
                extra={"operation": "object_generation", "requested_device": requested},
            )
            return DeviceInfo(
                device="cpu",
                name="cpu (explicit CPU fallback)",
                total_memory_bytes=None,
                cuda_available=False,
            )
        raise ModelUnavailableError(
            GPU_UNAVAILABLE,
            "CUDA is not available and CPU fallback is disabled.",
        )

    try:
        index = int(requested.split(":", 1)[1]) if ":" in requested else 0
    except ValueError as exc:
        raise ModelUnavailableError(GPU_UNAVAILABLE, f"Invalid CUDA device {requested!r}.") from exc
    device_count = torch.cuda.device_count()
    if index < 0 or index >= device_count:
        raise ModelUnavailableError(
            GPU_UNAVAILABLE,
            f"CUDA device {index} is not visible ({device_count} device(s) detected).",
        )

    properties = torch.cuda.get_device_properties(index)
    total_memory = int(properties.total_memory)
    if total_memory < _RECOMMENDED_VRAM_BYTES:
        logger.warning(
            "object_gpu_low_vram",
            extra={
                "operation": "object_generation",
                "device": f"cuda:{index}",
                "total_memory_bytes": total_memory,
            },
        )
    return DeviceInfo(
        device=f"cuda:{index}",
        name=str(properties.name),
        total_memory_bytes=total_memory,
        cuda_available=True,
    )


def load_model(config: ObjectGenerationConfig) -> ModelLoadResult:
    """Load, configure and move the pinned TripoSR model to its device."""
    import torch
    from tsr.system import TSR

    started = time.perf_counter()
    verify_model_files(config)
    device = resolve_device(preferred=config.device, allow_cpu_fallback=config.allow_cpu_fallback)
    try:
        model = TSR.from_pretrained(
            str(config.model_dir), config_name="config.yaml", weight_name="model.ckpt"
        )
        model.renderer.set_chunk_size(config.chunk_size)
        model.to(device.device)
        model.eval()
        # The whole pipeline is inference-only; freezing gradients also trims
        # per-task memory a little.
        for parameter in model.parameters():
            parameter.requires_grad_(False)
    except ModelUnavailableError:
        raise
    except Exception as exc:
        raise ModelUnavailableError(
            MODEL_LOAD_FAILED, "The TripoSR model could not be initialized."
        ) from exc

    elapsed = time.perf_counter() - started
    logger.info(
        "triposr_model_loaded",
        extra={
            "operation": "object_generation",
            "device": device.device,
            "device_name": device.name,
            "load_seconds": round(elapsed, 3),
            "chunk_size": config.chunk_size,
            "torch_version": torch.__version__,
            "cuda_version": torch.version.cuda,
        },
    )
    return ModelLoadResult(model=model, device=device, load_seconds=elapsed)


def get_model(config: ObjectGenerationConfig) -> ModelLoadResult:
    """Return the process-wide model instance, loading it on first use."""
    key = (str(config.model_dir.resolve()), config.device)
    with _model_lock:
        cached = _model_cache.get(key)
        if cached is None:
            cached = load_model(config)
            _model_cache[key] = cached
        return cached


def warm_up(config: ObjectGenerationConfig) -> ModelLoadResult:
    """Initialize the model during worker startup (OBJ-AC-01/02/03)."""
    result = get_model(config)
    # Touch CUDA once so an unusable driver fails here, not mid-task.
    if result.device.device.startswith("cuda"):
        import torch

        torch.zeros(1, device=result.device.device)
        torch.cuda.synchronize(result.device.device)
        allocated = torch.cuda.memory_allocated(result.device.device)
        logger.info(
            "triposr_cuda_ready",
            extra={
                "operation": "object_generation",
                "device": result.device.device,
                "model_memory_bytes": int(allocated),
                "total_memory_bytes": result.device.total_memory_bytes,
            },
        )
    return result


def cleanup_gpu(device: str | None = None) -> None:
    """Release temporary tensors and the CUDA cache after a task (06 5.5)."""
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize(device or None)
            torch.cuda.empty_cache()
    except Exception:  # cleanup must never mask the task outcome
        logger.debug("cuda_cleanup_failed", extra={"operation": "object_generation"})
