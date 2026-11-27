"""Mesh validation and GLB export tests (06 Sections 9-12)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import trimesh

from object_generation.exceptions import ExportError, MeshError
from object_generation.exporter import export_glb
from object_generation.mesh_processor import validate_mesh
from object_generation.validator import validate_glb
from tests.helpers import colored_box


def test_validate_mesh_returns_geometry_statistics() -> None:
    mesh = colored_box()

    stats = validate_mesh(mesh)

    assert stats.vertices_count == len(mesh.vertices)
    assert stats.faces_count == len(mesh.faces)
    assert stats.bounding_box["width"] == pytest.approx(1.0)
    assert stats.bounding_box["height"] == pytest.approx(0.8)
    assert stats.bounding_box["depth"] == pytest.approx(0.6)
    assert stats.has_vertex_colors is True
    metadata = stats.as_metadata()
    assert metadata["meshes_count"] == 1
    assert metadata["vertices_count"] == stats.vertices_count


def test_validate_mesh_rejects_empty_and_invalid_geometry() -> None:
    with pytest.raises(MeshError) as empty:
        validate_mesh(None)
    assert empty.value.error_code == "MESH_EXTRACTION_FAILED"

    with pytest.raises(MeshError) as no_faces:
        validate_mesh(
            trimesh.Trimesh(vertices=np.zeros((3, 3)), faces=np.zeros((0, 3)), process=False)
        )
    assert no_faces.value.error_code == "INVALID_MESH"

    nan_mesh = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [np.nan, 1, 0]], dtype=float),
        faces=np.array([[0, 1, 2]]),
        process=False,
    )
    with pytest.raises(MeshError) as non_finite:
        validate_mesh(nan_mesh)
    assert non_finite.value.error_code == "INVALID_MESH"

    flat = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
        faces=np.array([[0, 1, 2]]),
        process=False,
    )
    with pytest.raises(MeshError) as degenerate:
        validate_mesh(flat)
    assert degenerate.value.error_code == "INVALID_MESH"


def test_export_glb_produces_a_valid_self_contained_asset(tmp_path: Path) -> None:
    path = tmp_path / "model.glb"

    validation = export_glb(colored_box(), path)

    assert path.is_file()
    assert validation.file_size_bytes == path.stat().st_size
    assert validation.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert validation.has_vertex_colors is True
    assert validation.vertices_count > 0
    assert validation.faces_count > 0
    assert validate_glb(path).sha256 == validation.sha256


def test_export_rejects_a_mesh_without_any_appearance(tmp_path: Path) -> None:
    mesh = trimesh.creation.box(extents=(1, 1, 1))
    mesh.visual = trimesh.visual.texture.TextureVisuals()  # no colours, no texture
    path = tmp_path / "model.glb"

    with pytest.raises(ExportError) as excinfo:
        export_glb(mesh, path)

    # Increment 13 accepts a textured material as appearance, so the rejection
    # code is now generator-neutral; a mesh with neither appearance still fails.
    assert excinfo.value.error_code == "UNSUPPORTED_MESH_OUTPUT"
    assert not path.exists()


def test_export_removes_an_invalid_output(tmp_path: Path, monkeypatch) -> None:
    """An exporter that writes rubbish must not leave the rubbish behind."""
    path = tmp_path / "model.glb"

    def _bad_export(_self, _file, file_type=None):
        path.write_bytes(b"not a glb")
        return b"not a glb"

    monkeypatch.setattr(trimesh.Trimesh, "export", _bad_export)

    with pytest.raises(ExportError):
        export_glb(colored_box(), path)

    assert not path.exists()
