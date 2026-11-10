"""Configuration shared by the object-generation pipeline modules.

The values are supplied by the worker adapter (``app.tasks.object_pipeline``)
from the validated backend settings, so this package never reads the process
environment directly. Defaults follow 06_object_generation.md Section 8.4 and
Section 16.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ObjectGenerationConfig:
    """Everything the TripoSR pipeline needs for one task.

    ``model_dir`` must contain the pinned ``config.yaml`` and ``model.ckpt``;
    it is populated once by ``python -m object_generation.download_models`` and
    mounted as a persistent volume (06 Section 4.5).
    """

    model_dir: Path
    model_revision: str
    model_sha256: str
    device: str = "cuda:0"
    allow_cpu_fallback: bool = False
    chunk_size: int = 8192
    mc_resolution: int = 256
    remove_background: bool = True
    foreground_ratio: float = 0.85
    output_format: str = "glb"
    bake_texture: bool = False
    texture_resolution: int = 2048
    max_task_seconds: int = 600
    rembg_model: str = "u2net"
    # TripoSR normalizes the input to this conditioning size, then places the
    # foreground at `foreground_ratio` of it (06 Sections 7.5 and 8.4).
    input_size: int = 512

    def __post_init__(self) -> None:
        if not self.model_dir.is_absolute():
            message = "model_dir must be an absolute path"
            raise ValueError(message)
        if self.output_format.lower() != "glb":
            message = "The MVP only supports GLB output (06 Section 11.1)"
            raise ValueError(message)
        if self.chunk_size < 1:
            message = "chunk_size must be positive"
            raise ValueError(message)
        if not 32 <= self.mc_resolution <= 512:
            message = "mc_resolution must be between 32 and 512"
            raise ValueError(message)
        if not 0 < self.foreground_ratio <= 1:
            message = "foreground_ratio must be in (0, 1]"
            raise ValueError(message)
        if self.max_task_seconds < 1:
            message = "max_task_seconds must be positive"
            raise ValueError(message)
        if self.bake_texture:
            message = (
                "Texture baking is not implemented in the MVP; leave "
                "OBJECT_BAKE_TEXTURE=false (06 Section 10.3)"
            )
            raise ValueError(message)
