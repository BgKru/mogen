"""Output normalization shared by every object generator.

Generators return meshes in slightly different shapes: TripoSR supplies vertex
colours, Stable Fast 3D supplies UVs plus a baked base-colour texture and PBR
factors. Downstream code needs one explicit representation, and unsupported
output must fail loudly instead of being silently flattened
(13_advanced_object_generation.md Section 5.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .exceptions import INVALID_MESH, UNSUPPORTED_MESH_OUTPUT, NormalizationError
from .mesh_processor import MeshStats, validate_mesh

# glTF assets are Y-up; both supported generators already produce that frame.
COORDINATE_SYSTEM = "y_up"


@dataclass(frozen=True, slots=True)
class NormalizedMesh:
    """A mesh accepted by the exporter plus the facts recorded about it."""

    mesh: Any
    stats: MeshStats
    has_textures: bool
    has_vertex_colors: bool
    texture_resolution: int | None
    material_name: str
    coordinate_system: str = COORDINATE_SYSTEM

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSON-safe normalization facts."""
        block: dict[str, Any] = {
            "coordinate_system": self.coordinate_system,
            "has_textures": self.has_textures,
            "has_vertex_colors": self.has_vertex_colors,
            "material": self.material_name,
        }
        if self.texture_resolution is not None:
            block["texture_resolution"] = self.texture_resolution
        return block


def _single_mesh(mesh: Any) -> Any:
    """Return the mesh, or the single geometry of a one-part scene."""
    if mesh is None:
        raise NormalizationError(INVALID_MESH, "The generator returned no geometry.")
    geometries = getattr(mesh, "geometry", None)
    if isinstance(geometries, dict):
        parts = list(geometries.values())
        if len(parts) != 1:
            message = (
                "The generator returned a multi-part scene; combining parts "
                "would change geometry or UV mapping, so the output is rejected."
            )
            raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
        return parts[0]
    return mesh


def _texture_image(material: Any) -> Image.Image | None:
    """Return the base-colour image of a material, when it has one."""
    for attribute in ("baseColorTexture", "image", "baseColorTextureImage"):
        candidate = getattr(material, attribute, None)
        if candidate is None:
            continue
        if isinstance(candidate, Image.Image):
            return candidate
        if isinstance(candidate, np.ndarray):
            # trimesh also accepts arrays for texture data; keep them in memory.
            array = np.asarray(candidate)
            if array.dtype != np.uint8:
                if not np.isfinite(array).all():
                    return None
                array = np.clip(array, 0, 255).astype(np.uint8)
            return Image.fromarray(array)
        return None
    return None


def _validate_uvs(mesh: Any) -> int:
    """Return the UV count and reject missing, non-finite or mismatched UVs."""
    visual = getattr(mesh, "visual", None)
    uv = getattr(visual, "uv", None)
    if uv is None:
        message = "A textured generator output has no UV coordinates."
        raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
    array = np.asarray(uv, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        message = "The generator output has invalid UV coordinates."
        raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
    if len(array) != len(mesh.vertices):
        message = "The UV count does not match the vertex count."
        raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
    if not np.isfinite(array).all():
        message = "The generator output has non-finite UV coordinates."
        raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
    return int(len(array))


def normalize_output(mesh: Any, *, generator: str) -> NormalizedMesh:
    """Validate a generator's mesh and classify its appearance.

    Raises :class:`NormalizationError` with ``UNSUPPORTED_MESH_OUTPUT`` for a
    representation that cannot be exported without losing data, and
    ``INVALID_MESH`` for broken geometry.
    """
    candidate = _single_mesh(mesh)
    stats = validate_mesh(candidate)

    visual = getattr(candidate, "visual", None)
    kind = getattr(visual, "kind", None)

    if kind == "texture":
        material = getattr(visual, "material", None)
        if material is None:
            message = "A textured generator output has no material."
            raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
        image = _texture_image(material)
        if image is None or image.width < 1 or image.height < 1:
            message = "A textured generator output has no readable base-colour texture."
            raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)
        _validate_uvs(candidate)
        return NormalizedMesh(
            mesh=candidate,
            stats=stats,
            has_textures=True,
            has_vertex_colors=False,
            texture_resolution=int(max(image.size)),
            material_name=type(material).__name__,
        )

    if kind in {"vertex", "face"} and stats.has_vertex_colors:
        return NormalizedMesh(
            mesh=candidate,
            stats=stats,
            has_textures=False,
            has_vertex_colors=True,
            texture_resolution=None,
            material_name=kind,
        )

    message = (
        f"The {generator} output has neither vertex colours nor a textured "
        "material; it cannot be exported without losing appearance data."
    )
    raise NormalizationError(UNSUPPORTED_MESH_OUTPUT, message)


__all__ = ["COORDINATE_SYSTEM", "NormalizedMesh", "normalize_output"]
