"""Opt-in real Splatfacto integration test (increment 15 Section 10.2).

Runs the real pinned Nerfstudio/gsplat stack on a validated COLMAP model:
dataset conversion → short standard Splatfacto training → checkpoint → Gaussian
PLY export → independent validation. It is skipped unless
``RUN_SPLAT_REAL_TESTS=1`` and a retained workspace is provided:

    docker run --rm --gpus all \
      -v "${PWD}/.proof:/proof" mogen-splat-worker:dev \
      env RUN_SPLAT_REAL_TESTS=1 SPLAT_REAL_WORKSPACE=/proof/scene-check-iq \
      SPLAT_REAL_ITERATIONS=100 /opt/venv/bin/python -m pytest \
      /opt/scene_reconstruction/tests/test_real_splat.py -m real_splat -q

The workspace must contain ``colmap/dense/sparse`` (undistorted model) and
``colmap/dense/images`` (undistorted images) from a validated reconstruction.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from scene_reconstruction.config import SceneConfig
from scene_reconstruction.dataset import PreparedImage, SceneDataset
from scene_reconstruction.neural_pipeline import NeuralReconstructor, build_splat_manifest
from scene_reconstruction.splat_config import SplatConfig
from scene_reconstruction.splat_validator import validate_splat_ply

pytestmark = [pytest.mark.integration, pytest.mark.real_splat]

ENABLED = os.environ.get("RUN_SPLAT_REAL_TESTS") == "1"
WORKSPACE = Path(os.environ.get("SPLAT_REAL_WORKSPACE", "/proof/scene-check-iq"))
ITERATIONS = int(os.environ.get("SPLAT_REAL_ITERATIONS", "100"))
MAX_DIMENSION = int(os.environ.get("SPLAT_REAL_MAX_DIMENSION", "640"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset(images_dir: Path) -> SceneDataset:
    prepared = []
    for path in sorted(images_dir.iterdir()):
        if not path.is_file():
            continue
        with Image.open(path) as image:
            width, height = image.size
            image_format = (image.format or "JPEG").upper()
        prepared.append(
            PreparedImage(
                path=path,
                filename=path.name,
                original_filename=path.name,
                image_id=path.stem,
                sha256=_sha256(path),
                size_bytes=path.stat().st_size,
                format=image_format,
                width=width,
                height=height,
            )
        )
    return SceneDataset(work_dir=WORKSPACE, images_dir=images_dir, images=tuple(prepared))


@pytest.mark.skipif(not ENABLED, reason="set RUN_SPLAT_REAL_TESTS=1 to run real Splatfacto")
def test_real_splatfacto_trains_and_exports_a_valid_ply(tmp_path: Path) -> None:
    assert WORKSPACE.is_dir(), f"missing retained reconstruction workspace {WORKSPACE}"
    splat = SplatConfig(
        enabled=True,
        min_registered_images=3,
        max_iterations=ITERATIONS,
        checkpoint_interval=max(100, ITERATIONS),
        max_image_dimension=MAX_DIMENSION,
        sh_degree=3,
        device="cuda",
    )
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT",
        output_format="PLY",
        splat=splat,
        work_root=tmp_path,
        min_registered_images=3,
    )
    reconstructor = NeuralReconstructor(config)
    runtime = reconstructor.runtime_report()
    assert runtime.versions["kernel_executed"] is True

    dataset = _dataset(WORKSPACE / "colmap" / "dense" / "images")
    converted = reconstructor.prepare(
        dataset,
        model_dir=WORKSPACE / "colmap" / "dense" / "sparse",
        images_dir=WORKSPACE / "colmap" / "dense" / "images",
        work_dir=tmp_path,
        runtime=runtime,
    )
    assert converted.registered_images >= 3
    assert converted.convention.ok
    manifest = build_splat_manifest(dataset=converted, runtime=runtime, splat=splat)

    training = reconstructor.train(dataset=converted, work_dir=tmp_path, timeout=1800)
    assert training.checkpoint_path is not None and training.checkpoint_path.is_file()

    export = reconstructor.export(checkpoint_path=training.checkpoint_path, work_dir=tmp_path)
    assert export.gaussian_count > 0
    validation = validate_splat_ply(
        export.path, sh_degree=3, max_artifact_bytes=splat.max_artifact_bytes
    )
    assert validation.gaussian_count == export.gaussian_count
    assert validation.sha256 == export.sha256
    assert validation.sh_degree == 3

    artifact = reconstructor.build_artifact(
        export=export,
        dataset=converted,
        training=training,
        runtime=runtime,
        vram=reconstructor.check_vram(),
        work_dir=tmp_path,
        expected_manifest=manifest,
    )
    metadata = artifact.metadata
    assert metadata["representation"] == "GAUSSIAN_SPLAT"
    assert metadata["artifact"]["gaussian_count"] == export.gaussian_count
    assert str(tmp_path) not in json.dumps(metadata)
