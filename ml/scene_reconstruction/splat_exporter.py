"""Export a trained Splatfacto checkpoint to the pinned Gaussian PLY (15 §4.4/5.3).

The exporter reads the tensors of a Nerfstudio checkpoint and writes the exact
property set, order and dtypes of ``ns-export gaussian-splat`` in 1.1.5. It
filters non-finite and sub-threshold-opacity Gaussians the same way upstream
does, validates the result independently, hashes it and only then publishes it
atomically, so a partial PLY can never be registered.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .exceptions import (
    SPLAT_ARTIFACT_TOO_LARGE,
    SPLAT_CHECKPOINT_INVALID,
    SPLAT_EXPORT_FAILED,
    SplatError,
)
from .splat_config import splat_ply_properties
from .splat_validator import SplatPlyValidation, validate_splat_ply

logger = logging.getLogger(__name__)

# logit(1/255): Gaussians below this opacity are skipped by the CUDA rasterizer
# and by the upstream exporter (15 Section 5.3).
LOW_OPACITY_LOGIT = -5.5373
_WRITE_CHUNK_ROWS = 262_144


@dataclass(frozen=True, slots=True)
class SplatExportResult:
    """A validated Gaussian PLY ready for transactional registration."""

    path: Path
    sha256: str
    file_size_bytes: int
    gaussian_count: int
    gaussian_count_before_filter: int
    sh_degree: int
    training_step: int
    validation: SplatPlyValidation

    def as_metadata(self) -> dict[str, Any]:
        metadata = self.validation.as_metadata()
        metadata.update(
            {
                "gaussian_count_before_filter": self.gaussian_count_before_filter,
                "training_step": self.training_step,
            }
        )
        return metadata


def _tensor_to_numpy(state: dict[str, Any], *keys: str) -> np.ndarray:
    """Return one checkpoint tensor, accepting both Splatfacto key layouts.

    Nerfstudio 1.1.5 stores the Gaussian parameters in a ``ParameterDict``
    (``_model.gauss_params.means``); older checkpoints use ``model.means``.
    """
    value = None
    for key in keys:
        value = state.get(key)
        if value is not None:
            break
    if value is None:
        raise SplatError(
            SPLAT_CHECKPOINT_INVALID, "The Splatfacto checkpoint is missing a model tensor."
        )
    try:
        array = value.detach().cpu().numpy()
    except AttributeError as exc:
        raise SplatError(
            SPLAT_CHECKPOINT_INVALID, "The Splatfacto checkpoint contains an invalid tensor."
        ) from exc
    return np.asarray(array, dtype=np.float64)


def _register_safe_numpy_globals() -> None:
    """Allow the narrow NumPy scalar types Nerfstudio stores in checkpoints.

    ``weights_only=True`` refuses unknown globals. The pinned Splatfacto
    checkpoint contains a NumPy scalar (for example a scheduler/strategy value),
    so only that scalar class and its reconstruct helper are allowlisted; the
    rest of the checkpoint is still parsed as plain tensors.
    """
    import torch

    safe: list[object] = []
    try:
        from numpy._core.multiarray import _reconstruct, scalar  # noqa: PLC0415

        safe.extend([scalar, _reconstruct])
    except ImportError:  # pragma: no cover - NumPy 1.x layout
        try:
            from numpy.core.multiarray import _reconstruct, scalar  # noqa: PLC0415

            safe.extend([scalar, _reconstruct])
        except ImportError:
            pass
    try:
        import numpy as np  # noqa: PLC0415

        safe.append(np.float64)
        safe.append(np.dtype)
        with contextlib.suppress(AttributeError):  # older NumPy has no dtypes module
            safe.append(np.dtypes.Float64DType)
    except ImportError:  # pragma: no cover - numpy is a hard runtime dependency
        pass
    if safe:
        torch.serialization.add_safe_globals(safe)


def load_splat_state(checkpoint_path: Path) -> tuple[dict[str, Any], int]:
    """Load the pipeline tensors of a Splatfacto checkpoint.

    ``weights_only=True`` keeps the load restricted to tensors and primitives;
    the checkpoint is produced by the worker, but it is still parsed as data.
    """
    path = Path(checkpoint_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The Splatfacto checkpoint is missing.")
    try:
        import torch

        _register_safe_numpy_globals()
        state = torch.load(path, map_location="cpu", weights_only=True)
    except SplatError:
        raise
    except Exception as exc:  # torch raises several concrete loader errors
        raise SplatError(
            SPLAT_CHECKPOINT_INVALID, "The Splatfacto checkpoint could not be read."
        ) from exc
    if not isinstance(state, dict) or "pipeline" not in state:
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The file is not a Splatfacto checkpoint.")
    pipeline = state["pipeline"]
    if not isinstance(pipeline, dict):
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint pipeline state is invalid.")
    step = state.get("step", 0)
    return pipeline, int(step) if isinstance(step, int | float) else 0


def _model_arrays(pipeline: dict[str, Any], sh_degree: int) -> dict[str, np.ndarray]:
    arrays = {
        "means": _tensor_to_numpy(pipeline, "_model.gauss_params.means", "model.means"),
        "scales": _tensor_to_numpy(pipeline, "_model.gauss_params.scales", "model.scales"),
        "quats": _tensor_to_numpy(pipeline, "_model.gauss_params.quats", "model.quats"),
        "opacities": _tensor_to_numpy(pipeline, "_model.gauss_params.opacities", "model.opacities"),
        "features_dc": _tensor_to_numpy(
            pipeline, "_model.gauss_params.features_dc", "model.features_dc"
        ),
        "features_rest": _tensor_to_numpy(
            pipeline, "_model.gauss_params.features_rest", "model.features_rest"
        ),
    }
    if arrays["means"].ndim != 2 or arrays["means"].shape[1] != 3:
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint means have an invalid shape.")
    if arrays["scales"].shape != arrays["means"].shape:
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint scales have an invalid shape.")
    if arrays["quats"].shape != (arrays["means"].shape[0], 4):
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint quaternions are invalid.")
    if arrays["opacities"].reshape(-1, 1).shape[0] != arrays["means"].shape[0]:
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint opacities are invalid.")
    expected_rest = {0: 0, 1: 9, 2: 24, 3: 45}[sh_degree]
    features_rest = arrays["features_rest"]
    if features_rest.ndim != 3 or features_rest.shape[0] != arrays["means"].shape[0]:
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint SH features are invalid.")
    if int(np.prod(features_rest.shape[1:])) != expected_rest:
        raise SplatError(
            SPLAT_CHECKPOINT_INVALID,
            f"The checkpoint SH layout does not match sh_degree={sh_degree}.",
        )
    if arrays["features_dc"].shape != (arrays["means"].shape[0], 3):
        raise SplatError(SPLAT_CHECKPOINT_INVALID, "The checkpoint DC colours are invalid.")
    return arrays


def _ply_values(arrays: dict[str, np.ndarray], mask: np.ndarray) -> dict[str, np.ndarray]:
    """Map checkpoint tensors to PLY properties in upstream order."""
    features_rest = arrays["features_rest"][mask]
    count = features_rest.shape[0]
    rest = features_rest.transpose(0, 2, 1).reshape(count, -1)
    values: dict[str, np.ndarray] = {}
    means = arrays["means"][mask]
    for index, name in enumerate(("x", "y", "z")):
        values[name] = means[:, index]
    for name in ("nx", "ny", "nz"):
        values[name] = np.zeros(count, dtype=np.float64)
    features_dc = arrays["features_dc"][mask]
    for index in range(3):
        values[f"f_dc_{index}"] = features_dc[:, index]
    for index in range(rest.shape[1]):
        values[f"f_rest_{index}"] = rest[:, index]
    values["opacity"] = arrays["opacities"].reshape(-1)[mask]
    scales = arrays["scales"][mask]
    for index in range(3):
        values[f"scale_{index}"] = scales[:, index]
    quats = arrays["quats"][mask]
    for index in range(4):
        values[f"rot_{index}"] = quats[:, index]
    return values


def _write_ply_streaming(
    path: Path, properties: tuple[str, ...], values: dict[str, np.ndarray], count: int
) -> None:
    with Path(path).open("wb") as handle:
        handle.write(b"ply\n")
        handle.write(b"format binary_little_endian 1.0\n")
        handle.write(b"comment Generated by Nerfstudio 1.1.5\n")
        handle.write(b"comment Vertical Axis: z\n")
        handle.write(f"element vertex {count}\n".encode())
        for name in properties:
            handle.write(f"property float {name}\n".encode())
        handle.write(b"end_header\n")
        for start in range(0, count, _WRITE_CHUNK_ROWS):
            stop = min(start + _WRITE_CHUNK_ROWS, count)
            block = np.stack(
                [np.asarray(values[name][start:stop], dtype="<f4") for name in properties],
                axis=1,
            )
            handle.write(block.tobytes(order="C"))


def export_splat_ply(
    checkpoint_path: Path,
    output_path: Path,
    *,
    sh_degree: int = 3,
    max_artifact_bytes: int = 512 * 1024 * 1024,
    max_gaussians: int = 5_000_000,
) -> SplatExportResult:
    """Write, validate and atomically publish a Gaussian PLY."""
    pipeline, step = load_splat_state(checkpoint_path)
    arrays = _model_arrays(pipeline, sh_degree)
    count_before = int(arrays["means"].shape[0])
    if count_before < 1:
        raise SplatError(SPLAT_EXPORT_FAILED, "The checkpoint contains no Gaussians.")

    finite = np.ones(count_before, dtype=bool)
    for array in (
        arrays["means"],
        arrays["scales"],
        arrays["quats"],
        arrays["opacities"].reshape(count_before, -1),
        arrays["features_dc"],
        arrays["features_rest"].reshape(count_before, -1),
    ):
        finite &= np.isfinite(array).all(axis=1)
    opacity = arrays["opacities"].reshape(-1)
    keep = finite & (opacity >= LOW_OPACITY_LOGIT)
    count = int(np.count_nonzero(keep))
    if count < 1:
        raise SplatError(SPLAT_EXPORT_FAILED, "No Gaussian survived the export filters.")
    if count > max_gaussians:
        raise SplatError(
            SPLAT_ARTIFACT_TOO_LARGE, "The checkpoint contains more Gaussians than supported."
        )

    values = _ply_values(arrays, keep)
    properties = splat_ply_properties(sh_degree)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{output.stem}-", suffix=".ply.tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _write_ply_streaming(temporary, properties, values, count)
        validation = validate_splat_ply(
            temporary,
            sh_degree=sh_degree,
            max_artifact_bytes=max_artifact_bytes,
            max_gaussians=max_gaussians,
        )
        os.replace(temporary, output)
        final = validate_splat_ply(
            output,
            sh_degree=sh_degree,
            max_artifact_bytes=max_artifact_bytes,
            max_gaussians=max_gaussians,
        )
        if final.sha256 != validation.sha256 or final.file_size_bytes != validation.file_size_bytes:
            raise SplatError(SPLAT_EXPORT_FAILED, "The Gaussian PLY changed after validation.")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    logger.info(
        "splat_ply_exported",
        extra={
            "operation": "scene_reconstruction",
            "gaussian_count": count,
            "file_size_bytes": final.file_size_bytes,
        },
    )
    return SplatExportResult(
        path=output,
        sha256=final.sha256,
        file_size_bytes=final.file_size_bytes,
        gaussian_count=count,
        gaussian_count_before_filter=count_before,
        sh_degree=sh_degree,
        training_step=step,
        validation=final,
    )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file, used for manifest checks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "LOW_OPACITY_LOGIT",
    "SplatExportResult",
    "export_splat_ply",
    "load_splat_state",
    "sha256_file",
]
