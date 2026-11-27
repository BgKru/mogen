"""GLB export (06_object_generation.md Sections 10 and 11).

Two appearance paths are supported, and neither degrades the other:

* vertex colours — TripoSR's default, exported exactly as the Phase 5 path did;
* a textured PBR material — Stable Fast 3D's UV-unwrapped albedo/normal maps,
  preserved instead of being flattened to vertex colours
  (13_advanced_object_generation.md Section 5.3).

Unsupported appearance data fails the export; it is never silently dropped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image

from .exceptions import GLB_EXPORT_FAILED, UNSUPPORTED_MESH_OUTPUT, ExportError
from .texture_baking import has_texture_image
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


def _as_image(value: Any) -> Image.Image | None:
    """Return an in-memory image for a material texture slot."""
    if isinstance(value, Image.Image):
        return value
    if isinstance(value, np.ndarray):
        array = np.asarray(value)
        if array.dtype != np.uint8:
            if not np.isfinite(array).all():
                return None
            array = np.clip(array, 0, 255).astype(np.uint8)
        return Image.fromarray(array)
    return None


def _prepare_textured_visual(mesh: Any) -> None:
    """Verify and normalise a textured material without changing UVs."""
    visual = getattr(mesh, "visual", None)
    material = getattr(visual, "material", None)
    uv = np.asarray(getattr(visual, "uv", None), dtype=np.float64)
    if material is None:
        raise ExportError(UNSUPPORTED_MESH_OUTPUT, "The textured mesh has no material.")
    if uv.ndim != 2 or uv.shape[1] != 2 or len(uv) != len(mesh.vertices):
        raise ExportError(UNSUPPORTED_MESH_OUTPUT, "The textured mesh has invalid UVs.")
    if not np.isfinite(uv).all():
        raise ExportError(UNSUPPORTED_MESH_OUTPUT, "The textured mesh has non-finite UVs.")

    base = _as_image(getattr(material, "baseColorTexture", None))
    if base is None:
        base = _as_image(getattr(material, "image", None))
    if base is None or base.width < 1 or base.height < 1:
        raise ExportError(
            UNSUPPORTED_MESH_OUTPUT, "The textured mesh has no readable base-colour texture."
        )
    # trimesh's GLB writer embeds PIL images; a path/URI could leak an external
    # dependency into the asset, so the material is pinned to the in-memory image.
    material.baseColorTexture = base
    normal = _as_image(getattr(material, "normalTexture", None))
    if normal is not None:
        material.normalTexture = normal


def _appearance(mesh: Any) -> str:
    """Return ``vertex`` or ``texture``; raise when neither is usable."""
    visual = getattr(mesh, "visual", None)
    kind = getattr(visual, "kind", None)
    if kind == "texture" and has_texture_image(mesh):
        _prepare_textured_visual(mesh)
        return "texture"
    if kind == "texture" and getattr(visual, "vertex_colors", None) is None:
        # A textured visual without a real embedded image has no appearance at
        # all; do not silently export a grey placeholder (OBJ-AC-10).
        raise ExportError(
            UNSUPPORTED_MESH_OUTPUT,
            "The textured mesh has no readable base-colour texture.",
        )
    try:
        mesh.visual.vertex_colors = _normalized_colors(mesh)
        if kind == "texture":
            # UV-only enhancement visual: drop the placeholder atlas and export
            # through the legacy vertex-colour path.
            mesh.visual = trimesh.visual.ColorVisuals(
                vertex_colors=np.asarray(mesh.visual.vertex_colors)
            )
    except ExportError as exc:
        if kind == "texture":
            raise ExportError(
                UNSUPPORTED_MESH_OUTPUT,
                "The textured mesh has no readable base-colour texture.",
            ) from exc
        raise
    except Exception as exc:
        raise ExportError(GLB_EXPORT_FAILED, "Preparing vertex colours for export failed.") from exc
    return "vertex"


def export_glb(
    mesh: Any,
    output_path: Path,
    *,
    include_normals: bool = False,
) -> GLBValidation:
    """Export a validated mesh as a self-contained GLB and validate the file.

    ``include_normals`` is enabled only when the enhancement stage produced and
    validated normals; the legacy vertex-colour export remains byte-shape
    compatible otherwise (14 Section 5.3). A file that fails validation is
    removed so an invalid asset can never be registered as a successful result
    (06 Section 12.4).
    """
    appearance = _appearance(mesh)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        export_options: dict[str, Any] = {"file_type": "glb"}
        if include_normals:
            export_options["include_normals"] = True
        mesh.export(str(output_path), **export_options)
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
            "appearance": appearance,
            "textures_count": validation.textures_count,
        },
    )
    return validation
