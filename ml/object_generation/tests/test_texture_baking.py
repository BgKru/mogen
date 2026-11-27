"""xatlas UV generation, vertex-colour baking and PBR tests (14 Sections 5.4-5.7)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest
import trimesh

from object_generation.exceptions import ExportError
from object_generation.exporter import export_glb
from object_generation.texture_baking import (
    bake_vertex_colors,
    generate_uvs,
    has_texture_image,
    has_usable_uvs,
    normalize_pbr_material,
)
from object_generation.validator import validate_glb
from tests.helpers import colored_box, textured_box


def _glb_document(path: Path) -> dict:
    data = path.read_bytes()
    length, _ = struct.unpack_from("<II", data, 12)
    return json.loads(data[20 : 20 + length].decode("utf-8").rstrip("\x00 "))


def test_generate_uvs_remaps_geometry_and_vertex_colours() -> None:
    mesh = colored_box()
    original_colors = np.asarray(mesh.visual.vertex_colors).copy()

    outcome = generate_uvs(mesh, padding=3)

    result = outcome.mesh
    assert outcome.chart_count >= 1
    assert outcome.faces_count == len(result.faces)
    assert len(result.vertices) == len(outcome.mesh.vertices)
    assert result.visual.uv is not None
    uv = np.asarray(result.visual.uv)
    assert uv.shape == (len(result.vertices), 2)
    assert np.isfinite(uv).all()
    assert uv.min() >= 0.0 and uv.max() <= 1.0
    assert len(result.visual.vertex_colors) == len(result.vertices)
    # The atlas duplicates seam vertices, but every source colour value survives.
    unique_colors = np.unique(np.asarray(result.visual.vertex_colors), axis=0)
    assert np.unique(original_colors, axis=0).tolist() == unique_colors.tolist()
    assert outcome.as_metadata()["generator"] == "xatlas"


def test_generated_uvs_are_usable_and_existing_uvs_are_preserved() -> None:
    generated = generate_uvs(colored_box())
    textured = textured_box()

    assert has_usable_uvs(generated.mesh) is True
    assert has_usable_uvs(textured) is True
    assert has_usable_uvs(colored_box()) is False


def test_bake_vertex_colors_produces_an_embedded_texture_and_pbr_material(tmp_path: Path) -> None:
    mesh = generate_uvs(colored_box(), padding=2).mesh

    outcome = bake_vertex_colors(mesh, resolution=128, padding=2)
    path = tmp_path / "baked.glb"
    validation = export_glb(outcome.mesh, path, include_normals=True)

    assert outcome.coverage_ratio > 0.0
    assert has_texture_image(outcome.mesh) is True
    document = _glb_document(path)
    primitive = document["meshes"][0]["primitives"][0]
    assert "TEXCOORD_0" in primitive["attributes"]
    assert "NORMAL" in primitive["attributes"]
    material = document["materials"][0]["pbrMetallicRoughness"]
    assert material["baseColorTexture"]["index"] == 0
    assert material["metallicFactor"] == 0.0
    assert material["roughnessFactor"] == 0.9
    assert document["images"][0]["mimeType"] == "image/png"
    assert "uri" not in document["images"][0]
    assert validation.has_textures is True
    assert validation.has_pbr_materials is True
    assert validate_glb(path).sha256 == validation.sha256


def test_baking_without_uvs_is_rejected() -> None:
    with pytest.raises(ExportError) as excinfo:
        bake_vertex_colors(colored_box(), resolution=128)
    assert excinfo.value.error_code == "TEXTURE_BAKING_FAILED"


def test_baking_rejects_an_out_of_range_resolution() -> None:
    mesh = generate_uvs(colored_box()).mesh
    with pytest.raises(ExportError) as excinfo:
        bake_vertex_colors(mesh, resolution=32)
    assert excinfo.value.error_code == "TEXTURE_BAKING_FAILED"


def test_pbr_normalization_clamps_invalid_factors() -> None:
    mesh = textured_box()
    material = mesh.visual.material
    material.metallicFactor = 4.0
    material.roughnessFactor = -1.0

    outcome = normalize_pbr_material(mesh)

    assert outcome["applied"] is True
    assert outcome["metallic_factor"] == 1.0
    assert outcome["roughness_factor"] == 0.0
    assert outcome["changes"] == {"metallicFactor": 1.0, "roughnessFactor": 0.0}


def test_pbr_normalization_uses_dielectric_defaults() -> None:
    mesh = generate_uvs(colored_box()).mesh
    baked = bake_vertex_colors(mesh, resolution=64, padding=1).mesh
    baked.visual.material.metallicFactor = None
    baked.visual.material.roughnessFactor = None

    outcome = normalize_pbr_material(baked)

    assert outcome["metallic_factor"] == 0.0
    assert outcome["roughness_factor"] == 0.9
    assert outcome["base_color_srgb"] is True
    assert outcome["metallic_roughness_linear"] is True


def test_pbr_normalization_skips_vertex_colour_assets() -> None:
    outcome = normalize_pbr_material(colored_box())
    assert outcome == {"applied": False, "reason": "no_texture_material"}


def test_baked_atlas_preserves_average_colour() -> None:
    mesh = colored_box()
    mesh.visual.vertex_colors = np.tile(
        np.array([[200, 60, 30, 255]], dtype=np.uint8), (len(mesh.vertices), 1)
    )
    unwrapped = generate_uvs(mesh).mesh
    baked = bake_vertex_colors(unwrapped, resolution=64, padding=1).mesh

    image = np.asarray(baked.visual.material.baseColorTexture)
    assert image.shape == (64, 64, 3)
    assert abs(float(image[..., 0].mean()) - 200.0) < 2.0
    assert abs(float(image[..., 1].mean()) - 60.0) < 2.0
    assert abs(float(image[..., 2].mean()) - 30.0) < 2.0


def test_uv_generation_requires_faces() -> None:
    empty = trimesh.Trimesh(
        vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        faces=np.zeros((0, 3)),
        process=False,
    )
    with pytest.raises(ExportError) as excinfo:
        generate_uvs(empty)
    assert excinfo.value.error_code == "UV_GENERATION_FAILED"
