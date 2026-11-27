"""Stable Fast 3D weight verification and loading (13 Section 5.1).

Weights are downloaded once by ``python -m object_generation.sf3d.download_models``
into a dedicated cache and verified against a manifest before every worker
start. Task execution never downloads anything: the runtime image sets
``HF_HUB_OFFLINE=1`` and the adapter only ever opens local files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import SF3DConfig
from ..exceptions import (
    MODEL_LOAD_FAILED,
    MODEL_WEIGHTS_CHECKSUM_MISMATCH,
    MODEL_WEIGHTS_MISSING,
    ModelUnavailableError,
)
from ..model_loader import DeviceInfo, resolve_device

logger = logging.getLogger(__name__)

CONFIG_NAME = "config.yaml"
WEIGHT_NAME = "model.safetensors"

# The pinned upstream checkout lives outside this package because the package is
# itself named ``sf3d``. When the object-generation directory is on ``sys.path``
# (for example `pytest` with this module's ``pythonpath = ["."]`` setting), a
# plain ``import sf3d`` resolves MOGEN's own subpackage and fails with a
# relative-import error. The worker installs the upstream source at
# /opt/sf3d-src; SF3D_SOURCE_ROOT overrides it for a different layout.
SF3D_SOURCE_ROOT = Path(os.environ.get("SF3D_SOURCE_ROOT") or "/opt/sf3d-src")
LOCAL_PACKAGE = Path(__file__).resolve().parent


def import_sf3d_system() -> Any:
    """Import the pinned upstream ``SF3D`` class, never MOGEN's own subpackage.

    The upstream checkout has no ``sf3d/__init__.py``, so it is a namespace
    package; a regular package later on ``sys.path`` would still win. The
    upstream directory is therefore registered under ``sf3d`` explicitly before
    the submodule import.
    """
    upstream_dir = SF3D_SOURCE_ROOT / "sf3d"
    if (upstream_dir / "system.py").is_file():
        current = sys.modules.get("sf3d")
        current_file = getattr(current, "__file__", None) if current is not None else None
        shadowed = current is not None and (
            current_file is not None
            and Path(current_file).resolve() == LOCAL_PACKAGE / "__init__.py"
        )
        if current is None or shadowed:
            if shadowed:
                for name in [
                    item for item in sys.modules if item == "sf3d" or item.startswith("sf3d.")
                ]:
                    sys.modules.pop(name, None)
            package = types.ModuleType("sf3d")
            package.__path__ = [str(upstream_dir)]
            sys.modules["sf3d"] = package
    from sf3d.system import SF3D

    return SF3D


@dataclass(frozen=True, slots=True)
class SF3DWeights:
    """The verified local files and their checksums."""

    model_dir: Path
    config_path: Path
    weight_path: Path
    config_sha256: str
    weight_sha256: str
    model_revision: str
    model_id: str
    load_seconds: float = 0.0


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, streaming it in 4 MiB blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_MISSING,
            "The SF3D checksum manifest is missing; run the SF3D model initializer.",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The SF3D checksum manifest is unreadable.",
        ) from exc
    if not isinstance(payload, dict):
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The SF3D checksum manifest is malformed.",
        )
    return payload


def _expected_digest(manifest: dict[str, Any], filename: str) -> str:
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The SF3D checksum manifest lists no files.",
        )
    entry = files.get(filename)
    if isinstance(entry, dict):
        entry = entry.get("sha256")
    if not isinstance(entry, str) or len(entry) != 64:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            f"The SF3D checksum manifest has no valid digest for {filename}.",
        )
    return entry.strip().lower()


def verify_weights(config: SF3DConfig) -> SF3DWeights:
    """Verify the pinned files and the manifest before loading the model."""
    if not config.enabled:
        raise ModelUnavailableError(MODEL_WEIGHTS_MISSING, "SF3D is not enabled for this worker.")
    config_path = config.model_dir / CONFIG_NAME
    weight_path = config.model_dir / WEIGHT_NAME
    missing = [path.name for path in (config_path, weight_path) if not path.is_file()]
    if missing:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_MISSING,
            "The SF3D weights are not available in the model cache.",
        )
    if weight_path.stat().st_size < 1024 * 1024:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_MISSING, "The cached SF3D checkpoint is incomplete."
        )

    manifest = _read_manifest(config.manifest_path)
    declared_revision = str(manifest.get("model_revision") or "")
    declared_id = str(manifest.get("model_id") or "")
    if declared_revision != config.model_revision:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The SF3D manifest describes a different pinned model revision.",
        )
    if declared_id and declared_id != config.model_id:
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The SF3D manifest describes a different model identifier.",
        )

    config_sha = sha256_file(config_path)
    weight_sha = sha256_file(weight_path)
    if config_sha != _expected_digest(manifest, CONFIG_NAME):
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The cached SF3D configuration does not match the pinned checksum.",
        )
    if weight_sha != _expected_digest(manifest, WEIGHT_NAME):
        raise ModelUnavailableError(
            MODEL_WEIGHTS_CHECKSUM_MISMATCH,
            "The cached SF3D checkpoint does not match the pinned checksum.",
        )
    return SF3DWeights(
        model_dir=config.model_dir,
        config_path=config_path,
        weight_path=weight_path,
        config_sha256=config_sha,
        weight_sha256=weight_sha,
        model_revision=config.model_revision,
        model_id=config.model_id,
    )


def resolve_sf3d_device(config: Any) -> DeviceInfo:
    """Select the device exactly like the TripoSR path does."""
    return resolve_device(preferred=config.device, allow_cpu_fallback=config.allow_cpu_fallback)


def load_model(config: Any) -> tuple[Any, SF3DWeights, DeviceInfo, float]:
    """Load and verify the pinned SF3D model on its configured device."""
    import torch

    started = time.perf_counter()
    weights = verify_weights(config.sf3d)
    device = resolve_sf3d_device(config)
    try:
        SF3D = import_sf3d_system()

        model = SF3D.from_pretrained(
            str(weights.model_dir),
            config_name=CONFIG_NAME,
            weight_name=WEIGHT_NAME,
        )
        model.to(device.device)
        model.eval()
        for parameter in model.parameters():
            parameter.requires_grad_(False)
    except ModelUnavailableError:
        raise
    except Exception as exc:
        raise ModelUnavailableError(
            MODEL_LOAD_FAILED, "The SF3D model could not be initialized."
        ) from exc

    elapsed = time.perf_counter() - started
    logger.info(
        "sf3d_model_loaded",
        extra={
            "operation": "object_generation",
            "generator": "sf3d",
            "device": device.device,
            "device_name": device.name,
            "load_seconds": round(elapsed, 3),
            "model_revision": config.sf3d.model_revision,
            "torch_version": torch.__version__,
            "cuda_version": torch.version.cuda,
        },
    )
    return model, weights, device, elapsed


__all__ = [
    "CONFIG_NAME",
    "WEIGHT_NAME",
    "SF3DWeights",
    "import_sf3d_system",
    "load_model",
    "resolve_sf3d_device",
    "sha256_file",
    "verify_weights",
]
