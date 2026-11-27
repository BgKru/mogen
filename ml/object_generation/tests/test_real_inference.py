"""Real TripoSR inference with pretrained weights (TEST-AC-12, OBJ-AC-17).

This test is opt-in because it loads ~1.7 GB of weights and runs a full GPU
inference:

    RUN_REAL_MODEL_TESTS=1 pytest tests/test_real_inference.py -m real_model

It is executed once as the Phase 5 integration proof and kept in the repository
as the regression test required by 09_testing.md Section 10.3.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from object_generation.config import ObjectGenerationConfig
from object_generation.pipeline import run_object_generation

pytestmark = [pytest.mark.real_model, pytest.mark.slow, pytest.mark.ml]

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
MODEL_DIR = Path(os.environ.get("TRIPOSR_MODEL_DIR", "/models/triposr"))
DEVICE = os.environ.get("OBJECT_DEVICE", "cuda:0")


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_MODEL_TESTS") != "1",
    reason="set RUN_REAL_MODEL_TESTS=1 to execute the real TripoSR inference",
)
def test_real_triposr_inference_exports_a_valid_glb(tmp_path: Path) -> None:
    image_path = TESTDATA / "car-1.jpg"
    assert image_path.is_file(), f"test photograph missing: {image_path}"

    config = ObjectGenerationConfig(
        model_dir=MODEL_DIR,
        model_revision=os.environ.get("OBJECT_MODEL_REVISION", "test"),
        model_sha256=os.environ.get("OBJECT_MODEL_SHA256", ""),
        device=DEVICE,
        allow_cpu_fallback=os.environ.get("OBJECT_ALLOW_CPU_FALLBACK", "false") == "true",
        chunk_size=int(os.environ.get("OBJECT_CHUNK_SIZE", "8192")),
        mc_resolution=int(os.environ.get("OBJECT_MC_RESOLUTION", "256")),
        foreground_ratio=float(os.environ.get("OBJECT_FOREGROUND_RATIO", "0.85")),
        max_task_seconds=int(os.environ.get("OBJECT_MAX_TASK_SECONDS", "1800")),
    )

    asset = run_object_generation(
        image_bytes=image_path.read_bytes(),
        config=config,
        work_dir=tmp_path / "task",
    )

    assert asset.path.is_file()
    assert asset.file_size_bytes > 10_000
    assert asset.metadata["has_vertex_colors"] is True
    assert asset.metadata["vertices_count"] > 1_000
    assert asset.metadata["faces_count"] > 1_000
    assert all(value > 0 for value in asset.metadata["bounding_box"].values())

    # The same file must load in a general glTF library used by the viewer
    # integration, not only pass our structural validator.
    import trimesh

    scene = trimesh.load(asset.path, force="scene")
    geometries = list(scene.geometry.values())
    assert geometries, "the exported GLB contains no loadable geometry"
    assert any(len(geometry.vertices) > 0 for geometry in geometries)

    print(
        "REAL_TRIPOSR_PROOF",
        {
            "glb": str(asset.path),
            "sha256": asset.sha256,
            "size": asset.file_size_bytes,
            "vertices": asset.metadata["vertices_count"],
            "faces": asset.metadata["faces_count"],
            "bbox": asset.metadata["bounding_box"],
            "timing": asset.metadata["timing"],
        },
    )
