"""Shared, dependency-light mesh utilities for the object and scene workers.

The package is installed as ``mesh_enhancement`` next to ``image_quality`` in
both worker images. It contains only pure CPU helpers (trimesh/NumPy) so neither
worker imports the other worker's package (14 Section 3).
"""

from __future__ import annotations

from .cleanup import CleanupError, CleanupOutcome, cleanup_mesh
from .manifest import (
    MeshEnhancementManifestError,
    build_enhancement_manifest,
    dependency_versions,
    mesh_fingerprint,
    read_enhancement_manifest,
    write_enhancement_manifest,
)
from .metrics import MeshMetrics, measure_mesh
from .normals import NormalError, NormalOutcome, ensure_normals, validate_normals
from .simplification import (
    SimplificationOutcome,
    SimplifierUnavailable,
    simplify_mesh,
)

__all__ = [
    "CleanupError",
    "CleanupOutcome",
    "MeshEnhancementManifestError",
    "MeshMetrics",
    "NormalError",
    "NormalOutcome",
    "SimplificationOutcome",
    "SimplifierUnavailable",
    "build_enhancement_manifest",
    "cleanup_mesh",
    "dependency_versions",
    "ensure_normals",
    "measure_mesh",
    "mesh_fingerprint",
    "read_enhancement_manifest",
    "simplify_mesh",
    "validate_normals",
    "write_enhancement_manifest",
]
