"""Scene reconstruction pipeline package (ml/scene_reconstruction).

COLMAP performs feature extraction, matching, sparse reconstruction and image
undistortion; OpenMVS performs dense reconstruction, meshing, refinement and
texturing; this package orchestrates both and repacks the exported scene into a
validated single-file GLB.
"""

from __future__ import annotations

from .config import SceneConfig, build_config_from_settings
from .exceptions import SceneCancelled, SceneReconstructionError
from .pipeline import PhotogrammetryReconstructor, PipelineCallbacks, SceneArtifact

__all__ = [
    "PhotogrammetryReconstructor",
    "PipelineCallbacks",
    "SceneArtifact",
    "SceneCancelled",
    "SceneConfig",
    "SceneReconstructionError",
    "build_config_from_settings",
]
