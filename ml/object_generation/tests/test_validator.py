"""GLB validation unit tests (06 Section 12, 09_testing.md Section 12)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from object_generation.exceptions import ExportError
from object_generation.validator import (
    GLBValidation,
    sha256_file,
    validate_glb,
    validate_glb_bytes,
)
from tests.helpers import JSON_CHUNK, build_glb_bytes


def _expect_invalid(data: bytes) -> None:
    with pytest.raises(ExportError) as excinfo:
        validate_glb_bytes(data)
    assert excinfo.value.error_code == "GLB_VALIDATION_FAILED"


def _split(data: bytes) -> tuple[dict, bytes, str]:
    magic, version, total = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2 and total == len(data)
    offset = 12
    document = None
    binary = b""
    while offset < len(data):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset : offset + length]
        offset += length
        if chunk_type == JSON_CHUNK:
            document = json.loads(payload.decode("utf-8").rstrip(" \x00"))
        else:
            binary = payload
    assert document is not None
    return document, binary, "json"


def _rebuild(document: dict, binary: bytes) -> bytes:
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_bytes), JSON_CHUNK)
        + json_bytes
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def test_a_valid_glb_reports_geometry_and_appearance() -> None:
    result = validate_glb_bytes(build_glb_bytes())

    assert isinstance(result, GLBValidation)
    assert result.meshes_count == 1
    assert result.primitives_count == 1
    assert result.vertices_count == 4
    assert result.faces_count == 4
    assert result.has_vertex_colors is True
    assert result.bounding_box == {"width": 1.0, "height": 1.0, "depth": 1.0}
    assert result.file_size_bytes > 0
    assert len(result.sha256) == 64


def test_validate_glb_reads_and_checksums_a_file(tmp_path: Path) -> None:
    data = build_glb_bytes()
    path = tmp_path / "model.glb"
    path.write_bytes(data)

    result = validate_glb(path)

    assert result.sha256 == sha256_file(path)
    assert result.file_size_bytes == len(data)


@pytest.mark.parametrize("payload", [b"", b"nope", b"glTF" + b"\x00" * 4])
def test_truncated_or_non_glb_content_is_rejected(payload: bytes) -> None:
    _expect_invalid(payload)


def test_bad_magic_version_and_length_are_rejected() -> None:
    data = bytearray(build_glb_bytes())
    struct.pack_into("<I", data, 0, 0x12345678)
    _expect_invalid(bytes(data))

    data = bytearray(build_glb_bytes())
    struct.pack_into("<I", data, 4, 3)
    _expect_invalid(bytes(data))

    data = bytearray(build_glb_bytes())
    struct.pack_into("<I", data, 8, len(data) + 4)
    _expect_invalid(bytes(data))


def test_missing_color_0_is_rejected() -> None:
    _expect_invalid(build_glb_bytes(include_colors=False))


def test_non_finite_positions_are_rejected() -> None:
    positions = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [np.nan, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    _expect_invalid(build_glb_bytes(positions=positions))


def test_out_of_range_indices_are_rejected() -> None:
    indices = np.array([0, 1, 2, 0, 1, 99], dtype=np.uint16)
    _expect_invalid(build_glb_bytes(indices=indices))


def test_degenerate_bounding_box_is_rejected() -> None:
    positions = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
        dtype=np.float32,
    )
    _expect_invalid(build_glb_bytes(positions=positions))


def test_an_external_buffer_is_rejected() -> None:
    document, binary, _ = _split(build_glb_bytes())
    document["buffers"][0]["uri"] = "model.bin"
    _expect_invalid(_rebuild(document, binary))


def test_missing_mesh_or_scene_is_rejected() -> None:
    document, binary, _ = _split(build_glb_bytes())
    document["meshes"] = []
    _expect_invalid(_rebuild(document, binary))

    document, binary, _ = _split(build_glb_bytes())
    document["scenes"] = []
    _expect_invalid(_rebuild(document, binary))


def test_missing_primitive_attributes_are_rejected() -> None:
    document, binary, _ = _split(build_glb_bytes())
    document["meshes"][0]["primitives"][0]["attributes"] = {}
    _expect_invalid(_rebuild(document, binary))


def test_a_material_index_must_resolve() -> None:
    document, binary, _ = _split(build_glb_bytes())
    document["meshes"][0]["primitives"][0]["material"] = 3
    _expect_invalid(_rebuild(document, binary))


# -- increment 14: normals, UVs, PBR and embedded images --------------------


def test_normals_are_validated_when_present() -> None:
    result = validate_glb_bytes(build_glb_bytes(include_normals=True))
    assert result.has_normals is True

    zero = np.zeros((4, 3), dtype=np.float32)
    _expect_invalid(build_glb_bytes(include_normals=True, normals=zero))

    nan = np.full((4, 3), np.nan, dtype=np.float32)
    _expect_invalid(build_glb_bytes(include_normals=True, normals=nan))


def test_a_legacy_vertex_colour_asset_without_normals_still_passes() -> None:
    result = validate_glb_bytes(build_glb_bytes(include_normals=False))
    assert result.has_normals is False
    assert "vertex-colour asset has no NORMAL attribute" in result.warnings


def _export_textured(tmp_path: Path) -> tuple[dict, bytes]:
    from object_generation.exporter import export_glb
    from tests.helpers import textured_box

    path = tmp_path / "textured.glb"
    export_glb(textured_box(), path)
    return _split(path.read_bytes())


def test_a_textured_primitive_requires_texture_coordinates(tmp_path: Path) -> None:
    document, binary, _ = _export_textured(tmp_path)
    del document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
    _expect_invalid(_rebuild(document, binary))


def test_metallic_roughness_factors_must_be_in_range(tmp_path: Path) -> None:
    document, binary, _ = _export_textured(tmp_path)
    document["materials"][0]["pbrMetallicRoughness"]["metallicFactor"] = 2.0
    _expect_invalid(_rebuild(document, binary))

    document, binary, _ = _export_textured(tmp_path)
    document["materials"][0]["pbrMetallicRoughness"]["roughnessFactor"] = -0.5
    _expect_invalid(_rebuild(document, binary))


def test_a_texture_image_must_be_embedded_and_readable(tmp_path: Path) -> None:
    document, binary, _ = _export_textured(tmp_path)
    document["images"][0]["uri"] = "sidecar.png"
    _expect_invalid(_rebuild(document, binary))

    document, binary, _ = _export_textured(tmp_path)
    # Point the image bufferView at an empty range.
    document["bufferViews"][document["images"][0]["bufferView"]]["byteLength"] = 0
    _expect_invalid(_rebuild(document, binary))


def test_an_emissive_texture_requires_a_valid_reference(tmp_path: Path) -> None:
    document, binary, _ = _export_textured(tmp_path)
    document["materials"][0]["emissiveTexture"] = {"index": 99}
    _expect_invalid(_rebuild(document, binary))
