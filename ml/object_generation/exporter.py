"""GLB export (06_object_generation.md Sections 10 and 11).

The export keeps TripoSR's default vertex colours. Texture baking is optional
in the specification and deliberately not enabled for the MVP
(06 Section 10.3); enabling it is rejected by the configuration validator.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from .exceptions import GLB_EXPORT_FAILED, ExportError
from .validator import GLBValidation, validate_glb

logger = logging.getLogger(__name__)


def _normalized_colors(mesh: Any) -> np.ndarray:
    """Return uint8 vertex colours, converting TripoSR's float 0..1 values."""
    try:
        colors = np.asarray(mesh.visual.vertex_colors)
    except Exception as exc:
        raise ExportError(GLB_EXPORT_FAILED, "The mesh has no readable vertex colours.") from exc
    if colors.size == 0:
        raise ExportError(GLB_EXPORT_FAILED, "The mesh has no vertex colours to export.")
    if colors.ndim != 2 or colors.shape[1] not in (3, 4):
        raise ExportError(GLB_EXPORT_FAILED, "The mesh vertex colours have an invalid shape.")
    if colors.dtype.kind == "f":
        if not np.isfinite(colors).all():
            raise ExportError(
                GLB_EXPORT_FAILED, "The mesh vertex colours contain non-finite values."
            )
        if colors.max() <= 1.0 + 1e-6:
            colors = colors * 255.0
    return np.clip(colors, 0, 255).astype(np.uint8)


def export_glb(mesh: Any, output_path: Path) -> GLBValidation:
    """Export a validated mesh as a self-contained GLB and validate the file.

    A file that fails validation is removed so an invalid asset can never be
    registered as a successful result (06 Section 12.4).
    """
    try:
        colors = _normalized_colors(mesh)
        mesh.visual.vertex_colors = colors
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(GLB_EXPORT_FAILED, "Preparing vertex colours for export failed.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mesh.export(str(output_path), file_type="glb")
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ExportError(GLB_EXPORT_FAILED, "GLB export failed.") from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ExportError(GLB_EXPORT_FAILED, "GLB export produced no file.")

    try:
        validation = validate_glb(output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    logger.info(
        "glb_exported",
        extra={
            "operation": "object_generation",
            "file_size_bytes": validation.file_size_bytes,
            "vertices_count": validation.vertices_count,
            "faces_count": validation.faces_count,
        },
    )
    return validation
