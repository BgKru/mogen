"""Independent GLB validation for reconstructed scenes (07 Sections 11 and 18)."""

from __future__ import annotations

import json
import struct

import pytest

from scene_reconstruction.exceptions import SceneExportError
from scene_reconstruction.validator import (
    validate_scene_glb,
    validate_scene_glb_bytes,
)

from .helpers import textured_glb


def _glb_with_document(document: dict, binary: bytes) -> bytes:
    json_chunk = json.dumps(document).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    bin_chunk = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_chunk), 0x004E4942)
        + bin_chunk
    )


def test_valid_textured_glb_passes(tmp_path):
    path = textured_glb(tmp_path / "scene.glb")
    validation = validate_scene_glb(path)

    assert validation.meshes_count >= 1
    assert validation.vertices_count >= 3
    assert validation.faces_count >= 1
    assert validation.has_texture_coordinates is True
    assert validation.has_embedded_textures is True
    assert validation.textures_count >= 1
    assert validation.images_count >= 1
    assert validation.bounding_box["width"] > 0
    assert len(validation.sha256) == 64


def test_result_metadata_contains_the_documented_fields(tmp_path):
    validation = validate_scene_glb(textured_glb(tmp_path / "scene.glb"))
    metadata = validation.as_metadata()
    for key in (
        "vertices_count",
        "faces_count",
        "meshes_count",
        "materials_count",
        "textures_count",
        "bounding_box",
    ):
        assert key in metadata


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(SceneExportError):
        validate_scene_glb(tmp_path / "absent.glb")


def test_not_a_glb_is_rejected(tmp_path):
    path = tmp_path / "bad.glb"
    path.write_bytes(b"definitely not a glb")
    with pytest.raises(SceneExportError):
        validate_scene_glb(path)


def test_external_texture_reference_is_rejected(tmp_path):
    path = textured_glb(tmp_path / "scene.glb")
    data = path.read_bytes()
    document, binary = _split(data)
    document["images"] = [{"uri": "scene_texture0.png", "mimeType": "image/png"}]
    rebuilt = _glb_with_document(document, binary)
    with pytest.raises(SceneExportError):
        validate_scene_glb_bytes(rebuilt)


def test_missing_texture_coordinates_are_rejected(tmp_path):
    path = textured_glb(tmp_path / "scene.glb")
    document, binary = _split(path.read_bytes())
    for mesh in document["meshes"]:
        for primitive in mesh["primitives"]:
            primitive["attributes"].pop("TEXCOORD_0", None)
    with pytest.raises(SceneExportError):
        validate_scene_glb_bytes(_glb_with_document(document, binary))


def test_no_embedded_image_is_rejected_when_textures_are_required(tmp_path):
    path = textured_glb(tmp_path / "scene.glb")
    document, binary = _split(path.read_bytes())
    document["images"] = []
    document["textures"] = []
    with pytest.raises(SceneExportError):
        validate_scene_glb_bytes(_glb_with_document(document, binary))


def test_untextured_asset_is_accepted_when_textures_are_optional(tmp_path):
    path = textured_glb(tmp_path / "scene.glb")
    document, binary = _split(path.read_bytes())
    document["images"] = []
    document["textures"] = []
    for material in document.get("materials", []):
        pbr = material.get("pbrMetallicRoughness") or {}
        pbr.pop("baseColorTexture", None)
    validation = validate_scene_glb_bytes(
        _glb_with_document(document, binary), require_textures=False
    )
    assert validation.textures_count == 0


def test_external_buffer_reference_is_rejected(tmp_path):
    path = textured_glb(tmp_path / "scene.glb")
    document, binary = _split(path.read_bytes())
    document["buffers"][0]["uri"] = "scene.bin"
    with pytest.raises(SceneExportError):
        validate_scene_glb_bytes(_glb_with_document(document, binary))


def _split(data: bytes) -> tuple[dict, bytes]:
    _, _, total = struct.unpack_from("<III", data, 0)
    offset = 12
    document: dict | None = None
    binary = b""
    while offset < total:
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset : offset + length]
        offset += length
        if kind == 0x4E4F534A:
            document = json.loads(payload.decode("utf-8").rstrip("\x00 \t\r\n"))
        elif kind == 0x004E4942:
            binary = payload
    assert document is not None
    return document, binary
