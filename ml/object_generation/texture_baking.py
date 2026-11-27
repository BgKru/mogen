"""xatlas UV generation and deterministic vertex-colour baking (14 Section 5.4-5.5).

The atlas is generated on the final topology and every per-vertex attribute is
remapped through xatlas's vertex mapping. Baking rasterises the existing vertex
colours over that atlas; it never invents new surface detail, and a generator
or OpenMVS texture is preserved instead of being rebaked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh
import xatlas
from PIL import Image

from .exceptions import TEXTURE_BAKING_FAILED, UV_GENERATION_FAILED, ExportError

_UV_TOLERANCE = 1e-3


@dataclass(frozen=True, slots=True)
class UvOutcome:
    """A mesh re-indexed by xatlas plus atlas statistics."""

    mesh: trimesh.Trimesh
    chart_count: int
    atlas_utilization: float
    vertices_count: int
    faces_count: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "generator": "xatlas",
            "xatlas_version": _xatlas_version(),
            "chart_count": self.chart_count,
            "atlas_utilization": round(self.atlas_utilization, 6),
            "vertices_count": self.vertices_count,
            "faces_count": self.faces_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class BakeOutcome:
    """A textured mesh whose embedded atlas was baked from vertex colours."""

    mesh: trimesh.Trimesh
    resolution: int
    padding: int
    covered_pixels: int
    coverage_ratio: float
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution,
            "padding": self.padding,
            "covered_pixels": self.covered_pixels,
            "coverage_ratio": round(self.coverage_ratio, 6),
            "warnings": list(self.warnings),
        }


def _xatlas_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("xatlas")
    except PackageNotFoundError:
        return "unknown"


def _validate_uvs(uv: np.ndarray, vertex_count: int) -> tuple[str, ...]:
    values = np.asarray(uv, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 2 or len(values) != vertex_count:
        raise ExportError(UV_GENERATION_FAILED, "Generated UVs have an invalid shape.")
    if not np.isfinite(values).all():
        raise ExportError(UV_GENERATION_FAILED, "Generated UVs contain non-finite values.")
    warnings: list[str] = []
    if values.min() < -_UV_TOLERANCE or values.max() > 1.0 + _UV_TOLERANCE:
        raise ExportError(UV_GENERATION_FAILED, "Generated UVs fall outside the atlas range.")
    if values.min() < 0.0 or values.max() > 1.0:
        warnings.append("uv_outside_unit_square_within_tolerance")
    return tuple(warnings)


def _vertex_colors(mesh: trimesh.Trimesh) -> np.ndarray:
    try:
        colors = np.asarray(mesh.visual.vertex_colors)
    except Exception as exc:
        raise ExportError(
            TEXTURE_BAKING_FAILED, "The mesh has no readable vertex colours to bake."
        ) from exc
    if colors.ndim != 2 or colors.shape[1] not in (3, 4) or len(colors) != len(mesh.vertices):
        raise ExportError(TEXTURE_BAKING_FAILED, "The mesh vertex colours have an invalid shape.")
    if colors.dtype.kind == "f":
        if not np.isfinite(colors).all():
            raise ExportError(
                TEXTURE_BAKING_FAILED, "The vertex colours contain non-finite values."
            )
        if colors.max() <= 1.0 + 1e-6:
            colors = colors * 255.0
    return np.clip(colors[:, :3], 0, 255).astype(np.uint8)


def has_usable_uvs(mesh: trimesh.Trimesh) -> bool:
    """Return whether the mesh already carries valid generator/OpenMVS UVs."""
    try:
        uv = getattr(mesh.visual, "uv", None)
        if uv is None or len(uv) != len(mesh.vertices):
            return False
        return bool(np.isfinite(np.asarray(uv, dtype=np.float64)).all())
    except Exception:
        return False


def generate_uvs(mesh: trimesh.Trimesh, *, padding: int = 2) -> UvOutcome:
    """Generate a non-overlapping atlas and remap positions/colours."""
    if len(mesh.faces) == 0:
        raise ExportError(UV_GENERATION_FAILED, "The mesh has no faces to unwrap.")
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    atlas = xatlas.Atlas()
    try:
        atlas.add_mesh(vertices, faces)
        pack = xatlas.PackOptions()
        pack.padding = max(0, int(padding))
        atlas.generate(pack_options=pack)
        mapping, indices, uvs = atlas.get_mesh(0)
    except Exception as exc:
        raise ExportError(UV_GENERATION_FAILED, "xatlas could not generate a UV atlas.") from exc
    if mapping is None or indices is None or uvs is None or len(indices) == 0:
        raise ExportError(UV_GENERATION_FAILED, "xatlas returned an empty atlas.")

    warnings = list(_validate_uvs(uvs, len(mapping)))
    new_vertices = np.asarray(mesh.vertices, dtype=np.float64)[mapping]
    new_mesh = trimesh.Trimesh(
        vertices=new_vertices,
        faces=np.asarray(indices, dtype=np.int64),
        process=False,
        validate=False,
    )
    try:
        kind = getattr(mesh.visual, "kind", None)
    except Exception:
        kind = None
    new_mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.asarray(uvs, dtype=np.float64), material=None
    )
    if kind in {"vertex", "face"}:
        colors = np.asarray(mesh.visual.vertex_colors)
        if len(colors) == len(mesh.vertices):
            # TextureVisuals creates a placeholder SimpleMaterial; the source
            # colours stay attached so the baking step can consume them.
            new_mesh.visual.vertex_colors = colors[mapping]
    try:
        chart_count = int(atlas.chart_count)
        utilization = float(atlas.utilization)
    except Exception:
        chart_count = 0
        utilization = 0.0
    return UvOutcome(
        mesh=new_mesh,
        chart_count=chart_count,
        atlas_utilization=utilization,
        vertices_count=int(len(new_mesh.vertices)),
        faces_count=int(len(new_mesh.faces)),
        warnings=tuple(warnings),
    )


def _rasterize_vertex_colors(
    uv: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    resolution: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Rasterise barycentric vertex colours into an RGB atlas and coverage mask.

    Triangles are processed in bounded vectorised batches: a face-id map was
    tried first but 76k Pillow polygon calls dominated the runtime. The batch
    rasteriser expands each triangle's pixel bounding box, tests barycentric
    coverage in NumPy and writes the interpolated colour, which keeps the
    optional bake practical at 512-1024 px.
    """
    size = int(resolution)
    # glTF UV origin is bottom-left; image row zero is the top row.
    pixels = np.stack([uv[:, 0] * (size - 1), (1.0 - uv[:, 1]) * (size - 1)], axis=1)
    image = np.zeros((size, size, 3), dtype=np.float32)
    covered = np.zeros((size, size), dtype=bool)
    color_values = colors.astype(np.float32)
    face_count = len(faces)
    batch = 4096
    for start in range(0, face_count, batch):
        stop = min(start + batch, face_count)
        batch_faces = faces[start:stop]
        triangles = pixels[batch_faces]
        minimum = np.floor(triangles.min(axis=1)).astype(np.int64)
        maximum = np.ceil(triangles.max(axis=1)).astype(np.int64)
        minimum[:, 0] = np.clip(minimum[:, 0], 0, size - 1)
        minimum[:, 1] = np.clip(minimum[:, 1], 0, size - 1)
        maximum[:, 0] = np.clip(maximum[:, 0], 0, size - 1)
        maximum[:, 1] = np.clip(maximum[:, 1], 0, size - 1)
        widths = maximum[:, 0] - minimum[:, 0] + 1
        heights = maximum[:, 1] - minimum[:, 1] + 1
        counts = widths * heights
        usable = (widths > 0) & (heights > 0)
        if not usable.any():
            continue
        batch_faces = batch_faces[usable]
        triangles = triangles[usable]
        minimum = minimum[usable]
        widths = widths[usable]
        counts = counts[usable]
        total = int(counts.sum())
        if total <= 0:
            continue
        repeated = np.repeat(np.arange(len(counts)), counts)
        starts = np.repeat(np.cumsum(counts) - counts, counts)
        offsets = np.arange(total, dtype=np.int64) - starts
        local_x = offsets % widths[repeated]
        local_y = offsets // widths[repeated]
        xs = minimum[repeated, 0] + local_x
        ys = minimum[repeated, 1] + local_y
        with np.errstate(invalid="ignore", divide="ignore"):
            triangle = triangles[repeated]
            denominator = (triangle[:, 1, 1] - triangle[:, 2, 1]) * (
                triangle[:, 0, 0] - triangle[:, 2, 0]
            ) + (triangle[:, 2, 0] - triangle[:, 1, 0]) * (triangle[:, 0, 1] - triangle[:, 2, 1])
            safe = np.abs(denominator) > 1e-12
            denominator = np.where(safe, denominator, 1.0)
            weight_a = (
                (triangle[:, 1, 1] - triangle[:, 2, 1]) * (xs - triangle[:, 2, 0])
                + (triangle[:, 2, 0] - triangle[:, 1, 0]) * (ys - triangle[:, 2, 1])
            ) / denominator
            weight_b = (
                (triangle[:, 2, 1] - triangle[:, 0, 1]) * (xs - triangle[:, 2, 0])
                + (triangle[:, 0, 0] - triangle[:, 2, 0]) * (ys - triangle[:, 2, 1])
            ) / denominator
            weight_c = 1.0 - weight_a - weight_b
            inside = (
                safe
                & (weight_a >= -1e-6)
                & (weight_b >= -1e-6)
                & (weight_c >= -1e-6)
                & (xs >= 0)
                & (xs < size)
                & (ys >= 0)
                & (ys < size)
            )
        if not inside.any():
            continue
        target_rows = ys[inside]
        target_columns = xs[inside]
        vertices = batch_faces[repeated[inside]]
        per_pixel = color_values[vertices]
        image[target_rows, target_columns] = (
            weight_a[inside, None] * per_pixel[:, 0]
            + weight_b[inside, None] * per_pixel[:, 1]
            + weight_c[inside, None] * per_pixel[:, 2]
        )
        covered[target_rows, target_columns] = True
    return image, covered


def _dilate(image: np.ndarray, covered: np.ndarray, padding: int) -> tuple[np.ndarray, np.ndarray]:
    """Fill empty pixels from their covered neighbours, bounded by ``padding``."""
    result = image.copy()
    mask = covered.copy()
    for _ in range(max(0, int(padding))):
        if mask.all():
            break
        total = np.zeros_like(result)
        count = np.zeros(mask.shape, dtype=np.float32)
        for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            shifted_value = np.roll(result, shift, axis=axis)
            shifted_mask = np.roll(mask, shift, axis=axis)
            if axis == 0:
                if shift > 0:
                    shifted_mask[0, :] = False
                else:
                    shifted_mask[-1, :] = False
            else:
                if shift > 0:
                    shifted_mask[:, 0] = False
                else:
                    shifted_mask[:, -1] = False
            total += shifted_value * shifted_mask[..., None]
            count += shifted_mask
        fill = (~mask) & (count > 0)
        if not fill.any():
            break
        result[fill] = total[fill] / count[fill, None]
        mask = mask | fill
    return result, mask


def bake_vertex_colors(
    mesh: trimesh.Trimesh,
    *,
    resolution: int = 1024,
    padding: int = 4,
) -> BakeOutcome:
    """Bake the mesh's vertex colours into an atlas and attach a PBR material."""
    if resolution < 64 or resolution > 4096:
        raise ExportError(TEXTURE_BAKING_FAILED, "The bake resolution is outside 64-4096.")
    if not has_usable_uvs(mesh):
        raise ExportError(TEXTURE_BAKING_FAILED, "Texture baking requires a UV layout.")
    colors = _vertex_colors(mesh)
    uv = np.asarray(mesh.visual.uv, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    image, covered = _rasterize_vertex_colors(uv, faces, colors, resolution)
    if not covered.any():
        raise ExportError(TEXTURE_BAKING_FAILED, "No triangle covered the texture atlas.")
    filled, mask = _dilate(image, covered, padding)
    background = filled[mask].mean(axis=0) if mask.any() else np.zeros(3)
    filled[~mask] = background
    atlas = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8), mode="RGB")
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=atlas,
        baseColorFactor=[1.0, 1.0, 1.0, 1.0],
        metallicFactor=0.0,
        roughnessFactor=0.9,
    )
    textured = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64).copy(),
        faces=faces.copy(),
        process=False,
        validate=False,
    )
    textured.visual = trimesh.visual.TextureVisuals(uv=uv.copy(), material=material)
    covered_pixels = int(np.count_nonzero(covered))
    return BakeOutcome(
        mesh=textured,
        resolution=int(resolution),
        padding=int(padding),
        covered_pixels=covered_pixels,
        coverage_ratio=round(covered_pixels / float(resolution * resolution), 6),
    )


def has_texture_image(mesh: trimesh.Trimesh) -> bool:
    """Return whether the visual carries a real in-memory base-colour image.

    ``TextureVisuals`` creates a placeholder ``SimpleMaterial`` with a 2x2 image
    when no material is supplied, so the mere presence of ``material.image`` is
    not evidence of a texture. Only a real ``baseColorTexture`` (or a
    non-placeholder image) counts.
    """
    try:
        if getattr(mesh.visual, "kind", None) != "texture":
            return False
        material = getattr(mesh.visual, "material", None)
        if material is None:
            return False
        if getattr(material, "baseColorTexture", None) is not None:
            return True
        image = getattr(material, "image", None)
        if image is None:
            return False
        return bool(int(getattr(image, "width", 0)) > 2 or int(getattr(image, "height", 0)) > 2)
    except Exception:
        return False


def normalize_pbr_material(
    mesh: trimesh.Trimesh,
    *,
    default_metallic: float = 0.0,
    default_roughness: float = 0.9,
) -> dict[str, Any]:
    """Clamp normalise a PBR material to glTF metallic-roughness semantics.

    Only existing material factors are normalised. A vertex-colour-only asset
    keeps its legacy material-less export; no metallic/roughness map is
    synthesised from a base-colour image (14 Section 5.7).
    """
    try:
        if getattr(mesh.visual, "kind", None) != "texture":
            return {"applied": False, "reason": "no_texture_material"}
        visual = mesh.visual
        material = getattr(visual, "material", None)
        if material is None or not has_texture_image(mesh):
            return {"applied": False, "reason": "no_material"}
        changes: dict[str, Any] = {}
        metallic = getattr(material, "metallicFactor", None)
        if metallic is None or not np.isfinite(float(metallic)):
            material.metallicFactor = default_metallic
            changes["metallicFactor"] = default_metallic
        else:
            clamped = float(min(max(float(metallic), 0.0), 1.0))
            if clamped != float(metallic):
                material.metallicFactor = clamped
                changes["metallicFactor"] = clamped
        roughness = getattr(material, "roughnessFactor", None)
        if roughness is None or not np.isfinite(float(roughness)):
            material.roughnessFactor = default_roughness
            changes["roughnessFactor"] = default_roughness
        else:
            clamped = float(min(max(float(roughness), 0.0), 1.0))
            if clamped != float(roughness):
                material.roughnessFactor = clamped
                changes["roughnessFactor"] = clamped
        if not has_usable_uvs(mesh):
            raise ExportError(TEXTURE_BAKING_FAILED, "A textured material requires a UV layout.")
        return {
            "applied": True,
            "changes": changes,
            "metallic_factor": float(getattr(material, "metallicFactor", 0.0)),
            "roughness_factor": float(getattr(material, "roughnessFactor", 1.0)),
            "base_color_srgb": True,
            "metallic_roughness_linear": True,
        }
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(TEXTURE_BAKING_FAILED, "The PBR material is invalid.") from exc


__all__ = [
    "BakeOutcome",
    "UvOutcome",
    "bake_vertex_colors",
    "generate_uvs",
    "has_texture_image",
    "has_usable_uvs",
    "normalize_pbr_material",
]
