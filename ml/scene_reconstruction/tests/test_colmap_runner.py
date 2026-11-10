"""COLMAP runner failure mapping and user-safe messages (07 Sections 8.7, 17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scene_reconstruction.colmap_runner import ColmapRunner, StageOutcome
from scene_reconstruction.exceptions import (
    FEATURE_EXTRACTION_FAILED,
    INSUFFICIENT_REGISTERED_IMAGES,
    ReconstructionError,
)
from scene_reconstruction.runner import CommandOutcome

from .helpers import default_config


class _FakeRunner:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code
        self.calls: list[tuple[str, ...]] = []

    def run(self, command, *, cwd, timeout, log_path, on_poll=None) -> CommandOutcome:
        self.calls.append(tuple(command))
        Path(log_path).write_text("tool output\n", encoding="utf-8")
        return CommandOutcome(
            command=tuple(command),
            exit_code=self.exit_code,
            duration_seconds=0.1,
            log_path=Path(log_path),
        )


def test_sparse_failure_without_a_model_is_actionable(tmp_path):
    runner = _FakeRunner(exit_code=1)
    colmap = ColmapRunner(default_config(), runner=runner)  # type: ignore[arg-type]
    with pytest.raises(ReconstructionError) as exc:
        colmap.reconstruct_sparse(
            images_dir=tmp_path / "images",
            database_path=tmp_path / "database.db",
            sparse_dir=tmp_path / "sparse",
            log_path=tmp_path / "sparse.log",
        )

    assert exc.value.error_code == INSUFFICIENT_REGISTERED_IMAGES
    message = str(exc.value)
    assert "overlap" in message
    assert "exit code" not in message
    assert "1" not in message


def test_sparse_failure_with_a_model_is_accepted(tmp_path):
    sparse = tmp_path / "sparse"
    model = sparse / "0"
    model.mkdir(parents=True)
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        (model / name).write_bytes(b"model")

    runner = _FakeRunner(exit_code=1)
    colmap = ColmapRunner(default_config(), runner=runner)  # type: ignore[arg-type]
    outcome = colmap.reconstruct_sparse(
        images_dir=tmp_path / "images",
        database_path=tmp_path / "database.db",
        sparse_dir=sparse,
        log_path=tmp_path / "sparse.log",
    )

    assert isinstance(outcome, StageOutcome)
    assert outcome.model_dirs == (model,)


def test_feature_extraction_failure_hides_the_exit_code(tmp_path):
    runner = _FakeRunner(exit_code=2)
    colmap = ColmapRunner(default_config(), runner=runner)  # type: ignore[arg-type]
    with pytest.raises(ReconstructionError) as exc:
        colmap.extract_features(
            images_dir=tmp_path / "images",
            database_path=tmp_path / "database.db",
            log_path=tmp_path / "extract.log",
            expected_images=4,
        )

    assert exc.value.error_code == FEATURE_EXTRACTION_FAILED
    assert "exit code" not in str(exc.value)
