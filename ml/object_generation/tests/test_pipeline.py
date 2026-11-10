"""Pipeline orchestration with a fake model (no GPU required).

The real-model integration test lives in ``test_real_inference.py`` and is
gated by ``RUN_REAL_MODEL_TESTS=1`` (TEST-AC-12); these tests keep ordinary CI
fast and deterministic.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from object_generation.config import ObjectGenerationConfig
from object_generation.exceptions import InferenceError
from object_generation.generator import GeneratedMesh
from object_generation.mesh_processor import validate_mesh
from object_generation.pipeline import (
    STAGES,
    PipelineCallbacks,
    run_object_generation,
)
from PIL import Image

from tests.helpers import colored_box


def _config(tmp_path: Path, **overrides) -> ObjectGenerationConfig:
    values = {
        "model_dir": tmp_path / "model",
        "model_revision": "test",
        "model_sha256": "",
        "remove_background": False,
        "device": "cpu",
    }
    values.update(overrides)
    return ObjectGenerationConfig(**values)


def _png_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(120, 80, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeGenerator:
    def __init__(self, mesh=None) -> None:
        self._mesh = mesh or colored_box()

    def generate(self, image, *, started_at=None) -> GeneratedMesh:
        assert image.size == (512, 512)
        stats = validate_mesh(self._mesh)
        return GeneratedMesh(
            mesh=self._mesh,
            stats=stats,
            inference_seconds=0.01,
            extraction_seconds=0.02,
        )


class FailingGenerator:
    def generate(self, image, *, started_at=None):
        raise InferenceError("GPU_OUT_OF_MEMORY", "CUDA out of memory")


def test_the_pipeline_reports_real_stages_and_exports_a_validated_glb(
    tmp_path: Path,
) -> None:
    stages: list[str] = []
    heartbeats: list[int] = []
    original = _png_bytes()

    asset = run_object_generation(
        image_bytes=original,
        config=_config(tmp_path),
        work_dir=tmp_path / "task",
        callbacks=PipelineCallbacks(
            report_stage=lambda stage, _message: stages.append(stage),
            heartbeat=lambda: heartbeats.append(1),
        ),
        generator=FakeGenerator(),
    )

    assert stages == list(STAGES)
    assert len(heartbeats) >= len(STAGES)
    assert asset.path.is_file()
    assert asset.path.name == "model.glb"
    assert asset.format == "GLB"
    assert asset.mime_type == "model/gltf-binary"
    assert asset.file_size_bytes > 0
    assert len(asset.sha256) == 64
    assert asset.metadata["has_vertex_colors"] is True
    assert asset.metadata["vertices_count"] > 0
    assert asset.metadata["faces_count"] > 0
    assert asset.metadata["generation"]["bake_texture"] is False
    # The original upload is preserved byte-for-byte (OBJ-AC-05).
    assert (tmp_path / "task" / "input" / "original.png").read_bytes() == original
    assert (tmp_path / "task" / "input" / "preprocessed.png").is_file()
    assert (tmp_path / "task" / "run.json").is_file()


def test_a_preprocessing_failure_stops_before_inference(tmp_path: Path) -> None:
    stages: list[str] = []

    with pytest.raises(Exception) as excinfo:
        run_object_generation(
            image_bytes=b"not an image",
            config=_config(tmp_path),
            work_dir=tmp_path / "task",
            callbacks=PipelineCallbacks(report_stage=lambda stage, _message: stages.append(stage)),
            generator=FakeGenerator(),
        )

    assert excinfo.value.error_code == "IMAGE_DECODE_FAILED"
    assert stages == ["IMAGE_PREPARATION"]


def test_an_inference_failure_is_propagated_with_its_code(tmp_path: Path) -> None:
    with pytest.raises(InferenceError) as excinfo:
        run_object_generation(
            image_bytes=_png_bytes(),
            config=_config(tmp_path),
            work_dir=tmp_path / "task",
            generator=FailingGenerator(),
        )

    assert excinfo.value.error_code == "GPU_OUT_OF_MEMORY"
    assert (tmp_path / "task" / "run.json").is_file()


def test_cancellation_between_stages_stops_the_pipeline(tmp_path: Path) -> None:
    class Stop:
        def __call__(self) -> None:
            raise RuntimeError("stop requested")

    with pytest.raises(RuntimeError):
        run_object_generation(
            image_bytes=_png_bytes(),
            config=_config(tmp_path),
            work_dir=tmp_path / "task",
            callbacks=PipelineCallbacks(raise_if_cancelled=Stop()),
            generator=FakeGenerator(),
        )
