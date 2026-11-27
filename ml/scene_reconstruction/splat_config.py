"""Validated configuration for the optional Gaussian-splat representation.

The neural path is deliberately represented by a small immutable value object:
the training entry point, dataset adapter, exporter and the worker all read the
same validated settings, and the backend maps its ``SCENE_SPLAT_*`` variables
onto this class in one place (``config.build_config_from_settings``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPRESENTATION_MESH = "MESH"
REPRESENTATION_GAUSSIAN_SPLAT = "GAUSSIAN_SPLAT"
REPRESENTATIONS: tuple[str, ...] = (REPRESENTATION_MESH, REPRESENTATION_GAUSSIAN_SPLAT)

METHOD_MESH = "COLMAP_OPENMVS"
METHOD_SPLATFACTO = "NERFSTUDIO_SPLATFACTO"

MODEL_SPLATFACTO = "splatfacto"
SUPPORTED_MODELS: tuple[str, ...] = (MODEL_SPLATFACTO,)
# ``splatfacto-big`` is intentionally absent: upstream documents roughly 12 GB
# for it and the target card has 12 GB total, so it is rejected by validation
# instead of failing at run time.

SPLAT_FORMAT = "PLY"
SPLAT_MIME_TYPE = "application/octet-stream"
SPLAT_RESULT_FILENAME = "scene.ply"
GLB_FORMAT = "GLB"
GLB_MIME_TYPE = "model/gltf-binary"

# COLMAP camera models the pinned Nerfstudio importer is trusted with. The splat
# path consumes the *undistorted* dense model, which COLMAP writes as SIMPLE_PINHOLE
# or PINHOLE; anything else means the wrong model directory was supplied.
SUPPORTED_CAMERA_MODELS: frozenset[str] = frozenset({"SIMPLE_PINHOLE", "PINHOLE"})

# Nerfstudio 1.1.5 ``ns-export gaussian-splat`` binary PLY property order for
# spherical-harmonic degree 3. This is the exact dialect the frontend renderer
# and the independent validator accept; a generic point-cloud PLY is not enough.
SH_DEGREE_DEFAULT = 3
_F_DC = 3
F_REST_PER_DEGREE = {0: 0, 1: 9, 2: 24, 3: 45}


def splat_ply_properties(sh_degree: int) -> tuple[str, ...]:
    """Return the expected PLY vertex properties for one SH degree."""
    if sh_degree not in F_REST_PER_DEGREE:
        raise ValueError("sh_degree must be between 0 and 3")
    properties = ["x", "y", "z", "nx", "ny", "nz"]
    properties.extend(f"f_dc_{index}" for index in range(_F_DC))
    properties.extend(f"f_rest_{index}" for index in range(F_REST_PER_DEGREE[sh_degree]))
    properties.extend(
        ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    )
    return tuple(properties)


@dataclass(frozen=True, slots=True)
class SplatConfig:
    """Everything that affects Splatfacto training and export."""

    enabled: bool = False
    model: str = MODEL_SPLATFACTO
    max_iterations: int = 30_000
    image_scale: float = 1.0
    max_image_dimension: int = 1600
    checkpoint_interval: int = 5000
    max_vram_mb: int = 9000
    device: str = "cuda"
    max_artifact_bytes: int = 512 * 1024 * 1024
    timeout_seconds: int = 7200
    min_registered_images: int = 8
    sh_degree: int = SH_DEGREE_DEFAULT
    # The pinned Nerfstudio/gsplat packages live in a dedicated target directory
    # that is added to PYTHONPATH only for the training/export subprocess. The
    # interpreter is the verified scene-worker venv (torch/torchvision are not
    # duplicated), so isolation is per package directory, not a second torch.
    python_executable: Path = Path("/opt/venv/bin/python")
    site_packages: Path = Path("/opt/splat-site")
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        model = self.model.strip().lower()
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"splat model must be one of {SUPPORTED_MODELS}; splatfacto-big does not "
                "fit the 12 GB target profile"
            )
        object.__setattr__(self, "model", model)
        device = self.device.strip().lower()
        if device not in {"cuda", "cpu"}:
            raise ValueError("splat device must be 'cuda' or 'cpu'")
        object.__setattr__(self, "device", device)
        if not 100 <= self.max_iterations <= 200_000:
            raise ValueError("max_iterations must be between 100 and 200000")
        if not 0.1 <= self.image_scale <= 1.0:
            raise ValueError("image_scale must be in (0.1, 1.0]")
        if not 256 <= self.max_image_dimension <= 8192:
            raise ValueError("max_image_dimension must be between 256 and 8192")
        if not 100 <= self.checkpoint_interval <= self.max_iterations:
            raise ValueError("checkpoint_interval must be between 100 and max_iterations")
        if not 1024 <= self.max_vram_mb <= 16384:
            raise ValueError("max_vram_mb must be between 1024 and 16384")
        if not 1024 * 1024 <= self.max_artifact_bytes <= 4 * 1024 * 1024 * 1024:
            raise ValueError("max_artifact_bytes must be between 1 MiB and 4 GiB")
        if not 60 <= self.timeout_seconds <= 86_400:
            raise ValueError("timeout_seconds must be between 60 and 86400")
        if self.min_registered_images < 1:
            raise ValueError("min_registered_images must be at least 1")
        if not 0 <= self.sh_degree <= 3:
            raise ValueError("sh_degree must be between 0 and 3")
        if not self.python_executable.is_absolute():
            raise ValueError("python_executable must be an absolute path")
        if not self.site_packages.is_absolute():
            raise ValueError("site_packages must be an absolute path")

    def as_manifest(self) -> dict[str, Any]:
        """Return the JSON-safe settings that affect training/export output."""
        return {
            "representation": REPRESENTATION_GAUSSIAN_SPLAT,
            "method": METHOD_SPLATFACTO,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "image_scale": self.image_scale,
            "max_image_dimension": self.max_image_dimension,
            "checkpoint_interval": self.checkpoint_interval,
            "max_vram_mb": self.max_vram_mb,
            "device": self.device,
            "max_artifact_bytes": self.max_artifact_bytes,
            "timeout_seconds": self.timeout_seconds,
            "min_registered_images": self.min_registered_images,
            "sh_degree": self.sh_degree,
        }


__all__ = [
    "F_REST_PER_DEGREE",
    "GLB_FORMAT",
    "GLB_MIME_TYPE",
    "METHOD_MESH",
    "METHOD_SPLATFACTO",
    "MODEL_SPLATFACTO",
    "REPRESENTATION_GAUSSIAN_SPLAT",
    "REPRESENTATION_MESH",
    "REPRESENTATIONS",
    "SH_DEGREE_DEFAULT",
    "SPLAT_FORMAT",
    "SPLAT_MIME_TYPE",
    "SPLAT_RESULT_FILENAME",
    "SUPPORTED_CAMERA_MODELS",
    "SUPPORTED_MODELS",
    "SplatConfig",
    "splat_ply_properties",
]
