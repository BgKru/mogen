"""Real COLMAP/OpenMVS checks inside the worker image.

The toolchain check is part of the normal suite: SCENE-AC-01 requires the image
to detect its executables. The full reconstruction is opt-in because it is slow
and needs a real multi-view dataset:

    RUN_SCENE_RECONSTRUCTION_TEST=1 SCENE_TEST_IMAGES=/data/SceauxCastle \
        python -m pytest -m scene_binaries
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scene_reconstruction.config import SceneConfig
from scene_reconstruction.preflight import REQUIRED_TOOLS, verify_toolchain


def test_the_worker_image_contains_every_required_executable():
    report = verify_toolchain(SceneConfig())
    assert report.verified is True
    assert set(report.as_dict()) == set(REQUIRED_TOOLS)
    assert any("COLMAP" in version for version in report.as_dict().values())


@pytest.mark.scene_binaries
@pytest.mark.slow
def test_real_reconstruction_when_dataset_is_configured(tmp_path):
    if os.environ.get("RUN_SCENE_RECONSTRUCTION_TEST") != "1":
        pytest.skip("set RUN_SCENE_RECONSTRUCTION_TEST=1 with SCENE_TEST_IMAGES to run")
    directory = Path(os.environ.get("SCENE_TEST_IMAGES", ""))
    if not directory.is_dir():
        pytest.skip("SCENE_TEST_IMAGES does not point at a directory")
    images = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    assert len(images) >= 3, "the configured dataset needs at least three photographs"

    from scene_reconstruction.dataset import SourceImage
    from scene_reconstruction.pipeline import PhotogrammetryReconstructor

    config = SceneConfig(
        colmap_use_gpu=os.environ.get("SCENE_COLMAP_USE_GPU", "false") == "true",
        max_image_size=1600,
        min_registered_images=3,
        min_registration_ratio=0.4,
    )
    artifact = PhotogrammetryReconstructor(config).reconstruct(
        [SourceImage.from_path(path) for path in images],
        work_dir=tmp_path / "real",
        min_images=3,
    )
    assert artifact.path.is_file()
    assert artifact.file_size_bytes > 0
    assert artifact.metadata["vertices_count"] > 0
