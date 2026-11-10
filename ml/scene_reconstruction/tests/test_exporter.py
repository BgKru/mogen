"""GLB repack and raw-export inspection (07 Section 11.2)."""

from __future__ import annotations

import json
import struct

import pytest

from scene_reconstruction.exceptions import SceneExportError
from scene_reconstruction.exporter import (
    find_export_sources,
    repack_scene,
    summarize_raw_glb,
)
from scene_reconstruction.validator import validate_scene_glb

from .helpers import textured_glb, textured_quad_obj


def test_repacks_an_obj_set_into_a_self_contained_glb(tmp_path):
    obj = textured_quad_obj(tmp_path / "export")
    output = tmp_path / "output" / "scene.glb"

    validation = repack_scene([obj], output, require_textures=True)

    assert output.is_file()
    assert validation.has_embedded_textures is True
    assert validation.has_texture_coordinates is True
    document = json.loads(_json_chunk(output.read_bytes()))
    assert all("uri" not in image for image in document.get("images", []))
    assert len(document["buffers"]) == 1
    assert document["buffers"][0].get("uri") is None


def test_repack_falls_back_to_the_next_source(tmp_path):
    broken = tmp_path / "export" / "broken.obj"
    broken.parent.mkdir(parents=True)
    broken.write_text("this is not a mesh", encoding="utf-8")
    good = textured_quad_obj(tmp_path / "export2")
    output = tmp_path / "scene.glb"

    validation = repack_scene([broken, good], output)
    assert validate_scene_glb(output).sha256 == validation.sha256


def test_repack_without_sources_fails(tmp_path):
    with pytest.raises(SceneExportError):
        repack_scene([], tmp_path / "scene.glb")


def test_repack_to_an_unwritable_location_fails(tmp_path):
    obj = textured_quad_obj(tmp_path / "export")
    # A directory cannot be replaced by a file, so the export must fail cleanly.
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(SceneExportError):
        repack_scene([obj], output)


def test_find_export_sources_prefers_the_largest_file(tmp_path):
    directory = tmp_path / "export"
    directory.mkdir()
    (directory / "small.obj").write_text("v 0 0 0\n", encoding="utf-8")
    (directory / "scene_mesh.obj").write_text("v 0 0 0\nv 1 1 1\n", encoding="utf-8")
    sources = find_export_sources(directory, export_type="obj")
    assert [path.name for path in sources] == ["scene_mesh.obj", "small.obj"]


def test_summarize_raw_glb_detects_a_sidecar_texture(tmp_path):
    path = textured_glb(tmp_path / "raw.glb")
    document = json.loads(_json_chunk(path.read_bytes()))
    document["images"] = [{"uri": "scene_texture0.png", "mimeType": "image/png"}]
    raw = _rebuild(path.read_bytes(), document)
    raw_path = tmp_path / "raw-sidecar.glb"
    raw_path.write_bytes(raw)

    summary = summarize_raw_glb(raw_path)
    assert summary.has_external_images is True
    assert summary.image_uris == ("scene_texture0.png",)
    assert summary.as_metadata()["has_external_images"] is True


def test_untextured_repack_is_valid_when_textures_are_optional(tmp_path):
    glb = textured_glb(tmp_path / "plain.glb")
    document = json.loads(_json_chunk(glb.read_bytes()))
    document["images"] = []
    document["textures"] = []
    for material in document.get("materials", []):
        (material.get("pbrMetallicRoughness") or {}).pop("baseColorTexture", None)
    plain = tmp_path / "plain-untextured.glb"
    plain.write_bytes(_rebuild(glb.read_bytes(), document))

    validation = repack_scene([plain], tmp_path / "output.glb", require_textures=False)
    assert validation.textures_count == 0


def _json_chunk(data: bytes) -> bytes:
    length, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    return data[20 : 20 + length]


def _rebuild(data: bytes, document: dict) -> bytes:
    _, _, total = struct.unpack_from("<III", data, 0)
    offset = 12
    binary = b""
    while offset < total:
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset : offset + length]
        offset += length
        if kind == 0x004E4942:
            binary = payload
    json_chunk = json.dumps(document).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    bin_chunk = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return (
        struct.pack("<III", 0x46546C67, 2, total_length)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_chunk), 0x004E4942)
        + bin_chunk
    )
