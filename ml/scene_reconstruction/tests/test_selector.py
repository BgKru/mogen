"""Sparse model inspection and selection (07 Sections 8.5-8.7)."""

from __future__ import annotations

import pytest

from scene_reconstruction.exceptions import (
    INSUFFICIENT_REGISTERED_IMAGES,
    INVALID_CAMERA_PARAMETERS,
    SPARSE_RECONSTRUCTION_FAILED,
    ReconstructionError,
)
from scene_reconstruction.reconstruction_selector import (
    inspect_model,
    parse_cameras,
    parse_images,
    parse_points,
    select_reconstruction,
)

from .helpers import default_config, write_sparse_model


def _images(count: int) -> list[tuple[int, float]]:
    return [(image_id, 0.5 + image_id * 0.1) for image_id in range(1, count + 1)]


def test_parses_cameras_images_and_points(tmp_path):
    text_dir = write_sparse_model(
        tmp_path / "0",
        camera_count=2,
        images=_images(3),
        points=[(1, 0.4, [1, 2, 3]), (2, 0.8, [1, 2])],
    )
    cameras, cameras_valid, _ = parse_cameras(text_dir / "cameras.txt")
    images, count, poses_valid, _ = parse_images(text_dir / "images.txt", cameras)
    points = parse_points(text_dir / "points3D.txt")

    assert cameras == {1: "SIMPLE_RADIAL", 2: "SIMPLE_RADIAL"}
    assert cameras_valid is True
    assert count == 3
    assert set(images) == {1, 2, 3}
    assert poses_valid is True
    assert points.points == 2
    assert points.mean_error == pytest.approx(0.6)
    assert (1, 2) in points.edges
    assert (1, 3) in points.edges


def test_detects_disconnected_components(tmp_path):
    text_dir = write_sparse_model(
        tmp_path / "0",
        images=_images(4),
        points=[(1, 0.2, [1, 2]), (2, 0.3, [3, 4])],
    )
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=4)
    assert candidate.components == 2
    assert candidate.largest_component == 2
    assert any("fragmented" in warning for warning in candidate.warnings)


def test_selects_the_most_registered_model_not_the_first_directory(tmp_path):
    small = write_sparse_model(tmp_path / "2", images=_images(3), points=[(1, 0.2, [1, 2, 3])])
    large = write_sparse_model(
        tmp_path / "10",
        images=_images(6),
        points=[(index, 0.2, [index, index + 1]) for index in range(1, 6)],
    )
    candidates = [
        inspect_model(tmp_path / "2", small, total_images=8),
        inspect_model(tmp_path / "10", large, total_images=8),
    ]
    selection = select_reconstruction(candidates, default_config(min_registration_ratio=0.5))
    assert selection.selected.model_dir.name == "10"
    assert selection.selected.registered_images == 6
    assert "selected model 10" in selection.reason
    assert len(selection.candidates) == 2


def test_rejects_too_few_registered_images(tmp_path):
    text_dir = write_sparse_model(tmp_path / "0", images=_images(2))
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=10)
    with pytest.raises(ReconstructionError) as exc:
        select_reconstruction([candidate], default_config(min_registered_images=3))
    assert exc.value.error_code == INSUFFICIENT_REGISTERED_IMAGES


def test_rejects_a_low_registration_ratio(tmp_path):
    text_dir = write_sparse_model(tmp_path / "0", images=_images(3))
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=10)
    with pytest.raises(ReconstructionError) as exc:
        select_reconstruction(
            [candidate],
            default_config(min_registered_images=1, min_registration_ratio=0.8),
        )
    assert exc.value.error_code == INSUFFICIENT_REGISTERED_IMAGES


def test_rejects_an_empty_point_cloud(tmp_path):
    text_dir = write_sparse_model(tmp_path / "0", images=_images(3), points=[])
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=3)
    with pytest.raises(ReconstructionError) as exc:
        select_reconstruction([candidate], default_config(min_sparse_points=10))
    assert exc.value.error_code == SPARSE_RECONSTRUCTION_FAILED


def test_rejects_invalid_camera_parameters(tmp_path):
    text_dir = write_sparse_model(tmp_path / "0", images=_images(3))
    (text_dir / "cameras.txt").write_text("1 SIMPLE_RADIAL 0 0 1500.0\n", encoding="utf-8")
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=3)
    assert candidate.cameras_valid is False
    with pytest.raises(ReconstructionError) as exc:
        select_reconstruction([candidate], default_config())
    assert exc.value.error_code == INVALID_CAMERA_PARAMETERS


def test_no_candidates_is_a_sparse_failure():
    with pytest.raises(ReconstructionError) as exc:
        select_reconstruction([], default_config())
    assert exc.value.error_code == SPARSE_RECONSTRUCTION_FAILED


def test_selection_metadata_is_json_safe(tmp_path):
    text_dir = write_sparse_model(tmp_path / "0", images=_images(3), points=[(1, 0.2, [1, 2, 3])])
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=3)
    metadata = candidate.as_metadata()
    assert metadata["model"] == "0"
    assert metadata["registered_images"] == 3
    assert isinstance(metadata["registration_ratio"], float)


def test_malformed_model_files_are_rejected(tmp_path):
    text_dir = write_sparse_model(tmp_path / "0", images=_images(2))
    (text_dir / "images.txt").write_text("garbage\n", encoding="utf-8")
    candidate = inspect_model(tmp_path / "0", text_dir, total_images=2)
    with pytest.raises(ReconstructionError) as exc:
        select_reconstruction([candidate], default_config())
    assert exc.value.error_code == SPARSE_RECONSTRUCTION_FAILED


def test_missing_model_file_is_a_stable_error(tmp_path):
    camera_dir = write_sparse_model(tmp_path / "0", images=_images(2))
    (camera_dir / "cameras.txt").unlink()
    with pytest.raises(ReconstructionError) as exc:
        inspect_model(tmp_path / "0", camera_dir, total_images=2)
    assert exc.value.error_code == SPARSE_RECONSTRUCTION_FAILED
