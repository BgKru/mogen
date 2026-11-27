"""Configuration shared by the object-generation pipeline modules.

The values are supplied by the worker adapter (``app.tasks.object_pipeline``)
from the validated backend settings, so this package never reads the process
environment directly. Defaults follow 06_object_generation.md Section 8.4 and
Section 16.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from image_quality import ImageQualityConfig

from .enhancement import EnhancementConfig

SUPPORTED_GENERATORS = ("triposr", "sf3d")
# Hunyuan3D is recognised so the configuration can explain why it is not
# available instead of silently treating the name as a typo. The adapter itself
# is not installed (13 Section 5.2 and Section 8 of the increment plan).
BLOCKED_GENERATORS = ("hunyuan3d",)
REMESH_MODES = ("none", "triangle", "quad")


@dataclass(frozen=True, slots=True)
class SF3DConfig:
    """Validated Stable Fast 3D settings (13 Section 6).

    SF3D is opt-in: the adapter refuses to initialise unless it is explicitly
    enabled, its weights live in their own cache, and a pinned revision plus a
    checksum manifest are configured. TripoSR defaults are untouched.
    """

    enabled: bool = False
    model_id: str = "stabilityai/stable-fast-3d"
    model_revision: str = ""
    model_dir: Path = Path("/models/sf3d")
    manifest_path: Path = Path("/models/sf3d/model-manifest.json")
    texture_resolution: int = 1024
    remesh: str = "none"
    target_vertex_count: int = -1

    def __post_init__(self) -> None:
        if not self.model_dir.is_absolute():
            message = "sf3d model_dir must be an absolute path"
            raise ValueError(message)
        if not self.manifest_path.is_absolute():
            message = "sf3d manifest_path must be an absolute path"
            raise ValueError(message)
        if not 128 <= self.texture_resolution <= 4096:
            message = "sf3d texture_resolution must be between 128 and 4096"
            raise ValueError(message)
        if self.remesh not in REMESH_MODES:
            message = f"sf3d remesh must be one of {REMESH_MODES}"
            raise ValueError(message)
        if self.target_vertex_count != -1 and self.target_vertex_count < 100:
            message = "sf3d target_vertex_count must be -1 or at least 100"
            raise ValueError(message)
        if self.enabled:
            if not self.model_revision.strip():
                message = "sf3d model_revision is required when SF3D is enabled"
                raise ValueError(message)
            if self.model_revision.strip().lower() in {"main", "master", "head"}:
                message = "sf3d model_revision must be an immutable revision"
                raise ValueError(message)

    def as_metadata(self) -> dict[str, object]:
        """Return the non-secret settings recorded with the result."""
        return {
            "enabled": self.enabled,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "texture_resolution": self.texture_resolution,
            "remesh": self.remesh,
            "target_vertex_count": self.target_vertex_count,
        }


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
    model_id: str = "stabilityai/TripoSR"
    device: str = "cuda:0"
    allow_cpu_fallback: bool = False
    chunk_size: int = 8192
    mc_resolution: int = 256
    remove_background: bool = True
    foreground_ratio: float = 0.85
    output_format: str = "glb"
    bake_texture: bool = False
    texture_resolution: int = 1024
    max_task_seconds: int = 600
    rembg_model: str = "u2net"
    # TripoSR normalizes the input to this conditioning size, then places the
    # foreground at `foreground_ratio` of it (06 Sections 7.5 and 8.4).
    input_size: int = 512
    # Shared advisory image-quality analysis (11_image_quality_analysis.md).
    # It inspects the decoded original photograph, never the preprocessed image.
    image_quality: ImageQualityConfig = field(default_factory=ImageQualityConfig)
    # Generator selection (13_advanced_object_generation.md Section 4.2). The
    # allowlist is explicit; TripoSR stays the default and the regression
    # baseline. Selection is deployment configuration only, never per request.
    generator: str = "triposr"
    generator_fallback: bool = False
    sf3d: SF3DConfig = field(default_factory=SF3DConfig)
    # Optional post-generation mesh/texture enhancement
    # (14_mesh_texture_enhancement.md Section 6). Conservative cleanup and
    # normal validation are on; every other operation is disabled by default.
    enhancement: EnhancementConfig = field(default_factory=EnhancementConfig)

    def __post_init__(self) -> None:
        if not self.model_dir.is_absolute():
            message = "model_dir must be an absolute path"
            raise ValueError(message)
        self._validate_generator()
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
        if self.bake_texture != self.enhancement.bake_texture:
            message = (
                "bake_texture and enhancement.bake_texture disagree; map "
                "OBJECT_BAKE_TEXTURE into EnhancementConfig"
            )
            raise ValueError(message)

    def _validate_generator(self) -> None:
        """Reject an unknown, blocked or disabled generator during validation."""
        name = (self.generator or "").strip().lower()
        if name in BLOCKED_GENERATORS:
            message = (
                "The Hunyuan3D adapter is not available in this build: its "
                "licence/territory and 12 GB hardware checks were not satisfied "
                "(13 Section 5.2). It cannot be selected."
            )
            raise ValueError(message)
        if name not in SUPPORTED_GENERATORS:
            message = (
                f"Unsupported object generator {self.generator!r}; "
                f"supported values are {SUPPORTED_GENERATORS}"
            )
            raise ValueError(message)
        if name == "sf3d" and not self.sf3d.enabled:
            message = "OBJECT_GENERATOR=sf3d requires OBJECT_SF3D_ENABLED=true (13 Section 6)"
            raise ValueError(message)
