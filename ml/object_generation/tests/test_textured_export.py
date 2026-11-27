"""Textured-output normalization, GLB export and validation (increment 13).

The TripoSR vertex-colour path keeps its own regression test in
``test_mesh_export.py``; these tests cover the second appearance path added for
Stable Fast 3D's UV-unwrapped albedo/normal maps.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest
import trimesh

from object_generation.exceptions import UNSUPPORTED_MESH_OUTPUT, NormalizationError
from object_generation.exporter import export_glb
from object_generation.normalization import normalize_output
from object_generation.validator import validate_glb
from tests.helpers import textured_box


def _glb_document(data: bytes) -> dict:
    _magic, _version, _length = struct.unpack_from("<III", data, 0)
    json_length, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A
    return json.loads(data[20 : 20 + json_length].decode("utf-8").rstrip("\x00 \t\r\n"))


def test_normalize_accepts_uv_texture_and_reports_its_resolution() -> None:
    normalized = normalize_output(textured_box(texture_size=32), generator="sf3d")

    assert normalized.has_textures is True
    assert normalized.has_vertex_colors is False
    assert normalized.texture_resolution == 32
    assert normalized.material_name == "PBRMaterial"
    metadata = normalized.as_metadata()
    assert metadata["coordinate_system"] == "y_up"
    assert metadata["texture_resolution"] == 32


def test_normalize_rejects_a_mesh_without_appearance() -> None:
    mesh = trimesh.creation.box(extents=(1, 1, 1))
    mesh.visual = trimesh.visual.ColorVisuals()

    with pytest.raises(NormalizationError) as excinfo:
        normalize_output(mesh, generator="sf3d")

    assert excinfo.value.error_code == UNSUPPORTED_MESH_OUTPUT


def test_normalize_rejects_textured_output_without_uvs() -> None:
    mesh = textured_box()
    mesh.visual = trimesh.visual.texture.TextureVisuals(uv=None, material=mesh.visual.material)

    with pytest.raises(NormalizationError) as excinfo:
        normalize_output(mesh, generator="sf3d")

    assert excinfo.value.error_code == UNSUPPORTED_MESH_OUTPUT


def test_normalize_rejects_non_finite_uvs() -> None:
    mesh = textured_box()
    uv = np.array(mesh.visual.uv, dtype=np.float64)
    uv[0, 0] = np.nan
    mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, material=mesh.visual.material)

    with pytest.raises(NormalizationError):
        normalize_output(mesh, generator="sf3d")


def test_normalize_rejects_a_multi_part_scene() -> None:
    scene = trimesh.Scene(
        [
            trimesh.creation.box(extents=(1, 1, 1)),
            trimesh.creation.box(extents=(0.5, 0.5, 0.5)),
        ]
    )

    with pytest.raises(NormalizationError) as excinfo:
        normalize_output(scene, generator="sf3d")

    assert excinfo.value.error_code == UNSUPPORTED_MESH_OUTPUT


def test_normalize_unwraps_a_single_part_scene() -> None:
    scene = trimesh.Scene([textured_box()])

    normalized = normalize_output(scene, generator="sf3d")

    assert normalized.has_textures is True


def test_export_embeds_the_texture_and_validation_accepts_it(tmp_path: Path) -> None:
    normalized = normalize_output(textured_box(texture_size=48), generator="sf3d")
    path = tmp_path / "model.glb"

    validation = export_glb(normalized.mesh, path)

    assert validation.has_textures is True
    assert validation.has_uvs is True
    assert validation.has_vertex_colors is False
    assert validation.textures_count >= 1
    document = _glb_document(path.read_bytes())
    material = document["materials"][0]
    texture_index = material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    image_index = document["textures"][texture_index]["source"]
    image = document["images"][image_index]
    assert "uri" not in image  # self-contained: embedded bufferView only
    assert image["mimeType"] in {"image/png", "image/jpeg", "image/webp"}
    assert "TEXCOORD_0" in document["meshes"][0]["primitives"][0]["attributes"]
    # The stored file is reproducible and re-validates identically.
    assert validate_glb(path).sha256 == validation.sha256


def test_export_rejects_a_textured_mesh_with_an_empty_texture(tmp_path: Path) -> None:
    mesh = textured_box()
    mesh.visual.material.baseColorTexture = None
    path = tmp_path / "model.glb"

    with pytest.raises(Exception) as excinfo:
        export_glb(mesh, path)

    assert excinfo.value.error_code == UNSUPPORTED_MESH_OUTPUT
    assert not path.exists()


def test_validator_rejects_a_glb_without_appearance(tmp_path: Path) -> None:
    from tests.helpers import build_glb_bytes

    path = tmp_path / "plain.glb"
    path.write_bytes(build_glb_bytes(include_colors=False))

    with pytest.raises(Exception) as excinfo:
        validate_glb(path)

    assert excinfo.value.error_code == "GLB_VALIDATION_FAILED"
