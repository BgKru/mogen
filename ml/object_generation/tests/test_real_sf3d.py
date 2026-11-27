"""Real Stable Fast 3D inference with the pinned weights (increment 13).

This test is opt-in because it loads the gated 3.84 GB checkpoint and runs a
full GPU inference:

    RUN_SF3D_REAL_TESTS=1 pytest tests/test_real_sf3d.py -m real_sf3d

It requires the populated, checksum-verified SF3D cache produced by
``python -m object_generation.sf3d.download_models``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from object_generation.config import ObjectGenerationConfig, SF3DConfig
from object_generation.pipeline import run_object_generation

pytestmark = [pytest.mark.real_sf3d, pytest.mark.slow, pytest.mark.ml]

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
MODEL_DIR = Path(os.environ.get("SF3D_TEST_MODEL_DIR", "/models/sf3d"))
MANIFEST = Path(os.environ.get("SF3D_TEST_MANIFEST", str(MODEL_DIR / "model-manifest.json")))
REVISION = os.environ.get("OBJECT_SF3D_MODEL_REVISION", "f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778")
DEVICE = os.environ.get("SF3D_TEST_DEVICE", "cuda:0")


def _config() -> ObjectGenerationConfig:
    return ObjectGenerationConfig(
        model_dir=Path(os.environ.get("TRIPOSR_MODEL_DIR", "/models/triposr")),
        model_revision=os.environ.get("OBJECT_MODEL_REVISION", "test"),
        model_sha256=os.environ.get("OBJECT_MODEL_SHA256", ""),
        device=DEVICE,
        allow_cpu_fallback=os.environ.get("OBJECT_ALLOW_CPU_FALLBACK", "false") == "true",
        foreground_ratio=float(os.environ.get("OBJECT_FOREGROUND_RATIO", "0.85")),
        max_task_seconds=int(os.environ.get("OBJECT_MAX_TASK_SECONDS", "1800")),
        generator="sf3d",
        sf3d=SF3DConfig(
            enabled=True,
            model_revision=REVISION,
            model_dir=MODEL_DIR,
            manifest_path=MANIFEST,
            texture_resolution=int(os.environ.get("OBJECT_SF3D_TEXTURE_RESOLUTION", "1024")),
            remesh=os.environ.get("OBJECT_SF3D_REMESH", "none"),
        ),
    )


@pytest.mark.skipif(
    os.environ.get("RUN_SF3D_REAL_TESTS") != "1",
    reason="set RUN_SF3D_REAL_TESTS=1 to execute the real SF3D inference",
)
def test_real_sf3d_inference_exports_a_valid_textured_glb(tmp_path: Path) -> None:
    image_path = TESTDATA / "car-1.jpg"
    assert image_path.is_file(), f"test photograph missing: {image_path}"

    asset = run_object_generation(
        image_bytes=image_path.read_bytes(),
        config=_config(),
        work_dir=tmp_path / "task",
    )

    assert asset.path.is_file()
    assert asset.file_size_bytes > 10_000
    assert asset.metadata["has_textures"] is True
    assert asset.metadata["textures_count"] >= 1
    assert asset.metadata["vertices_count"] > 1_000
    assert asset.metadata["faces_count"] > 1_000
    assert all(value > 0 for value in asset.metadata["bounding_box"].values())
    generator = asset.metadata["generator"]
    assert generator["name"] == "sf3d"
    assert generator["model_revision"] == REVISION

    # The same file must load in a general glTF library; the Three.js viewer
    # proof is a separate browser check, not a Python unit test.
    import trimesh

    scene = trimesh.load(asset.path, force="scene")
    geometries = list(scene.geometry.values())
    assert geometries, "the exported GLB contains no loadable geometry"
    assert any(geometry.visual.kind == "texture" for geometry in geometries)

    print("REAL_SF3D_PROOF", asset.metadata["generator"])


@pytest.mark.skipif(
    os.environ.get("RUN_SF3D_REAL_TESTS") != "1",
    reason="set RUN_SF3D_REAL_TESTS=1 to execute the real SF3D inference",
)
def test_two_sequential_sf3d_tasks_reuse_the_loaded_model(tmp_path: Path) -> None:
    config = _config()
    image_bytes = (TESTDATA / "car-2.jpg").read_bytes()

    first = run_object_generation(
        image_bytes=image_bytes, config=config, work_dir=tmp_path / "task-1"
    )
    second = run_object_generation(
        image_bytes=image_bytes, config=config, work_dir=tmp_path / "task-2"
    )

    assert first.path.is_file() and second.path.is_file()
    assert first.file_size_bytes > 10_000 and second.file_size_bytes > 10_000
    generator_blocks = [first.metadata["generator"], second.metadata["generator"]]
    # The second task reuses the process-wide model instead of loading it again.
    assert (
        generator_blocks[1]["diagnostics"]["load_seconds"]
        == generator_blocks[0]["diagnostics"]["load_seconds"]
    )
    assert all(item["has_textures"] for item in generator_blocks)
